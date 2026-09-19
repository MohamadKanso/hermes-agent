"""regression coverage for dead stdio children after the proof deadline."""

import asyncio
import sys
from types import SimpleNamespace
from unittest.mock import Mock

import pytest

from tools.mcp_tool import MCPServerTask
import tools.mcp_tool_server_run as run_mod


def _set_fake_psutil(monkeypatch, *, child_alive):
    monkeypatch.setitem(
        sys.modules,
        "psutil",
        SimpleNamespace(pid_exists=lambda _pid: child_alive),
    )


@pytest.mark.asyncio
async def test_dead_stdio_child_reconnects_after_proof_deadline(monkeypatch, caplog):
    """a dead child must leave the lifecycle loop on its first expired proof wake."""
    task = MCPServerTask("test-stdio-dead")
    task._config = {"command": "true"}
    task.session = object()
    task._stdio_child_pids = {12345}
    _set_fake_psutil(monkeypatch, child_alive=False)
    monkeypatch.setattr("tools.mcp_tool._DEFAULT_KEEPALIVE_INTERVAL", 0.0)

    failed = Mock()
    monkeypatch.setattr(task, "_fail_inflight_calls", failed)
    waits = 0

    async def fake_wait(waiters, timeout=None, return_when=None):
        nonlocal waits
        waits += 1
        if waits > 1:
            raise AssertionError("dead stdio proof must not spin")
        assert timeout == 0.0
        return set(), set(waiters)

    monkeypatch.setattr(run_mod.asyncio, "wait", fake_wait)

    with caplog.at_level("WARNING", logger="tools.mcp_tool"):
        reason = await asyncio.wait_for(task._wait_for_lifecycle_event(), timeout=1.0)

    assert reason == "reconnect"
    assert waits == 1
    failed.assert_called_once_with("reconnect")
    assert "exited before the session was proven" in caplog.text


@pytest.mark.asyncio
async def test_live_stdio_child_still_proves_after_proof_deadline(monkeypatch):
    """a live child keeps the existing proof path and does not reconnect."""
    task = MCPServerTask("test-stdio-live")
    task._config = {"command": "true"}
    task.session = object()
    task._stdio_child_pids = {12345}
    _set_fake_psutil(monkeypatch, child_alive=True)
    monkeypatch.setattr("tools.mcp_tool._DEFAULT_KEEPALIVE_INTERVAL", 0.0)

    real_wait = asyncio.wait
    waits = 0

    async def fake_wait(waiters, timeout=None, return_when=None):
        nonlocal waits
        waits += 1
        if waits == 1:
            assert timeout == 0.0
            return set(), set(waiters)
        task._shutdown_event.set()
        return await real_wait(
            waiters,
            timeout=1.0,
            return_when=return_when or asyncio.FIRST_COMPLETED,
        )

    monkeypatch.setattr(run_mod.asyncio, "wait", fake_wait)

    reason = await asyncio.wait_for(task._wait_for_lifecycle_event(), timeout=1.0)

    assert reason == "shutdown"
    assert waits == 2
    assert task._session_proven is True
