"""Actionable diagnostics for explicit providers with missing credentials."""

import re


_NON_API_KEY_ENV_VARS = frozenset({"CLAUDE_CODE_OAUTH_TOKEN"})


def format_missing_provider_credentials(provider_id: str) -> str:
    """Build a credential hint from the provider registry when it is available."""
    provider = str(provider_id or "").strip().lower()
    fallback_env = f"{re.sub(r'[^A-Z0-9_]', '_', provider.upper())}_API_KEY"

    try:
        from hermes_cli.auth import PROVIDER_REGISTRY

        config = PROVIDER_REGISTRY.get(provider)
    except Exception:
        config = None

    raw_env_vars = getattr(config, "api_key_env_vars", ()) or ()
    env_vars = tuple(
        value.strip()
        for value in raw_env_vars
        if isinstance(value, str)
        and value.strip()
        and value.strip() not in _NON_API_KEY_ENV_VARS
    )
    if env_vars:
        if len(env_vars) == 1:
            env_hint = f"Set the {env_vars[0]} environment variable"
        else:
            env_hint = f"Set one of these environment variables: {', '.join(env_vars)}"
        detail = f"no API key was found. {env_hint}"
    elif config and str(getattr(config, "auth_type", "")).strip().lower().startswith(
        "oauth"
    ):
        detail = (
            f"no credentials were found. Run `hermes auth add {provider}` to sign in"
        )
    else:
        detail = f"no API key was found. Set the {fallback_env} environment variable"

    return (
        f"Provider '{provider}' is set in config.yaml but {detail}, or switch to "
        "a different provider with `hermes model`."
    )
