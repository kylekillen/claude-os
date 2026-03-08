---
name: install-context7
description: Install Context7 for pulling live library documentation into context
version: 1.0.0
installs:
  - context7-mcp-server
requires:
  bins: ["npx"]
---

# Install: Context7 (Live Documentation)

## What This Installs

- Context7 MCP server (46K GitHub stars) that pulls current library/API documentation
- Prevents hallucination on API calls, SDK methods, and framework patterns
- Searches across thousands of libraries automatically

## Steps

### 1. Add MCP Server

Add to `~/.claude/settings.json` under `mcpServers`:
```json
"context7": {
  "command": "npx",
  "args": ["@upstash/context7-mcp"]
}
```

### 2. Verify

Test by asking about a library's API — Context7 should provide current docs.

## Usage

Context7 activates automatically when coding. When you're working with any library or API, it pulls the latest documentation so responses use current syntax and methods.
