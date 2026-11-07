"""regression tests for issue #150823.

user-defined providers under providers: whose key matches a canonical
built-in provider id (e.g. ai-gateway) must emit slug custom:<name> so
sessions resolve to the custom endpoint instead of the unconfigured built-in.
"""

from hermes_cli.inventory import build_model_options_payload, load_picker_context
from hermes_cli.runtime_provider import resolve_runtime_provider


def test_user_provider_colliding_with_builtin_id_emits_custom_slug(monkeypatch):
    """when a providers entry key matches a canonical built-in provider,
    the picker must emit slug custom:<name> rather than bare <name>."""
    monkeypatch.setattr("agent.models_dev.fetch_models_dev", dict)
    monkeypatch.setattr("hermes_cli.providers.HERMES_OVERLAYS", {})
    monkeypatch.delenv("AI_GATEWAY_API_KEY", raising=False)

    user_providers = {
        "ai-gateway": {
            "name": "my gateway",
            "base_url": "https://gateway.example.com/v1",
            "models": ["gateway-model-1"],
        },
        "custom-router": {
            "name": "my router",
            "base_url": "https://router.example.com/v1",
            "models": ["router-model-1"],
        },
    }

    monkeypatch.setattr(
        "hermes_cli.config.load_config",
        lambda: {"providers": user_providers},
    )

    ctx = load_picker_context()
    payload = build_model_options_payload(ctx)
    providers = payload["providers"]

    colliding = next((p for p in providers if p["name"] == "my gateway"), None)
    assert colliding is not None, "colliding user provider missing from options payload"
    assert colliding["slug"] == "custom:ai-gateway", "colliding provider must emit custom:<name> slug"
    assert colliding["is_user_defined"] is True
    assert "ai-gateway" in colliding.get("aliases", [])
    assert "custom:ai-gateway" in colliding.get("aliases", [])

    non_colliding = next((p for p in providers if p["name"] == "my router"), None)
    assert non_colliding is not None, "non-colliding user provider missing from options payload"
    assert non_colliding["slug"] == "custom-router", "non-colliding provider keeps its bare slug"
    assert non_colliding["is_user_defined"] is True


def test_lmstudio_user_provider_keeps_bare_slug(monkeypatch):
    """lmstudio is a local server provider whose explicit endpoint stays bare lmstudio."""
    monkeypatch.setattr("agent.models_dev.fetch_models_dev", dict)
    monkeypatch.setattr("hermes_cli.providers.HERMES_OVERLAYS", {})
    monkeypatch.delenv("LM_BASE_URL", raising=False)
    monkeypatch.delenv("LM_API_KEY", raising=False)
    monkeypatch.setattr(
        "hermes_cli.models_local.fetch_lmstudio_models",
        lambda *a, **k: ["remote-model"],
    )

    monkeypatch.setattr(
        "hermes_cli.config.load_config",
        lambda: {
            "providers": {
                "lmstudio": {
                    "base_url": "http://remote-box:1234/v1",
                    "models": ["remote-model"],
                }
            }
        },
    )

    ctx = load_picker_context()
    payload = build_model_options_payload(ctx)
    providers = payload["providers"]

    lm_row = next((p for p in providers if p["slug"] == "lmstudio"), None)
    assert lm_row is not None, "lmstudio row missing from options payload"
    assert lm_row["slug"] == "lmstudio"
    assert lm_row["is_user_defined"] is True


def test_session_resolution_with_emitted_custom_slug(monkeypatch):
    """resolving runtime provider using the emitted custom:<name> slug targets the user config."""
    monkeypatch.delenv("AI_GATEWAY_API_KEY", raising=False)
    monkeypatch.setattr(
        "hermes_cli.config.load_config",
        lambda: {
            "providers": {
                "ai-gateway": {
                    "name": "my gateway",
                    "base_url": "https://gateway.example.com/v1",
                    "models": ["gateway-model-1"],
                }
            }
        },
    )

    resolved = resolve_runtime_provider(requested="custom:ai-gateway", target_model="gateway-model-1")
    assert resolved["provider"] == "custom"
    assert resolved["base_url"] == "https://gateway.example.com/v1"
