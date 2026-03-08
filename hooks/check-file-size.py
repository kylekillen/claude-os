#!/usr/bin/env python3
"""
Personal OS v2: Pre-Read Hook
Warns about very large files but no longer blocks PDFs (Read tool handles them natively).
Only blocks truly dangerous files (multi-GB binaries, archives).
"""

import json
import sys
import os

# Hard block at 50MB (binary files that would crash context)
HARD_LIMIT = 50 * 1024 * 1024

# PDF/document extensions handled natively by Claude's Read tool
NATIVE_EXTENSIONS = {'.pdf', '.ipynb'}

# Archive/binary extensions that should still be blocked when large
BINARY_EXTENSIONS = {'.zip', '.tar', '.gz', '.bz2', '.7z', '.dmg', '.iso', '.bin'}

try:
    data = json.load(sys.stdin)
    file_path = data.get('tool_input', {}).get('file_path', '')

    if not file_path or not os.path.exists(file_path):
        sys.exit(0)

    size_bytes = os.path.getsize(file_path)
    size_kb = size_bytes / 1024
    ext = os.path.splitext(file_path)[1].lower()

    # PDFs and notebooks are handled natively — never block
    if ext in NATIVE_EXTENSIONS:
        sys.exit(0)

    # Block truly huge binary files
    if ext in BINARY_EXTENSIONS and size_bytes > HARD_LIMIT:
        print(json.dumps({
            "continue": False,
            "stopReason": f"BLOCKED: Binary file is {size_kb/1024:.0f}MB. Extract or convert first."
        }))
        sys.exit(0)

    sys.exit(0)

except Exception as e:
    print(f"Hook error: {e}", file=sys.stderr)
    sys.exit(0)
