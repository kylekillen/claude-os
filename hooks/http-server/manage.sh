#!/bin/bash
# Manage the HTTP hooks server
# Usage: manage.sh [start|stop|restart|status|install-launchd|uninstall-launchd]

SERVER_DIR="$HOME/.claude/hooks/http-server"
PID_FILE="$SERVER_DIR/server.pid"
LOG_FILE="$HOME/.claude-mem/logs/http-hooks-server.log"
PLIST_NAME="com.claude-os.http-hooks-server"
PLIST_PATH="$HOME/Library/LaunchAgents/$PLIST_NAME.plist"

case "${1:-status}" in
    start)
        if [ -f "$PID_FILE" ] && kill -0 "$(cat "$PID_FILE")" 2>/dev/null; then
            echo "Server already running (PID $(cat "$PID_FILE"))"
            exit 0
        fi
        echo "Starting HTTP hooks server..."
        python3 "$SERVER_DIR/server.py" &
        sleep 1
        if [ -f "$PID_FILE" ]; then
            echo "Started (PID $(cat "$PID_FILE"))"
        else
            echo "Failed to start — check $LOG_FILE"
            exit 1
        fi
        ;;
    stop)
        if [ -f "$PID_FILE" ]; then
            PID=$(cat "$PID_FILE")
            echo "Stopping server (PID $PID)..."
            kill "$PID" 2>/dev/null
            rm -f "$PID_FILE"
            echo "Stopped"
        else
            echo "No PID file found"
            pkill -f "http-server/server.py" 2>/dev/null
        fi
        ;;
    restart)
        "$0" stop
        sleep 1
        "$0" start
        ;;
    status)
        if [ -f "$PID_FILE" ] && kill -0 "$(cat "$PID_FILE")" 2>/dev/null; then
            echo "Running (PID $(cat "$PID_FILE"))"
            RESP=$(curl -s -o /dev/null -w "%{http_code}" -X POST http://127.0.0.1:9090/hooks/PreToolUse -d '{}' 2>/dev/null)
            if [ "$RESP" = "200" ]; then
                echo "Health: OK (HTTP 200)"
            else
                echo "Health: UNHEALTHY (HTTP $RESP)"
            fi
        else
            echo "Not running"
        fi
        ;;
    install-launchd)
        echo "Installing launchd plist..."
        mkdir -p "$HOME/.claude-mem/logs"
        cat > "$PLIST_PATH" << PLIST
<?xml version="1.0" encoding="UTF-8"?>
<!DOCTYPE plist PUBLIC "-//Apple//DTD PLIST 1.0//EN" "http://www.apple.com/DTDs/PropertyList-1.0.dtd">
<plist version="1.0">
<dict>
    <key>Label</key>
    <string>$PLIST_NAME</string>
    <key>ProgramArguments</key>
    <array>
        <string>/usr/bin/python3</string>
        <string>$SERVER_DIR/server.py</string>
    </array>
    <key>EnvironmentVariables</key>
    <dict>
        <key>PATH</key>
        <string>$HOME/.bun/bin:/opt/homebrew/bin:/opt/homebrew/sbin:/usr/local/bin:/usr/bin:/bin:/usr/sbin:/sbin:$HOME/.local/bin</string>
        <key>HOME</key>
        <string>$HOME</string>
        <key>ANTHROPIC_API_KEY</key>
        <string>${ANTHROPIC_API_KEY:-}</string>
    </dict>
    <key>RunAtLoad</key>
    <true/>
    <key>KeepAlive</key>
    <true/>
    <key>StandardOutPath</key>
    <string>$HOME/.claude-mem/logs/http-hooks-stdout.log</string>
    <key>StandardErrorPath</key>
    <string>$HOME/.claude-mem/logs/http-hooks-stderr.log</string>
    <key>WorkingDirectory</key>
    <string>$SERVER_DIR</string>
</dict>
</plist>
PLIST
        launchctl load "$PLIST_PATH"
        echo "Installed and loaded: $PLIST_NAME"
        sleep 2
        "$0" status
        ;;
    uninstall-launchd)
        launchctl unload "$PLIST_PATH" 2>/dev/null
        rm -f "$PLIST_PATH"
        echo "Uninstalled: $PLIST_NAME"
        ;;
    *)
        echo "Usage: $0 [start|stop|restart|status|install-launchd|uninstall-launchd]"
        ;;
esac
