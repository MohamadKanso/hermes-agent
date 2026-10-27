## What does this PR do?

the standalone telegram send lane (`_telegram_bot` in `tools/send_message_senders.py`) built its `Bot` with no timeouts so it ran on ptb's 5s/1s defaults and ignored `HERMES_TELEGRAM_HTTP_*`. it now uses the same env vars and defaults as the gateway adapter (10/20/20/8) on both the proxy and no-proxy paths. also stopped logging the proxy url with `user:password` in it, it logs scheme://host:port now

## Related Issue

Fixes #145412

## Type of Change

- [x] Bug fix (non-breaking change that fixes an issue)
- [ ] New feature (non-breaking change that adds functionality)
- [ ] Security fix
- [ ] Documentation update
- [ ] Tests (adding or improving test coverage)
- [ ] Refactor (no behavior change)
- [ ] New skill (bundled or hub)

## Changes Made

- `tools/send_message_senders.py`: new `_telegram_http_timeouts()` reading the `HERMES_TELEGRAM_HTTP_*` timeouts, applied to every `Bot` the standalone lane builds, plus `_proxy_log_label()` so the log line has no credentials
- `tests/tools/test_send_message_telegram_proxy.py`: no-proxy bot now carries a `request`, new tests for env timeouts, defaults and the credential-free log
- `tests/tools/test_send_message_tool.py` and `tests/tools/test_telegram_send_message_caption.py`: telegram stubs accept `request` and expose `telegram.request`

## How to Test

1. `scripts/run_tests.sh tests/tools/test_send_message_telegram_proxy.py` fails 5 tests on main and passes with the change
2. ran the neighbouring send_message, telegram caption/video and cron scheduler tests, 17 files and 258 tests pass

## Checklist

### Code

- [x] I've read the Contributing Guide
- [x] My commit messages follow Conventional Commits
- [x] I searched for existing PRs to make sure this isn't a duplicate
- [x] My PR contains **only** changes related to this fix/feature
- [ ] I've run `pytest tests/ -q` and all tests pass
- [ ] `python scripts/check` passes
- [x] I've added tests for my changes
- [x] I've tested on my platform: Linux

### Documentation & Housekeeping

- [x] I've updated relevant documentation, or N/A
- [x] I've updated `cli-config.yaml.example` if I added/changed config keys, or N/A
- [x] I've updated `CONTRIBUTING.md` or `AGENTS.md`, or N/A
- [x] I've considered cross-platform impact, or N/A
- [x] I've updated tool descriptions/schemas, or N/A
