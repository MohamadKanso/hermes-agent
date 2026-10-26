# outbox

Upstream actions waiting for the local poster on the owner's Mac (cloud runs cannot write to NousResearch).
One per line, exactly one of:
- `comment | <pr number> | <comment text>`
- `close | <pr number> | <closing comment text>`
- `ready | <pr number> | <optional short comment or ->`
- `pr | <branch> | <issue number or -> | <pr title>` (body in `bodies/<branch with / replaced by __>.md`)
The poster removes a line once it is done.

pr | docs/144424-in-place-compaction-lineage | #144424 | docs(sessions): describe in-place compaction as the default lineage behavior
close | 135334 | closing this one, #135726 already landed the docker baked extras fix on main
ready | 137982 | -
ready | 137868 | -
ready | 135528 | -
ready | 135070 | -
ready | 134924 | -
ready | 135045 | -
ready | 132413 | -
ready | 133998 | -
ready | 132418 | -
ready | 134907 | -
