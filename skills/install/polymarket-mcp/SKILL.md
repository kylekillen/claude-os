---
name: install-polymarket-mcp
description: Install Polymarket CLOB MCP server
version: 1.0.0
installs:
  - polymarket-mcp-server
requires:
  bins: ["npx"]
  env: ["POLY_PRIVATE_KEY"]
  npm_config: ["@jsr:registry=https://npm.jsr.io in ~/.npmrc"]
---

# Install: Polymarket MCP Server

## What This Installs

- Polymarket CLOB MCP server for accessing prediction markets
- Configured for Safe wallet mode (Gnosis Safe)

## Steps

### 1. Configure JSR Registry

Add to `~/.npmrc`:
```
@jsr:registry=https://npm.jsr.io
```

### 2. Add MCP Server

Add to `~/.claude/settings.json` under `mcpServers`:

```json
"polymarket": {
  "command": "npx",
  "args": ["@jsr/iqai__mcp-polymarket"],
  "env": {
    "POLY_PRIVATE_KEY": "<private-key>",
    "POLY_API_KEY": "<api-key>",
    "POLY_API_SECRET": "<api-secret>",
    "POLY_PASSPHRASE": "<passphrase>"
  }
}
```

### 3. Verify

Test MCP server responds to Polymarket tool calls.

## Key Notes

- Safe mode verified working — positions land at Safe address `0x5953...`
- Kyle handles Poly redemptions manually via VPN — do NOT automate redemptions
- CLOB status is CASE SENSITIVE — `get_order()` returns "MATCHED" (uppercase)
- Use CLOB `/book?token_id=X` for executable prices, NOT gamma API bestBid/bestAsk
- Poly-first execution — never commit Kalshi before Poly confirmed
- FOK does NOT work on neg-risk markets — use GTC + poll + cancel (~3s)
