"""voice-list discovery for profile-scoped command TTS providers."""

from __future__ import annotations

import logging
import subprocess
from typing import Any

_log = logging.getLogger("hermes_cli.web_server")

_MAX_VOICE_COMMAND_OUTPUT_CHARS = 64_000
_MAX_COMMAND_VOICES = 500
_MAX_COMMAND_VOICE_ID_CHARS = 256
_COMMAND_VOICE_TIMEOUT_SECONDS = 10.0


def _unavailable(provider: str) -> dict[str, Any]:
    return {"available": False, "provider": provider, "voices": [], "current": ""}


def list_command_tts_voices(provider: str) -> dict[str, Any]:
    """run a configured command provider's bounded, one-id-per-line voice query."""
    provider_name = (provider or "").strip()
    if not provider_name or len(provider_name) > 128 or any(ord(char) < 32 for char in provider_name):
        return _unavailable(provider_name)

    from hermes_cli.config import load_config_readonly
    from tools.tts_command_provider import (
        CommandProviderOutputLimitError,
        _get_command_tts_output_format,
        _get_command_tts_timeout,
        _resolve_command_provider_config,
        command_env_passthrough,
        render_command_template,
        run_command_provider,
    )

    config = load_config_readonly()
    tts_config = config.get("tts") if isinstance(config, dict) else None
    if not isinstance(tts_config, dict):
        return _unavailable(provider_name)
    selected_provider = str(tts_config.get("provider") or "").strip().lower()
    if selected_provider != provider_name.lower():
        return _unavailable(provider_name)

    provider_config = _resolve_command_provider_config(provider_name, tts_config)
    if provider_config is None:
        return _unavailable(provider_name)

    voices_command = provider_config.get("voices_command")
    if not isinstance(voices_command, str) or not voices_command.strip():
        return _unavailable(provider_name)

    current = str(provider_config.get("voice") or "").strip()
    command = render_command_template(voices_command.strip(), {
        "format": _get_command_tts_output_format(provider_config),
        "model": str(provider_config.get("model") or ""),
        "speed": str(provider_config.get("speed", tts_config.get("speed", "")) or ""),
        "voice": current,
    })
    timeout = min(_get_command_tts_timeout(provider_config), _COMMAND_VOICE_TIMEOUT_SECONDS)

    try:
        result = run_command_provider(
            command,
            timeout,
            env_passthrough=command_env_passthrough(provider_config),
            max_output_chars=_MAX_VOICE_COMMAND_OUTPUT_CHARS,
            max_duration_seconds=_COMMAND_VOICE_TIMEOUT_SECONDS,
        )
    except (subprocess.CalledProcessError, subprocess.TimeoutExpired, CommandProviderOutputLimitError) as exc:
        _log.debug("Command TTS voice listing failed for %s (%s)", provider_name, type(exc).__name__)
        return _unavailable(provider_name)
    except Exception:
        _log.exception("Command TTS voice listing failed for %s", provider_name)
        return _unavailable(provider_name)

    voices = []
    seen: set[str] = set()
    for line in result.stdout.splitlines():
        voice_id = line.strip()
        if not voice_id or len(voice_id) > _MAX_COMMAND_VOICE_ID_CHARS:
            continue
        if any(ord(char) < 32 or ord(char) == 127 for char in voice_id) or voice_id in seen:
            continue
        seen.add(voice_id)
        voices.append({"id": voice_id, "label": voice_id})
        if len(voices) > _MAX_COMMAND_VOICES:
            return _unavailable(provider_name)

    return {
        "available": True,
        "provider": provider_name,
        "voices": voices,
        "current": current,
    }
