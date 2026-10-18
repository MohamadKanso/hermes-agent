"""a lost progress-send acknowledgement must not create another bubble."""

from types import SimpleNamespace
from unittest.mock import AsyncMock

import pytest

from gateway.platforms.base import SendResult
from gateway.run_turn_progress import GatewayTurnProgressMixin


def _runner():
    return object.__new__(GatewayTurnProgressMixin)


def _state(*, message_id=None):
    return SimpleNamespace(
        adapter=SimpleNamespace(name="whatsapp"),
        progress_lines=["running a tool"],
        progress_msg_id=message_id,
        can_edit=True,
        delivery_unknown=False,
    )


class TestProgressDeliveryUnknown:
    @pytest.mark.asyncio
    async def test_unknown_edit_does_not_fall_back_to_a_new_progress_message(self):
        runner = _runner()
        runner._edit_progress_message = AsyncMock(return_value=SendResult(
            success=False,
            error="opaque failure",
            raw_response={"delivery_unknown": True},
        ))
        runner._send_progress_text = AsyncMock()
        state = _state(message_id="progress-1")

        assert await runner._progress_send_or_edit(state, "running a tool") is False

        assert state.delivery_unknown is True
        runner._send_progress_text.assert_not_awaited()

    @pytest.mark.asyncio
    async def test_unknown_first_progress_send_is_not_repeated(self):
        runner = _runner()
        runner._edit_progress_message = AsyncMock()
        runner._send_progress_text = AsyncMock(return_value=SendResult(
            success=False,
            error="opaque failure",
            raw_response={"delivery_unknown": True},
        ))
        state = _state()

        assert await runner._progress_send_or_edit(state, "running a tool") is False
        assert await runner._progress_send_or_edit(state, "running a tool") is False

        assert state.delivery_unknown is True
        runner._send_progress_text.assert_awaited_once()
        runner._edit_progress_message.assert_not_awaited()

    @pytest.mark.asyncio
    async def test_unknown_send_after_permanent_edit_failure_is_not_repeated(self):
        runner = _runner()
        runner._edit_progress_message = AsyncMock(return_value=SendResult(
            success=False,
            error="message not found",
        ))
        runner._send_progress_text = AsyncMock(return_value=SendResult(
            success=False,
            error="opaque failure",
            raw_response={"delivery_unknown": True},
        ))
        state = _state(message_id="progress-1")

        assert await runner._progress_send_or_edit(state, "running a tool") is True
        assert await runner._progress_send_or_edit(state, "running a tool") is False

        assert state.delivery_unknown is True
        runner._send_progress_text.assert_awaited_once()

    @pytest.mark.asyncio
    async def test_unknown_native_card_does_not_fall_back_to_text(self):
        runner = _runner()
        runner._ctx = SimpleNamespace(
            source=SimpleNamespace(chat_id="chat-1"),
            _progress_reply_to=None,
            _progress_metadata=None,
        )
        adapter = SimpleNamespace(send_native_task_card_progress=AsyncMock(return_value=SendResult(
            success=False,
            error="opaque failure",
            raw_response={"delivery_unknown": True},
        )))
        state = runner._TaskCardState(adapter=adapter)
        state._upsert("call-1", "search")
        runner._send_progress_text = AsyncMock()

        await runner._task_card_publish(state)

        assert state.publication_suppressed is True
        runner._send_progress_text.assert_not_awaited()

    @pytest.mark.asyncio
    async def test_unknown_fallback_edit_does_not_send_a_second_progress_bubble(self):
        runner = _runner()
        runner._ctx = SimpleNamespace(
            source=SimpleNamespace(chat_id="chat-1"),
            _progress_metadata=None,
        )
        adapter = SimpleNamespace(edit_message=AsyncMock(return_value=SendResult(
            success=False,
            error="opaque failure",
            raw_response={"delivery_unknown": True},
        )))
        state = runner._TaskCardState(adapter=adapter)
        state._upsert("call-1", "search")
        state.fallback_msg_id = "progress-1"
        runner._send_progress_text = AsyncMock()

        await runner._task_card_send_or_edit_fallback(state)

        assert state.publication_suppressed is True
        runner._send_progress_text.assert_not_awaited()
