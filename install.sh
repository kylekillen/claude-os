#!/bin/bash
set -e

# ════════════════════════════════════════════════
# Claude OS v3 Installer
# Markdown-first memory for Claude Code
# Zero API cost — everything runs locally
# ════════════════════════════════════════════════

SCRIPT_DIR="$(cd "$(dirname "$0")" && pwd)"
CLAUDE_DIR="$HOME/.claude"
MEM_DIR="$HOME/.claude-mem"
VENV_DIR="$MEM_DIR/venv"
INDEX_DB="$MEM_DIR/markdown-index.db"
DAEMON_DIR="$HOME/mojo-daemon"

# Colors
GREEN='\033[0;32m'
YELLOW='\033[1;33m'
RED='\033[0;31m'
BLUE='\033[0;34m'
BOLD='\033[1m'
NC='\033[0m'

info()  { echo -e "${BLUE}▸${NC} $1"; }
ok()    { echo -e "${GREEN}✓${NC} $1"; }
warn()  { echo -e "${YELLOW}!${NC} $1"; }
fail()  { echo -e "${RED}✗${NC} $1"; exit 1; }

echo ""
echo -e "${BOLD}════════════════════════════════════════${NC}"
echo -e "${BOLD}       Claude OS v3 Installer${NC}"
echo -e "${BOLD}  Markdown-First Memory for Claude Code${NC}"
echo -e "${BOLD}════════════════════════════════════════${NC}"
echo ""

# ── Step 1: Name your assistant ──
echo -e "${BOLD}What would you like to name your AI assistant?${NC}"
echo "  (This name will appear in your CLAUDE.md instructions)"
echo "  Press Enter for default: Claude"
read -r -p "  Name: " ASSISTANT_NAME
ASSISTANT_NAME="${ASSISTANT_NAME:-Claude}"
echo ""
ok "Your assistant will be called ${BOLD}${ASSISTANT_NAME}${NC}"
echo ""

# ── Step 2: Check prerequisites ──
echo -e "${BOLD}Checking prerequisites...${NC}"

# Check Claude Code
if command -v claude &>/dev/null; then
    CLAUDE_VERSION=$(claude --version 2>/dev/null | head -1 || echo "unknown")
    ok "Claude Code installed ($CLAUDE_VERSION)"
else
    fail "Claude Code not found. Install it first: https://docs.anthropic.com/en/docs/claude-code/getting-started"
fi

# Check Python
PYTHON_CMD=""
for cmd in python3.13 python3.12 python3.11 python3.10 python3; do
    if command -v "$cmd" &>/dev/null; then
        PY_VER=$("$cmd" --version 2>&1 | grep -oE '[0-9]+\.[0-9]+')
        PY_MAJOR=$(echo "$PY_VER" | cut -d. -f1)
        PY_MINOR=$(echo "$PY_VER" | cut -d. -f2)
        if [ "$PY_MAJOR" -ge 3 ] && [ "$PY_MINOR" -ge 10 ]; then
            PYTHON_CMD="$cmd"
            break
        fi
    fi
done

if [ -z "$PYTHON_CMD" ]; then
    fail "Python 3.10+ required. Install from python.org or: brew install python@3.13"
fi
ok "Python found: $($PYTHON_CMD --version)"

# Check sqlite3
if command -v sqlite3 &>/dev/null; then
    ok "SQLite3 available"
else
    fail "sqlite3 not found. Install it: brew install sqlite3"
fi

# ── Step 3: AgentMail (optional) ──
echo ""
echo -e "${BOLD}AgentMail (optional)${NC}"
echo "  Give your assistant its own email address (e.g., ${ASSISTANT_NAME,,}@agentmail.to)"
echo "  Get a free API key at: https://agentmail.to"
echo ""
read -r -p "  AgentMail API key (am_... or press Enter to skip): " AGENTMAIL_KEY
ASSISTANT_EMAIL=""
if [ -n "$AGENTMAIL_KEY" ]; then
    read -r -p "  Email address (e.g., ${ASSISTANT_NAME,,}): " ASSISTANT_EMAIL
    ASSISTANT_EMAIL="${ASSISTANT_EMAIL:-${ASSISTANT_NAME,,}}"
    ok "AgentMail: ${ASSISTANT_EMAIL}@agentmail.to"
else
    warn "No AgentMail — assistant won't have email (can add later)"
fi

# ── Step 4: Create directory structure ──
echo ""
echo -e "${BOLD}Setting up directories...${NC}"

mkdir -p "$CLAUDE_DIR/hooks/http-server"
mkdir -p "$CLAUDE_DIR/scripts"
mkdir -p "$CLAUDE_DIR/skills"
mkdir -p "$CLAUDE_DIR/agents"
mkdir -p "$MEM_DIR/logs"
mkdir -p "$MEM_DIR/session-narratives"
mkdir -p "$DAEMON_DIR/src"
mkdir -p "$DAEMON_DIR/logs"
mkdir -p "$DAEMON_DIR/state"
mkdir -p "$DAEMON_DIR/results"
ok "Directory structure created"

# ── Step 5: Copy hooks ──
echo ""
echo -e "${BOLD}Installing hooks...${NC}"

cp "$SCRIPT_DIR/hooks/http-server/server.py" "$CLAUDE_DIR/hooks/http-server/server.py"
cp "$SCRIPT_DIR/hooks/http-server/manage.sh" "$CLAUDE_DIR/hooks/http-server/manage.sh"
chmod +x "$CLAUDE_DIR/hooks/http-server/manage.sh"
if [ -f "$SCRIPT_DIR/hooks/http-server/test-pipeline.sh" ]; then
    cp "$SCRIPT_DIR/hooks/http-server/test-pipeline.sh" "$CLAUDE_DIR/hooks/http-server/test-pipeline.sh"
    chmod +x "$CLAUDE_DIR/hooks/http-server/test-pipeline.sh"
fi

# Session start bridge
cp "$SCRIPT_DIR/hooks/session-start-bridge.sh" "$CLAUDE_DIR/hooks/session-start-bridge.sh"
chmod +x "$CLAUDE_DIR/hooks/session-start-bridge.sh"

# Guard hooks (file size check, bash-cat prevention, pre-compact backup)
for guard in check-file-size.py check-bash-cat.py pre-compact-backup.py; do
    if [ -f "$SCRIPT_DIR/hooks/$guard" ]; then
        cp "$SCRIPT_DIR/hooks/$guard" "$CLAUDE_DIR/hooks/$guard"
        chmod +x "$CLAUDE_DIR/hooks/$guard"
    fi
done

ok "Hooks installed"

# ── Step 6: Copy scripts ──
echo -e "${BOLD}Installing scripts...${NC}"

for script in "$SCRIPT_DIR"/scripts/*.py; do
    if [ -f "$script" ]; then
        cp "$script" "$CLAUDE_DIR/scripts/$(basename "$script")"
    fi
done
ok "Scripts installed ($(ls "$CLAUDE_DIR/scripts/"*.py 2>/dev/null | wc -l | tr -d ' ') files)"

# ── Step 7: Copy skills ──
echo -e "${BOLD}Installing skills...${NC}"

SKILL_COUNT=0
if [ -d "$SCRIPT_DIR/skills" ]; then
    for skill_dir in "$SCRIPT_DIR"/skills/*/; do
        if [ -d "$skill_dir" ]; then
            skill_name=$(basename "$skill_dir")
            cp -r "$skill_dir" "$CLAUDE_DIR/skills/$skill_name"
            SKILL_COUNT=$((SKILL_COUNT + 1))
        fi
    done
fi
ok "Skills installed ($SKILL_COUNT skills)"

# ── Step 8: Copy agent configs ──
echo -e "${BOLD}Installing agent configs...${NC}"

if [ -d "$SCRIPT_DIR/agents" ]; then
    for agent_file in "$SCRIPT_DIR"/agents/*.md; do
        if [ -f "$agent_file" ]; then
            cp "$agent_file" "$CLAUDE_DIR/agents/$(basename "$agent_file")"
        fi
    done
fi
ok "Agent configs installed"

# ── Step 9: Copy daemon scripts ──
echo -e "${BOLD}Installing daemon scripts...${NC}"

if [ -d "$SCRIPT_DIR/daemons/src" ]; then
    for daemon_file in "$SCRIPT_DIR"/daemons/src/*; do
        if [ -f "$daemon_file" ]; then
            cp "$daemon_file" "$DAEMON_DIR/src/$(basename "$daemon_file")"
            chmod +x "$DAEMON_DIR/src/$(basename "$daemon_file")"
        fi
    done
fi
ok "Daemon scripts installed"

# ── Step 10: Create Python venv ──
echo ""
echo -e "${BOLD}Setting up Python environment...${NC}"
info "Creating virtual environment..."

if [ ! -d "$VENV_DIR" ]; then
    "$PYTHON_CMD" -m venv "$VENV_DIR"
fi

info "Installing dependencies (this may take a few minutes on first run)..."
"$VENV_DIR/bin/pip" install --quiet --upgrade pip
"$VENV_DIR/bin/pip" install --quiet sentence-transformers numpy
ok "Python environment ready"

# ── Step 11: Download embedding model ──
echo ""
echo -e "${BOLD}Downloading embedding model (~90MB, one-time)...${NC}"
"$VENV_DIR/bin/python" -c "from sentence_transformers import SentenceTransformer; SentenceTransformer('all-MiniLM-L6-v2')" 2>/dev/null
ok "Embedding model ready"

# ── Step 12: Initialize markdown index database ──
echo ""
echo -e "${BOLD}Initializing markdown index...${NC}"

if [ -f "$INDEX_DB" ]; then
    warn "Index database already exists at $INDEX_DB — skipping initialization"
else
    sqlite3 "$INDEX_DB" < "$SCRIPT_DIR/schema/init.sql"
    ok "Markdown index initialized"
fi

# Create empty persistent files
touch "$MEM_DIR/decisions.md"
touch "$MEM_DIR/errors.log"
touch "$MEM_DIR/last-session.md"

# ── Step 13: Save API keys ──
echo ""
echo -e "${BOLD}Saving configuration...${NC}"

# Create .env.tools for AgentMail
if [ -n "$AGENTMAIL_KEY" ]; then
    cat > "$CLAUDE_DIR/.env.tools" << EOF
AGENTMAIL_API_KEY=$AGENTMAIL_KEY
EOF
    ok "AgentMail API key saved"
fi

# ── Step 14: Configure settings.local.json ──
echo ""
echo -e "${BOLD}Configuring Claude Code hooks...${NC}"

SETTINGS_FILE="$CLAUDE_DIR/settings.local.json"
if [ -f "$SETTINGS_FILE" ]; then
    warn "settings.local.json already exists"
    read -r -p "  Overwrite with Claude OS hook configuration? (y/N): " OVERWRITE
    if [[ ! "$OVERWRITE" =~ ^[Yy] ]]; then
        warn "Skipped — you may need to manually merge hook URLs"
    else
        sed "s|{{HOME}}|$HOME|g" "$SCRIPT_DIR/templates/settings.local.json.tmpl" > "$SETTINGS_FILE"
        ok "Hook configuration written"
    fi
else
    sed "s|{{HOME}}|$HOME|g" "$SCRIPT_DIR/templates/settings.local.json.tmpl" > "$SETTINGS_FILE"
    ok "Hook configuration written"
fi

# ── Step 15: Configure settings.json (MCP servers) ──
echo ""
echo -e "${BOLD}Configuring MCP servers...${NC}"

SETTINGS_JSON="$CLAUDE_DIR/settings.json"
if [ -f "$SETTINGS_JSON" ]; then
    warn "settings.json already exists — not overwriting"
    info "You can manually add MCP servers later"
else
    if [ -n "$AGENTMAIL_KEY" ]; then
        cat > "$SETTINGS_JSON" << SETTINGSEOF
{
  "env": {
    "AGENTMAIL_API_KEY": "$AGENTMAIL_KEY"
  },
  "mcpServers": {
    "agentmail": {
      "command": "npx",
      "args": ["-y", "agentmail-mcp"],
      "env": {
        "AGENTMAIL_API_KEY": "$AGENTMAIL_KEY"
      }
    }
  }
}
SETTINGSEOF
        ok "settings.json created with AgentMail MCP"
    else
        cat > "$SETTINGS_JSON" << SETTINGSEOF
{
  "env": {},
  "mcpServers": {}
}
SETTINGSEOF
        ok "settings.json created (empty — add MCP servers as needed)"
    fi
fi

# ── Step 16: Write CLAUDE.md ──
echo ""
echo -e "${BOLD}Writing assistant instructions...${NC}"

CLAUDE_MD="$CLAUDE_DIR/CLAUDE.md"
if [ -f "$CLAUDE_MD" ] && [ -s "$CLAUDE_MD" ]; then
    warn "CLAUDE.md already exists"
    read -r -p "  Overwrite? (y/N): " OVERWRITE_MD
    if [[ ! "$OVERWRITE_MD" =~ ^[Yy] ]]; then
        warn "Skipped"
    else
        sed -e "s/{{ASSISTANT_NAME}}/$ASSISTANT_NAME/g" \
            -e "s/{{ASSISTANT_EMAIL}}/$ASSISTANT_EMAIL/g" \
            "$SCRIPT_DIR/templates/CLAUDE.md.template" > "$CLAUDE_MD"
        ok "CLAUDE.md written for $ASSISTANT_NAME"
    fi
else
    sed -e "s/{{ASSISTANT_NAME}}/$ASSISTANT_NAME/g" \
        -e "s/{{ASSISTANT_EMAIL}}/$ASSISTANT_EMAIL/g" \
        "$SCRIPT_DIR/templates/CLAUDE.md.template" > "$CLAUDE_MD"
    ok "CLAUDE.md written for $ASSISTANT_NAME"
fi

# ── Step 17: Install launchd daemon (macOS) ──
echo ""
echo -e "${BOLD}Starting memory hooks server...${NC}"

if [[ "$OSTYPE" == "darwin"* ]]; then
    PLIST_NAME="com.claude-os.http-hooks-server"
    PLIST_PATH="$HOME/Library/LaunchAgents/$PLIST_NAME.plist"

    cat > "$PLIST_PATH" << PLIST
<?xml version="1.0" encoding="UTF-8"?>
<!DOCTYPE plist PUBLIC "-//Apple//DTD PLIST 1.0//EN" "http://www.apple.com/DTDs/PropertyList-1.0.dtd">
<plist version="1.0">
<dict>
    <key>Label</key>
    <string>$PLIST_NAME</string>
    <key>ProgramArguments</key>
    <array>
        <string>$VENV_DIR/bin/python</string>
        <string>$CLAUDE_DIR/hooks/http-server/server.py</string>
    </array>
    <key>RunAtLoad</key>
    <true/>
    <key>KeepAlive</key>
    <true/>
    <key>StandardOutPath</key>
    <string>$MEM_DIR/logs/http-hooks-stdout.log</string>
    <key>StandardErrorPath</key>
    <string>$MEM_DIR/logs/http-hooks-stderr.log</string>
    <key>WorkingDirectory</key>
    <string>$CLAUDE_DIR/hooks/http-server</string>
    <key>EnvironmentVariables</key>
    <dict>
        <key>PYTORCH_MPS_DISABLE</key>
        <string>1</string>
    </dict>
</dict>
</plist>
PLIST

    launchctl load "$PLIST_PATH" 2>/dev/null || true
    ok "Hooks server installed as launchd daemon (auto-starts on login)"
else
    info "Linux detected — start manually: ~/.claude/hooks/http-server/manage.sh start"
    warn "For auto-start, create a systemd unit"
fi

# ── Step 18: Verify ──
echo ""
echo -e "${BOLD}Verifying installation...${NC}"

sleep 3

# Test hooks server
RESP=$(curl -s -o /dev/null -w "%{http_code}" -X POST http://127.0.0.1:9090/hooks/PreToolUse -d '{}' 2>/dev/null || echo "failed")
if [ "$RESP" = "200" ]; then
    ok "Hooks server responding (HTTP 200)"
else
    warn "Hooks server not responding yet (HTTP $RESP) — it may need a moment to start"
    info "Check logs: tail -f $MEM_DIR/logs/http-hooks-stderr.log"
fi

# Test database
if [ -f "$INDEX_DB" ]; then
    TABLE_COUNT=$(sqlite3 "$INDEX_DB" "SELECT count(*) FROM sqlite_master WHERE type='table';" 2>/dev/null || echo "0")
    ok "Markdown index healthy ($TABLE_COUNT tables)"
fi

# Test venv
if "$VENV_DIR/bin/python" -c "import sentence_transformers" 2>/dev/null; then
    ok "Sentence transformers working"
else
    warn "Sentence transformers import failed"
fi

# ── Done ──
echo ""
echo -e "${BOLD}════════════════════════════════════════${NC}"
echo -e "${GREEN}${BOLD}  Claude OS v3 installed successfully!${NC}"
echo -e "${BOLD}════════════════════════════════════════${NC}"
echo ""
echo "  Your assistant: ${BOLD}${ASSISTANT_NAME}${NC}"
if [ -n "$ASSISTANT_EMAIL" ]; then
    echo "  Email: ${BOLD}${ASSISTANT_EMAIL}@agentmail.to${NC}"
fi
echo ""
echo "  What was installed:"
echo "    ${BLUE}~/.claude/hooks/${NC}      — Hook server (HTTP on port 9090)"
echo "    ${BLUE}~/.claude/scripts/${NC}    — Search engine, narrative extraction, compound loop"
echo "    ${BLUE}~/.claude/skills/${NC}     — $SKILL_COUNT skills (pdf, research, design, etc.)"
echo "    ${BLUE}~/.claude-mem/${NC}        — Markdown index + Python venv + embeddings"
echo "    ${BLUE}~/mojo-daemon/${NC}        — Autonomous task daemon"
echo ""
echo "  How memory works (v3 — zero API cost):"
echo "    Every prompt       → markdown index searched (FTS5 + semantic) → context injected"
echo "    Session end        → narratives extracted from transcript → index rebuilt"
echo "    Session start      → previous session narrative + daily logs loaded"
echo "    Anthropic built-in → MEMORY.md updated organically by Claude"
echo ""
echo "  No LLM extraction. No API calls. Memory comes from your markdown files."
echo ""
echo "  Next steps:"
echo "    1. Run: ${BOLD}claude${NC}"
echo "    2. Start talking — memory builds automatically"
echo "    3. Ask your assistant to install more capabilities from ~/.claude/skills/install/"
echo ""
echo "  Management:"
echo "    ${BOLD}~/.claude/hooks/http-server/manage.sh status${NC}   — Check server"
echo "    ${BOLD}~/.claude/hooks/http-server/manage.sh restart${NC}  — Restart server"
echo "    ${BOLD}tail -f ~/.claude-mem/logs/http-hooks-stderr.log${NC} — View logs"
echo ""
