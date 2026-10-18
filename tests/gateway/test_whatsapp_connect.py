"""Tests for WhatsApp connect() error handling.

Regression tests for two bugs in WhatsAppAdapter.connect():

1. Uninitialized ``data`` variable: when ``resp.json()`` raised after the
   health endpoint returned HTTP 200, ``http_ready`` was set to True but
   ``data`` was never assigned.  The subsequent ``data.get("status")``
   check raised ``NameError``.

2. Bridge log file handle leaked on error paths: the file was opened before
   the health-check loop but never closed when ``connect()`` returned False.
   Repeated connection failures accumulated open file descriptors.
"""

import asyncio
import json
import signal
import sys
import types
from pathlib import Path
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from gateway.config import Platform
from gateway.platforms.base import SendResult


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


@pytest.fixture(autouse=True)
def _pm_node(monkeypatch):
    """Stand-in for PM's Node/npm; the user's PATH copy is never picked up."""
    from plugins.platforms.whatsapp import adapter as whatsapp_adapter
    monkeypatch.setattr(whatsapp_adapter, "find_node_executable", lambda name: f"/pm/{name}")


def _make_adapter():
    """Create a WhatsAppAdapter with test attributes (bypass __init__)."""
    from plugins.platforms.whatsapp.adapter import WhatsAppAdapter

    adapter = WhatsAppAdapter.__new__(WhatsAppAdapter)
    adapter.platform = Platform.WHATSAPP
    adapter.config = MagicMock()
    adapter._bridge_port = 19876
    adapter._bridge_script = "/tmp/test-bridge.js"
    adapter._session_path = Path("/tmp/test-wa-session")
    adapter._bridge_log_fh = None
    adapter._bridge_log = None
    adapter._bridge_process = None
    adapter._reply_prefix = None
    adapter._send_read_receipts = False
    adapter._dm_policy = adapter._group_policy = "pairing"
    adapter._allow_from = adapter._group_allow_from = set()
    adapter._running = False
    adapter._message_handler = None
    adapter._fatal_error_code = None
    adapter._fatal_error_message = None
    adapter._fatal_error_retryable = True
    adapter._fatal_error_handler = None
    adapter._active_sessions = {}
    adapter._pending_messages = {}
    adapter._background_tasks = set()
    adapter._auto_tts_disabled_chats = set()
    adapter._message_queue = asyncio.Queue()
    adapter._http_session = None
    return adapter


def _connect_patches(mock_proc, mock_fh):
    """Return common patches needed to reach the health-check loop."""
    base = [
        patch("plugins.platforms.whatsapp.adapter.check_whatsapp_requirements", return_value=True),
        patch.object(Path, "exists", return_value=True),
        patch.object(Path, "mkdir", return_value=None),
        patch("subprocess.run", return_value=MagicMock(returncode=0)),
        patch("subprocess.Popen", return_value=mock_proc),
        patch("builtins.open", return_value=mock_fh),
        patch("plugins.platforms.whatsapp.adapter.asyncio.sleep", new_callable=AsyncMock),
        patch("plugins.platforms.whatsapp.adapter.asyncio.create_task"),
    ]
    return base


# ---------------------------------------------------------------------------
# _close_bridge_log() unit tests
# ---------------------------------------------------------------------------



# ---------------------------------------------------------------------------
# data variable initialization
# ---------------------------------------------------------------------------

class TestDataInitialized:
    """Verify an unparseable health response cannot leave polling state unbound."""

    @pytest.mark.asyncio
    async def test_no_name_error_when_json_always_fails(self):
        """HTTP 200 sets http_ready but json() always raises.

        Without the fix, ``data`` was never assigned and the Phase 2 check
        ``data.get("status")`` raised NameError.  With ``data = {}``, the
        check evaluates to ``None != "connected"`` and Phase 2 runs normally.
        """
        adapter = _make_adapter()

        mock_proc = MagicMock()
        mock_proc.poll.return_value = None  # bridge stays alive

        adapter._bridge_process = mock_proc

        # _probe_bridge_health normalizes an unparseable HTTP 200 body to
        # (True, None). Exercise the polling contract without requiring the
        # optional messaging transport in the base test environment.
        with patch.object(
            adapter,
            "_probe_bridge_health",
            new_callable=AsyncMock,
            return_value=(True, None),
        ), patch(
            "plugins.platforms.whatsapp.adapter.asyncio.sleep",
            new_callable=AsyncMock,
        ):
            result = await adapter._wait_for_bridge()

        # The bridge HTTP server is up, so timeout uses the warn-and-proceed path.
        assert result is True


# ---------------------------------------------------------------------------
# File handle cleanup on error paths
# ---------------------------------------------------------------------------

class TestFileHandleClosedOnError:
    """Verify the bridge log file handle is closed on every failure path."""

    @pytest.mark.asyncio
    async def test_closed_when_bridge_dies_phase1(self):
        """Bridge process exits during Phase 1 health-check loop."""
        adapter = _make_adapter()

        mock_proc = MagicMock()
        mock_proc.poll.return_value = 1  # dead immediately
        mock_proc.returncode = 1

        mock_fh = MagicMock()
        patches = _connect_patches(mock_proc, mock_fh)

        with patches[0], patches[1], patches[2], patches[3], patches[4], \
             patches[5], patches[6], patches[7]:
            result = await adapter.connect()

        assert result is False
        mock_fh.close.assert_called_once()
        assert adapter._bridge_log_fh is None


class TestConnectCleanup:
    """Verify failure paths release the scoped session lock."""

    @pytest.mark.asyncio
    async def test_releases_lock_when_npm_install_fails(self):
        adapter = _make_adapter()

        def _path_exists(path_obj):
            return not str(path_obj).endswith("node_modules")

        install_result = MagicMock(returncode=1, stderr="install failed")

        with patch("plugins.platforms.whatsapp.adapter.check_whatsapp_requirements", return_value=True), \
             patch.object(Path, "exists", autospec=True, side_effect=_path_exists), \
             patch("subprocess.run", return_value=install_result), \
             patch("gateway.status.acquire_scoped_lock", return_value=(True, None)), \
             patch("gateway.status_scoped_locks.release_scoped_lock") as mock_release:
            result = await adapter.connect()

        assert result is False
        assert adapter.fatal_error_code == "whatsapp_npm_install_failed"
        assert adapter.fatal_error_retryable is False
        mock_release.assert_called_once_with("whatsapp-session", str(adapter._session_path))
        assert adapter._platform_lock_identity is None


class TestBridgeRuntimeFailure:
    """Verify runtime bridge death is surfaced as a fatal adapter error."""

    @pytest.mark.asyncio
    async def test_send_marks_retryable_fatal_when_managed_bridge_exits(self):
        adapter = _make_adapter()
        fatal_handler = AsyncMock()
        adapter.set_fatal_error_handler(fatal_handler)
        adapter._running = True
        adapter._http_session = MagicMock()  # Persistent session active
        mock_fh = MagicMock()
        adapter._bridge_log_fh = mock_fh

        mock_proc = MagicMock()
        mock_proc.poll.return_value = 7
        adapter._bridge_process = mock_proc

        result = await adapter.send("chat-123", "hello")

        assert result.success is False
        assert adapter.fatal_error_code == "whatsapp_bridge_exited"
        assert adapter.fatal_error_retryable is True
        fatal_handler.assert_awaited_once()
        mock_fh.close.assert_called_once()
        assert adapter._bridge_log_fh is None

    @pytest.mark.asyncio
    @pytest.mark.parametrize("returncode", [-15, -2], ids=["sigterm", "sigint"])
    async def test_signal_exit_during_gateway_signal_shutdown_is_not_fatal(self, returncode):
        """A -15/-2 bridge exit races the stop flow: the signal handler flags the runner
        long before disconnect() flips ``_shutting_down`` (#127047)."""
        from types import SimpleNamespace

        adapter = _make_adapter()
        fatal_handler = AsyncMock()
        adapter.set_fatal_error_handler(fatal_handler)
        adapter._running = True
        adapter._shutting_down = False  # disconnect() has NOT run yet — this is the race
        adapter.gateway_runner = SimpleNamespace(_stop_requested_by_signal=True)
        adapter._bridge_log_fh = MagicMock()

        mock_proc = MagicMock()
        mock_proc.poll.return_value = returncode
        adapter._bridge_process = mock_proc

        assert await adapter._check_managed_bridge_exit() is None
        assert adapter.fatal_error_code is None
        fatal_handler.assert_not_awaited()

    @pytest.mark.asyncio
    async def test_sigterm_exit_without_gateway_shutdown_stays_fatal(self):
        """The runner flag must not mask a genuine crash: a bridge SIGTERMed while the
        gateway keeps running still queues the retryable reconnect."""
        from types import SimpleNamespace

        adapter = _make_adapter()
        fatal_handler = AsyncMock()
        adapter.set_fatal_error_handler(fatal_handler)
        adapter._running = True
        adapter._shutting_down = False
        adapter.gateway_runner = SimpleNamespace(_stop_requested_by_signal=False)
        adapter._bridge_log_fh = MagicMock()

        mock_proc = MagicMock()
        mock_proc.poll.return_value = -15
        adapter._bridge_process = mock_proc

        assert await adapter._check_managed_bridge_exit() is not None
        assert adapter.fatal_error_code == "whatsapp_bridge_exited"
        assert adapter.fatal_error_retryable is True
        fatal_handler.assert_awaited_once()

    @pytest.mark.asyncio
    async def test_send_normalizes_bare_phone_numbers_to_jid(self):
        """A bare phone target (with or without +) becomes a full JID.

        Baileys' jidDecode crashes on a bare number (#8637); the adapter
        must rewrite it to ``<digits>@s.whatsapp.net`` before the bridge
        call. Regression guard for that crash.
        """
        adapter = _make_adapter()
        adapter._running = True
        adapter._bridge_process = None  # unmanaged bridge — skip exit check

        adapter._http_session = MagicMock()

        with patch.object(
            adapter,
            "_post_bridge_message",
            new_callable=AsyncMock,
            return_value=SendResult(success=True, message_id="msg-1"),
        ) as mock_post:
            result = await adapter.send("+15551234567", "hello")

        assert result.success is True
        mock_post.assert_awaited_once_with(
            "send",
            {"chatId": "15551234567@s.whatsapp.net", "message": "hello"},
            timeout=65,
        )

    def test_bridge_request_timeout_covers_internal_bridge_chunks(self):
        adapter = _make_adapter()

        def scoped_value(name, default=""):
            return {
                "WHATSAPP_SEND_TIMEOUT_MS": "90000",
                "WHATSAPP_MAX_MESSAGE_LENGTH": "1000",
            }.get(name, default)

        with patch("plugins.platforms.whatsapp.adapter._wenv", side_effect=scoped_value):
            assert adapter._bridge_operation_timeout(15, "x" * 2000) == 190
            assert adapter._bridge_operation_timeout(15, "😀" * 1000) == 190

    def test_bridge_request_timeout_counts_self_chat_reply_prefix(self):
        adapter = _make_adapter()
        adapter._outgoing_chunk_limit = lambda: 4096
        adapter._reply_prefix = None

        def scoped_value(name, default=""):
            return {"WHATSAPP_SEND_TIMEOUT_MS": "60000", "WHATSAPP_MODE": "self-chat"}.get(name, default)

        with patch("plugins.platforms.whatsapp.adapter._wenv", side_effect=scoped_value):
            assert adapter._bridge_operation_timeout(15, "x" * 4094) == 65
            assert adapter._bridge_operation_timeout(15, "x" * 4094, include_reply_prefix=True) == 195

    def test_bridge_request_timeout_matches_whitespace_aware_splits(self):
        adapter = _make_adapter()
        content = ("😀" * 550 + "\n") * 7 + "😀" * 150
        assert len(content) == 4007
        assert len(content) <= adapter._outgoing_chunk_limit()

        def scoped_value(name, default=""):
            return {
                "WHATSAPP_SEND_TIMEOUT_MS": "60000",
                "WHATSAPP_MODE": "self-chat",
                "WHATSAPP_MAX_MESSAGE_LENGTH": "2000",
            }.get(name, default)

        with patch("plugins.platforms.whatsapp.adapter._wenv", side_effect=scoped_value):
            assert adapter._bridge_operation_timeout(15, content, include_reply_prefix=True) == 455

    def test_bridge_request_timeout_uses_configured_bridge_chunk_limit(self):
        adapter = _make_adapter()
        adapter._outgoing_chunk_limit = lambda: 4096
        adapter._reply_prefix = None

        def scoped_value(name, default=""):
            return {
                "WHATSAPP_SEND_TIMEOUT_MS": "90000",
                "WHATSAPP_MODE": "self-chat",
                "WHATSAPP_MAX_MESSAGE_LENGTH": "2000",
                "WHATSAPP_REPLY_PREFIX": "p",
            }.get(name, default)

        with patch("plugins.platforms.whatsapp.adapter._wenv", side_effect=scoped_value):
            assert adapter._bridge_operation_timeout(15, "x" * 4096, include_reply_prefix=True) == 285

    @pytest.mark.asyncio
    async def test_send_counts_reconnecting_adapter_chunk_as_unattempted(self):
        adapter = _make_adapter()
        adapter._running = True
        adapter._bridge_process = None
        adapter._http_session = MagicMock()
        adapter.format_message = lambda text: text
        adapter.truncate_message = lambda _text, _limit: ["first", "second", "third"]
        adapter._outgoing_chunk_limit = lambda: 100
        results = [
            SendResult(
                success=True,
                message_id="sent-first",
                raw_response={"messageIds": ["sent-first"], "deliveredChunks": 1},
            ),
            SendResult(
                success=False,
                error="bridge reconnecting",
                retryable=True,
                raw_response={"connectionState": "reconnecting"},
            ),
        ]

        with patch("plugins.platforms.whatsapp.adapter.asyncio.sleep", new_callable=AsyncMock), \
             patch.object(adapter, "_post_bridge_message", new_callable=AsyncMock, side_effect=results):
            result = await adapter.send("+15551234567", "hello")

        assert result.retryable is False
        assert result.raw_response["partial_overflow"] is True
        assert result.raw_response["unattempted_chunks"] == 2

    @pytest.mark.asyncio
    @pytest.mark.parametrize(
        ("status", "connection_state", "expected_retryable"),
        [(503, "reconnecting", True), (503, "disconnected", False), (500, "reconnecting", False)],
    )
    async def test_send_result_is_retryable_only_during_bridge_reconnect(self, status, connection_state, expected_retryable):
        adapter = _make_adapter()
        payload = {"error": "Not connected to WhatsApp", "connectionState": connection_state}

        class Response:
            def __init__(self):
                self.status = status

            async def text(self):
                return json.dumps(payload)

        class ResponseContext:
            async def __aenter__(self):
                return Response()

            async def __aexit__(self, *_args):
                return False

        with patch.object(adapter, "_bridge_req", return_value=ResponseContext()):
            result = await adapter._post_bridge_message("send", {}, timeout=30)

        assert result.retryable is expected_retryable

    @pytest.mark.asyncio
    async def test_bridge_partial_failure_is_marked_for_base_delivery_guard(self):
        adapter = _make_adapter()
        payload = {
            "error": "bridge closed",
            "partial_overflow": True,
            "delivered_chunks": 1,
        }

        class Response:
            status = 500

            async def text(self):
                return json.dumps(payload)

        class ResponseContext:
            async def __aenter__(self):
                return Response()

            async def __aexit__(self, *_args):
                return False

        with patch.object(adapter, "_bridge_req", return_value=ResponseContext()):
            result = await adapter._post_bridge_message("send", {}, timeout=30)

        assert result.raw_response["partial_overflow"] is True
        assert result.raw_response["delivered_chunks"] == 1

    @pytest.mark.asyncio
    async def test_bridge_edit_partial_failure_keeps_prefix_and_continuation_id(self):
        adapter = _make_adapter()
        adapter._running = True
        adapter._http_session = MagicMock()
        payload = {
            "error": "bridge closed",
            "partial_overflow": True,
            "delivered_chunks": 2,
            "delivered_prefix": "visible part",
            "last_message_id": "continuation-1",
        }

        class Response:
            status = 500

            async def text(self):
                return json.dumps(payload)

        class ResponseContext:
            async def __aenter__(self):
                return Response()

            async def __aexit__(self, *_args):
                return False

        with patch.object(adapter, "_bridge_req", return_value=ResponseContext()):
            result = await adapter.edit_message("+15551234567", "original-1", "visible part plus tail")

        assert result.retryable is False
        assert result.message_id == "continuation-1"
        assert result.raw_response["delivered_prefix"] == "visible part"

    @pytest.mark.asyncio
    async def test_bridge_timeout_marks_delivery_as_unknown(self):
        adapter = _make_adapter()

        with patch.object(adapter, "_bridge_req", side_effect=TimeoutError()):
            result = await adapter._post_bridge_message("send", {}, timeout=30)

        assert "timed out" in result.error
        assert result.raw_response["delivery_unknown"] is True
        assert result.raw_response["ambiguous"] is True
        assert result.retryable is False

    @pytest.mark.asyncio
    async def test_bridge_response_read_failure_marks_delivery_as_unknown(self):
        adapter = _make_adapter()

        class Response:
            status = 200

            async def json(self):
                raise ConnectionResetError("connection reset while reading response")

        class ResponseContext:
            async def __aenter__(self):
                return Response()

            async def __aexit__(self, *_args):
                return False

        with patch.object(adapter, "_bridge_req", return_value=ResponseContext()):
            result = await adapter._post_bridge_message("send", {}, timeout=30)

        assert result.delivery_unknown is True
        assert result.retryable is False

    @pytest.mark.asyncio
    async def test_bridge_edit_response_read_failure_marks_delivery_as_unknown(self):
        adapter = _make_adapter()
        adapter._running = True
        adapter._http_session = MagicMock()

        class Response:
            status = 500

            async def text(self):
                raise ValueError("response body could not be decoded")

        class ResponseContext:
            async def __aenter__(self):
                return Response()

            async def __aexit__(self, *_args):
                return False

        with patch.object(adapter, "_bridge_req", return_value=ResponseContext()):
            result = await adapter.edit_message("+15551234567", "message-1", "final text")

        assert result.delivery_unknown is True
        assert result.retryable is False

    @pytest.mark.asyncio
    async def test_bridge_local_request_error_is_not_marked_delivery_unknown(self):
        adapter = _make_adapter()

        with patch.object(adapter, "_bridge_req", side_effect=TypeError("invalid local request")):
            result = await adapter._post_bridge_message("send", {}, timeout=30)

        assert result.delivery_unknown is False

    @pytest.mark.asyncio
    async def test_unknown_poll_delivery_does_not_fall_back_to_text_clarify(self):
        adapter = _make_adapter()
        adapter._running = True
        adapter._http_session = MagicMock()
        payload = {
            "error": "sendMessage timed out after 30s",
            "delivery_unknown": True,
            "ambiguous": True,
        }

        class Response:
            status = 400

            async def text(self):
                return json.dumps(payload)

        class ResponseContext:
            async def __aenter__(self):
                return Response()

            async def __aexit__(self, *_args):
                return False

        with patch.object(adapter, "_bridge_req", return_value=ResponseContext()), patch(
            "gateway.platforms.base.BasePlatformAdapter.send_clarify", new_callable=AsyncMock,
        ) as fallback:
            result = await adapter.send_clarify("+15551234567", "pick one", ["first", "second"], "clarify-1", "session-1")

        assert result.delivery_unknown is True
        fallback.assert_not_awaited()

    @pytest.mark.asyncio
    async def test_disconnected_poll_does_not_start_a_text_clarify_fallback(self):
        adapter = _make_adapter()
        adapter._running = True
        adapter._http_session = MagicMock()
        payload = {"error": "Not connected to WhatsApp", "connectionState": "disconnected"}

        class Response:
            status = 503

            async def text(self):
                return json.dumps(payload)

        class ResponseContext:
            async def __aenter__(self):
                return Response()

            async def __aexit__(self, *_args):
                return False

        with patch.object(adapter, "_bridge_req", return_value=ResponseContext()), patch(
            "gateway.platforms.base.BasePlatformAdapter.send_clarify", new_callable=AsyncMock,
        ) as fallback:
            result = await adapter.send_clarify("+15551234567", "pick one", ["first", "second"], "clarify-2", "session-2")

        assert result.raw_response["connectionState"] == "disconnected"
        fallback.assert_not_awaited()

    @pytest.mark.asyncio
    async def test_send_preserves_reconnect_retry_verdict(self):
        adapter = _make_adapter()
        adapter._running = True
        adapter._bridge_process = None
        adapter._http_session = MagicMock()
        adapter.format_message = lambda text: text
        adapter.truncate_message = lambda text, _limit: [text]
        adapter._outgoing_chunk_limit = lambda: 100

        with patch.object(
            adapter,
            "_post_bridge_message",
            new_callable=AsyncMock,
            return_value=SendResult(success=False, error="bridge reconnecting", retryable=True),
        ):
            result = await adapter.send("+15551234567", "hello")

        assert result.success is False
        assert result.retryable is True

    @pytest.mark.asyncio
    async def test_send_does_not_retry_after_a_chunk_was_delivered(self):
        adapter = _make_adapter()
        adapter._running = True
        adapter._bridge_process = None
        adapter._http_session = MagicMock()
        adapter.format_message = lambda text: text
        adapter.truncate_message = lambda _text, _limit: ["first", "second"]
        adapter._outgoing_chunk_limit = lambda: 100
        results = [
            SendResult(
                success=True,
                message_id="sent-2",
                raw_response={"messageIds": ["sent-1", "sent-2"], "deliveredChunks": 2},
            ),
            SendResult(success=False, error="bridge reconnecting", retryable=True),
        ]

        with patch.object(adapter, "_post_bridge_message", new_callable=AsyncMock, side_effect=results):
            result = await adapter.send("+15551234567", "hello")

        assert result.success is False
        assert result.retryable is False
        assert result.raw_response["partial_overflow"] is True
        assert result.raw_response["delivered_chunks"] == 2
        assert result.raw_response["delivered_message_ids"] == ["sent-1", "sent-2"]

    @pytest.mark.asyncio
    async def test_unknown_first_chunk_marks_later_chunks_unattempted(self):
        adapter = _make_adapter()
        adapter._running = True
        adapter._bridge_process = None
        adapter._http_session = MagicMock()
        adapter.format_message = lambda text: text
        adapter.truncate_message = lambda _text, _limit: ["first", "second"]
        adapter._outgoing_chunk_limit = lambda: 100

        unknown = SendResult(
            success=False,
            error="send acknowledgement lost",
            raw_response={
                "delivery_unknown": True,
                "ambiguous": True,
                "delivered_message_ids": ["bridge-partial-1", "bridge-partial-2"],
                "delivered_prefix": "known prefix",
            },
        )
        with patch.object(adapter, "_post_bridge_message", new_callable=AsyncMock, return_value=unknown):
            result = await adapter.send("+15551234567", "hello")

        assert result.retryable is False
        assert result.raw_response["partial_overflow"] is True
        assert result.raw_response["unattempted_chunks"] == 1
        assert result.raw_response["delivered_message_ids"] == ["bridge-partial-1", "bridge-partial-2"]

    @pytest.mark.asyncio
    async def test_base_does_not_retry_or_fallback_after_partial_delivery(self):
        adapter = _make_adapter()
        partial = SendResult(
            success=False,
            error="later chunk failed",
            raw_response={"partial_overflow": True, "delivered_chunks": 1},
        )
        adapter.send = AsyncMock(return_value=partial)
        adapter._send_plain_fallback = AsyncMock(return_value=SendResult(success=True))

        result = await adapter._send_with_retry("15551234567@s.whatsapp.net", "original", max_retries=2)

        assert result is partial
        adapter.send.assert_awaited_once()
        adapter._send_plain_fallback.assert_not_awaited()

    @pytest.mark.asyncio
    async def test_base_does_not_resend_partial_payload_after_transient_failure(self):
        adapter = _make_adapter()
        partial = SendResult(
            success=False,
            error="connection reset",
            raw_response={"partial_overflow": True, "delivered_chunks": 1},
            retryable=True,
        )
        adapter.send = AsyncMock(return_value=partial)
        adapter._send_plain_fallback = AsyncMock(return_value=SendResult(success=True))

        with patch("gateway.platforms.base.asyncio.sleep", new_callable=AsyncMock) as sleep:
            result = await adapter._send_with_retry(
                "15551234567@s.whatsapp.net", "original", max_retries=2, base_delay=0,
            )

        assert result is partial
        adapter.send.assert_awaited_once()
        adapter._send_plain_fallback.assert_not_awaited()
        sleep.assert_awaited_once()

    @pytest.mark.asyncio
    async def test_base_does_not_fallback_after_delivery_unknown_timeout(self):
        adapter = _make_adapter()
        timeout = SendResult(
            success=False,
            error="whatsapp bridge request timed out; delivery status is unknown",
            raw_response={"delivery_unknown": True},
        )
        adapter.send = AsyncMock(return_value=timeout)
        adapter._send_plain_fallback = AsyncMock(return_value=SendResult(success=True))

        result = await adapter._send_with_retry("15551234567@s.whatsapp.net", "original", max_retries=2)

        assert result is timeout
        adapter.send.assert_awaited_once()
        adapter._send_plain_fallback.assert_not_awaited()

    @pytest.mark.asyncio
    async def test_base_does_not_plain_fallback_when_bridge_is_disconnected(self):
        adapter = _make_adapter()
        disconnected = SendResult(
            success=False,
            error='{"error":"Not connected to WhatsApp","connectionState":"disconnected"}',
            raw_response={"error": "Not connected to WhatsApp", "connectionState": "disconnected"},
        )
        adapter.send = AsyncMock(return_value=disconnected)
        adapter._send_plain_fallback = AsyncMock(return_value=SendResult(success=True))

        result = await adapter._send_with_retry("15551234567@s.whatsapp.net", "original", max_retries=2)

        assert result is disconnected
        adapter.send.assert_awaited_once()
        adapter._send_plain_fallback.assert_not_awaited()


    @pytest.mark.asyncio
    async def test_closed_when_bridge_dies_phase2(self):
        """Bridge alive during Phase 1 but dies during Phase 2."""
        adapter = _make_adapter()

        # Phase 1 (15 iterations): alive.  Phase 2 (iteration 16): dead.
        call_count = [0]

        def poll_side_effect():
            call_count[0] += 1
            return None if call_count[0] <= 15 else 1

        mock_proc = MagicMock()
        mock_proc.poll.side_effect = poll_side_effect
        mock_proc.returncode = 1

        mock_fh = MagicMock()
        adapter._bridge_process = mock_proc
        adapter._bridge_log_fh = mock_fh

        # A healthy HTTP endpoint with status != connected exhausts Phase 1.
        # The managed bridge then dies on the first Phase 2 poll.
        with patch.object(
            adapter,
            "_probe_bridge_health",
            new_callable=AsyncMock,
            return_value=(True, {"status": "disconnected"}),
        ), patch(
            "plugins.platforms.whatsapp.adapter.asyncio.sleep",
            new_callable=AsyncMock,
        ):
            result = await adapter._wait_for_bridge()

        assert result is False
        mock_fh.close.assert_called_once()
        assert adapter._bridge_log_fh is None


# ---------------------------------------------------------------------------
# _kill_port_process() cross-platform tests
# ---------------------------------------------------------------------------

class TestKillPortProcess:
    """Verify _kill_port_process uses platform-appropriate commands."""

    @pytest.mark.platforms("windows")
    def test_uses_netstat_and_taskkill_on_windows(self):
        """``platforms("windows")``: netstat/taskkill are Windows binaries. The old
        ``_IS_WINDOWS`` patch selected this branch on Linux, where neither
        exists, so the mocked argv was the only thing under test."""
        from plugins.platforms.whatsapp.adapter import _kill_port_process

        netstat_output = (
            "  Proto  Local Address          Foreign Address        State           PID\n"
            "  TCP    0.0.0.0:3000           0.0.0.0:0              LISTENING       12345\n"
            "  TCP    0.0.0.0:3001           0.0.0.0:0              LISTENING       99999\n"
        )
        mock_netstat = MagicMock(stdout=netstat_output)
        mock_taskkill = MagicMock()

        def run_side_effect(cmd, **kwargs):
            if cmd[0] == "netstat":
                return mock_netstat
            if cmd[0] == "taskkill":
                return mock_taskkill
            return MagicMock()

        with patch("plugins.platforms.whatsapp.adapter.subprocess.run", side_effect=run_side_effect) as mock_run, \
             patch("plugins.platforms.whatsapp.adapter._pid_looks_like_node_bridge",
                   return_value=True):
            _kill_port_process(3000)

        # netstat called
        assert any(
            call.args[0][0] == "netstat" for call in mock_run.call_args_list
        )
        # taskkill called with correct PID
        assert any(
            call.args[0] == ["taskkill", "/PID", "12345", "/F"]
            for call in mock_run.call_args_list
        )

    @pytest.mark.platforms("windows")
    def test_windows_refuses_taskkill_on_non_bridge_pid(self):
        """#89614 class: the netstat-scanned PID is a bare number — if the
        live process is not a node bridge, taskkill must never fire."""
        from plugins.platforms.whatsapp.adapter import _kill_port_process

        netstat_output = (
            "  Proto  Local Address          Foreign Address        State           PID\n"
            "  TCP    0.0.0.0:3000           0.0.0.0:0              LISTENING       12345\n"
        )

        def run_side_effect(cmd, **kwargs):
            if cmd[0] == "netstat":
                return MagicMock(stdout=netstat_output)
            return MagicMock()

        with patch("plugins.platforms.whatsapp.adapter.subprocess.run", side_effect=run_side_effect) as mock_run, \
             patch("plugins.platforms.whatsapp.adapter._pid_looks_like_node_bridge",
                   return_value=False):
            _kill_port_process(3000)

        assert not any(
            call.args[0][0] == "taskkill" for call in mock_run.call_args_list
        )


    @pytest.mark.platforms("linux")
    def test_kills_only_listeners_on_linux(self):
        """POSIX path SIGTERMs only LISTENer PIDs (never clients) — the #43846 fix.

        Replaces the old fuser-based test: ``fuser``/bare ``lsof -i`` also
        matched client sockets sharing the port number, which closed unrelated
        processes (a browser tab on the same port). The implementation now
        resolves listeners via ``_listener_pids_on_port`` and signals only those.

        ``platforms("linux")``: asserts the POSIX ``os.kill``/SIGTERM path, which is
        genuinely selected here without patching ``_IS_WINDOWS``.
        """
        from plugins.platforms.whatsapp import adapter as wa

        kills = []
        with patch("plugins.platforms.whatsapp.adapter._listener_pids_on_port",
                   return_value=[55555]) as mock_listeners, \
             patch("plugins.platforms.whatsapp.adapter._pid_looks_like_node_bridge",
                   return_value=True), \
             patch("plugins.platforms.whatsapp.adapter.os.kill",
                   side_effect=lambda pid, sig: kills.append((pid, sig))):
            wa._kill_port_process(3000)

        mock_listeners.assert_called_once_with(3000)
        assert kills == [(55555, signal.SIGTERM)]

    @pytest.mark.platforms("linux")
    def test_non_bridge_listener_is_never_killed(self):
        """#89614 class: a listener that is not a node bridge is refused."""
        from plugins.platforms.whatsapp import adapter as wa

        kills = []
        with patch("plugins.platforms.whatsapp.adapter._listener_pids_on_port",
                   return_value=[55555]), \
             patch("plugins.platforms.whatsapp.adapter._pid_looks_like_node_bridge",
                   return_value=False), \
             patch("plugins.platforms.whatsapp.adapter.os.kill",
                   side_effect=lambda pid, sig: kills.append((pid, sig))):
            wa._kill_port_process(3000)

        assert kills == []


# ---------------------------------------------------------------------------
# Persistent HTTP session lifecycle
# ---------------------------------------------------------------------------

class TestHttpSessionLifecycle:
    """Verify persistent aiohttp.ClientSession is created and cleaned up."""

    @pytest.mark.asyncio
    @pytest.mark.platforms("windows")
    async def test_disconnect_uses_taskkill_tree_on_windows(self):
        """Windows disconnect should target the bridge process tree, not just the parent PID.

        ``platforms("windows")``: ``taskkill /T`` is the Windows tree-kill primitive;
        on Linux the branch was reachable only by faking ``_IS_WINDOWS``.
        """
        adapter = _make_adapter()
        mock_proc = MagicMock()
        mock_proc.pid = 12345
        mock_proc.poll.side_effect = [0]
        adapter._bridge_process = mock_proc
        adapter._poll_task = None
        adapter._http_session = None
        adapter._running = True
        adapter._session_lock_identity = None

        with patch("plugins.platforms.whatsapp.adapter.subprocess.run", return_value=MagicMock(returncode=0)) as mock_run, \
             patch("plugins.platforms.whatsapp.adapter.asyncio.sleep", new_callable=AsyncMock):
            await adapter.disconnect()

        mock_run.assert_called_once()
        assert mock_run.call_args.args[0] == ["taskkill", "/PID", "12345", "/T"]
        mock_proc.terminate.assert_not_called()
        mock_proc.kill.assert_not_called()

    @pytest.mark.asyncio
    async def test_session_closed_on_disconnect(self):
        """disconnect() should close self._http_session."""
        adapter = _make_adapter()
        mock_session = AsyncMock()
        mock_session.closed = False
        adapter._http_session = mock_session
        adapter._poll_task = None
        adapter._bridge_process = None
        adapter._running = True
        adapter._session_lock_identity = None

        await adapter.disconnect()

        mock_session.close.assert_called_once()
        assert adapter._http_session is None


# ---------------------------------------------------------------------------
# Pre-flight: refuse to start the bridge when creds.json is missing
# ---------------------------------------------------------------------------


class TestNoCredsPreflight:
    """Verify ``connect()`` fast-fails as non-retryable when WhatsApp is
    enabled but the user never finished pairing (no ``creds.json``).

    Without this guard, every gateway boot:
      • spawned the bridge subprocess (npm install if needed)
      • waited 30s for status:connected (never happens without creds)
      • queued WhatsApp for indefinite retries that would just repeat
    With the guard, ``connect()`` returns False immediately with a
    non-retryable fatal error so the reconnect watcher drops the platform
    and the gateway gets a single clear log line telling the user to run
    ``hermes whatsapp``.
    """


    @pytest.mark.asyncio
    async def test_connect_proceeds_when_creds_present(self, tmp_path):
        """When creds.json exists, the preflight check is bypassed and
        connect() proceeds to the bridge bootstrap path. We don't fully
        simulate the bridge here — we just verify no fast-fail occurs.
        """
        from plugins.platforms.whatsapp.adapter import WhatsAppAdapter

        adapter = WhatsAppAdapter.__new__(WhatsAppAdapter)
        adapter.platform = Platform.WHATSAPP
        adapter.config = MagicMock()
        adapter._bridge_port = 19877
        bridge = tmp_path / "bridge.js"
        bridge.write_text("// stub", encoding="utf-8")
        adapter._bridge_script = str(bridge)
        session_dir = tmp_path / "session"
        session_dir.mkdir()
        (session_dir / "creds.json").write_text("{}", encoding="utf-8")
        adapter._session_path = session_dir
        adapter._bridge_log_fh = None
        adapter._fatal_error_code = None
        adapter._fatal_error_message = None
        adapter._fatal_error_retryable = True
        # Stub _acquire_platform_lock to return False so connect() exits
        # cleanly *after* the preflight, without spawning subprocesses.
        adapter._acquire_platform_lock = MagicMock(return_value=False)

        with patch(
            "plugins.platforms.whatsapp.adapter.check_whatsapp_requirements",
            return_value=True,
        ):
            result = await adapter.connect()

        # Preflight passed — exits because we faked lock acquisition,
        # but the fatal-error code is NOT the "not paired" one.
        assert result is False
        assert adapter._fatal_error_code != "whatsapp_not_paired"


class TestNamedConnectFailures:
    """A failed connect names its cause; an unnamed False loops forever as an unclassified failure (#126358)."""

    @pytest.mark.asyncio
    @pytest.mark.parametrize("aiohttp_module, lazy_allowed, cause, retryable", [
        (None, False, "lazy installs are disabled", False),
        # Installed but this process could not adopt it: final would exit the gateway 78 instead of restarting.
        (None, True, "sms installed; restart Hermes to activate it", True),
        (types.ModuleType("aiohttp"), True, "incomplete install", False),  # a shadowing aiohttp.py has no __path__
    ])
    async def test_missing_aiohttp_is_named_and_final_only_when_pm_cannot_install(
            self, aiohttp_module, lazy_allowed, cause, retryable):
        from pm.package import InstallError

        adapter = _make_adapter()
        adapter._acquire_platform_lock = MagicMock(return_value=False)
        ensure_import = MagicMock(side_effect=InstallError("venv", cause))
        with patch("plugins.platforms.whatsapp.adapter.check_whatsapp_requirements", return_value=True), \
             patch.object(Path, "exists", return_value=True), patch.dict(sys.modules, {"aiohttp": aiohttp_module}), \
             patch("pm.extras.ensure_import", ensure_import), \
             patch("pm.install.lazy_installs_allowed", return_value=lazy_allowed), \
             patch("pm.environments.running_from_selected_environment", return_value=True):
            assert await adapter.connect() is False

        assert ensure_import.call_count == (aiohttp_module is None)
        adapter._acquire_platform_lock.assert_not_called()  # bridge never started
        assert adapter.fatal_error_code == "whatsapp_aiohttp_missing"
        assert adapter.fatal_error_retryable is retryable
        assert cause in adapter.fatal_error_message

    @pytest.mark.asyncio
    async def test_bridge_http_timeout_is_a_named_retryable_failure(self):
        adapter = _make_adapter()
        adapter._bridge_process = MagicMock(**{"poll.return_value": None})
        with patch.object(adapter, "_probe_bridge_health", new_callable=AsyncMock, side_effect=OSError("refused")), \
             patch("plugins.platforms.whatsapp.adapter.asyncio.sleep", new_callable=AsyncMock):
            assert await adapter._wait_for_bridge() is False

        assert adapter.fatal_error_code == "whatsapp_bridge_timeout"
        assert adapter.fatal_error_retryable is True
