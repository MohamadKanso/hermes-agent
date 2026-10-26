"""Checkpoint-enablement resolution for TUI-created agents (issue #79625).

Desktop sessions (``hermes serve`` → TUI gateway) never set ``HERMES_TUI_CHECKPOINTS``
(that env var is only set by the ``hermes --tui --checkpoints`` CLI path), so agent
creation previously gated filesystem checkpointing on the env var alone and silently
ignored ``checkpoints.enabled`` in config.yaml. These helpers resolve enablement the
way the messaging gateway does (``gateway/run.py`` ``_checkpoint_agent_kwargs``):
the env var (explicit CLI opt-in) wins when set, otherwise the ``checkpoints``
config section applies with ``DEFAULT_CONFIG`` defaults.
"""

import os

from utils import is_truthy_value


def _load_checkpoints_enabled(cfg: dict | None = None) -> bool:
    """Whether filesystem checkpoints are enabled for TUI-created agents.

    Keeps the legacy ``checkpoints: true`` bool form working and falls back to the
    ``DEFAULT_CONFIG`` default when the section is absent or malformed.
    """
    cp_cfg = (cfg or {}).get("checkpoints", {})
    if isinstance(cp_cfg, bool):
        cp_cfg = {"enabled": cp_cfg}
    elif not isinstance(cp_cfg, dict):
        cp_cfg = {}
    from hermes_cli.config import DEFAULT_CONFIG
    return bool(cp_cfg.get("enabled", DEFAULT_CONFIG["checkpoints"]["enabled"]))


def resolve_checkpoint_limits(cfg: dict | None = None) -> dict:
    """``AIAgent`` checkpoint size/count limits from the ``checkpoints`` config section, falling
    back to ``DEFAULT_CONFIG`` per key (same keys the CLI and messaging gateway pass)."""
    cp_cfg = (cfg or {}).get("checkpoints", {})
    if not isinstance(cp_cfg, dict):
        cp_cfg = {}
    from hermes_cli.config import DEFAULT_CONFIG
    defaults = DEFAULT_CONFIG["checkpoints"]
    return {f"checkpoint_{key}": cp_cfg.get(key, defaults[key])
            for key in ("max_snapshots", "max_total_size_mb", "max_file_size_mb")}


def resolve_checkpoints_enabled(cfg: dict | None = None) -> bool:
    """Resolve checkpoint enablement with the env-var override first.

    ``HERMES_TUI_CHECKPOINTS`` (set by ``hermes --tui --checkpoints``) is the
    explicit opt-in and wins when present; otherwise fall back to the
    ``checkpoints`` config section (issue #79625 — the desktop backend never
    sets the env var, so config was being silently ignored).
    """
    env_val = os.environ.get("HERMES_TUI_CHECKPOINTS")
    if env_val is not None:
        return is_truthy_value(env_val)
    return _load_checkpoints_enabled(cfg)


def _resolve_checkpoint_hash(mgr, cwd: str, ref: str) -> str:
    """``/rollback N`` style number → the checkpoint's hash; a real hash passes through."""
    try:
        checkpoints = mgr.list_checkpoints(cwd)
        idx = int(ref) - 1
    except ValueError:
        return ref
    if 0 <= idx < len(checkpoints):
        return checkpoints[idx].get("hash", ref)
    raise ValueError(f"Invalid checkpoint number. Use 1-{len(checkpoints)}.")
