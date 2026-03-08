#!/usr/bin/env python3
"""
Personal OS v2: Pre-Bash Hook
Intercepts cat commands on large files to prevent context overflow.
"""

import json
import sys
import os
import re

SIZE_LIMIT = 500 * 1024  # 500KB

try:
    data = json.load(sys.stdin)
    command = data.get('tool_input', {}).get('command', '')

    # Look for cat commands
    # Match: cat file, cat "file", cat 'file', cat /path/to/file
    cat_patterns = [
        r'\bcat\s+["\']?([^|;&\n"\']+)["\']?',
        r'\bhead\s+(?:-\d+\s+)?["\']?([^|;&\n"\']+)["\']?',
        r'\btail\s+(?:-\d+\s+)?["\']?([^|;&\n"\']+)["\']?',
    ]

    for pattern in cat_patterns:
        match = re.search(pattern, command)
        if match:
            file_path = match.group(1).strip()

            # Expand ~ to home directory
            if file_path.startswith('~'):
                file_path = os.path.expanduser(file_path)

            # Skip if file doesn't exist (let bash handle the error)
            if not os.path.exists(file_path):
                sys.exit(0)

            # Skip if it's a directory
            if os.path.isdir(file_path):
                sys.exit(0)

            size_bytes = os.path.getsize(file_path)
            size_kb = size_bytes / 1024

            if size_bytes > SIZE_LIMIT:
                print(json.dumps({
                    "continue": False,
                    "stopReason": f"BLOCKED: cat/head/tail on {size_kb:.0f}KB file (limit: 500KB). Use `large-file-processing` skill instead."
                }))
                sys.exit(0)

    # Allow command to proceed
    sys.exit(0)

except Exception as e:
    # Don't block on errors
    print(f"Hook error: {e}", file=sys.stderr)
    sys.exit(0)
