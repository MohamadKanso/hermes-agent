## What does this PR do?

a 403 whose body says `type: permission_error` was getting classified as billing whenever the gateway stamped a billing looking `code` on it, like omniroute does with `insufficient_quota` on a combo allow-list denial. the serialized body ends up in the message so `_BILLING_PATTERNS` matched the code, healthy credentials got rotated and the user was told to top up credits. now `_status_403()` trusts a permission `type` first and returns `provider_policy_blocked`, unless the human message itself names a billing quantity so real quota 403s still read as billing

## Related Issue

Fixes #146649

## Type of Change

- [x] Bug fix (non-breaking change that fixes an issue)
- [ ] New feature (non-breaking change that adds functionality)
- [ ] Security fix
- [ ] Documentation update
- [ ] Tests (adding or improving test coverage)
- [ ] Refactor (no behavior change)
- [ ] New skill (bundled or hub)

## Changes Made

- `agent/error_classifier.py`: new `_403_PERMISSION_REFUSAL_TYPES` and an early check in `_status_403()` that returns `_V_POLICY_BLOCKED` for those types when the message has no billing pattern
- `tests/agent/test_error_classifier.py`: one test for the omniroute shape (policy blocked, no credential rotation) and one that a permission_error body with a real quota message stays billing

## How to Test

1. `pytest tests/agent/test_error_classifier.py -k 403_permission_error`
2. on main the omniroute shape test fails (reason is billing), with the change it passes and the quota message case stays billing
3. full `tests/agent/test_error_classifier.py` passes (194) and the other `test_error_classifier_*.py` files pass apart from 2 reasoning_effort 400 cases in `test_error_classifier_reasoning_level.py` that fail the same way on clean main in my env

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
- [x] I've considered cross-platform impact (Windows, macOS) per the [compatibility guide](https://github.com/NousResearch/hermes-agent/blob/main/CONTRIBUTING.md#cross-platform-compatibility) — or N/A
- [x] I've updated tool descriptions/schemas if I changed tool behavior — or N/A
