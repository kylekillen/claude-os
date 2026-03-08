---
name: install-sqlite-mcp
description: Install SQLite MCP server for direct database access (memory DB, etc.)
version: 1.0.0
installs:
  - sqlite-mcp-server
requires:
  bins: ["npx"]
---

# Install: SQLite MCP Server

## What This Installs

- Direct SQLite access via MCP tools — query, inspect schema, read/write
- Primary use: debug and query `~/.claude-mem/claude-mem.db` (memory system)

## Steps

### 1. Add MCP Server

Add to `~/.claude/settings.json` under `mcpServers`:
```json
"sqlite": {
  "command": "npx",
  "args": ["@modelcontextprotocol/server-sqlite", "--db-path", "/Users/kylekillen/.claude-mem/claude-mem.db"]
}
```

### 2. Verify

Query the memories table:
```sql
SELECT COUNT(*) FROM memories;
SELECT * FROM memories ORDER BY updated_at DESC LIMIT 5;
```

## Key Databases

| Database | Purpose |
|----------|---------|
| `~/.claude-mem/claude-mem.db` | Memory system (observations, memories, entities) |
