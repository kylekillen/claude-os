#!/usr/bin/env python3
"""
Entity extraction for claude-mem observations.

Extracts named entities (people, projects, files, concepts, markets) from
observations and links them in a junction table. Enables relationship queries
like "what do I know about Carter?" across all sessions.

Runs on Stop hook after memory-update.
"""

import sqlite3
import os
import re
import json
import time
import hashlib
from datetime import datetime, timezone

DB_PATH = os.path.expanduser("~/.claude-mem/claude-mem.db")
LOG_PATH = os.path.expanduser("~/.claude-mem/logs/extract-entities.log")

# Known entities and their aliases (bootstrap — grows over time)
KNOWN_ENTITIES = {
    'claude-mem': {'type': 'system', 'aliases': ['memory system', 'observation database', 'hybrid search']},
}

# Patterns for extracting new entities from text
FILE_PATTERN = re.compile(r'(?:^|[\s`])([a-zA-Z_][\w\-./]*\.(?:py|js|cjs|ts|md|json|sh|sql|yaml|yml))\b')
PERSON_PATTERN = re.compile(r'\b([A-Z][a-z]+(?:\s[A-Z][a-z]+)+)\b')


def log(msg):
    try:
        os.makedirs(os.path.dirname(LOG_PATH), exist_ok=True)
        with open(LOG_PATH, "a") as f:
            ts = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
            f.write(f"[{ts}] {msg}\n")
    except Exception:
        pass


def entity_id(name):
    """Generate stable ID from entity name."""
    return hashlib.md5(name.lower().strip().encode()).hexdigest()[:12]


def build_alias_index(db):
    """Build a lookup from all known aliases to entity IDs."""
    index = {}

    # From hardcoded known entities
    for name, info in KNOWN_ENTITIES.items():
        eid = entity_id(name)
        index[name.lower()] = eid
        for alias in info.get('aliases', []):
            index[alias.lower()] = eid

    # From existing entities in DB
    rows = db.execute("SELECT id, name, aliases FROM entities").fetchall()
    for eid, name, aliases_json in rows:
        index[name.lower()] = eid
        if aliases_json:
            try:
                for alias in json.loads(aliases_json):
                    index[alias.lower()] = eid
            except (json.JSONDecodeError, TypeError):
                pass

    return index


def extract_entities_from_text(text, alias_index):
    """Extract entity mentions from text. Returns list of (entity_id, name, type, role)."""
    if not text:
        return []

    found = []
    text_lower = text.lower()

    # Match known entities and aliases
    for alias, eid in alias_index.items():
        if alias in text_lower:
            # Get canonical name
            name = alias
            for known_name, info in KNOWN_ENTITIES.items():
                if entity_id(known_name) == eid:
                    name = known_name
                    break
            found.append((eid, name, 'mentioned'))

    # Extract file paths
    for match in FILE_PATTERN.finditer(text):
        filepath = match.group(1)
        if len(filepath) > 5:  # Skip very short filenames
            eid = entity_id(filepath)
            found.append((eid, filepath, 'file'))

    # Deduplicate by entity_id
    seen = set()
    unique = []
    for eid, name, role in found:
        if eid not in seen:
            seen.add(eid)
            unique.append((eid, name, role))

    return unique


def ensure_entity(db, eid, name, etype, epoch):
    """Create or update entity record."""
    existing = db.execute("SELECT id, observation_count FROM entities WHERE id = ?", (eid,)).fetchone()
    if existing:
        db.execute("""
            UPDATE entities SET last_seen_epoch = ?, observation_count = observation_count + 1
            WHERE id = ?
        """, (epoch, eid))
    else:
        # Determine type
        if etype == 'file':
            entity_type = 'file'
        elif eid in [entity_id(n) for n in KNOWN_ENTITIES]:
            for n, info in KNOWN_ENTITIES.items():
                if entity_id(n) == eid:
                    entity_type = info['type']
                    break
            else:
                entity_type = 'unknown'
        else:
            entity_type = 'unknown'

        aliases = json.dumps(KNOWN_ENTITIES.get(name, {}).get('aliases', []))
        db.execute("""
            INSERT INTO entities (id, name, entity_type, aliases, first_seen_epoch, last_seen_epoch, observation_count)
            VALUES (?, ?, ?, ?, ?, ?, 1)
        """, (eid, name, entity_type, aliases, epoch, epoch))


def process_observations(db):
    """Extract entities from recent unprocessed observations."""
    now_ms = int(datetime.now(timezone.utc).timestamp() * 1000)
    three_hours_ago = now_ms - (3 * 60 * 60 * 1000)

    # Get observations not yet entity-processed (not in junction table)
    recent = db.execute("""
        SELECT o.id, o.title, o.subtitle, o.facts, o.narrative, o.created_at_epoch
        FROM observations o
        WHERE o.created_at_epoch > ?
          AND o.valid_until_epoch IS NULL
          AND NOT EXISTS (
              SELECT 1 FROM observation_entities oe WHERE oe.observation_id = o.id
          )
        ORDER BY o.created_at_epoch DESC
    """, (three_hours_ago,)).fetchall()

    if not recent:
        log("No unprocessed recent observations")
        return 0, 0

    alias_index = build_alias_index(db)
    total_entities = 0
    total_links = 0

    for obs_id, title, subtitle, facts_json, narrative, epoch in recent:
        # Combine all text fields
        text_parts = [title or '', subtitle or '', narrative or '']
        if facts_json:
            try:
                facts = json.loads(facts_json)
                text_parts.extend(str(f) for f in facts if f)
            except (json.JSONDecodeError, TypeError):
                pass
        full_text = " ".join(text_parts)

        # Extract entities
        entities = extract_entities_from_text(full_text, alias_index)

        for eid, name, role in entities:
            etype = role if role == 'file' else 'mentioned'
            ensure_entity(db, eid, name, etype, epoch or now_ms)

            # Link observation to entity
            try:
                db.execute("""
                    INSERT OR IGNORE INTO observation_entities (observation_id, entity_id, role)
                    VALUES (?, ?, ?)
                """, (obs_id, eid, role))
                total_links += 1
            except Exception:
                pass

        total_entities += len(entities)

    db.commit()
    return len(recent), total_links


def main():
    t0 = time.time()

    if not os.path.exists(DB_PATH):
        log("No database found")
        return

    db = sqlite3.connect(DB_PATH, timeout=10)
    db.execute("PRAGMA journal_mode=WAL")

    processed, links = process_observations(db)
    elapsed = time.time() - t0

    log(f"Processed {processed} observations, created {links} entity links ({elapsed:.1f}s)")

    if processed > 0:
        # Report entity stats
        total = db.execute("SELECT COUNT(*) FROM entities").fetchone()[0]
        print(f"Entity extraction: {processed} observations processed, {links} links, {total} total entities ({elapsed:.1f}s)")

    db.close()


if __name__ == '__main__':
    main()
