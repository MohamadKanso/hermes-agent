## What does this PR do?

desktop and tui sessions only got `checkpoints.enabled` from config, the three limits never reached `AIAgent` so it always ran with the built in 20 snapshots / 500 MB / 10 MB. setting `checkpoints.max_total_size_mb: 1000` did nothing there, the cli and messaging gateway already pass them. added a small `resolve_checkpoint_limits` next to `resolve_checkpoints_enabled` and spread it into the agent kwargs in `_make_agent`

## Related Issue

Fixes #145268

## Type of Change

- [x] Bug fix (non-breaking change that fixes an issue)
- [ ] New feature (non-breaking change that adds functionality)
- [ ] Security fix
- [ ] Documentation update
- [ ] Tests (adding or improving test coverage)
- [ ] Refactor (no behavior change)
- [ ] New skill (bundled or hub)

## Changes Made

- `tui_gateway/checkpoints.py`: new `resolve_checkpoint_limits(cfg)` returning `checkpoint_max_snapshots`, `checkpoint_max_total_size_mb` and `checkpoint_max_file_size_mb` with per key `DEFAULT_CONFIG` fallback
- `tui_gateway/server.py`: import it like the other checkpoint helpers
- `tui_gateway/agent_factory.py`: pass the limits to `AIAgent` next to `checkpoints_enabled`
- `tests/tui_gateway/test_checkpoints_config_fallback.py`: helper tests plus one that checks the values reach the agent through `_make_agent`

## How to Test

1. set `checkpoints: {enabled: true, max_total_size_mb: 1000, max_snapshots: 5}` in `config.yaml`
2. start a desktop or tui session and check the agent's checkpoint manager, it now gets 1000 / 5 instead of 500 / 20
3. `scripts/run_tests.sh tests/tui_gateway/test_checkpoints_config_fallback.py` the new `test_limits_reach_agent` fails on main and passes here

## Checklist

### Code

- [x] I've read the [Contributing Guide](https://github.com/NousResearch/hermes-agent/blob/main/CONTRIBUTING.md)
- [x] My commit messages follow [Conventional Commits](https://www.conventionalcommits.org/) (`fix(scope):`, `feat(scope):`, etc.)
- [x] I searched for [existing PRs](https://github.com/NousResearch/hermes-agent/pulls) to make sure this isn't a duplicate
- [x] My PR contains **only** changes related to this fix/feature (no unrelated commits)
- [ ] I've run `pytest tests/ -q` and all tests pass
- [x] `python scripts/check` passes (the blocking lint and code-health checks CI runs)
- [x] I've added tests for my changes (required for bug fixes, strongly encouraged for features)
- [x] I've tested on my platform: Ubuntu, ran the touched test file and the neighbouring `tests/tui_gateway/test_make_agent_*` files

### Documentation & Housekeeping

- [x] I've updated relevant documentation (README, `docs/`, docstrings) — or N/A
- [x] I've updated `cli-config.yaml.example` if I added/changed config keys — or N/A
- [x] I've updated `CONTRIBUTING.md` or `AGENTS.md` if I changed architecture or workflows — or N/A
- [x] I've considered cross-platform impact (Windows, macOS) per the [compatibility guide](https://github.com/NousResearch/hermes-agent/blob/main/CONTRIBUTING.md#cross-platform-compatibility) — or N/A
- [x] I've updated tool descriptions/schemas if I changed tool behavior — or N/A
