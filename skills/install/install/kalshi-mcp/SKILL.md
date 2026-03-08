---
name: install-kalshi-mcp
description: Install Kalshi prediction market MCP server and position monitor
version: 1.0.0
installs:
  - kalshi-mcp-server
  - position-monitor
requires:
  bins: ["npx", "python3"]
  files: ["mojo-work/kalshi-polymarket-arb/keys/kalshi.pem"]
---

# Install: Kalshi MCP Server

## What This Installs

- Kalshi MCP server (`@iqai/mcp-kalshi`) for API access to prediction markets
- Position monitor (`~/kalshi-position-monitor/`) for tracking positions and generating research triggers
- Thesis researcher for position health analysis

## Steps

### 1. Add MCP Server

Add to `~/.claude/settings.json` under `mcpServers`:

```json
"kalshi": {
  "command": "npx",
  "args": ["@iqai/mcp-kalshi"],
  "env": {
    "KALSHI_API_KEY_ID": "<key-id>",
    "KALSHI_API_PRIVATE_KEY_PATH": "<path-to-kalshi.pem>"
  }
}
```

### 2. Install Position Monitor

```bash
cd ~/kalshi-position-monitor
python3 -m venv venv
source venv/bin/activate
pip install -r requirements.txt
```

### 3. Test Connection

```bash
cd ~/kalshi-position-monitor && source venv/bin/activate && python monitor.py --once
```

### 4. Verify

- MCP server responds to Kalshi tool calls
- Monitor outputs to `~/.kalshi-monitor/positions-current.md`
- Research triggers written to `~/.kalshi-monitor/pending-research/`

## Key Notes

- API rate limit: ~5 requests/sec safe for orderbook fetches
- Fee formula: `ceil(rate * P * (1-P) * 100)` — taker 7%, maker 1.75%
- Orderbook endpoint (`/markets/{ticker}/orderbook`) has real prices even when market summary fields are empty
- FOK orders DO work on Kalshi (contrary to earlier belief about neg-risk markets)

## Usage

```bash
# Quick position check
cd ~/kalshi-position-monitor && source venv/bin/activate && python monitor.py --once

# Continuous monitoring
cd ~/kalshi-position-monitor && source venv/bin/activate && python monitor.py

# Research specific position
cd ~/kalshi-position-monitor && source venv/bin/activate && python thesis_researcher.py --position TICKER
```
