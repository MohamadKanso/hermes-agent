"""Unit tests for the browser supervisor reconnect budget."""

from __future__ import annotations

import asyncio
from types import SimpleNamespace

import pytest
import websockets

from tools import browser_supervisor


async def _noop(*_args, **_kwargs) -> None:
    return None


def test_reconnect_failures_stop_after_a_time_budget(monkeypatch, caplog):
    supervisor = browser_supervisor.CDPSupervisor("task-1", "ws://127.0.0.1:9222/devtools")
    attempts = 0
    clock = 0.0

    class FakeWebSocket:
        async def close(self):
            return None

    async def connect(*_args, **_kwargs):
        nonlocal attempts
        attempts += 1
        if attempts == 1:
            return FakeWebSocket()
        raise ConnectionRefusedError("browser is gone")

    async def advance_clock(_delay: float) -> None:
        nonlocal clock
        clock += 1.0

    monkeypatch.setattr(browser_supervisor, "_MAX_RECONNECT_SECONDS", 3.0)
    monkeypatch.setattr(browser_supervisor, "time", SimpleNamespace(monotonic=lambda: clock))
    monkeypatch.setattr(websockets, "connect", connect)
    monkeypatch.setattr(supervisor, "_attach_initial_page", _noop)
    monkeypatch.setattr(supervisor, "_read_loop", _noop)
    monkeypatch.setattr(browser_supervisor.asyncio, "sleep", advance_clock)

    with caplog.at_level("WARNING"):
        asyncio.run(supervisor._run())

    assert attempts == 3
    assert supervisor._stop_requested is True
    assert sum("stopping after" in record.message for record in caplog.records) == 1


@pytest.mark.asyncio
async def test_successful_attach_resets_reconnect_window(monkeypatch, caplog):
    supervisor = browser_supervisor.CDPSupervisor("task-refresh", "ws://127.0.0.1:9222/devtools")
    attempts = 0
    successful_sessions = 0
    clock = 0.0

    class FakeWebSocket:
        async def close(self):
            return None

    async def connect(*_args, **_kwargs):
        nonlocal attempts, successful_sessions
        attempts += 1
        if successful_sessions == 2:
            raise ConnectionRefusedError("browser is gone")
        successful_sessions += 1
        return FakeWebSocket()

    async def advance_clock(_delay: float) -> None:
        nonlocal clock
        clock += 2.0

    monkeypatch.setattr(browser_supervisor, "_MAX_RECONNECT_SECONDS", 3.0)
    monkeypatch.setattr(browser_supervisor, "time", SimpleNamespace(monotonic=lambda: clock))
    monkeypatch.setattr(websockets, "connect", connect)
    monkeypatch.setattr(supervisor, "_attach_initial_page", _noop)
    monkeypatch.setattr(supervisor, "_read_loop", _noop)
    monkeypatch.setattr(browser_supervisor.asyncio, "sleep", advance_clock)

    with caplog.at_level("WARNING"):
        await supervisor._run()

    assert attempts == 3
    assert supervisor._stop_requested is True
    assert sum("stopping after" in record.message for record in caplog.records) == 1


@pytest.mark.asyncio
async def test_attach_failures_obey_reconnect_window(monkeypatch, caplog):
    supervisor = browser_supervisor.CDPSupervisor("task-attach", "ws://127.0.0.1:9222/devtools")
    attempts = 0
    attach_attempts = 0
    clock = 0.0

    class FakeWebSocket:
        async def close(self):
            return None

    async def connect(*_args, **_kwargs):
        nonlocal attempts
        attempts += 1
        return FakeWebSocket()

    async def attach():
        nonlocal attach_attempts
        attach_attempts += 1
        if attach_attempts > 1:
            raise ConnectionError("CDP commands are no longer responding")

    async def advance_clock(_delay: float) -> None:
        nonlocal clock
        clock += 1.0

    monkeypatch.setattr(browser_supervisor, "_MAX_RECONNECT_SECONDS", 3.0)
    monkeypatch.setattr(browser_supervisor, "time", SimpleNamespace(monotonic=lambda: clock))
    monkeypatch.setattr(websockets, "connect", connect)
    monkeypatch.setattr(supervisor, "_attach_initial_page", attach)
    monkeypatch.setattr(supervisor, "_read_loop", _noop)
    monkeypatch.setattr(browser_supervisor.asyncio, "sleep", advance_clock)

    with caplog.at_level("WARNING"):
        await supervisor._run()

    assert attempts == 3
    assert supervisor._stop_requested is True
    assert sum("stopping after" in record.message for record in caplog.records) == 1


@pytest.mark.asyncio
async def test_slow_attach_cannot_refresh_an_expired_window(monkeypatch, caplog):
    supervisor = browser_supervisor.CDPSupervisor("task-slow-attach", "ws://127.0.0.1:9222/devtools")
    attempts = 0
    clock = 0.0

    class FakeWebSocket:
        async def close(self):
            return None

    async def connect(*_args, **_kwargs):
        nonlocal attempts
        attempts += 1
        return FakeWebSocket()

    async def attach():
        nonlocal clock
        if attempts > 1:
            clock += 4.0

    async def no_sleep(_delay: float) -> None:
        return None

    monkeypatch.setattr(browser_supervisor, "_MAX_RECONNECT_SECONDS", 3.0)
    monkeypatch.setattr(browser_supervisor, "time", SimpleNamespace(monotonic=lambda: clock))
    monkeypatch.setattr(websockets, "connect", connect)
    monkeypatch.setattr(supervisor, "_attach_initial_page", attach)
    monkeypatch.setattr(supervisor, "_read_loop", _noop)
    monkeypatch.setattr(browser_supervisor.asyncio, "sleep", no_sleep)

    with caplog.at_level("WARNING"):
        await supervisor._run()

    assert attempts == 2
    assert supervisor._stop_requested is True
    assert sum("stopping after" in record.message for record in caplog.records) == 1


@pytest.mark.asyncio
async def test_fast_session_drops_keep_reconnecting(monkeypatch, caplog):
    supervisor = browser_supervisor.CDPSupervisor("task-2", "ws://127.0.0.1:9222/devtools")
    attempts = 0
    clock = 0.0

    class FakeWebSocket:
        async def close(self):
            return None

    async def connect(*_args, **_kwargs):
        nonlocal attempts
        attempts += 1
        if attempts <= 3:
            return FakeWebSocket()
        raise ConnectionRefusedError("browser is gone")

    async def advance_clock(_delay: float) -> None:
        nonlocal clock
        clock += 1.0

    monkeypatch.setattr(browser_supervisor, "_MAX_RECONNECT_SECONDS", 10.0)
    monkeypatch.setattr(browser_supervisor, "time", SimpleNamespace(monotonic=lambda: clock))
    monkeypatch.setattr(websockets, "connect", connect)
    monkeypatch.setattr(supervisor, "_attach_initial_page", _noop)
    monkeypatch.setattr(supervisor, "_read_loop", _noop)
    monkeypatch.setattr(browser_supervisor.asyncio, "sleep", advance_clock)

    with caplog.at_level("WARNING"):
        await supervisor._run()

    assert attempts == 12
    assert supervisor._stop_requested is True
    assert sum("stopping after" in record.message for record in caplog.records) == 1
