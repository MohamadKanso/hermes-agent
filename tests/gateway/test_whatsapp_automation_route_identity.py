"""tests for whatsapp identity canonicalization in automation route checks."""

import json
from types import SimpleNamespace
from unittest.mock import MagicMock

import pytest

from gateway.config import Platform
from gateway.platforms.event import MessageEvent, MessageType
from gateway.session import SessionSource
from gateway.session_automation import _route_identity, snapshot_automation
from hermes_state_runtime import RuntimeStoreError


def test_whatsapp_dm_lid_and_phone_route_identities_match(tmp_path, monkeypatch):
    """dm origin with lid and turn with phone jid compare equal when alias mapped."""
    tmp_home = tmp_path / "hermes-home"
    mapping_dir = tmp_home / "platforms" / "whatsapp" / "session"
    mapping_dir.mkdir(parents=True, exist_ok=True)
    (mapping_dir / "lid-mapping-999999999999999.json").write_text(
        json.dumps("15551234567@s.whatsapp.net"),
        encoding="utf-8",
    )
    monkeypatch.setenv("HERMES_HOME", str(tmp_home))

    origin = SessionSource(
        platform=Platform.WHATSAPP,
        chat_id="999999999999999@lid",
        chat_type="dm",
        user_id="999999999999999@lid",
        message_id="msg-origin",
    )
    turn = SessionSource(
        platform=Platform.WHATSAPP,
        chat_id="15551234567@s.whatsapp.net",
        chat_type="dm",
        user_id="15551234567@s.whatsapp.net",
        message_id="msg-turn",
    )

    assert _route_identity(origin) == _route_identity(turn)


def test_whatsapp_different_users_stay_distinct(tmp_path, monkeypatch):
    """two different senders never compare equal."""
    tmp_home = tmp_path / "hermes-home"
    mapping_dir = tmp_home / "platforms" / "whatsapp" / "session"
    mapping_dir.mkdir(parents=True, exist_ok=True)
    (mapping_dir / "lid-mapping-999999999999999.json").write_text(
        json.dumps("15551234567@s.whatsapp.net"),
        encoding="utf-8",
    )
    monkeypatch.setenv("HERMES_HOME", str(tmp_home))

    user_a = SessionSource(
        platform=Platform.WHATSAPP,
        chat_id="999999999999999@lid",
        chat_type="dm",
        user_id="999999999999999@lid",
    )
    user_b = SessionSource(
        platform=Platform.WHATSAPP,
        chat_id="15550009999@s.whatsapp.net",
        chat_type="dm",
        user_id="15550009999@s.whatsapp.net",
    )

    assert _route_identity(user_a) != _route_identity(user_b)


def test_non_whatsapp_platform_compared_raw():
    """discord and other platforms keep raw identity comparison."""
    source_a = SessionSource(
        platform=Platform.DISCORD,
        chat_id="channel-123",
        chat_type="dm",
        user_id="user-456",
        message_id="msg-1",
    )
    source_b = SessionSource(
        platform=Platform.DISCORD,
        chat_id="channel-123",
        chat_type="dm",
        user_id="user-456",
        message_id="msg-2",
    )
    source_c = SessionSource(
        platform=Platform.DISCORD,
        chat_id="channel-123",
        chat_type="dm",
        user_id="user-789",
    )

    assert _route_identity(source_a) == _route_identity(source_b)
    assert _route_identity(source_a) != _route_identity(source_c)


def test_whatsapp_group_preserves_group_chat_id(tmp_path, monkeypatch):
    """group chat_id preserves group jid while participant user_id is canonicalized."""
    tmp_home = tmp_path / "hermes-home"
    mapping_dir = tmp_home / "platforms" / "whatsapp" / "session"
    mapping_dir.mkdir(parents=True, exist_ok=True)
    (mapping_dir / "lid-mapping-999999999999999.json").write_text(
        json.dumps("15551234567@s.whatsapp.net"),
        encoding="utf-8",
    )
    monkeypatch.setenv("HERMES_HOME", str(tmp_home))

    group_source_lid = SessionSource(
        platform=Platform.WHATSAPP,
        chat_id="12345678-group@g.us",
        chat_type="group",
        user_id="999999999999999@lid",
    )
    group_source_phone = SessionSource(
        platform=Platform.WHATSAPP,
        chat_id="12345678-group@g.us",
        chat_type="group",
        user_id="15551234567@s.whatsapp.net",
    )

    route_lid = _route_identity(group_source_lid)
    route_phone = _route_identity(group_source_phone)

    assert route_lid["chat_id"] == "12345678-group@g.us"
    assert route_lid["user_id"] == "15551234567"
    assert route_lid == route_phone


def test_snapshot_automation_admits_whatsapp_lid_origin_with_phone_turn(tmp_path, monkeypatch):
    """snapshot_automation admits wake when dm origin is lid and committed turn is phone."""
    tmp_home = tmp_path / "hermes-home"
    mapping_dir = tmp_home / "platforms" / "whatsapp" / "session"
    mapping_dir.mkdir(parents=True, exist_ok=True)
    (mapping_dir / "lid-mapping-999999999999999.json").write_text(
        json.dumps("15551234567@s.whatsapp.net"),
        encoding="utf-8",
    )
    monkeypatch.setenv("HERMES_HOME", str(tmp_home))

    lid_source = SessionSource(
        platform=Platform.WHATSAPP,
        chat_id="999999999999999@lid",
        chat_type="dm",
        user_id="999999999999999@lid",
    )
    phone_source = SessionSource(
        platform=Platform.WHATSAPP,
        chat_id="15551234567@s.whatsapp.net",
        chat_type="dm",
        user_id="15551234567@s.whatsapp.net",
    )

    entry = SimpleNamespace(
        session_key="whatsapp:15551234567",
        session_id="session-xyz",
        origin=lid_source,
    )

    adapter = object()
    runner = MagicMock()
    runner._adapter_for_source.return_value = adapter

    authority = MagicMock()
    authority.runner = runner
    authority.logical_owner.return_value = "session-xyz"

    event = MessageEvent(
        text="completed async delegation",
        message_type=MessageType.TEXT,
        source=lid_source,
        internal=True,
        metadata={
            "gateway_session_key": "whatsapp:15551234567",
            "notification_category": "result",
        },
    )

    phone_dict = phone_source.to_dict()
    phone_dict["is_bot"] = False
    committed_envelope = {
        "timestamp": "2026-11-04T00:00:00+00:00",
        "provenance": {"message_id": "phone-msg-1"},
        "source": phone_dict,
        "event": {},
    }

    monkeypatch.setattr(
        "gateway.session_ingress_context.restore_provenance",
        lambda *args, **kwargs: None,
    )
    monkeypatch.setattr(
        "gateway.session_automation._owner",
        lambda _runner, _event, _authority: entry,
    )
    monkeypatch.setattr(
        "gateway.session_automation.committed_route_envelope",
        lambda _authority, _entry: committed_envelope,
    )

    payload, returned_entry = snapshot_automation(
        authority,
        adapter,
        event,
        identity="delegation-task-uuid",
    )

    assert returned_entry is entry
    assert payload["native_text_v1"]["automation"]["identity"] == "delegation-task-uuid"


def test_snapshot_automation_refuses_different_whatsapp_sender(tmp_path, monkeypatch):
    """snapshot_automation still raises admission_conflict for a foreign sender."""
    tmp_home = tmp_path / "hermes-home"
    monkeypatch.setenv("HERMES_HOME", str(tmp_home))

    lid_source = SessionSource(
        platform=Platform.WHATSAPP,
        chat_id="999999999999999@lid",
        chat_type="dm",
        user_id="999999999999999@lid",
    )
    attacker_source = SessionSource(
        platform=Platform.WHATSAPP,
        chat_id="15550006666@s.whatsapp.net",
        chat_type="dm",
        user_id="15550006666@s.whatsapp.net",
    )

    entry = SimpleNamespace(
        session_key="whatsapp:15551234567",
        session_id="session-xyz",
        origin=lid_source,
    )

    adapter = object()
    runner = MagicMock()
    runner._adapter_for_source.return_value = adapter

    authority = MagicMock()
    authority.runner = runner
    authority.logical_owner.return_value = "session-xyz"

    event = MessageEvent(
        text="completed async delegation",
        message_type=MessageType.TEXT,
        source=lid_source,
        internal=True,
        metadata={
            "gateway_session_key": "whatsapp:15551234567",
            "notification_category": "result",
        },
    )

    attacker_dict = attacker_source.to_dict()
    attacker_dict["is_bot"] = False
    committed_envelope = {
        "timestamp": "2026-11-04T00:00:00+00:00",
        "provenance": {"message_id": "attacker-msg-1"},
        "source": attacker_dict,
        "event": {},
    }

    monkeypatch.setattr(
        "gateway.session_ingress_context.restore_provenance",
        lambda *args, **kwargs: None,
    )
    monkeypatch.setattr(
        "gateway.session_automation._owner",
        lambda _runner, _event, _authority: entry,
    )
    monkeypatch.setattr(
        "gateway.session_automation.committed_route_envelope",
        lambda _authority, _entry: committed_envelope,
    )

    with pytest.raises(RuntimeStoreError, match="admission_conflict"):
        snapshot_automation(
            authority,
            adapter,
            event,
            identity="delegation-task-uuid",
        )
