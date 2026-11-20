"""A Desktop-owned ``serve --isolated`` backend over SSH must retire itself once no client has been
connected for the grace window and no turn is running (#101626): it is detached from any parent on
purpose, so the client count IS its liveness signal."""

import threading
from types import SimpleNamespace

import pytest
from fastapi import FastAPI, WebSocket
from starlette.testclient import TestClient

import hermes_cli.web_server as ws_mod
from hermes_cli.backend_retirement import RetirementFence
from hermes_cli.web_server_idle_exit import (
    IdleClientTracker, should_exit_idle, start_idle_watchdog, wrap_asgi_with_ws_tracking)


def test_ws_sessions_are_counted_at_the_asgi_boundary_for_any_route():
    app = FastAPI()

    @app.websocket("/api/anything")
    async def anything(ws: WebSocket):
        await ws.accept()
        await ws.receive_text()
        await ws.close()

    @app.websocket("/api/refused")
    async def refused(ws: WebSocket):
        await ws.close(code=4401)  # never accepted: must not count

    tracker = IdleClientTracker(now=lambda: 0.0)
    client = TestClient(wrap_asgi_with_ws_tracking(app, tracker))
    with client.websocket_connect("/api/anything") as a:
        with client.websocket_connect("/api/anything") as b:
            assert tracker.live_count() == 2
            b.send_text("bye")
        assert tracker.live_count() == 1
        a.send_text("bye")
    assert tracker.live_count() == 0
    try:
        with client.websocket_connect("/api/refused"):
            pass
    except Exception:
        pass
    assert tracker.live_count() == 0  # a refused (never accepted) upgrade is not a client


def test_exit_only_after_grace_with_no_client_and_no_running_turn():
    clock = {"t": 0.0}
    tracker = IdleClientTracker(now=lambda: clock["t"])
    grace = 900.0
    assert should_exit_idle(tracker, grace, probe=lambda: False) is False  # just started
    clock["t"] = 901.0
    assert should_exit_idle(tracker, grace, probe=lambda: False) is True
    assert should_exit_idle(tracker, grace, probe=lambda: True) is False   # turn running
    assert should_exit_idle(tracker, grace, probe=lambda: None) is False   # indeterminate: fail closed
    tracker.on_open()
    clock["t"] = 5000.0
    assert should_exit_idle(tracker, grace, probe=lambda: False) is False  # a client is connected
    assert should_exit_idle(tracker, 0.0, probe=lambda: False) is False
    tracker.on_close()
    assert should_exit_idle(tracker, grace, probe=lambda: False) is False  # grace restarts on close
    clock["t"] = 5000.0 + grace + 1
    assert should_exit_idle(tracker, grace, probe=lambda: False) is True


def test_watchdog_sets_should_exit_and_only_arms_for_ssh_isolated_backends(monkeypatch):
    class _Server:
        should_exit = False

    server = _Server()
    clock = iter([0.0, 0.0, 10_000.0, 10_000.0, 10_000.0, 10_000.0])
    tracker = IdleClientTracker(now=lambda: next(clock, 10_000.0))
    start_idle_watchdog(server, tracker, grace_s=1.0, poll_s=0.01, probe=lambda: False,
                        fence=RetirementFence()).join(timeout=5)
    assert server.should_exit is True

    # The uvicorn builder wraps the app + arms tunnel pings ONLY when a session token was handed over.
    monkeypatch.setattr(ws_mod.app.state, "auth_required", False, raising=False)
    plain, _ = ws_mod._build_uvicorn_server("127.0.0.1", 0)
    assert plain.ws_ping_interval is None and getattr(ws_mod.app.state, "ssh_isolated_clients", None) is None
    assert plain.ws_per_message_deflate is False  # loopback: no per-frame zlib on the loop
    try:
        isolated, _ = ws_mod._build_uvicorn_server("127.0.0.1", 0, ssh_isolated=True)
        assert isolated.ws_ping_interval and isolated.ws_ping_timeout > isolated.ws_ping_interval
        assert isolated.ws_per_message_deflate is True  # the tunnelled client is remote
        assert isinstance(ws_mod.app.state.ssh_isolated_clients, IdleClientTracker)
    finally:
        ws_mod.app.state._state.pop("ssh_isolated_clients", None)  # process-global app: never leak the tracker


def test_turn_probe_counts_in_flight_cron_execution():
    """#107485: a cron job mid-run must keep the SSH-isolated backend alive; the run lives outside
    the dashboard session table, in the scheduler's running-job ledger."""
    from cron import scheduler
    from hermes_cli.web_server_idle_exit import turn_in_flight

    assert turn_in_flight() is False
    with scheduler._running_lock:
        scheduler._running_job_ids.add("idle-exit-probe-job")
    try:
        assert turn_in_flight() is True
    finally:
        with scheduler._running_lock:
            scheduler._running_job_ids.discard("idle-exit-probe-job")


@pytest.mark.platforms("posix")
def test_running_background_process_blocks_idle_exit_and_retirement(tmp_path, monkeypatch):
    from tools import process_registry as processes

    registry = processes.ProcessRegistry()
    monkeypatch.setattr(processes, "process_registry", registry)
    clock = [0.0]
    tracker = IdleClientTracker(now=lambda: clock[0])
    clock[0] = 901.0
    fence = RetirementFence()

    process = registry.spawn_local("exec sleep 60", cwd=str(tmp_path))
    try:
        assert should_exit_idle(tracker, 900.0) is False
        assert fence.prepare() == {"ok": False, "idle": False}
    finally:
        stopped = registry.kill_process(process.id)

    assert stopped["status"] == "killed"
    assert should_exit_idle(tracker, 900.0) is True
    assert fence.prepare()["idle"] is True


def test_retirement_waits_for_desktop_process_notice_to_be_routed(monkeypatch):
    from hermes_cli.web_server_idle_proof import idle_proof
    from tools import process_registry as processes
    from tools.process_registry_awaiting import release, take_ready
    from tui_gateway import server

    registry = processes.ProcessRegistry()
    monkeypatch.setattr(processes, "process_registry", registry)
    owner = "background-notice-owner"
    monkeypatch.setitem(server._sessions, "background-notice-session", {"session_key": owner})
    registry.completion_queue.put({"type": "completion", "owner_task_id": owner})

    assert idle_proof() == {"idle": False, "reason": "turn_in_flight", "detail": "process"}
    ready = take_ready(registry.completion_queue, 0)
    try:
        assert idle_proof()["idle"] is False
    finally:
        release(ready)
    assert idle_proof()["idle"] is True


def test_idle_watchdog_cannot_retire_during_process_notice_handoff():
    server = SimpleNamespace(should_exit=False)
    clock = [0.0]
    tracker = IdleClientTracker(now=lambda: clock[0])
    clock[0] = 901.0
    fence = RetirementFence()
    admitted = threading.Event()
    retried = threading.Event()

    def probe():
        # the process notice admits a new turn just as the first idle check returns
        if not admitted.is_set():
            if fence.acquire():
                admitted.set()
        else:
            retried.set()
        return False

    watcher = start_idle_watchdog(server, tracker, poll_s=0.01, probe=probe, fence=fence)
    try:
        assert retried.wait(5)
        assert not server.should_exit
    finally:
        if admitted.is_set():
            fence.release()
        watcher.join(timeout=5)
    assert server.should_exit


def test_idle_watchdog_cancels_retirement_if_client_reconnects(monkeypatch):
    from hermes_cli import web_server_idle_proof

    server = SimpleNamespace(should_exit=False)
    clock = [0.0]
    tracker = IdleClientTracker(now=lambda: clock[0])
    clock[0] = 901.0
    fence = RetirementFence()
    cancelled = threading.Event()
    original_cancel = fence.cancel

    def prove_idle():
        tracker.on_open()
        return {"idle": True}

    def cancel(token):
        result = original_cancel(token)
        cancelled.set()
        return result

    monkeypatch.setattr(web_server_idle_proof, "idle_proof", prove_idle)
    monkeypatch.setattr(fence, "cancel", cancel)
    watcher = start_idle_watchdog(server, tracker, poll_s=0.01, probe=lambda: False, fence=fence)
    try:
        assert cancelled.wait(5)
        assert not server.should_exit
        with fence.work() as admitted:
            assert admitted
    finally:
        server.should_exit = True
        watcher.join(timeout=5)
