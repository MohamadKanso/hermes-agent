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
pr | fix/146059-numbered-env-resave | #146059 | fix(credentials): lift suppression when a removed numbered env key is saved again
pr | fix/146435-plugin-dependency-groups | #146435 | fix(pm): drop dependency-groups from generated plugin workspace members
close | 131647 | closing this one, main already stops a live renderer before the posix stage and swap rename (12a75a1ad4) so the guard here is covered by a different approach
close | 118489 | closing this one, main now adopts the published session token on the post-update relaunch (f1247d2e01) and the backend modules this touched were reworked
