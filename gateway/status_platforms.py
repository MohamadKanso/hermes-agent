"""Retire platform status at secondary-profile configuration boundaries."""

from gateway.config import Platform


def prune_profile_platforms(platforms, profile_name, retained=None):
    """Drop one profile's obsolete keys, or all namespaced keys at startup."""
    prefix = f"{profile_name}:" if profile_name else None
    return {
        key: value for key, value in platforms.items()
        if not isinstance(key, str) or ":" not in key
        or (prefix is not None and (not key.startswith(prefix) or key in (retained or ())))
    }


def retire_secondary_platform_status(runner, profile_name, profile_home, config):
    """Discard stale refusals only after a new secondary config has loaded.

    Live and queued adapters still own their status until their lifecycle ends,
    even if the new config disables them. Enabled unserved channels retain their
    explanatory status, including WhatsApp's intentional unpaired notice.
    """
    from gateway.run import (
        _platform_has_bot_credential, _profile_runtime_scope, _write_runtime_status_quiet,
    )

    retained = set(runner._profile_adapters.get(profile_name) or {})
    retained.update((getattr(runner, "_profile_failed_platforms", None) or {}).get(profile_name) or {})
    with _profile_runtime_scope(profile_home, hydrate_secrets=False):
        retained.update(
            platform for platform, platform_config in config.platforms.items()
            if platform_config.enabled and (
                not runner._multiplex_on() or platform is Platform.WHATSAPP
                or _platform_has_bot_credential(platform, platform_config)
            )
        )
    noted = getattr(runner, "_unserved_secondary_platforms", None)
    if noted is not None:
        noted.difference_update({
            item for item in noted if item[0] == profile_name and item[1] not in retained
        })
    _write_runtime_status_quiet(
        drop_profile_platforms=profile_name,
        retain_profile_platforms={f"{profile_name}:{platform.value}" for platform in retained},
    )
