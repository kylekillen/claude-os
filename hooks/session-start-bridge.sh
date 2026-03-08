#!/bin/bash
# Bridge: SessionStart command hook → HTTP hooks server
# SessionStart only supports command hooks, not HTTP hooks.
# This script reads stdin (Claude Code's JSON payload) and forwards it to the HTTP server.
curl -s -X POST http://127.0.0.1:9090/hooks/SessionStart \
  -H 'Content-Type: application/json' \
  -d @- \
  --max-time 10
