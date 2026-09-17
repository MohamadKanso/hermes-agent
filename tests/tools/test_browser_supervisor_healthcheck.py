"""Unit tests for _SupervisorRegistry cache-hit healthcheck.

Verifies that get_or_start() does NOT return a cached supervisor whose
thread has exited or whose event loop has stopped. Avoids a real Chrome —
the only thing under test is the registry's cache decision.
"""

from __future__ import annotations

import threading
from types import SimpleNamespace

import pytest

from tools import browser_supervisor as bs


class _FakeLoop:
    def __init__(self, running: bool) -> None:
        self._running = running

    def is_running(self) -> bool:
        return self._running


def _make_fake_supervisor(cdp_url: str, *, thread_alive: bool, loop_running: bool):
    """Build a minimal stand-in for a CDPSupervisor entry in the registry.

    Only the attributes touched by the healthcheck (_thread, _loop, cdp_url)
    and by the teardown path (stop()) need to exist.
    """

    if thread_alive:
        # A thread that is actually running — parks on an Event we never set.
        hold = threading.Event()
        t = threading.Thread(target=hold.wait, daemon=True)
        t.start()
        # Attach the release hook so the test can let the thread exit.
        setattr(t, "_release", hold.set)
    else:
        # An un-started thread — is_alive() returns False.
        t = threading.Thread(target=lambda: None)

    stop_calls: list[bool] = []

    fake = SimpleNamespace(
        cdp_url=cdp_url,
        _thread=t,
        _loop=_FakeLoop(loop_running),
        _stop_requested=False,
        stop=lambda: stop_calls.append(True),
    )
    fake._stop_calls = stop_calls  # type: ignore[attr-defined]
    return fake


@pytest.fixture
def isolated_registry():
    """A fresh registry instance, independent of the global SUPERVISOR_REGISTRY."""
    return bs._SupervisorRegistry()


@pytest.fixture
def stub_cdp_supervisor(monkeypatch):
    """Replace CDPSupervisor in the module so recreate paths don't touch Chrome.

    Returns a callable that reads the last-constructed fake out.
    """
    created: list[SimpleNamespace] = []

    class _StubSupervisor:
        def __init__(self, *, task_id, cdp_url, dialog_policy, dialog_timeout_s):
            self.task_id = task_id
            self.cdp_url = cdp_url
            self.dialog_policy = dialog_policy
            self.dialog_timeout_s = dialog_timeout_s
            # Healthy by default — real thread, running "loop".
            hold = threading.Event()
            self._thread = threading.Thread(target=hold.wait, daemon=True)
            self._thread.start()
            self._thread_release = hold.set  # type: ignore[attr-defined]
            self._loop = _FakeLoop(True)
            self.start_called = False
            self.stop_called = False
            created.append(self)

        def start(self, timeout: float = 15.0) -> None:
            self.start_called = True

        def stop(self) -> None:
            self.stop_called = True
            # Release the parked thread so the process exits cleanly.
            release = getattr(self, "_thread_release", None)
            if release is not None:
                release()

    monkeypatch.setattr(bs, "CDPSupervisor", _StubSupervisor)
    yield created
    # Teardown: release any parked threads in stubs the test left behind.
    for s in created:
        release = getattr(s, "_thread_release", None)
        if release is not None:
            release()


def test_cache_hit_returns_same_instance_when_healthy(
    isolated_registry, stub_cdp_supervisor
):
    """Sanity: healthy cached supervisor is returned without recreate."""
    first = isolated_registry.get_or_start(task_id="t1", cdp_url="http://h/1")
    second = isolated_registry.get_or_start(task_id="t1", cdp_url="http://h/1")
    assert first is second
    # Only one CDPSupervisor was ever constructed.
    assert len(stub_cdp_supervisor) == 1
    first.stop()


def test_missing_thread_and_loop_attrs_trigger_recreate(
    isolated_registry, stub_cdp_supervisor
):
    """Defensive: None _thread or None _loop counts as unhealthy."""
    cdp_url = "http://h/4"
    broken = SimpleNamespace(
        cdp_url=cdp_url,
        _thread=None,
        _loop=None,
        stop=lambda: None,
    )
    isolated_registry._by_task["t4"] = broken

    fresh = isolated_registry.get_or_start(task_id="t4", cdp_url=cdp_url)
    assert fresh is not broken
    assert isolated_registry._by_task["t4"] is fresh
    fresh.stop()


def test_get_drops_supervisor_that_exhausted_its_retry_budget(isolated_registry):
    stale = _make_fake_supervisor("http://h/5", thread_alive=True, loop_running=True)
    stale._stop_requested = True  # type: ignore[attr-defined]
    isolated_registry._by_task["t5"] = stale

    assert isolated_registry.get("t5") is None
    assert "t5" not in isolated_registry._by_task
    stale._thread._release()  # type: ignore[attr-defined]


def test_get_or_start_replaces_supervisor_that_is_already_stopping(
    isolated_registry, stub_cdp_supervisor
):
    stale = _make_fake_supervisor("http://h/6", thread_alive=True, loop_running=True)
    stale._stop_requested = True  # type: ignore[attr-defined]
    isolated_registry._by_task["t6"] = stale

    fresh = isolated_registry.get_or_start(task_id="t6", cdp_url="http://h/6")

    assert fresh is not stale
    assert stale._stop_calls == [True]  # type: ignore[attr-defined]
    fresh.stop()


def test_final_concurrent_guard_does_not_return_stopping_winner(
    isolated_registry, monkeypatch
):
    stale = _make_fake_supervisor("http://h/7", thread_alive=True, loop_running=True)
    stale._stop_requested = True  # type: ignore[attr-defined]
    created: list[SimpleNamespace] = []

    class _StubSupervisor:
        def __init__(self, *, task_id, cdp_url, dialog_policy, dialog_timeout_s):
            self.task_id = task_id
            self.cdp_url = cdp_url
            self.dialog_policy = dialog_policy
            self.dialog_timeout_s = dialog_timeout_s
            hold = threading.Event()
            self._thread = threading.Thread(target=hold.wait, daemon=True)
            self._thread.start()
            self._release = hold.set
            self._loop = _FakeLoop(True)
            self._stop_requested = False
            created.append(self)

        def start(self, timeout: float = 15.0) -> None:
            isolated_registry._by_task["t7"] = stale

        def stop(self) -> None:
            self._stop_requested = True
            self._release()

    monkeypatch.setattr(bs, "CDPSupervisor", _StubSupervisor)

    fresh = isolated_registry.get_or_start(task_id="t7", cdp_url="http://h/7")

    assert fresh is created[0]
    assert isolated_registry._by_task["t7"] is fresh
    assert stale._stop_calls == [True]  # type: ignore[attr-defined]
    fresh.stop()


def test_stop_cancels_supervisor_that_is_still_starting(isolated_registry, monkeypatch):
    created: list[SimpleNamespace] = []

    class _StubSupervisor:
        def __init__(self, *, task_id, cdp_url, dialog_policy, dialog_timeout_s):
            self.task_id = task_id
            self.cdp_url = cdp_url
            self.dialog_policy = dialog_policy
            self.dialog_timeout_s = dialog_timeout_s
            self.stop_called = False
            created.append(self)

        def start(self, timeout: float = 15.0) -> None:
            isolated_registry.stop("t8")

        def stop(self) -> None:
            self.stop_called = True

    monkeypatch.setattr(bs, "CDPSupervisor", _StubSupervisor)

    fresh = isolated_registry.get_or_start(task_id="t8", cdp_url="http://h/8")

    assert fresh is created[0]
    assert fresh.stop_called is True
    assert isolated_registry.get("t8") is None
    assert isolated_registry._starting == {}


def test_concurrent_starts_share_one_supervisor(isolated_registry, monkeypatch):
    created: list[SimpleNamespace] = []
    start_entered = threading.Event()
    release_start = threading.Event()
    thread_holds: list[threading.Event] = []

    class _StubSupervisor:
        def __init__(self, *, task_id, cdp_url, dialog_policy, dialog_timeout_s):
            self.task_id = task_id
            self.cdp_url = cdp_url
            self.dialog_policy = dialog_policy
            self.dialog_timeout_s = dialog_timeout_s
            self._stop_requested = False
            self._loop = _FakeLoop(True)
            hold = threading.Event()
            thread_holds.append(hold)
            self._thread = threading.Thread(target=hold.wait, daemon=True)
            self._thread.start()
            self.stop_called = False
            created.append(self)

        def start(self, timeout: float = 15.0) -> None:
            start_entered.set()
            assert release_start.wait(timeout=timeout)

        def stop(self) -> None:
            self.stop_called = True
            self._stop_requested = True
            release_start.set()
            thread_holds[-1].set()

    monkeypatch.setattr(bs, "CDPSupervisor", _StubSupervisor)
    results: list[object] = []

    def start_one() -> None:
        results.append(isolated_registry.get_or_start("t9", "http://h/9", start_timeout=2.0))

    first = threading.Thread(target=start_one)
    second = threading.Thread(target=start_one)
    first.start()
    assert start_entered.wait(timeout=1.0)
    second.start()
    release_start.set()
    first.join(timeout=2.0)
    second.join(timeout=2.0)

    assert not first.is_alive()
    assert not second.is_alive()
    assert len(created) == 1
    assert len(results) == 2
    assert results[0] is results[1]
    results[0].stop()  # type: ignore[attr-defined]


def test_stop_wakes_waiter_without_restarting(isolated_registry, monkeypatch):
    created: list[SimpleNamespace] = []
    start_entered = threading.Event()
    waiter_waiting = threading.Event()
    release_start = threading.Event()

    class _ObservedEvent:
        def __init__(self, event: threading.Event):
            self._event = event

        def wait(self, timeout=None):
            waiter_waiting.set()
            return self._event.wait(timeout)

        def set(self):
            self._event.set()

    class _ObservedStart:
        def __init__(self, done, generation=0):
            self.done = _ObservedEvent(done)
            self.cancelled = False
            self.generation = generation

    class _StubSupervisor:
        def __init__(self, *, task_id, cdp_url, dialog_policy, dialog_timeout_s):
            self.task_id = task_id
            self.cdp_url = cdp_url
            self.dialog_policy = dialog_policy
            self.dialog_timeout_s = dialog_timeout_s
            self._stop_requested = False
            self._loop = _FakeLoop(True)
            self._hold = threading.Event()
            self._thread = threading.Thread(target=self._hold.wait, daemon=True)
            self._thread.start()
            created.append(self)

        def start(self, timeout: float = 15.0) -> None:
            start_entered.set()
            assert release_start.wait(timeout=timeout)

        def stop(self) -> None:
            self._stop_requested = True
            self._hold.set()

    monkeypatch.setattr(bs, "CDPSupervisor", _StubSupervisor)
    monkeypatch.setattr(bs, "_SupervisorStart", _ObservedStart)
    results: list[object] = []
    errors: list[BaseException] = []

    def start_one() -> None:
        try:
            results.append(isolated_registry.get_or_start("t10", "http://h/10", start_timeout=2.0))
        except BaseException as exc:  # noqa: BLE001 - assert the cancellation type below
            errors.append(exc)

    first = threading.Thread(target=start_one)
    waiter = threading.Thread(target=start_one)
    first.start()
    assert start_entered.wait(timeout=1.0)
    waiter.start()
    assert waiter_waiting.wait(timeout=1.0)
    isolated_registry.stop("t10")
    release_start.set()
    first.join(timeout=2.0)
    waiter.join(timeout=2.0)

    assert not first.is_alive()
    assert not waiter.is_alive()
    assert len(created) == 1
    assert len(results) == 1
    assert len(errors) == 1
    assert isinstance(errors[0], RuntimeError)
    assert isolated_registry.get("t10") is None
    assert isolated_registry._starting == {}


def test_stop_after_publication_cancels_waiter(isolated_registry, monkeypatch):
    created: list[SimpleNamespace] = []
    start_entered = threading.Event()
    waiter_waiting = threading.Event()
    waiter_returned = threading.Event()
    release_start = threading.Event()
    release_recheck = threading.Event()

    class _ObservedEvent:
        def __init__(self, event: threading.Event):
            self._event = event

        def wait(self, timeout=None):
            waiter_waiting.set()
            result = self._event.wait(timeout)
            if result:
                waiter_returned.set()
                assert release_recheck.wait(timeout=1.0)
            return result

        def set(self):
            self._event.set()

    class _ObservedStart:
        def __init__(self, done, generation=0):
            self.done = _ObservedEvent(done)
            self.cancelled = False
            self.generation = generation

    class _StubSupervisor:
        def __init__(self, *, task_id, cdp_url, dialog_policy, dialog_timeout_s):
            self.task_id = task_id
            self.cdp_url = cdp_url
            self.dialog_policy = dialog_policy
            self.dialog_timeout_s = dialog_timeout_s
            self._stop_requested = False
            self._loop = _FakeLoop(True)
            self._hold = threading.Event()
            self._thread = threading.Thread(target=self._hold.wait, daemon=True)
            self._thread.start()
            created.append(self)

        def start(self, timeout: float = 15.0) -> None:
            start_entered.set()
            assert release_start.wait(timeout=timeout)

        def stop(self) -> None:
            self._stop_requested = True
            self._hold.set()

    monkeypatch.setattr(bs, "CDPSupervisor", _StubSupervisor)
    monkeypatch.setattr(bs, "_SupervisorStart", _ObservedStart)
    results: list[object] = []
    errors: list[BaseException] = []

    def start_one() -> None:
        try:
            results.append(isolated_registry.get_or_start("t11", "http://h/11", start_timeout=2.0))
        except BaseException as exc:  # noqa: BLE001 - assert the cancellation type below
            errors.append(exc)

    first = threading.Thread(target=start_one)
    waiter = threading.Thread(target=start_one)
    first.start()
    assert start_entered.wait(timeout=1.0)
    waiter.start()
    assert waiter_waiting.wait(timeout=1.0)
    release_start.set()
    assert waiter_returned.wait(timeout=1.0)
    isolated_registry.stop("t11")
    release_recheck.set()
    first.join(timeout=2.0)
    waiter.join(timeout=2.0)

    assert not first.is_alive()
    assert not waiter.is_alive()
    assert len(created) == 1
    assert len(results) == 1
    assert len(errors) == 1
    assert isinstance(errors[0], RuntimeError)
    assert isolated_registry.get("t11") is None
    assert isolated_registry._starting == {}
