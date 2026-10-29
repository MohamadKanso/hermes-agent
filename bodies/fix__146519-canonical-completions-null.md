## What does this PR do?

a cron job record with `"canonical_completions": null` (key present, value null) made `mark_job_run` raise `TypeError` before the run got booked, so the dispatcher kept re-firing the job every minute. `dict.get(key, [])` only uses the default when the key is missing, so a stored `null` slipped through. now it reads the list the same way `cron/delivery_outcome.py` already does, with `or []`

## Related Issue

Fixes #146519

## Type of Change

- [x] Bug fix (non-breaking change that fixes an issue)

## Changes Made

- `cron/jobs.py` - `mark_job_run` treats a null `canonical_completions` as empty
- `tests/cron/test_canonical_completion_retention.py` - regression test that stores a null value and checks the run still books

## How to Test

1. `scripts/run_tests.sh tests/cron/test_canonical_completion_retention.py` - the new test fails with the `TypeError` on main and passes with the fix
2. ran `test_jobs.py`, `test_scheduler_completion_verification.py` and `test_jobs_shrink_merge.py` too, 127 tests pass

## Checklist

### Code

- [x] I've read the [Contributing Guide](https://github.com/NousResearch/hermes-agent/blob/main/CONTRIBUTING.md)
- [x] My commit messages follow [Conventional Commits](https://www.conventionalcommits.org/) (`fix(scope):`, `feat(scope):`, etc.)
- [x] I searched for [existing PRs](https://github.com/NousResearch/hermes-agent/pulls) to make sure this isn't a duplicate
- [x] My PR contains **only** changes related to this fix/feature (no unrelated commits)
- [ ] I've run `pytest tests/ -q` and all tests pass
- [ ] `python scripts/check` passes (the blocking lint and code-health checks CI runs)
- [x] I've added tests for my changes (required for bug fixes, strongly encouraged for features)
- [ ] I've tested on my platform

### Documentation & Housekeeping

- [x] I've updated relevant documentation (README, `docs/`, docstrings) — or N/A
- [x] I've updated `cli-config.yaml.example` if I added/changed config keys — or N/A
- [x] I've updated `CONTRIBUTING.md` or `AGENTS.md` if I changed architecture or workflows — or N/A
- [x] I've considered cross-platform impact (Windows, macOS) per the compatibility guide — or N/A
- [x] I've updated tool descriptions/schemas if I changed tool behavior — or N/A
