## What does this PR do?

`hermes plugins update` fails for a plugin whose `pyproject.toml` has a `[dependency-groups]` table naming `hermes-agent` (the current honcho pin does this for its tests). `_workspace_member` copies the plugin pyproject into the generated workspace as is, and uv validates dependency groups for every workspace member, so it sees a member asking for the workspace root and refuses to lock. the update rolls back and blocks other plugins in the same workspace too

hermes only ever installs `[project].dependencies` from a member, so the generated member now drops `[dependency-groups]` (and `tool.uv.default-groups`, which would otherwise point at groups that no longer exist)

## Related Issue

Fixes #146435

## Type of Change

- [x] Bug fix (non-breaking change that fixes an issue)
- [ ] New feature (non-breaking change that adds functionality)
- [ ] Security fix
- [ ] Documentation update
- [ ] Tests (adding or improving test coverage)
- [ ] Refactor (no behavior change)
- [ ] New skill (bundled or hub)

## Changes Made

- `pm/workspace.py`: `_workspace_member` pops `dependency-groups` from the copied pyproject and clears `tool.uv.default-groups`, then marks the file as changed so it gets rewritten
- `tests/pm/test_member_selection.py`: new `test_member_drops_dependency_groups` using a honcho style pyproject

## How to Test

1. `python -m pytest tests/pm/test_member_selection.py -q`
2. on main the new test fails (`dependency-groups` still in the generated member), with the change all 8 pass

## Checklist

### Code

- [x] I've read the [Contributing Guide](https://github.com/NousResearch/hermes-agent/blob/main/CONTRIBUTING.md)
- [x] My commit messages follow [Conventional Commits](https://www.conventionalcommits.org/) (`fix(scope):`, `feat(scope):`, etc.)
- [x] I searched for [existing PRs](https://github.com/NousResearch/hermes-agent/pulls) to make sure this isn't a duplicate
- [x] My PR contains **only** changes related to this fix/feature (no unrelated commits)
- [ ] I've run `pytest tests/ -q` and all tests pass
- [ ] `python scripts/check` passes (the blocking lint and code-health checks CI runs)
- [x] I've added tests for my changes (required for bug fixes, strongly encouraged for features)
- [x] I've tested on my platform: Linux

### Documentation & Housekeeping

- [x] I've updated relevant documentation (README, `docs/`, docstrings) — or N/A
- [x] I've updated `cli-config.yaml.example` if I added/changed config keys — or N/A
- [x] I've updated `CONTRIBUTING.md` or `AGENTS.md` if I changed architecture or workflows — or N/A

only ran `tests/pm/test_member_selection.py` and `tests/pm/test_workspace*.py`. two failures in `test_workspace_build_inputs.py` happen on main too
