## What does this PR do?

the startup failure line in `hermes_bootstrap.py` was `hermes: {exc}; run `hermes pm repair``, so a cwd failure like a bare `[Errno 2] No such file or directory` sent people to rebuild a healthy dependency tree with no hint of what actually broke. it now says which step failed (`startup recovery` or `dependency activation`) and when an `OSError` has no filename it points at a deleted working directory instead of `pm repair`. `HERMES_BOOTSTRAP_DEBUG=1` also prints the traceback. errors that do carry a path or are plain `RuntimeError`s keep the `pm repair` advice

## Related Issue

Fixes #147781

## Type of Change

- [x] Bug fix (non-breaking change that fixes an issue)
- [ ] New feature (non-breaking change that adds functionality)
- [ ] Security fix
- [ ] Documentation update
- [ ] Tests (adding or improving test coverage)
- [ ] Refactor (no behavior change)
- [ ] New skill (bundled or hub)

## Changes Made

- `hermes_bootstrap.py`: track the current startup step, pick the remedy by whether the `OSError` names a file, optional traceback behind `HERMES_BOOTSTRAP_DEBUG`
- `tests/pm/test_runtime_selection.py`: new test for the three cases (fileless `OSError`, `OSError` with a path, `RuntimeError`)

## How to Test

1. stub `activate_dependencies` to raise `OSError(2, "No such file or directory")` and import `hermes_bootstrap` with a non-`pm` command
2. stderr now says `dependency activation failed` and the deleted directory hint, no `pm repair`
3. `pytest tests/pm/test_runtime_selection.py` the new test fails on main (2 of 3 cases) and passes here

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
