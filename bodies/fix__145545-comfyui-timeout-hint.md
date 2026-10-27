## What does this PR do?

the timeout payload from `run_workflow.py` told callers to "re-run with larger --timeout, or use --submit-only and check later". but the job was already submitted and nothing cancels it on timeout, and both of those suggestions go through `submit()` again so you end up with a second job. the hint now says the job may still be queued or running, points at `fetch_logs.py <prompt_id> --raw` with the same `--host` and `--api-key` or `$COMFY_CLOUD_API_KEY`, mentions `--tail-queue` for local jobs that are not in history yet, and says not to re-run just because the wait timed out

## Related Issue

Fixes #145545

## Type of Change

- [x] Bug fix (non-breaking change that fixes an issue)
- [ ] New feature (non-breaking change that adds functionality)
- [ ] Security fix
- [ ] Documentation update
- [ ] Tests (adding or improving test coverage)
- [ ] Refactor (no behavior change)
- [ ] New skill (bundled or hub)

## Changes Made

- `optional-skills/creative/comfyui/scripts/run_workflow.py`: reworded the `hint` in the timeout branch of `main()`, no other field or exit code changes
- `tests/skills/test_comfyui_skill.py`: new test that drives `main()` to a timeout with a fake `ComfyRunner` and checks exactly one submit, the lookup commands in the hint and that `--submit-only` and `larger --timeout` are gone

## How to Test

1. `pytest tests/skills/test_comfyui_skill.py -q`
2. new test fails on main (old hint) and passes with the change, the two existing tests in the file still pass
3. `ruff check` on both files is clean

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
