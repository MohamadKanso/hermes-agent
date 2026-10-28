## What does this PR do?

re-saving a removed numbered env key like `DEEPSEEK_API_KEY_2` left `env:DEEPSEEK_API_KEY_2` suppressed so the key was never used again even though the save said ok. `save_provider_env_credential` looked up providers by exact `api_key_env_vars` match and a `_2` sibling matches nothing so nothing got unsuppressed and no `load_pool()` ran. the save path now resolves a `VAR_n` (n >= 2) to the providers that own `VAR`, same idea as `_env_key_var_candidates` in the credential pool. the remove path is untouched so deleting an extra key doesn't wipe the models cache of a provider that still has its base key

## Related Issue

Fixes #146059

## Type of Change

- [x] Bug fix (non-breaking change that fixes an issue)
- [ ] New feature (non-breaking change that adds functionality)
- [ ] Security fix
- [ ] Documentation update
- [ ] Tests (adding or improving test coverage)
- [ ] Refactor (no behavior change)
- [ ] New skill (bundled or hub)

## Changes Made

- `hermes_cli/credential_lifecycle.py`: `_providers_for_env_var` takes a `numbered` flag that also matches the base var of a `VAR_n` sibling, `save_provider_env_credential` passes it
- `tests/hermes_cli/test_credential_lifecycle.py`: put, delete, put again of `ZAI_API_KEY_2` through `/api/env` and check the source is no longer suppressed and the pool row is back

## How to Test

1. put `ZAI_API_KEY` in `.env`, `PUT /api/env` with `ZAI_API_KEY_2`, then `DELETE /api/env` for it and `PUT` it again
2. `is_source_suppressed("zai", "env:ZAI_API_KEY_2")` is now false and `load_pool("zai")` has the row
3. `pytest tests/hermes_cli/test_credential_lifecycle.py` the new `test_resave_removed_numbered_env_key_is_used_again` fails on main and passes here

## Checklist

### Code

- [x] I've read the [Contributing Guide](https://github.com/NousResearch/hermes-agent/blob/main/CONTRIBUTING.md)
- [x] My commit messages follow [Conventional Commits](https://www.conventionalcommits.org/) (`fix(scope):`, `feat(scope):`, etc.)
- [x] I searched for [existing PRs](https://github.com/NousResearch/hermes-agent/pulls) to make sure this isn't a duplicate
- [x] My PR contains **only** changes related to this fix/feature (no unrelated commits)
- [ ] I've run `pytest tests/ -q` and all tests pass
- [ ] `python scripts/check` passes (the blocking lint and code-health checks CI runs)
- [x] I've added tests for my changes (required for bug fixes, strongly encouraged for features)
- [x] I've tested on my platform: Linux, ran `test_credential_lifecycle.py` and `test_dashboard_admin_endpoints.py`

### Documentation & Housekeeping

- [x] I've updated relevant documentation (README, `docs/`, docstrings) — or N/A
- [x] I've updated `cli-config.yaml.example` if I added/changed config keys — or N/A
- [x] I've updated `CONTRIBUTING.md` or `AGENTS.md` if I changed architecture or workflows — or N/A
- [x] I've considered cross-platform impact (Windows, macOS) per the [compatibility guide](https://github.com/NousResearch/hermes-agent/blob/main/CONTRIBUTING.md#cross-platform-compatibility) — or N/A
- [x] I've updated tool descriptions/schemas if I changed tool behavior — or N/A
