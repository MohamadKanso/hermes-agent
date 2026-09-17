"""Regression coverage for explicit-provider credential diagnostics."""

from types import SimpleNamespace
from unittest.mock import patch

import pytest

from agent.auxiliary_client import _resolve_call_client
from agent.agent_init import _routed_client_kwargs
from agent.auxiliary_unavailable import AuxiliaryClientUnavailable
from agent.context_compressor import _is_summary_access_or_quota_error
from agent.provider_credential_hints import format_missing_provider_credentials


def test_registry_uses_valid_env_name_for_hyphenated_provider():
    message = format_missing_provider_credentials("opencode-zen")

    assert "OPENCODE_ZEN_API_KEY" in message
    assert "OPENCODE-ZEN_API_KEY" not in message


def test_registry_points_oauth_provider_to_sign_in():
    message = format_missing_provider_credentials("minimax-oauth")

    assert "hermes auth add minimax-oauth" in message
    assert "MINIMAX-OAUTH_API_KEY" not in message


def test_unknown_provider_keeps_legacy_env_fallback():
    message = format_missing_provider_credentials("custom-provider")

    assert "CUSTOM_PROVIDER_API_KEY" in message


def test_anthropic_hint_does_not_present_oauth_token_as_api_key():
    message = format_missing_provider_credentials("anthropic")

    assert "ANTHROPIC_API_KEY" in message
    assert "CLAUDE_CODE_OAUTH_TOKEN" not in message


def test_auxiliary_path_uses_registry_hint():
    with (
        patch("agent.auxiliary_client._get_cached_client", return_value=(None, None)),
        patch(
            "agent.auxiliary_client._try_configured_fallback_for_unavailable_client",
            return_value=(None, None, None),
        ),
        pytest.raises(AuxiliaryClientUnavailable, match="OPENCODE_ZEN_API_KEY"),
    ):
        _resolve_call_client(
            "compression",
            provider="opencode-zen",
            model=None,
            base_url=None,
            api_key=None,
            resolved_provider="opencode-zen",
            resolved_model=None,
            resolved_base_url=None,
            resolved_api_key=None,
            resolved_api_mode=None,
            main_runtime=None,
            async_mode=False,
        )


def test_auxiliary_oauth_hint_stays_terminal_for_compression():
    with (
        patch("agent.auxiliary_client._get_cached_client", return_value=(None, None)),
        patch(
            "agent.auxiliary_client._try_configured_fallback_for_unavailable_client",
            return_value=(None, None, None),
        ),
        pytest.raises(AuxiliaryClientUnavailable) as exc_info,
    ):
        _resolve_call_client(
            "compression",
            provider="minimax-oauth",
            model=None,
            base_url=None,
            api_key=None,
            resolved_provider="minimax-oauth",
            resolved_model=None,
            resolved_base_url=None,
            resolved_api_key=None,
            resolved_api_mode=None,
            main_runtime=None,
            async_mode=False,
        )

    assert _is_summary_access_or_quota_error(exc_info.value) is True


def test_agent_init_path_uses_registry_hint():
    agent = SimpleNamespace(provider="opencode-zen", model="test-model")

    with (
        patch(
            "agent.auxiliary_client.resolve_provider_client", return_value=(None, None)
        ),
        pytest.raises(RuntimeError, match="OPENCODE_ZEN_API_KEY"),
    ):
        _routed_client_kwargs(agent, None, None)
