## What does this PR do?

the collapsed tool-run header in the desktop app counted every call in the live category and put the whole count in the present tense, so a turn with 22 finished commands and one in flight read `Running 23 commands`. `clause()` in `run-summary.ts` now splits a live category into settled and pending calls, so it reads `Ran 22 commands, running npm test` and only calls that are actually pending get the present tense. when nothing is pending (the gap between two sequential calls) it keeps narrating like before so the ticker intent stays

## Related Issue

Fixes #145748

## Type of Change

- [x] Bug fix (non-breaking change that fixes an issue)
- [ ] New feature (non-breaking change that adds functionality)
- [ ] Security fix (undisclosed vulnerabilities in [SECURITY.md](https://github.com/NousResearch/hermes-agent/blob/main/SECURITY.md) §3.1 scope go to [Security Advisories](https://github.com/NousResearch/hermes-agent/security/advisories/new) first, not a public PR)
- [ ] Documentation update
- [ ] Tests (adding or improving test coverage)
- [ ] Refactor (no behavior change)
- [ ] New skill (bundled or hub)

## Changes Made

- `apps/desktop/src/components/assistant-ui/tool/run-summary.ts`: `clause()` splits a live category by `isPending` and joins the past clause and the present clause
- `apps/desktop/src/components/assistant-ui/tool/run-summary.test.ts`: new case for 22 settled plus 1 or 2 pending commands, and the existing mixed read case now expects `Explored a.ts, exploring b.ts, ran 2 commands` since b.ts is the pending one

## How to Test

1. `cd apps/desktop && npx vitest run --project ui src/components/assistant-ui/tool src/lib/chat-messages`
2. the new test fails on main (`Running 23 commands`) and passes with the change
3. `npx tsc --noEmit` and prettier are clean

## Checklist

### Code

- [x] I've read the [Contributing Guide](https://github.com/NousResearch/hermes-agent/blob/main/CONTRIBUTING.md)
- [x] My commit messages follow [Conventional Commits](https://www.conventionalcommits.org/) (`fix(scope):`, `feat(scope):`, etc.)
- [x] I searched for [existing PRs](https://github.com/NousResearch/hermes-agent/pulls) to make sure this isn't a duplicate
- [x] My PR contains **only** changes related to this fix/feature (no unrelated commits)
- [ ] I've run `pytest tests/ -q` and all tests pass
- [ ] `python scripts/check` passes (the blocking lint and code-health checks CI runs)
- [x] I've added tests for my changes (required for bug fixes, strongly encouraged for features)
- [ ] I've tested on my platform: linux, vitest only

### Documentation & Housekeeping

- [x] I've updated relevant documentation (README, `docs/`, docstrings) — or N/A
- [x] I've updated `cli-config.yaml.example` if I added/changed config keys — or N/A
- [x] I've updated `CONTRIBUTING.md` or `AGENTS.md` if I changed architecture or workflows — or N/A
- [x] I've considered cross-platform impact (Windows, macOS) per the [compatibility guide](https://github.com/NousResearch/hermes-agent/blob/main/CONTRIBUTING.md#cross-platform-compatibility) — or N/A
- [x] I've updated tool descriptions/schemas if I changed tool behavior — or N/A
