#!/usr/bin/env python3
"""
Sync memories table to MEMORY.md

Reads all active memories from the memories table and regenerates
MEMORY.md as a formatted view. No LLM needed — the facts are already
clean sentences from when they were stored.

Run on Stop hook after memory extraction completes.
"""

import sqlite3
import os
import json
import sys
from datetime import datetime, timezone
from pathlib import Path
from collections import defaultdict

DB_PATH = os.path.expanduser("~/.claude-mem/claude-mem.db")
MEMORY_MD_PATH = os.path.expanduser("~/.claude-mem/MEMORY.md")
LOG_PATH = os.path.expanduser("~/.claude-mem/logs/sync-memories.log")

# Preserve these sections from the existing MEMORY.md
# (infrastructure docs that aren't in the memories table yet)
PRESERVED_HEADER = """# Claude Memory

## Active Knowledge (auto-generated from memories table)
"""


def log(msg):
    try:
        os.makedirs(os.path.dirname(LOG_PATH), exist_ok=True)
        with open(LOG_PATH, "a") as f:
            ts = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
            f.write(f"[{ts}] {msg}\n")
    except Exception:
        pass


def main():
    if not os.path.exists(DB_PATH):
        log("No database")
        sys.exit(0)

    db = sqlite3.connect(DB_PATH, timeout=5)
    db.execute("PRAGMA journal_mode=WAL")

    # Get all active memories grouped by category
    rows = db.execute("""
        SELECT id, fact, category, created_at_epoch, updated_at_epoch
        FROM memories
        WHERE is_active = 1
        ORDER BY category, updated_at_epoch DESC
    """).fetchall()

    db.close()

    if not rows:
        log("No active memories — skipping MEMORY.md generation")
        sys.exit(0)

    # Group by category
    by_category = defaultdict(list)
    for mid, fact, category, created, updated in rows:
        cat = category or "uncategorized"
        by_category[cat].append((mid, fact, updated))

    # Category display order and labels
    cat_order = ["technical", "financial", "workflow", "project",
                 "preference", "person", "uncategorized"]
    cat_labels = {
        "technical": "Technical",
        "financial": "Financial",
        "workflow": "Workflow",
        "project": "Project",
        "preference": "Preferences",
        "person": "People",
        "uncategorized": "Other",
    }

    # Build the markdown
    lines = [PRESERVED_HEADER.strip(), ""]
    lines.append(f"*{len(rows)} active memories as of {datetime.now().strftime('%Y-%m-%d %H:%M')}*")
    lines.append("")

    for cat in cat_order:
        if cat not in by_category:
            continue
        memories = by_category[cat]
        label = cat_labels.get(cat, cat.title())
        lines.append(f"### {label}")
        lines.append("")
        for mid, fact, updated in memories:
            lines.append(f"- {fact}")
        lines.append("")

    # Add link to reference.md for static project docs
    lines.append("---")
    lines.append("")
    lines.append("*Static project reference in `memory/reference.md`*")

    # Enforce 195-line limit (MEMORY.md is truncated at 200 by the loader)
    MAX_LINES = 195
    if len(lines) > MAX_LINES:
        lines = lines[:MAX_LINES]
        lines.append("")
        lines.append(f"*Truncated at {MAX_LINES} lines — {len(rows)} total memories*")

    # Write
    output = "\n".join(lines) + "\n"
    os.makedirs(os.path.dirname(MEMORY_MD_PATH), exist_ok=True)
    with open(MEMORY_MD_PATH, "w") as f:
        f.write(output)

    log(f"Wrote {len(rows)} memories to MEMORY.md ({len(output)} chars)")


if __name__ == "__main__":
    main()
