"""Tests for fallback credential pool isolation.

Verifies that fallback activation isolates the credential pool from the
primary provider, preventing two bugs:

1. GH #33163: fallback retains primary's base_url → requests go to wrong endpoint
2. GH #33088: fallback provider's 429 exhausts primary credential pool

Both bugs share the same root cause: _recover_with_credential_pool and
_swap_credential continue operating on the PRIMARY's credential pool during
fallback calls, contaminating primary state with fallback-provider errors.
"""

from types import SimpleNamespace
from unittest.mock import MagicMock, patch

# ── Helpers ──────────────────────────────────────────────────────────

def _make_pool(provider, n_entries=1):
    """Create a mock credential pool with N entries."""
    pool = MagicMock()
    pool.provider = provider
    pool.has_credentials.return_value = n_entries > 0
    pool.has_available.return_value = n_entries > 0
    entry = MagicMock()
    entry.id = f"{provider}-entry-0"
    entry.runtime_api_key = f"key-{provider}"
    entry.runtime_base_url = f"https://{provider}.example.com/v1"
    entry.access_token = f"token-{provider}"
    entry.base_url = f"https://{provider}.example.com/v1"
    pool.current.return_value = entry
    pool.mark_exhausted_and_rotate.return_value = entry
    return pool

def _make_agent(provider="openai-codex", model="gpt-5.5",
                base_url="https://chatgpt.com/backend-api/codex",
                api_mode="codex_responses"):
    """Create a minimal AIAgent-like object with just the fields we need."""
    agent = MagicMock()
    agent.provider = provider
    agent.model = model
    agent.base_url = base_url
    agent.api_mode = api_mode
    agent.api_key = "primary-key"
    agent._fallback_activated = False
    agent._fallback_index = 0
    agent._fallback_chain = []
    agent._primary_runtime = {
        "provider": provider,
        "model": model,
        "base_url": base_url,
        "api_mode": api_mode,
        "api_key": "primary-key",
        "client_kwargs": {
            "api_key": "primary-key",
            "base_url": base_url,
        },
        "use_prompt_caching": False,
        "use_native_cache_layout": False,
        "anthropic_api_key": "",
        "anthropic_base_url": "",
    }
    agent._config_context_length = None
    agent._credential_pool = _make_pool(provider)
    agent._rate_limited_until = 0
    agent._transport_cache = {}
    agent._client_kwargs = {
        "api_key": "primary-key",
        "base_url": base_url,
    }
    return agent

# ── Test: _try_activate_fallback clears mismatched pool ──────────────

class TestFallbackCredentialIsolation:
    """Test that _try_activate_fallback isolates the credential pool."""

    def test_fallback_attaches_matching_pool_after_clear(self):
        """Provider-switch fallback should attach the fallback provider's pool."""
        from agent.chat_completion_helpers import try_activate_fallback

        agent = _make_agent(
            provider="ollama-cloud",
            model="glm-5.2",
            base_url="https://ollama.com/v1",
            api_mode="chat_completions",
        )
        agent._fallback_chain = [{"provider": "openai-codex", "model": "gpt-5.5"}]
        agent._credential_pool = _make_pool("ollama-cloud")
        agent._buffer_status = MagicMock()
        agent._is_azure_openai_url.return_value = False
        agent._is_direct_openai_url.return_value = False
        agent._provider_model_requires_responses_api.return_value = False
        agent._anthropic_prompt_cache_policy.return_value = (False, False)
        agent._ensure_lmstudio_runtime_loaded = MagicMock()
        agent._replace_primary_openai_client = MagicMock()
        agent.context_compressor = None

        fallback_client = SimpleNamespace(
            api_key="codex-key",
            base_url="https://chatgpt.com/backend-api/codex",
            _custom_headers={},
        )
        fallback_pool = _make_pool("openai-codex")

        with patch(
            "agent.auxiliary_client.resolve_provider_client",
            return_value=(fallback_client, "gpt-5.5"),
        ) as resolve_provider_client, patch(
            "agent.credential_pool.load_pool",
            return_value=fallback_pool,
        ) as load_pool:
            assert try_activate_fallback(agent) is True

        resolve_provider_client.assert_called_once()
        # Loaded once for the exhausted-pool pre-check and once to attach; both for the fallback provider only.
        assert {c.args for c in load_pool.call_args_list} == {("openai-codex",)}
        assert agent.provider == "openai-codex"
        assert agent.model == "gpt-5.5"
        assert agent.base_url == "https://chatgpt.com/backend-api/codex"
        assert agent.api_mode == "codex_responses"
        assert agent._credential_pool is fallback_pool
        assert agent._credential_pool.provider == "openai-codex"
        assert agent._transport_cache == {}

    def test_fallback_skips_a_candidate_whose_pool_is_exhausted_for_hours(self):
        """#89401: a fallback whose every credential is benched until the weekly quota resets is
        skipped before any client is built; a short throttle on the next candidate is still tried."""
        import time
        from agent.chat_completion_helpers import try_activate_fallback

        agent = _make_agent(provider="anthropic", model="claude", base_url="https://api.anthropic.com", api_mode="chat_completions")
        agent._fallback_chain = [{"provider": "openai-codex", "model": "gpt-5.5"}, {"provider": "openrouter", "model": "m"}]
        agent._credential_pool = _make_pool("anthropic")
        agent._buffer_status = MagicMock()
        agent._is_azure_openai_url.return_value = False
        agent._is_direct_openai_url.return_value = False
        agent._provider_model_requires_responses_api.return_value = False
        agent._anthropic_prompt_cache_policy.return_value = (False, False)
        agent._ensure_lmstudio_runtime_loaded = MagicMock()
        agent._replace_primary_openai_client = MagicMock()
        agent.context_compressor = None

        benched = _make_pool("openai-codex")
        benched.has_available.return_value = False
        benched.next_available_at.return_value = time.time() + 30995
        throttled = _make_pool("openrouter")
        throttled.has_available.return_value = False
        throttled.next_available_at.return_value = time.time() + 30
        pools = {"openai-codex": benched, "openrouter": throttled}
        client = SimpleNamespace(api_key="k", base_url="https://openrouter.ai/api/v1", _custom_headers={})

        with patch("agent.auxiliary_client.resolve_provider_client", return_value=(client, "m")) as resolve, \
                patch("agent.credential_pool.load_pool", side_effect=lambda p: pools[p]):
            assert try_activate_fallback(agent) is True

        assert resolve.call_count == 1 and resolve.call_args.args[0] == "openrouter"
        assert agent.provider == "openrouter" and agent._credential_pool is throttled

    def test_same_provider_fallback_not_skipped_when_pool_has_no_wait_info(self):
        """#140568: same-provider fallback candidates must not be skipped when
        next_available_at() returns none because credentials (like vertex service-account
        key files) carry no wait info. only a fully dead pool is skipped."""
        from agent.chat_completion_helpers import try_activate_fallback

        agent = _make_agent(provider="vertex", model="google/gemini-3.8-flash", base_url="https://vertex.example.com", api_mode="chat_completions")
        agent._fallback_chain = [{"provider": "vertex", "model": "google/gemini-4-argon"}]
        pool = _make_pool("vertex")
        pool.has_available.return_value = False
        pool.next_available_at.return_value = None
        # entry is alive (e.g. sa key file auth), not dead
        alive_entry = SimpleNamespace(last_status=None)
        pool.entries.return_value = [alive_entry]
        agent._credential_pool = pool
        agent._buffer_status = MagicMock()
        agent._is_azure_openai_url.return_value = False
        agent._is_direct_openai_url.return_value = False
        agent._provider_model_requires_responses_api.return_value = False
        agent._anthropic_prompt_cache_policy.return_value = (False, False)
        agent._ensure_lmstudio_runtime_loaded = MagicMock()
        agent._replace_primary_openai_client = MagicMock()
        agent.context_compressor = None

        client = SimpleNamespace(api_key="k", base_url="https://vertex.example.com", _custom_headers={})

        with patch("agent.auxiliary_client.resolve_provider_client", return_value=(client, "google/gemini-4-argon")) as resolve, \
                patch("agent.credential_pool.load_pool", return_value=pool):
            assert try_activate_fallback(agent) is True

        assert resolve.call_count == 1
        assert agent.provider == "vertex" and agent.model == "google/gemini-4-argon"

    def test_candidate_pool_exhausted_skips_when_all_entries_are_dead(self):
        """#140568: when next_available_at() is none and every entry in the pool is
        marked dead, the candidate pool really is exhausted and should be skipped."""
        from agent.chat_completion_helpers import _candidate_pool_exhausted
        from agent.credential_pool import STATUS_DEAD

        pool = _make_pool("custom-provider")
        pool.has_available.return_value = False
        pool.next_available_at.return_value = None
        dead_entry1 = SimpleNamespace(last_status=STATUS_DEAD)
        dead_entry2 = SimpleNamespace(last_status=STATUS_DEAD)
        pool.entries.return_value = [dead_entry1, dead_entry2]

        agent = SimpleNamespace(_credential_pool=pool)
        assert _candidate_pool_exhausted(agent, "custom-provider", "model-x") is True

        # if at least one entry is not dead, pool is not considered exhausted
        dead_entry2.last_status = None
        assert _candidate_pool_exhausted(agent, "custom-provider", "model-x") is False

    def test_vertex_sa_credential_pool_repro_140568(self):
        """#140568: real credentialpool with vertex sa key file entry has
        has_credentials()=true, has_available()=false, next_available_at()=none.
        _candidate_pool_exhausted must return false so same-provider fallbacks are not skipped."""
        from agent.chat_completion_helpers import _candidate_pool_exhausted
        from agent.credential_pool import AUTH_TYPE_API_KEY, CredentialPool, PooledCredential

        entry = PooledCredential.from_dict("vertex", {
            "id": "vertex-sa-1",
            "auth_type": AUTH_TYPE_API_KEY,
            "label": "VERTEX_SA_KEY_FILE",
            "access_token": "",
            "last_status": None,
        })
        pool = CredentialPool(provider="vertex", entries=[entry])

        assert pool.has_credentials() is True
        assert pool.has_available(model="google/gemini-4-argon") is False
        assert pool.next_available_at(model="google/gemini-4-argon") is None

        agent = SimpleNamespace(_credential_pool=pool)
        assert _candidate_pool_exhausted(agent, "vertex", "google/gemini-4-argon") is False

# ── Test: _recover_with_credential_pool rejects mismatched pool ──────

# ── Test: base_url not overwritten after fallback ────────────────────
