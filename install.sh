#!/bin/bash
set -e

# ════════════════════════════════════════════════
# Claude OS Installer
# Persistent memory + context injection for Claude Code
# ════════════════════════════════════════════════

SCRIPT_DIR="$(cd "$(dirname "$0")" && pwd)"
CLAUDE_DIR="$HOME/.claude"
MEM_DIR="$HOME/.claude-mem"
VENV_DIR="$MEM_DIR/venv"
DB_PATH="$MEM_DIR/claude-mem.db"

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
echo -e "${BOLD}       Claude OS Installer${NC}"
echo -e "${BOLD}  Persistent Memory for Claude Code${NC}"
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

# Check Anthropic API key
if [ -z "$ANTHROPIC_API_KEY" ]; then
    echo ""
    warn "ANTHROPIC_API_KEY not set in environment"
    echo "  The memory system needs an Anthropic API key to extract facts from conversations."
    echo "  It uses Haiku (~\$0.01/session) for memory extraction."
    echo ""
    read -r -p "  Enter your Anthropic API key (sk-ant-...): " INPUT_KEY
    if [ -z "$INPUT_KEY" ]; then
        fail "API key required. Get one at: https://console.anthropic.com/settings/keys"
    fi
    ANTHROPIC_API_KEY="$INPUT_KEY"
    echo ""

    # Detect shell and offer to persist
    SHELL_NAME=$(basename "$SHELL")
    if [ "$SHELL_NAME" = "zsh" ]; then
        RC_FILE="$HOME/.zshrc"
    elif [ "$SHELL_NAME" = "bash" ]; then
        RC_FILE="$HOME/.bashrc"
    else
        RC_FILE="$HOME/.profile"
    fi

    read -r -p "  Add ANTHROPIC_API_KEY to $RC_FILE? (y/N): " ADD_TO_RC
    if [[ "$ADD_TO_RC" =~ ^[Yy] ]]; then
        echo "" >> "$RC_FILE"
        echo "# Anthropic API key (added by Claude OS installer)" >> "$RC_FILE"
        echo "export ANTHROPIC_API_KEY=\"$ANTHROPIC_API_KEY\"" >> "$RC_FILE"
        ok "API key added to $RC_FILE"
    else
        warn "Remember to set ANTHROPIC_API_KEY in your shell profile"
    fi
fi
ok "Anthropic API key configured"

# ── Step 3: Create directory structure ──
echo ""
echo -e "${BOLD}Setting up directories...${NC}"

mkdir -p "$CLAUDE_DIR/hooks/http-server"
mkdir -p "$CLAUDE_DIR/scripts"
mkdir -p "$CLAUDE_DIR/skills"
mkdir -p "$MEM_DIR/logs"
mkdir -p "$MEM_DIR/backups"
mkdir -p "$MEM_DIR/patterns"
ok "Directory structure created"

# ── Step 4: Copy hooks ──
echo ""
echo -e "${BOLD}Installing hooks...${NC}"

cp "$SCRIPT_DIR/hooks/http-server/server.py" "$CLAUDE_DIR/hooks/http-server/server.py"
cp "$SCRIPT_DIR/hooks/http-server/manage.sh" "$CLAUDE_DIR/hooks/http-server/manage.sh"
chmod +x "$CLAUDE_DIR/hooks/http-server/manage.sh"
cp "$SCRIPT_DIR/hooks/per-turn-memory.py" "$CLAUDE_DIR/hooks/per-turn-memory.py"
cp "$SCRIPT_DIR/hooks/pre-compact-memories.py" "$CLAUDE_DIR/hooks/pre-compact-memories.py"
ok "Hooks installed"

# ── Step 5: Copy scripts ──
echo -e "${BOLD}Installing scripts...${NC}"

for script in "$SCRIPT_DIR"/scripts/*.py; do
    cp "$script" "$CLAUDE_DIR/scripts/$(basename "$script")"
done
ok "Scripts installed ($(ls "$SCRIPT_DIR"/scripts/*.py | wc -l | tr -d ' ') files)"

# ── Step 6: Copy skills ──
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

# ── Step 7: Create Python venv ──
echo ""
echo -e "${BOLD}Setting up Python environment...${NC}"
info "Creating virtual environment..."

if [ ! -d "$VENV_DIR" ]; then
    "$PYTHON_CMD" -m venv "$VENV_DIR"
fi

info "Installing sentence-transformers (this may take a few minutes on first run)..."
"$VENV_DIR/bin/pip" install --quiet --upgrade pip
"$VENV_DIR/bin/pip" install --quiet sentence-transformers numpy
ok "Python environment ready"

# ── Step 8: Initialize database ──
echo ""
echo -e "${BOLD}Initializing memory database...${NC}"

if [ -f "$DB_PATH" ]; then
    warn "Database already exists at $DB_PATH — skipping initialization"
else
    sqlite3 "$DB_PATH" < "$SCRIPT_DIR/schema/init.sql"
    ok "Database initialized with full schema"
fi

# ── Step 9: Configure settings.local.json ──
echo ""
echo -e "${BOLD}Configuring Claude Code hooks...${NC}"

SETTINGS_FILE="$CLAUDE_DIR/settings.local.json"
if [ -f "$SETTINGS_FILE" ]; then
    warn "settings.local.json already exists"
    read -r -p "  Overwrite with Claude OS hook configuration? (y/N): " OVERWRITE
    if [[ ! "$OVERWRITE" =~ ^[Yy] ]]; then
        warn "Skipped — you may need to manually add hook URLs to your settings"
    else
        cp "$SCRIPT_DIR/templates/settings.local.json.tmpl" "$SETTINGS_FILE"
        ok "Hook configuration written"
    fi
else
    cp "$SCRIPT_DIR/templates/settings.local.json.tmpl" "$SETTINGS_FILE"
    ok "Hook configuration written"
fi

# ── Step 10: Write CLAUDE.md ──
echo ""
echo -e "${BOLD}Writing assistant instructions...${NC}"

CLAUDE_MD="$CLAUDE_DIR/CLAUDE.md"
if [ -f "$CLAUDE_MD" ] && [ -s "$CLAUDE_MD" ]; then
    warn "CLAUDE.md already exists"
    read -r -p "  Overwrite? (y/N): " OVERWRITE_MD
    if [[ ! "$OVERWRITE_MD" =~ ^[Yy] ]]; then
        warn "Skipped"
    else
        sed "s/{{ASSISTANT_NAME}}/$ASSISTANT_NAME/g" "$SCRIPT_DIR/templates/CLAUDE.md.template" > "$CLAUDE_MD"
        ok "CLAUDE.md written for $ASSISTANT_NAME"
    fi
else
    sed "s/{{ASSISTANT_NAME}}/$ASSISTANT_NAME/g" "$SCRIPT_DIR/templates/CLAUDE.md.template" > "$CLAUDE_MD"
    ok "CLAUDE.md written for $ASSISTANT_NAME"
fi

# ── Step 11: Download embedding model ──
echo ""
echo -e "${BOLD}Downloading embedding model (~90MB, one-time)...${NC}"
"$VENV_DIR/bin/python" -c "from sentence_transformers import SentenceTransformer; SentenceTransformer('all-MiniLM-L6-v2')" 2>/dev/null
ok "Embedding model ready"

# ── Step 12: Start hooks server (macOS) ──
echo ""
echo -e "${BOLD}Starting memory hooks server...${NC}"

if [[ "$OSTYPE" == "darwin"* ]]; then
    # Export API key for launchd
    export ANTHROPIC_API_KEY
    bash "$CLAUDE_DIR/hooks/http-server/manage.sh" install-launchd
    ok "Hooks server installed as launchd daemon (auto-starts on login)"
else
    # Linux: start manually (user can set up systemd)
    bash "$CLAUDE_DIR/hooks/http-server/manage.sh" start
    ok "Hooks server started"
    warn "For auto-start on Linux, create a systemd unit or add to ~/.profile"
fi

# ── Step 13: Verify ──
echo ""
echo -e "${BOLD}Verifying installation...${NC}"

sleep 2

# Test hooks server
RESP=$(curl -s -o /dev/null -w "%{http_code}" -X POST http://127.0.0.1:9090/hooks/PreToolUse -d '{}' 2>/dev/null || echo "failed")
if [ "$RESP" = "200" ]; then
    ok "Hooks server responding (HTTP 200)"
else
    warn "Hooks server not responding yet (HTTP $RESP) — it may need a moment to start"
fi

# Test database
TABLE_COUNT=$(sqlite3 "$DB_PATH" "SELECT count(*) FROM sqlite_master WHERE type='table';" 2>/dev/null || echo "0")
if [ "$TABLE_COUNT" -gt 5 ]; then
    ok "Database healthy ($TABLE_COUNT tables)"
else
    warn "Database may not be fully initialized"
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
echo -e "${GREEN}${BOLD}  Claude OS installed successfully!${NC}"
echo -e "${BOLD}════════════════════════════════════════${NC}"
echo ""
echo "  Your assistant: ${BOLD}${ASSISTANT_NAME}${NC}"
echo ""
echo "  What was installed:"
echo "    ${BLUE}~/.claude/hooks/${NC}     — Hook scripts (memory extraction)"
echo "    ${BLUE}~/.claude/scripts/${NC}   — Memory pipeline scripts"
echo "    ${BLUE}~/.claude/skills/${NC}    — $SKILL_COUNT portable skills"
echo "    ${BLUE}~/.claude-mem/${NC}       — Memory database + embeddings"
echo ""
echo "  How it works:"
echo "    Every conversation → facts extracted by Haiku → stored in SQLite"
echo "    Every new prompt → relevant memories retrieved → injected as context"
echo "    Cost: ~\$0.01 per session (Haiku API calls)"
echo ""
echo "  Next steps:"
echo "    1. Open a new terminal (to pick up API key)"
echo "    2. Run: ${BOLD}claude${NC}"
echo "    3. Start talking — memory builds automatically"
echo ""
echo "  Management:"
echo "    ${BOLD}~/.claude/hooks/http-server/manage.sh status${NC}  — Check server"
echo "    ${BOLD}~/.claude/hooks/http-server/manage.sh restart${NC} — Restart server"
echo ""
