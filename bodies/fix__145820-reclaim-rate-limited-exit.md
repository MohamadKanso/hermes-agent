## What does this PR do?

`release_stale_claims` runs before `detect_crashed_workers` in every reclaim phase, so when a worker exited 75 and its claim expired before a dispatcher pass settled it, the run got closed as `reclaimed` and counted a failure. two of those in a row hit the default `failure_limit` and the card went to `gave_up` even though every run only met a rate limit, and since the latest run wasn't `rate_limited` the respawn cooldown never kicked in either. now when the claim's worker is dead on this host `release_stale_claims` reads its exit the same way `detect_crashed_workers` does (reap registry, managed run result, then the log trailer) and if it's the rate limit code it closes the run as `rate_limited`, stamps `last_failure_error` and skips `_record_task_failure`. every other exit keeps the #111306 accounting

## Related Issue

Fixes #145820

## Type of Change

- [x] Bug fix (non-breaking change that fixes an issue)
- [ ] New feature (non-breaking change that adds functionality)
- [ ] Security fix
- [ ] Documentation update
- [ ] Tests (adding or improving test coverage)
- [ ] Refactor (no behavior change)
- [ ] New skill (bundled or hub)

## Changes Made

- `hermes_cli/kanban_db.py`: `release_stale_claims` classifies a dead host-local worker with `_classify_dead_worker_exit` before reclaiming, books a rate limited exit as a `rate_limited` run with no failure count, and `_record_reclaim` takes an optional `outcome` (default stays `reclaimed`). the `reclaimed` event payload gets a `rate_limited` flag
- `tests/hermes_cli/test_kanban_worker_exit_trailer.py`: new test where three expired claims in a row with an exit 75 trailer leave the card `ready` with 0 failures, `rate_limited` runs, no `gave_up` and the cooldown guard active, plus one that checks an exit 1 still counts a failure

## How to Test

1. `pytest tests/hermes_cli/test_kanban_worker_exit_trailer.py -q`
2. the new rate limit test fails on main (second reclaim blocks the card) and passes with the change, the other tests in the file still pass
3. ran the kanban test files under `tests/hermes_cli` plus `tests/gateway/test_kanban_reconcile_orphans.py`, same 30 failures before and after the change (they fail on clean main in my environment), no new ones
4. `ruff check` on both files is clean

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
