#!/bin/bash
# Build the Claude OS package from the current system
# Run this on Kyle's machine to assemble the latest files into the repo.
set -e

SCRIPT_DIR="$(cd "$(dirname "$0")" && pwd)"
CLAUDE_DIR="$HOME/.claude"
MEM_DIR="$HOME/.claude-mem"

echo "=== Building Claude OS Package ==="
echo ""

# ── Hooks ──
echo "[1/6] Copying hooks..."
cp "$CLAUDE_DIR/hooks/http-server/server.py" "$SCRIPT_DIR/hooks/http-server/server.py"
cp "$CLAUDE_DIR/hooks/http-server/manage.sh" "$SCRIPT_DIR/hooks/http-server/manage.sh"
cp "$CLAUDE_DIR/hooks/http-server/test-pipeline.sh" "$SCRIPT_DIR/hooks/http-server/test-pipeline.sh" 2>/dev/null || true
cp "$CLAUDE_DIR/hooks/session-start-bridge.sh" "$SCRIPT_DIR/hooks/session-start-bridge.sh"
echo "  Done"

# ── Scripts ──
echo "[2/6] Copying scripts..."
for f in markdown-search.py extract-narratives.py query-context.py compound-loop.py daily-upgrade-check.py; do
    if [ -f "$CLAUDE_DIR/scripts/$f" ]; then
        cp "$CLAUDE_DIR/scripts/$f" "$SCRIPT_DIR/scripts/$f"
    fi
done
echo "  Done ($(ls "$SCRIPT_DIR/scripts/"*.py 2>/dev/null | wc -l | tr -d ' ') scripts)"

# ── Skills ──
echo "[3/6] Copying skills..."
SKILL_COUNT=0
for skill_dir in "$CLAUDE_DIR/skills"/*/; do
    skill_name=$(basename "$skill_dir")
    # Skip archived, __pycache__, here-now symlink
    [[ "$skill_name" == "archived" ]] && continue
    [[ "$skill_name" == "__pycache__" ]] && continue
    [[ -L "$skill_dir" ]] && continue  # skip symlinks

    cp -r "$skill_dir" "$SCRIPT_DIR/skills/$skill_name"
    SKILL_COUNT=$((SKILL_COUNT + 1))
done
# Also copy install skills
if [ -d "$CLAUDE_DIR/skills/install" ]; then
    cp -r "$CLAUDE_DIR/skills/install" "$SCRIPT_DIR/skills/install"
fi
echo "  Done ($SKILL_COUNT skills)"

# ── Daemons ──
echo "[4/6] Copying daemon scripts..."
DAEMON_DIR="$HOME/mojo-daemon/src"
for f in heartbeat.sh heartbeat_runner.py mojo_notify.py; do
    if [ -f "$DAEMON_DIR/$f" ]; then
        cp "$DAEMON_DIR/$f" "$SCRIPT_DIR/daemons/src/$f"
    fi
done
echo "  Done"

# ── Schema ──
echo "[5/6] Copying database schema..."
# Export current schema from live database
sqlite3 "$MEM_DIR/claude-mem.db" ".schema" > "$SCRIPT_DIR/schema/init.sql" 2>/dev/null || {
    echo "  Warning: couldn't export live schema, using packaged version"
}
echo "  Done"

# ── Agents ──
echo "[6/6] Copying agent configs..."
mkdir -p "$SCRIPT_DIR/agents"
for f in "$CLAUDE_DIR/agents/"*.md; do
    if [ -f "$f" ]; then
        cp "$f" "$SCRIPT_DIR/agents/$(basename "$f")"
    fi
done
echo "  Done"

echo ""
echo "=== Package built ==="
echo "  Skills: $SKILL_COUNT"
echo "  Scripts: $(ls "$SCRIPT_DIR/scripts/"*.py 2>/dev/null | wc -l | tr -d ' ')"
echo "  Location: $SCRIPT_DIR"
echo ""
echo "Next: review templates/, then commit and push."
