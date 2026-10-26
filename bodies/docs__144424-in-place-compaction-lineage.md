## What does this PR do?

the auto-lineage section in the sessions guide still says `/compress` always spins up a new continuation session with a numbered title. that stopped being true once `compression.in_place` started defaulting to `true`, the session id just stays the same now. updated the docs so they match what actually happens by default and kept the old lineage bit for anyone running `in_place: false`

## Related Issue

Fixes #144424

## Type of Change

- [ ] Bug fix (non-breaking change that fixes an issue)
- [ ] New feature (non-breaking change that adds functionality)
- [ ] Security fix
- [x] Documentation update
- [ ] Tests (adding or improving test coverage)
- [ ] Refactor (no behavior change)
- [ ] New skill (bundled or hub)

## Changes Made

- `website/docs/user-guide/sessions.md`: auto-lineage section now says in-place compaction is the default and keeps the same session id
- the continuation session and `name #2` title stuff is now scoped to `compression.in_place: false`
- added a line on resume by name only mattering for older rotated sessions or `in_place: false`

## How to Test

1. check `agent/agent_init.py`, `in_place` defaults to `True`
2. run `/compress` on a titled session with default config, the id and title stay the same
3. set `compression.in_place: false` and compress again, you get the `#2` continuation like the docs describe

## Checklist

### Code

- [x] I've read the [Contributing Guide](https://github.com/NousResearch/hermes-agent/blob/main/CONTRIBUTING.md)
- [x] My commit messages follow [Conventional Commits](https://www.conventionalcommits.org/) (`fix(scope):`, `feat(scope):`, etc.)
- [x] I searched for [existing PRs](https://github.com/NousResearch/hermes-agent/pulls) to make sure this isn't a duplicate
- [x] My PR contains **only** changes related to this fix/feature (no unrelated commits)
- [ ] I've run `pytest tests/ -q` and all tests pass
- [ ] `python scripts/check` passes (the blocking lint and code-health checks CI runs)
- [ ] I've added tests for my changes (required for bug fixes, strongly encouraged for features)
- [x] I've tested on my platform: macOS

### Documentation & Housekeeping

- [x] I've updated relevant documentation (README, `docs/`, docstrings) — or N/A
- [x] I've updated `cli-config.yaml.example` if I added/changed config keys — or N/A
- [x] I've updated `CONTRIBUTING.md` or `AGENTS.md` if I changed architecture or workflows — or N/A
