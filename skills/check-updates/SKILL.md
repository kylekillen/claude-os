---
name: check-updates
description: Use this skill when the user asks to "check for updates", "any new features", "what's new with claude", "check anthropic news", or wants to know about Claude Code updates.
---

# Check for Updates

Monitor the Anthropic ecosystem for new Claude Code features and releases.

## Commands

```bash
# Normal check (only reports new changes)
python3 /Users/kylekillen/Library/CloudStorage/GoogleDrive-kyle.killen@gmail.com/My Drive/Personal-OS-v2/system/scripts/check_updates.py

# Force check everything (ignore previous state)
python3 /Users/kylekillen/Library/CloudStorage/GoogleDrive-kyle.killen@gmail.com/My Drive/Personal-OS-v2/system/scripts/check_updates.py --force

# Sync state to Drive after check
python3 /Users/kylekillen/Library/CloudStorage/GoogleDrive-kyle.killen@gmail.com/My Drive/Personal-OS-v2/system/scripts/check_updates.py --sync
```

## What Gets Checked

| Source | Priority | Tracks |
|--------|----------|--------|
| Anthropic News | HIGH | New announcements, features |
| Claude Code Releases | HIGH | New versions, changelogs |
| Claude Docs | MEDIUM | Documentation updates |
| MCP Docs | MEDIUM | Protocol changes |

## After Running

If updates are found:
1. Explain what changed in plain English
2. Assess whether it affects what we can do together
3. Recommend any actions to consider

State is stored at `~/.config/personal-os/update-state.json`.

## Rules

1. Web page changes may be false positives (dynamic content)
2. GitHub releases are the most reliable signal
3. If a significant upgrade is found, ask Kyle if he wants to install it
