# outbox

Upstream actions waiting for the local poster on the owner's Mac (cloud runs cannot write to NousResearch).
One per line, exactly one of:
- `comment | <pr number> | <comment text>`
- `close | <pr number> | <closing comment text>`
- `ready | <pr number> | <optional short comment or ->`
- `pr | <branch> | <issue number or -> | <pr title>` (body in `bodies/<branch with / replaced by __>.md`)
The poster removes a line once it is done.

pr | docs/144424-in-place-compaction-lineage | #144424 | docs(sessions): describe in-place compaction as the default lineage behavior
pr | fix/145268-tui-checkpoint-limits | #145268 | fix(tui-gateway): pass checkpoint size and count limits from config to desktop and tui agents
