"""behavior contracts for command TTS voice-list discovery."""

import subprocess

from hermes_cli import config as config_module
from hermes_cli.web_routers.audio_command_voices import list_command_tts_voices
from tools import tts_command_provider


def test_voice_list_requires_a_declared_command_and_voice_command(monkeypatch):
    monkeypatch.setattr(config_module, "load_config_readonly", lambda: {
        "tts": {
            "providers": {
                "plain": {"type": "command", "command": "say"},
                "edge": {"type": "command", "command": "not a builtin override"},
            }
        }
    })
    monkeypatch.setattr(
        tts_command_provider,
        "run_command_provider",
        lambda *_args, **_kwargs: (_ for _ in ()).throw(AssertionError("must not run")),
    )

    assert list_command_tts_voices("plain")["available"] is False
    assert list_command_tts_voices("edge")["available"] is False
    assert list_command_tts_voices("missing")["available"] is False


def test_voice_list_deduplicates_and_omits_invalid_ids(monkeypatch):
    monkeypatch.setattr(config_module, "load_config_readonly", lambda: {
        "tts": {
            "provider": "piper-custom",
            "speed": 0.8,
            "providers": {
                "piper-custom": {
                    "type": "command",
                    "command": "piper speak",
                    "voices_command": "piper --list-voices --current {voice} --speed {speed}",
                    "voice": "en_US-amy-medium",
                    "env_passthrough": ["PIPER_TOKEN"],
                }
            },
        }
    })
    observed = {}

    def run_command(command, timeout, env_passthrough=None, max_output_chars=None, max_duration_seconds=None):
        observed.update(
            command=command,
            timeout=timeout,
            env_passthrough=env_passthrough,
            max_output_chars=max_output_chars,
            max_duration_seconds=max_duration_seconds,
        )
        return subprocess.CompletedProcess(command, 0, "en_US-amy-medium\nen_GB-alan\nen_GB-alan\nbad\x00id\n", "")

    monkeypatch.setattr(tts_command_provider, "run_command_provider", run_command)
    result = list_command_tts_voices("piper-custom")

    assert result == {
        "available": True,
        "provider": "piper-custom",
        "voices": [
            {"id": "en_US-amy-medium", "label": "en_US-amy-medium"},
            {"id": "en_GB-alan", "label": "en_GB-alan"},
        ],
        "current": "en_US-amy-medium",
    }
    assert "en_US-amy-medium" in observed["command"]
    assert "0.8" in observed["command"]
    assert observed["timeout"] <= 10
    assert observed["env_passthrough"] == ["PIPER_TOKEN"]
    assert observed["max_output_chars"] == 64_000
    assert observed["max_duration_seconds"] == 10


def test_voice_list_does_not_run_an_unselected_provider(monkeypatch):
    monkeypatch.setattr(config_module, "load_config_readonly", lambda: {
        "tts": {
            "provider": "other-provider",
            "providers": {
                "piper-custom": {
                    "type": "command",
                    "command": "piper speak",
                    "voices_command": "piper --list-voices",
                }
            },
        }
    })
    monkeypatch.setattr(
        tts_command_provider,
        "run_command_provider",
        lambda *_args, **_kwargs: (_ for _ in ()).throw(AssertionError("must not run")),
    )

    assert list_command_tts_voices("piper-custom")["available"] is False


def test_voice_list_fails_closed_when_the_command_fails(monkeypatch):
    monkeypatch.setattr(config_module, "load_config_readonly", lambda: {
        "tts": {"provider": "piper-custom", "providers": {"piper-custom": {
            "type": "command", "command": "piper speak", "voices_command": "piper --list-voices",
        }}}
    })
    monkeypatch.setattr(
        tts_command_provider,
        "run_command_provider",
        lambda *_args, **_kwargs: (_ for _ in ()).throw(subprocess.TimeoutExpired("list", 10)),
    )

    result = list_command_tts_voices("piper-custom")
    assert result["available"] is False
    assert result["voices"] == []
    assert "command" not in result
