"""Regression tests for issue #116286.

Enabling a plugin whose manifest declares no capabilities (e.g. hook-only
plugins like opencode-usage) should not solicit an allow_tool_override grant
when no explicit flag was passed.
"""

from unittest.mock import MagicMock
import pytest
import yaml

from hermes_cli import plugins_cmd


@pytest.mark.parametrize(
    "caps,flag,existing,answer,expected_override,expected_prompts",
    [
        # No capabilities declared, no flag -> silent enable, no prompt, no override key
        (None, None, None, "n", None, 0),
        # Empty capabilities list declared, no flag -> silent enable, no prompt, no override key
        ([], None, None, "n", None, 0),
        # No capabilities declared, explicit --allow-tool-override -> true, no prompt
        (None, True, None, "n", True, 0),
        # No capabilities declared, explicit --no-allow-tool-override -> false, no prompt
        (None, False, True, "n", False, 0),
        # No capabilities declared, no flag, existing grant preserved unchanged
        (None, None, True, "n", True, 0),
        # Capabilities declared with tools.override -> consent prompt fired, grant mirrored
        (["tools.override"], None, None, "y", True, 1),
    ],
)
def test_enable_no_capabilities_avoids_tool_override_prompt(
    tmp_path, monkeypatch, caps, flag, existing, answer, expected_override, expected_prompts
):
    monkeypatch.setenv("HERMES_HOME", str(tmp_path))
    plugin_dir = tmp_path / "plugins" / "opencode-usage"
    plugin_dir.mkdir(parents=True)
    manifest = {
        "name": "opencode-usage",
        "version": "0.1.0",
        "description": "usage footer",
        "hooks": ["transform_llm_output"],
    }
    if caps is not None:
        manifest["capabilities"] = caps
    (plugin_dir / "plugin.yaml").write_text(yaml.safe_dump(manifest), encoding="utf-8")
    (plugin_dir / "__init__.py").write_text("def register(ctx):\n    pass\n", encoding="utf-8")

    initial_config = {}
    if existing is not None:
        initial_config = {
            "plugins": {
                "entries": {
                    "opencode-usage": {"allow_tool_override": existing}
                }
            }
        }
    (tmp_path / "config.yaml").write_text(yaml.safe_dump(initial_config), encoding="utf-8")

    console = MagicMock()
    console.input.return_value = answer
    monkeypatch.setattr(plugins_cmd, "_console", lambda: console)
    monkeypatch.setattr("sys.stdin.isatty", lambda: True)
    monkeypatch.setattr("sys.stdout.isatty", lambda: True)

    plugins_cmd.cmd_enable("opencode-usage", allow_tool_override=flag)

    assert console.input.call_count == expected_prompts
    cfg = yaml.safe_load((tmp_path / "config.yaml").read_text(encoding="utf-8")) or {}
    assert "opencode-usage" in cfg.get("plugins", {}).get("enabled", [])
    entry = cfg.get("plugins", {}).get("entries", {}).get("opencode-usage", {})
    assert entry.get("allow_tool_override") is expected_override
