#!/usr/bin/env python3
"""
Extract compaction summaries from session transcripts.

Reads .jsonl transcript files and extracts isCompactSummary entries,
which contain rich session narratives written by Claude during /compact.

Output: One markdown file per session in sessions/narratives/
"""

import json
import glob
import os
import re
from datetime import datetime

# Auto-detect transcript directory by globbing ~/.claude/projects/*/
import glob as _glob
_project_matches = _glob.glob(os.path.expanduser("~/.claude/projects/*/"))
TRANSCRIPT_DIR = _project_matches[0] if _project_matches else os.path.expanduser("~/.claude/projects/")

_project_root = os.environ.get("CLAUDE_OS_PROJECT_ROOT", os.path.expanduser("~"))
OUTPUT_DIR = os.path.join(_project_root, "sessions/narratives/")


def extract_summaries(filepath):
    """Extract all compaction summaries from a transcript file."""
    summaries = []
    session_id = os.path.basename(filepath).replace(".jsonl", "")

    # Get file modification time for dating
    mtime = os.path.getmtime(filepath)
    file_date = datetime.fromtimestamp(mtime).strftime("%Y-%m-%d")

    # Also try to get the earliest timestamp from the file
    first_timestamp = None

    with open(filepath, "r", errors="replace") as f:
        for line in f:
            try:
                d = json.loads(line)
            except (json.JSONDecodeError, ValueError):
                continue

            # Capture first timestamp
            if first_timestamp is None and d.get("timestamp"):
                try:
                    first_timestamp = d["timestamp"][:10]  # YYYY-MM-DD
                except (IndexError, TypeError):
                    pass

            # Look for compact summaries
            if d.get("isCompactSummary"):
                msg = d.get("message", {})
                content = msg.get("content", "")
                if isinstance(content, str) and len(content) > 100:
                    timestamp = d.get("timestamp", "")
                    summaries.append({
                        "content": content,
                        "timestamp": timestamp,
                        "session_id": session_id,
                    })

    start_date = first_timestamp or file_date
    return summaries, start_date, session_id


def extract_topic(summary_text):
    """Try to extract a topic slug from the summary."""
    # Look for "Primary Request and Intent" section
    match = re.search(r"Primary Request.*?:\s*\n\s*(.*?)(?:\n\n|\n\d\.)", summary_text, re.DOTALL)
    if match:
        first_line = match.group(1).strip().split("\n")[0]
        # Clean to slug
        slug = re.sub(r"[^a-z0-9]+", "-", first_line.lower().strip())[:60].strip("-")
        if len(slug) > 5:
            return slug

    # Fallback: first meaningful line
    for line in summary_text.split("\n"):
        line = line.strip()
        if len(line) > 20 and not line.startswith("This session") and not line.startswith("Summary"):
            slug = re.sub(r"[^a-z0-9]+", "-", line.lower())[:60].strip("-")
            if len(slug) > 5:
                return slug

    return "session"


def write_narrative(summaries, start_date, session_id):
    """Write extracted summaries as a single narrative markdown file.
    Uses session_id in filename to guarantee uniqueness and idempotency."""
    if not summaries:
        return None

    # Use the last (most complete) summary as the main narrative
    # Earlier ones are partial (pre-compaction snapshots)
    main_summary = summaries[-1]["content"]
    topic = extract_topic(main_summary)

    # Always include session_id for uniqueness — prevents duplicates on re-run
    filename = f"{start_date}-{topic[:40]}-{session_id[:8]}.md"
    filepath = os.path.join(OUTPUT_DIR, filename)

    # Skip if this exact file already exists and has content
    if os.path.exists(filepath) and os.path.getsize(filepath) > 100:
        return None

    content = f"""# Session Narrative

Session: `{session_id}`
Date: {start_date}
Compactions: {len(summaries)}

---

{main_summary}
"""

    # If there were multiple compactions, add earlier ones as appendix
    if len(summaries) > 1:
        content += "\n\n---\n\n## Earlier Compaction Summaries\n\n"
        for i, s in enumerate(summaries[:-1]):
            ts = s["timestamp"][:19] if s["timestamp"] else "unknown"
            # Only include first 500 chars of earlier summaries to avoid bloat
            excerpt = s["content"][:500]
            if len(s["content"]) > 500:
                excerpt += "\n...(truncated)"
            content += f"### Compaction {i+1} ({ts})\n\n{excerpt}\n\n"

    os.makedirs(os.path.dirname(filepath), exist_ok=True)
    with open(filepath, "w") as f:
        f.write(content)

    return filepath


def main():
    files = sorted(glob.glob(os.path.join(TRANSCRIPT_DIR, "*.jsonl")), key=os.path.getmtime)

    print(f"Found {len(files)} transcript files")

    total_summaries = 0
    files_written = 0

    for filepath in files:
        size_mb = os.path.getsize(filepath) / 1024 / 1024
        if size_mb < 0.1:  # Skip tiny files
            continue

        summaries, start_date, session_id = extract_summaries(filepath)

        if summaries:
            outpath = write_narrative(summaries, start_date, session_id)
            if outpath:
                total_summaries += len(summaries)
                files_written += 1
                print(f"  {session_id[:12]}... ({size_mb:.0f}MB) → {len(summaries)} summaries → {os.path.basename(outpath)}")

    print(f"\nDone: {total_summaries} summaries from {files_written} sessions")


if __name__ == "__main__":
    main()
