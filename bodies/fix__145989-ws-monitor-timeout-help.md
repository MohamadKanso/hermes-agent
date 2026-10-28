## What does this PR do?

`ws_monitor.py --timeout` was documented as a "hard cap on monitor duration" but it only goes to `create_connection` and `settimeout`, and the `recv` loop has no total deadline. a stream of messages keeps the monitor alive past the value. the help now calls it an idle socket timeout, which matches the existing "Idle for ..." exit branch. help string only, no behavior change

## Related Issue

Fixes #145989

## Type of Change

- [x] Bug fix (non-breaking change that fixes an issue)
- [ ] New feature (non-breaking change that adds functionality)
- [ ] Security fix
- [ ] Documentation update
- [ ] Tests (adding or improving test coverage)
- [ ] Refactor (no behavior change)
- [ ] New skill (bundled or hub)

## Changes Made

- `optional-skills/creative/comfyui/scripts/ws_monitor.py`: reworded the `--timeout` help
- `tests/skills/test_comfyui_skill.py`: new test that runs `ws_monitor.py --help` and checks it says idle socket timeout and no longer says hard cap

## How to Test

1. `pytest tests/skills/test_comfyui_skill.py -q`
2. new test fails on main (old help text) and passes with the change, the two existing tests in the file still pass

## Checklist

### Code

- [x] I've read the Contributing Guide
- [x] My commit messages follow Conventional Commits
- [x] I searched for existing PRs to make sure this isn't a duplicate
- [x] My PR contains only changes related to this fix
- [ ] I've run `pytest tests/ -q` and all tests pass
- [ ] `python scripts/check` passes
- [x] I've added tests for my changes
- [x] I've tested on my platform: Linux

### Documentation & Housekeeping

- [x] I've updated relevant documentation, N/A
- [x] I've updated `cli-config.yaml.example`, N/A
- [x] I've updated `CONTRIBUTING.md` or `AGENTS.md`, N/A
- [x] I've considered cross-platform impact, N/A
- [x] I've updated tool descriptions/schemas, N/A
