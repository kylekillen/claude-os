---
name: install-alpaca-mcp
description: Install Alpaca paper trading MCP server
version: 1.0.0
installs:
  - alpaca-mcp-server
requires:
  bins: ["uvx"]
  env: ["APCA_API_KEY_ID", "APCA_API_SECRET_KEY"]
---

# Install: Alpaca Paper Trading

## What This Installs

- Alpaca MCP server for paper trading via `uvx alpaca-mcp-server serve`
- 3 separate paper accounts configured

## Steps

### 1. Add MCP Server

Add to `~/.claude/settings.json` under `mcpServers`:

```json
"alpaca": {
  "command": "uvx",
  "args": ["alpaca-mcp-server", "serve"],
  "env": {
    "APCA_API_KEY_ID": "<key-id>",
    "APCA_API_SECRET_KEY": "<secret>",
    "ALPACA_PAPER_TRADE": "True"
  }
}
```

### 2. Verify

Test MCP server responds to Alpaca tool calls (list positions, check account).

## Key Notes

- Credentials at `~/.config/personal-os/alpaca.env` (3 separate paper accounts)
- `ALPACA_PAPER_TRADE=True` — always paper trading
- Trading bots: `~/claude-hedge-fund/` (AI energy thesis), `~/highvol-momentum-bot/` (momentum)
- When creating new bots, use `/new-alpaca-bot` skill for proper isolation
