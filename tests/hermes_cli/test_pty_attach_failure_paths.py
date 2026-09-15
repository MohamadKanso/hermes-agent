"""Regression coverage for PTY attach failure paths."""

import asyncio

import pytest

from hermes_cli.pty_session import PtySession


class FakeWS:
    def __init__(self):
        self.closed = False

    async def send_bytes(self, data):
        return None

    async def close(self, code=1000):
        self.closed = True


class RedrawBridge:
    def __init__(self, *, hold=False, fail=True):
        self.entered = asyncio.Event()
        self.release = asyncio.Event()
        self.hold = hold
        self.fail = fail

    async def write(self, data):
        self.entered.set()
        if self.hold:
            await self.release.wait()
        if self.fail:
            raise RuntimeError("redraw failed")
        return True

    def close(self):
        return None


@pytest.mark.asyncio
async def test_redraw_exception_detaches_current_socket():
    session = PtySession("k", RedrawBridge(), buffer_cap=1024, read_timeout=0.01)
    ws = FakeWS()

    assert await session.attach(ws, force_redraw=True) is False
    assert session.attached is False
    assert session._ws is None
    assert session.last_detached_at is not None


@pytest.mark.asyncio
async def test_late_redraw_exception_does_not_detach_replacement():
    bridge = RedrawBridge(hold=True)
    session = PtySession("k", bridge, buffer_cap=1024, read_timeout=0.01)
    stale = FakeWS()

    pending = asyncio.create_task(session.attach(stale, force_redraw=True))
    await asyncio.wait_for(bridge.entered.wait(), timeout=1)

    replacement = FakeWS()
    assert await session.attach(replacement) is True

    bridge.release.set()
    assert await asyncio.wait_for(pending, timeout=1) is False
    assert session._ws is replacement
    assert session.attached is True
    assert session.last_detached_at is None
