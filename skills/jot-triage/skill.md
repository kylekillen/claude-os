---
name: jot-triage
description: Use this skill when Kyle says "triage jot file", "process the backlog", "go through jot items", "what's in the jot file", or wants to work through captured ideas.
---

# Jot File Triage

Work through ingested jot file items and decide what to do with each.

## Setup

Open the file in VS Code so Kyle can follow along:
```bash
open -a "Visual Studio Code" "/Users/kylekillen/Library/CloudStorage/GoogleDrive-kyle.killen@gmail.com/My Drive/Personal-OS-v2/drafts/jot-file-ingested.md"
```

Then read the ingested items:
```
/Users/kylekillen/Library/CloudStorage/GoogleDrive-kyle.killen@gmail.com/My Drive/Personal-OS-v2/drafts/jot-file-ingested.md
```

## For Each Item

Present the item and ask Kyle what it should become:

1. **Task** — Add to Google Tasks (actionable, has a clear next step)
2. **Project** — Create a project brief in `drafts/projects/` (needs planning, multiple steps)
3. **Capability** — Add to Personal OS backlog (something for Claude to build)
4. **Reference** — Move to appropriate domain folder (info to keep, not actionable)
5. **Archive** — Mark as processed, no action needed
6. **Expand** — Kyle wants to talk through it more before deciding

## After Processing

Mark items as processed by adding `[PROCESSED]` prefix or moving to an archive section.

## Pacing

Go at Kyle's pace. Can do a few items or many. Ask "Keep going?" periodically.
