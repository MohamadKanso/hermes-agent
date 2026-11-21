# outbox

Upstream actions waiting for the local poster on the owner's Mac (cloud runs cannot write to NousResearch).
One per line, exactly one of:
- `comment | <pr number> | <comment text>`
- `close | <pr number> | <closing comment text>`
- `ready | <pr number> | <optional short comment or ->`
- `pr | <branch> | <issue number or -> | <pr title>` (body in `bodies/<branch with / replaced by __>.md`)
The poster removes a line once it is done.

pr | fix/145545-comfyui-timeout-hint | #145545 | fix(comfyui): point the wait-timeout hint back at the submitted job
pr | fix/145820-reclaim-rate-limited-exit | #145820 | fix(kanban): book an expired claim of a rate-limited worker as rate_limited
pr | fix/146059-numbered-env-resave | #146059 | fix(credentials): lift suppression when a removed numbered env key is saved again
pr | fix/146435-plugin-dependency-groups | #146435 | fix(pm): drop dependency-groups from generated plugin workspace members
pr | fix/147781-bootstrap-failure-context | #147781 | fix(bootstrap): name the failing startup step and stop blaming dependencies for cwd errors
comment | 134907 | thanks for the field data. moving the `_scratch_pruned_roots.add` after the hourly check does make sense but it changes the once per process behaviour to a stat on every call, so keeping it out of this one to stay small and happy to take it as a follow up if a maintainer wants it
