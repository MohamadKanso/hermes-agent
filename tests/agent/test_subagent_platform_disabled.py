"""tests for skills.platform_disabled.subagent isolation and inheritance."""

from pathlib import Path
from types import SimpleNamespace
import pytest

from agent.delegation_context import delegated_child_context
from agent.prompt_builder import build_skills_system_prompt
from agent.skill_utils import get_disabled_skill_names
from agent.system_prompt import _skills_prompt
from tools.skills_tool import _is_skill_disabled


def _make_skill(root: Path, name: str, category: str = "general") -> Path:
    skill_dir = root / category / name
    skill_dir.mkdir(parents=True, exist_ok=True)
    skill_file = skill_dir / "SKILL.md"
    skill_file.write_text(
        f"---\nname: {name}\ndescription: test skill {name}\n---\n\n# {name}\n",
        encoding="utf-8",
    )
    return skill_file


def _setup_skills_env(tmp_path, monkeypatch, config_yaml: str):
    home = tmp_path / "home"
    skills_dir = home / "skills"
    skills_dir.mkdir(parents=True, exist_ok=True)
    cfg_file = home / "config.yaml"
    cfg_file.write_text(config_yaml, encoding="utf-8")

    monkeypatch.setenv("HERMES_HOME", str(home))
    monkeypatch.delenv("HERMES_PLATFORM", raising=False)
    monkeypatch.delenv("HERMES_SESSION_PLATFORM", raising=False)

    from agent.skill_utils import _RAW_CONFIG_CACHE
    _RAW_CONFIG_CACHE.clear()

    try:
        from hermes_cli.config import _LOAD_CONFIG_CACHE, _RAW_CONFIG_CACHE as _CLI_RAW_CACHE
        _LOAD_CONFIG_CACHE.clear()
        _CLI_RAW_CACHE.clear()
    except Exception:
        pass

    import agent.prompt_builder as pb
    with pb._SKILLS_PROMPT_CACHE_LOCK:
        pb._SKILLS_PROMPT_CACHE.clear()

    return skills_dir


class TestSubagentPlatformDisabled:
    def test_subagent_platform_disabled_omitted_from_prompt(self, tmp_path, monkeypatch):
        yaml_content = (
            "skills:\n"
            "  platform_disabled:\n"
            "    subagent:\n"
            "      - child-disabled-skill\n"
        )
        skills_dir = _setup_skills_env(tmp_path, monkeypatch, yaml_content)
        _make_skill(skills_dir, "child-disabled-skill")
        _make_skill(skills_dir, "allowed-skill")

        parent_agent = SimpleNamespace(
            valid_tool_names={"skill_view", "skills_list"},
            platform="cli",
            _custom_skills_dir=None,
        )
        parent_prompt = _skills_prompt(parent_agent)
        assert "child-disabled-skill" in parent_prompt
        assert "allowed-skill" in parent_prompt

        child_agent = SimpleNamespace(
            valid_tool_names={"skill_view", "skills_list"},
            platform="subagent",
            _custom_skills_dir=None,
        )
        child_prompt = _skills_prompt(child_agent)
        assert "child-disabled-skill" not in child_prompt
        assert "allowed-skill" in child_prompt

    def test_subagent_inherits_calling_platform_disabled_skills(self, tmp_path, monkeypatch):
        yaml_content = (
            "skills:\n"
            "  platform_disabled:\n"
            "    telegram:\n"
            "      - tg-restricted-skill\n"
            "    subagent:\n"
            "      - subagent-restricted-skill\n"
        )
        skills_dir = _setup_skills_env(tmp_path, monkeypatch, yaml_content)
        _make_skill(skills_dir, "tg-restricted-skill")
        _make_skill(skills_dir, "subagent-restricted-skill")
        _make_skill(skills_dir, "common-skill")

        monkeypatch.setenv("HERMES_SESSION_PLATFORM", "telegram")

        parent_agent = SimpleNamespace(
            valid_tool_names={"skill_view", "skills_list"},
            platform="telegram",
            _custom_skills_dir=None,
        )
        parent_prompt = _skills_prompt(parent_agent)
        assert "tg-restricted-skill" not in parent_prompt
        assert "subagent-restricted-skill" in parent_prompt
        assert "common-skill" in parent_prompt

        child_agent = SimpleNamespace(
            valid_tool_names={"skill_view", "skills_list"},
            platform="subagent",
            _custom_skills_dir=None,
        )
        with delegated_child_context("child-sess-1"):
            child_prompt = _skills_prompt(child_agent)
            assert "tg-restricted-skill" not in child_prompt
            assert "subagent-restricted-skill" not in child_prompt
            assert "common-skill" in child_prompt

    def test_get_disabled_skill_names_subagent_resolution(self, tmp_path, monkeypatch):
        yaml_content = (
            "skills:\n"
            "  disabled:\n"
            "    - global-disabled\n"
            "  platform_disabled:\n"
            "    discord:\n"
            "      - discord-only\n"
            "    subagent:\n"
            "      - subagent-only\n"
        )
        _setup_skills_env(tmp_path, monkeypatch, yaml_content)

        monkeypatch.setenv("HERMES_SESSION_PLATFORM", "discord")

        parent_disabled = get_disabled_skill_names()
        assert parent_disabled == {"global-disabled", "discord-only"}

        child_disabled_explicit = get_disabled_skill_names(platform="subagent")
        assert child_disabled_explicit == {"global-disabled", "discord-only", "subagent-only"}

        with delegated_child_context("child-sess-2"):
            child_disabled_context = get_disabled_skill_names()
            assert child_disabled_context == {"global-disabled", "discord-only", "subagent-only"}

    def test_is_skill_disabled_in_subagent_context(self, tmp_path, monkeypatch):
        yaml_content = (
            "skills:\n"
            "  platform_disabled:\n"
            "    slack:\n"
            "      - slack-cut\n"
            "    subagent:\n"
            "      - subagent-cut\n"
        )
        _setup_skills_env(tmp_path, monkeypatch, yaml_content)
        monkeypatch.setenv("HERMES_SESSION_PLATFORM", "slack")

        assert _is_skill_disabled("slack-cut") is True
        assert _is_skill_disabled("subagent-cut") is False
        assert _is_skill_disabled("subagent-cut", platform="subagent") is True

        with delegated_child_context("child-sess-3"):
            assert _is_skill_disabled("slack-cut") is True
            assert _is_skill_disabled("subagent-cut") is True

    def test_prompt_builder_cache_key_isolation(self, tmp_path, monkeypatch):
        yaml_content = (
            "skills:\n"
            "  platform_disabled:\n"
            "    subagent:\n"
            "      - heavy-skill\n"
        )
        skills_dir = _setup_skills_env(tmp_path, monkeypatch, yaml_content)
        _make_skill(skills_dir, "heavy-skill")

        tools = {"skill_view", "skills_list"}
        p1 = build_skills_system_prompt(available_tools=tools, skills_dir_override=skills_dir, platform="cli")
        assert "heavy-skill" in p1

        p2 = build_skills_system_prompt(available_tools=tools, skills_dir_override=skills_dir, platform="subagent")
        assert "heavy-skill" not in p2

        p3 = build_skills_system_prompt(available_tools=tools, skills_dir_override=skills_dir, platform="cli")
        assert "heavy-skill" in p3
