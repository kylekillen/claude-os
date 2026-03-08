#!/usr/bin/env python3
"""
Compound Loop v1 — Automated failure-to-rule pipeline.

Scans session narratives for FAILED sections, extracts structured failure records,
detects recurring patterns, and generates persistent decisions or skills.

Runs as part of the Stop pipeline after extract-narratives.py.

Usage:
    python3 compound-loop.py                # Extract + detect patterns
    python3 compound-loop.py --report       # Show current failure log + candidates
    python3 compound-loop.py --validate     # Check if generated rules prevented recurrence
"""

import os
import re
import json
import hashlib
from datetime import datetime, timedelta
from pathlib import Path
from difflib import SequenceMatcher

NARRATIVE_DIR = os.path.expanduser("~/.claude-mem/session-narratives/")
VAULT_ROOT = os.environ.get("CLAUDE_OS_PROJECT_ROOT", os.path.expanduser("~"))
FAILURE_LOG = os.path.join(VAULT_ROOT, "mojo-work/failure-log.json")
GENERATED_RULES_DIR = os.path.join(VAULT_ROOT, "mojo-work/compound-rules/")

# Similarity threshold for deduplication (0-1, higher = stricter)
SIMILARITY_THRESHOLD = 0.6
# How many occurrences before generating a rule
PATTERN_THRESHOLD = 3
# Days before checking if a rule worked
VALIDATION_DAYS = 7


def parse_failed_sections(filepath):
    """Extract bullet points from FAILED: sections in a narrative file."""
    with open(filepath, "r") as f:
        content = f.read()

    failures = []
    # Find all FAILED: sections
    for match in re.finditer(r"^FAILED:\s*\n((?:- .*\n?)+)", content, re.MULTILINE):
        block = match.group(1)
        for line in block.strip().split("\n"):
            line = line.strip()
            if line.startswith("- "):
                entry = line[2:].strip()
                # Skip "None" entries
                if entry.lower() == "none" or entry.lower() == "none.":
                    continue
                # Skip entries that are actually PENDING items that leaked in
                if any(entry.startswith(p) for p in ["Process ", "Investigate why Python"]):
                    # These are valid failures, keep them
                    pass
                failures.append(entry)

    # Extract date from filename (format: YYYY-MM-DD-HHMMSS-sessionid.md)
    basename = os.path.basename(filepath)
    date_match = re.match(r"(\d{4}-\d{2}-\d{2})", basename)
    date_str = date_match.group(1) if date_match else datetime.now().strftime("%Y-%m-%d")

    # Extract session ID from filename
    session_match = re.search(r"-([a-f0-9]{8})-", basename)
    session_id = session_match.group(1) if session_match else "unknown"

    return [(f, date_str, session_id) for f in failures]


def normalize_failure(text):
    """Normalize a failure description for comparison."""
    # Remove trailing punctuation, lowercase
    text = text.strip().rstrip(".").lower()
    # Remove specific numbers/dates that vary
    text = re.sub(r"\d+", "N", text)
    # Remove extra whitespace
    text = re.sub(r"\s+", " ", text)
    return text


def failure_key(text):
    """Generate a stable key for a failure type."""
    normalized = normalize_failure(text)
    return hashlib.md5(normalized.encode()).hexdigest()[:12]


def are_similar(a, b):
    """Check if two failure descriptions are similar enough to be the same class."""
    na = normalize_failure(a)
    nb = normalize_failure(b)
    return SequenceMatcher(None, na, nb).ratio() >= SIMILARITY_THRESHOLD


def load_failure_log():
    """Load existing failure log or return empty list."""
    if not os.path.exists(FAILURE_LOG):
        return []
    with open(FAILURE_LOG, "r") as f:
        data = json.load(f)
    return data if isinstance(data, list) else []


def save_failure_log(entries):
    """Save failure log."""
    os.makedirs(os.path.dirname(FAILURE_LOG), exist_ok=True)
    with open(FAILURE_LOG, "w") as f:
        json.dump(entries, f, indent=2, ensure_ascii=False)


def find_matching_entry(entries, failure_text):
    """Find an existing entry that matches this failure."""
    for entry in entries:
        if are_similar(entry["example"], failure_text):
            return entry
    return None


def extract_failures():
    """Scan all narratives, extract failures, deduplicate, update log."""
    entries = load_failure_log()

    # Track which session IDs we've already processed
    processed_sessions = set()
    for entry in entries:
        processed_sessions.update(entry.get("sessions", []))

    new_count = 0

    for filepath in sorted(Path(NARRATIVE_DIR).glob("*.md")):
        all_failures = parse_failed_sections(str(filepath))

        for failure_text, date_str, session_id in all_failures:
            # Skip if we've already processed this session
            if session_id in processed_sessions:
                continue

            existing = find_matching_entry(entries, failure_text)

            if existing:
                # Update frequency and last_seen
                existing["frequency"] = existing.get("frequency", 1) + 1
                existing["last_seen"] = max(existing.get("last_seen", ""), date_str)
                if session_id not in existing.get("sessions", []):
                    existing.setdefault("sessions", []).append(session_id)
                # Keep the most detailed example
                if len(failure_text) > len(existing.get("example", "")):
                    existing["example"] = failure_text
            else:
                # New failure class
                entries.append({
                    "failure_type": _classify_failure(failure_text),
                    "example": failure_text,
                    "frequency": 1,
                    "first_seen": date_str,
                    "last_seen": date_str,
                    "sessions": [session_id],
                    "resolution": _extract_resolution(failure_text),
                    "rule_generated": False,
                })
                new_count += 1

        # Mark this session's narratives as processed
        for _, _, sid in all_failures:
            processed_sessions.add(sid)

    save_failure_log(entries)
    return entries, new_count


def _classify_failure(text):
    """Auto-classify a failure into a type category."""
    text_lower = text.lower()
    if "429" in text or "rate limit" in text_lower:
        return "api-rate-limit"
    if "403" in text or "forbidden" in text_lower or "blocked" in text_lower:
        return "api-auth-error"
    if "timeout" in text_lower or "timed out" in text_lower:
        return "timeout"
    if "crash" in text_lower or "quit" in text_lower or "killed" in text_lower:
        return "process-crash"
    if "missing" in text_lower or "not found" in text_lower:
        return "missing-dependency"
    if "syntax error" in text_lower or "import error" in text_lower:
        return "code-error"
    if "daemon" in text_lower or "restart" in text_lower:
        return "daemon-issue"
    return "other"


def _extract_resolution(text):
    """Extract resolution from failure text if it contains 'Fixed with...' or similar."""
    patterns = [
        r"[Ff]ixed (?:with|by) (.+?)\.?$",
        r"[Rr]esolved (?:with|by) (.+?)\.?$",
        r"[Ss]witched to (.+?)\.?$",
    ]
    for pat in patterns:
        m = re.search(pat, text)
        if m:
            return m.group(1).strip()
    return None


def detect_patterns(entries):
    """Find failure classes that have hit the pattern threshold."""
    candidates = []
    for entry in entries:
        if entry["frequency"] >= PATTERN_THRESHOLD and not entry.get("rule_generated"):
            candidates.append(entry)
    return candidates


def generate_rule(entry):
    """Generate a persistent decision from a recurring failure pattern."""
    os.makedirs(GENERATED_RULES_DIR, exist_ok=True)

    ftype = entry["failure_type"]
    example = entry["example"]
    resolution = entry.get("resolution", "")
    freq = entry["frequency"]

    # Build the rule content
    rule_text = f"""# Compound Rule: {ftype}

**Generated:** {datetime.now().strftime("%Y-%m-%d")}
**Source:** Compound Loop v1 (auto-detected from {freq} occurrences)
**Validated:** false
**Validation date:** {(datetime.now() + timedelta(days=VALIDATION_DAYS)).strftime("%Y-%m-%d")}

## Pattern

Failure type `{ftype}` has occurred {freq} times across sessions.

**Example:** {example}

## Preventive Principle

"""
    # Generate specific prevention based on type
    if ftype == "api-rate-limit" and resolution:
        rule_text += f"When encountering rate limits, {resolution}. Check rate limit status before making API calls.\n"
    elif ftype == "api-auth-error" and resolution:
        rule_text += f"Ensure proper authentication headers. Previous fix: {resolution}.\n"
    elif ftype == "timeout":
        rule_text += "Add timeout handling and fallback mechanisms for long-running operations.\n"
    elif ftype == "process-crash":
        rule_text += "Isolate crash-prone processes (use subprocess, force CPU backend for ML models).\n"
    elif resolution:
        rule_text += f"Apply known fix: {resolution}.\n"
    else:
        rule_text += "No automated resolution found. Flagged for human review.\n"

    rule_text += f"""
## When to Apply

Apply this rule whenever the system encounters conditions matching: `{ftype}`

## Sessions Affected

{', '.join(entry.get('sessions', ['unknown']))}
"""

    # Write rule file
    filename = f"{ftype}-{failure_key(example)}.md"
    filepath = os.path.join(GENERATED_RULES_DIR, filename)
    with open(filepath, "w") as f:
        f.write(rule_text)

    # Mark as generated
    entry["rule_generated"] = True
    entry["rule_file"] = filename

    return filepath


def validate_rules(entries):
    """Check if generated rules actually prevented recurrence."""
    today = datetime.now().strftime("%Y-%m-%d")
    results = []

    for entry in entries:
        if not entry.get("rule_generated") or not entry.get("rule_file"):
            continue

        rule_path = os.path.join(GENERATED_RULES_DIR, entry["rule_file"])
        if not os.path.exists(rule_path):
            continue

        with open(rule_path, "r") as f:
            content = f.read()

        # Check if validation date has passed
        val_match = re.search(r"\*\*Validation date:\*\* (\d{4}-\d{2}-\d{2})", content)
        if not val_match:
            continue

        val_date = val_match.group(1)
        if today < val_date:
            continue  # Not yet time to validate

        # Check if already validated
        if "**Validated:** true" in content:
            continue

        # Did the failure recur after the rule was generated?
        gen_match = re.search(r"\*\*Generated:\*\* (\d{4}-\d{2}-\d{2})", content)
        gen_date = gen_match.group(1) if gen_match else "2000-01-01"

        if entry["last_seen"] > gen_date:
            # Failure recurred — rule didn't work
            results.append({"entry": entry, "status": "failed", "reason": "Failure recurred after rule was generated"})
        else:
            # No recurrence — mark validated
            content = content.replace("**Validated:** false", "**Validated:** true")
            with open(rule_path, "w") as f:
                f.write(content)
            results.append({"entry": entry, "status": "validated"})

    return results


def report(entries):
    """Print a human-readable report."""
    print(f"\n{'='*60}")
    print(f"COMPOUND LOOP REPORT — {datetime.now().strftime('%Y-%m-%d %H:%M')}")
    print(f"{'='*60}\n")

    print(f"Total failure classes tracked: {len(entries)}\n")

    # Sort by frequency
    by_freq = sorted(entries, key=lambda e: e.get("frequency", 0), reverse=True)

    print("TOP FAILURES:")
    for e in by_freq[:10]:
        status = ""
        if e.get("rule_generated"):
            status = " [RULE GENERATED]"
        print(f"  [{e['frequency']}x] {e['failure_type']}: {e['example'][:80]}{status}")

    # Candidates for rule generation
    candidates = detect_patterns(entries)
    if candidates:
        print(f"\nCANDIDATES FOR RULE GENERATION ({len(candidates)}):")
        for c in candidates:
            print(f"  - {c['failure_type']}: {c['example'][:80]} ({c['frequency']}x)")

    print()


def main():
    import sys

    if "--report" in sys.argv:
        entries = load_failure_log()
        report(entries)
        return

    if "--validate" in sys.argv:
        entries = load_failure_log()
        results = validate_rules(entries)
        save_failure_log(entries)
        for r in results:
            print(f"  {r['status']}: {r['entry']['failure_type']}")
        if not results:
            print("  No rules ready for validation yet.")
        return

    # Default: extract + detect + generate
    entries, new_count = extract_failures()
    print(f"Compound Loop: {len(entries)} failure classes ({new_count} new)")

    candidates = detect_patterns(entries)
    if candidates:
        print(f"  {len(candidates)} patterns hit threshold (>={PATTERN_THRESHOLD}x), generating rules...")
        for c in candidates:
            path = generate_rule(c)
            print(f"    Generated: {os.path.basename(path)}")
        save_failure_log(entries)  # Save rule_generated flags

    # Also run validation
    results = validate_rules(entries)
    save_failure_log(entries)
    for r in results:
        print(f"  Validation: {r['entry']['failure_type']} → {r['status']}")


if __name__ == "__main__":
    main()
