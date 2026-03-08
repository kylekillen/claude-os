#!/bin/bash
set -e

RED='\033[0;31m'
GREEN='\033[0;32m'
YELLOW='\033[1;33m'
BOLD='\033[1m'
NC='\033[0m'

echo ""
echo -e "${BOLD}Claude OS Uninstaller${NC}"
echo ""

read -r -p "Remove all Claude OS files? This will delete memories, hooks, and skills. (y/N): " CONFIRM
if [[ ! "$CONFIRM" =~ ^[Yy] ]]; then
    echo "Cancelled."
    exit 0
fi

# Stop launchd daemons
echo "Stopping services..."
for plist in "$HOME/Library/LaunchAgents/com.claude-os."*".plist"; do
    if [ -f "$plist" ]; then
        launchctl unload "$plist" 2>/dev/null
        rm -f "$plist"
        echo -e "${GREEN}✓${NC} Removed $(basename "$plist")"
    fi
done

# Kill server process
pkill -f "http-server/server.py" 2>/dev/null || true

# Remove Claude OS files
echo "Removing files..."

rm -rf "$HOME/.claude/hooks"
echo -e "${GREEN}✓${NC} Removed hooks"

rm -rf "$HOME/.claude/scripts"
echo -e "${GREEN}✓${NC} Removed scripts"

rm -rf "$HOME/.claude/skills"
echo -e "${GREEN}✓${NC} Removed skills"

rm -rf "$HOME/.claude/agents"
echo -e "${GREEN}✓${NC} Removed agents"

# Remove memory system
read -r -p "Also remove memory database and Python venv (~1.7GB)? (y/N): " REMOVE_MEM
if [[ "$REMOVE_MEM" =~ ^[Yy] ]]; then
    rm -rf "$HOME/.claude-mem"
    echo -e "${GREEN}✓${NC} Removed memory system"
fi

# Remove daemon
read -r -p "Remove daemon scripts? (y/N): " REMOVE_DAEMON
if [[ "$REMOVE_DAEMON" =~ ^[Yy] ]]; then
    rm -rf "$HOME/mojo-daemon"
    echo -e "${GREEN}✓${NC} Removed daemon"
fi

# Clean settings
if [ -f "$HOME/.claude/settings.local.json" ]; then
    read -r -p "Remove settings.local.json (hook config)? (y/N): " REMOVE_SETTINGS
    if [[ "$REMOVE_SETTINGS" =~ ^[Yy] ]]; then
        rm -f "$HOME/.claude/settings.local.json"
        echo -e "${GREEN}✓${NC} Removed hook settings"
    fi
fi

echo ""
echo -e "${GREEN}${BOLD}Claude OS uninstalled.${NC}"
echo "Claude Code itself is preserved — you can still use 'claude' normally."
echo ""
