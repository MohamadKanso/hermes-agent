"""gemini native client socket-abort discovery and stream response lifecycle tests (#150822)."""

from __future__ import annotations

import json
import socket as _socket
from types import SimpleNamespace
from typing import Any

import run_agent
from agent import chat_completion_helpers as helpers
from agent.agent_runtime_helpers import force_close_tcp_sockets
from agent.gemini_native_adapter import (
    AsyncGeminiNativeClient,
    GeminiNativeClient,
    GeminiStream,
)


class _FakeSocket:
    def __init__(self) -> None:
        self.shutdown_calls = 0
        self.close_calls = 0

    def shutdown(self, _how: Any) -> None:
        self.shutdown_calls += 1

    def close(self) -> None:
        self.close_calls += 1


def _fake_http_client(sock: _FakeSocket) -> SimpleNamespace:
    network_stream = SimpleNamespace(_sock=sock)
    http11 = SimpleNamespace(_network_stream=network_stream)
    pool = SimpleNamespace(_connections=[http11])
    transport = SimpleNamespace(_pool=pool)
    return SimpleNamespace(_transport=transport, _mounts={}, close=lambda: None)


def test_gemini_native_client_pool_socket_discovery() -> None:
    sock = _FakeSocket()
    http_client = _fake_http_client(sock)
    client = GeminiNativeClient(api_key="AQ.test", http_client=http_client)

    assert force_close_tcp_sockets(client) == 1
    assert sock.shutdown_calls == 1
    assert sock.close_calls == 0

    async_client = AsyncGeminiNativeClient(client)
    assert force_close_tcp_sockets(async_client) == 1
    assert sock.shutdown_calls == 2


def test_gemini_native_stream_response_lifecycle() -> None:
    observed_responses: list[Any] = []

    class _MockResponse:
        status_code = 200

        def __enter__(self) -> _MockResponse:
            return self

        def __exit__(self, *exc: object) -> bool:
            return False

        def iter_text(self) -> list[str]:
            cand = {"content": {"role": "model", "parts": [{"text": "hello"}]}}
            event = {"candidates": [cand]}
            return [f"data: {json.dumps(event)}\n\n"]

    mock_resp = _MockResponse()

    class _MockHTTP:
        def stream(self, *args: Any, **kwargs: Any) -> _MockResponse:
            return mock_resp

        def close(self) -> None:
            pass

    client = GeminiNativeClient(api_key="AQ.test", http_client=_MockHTTP())
    stream = client.chat.completions.create(
        model="gemini-2.5-flash",
        messages=[{"role": "user", "content": "hi"}],
        stream=True,
    )
    assert isinstance(stream, GeminiStream)
    assert stream.response is None

    stream.on_response(lambda r: observed_responses.append(r))

    chunks = list(stream)
    assert len(chunks) == 1
    assert chunks[0].choices[0].delta.content == "hello"

    # response was set to mock_resp during streaming, and cleared to None in finally
    assert observed_responses == [mock_resp, None]
    assert stream.response is None


def test_gemini_native_stream_cancelled_stops_continuation() -> None:
    calls = []

    class _MockResponse:
        status_code = 200

        def __enter__(self) -> _MockResponse:
            return self

        def __exit__(self, *exc: object) -> bool:
            return False

        def iter_text(self) -> list[str]:
            cand = {"content": {"role": "model", "parts": [{"text": "hop1"}]}}
            event = {"candidates": [cand], "continuationToken": "token-1"}
            return [f"data: {json.dumps(event)}\n\n"]

    class _MockHTTP:
        def stream(self, method: str, url: str, json: Any = None, **kwargs: Any) -> _MockResponse:
            calls.append(json)
            return _MockResponse()

        def close(self) -> None:
            pass

    client = GeminiNativeClient(api_key="AQ.test", http_client=_MockHTTP())
    stream = client.chat.completions.create(
        model="gemini-4-argon",
        messages=[{"role": "user", "content": "hi"}],
        stream=True,
    )

    it = iter(stream)
    chunk = next(it)
    assert chunk.choices[0].delta.content == "hop1"
    assert len(calls) == 1

    # cancel mid-stream
    stream.cancel()
    # next should terminate without making a second call for continuationToken
    assert list(it) == []
    assert len(calls) == 1


def test_streaming_call_late_connect_gemini_reabort(monkeypatch: Any) -> None:
    reader, writer = _socket.socketpair()
    try:
        def _no_close():
            raise AssertionError("stranger thread must never close response")

        h11_conn = SimpleNamespace(
            _network_stream=SimpleNamespace(_sock=reader),
            _stream=None,
            _connection=None,
            _httpcore_stream=None,
        )
        pool_stream = SimpleNamespace(
            _stream=SimpleNamespace(_connection=h11_conn),
            _connection=None,
        )
        live_resp = SimpleNamespace(
            close=_no_close,
            stream=SimpleNamespace(_stream=SimpleNamespace(_httpcore_stream=pool_stream)),
        )

        agent = run_agent.AIAgent(
            api_key="test-key",
            base_url="https://generativelanguage.googleapis.com/v1beta",
            model="gemini-2.5-flash",
            provider="gemini",
            quiet_mode=True,
            skip_context_files=True,
            skip_memory=True,
            enabled_toolsets=[],
            max_iterations=1,
        )
        call = helpers._StreamingCall(agent, {"model": "gemini-2.5-flash", "messages": [{"role": "user", "content": "hi"}]}, None)

        raw_stream = SimpleNamespace()
        callbacks = []
        raw_stream.on_response = lambda cb: callbacks.append(cb)
        raw_stream.cancelled = False
        raw_stream.cancel = lambda: setattr(raw_stream, "cancelled", True)

        # mark call cancelled while connecting (late connect race)
        call._request_cancelled["value"] = True

        call._chat_stream_created(raw_stream)
        assert len(callbacks) == 1

        # when hop response arrives, on_response fires and triggers _reabort_if_cancelled
        callbacks[0](live_resp)

        assert raw_stream.cancelled is True
        writer.settimeout(5)
        assert writer.recv(1) == b"", "the late socket was not shut down"
    finally:
        reader.close()
        writer.close()
