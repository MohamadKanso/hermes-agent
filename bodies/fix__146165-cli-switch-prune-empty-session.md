## What does this PR do?

`/resume` and `/branch` in the classic cli ended the session row they were leaving but never pruned it, so switching before the first message left a titleless 0 message row in `hermes sessions list` and the `/resume` picker. `/new` and the tui quit path already call `_discard_session_if_empty` right after `end_session`, the switch path was the one that missed it. added the same call at the end of `_end_current_session`, which runs before the caller swaps `session_id` and `conversation_history` so the in memory transcript guard still protects unflushed turns

## Related Issue

Fixes #146165

## Type of Change

- [x] Bug fix (non-breaking change that fixes an issue)
- [ ] New feature (non-breaking change that adds functionality)
- [ ] Security fix
- [ ] Documentation update
- [ ] Tests (adding or improving test coverage)
- [ ] Refactor (no behavior change)
- [ ] New skill (bundled or hub)

## Changes Made

- `hermes_cli/cli_session_switch.py`: `_end_current_session` calls `cli._discard_session_if_empty(cli.session_id)` after `end_session`, still best effort
- `tests/hermes_cli/test_empty_session_hygiene.py`: three tests for the switch path, an empty row is dropped, a row with messages is kept, a row whose flush has not landed yet is kept
- `tests/hermes_cli/test_cli_resume_command.py`: the gateway store double now reports the old session as having content, otherwise the new prune adds a `session.resume` call the test does not care about

## How to Test

1. start the classic cli and run `/resume 1` before typing anything
2. the row you left is gone from `hermes sessions list` instead of lingering with `end_reason = resumed_other`
3. `scripts/run_tests.sh tests/hermes_cli/test_empty_session_hygiene.py` the new `test_switch_before_first_message_drops_the_row` fails on main and passes here

## Checklist

### Code

- [x] I've read the [Contributing Guide](https://github.com/NousResearch/hermes-agent/blob/main/CONTRIBUTING.md)
- [x] My commit messages follow [Conventional Commits](https://www.conventionalcommits.org/) (`fix(scope):`, `feat(scope):`, etc.)
- [x] I searched for [existing PRs](https://github.com/NousResearch/hermes-agent/pulls) to make sure this isn't a duplicate
- [x] My PR contains **only** changes related to this fix/feature (no unrelated commits)
- [ ] I've run `pytest tests/ -q` and all tests pass
- [ ] `python scripts/check` passes (the blocking lint and code-health checks CI runs)
- [x] I've added tests for my changes (required for bug fixes, strongly encouraged for features)
- [x] I've tested on my platform: Ubuntu, ran the touched test files and the neighbouring resume, branch, new session and exit tests in `tests/hermes_cli`

### Documentation & Housekeeping

- [x] I've updated relevant documentation (README, `docs/`, docstrings) — or N/A
- [x] I've updated `cli-config.yaml.example` if I added/changed config keys — or N/A
- [x] I've updated `CONTRIBUTING.md` or `AGENTS.md` if I changed architecture or workflows — or N/A
- [x] I've considered cross-platform impact (Windows, macOS) per the [compatibility guide](https://github.com/NousResearch/hermes-agent/blob/main/CONTRIBUTING.md#cross-platform-compatibility) — or N/A
- [x] I've updated tool descriptions/schemas if I changed tool behavior — or N/A
