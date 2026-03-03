---
name: install-parallel-search
description: Install Parallel AI MCP servers for fast web search and deep async research
version: 1.0.0
installs:
  - parallel-search-mcp
  - parallel-task-mcp
requires:
  bins: ["npx"]
  env: ["PARALLEL_API_KEY"]
---

# Install: Parallel Search & Deep Research

## What This Installs

- `parallel-search` MCP — fast web lookups (free tier)
- `parallel-task` MCP — deep async research (1-20 minutes, paid)
- Non-blocking architecture: start research, poll for results, continue working

## Steps

### 1. Get API Key

Sign up at parallel.ai for an API key.

### 2. Add MCP Servers

Add to `~/.claude/settings.json` under `mcpServers`:
```json
"parallel-search": {
  "command": "npx",
  "args": ["@anthropic/parallel-search-mcp"],
  "env": { "PARALLEL_API_KEY": "<key>" }
},
"parallel-task": {
  "command": "npx",
  "args": ["@anthropic/parallel-task-mcp"],
  "env": { "PARALLEL_API_KEY": "<key>" }
}
```

### 3. Verify

Test quick search: `mcp__parallel-search__search "test query"`
Test deep research: `mcp__parallel-task__create_task_run "research topic"`

## Usage

- **Quick search** (`mcp__parallel-search__search`): Fast web lookups, free
- **Deep research** (`mcp__parallel-task__create_task_run`): Comprehensive analysis, ask permission before using (costs money), poll for results non-blockingly
