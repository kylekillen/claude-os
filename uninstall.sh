#!/bin/bash
# Claude OS Uninstaller
# Removes hooks, scripts, skills, memory database, and launchd daemon

RED='\033[0;31m'
YELLOW='\033[1;33m'
GREEN='\033[0;32m'
BOLD='\033[1m'
NC='\033[0m'

echo ""
echo -e "${BOLD}Claude OS Uninstaller${NC}"
echo ""
echo -e "${YELLOW}This will remove:${NC}"
echo "  ~/.claude/hooks/          — Hook scripts"
echo "  ~/.claude/scripts/        — Memory pipeline scripts"
echo "  ~/.claude/skills/         — Installed skills"
echo "  ~/.claude/CLAUDE.md       — Assistant instructions"
echo "  ~/.claude-mem/            — Memory database, embeddings, logs"
echo "  LaunchAgent daemon        — com.claude-os.http-hooks-server"
echo ""
echo -e "${RED}${BOLD}This will permanently delete your memory database.${NC}"
read -r -p "Are you sure? (type 'yes' to confirm): " CONFIRM

if [ "$CONFIRM" != "yes" ]; then
    echo "Cancelled."
    exit 0
fi

echo ""

# Stop and uninstall launchd daemon
PLIST_PATH="$HOME/Library/LaunchAgents/com.claude-os.http-hooks-server.plist"
if [ -f "$PLIST_PATH" ]; then
    launchctl unload "$PLIST_PATH" 2>/dev/null
    rm -f "$PLIST_PATH"
    echo -e "${GREEN}✓${NC} LaunchAgent removed"
fi

# Kill any running server
pkill -f "http-server/server.py" 2>/dev/null

# Remove hooks
if [ -d "$HOME/.claude/hooks" ]; then
    rm -rf "$HOME/.claude/hooks"
    echo -e "${GREEN}✓${NC} Hooks removed"
fi

# Remove scripts
if [ -d "$HOME/.claude/scripts" ]; then
    rm -rf "$HOME/.claude/scripts"
    echo -e "${GREEN}✓${NC} Scripts removed"
fi

# Remove skills
if [ -d "$HOME/.claude/skills" ]; then
    rm -rf "$HOME/.claude/skills"
    echo -e "${GREEN}✓${NC} Skills removed"
fi

# Remove CLAUDE.md
if [ -f "$HOME/.claude/CLAUDE.md" ]; then
    rm -f "$HOME/.claude/CLAUDE.md"
    echo -e "${GREEN}✓${NC} CLAUDE.md removed"
fi

# Remove memory directory
if [ -d "$HOME/.claude-mem" ]; then
    rm -rf "$HOME/.claude-mem"
    echo -e "${GREEN}✓${NC} Memory database and logs removed"
fi

# Remove settings hooks (but preserve the file)
if [ -f "$HOME/.claude/settings.local.json" ]; then
    echo -e "${YELLOW}!${NC} settings.local.json preserved (may contain other config)"
    echo "  Remove hooks manually if needed: ~/.claude/settings.local.json"
fi

echo ""
echo -e "${GREEN}${BOLD}Claude OS uninstalled.${NC}"
echo "  Claude Code itself is not affected."
echo "  To reinstall: ./install.sh"
echo ""
