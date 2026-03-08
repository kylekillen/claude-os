#!/usr/bin/env python3
"""
Pre-Compaction Backup Hook

Fires BEFORE Claude auto-compacts the context window.
Saves the full transcript to a backup file so nothing is lost.

The hook receives JSON on stdin with:
- session_id
- transcript_path (the JSONL file)
- trigger (manual or auto)
"""

import sys
import json
import shutil
from datetime import datetime
from pathlib import Path

# Paths
BACKUP_DIR = Path.home() / "Library/CloudStorage/GoogleDrive-kyle.killen@gmail.com/My Drive/Personal-OS-v2/sessions/pre-compact-backups"
LOG_FILE = Path.home() / ".pos_precompact.log"


def log(msg: str):
    """Write to log file."""
    with open(LOG_FILE, "a") as f:
        f.write(f"{datetime.now().isoformat()} - {msg}\n")


def main():
    try:
        # Read hook input from stdin
        input_data = json.loads(sys.stdin.read())

        session_id = input_data.get("session_id", "unknown")
        transcript_path = input_data.get("transcript_path", "")
        trigger = input_data.get("trigger", "unknown")

        log(f"PreCompact triggered: {trigger}, session: {session_id}")

        if not transcript_path or not Path(transcript_path).exists():
            log(f"No transcript file at: {transcript_path}")
            sys.exit(0)

        # Create backup directory
        BACKUP_DIR.mkdir(parents=True, exist_ok=True)

        # Backup filename: timestamp-session_id-trigger.jsonl (full session_id for claude-mem matching)
        timestamp = datetime.now().strftime("%Y-%m-%d-%H%M%S")
        backup_name = f"{timestamp}-{session_id}-{trigger}.jsonl"
        backup_path = BACKUP_DIR / backup_name

        # Copy the transcript
        shutil.copy2(transcript_path, backup_path)

        # Update session index for easy lookup
        index_path = BACKUP_DIR / "session-index.json"
        try:
            if index_path.exists():
                index = json.loads(index_path.read_text())
            else:
                index = {}
            index[session_id] = {
                "backup_file": backup_name,
                "timestamp": timestamp,
                "trigger": trigger
            }
            index_path.write_text(json.dumps(index, indent=2))
        except Exception as e:
            log(f"Error updating index: {e}")

        # Get file size
        size = backup_path.stat().st_size
        size_kb = size / 1024

        log(f"Backed up {size_kb:.1f}KB to {backup_path}")
        print(f"PreCompact backup: {backup_name} ({size_kb:.1f}KB)", file=sys.stderr)

        # Also save a summary of what's being compacted
        try:
            with open(transcript_path) as f:
                lines = f.readlines()

            # Count messages
            user_count = 0
            assistant_count = 0
            tool_count = 0

            for line in lines:
                try:
                    msg = json.loads(line.strip())
                    msg_type = msg.get("type")
                    if msg_type == "user":
                        user_count += 1
                    elif msg_type == "assistant":
                        assistant_count += 1
                        # Count tool calls
                        content = msg.get("message", {}).get("content", [])
                        if isinstance(content, list):
                            for item in content:
                                if isinstance(item, dict) and item.get("type") == "tool_use":
                                    tool_count += 1
                except:
                    continue

            log(f"Stats: {user_count} user, {assistant_count} assistant, {tool_count} tool calls")

        except Exception as e:
            log(f"Error counting messages: {e}")

        sys.exit(0)

    except Exception as e:
        log(f"Error in pre-compact hook: {e}")
        sys.exit(0)  # Don't block compaction on error


if __name__ == "__main__":
    main()
