---
name: install-ntfy
description: Install ntfy push notifications MCP server for mobile/desktop alerts
version: 1.1.0
installs:
  - ntfy-me-mcp
requires:
  bins: ["npx"]
---

# Install: ntfy Push Notifications

## What This Installs

- ntfy-me-mcp (gitmotion) MCP server for sending push notifications to phone/desktop
- Uses ntfy.sh (free, no account required) or self-hosted instance
- Provides `ntfy_me` (send) and `ntfy_me_fetch` (read) MCP tools

## Steps

### 1. Add MCP Server

Add to `~/.claude/settings.json` under `mcpServers`:
```json
"ntfy": {
  "command": "npx",
  "args": ["-y", "ntfy-me-mcp"],
  "env": {
    "NTFY_TOPIC": "mojo-alerts-kk"
  }
}
```

Note: `@cyanheads/ntfy-mcp-server` has a path resolution bug and does NOT work.
`ntfy-me-mcp` (gitmotion) is the working alternative.

### 2. Install ntfy App

- iOS: Search "ntfy" in App Store
- Android: Search "ntfy" in Play Store
- Subscribe to topic: `mojo-alerts-kk`

### 3. Verify

Send a test notification using the MCP `ntfy_me` tool, or via curl:
```bash
curl -d "Test message" -H "Title: Test" https://ntfy.sh/mojo-alerts-kk
```

## Usage

Use MCP ntfy tools to send notifications when:
- Heartbeat daemon completes a task
- Trading bot fires a signal or executes a trade
- Research agents complete background work
- Any alert-worthy event occurs

Topic: `mojo-alerts-kk`
