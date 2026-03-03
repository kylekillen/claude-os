---
name: check-updates
description: Use this skill when the user asks to "check for updates", "any new features", "what's new with claude", "check anthropic news", or wants to know about Claude Code updates.
---

# Check for Updates

Monitor the Anthropic ecosystem for new Claude Code features and releases.

## Manual Check Method

Use these web tools to check for updates:

1. **Anthropic News** — Visit https://anthropic.com/news for announcements
2. **Claude Code Releases** — Check https://github.com/anthropics/claude-code for releases
3. **Claude Documentation** — Visit https://docs.anthropic.com for API/feature updates
4. **MCP Specification** — Check https://github.com/modelcontextprotocol/specification

## What Gets Checked

| Source | Priority | Tracks |
|--------|----------|--------|
| Anthropic News | HIGH | New announcements, features |
| Claude Code Releases | HIGH | New versions, changelogs |
| Claude Docs | MEDIUM | Documentation updates |
| MCP Docs | MEDIUM | Protocol changes |

## After Checking

If updates are found:
1. Explain what changed in plain English
2. Assess whether it affects current workflows
3. Recommend any actions to consider

## Rules

1. Web page changes may be false positives (dynamic content)
2. GitHub releases are the most reliable signal
3. If a significant upgrade is found, ask the user if they want to install it
