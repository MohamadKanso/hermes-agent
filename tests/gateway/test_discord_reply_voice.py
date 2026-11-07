"""regression tests for typed replies to discord bot voice messages (issue #150824)

when a user sends a typed reply to the bot's own voice note or audio attachment,
the turn must retain its own message type (text), bot-originated audio must not
enter media_urls where it gets transcribed as human speech via stt, and clearly
labeled context must be injected into the event text without dead network i/o.
"""

from datetime import datetime, UTC
import re
import sys
from types import SimpleNamespace
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from gateway.config import PlatformConfig
from gateway.platforms.event import MessageType


def _ensure_discord_mock():
    """install a mock discord module when discord.py is not available."""
    if "discord" in sys.modules and hasattr(sys.modules["discord"], "__file__"):
        return

    discord_mod = MagicMock()
    discord_mod.Intents.default.return_value = MagicMock()
    discord_mod.Client = MagicMock
    discord_mod.File = MagicMock
    discord_mod.DMChannel = type("DMChannel", (), {})
    discord_mod.Thread = type("Thread", (), {})
    discord_mod.ForumChannel = type("ForumChannel", (), {})
    discord_mod.ui = SimpleNamespace(
        View=object,
        button=lambda *a, **k: (lambda fn: fn),
        Button=object,
    )
    discord_mod.ButtonStyle = SimpleNamespace(
        success=1, primary=2, secondary=2, danger=3, green=1, grey=2, blurple=2, red=3
    )
    discord_mod.Color = SimpleNamespace(
        orange=lambda: 1, green=lambda: 2, blue=lambda: 3, red=lambda: 4, purple=lambda: 5
    )
    discord_mod.Interaction = object
    discord_mod.Embed = MagicMock
    discord_mod.app_commands = SimpleNamespace(
        describe=lambda **kwargs: (lambda fn: fn),
        choices=lambda **kwargs: (lambda fn: fn),
        Choice=lambda **kwargs: SimpleNamespace(**kwargs),
    )

    ext_mod = MagicMock()
    commands_mod = MagicMock()
    commands_mod.Bot = MagicMock
    ext_mod.commands = commands_mod

    sys.modules.setdefault("discord", discord_mod)
    sys.modules.setdefault("discord.ext", ext_mod)
    sys.modules.setdefault("discord.ext.commands", commands_mod)


_ensure_discord_mock()

from plugins.platforms.discord.adapter import DiscordAdapter


try:
    import discord as _discord_lib
    _DMChannelBase = _discord_lib.DMChannel
except (ImportError, AttributeError):
    _DMChannelBase = object


class FakeDMChannel(_DMChannelBase):
    """minimal dm channel stub."""

    def __init__(self, channel_id: int = 100, name: str = "dm"):
        self.id = channel_id
        self.name = name


def _make_attachment(
    *,
    filename: str = "voice-message.ogg",
    content_type: str = "audio/ogg",
    is_voice: bool = True,
    url: str = "https://cdn.discordapp.com/attachments/1/2/voice-message.ogg",
):
    """build an attachment mock with optional voice message markers."""
    att = SimpleNamespace(
        filename=filename,
        content_type=content_type,
        size=1024,
        url=url,
        is_voice_message=lambda: is_voice,
        duration=3.5 if is_voice else None,
        waveform=b"fake-waveform" if is_voice else None,
        read=AsyncMock(return_value=b"fake-audio-bytes"),
    )
    return att


def _make_message(
    *,
    content: str = "what did you say",
    reference=None,
    attachments=None,
    user_id: int = 42,
    is_bot: bool = False,
):
    """build a mock discord message."""
    author = SimpleNamespace(id=user_id, display_name="testuser", name="testuser", bot=is_bot)
    return SimpleNamespace(
        id=1001,
        content=content,
        mentions=[],
        attachments=attachments or [],
        reference=reference,
        created_at=datetime.now(UTC),
        channel=FakeDMChannel(),
        author=author,
    )


@pytest.fixture
def discord_adapter(tmp_path, monkeypatch):
    """discord adapter wired for handle_message dispatch testing."""
    monkeypatch.setattr(
        "gateway.platforms.base.DOCUMENT_CACHE_DIR", tmp_path / "doc_cache"
    )
    config = PlatformConfig(enabled=True, token="fake-token")
    adapter = DiscordAdapter(config)
    adapter._client = SimpleNamespace(user=SimpleNamespace(id=999, bot=True))
    adapter._text_batch_delay_seconds = 0
    adapter.handle_message = AsyncMock()
    return adapter


class TestDiscordReplyVoiceBotAttribution:
    """regression tests verifying that replies to bot voice messages keep text type."""

    @pytest.mark.asyncio
    async def test_typed_reply_to_bot_voice_keeps_text_type_and_injects_context(
        self, discord_adapter
    ):
        """typed reply to bot voice note should be text, never voice, and skip download."""
        bot_voice_att = _make_attachment(
            filename="voice-message.ogg",
            content_type="audio/ogg",
            is_voice=True,
            url="https://cdn.discordapp.com/voice-message.ogg",
        )
        resolved_msg = SimpleNamespace(
            id=555,
            content="",
            attachments=[bot_voice_att],
            author=SimpleNamespace(id=999, bot=True, name="bot"),
        )
        ref = SimpleNamespace(message_id=555, resolved=resolved_msg)
        msg = _make_message(content="what did you say", reference=ref)

        with patch.object(
            discord_adapter, "_cache_simple_media", new_callable=AsyncMock
        ) as mock_cache:
            dispatched = await discord_adapter._handle_message(msg)
            # dead download avoided: no network/disk churn on bot audio reply
            mock_cache.assert_not_called()

        assert dispatched is True
        assert discord_adapter.handle_message.await_count == 1
        event = discord_adapter.handle_message.await_args.args[0]

        # message type must stay text, never retyped to voice
        assert event.message_type == MessageType.TEXT

        # media_urls must not contain the bot audio so stt never fires
        assert event.media_urls == []
        assert event.media_types == []

        # labeled context note must be injected alongside the user text
        assert "[Replied-to audio 'voice-message.ogg' sent by the bot]" in event.text
        assert "what did you say" in event.text

    @pytest.mark.asyncio
    async def test_typed_reply_to_bot_audio_file_keeps_text_type(
        self, discord_adapter
    ):
        """typed reply to bot plain audio upload should stay text, not retyped to audio."""
        bot_audio_att = _make_attachment(
            filename="track.mp3",
            content_type="audio/mpeg",
            is_voice=False,
            url="https://cdn.discordapp.com/track.mp3",
        )
        resolved_msg = SimpleNamespace(
            id=556,
            content="here is the song",
            attachments=[bot_audio_att],
            author=SimpleNamespace(id=999, bot=True, name="bot"),
        )
        ref = SimpleNamespace(message_id=556, resolved=resolved_msg)
        msg = _make_message(content="nice song", reference=ref)

        with patch.object(
            discord_adapter, "_cache_simple_media", new_callable=AsyncMock
        ) as mock_cache:
            await discord_adapter._handle_message(msg)
            mock_cache.assert_not_called()

        event = discord_adapter.handle_message.await_args.args[0]
        assert event.message_type == MessageType.TEXT
        assert event.media_urls == []
        assert "[Replied-to audio 'track.mp3' sent by the bot]" in event.text
        assert "nice song" in event.text

    @pytest.mark.asyncio
    async def test_typed_reply_to_human_voice_preserves_voice_type_and_stt(
        self, discord_adapter
    ):
        """typed reply to another human voice note retains voice type for transcription."""
        human_voice_att = _make_attachment(
            filename="voice-message.ogg",
            content_type="audio/ogg",
            is_voice=True,
            url="https://cdn.discordapp.com/human-voice.ogg",
        )
        resolved_msg = SimpleNamespace(
            id=557,
            content="",
            attachments=[human_voice_att],
            author=SimpleNamespace(id=123, bot=False, name="otherhuman"),
        )
        ref = SimpleNamespace(message_id=557, resolved=resolved_msg)
        msg = _make_message(content="transcribe this please", reference=ref)

        with patch.object(
            discord_adapter, "_cache_simple_media", new_callable=AsyncMock
        ) as mock_cache:
            mock_cache.return_value = "/tmp/cached/human-voice.ogg"
            await discord_adapter._handle_message(msg)

        event = discord_adapter.handle_message.await_args.args[0]
        # human voice note is eligible for stt transcription
        assert event.message_type == MessageType.VOICE
        assert event.media_urls == ["/tmp/cached/human-voice.ogg"]
        assert event.media_types == ["audio/ogg"]

    @pytest.mark.asyncio
    async def test_typed_reply_to_third_party_bot_voice_preserves_voice_type_and_stt(
        self, discord_adapter
    ):
        """typed reply to a third-party bot voice note preserves stt transcription."""
        third_party_voice_att = _make_attachment(
            filename="voice-message.ogg",
            content_type="audio/ogg",
            is_voice=True,
            url="https://cdn.discordapp.com/third-party-voice.ogg",
        )
        # author is a bot (bot=True) but id 777 does not match hermes client user id (999)
        resolved_msg = SimpleNamespace(
            id=561,
            content="",
            attachments=[third_party_voice_att],
            author=SimpleNamespace(id=777, bot=True, name="foreignbot"),
        )
        ref = SimpleNamespace(message_id=561, resolved=resolved_msg)
        msg = _make_message(content="what did foreign bot say", reference=ref)

        with patch.object(
            discord_adapter, "_cache_simple_media", new_callable=AsyncMock
        ) as mock_cache:
            mock_cache.return_value = "/tmp/cached/third-party-voice.ogg"
            await discord_adapter._handle_message(msg)

        event = discord_adapter.handle_message.await_args.args[0]
        assert event.message_type == MessageType.VOICE
        assert event.media_urls == ["/tmp/cached/third-party-voice.ogg"]
        assert event.media_types == ["audio/ogg"]

    @pytest.mark.asyncio
    async def test_direct_image_replying_to_bot_voice_is_photo_type(
        self, discord_adapter
    ):
        """user direct attachment decides message type when replying to bot voice note."""
        bot_voice_att = _make_attachment(
            filename="voice-message.ogg",
            content_type="audio/ogg",
            is_voice=True,
        )
        resolved_msg = SimpleNamespace(
            id=558,
            content="",
            attachments=[bot_voice_att],
            author=SimpleNamespace(id=999, bot=True, name="bot"),
        )
        ref = SimpleNamespace(message_id=558, resolved=resolved_msg)

        user_img_att = SimpleNamespace(
            filename="screenshot.png",
            content_type="image/png",
            size=2048,
            url="https://cdn.discordapp.com/screenshot.png",
        )
        msg = _make_message(
            content="look at this",
            reference=ref,
            attachments=[user_img_att],
        )

        with patch.object(
            discord_adapter, "_cache_simple_media", new_callable=AsyncMock
        ) as mock_cache:
            mock_cache.return_value = "/tmp/cached/screenshot.jpg"
            await discord_adapter._handle_message(msg)

        event = discord_adapter.handle_message.await_args.args[0]
        assert event.message_type == MessageType.PHOTO
        assert event.media_urls == ["/tmp/cached/screenshot.jpg"]
        assert event.media_types == ["image/png"]
        assert "[Replied-to audio 'voice-message.ogg' sent by the bot]" in event.text
        assert "look at this" in event.text

    @pytest.mark.asyncio
    async def test_empty_typed_reply_to_bot_voice_dispatches_with_context_note(
        self, discord_adapter
    ):
        """empty text reply to bot voice note does not drop event and has context note."""
        bot_voice_att = _make_attachment(
            filename="voice-message.ogg",
            content_type="audio/ogg",
            is_voice=True,
        )
        resolved_msg = SimpleNamespace(
            id=559,
            content="",
            attachments=[bot_voice_att],
            author=SimpleNamespace(id=999, bot=True, name="bot"),
        )
        ref = SimpleNamespace(message_id=559, resolved=resolved_msg)
        msg = _make_message(content="", reference=ref)

        dispatched = await discord_adapter._handle_message(msg)

        assert dispatched is True
        event = discord_adapter.handle_message.await_args.args[0]
        assert event.message_type == MessageType.TEXT
        assert event.media_urls == []
        assert event.text == "[Replied-to audio 'voice-message.ogg' sent by the bot]"

    @pytest.mark.asyncio
    async def test_reply_to_client_user_id_matches_is_bot_ref(
        self, discord_adapter
    ):
        """author with bot flag False but matching client.user.id is treated as bot reference."""
        bot_voice_att = _make_attachment(
            filename="voice-message.ogg",
            content_type="audio/ogg",
            is_voice=True,
        )
        # author.bot is False, but id matches adapter._client.user.id (999)
        resolved_msg = SimpleNamespace(
            id=560,
            content="",
            attachments=[bot_voice_att],
            author=SimpleNamespace(id=999, bot=False, name="hermes"),
        )
        ref = SimpleNamespace(message_id=560, resolved=resolved_msg)
        msg = _make_message(content="replying to you", reference=ref)

        await discord_adapter._handle_message(msg)

        event = discord_adapter.handle_message.await_args.args[0]
        assert event.message_type == MessageType.TEXT
        assert event.media_urls == []
        assert "[Replied-to audio 'voice-message.ogg' sent by the bot]" in event.text
