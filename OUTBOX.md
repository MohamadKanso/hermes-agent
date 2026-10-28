# outbox

Upstream actions waiting for the local poster on the owner's Mac (cloud runs cannot write to NousResearch).
One per line, exactly one of:
- `comment | <pr number> | <comment text>`
- `close | <pr number> | <closing comment text>`
- `ready | <pr number> | <optional short comment or ->`
- `pr | <branch> | <issue number or -> | <pr title>` (body in `bodies/<branch with / replaced by __>.md`)
The poster removes a line once it is done.

pr | fix/145268-tui-checkpoint-limits | #145268 | fix(tui-gateway): pass checkpoint size and count limits from config to desktop and tui agents
pr | fix/145545-comfyui-timeout-hint | #145545 | fix(comfyui): point the wait-timeout hint back at the submitted job
pr | fix/145820-reclaim-rate-limited-exit | #145820 | fix(kanban): book an expired claim of a rate-limited worker as rate_limited
pr | fix/145989-ws-monitor-timeout-help | #145989 | fix(comfyui): describe ws_monitor --timeout as an idle socket timeout
