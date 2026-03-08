#!/usr/bin/env python3
"""
Markdown-first hybrid search engine for Memory v3.

Replaces hybrid-search.py (which searched SQLite observations).
Searches markdown files in configured directories using:
  - FTS5 keyword search on markdown chunks
  - Semantic search via sentence-transformers embeddings
  - MMR diversity reranking

Chunks are markdown sections split at ## headers.
Index is stored in ~/.claude-mem/markdown-index.db.

Usage:
    # Index all markdown files (run once, then incrementally)
    python3 markdown-search.py --index

    # Search
    python3 markdown-search.py --query "kalshi copybot maker orders"

    # Search with options
    python3 markdown-search.py --query "data center land" --top 10
    python3 markdown-search.py --query "weather arbitrage" --mode semantic
"""

import sqlite3
import os
import sys
import json
import hashlib
import argparse
import time
import glob
import numpy as np
from datetime import datetime, timedelta

DB_PATH = os.path.expanduser("~/.claude-mem/markdown-index.db")

# Directories to search (relative to project root)
PERSONAL_OS = os.environ.get("CLAUDE_OS_PROJECT_ROOT", "")
if PERSONAL_OS and not PERSONAL_OS.endswith("/"):
    PERSONAL_OS += "/"
SEARCH_DIRS = [
    "memory/",
    "sessions/narratives/",
    "Financial/",
    "Trading/",
    "mojo-work/",
    "Code/",
    "Health/",
    "Contacts/",
    "Screenwriting/Active/Imposter Syndrome/",
    "Screenwriting/Active/Magic/",
    "Screenwriting/Active/Myst/",
    "drafts/",
]

# Also index root-level .md files (non-recursive) — CLAUDE.md, HEARTBEAT.md, etc.
INDEX_ROOT_FILES = True

# Subdirectories to exclude (verbose logs, vendor code, changelogs)
EXCLUDE_PATTERNS = [
    "/sessions/20",          # Verbose session transcripts (Code/*/sessions/)
    "/node_modules/",
    "/CHANGELOG.md",
    "/LICENSE.md",
    "bug-bounty/",           # All bug-bounty vendor repos and analysis (1900+ noise chunks)
    ".obsidian/",
    "/lib/forge-std/",       # Solidity vendor libs
    "/lib/openzeppelin",     # OpenZeppelin vendor libs
    "/lib/chainlink",        # Chainlink vendor libs
]

# Also search the auto-memory directory (auto-detect by globbing)
_memory_matches = glob.glob(os.path.expanduser("~/.claude/projects/*/memory/"))
AUTO_MEMORY = _memory_matches[0] if _memory_matches else ""

MODEL_NAME = "all-MiniLM-L6-v2"
EMBEDDING_DIM = 384

# Search weights
FTS_WEIGHT = 0.4
SEMANTIC_WEIGHT = 0.6
SCORE_THRESHOLD = 0.10
MMR_LAMBDA = 0.7
DOMAIN_BOOST = 1.4  # Multiply score by this when query domain matches chunk domain

# Domain classification rules (path substring -> domain)
DOMAIN_RULES = [
    ("Trading/", "trading"),
    ("Financial/", "financial"),
    ("Screenwriting/", "screenwriting"),
    ("Health/", "health"),
    ("Code/", "code"),
    ("Contacts/", "contacts"),
    ("mojo-work/", "system"),
    ("memory/", "system"),
    ("sessions/", "system"),
    ("drafts/", "system"),
    ("HEARTBEAT", "system"),
    ("CLAUDE.md", "system"),
]

# Query keywords that signal a domain
DOMAIN_KEYWORDS = {
    "trading": ["trading", "kalshi", "polymarket", "arbitrage", "arb", "bot", "position",
                "market", "spread", "maker", "taker", "alpaca", "momentum", "backtest"],
    "financial": ["financial", "investment", "schwab", "tax", "401k", "ira", "roth",
                  "portfolio", "net worth", "fpl", "dew wealth", "blackstone"],
    "screenwriting": ["screenplay", "pitch", "imposter", "magic", "myst", "script",
                      "outline", "producer", "notes", "halo", "man on fire", "pilot",
                      "episode", "beat sheet", "red deck"],
    "health": ["health", "fitbit", "labs", "workout", "tonal", "sleep", "heart rate",
               "blood", "cholesterol", "weight"],
    "code": ["code", "spotify", "limen", "laten", "github", "deploy", "vercel",
             "nextjs", "react", "python", "typescript", "mcp", "api"],
    "system": ["memory", "heartbeat", "daemon", "hook", "session", "claude",
               "narrative", "compaction", "mojo"],
}

def classify_domain(filepath):
    """Classify a file into a domain based on its path."""
    for pattern, domain in DOMAIN_RULES:
        if pattern in filepath:
            return domain
    return "general"


def detect_query_domain(query):
    """Detect which domain a query is about based on keywords."""
    lower = query.lower()
    scores = {}
    for domain, keywords in DOMAIN_KEYWORDS.items():
        score = sum(1 for kw in keywords if kw in lower)
        if score > 0:
            scores[domain] = score
    if not scores:
        return None
    return max(scores, key=scores.get)


# Lazy model
_model = None


def get_model():
    global _model
    if _model is None:
        from sentence_transformers import SentenceTransformer
        _model = SentenceTransformer(MODEL_NAME, device="cpu")
    return _model


def init_db(db):
    """Create tables if they don't exist."""
    db.execute("""
        CREATE TABLE IF NOT EXISTS chunks (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            file_path TEXT NOT NULL,
            section_header TEXT,
            chunk_text TEXT NOT NULL,
            file_mtime REAL,
            content_hash TEXT,
            embedding BLOB,
            created_at TEXT DEFAULT CURRENT_TIMESTAMP
        )
    """)
    db.execute("""
        CREATE INDEX IF NOT EXISTS idx_chunks_filepath ON chunks(file_path)
    """)
    db.execute("""
        CREATE INDEX IF NOT EXISTS idx_chunks_hash ON chunks(content_hash)
    """)

    # FTS5 virtual table (standalone, not content-synced — avoids corruption)
    db.execute("""
        CREATE VIRTUAL TABLE IF NOT EXISTS chunks_fts USING fts5(
            section_header,
            chunk_text
        )
    """)

    # Migrate: add columns if missing
    cols = [r[1] for r in db.execute("PRAGMA table_info(chunks)").fetchall()]
    if "access_count" not in cols:
        db.execute("ALTER TABLE chunks ADD COLUMN access_count INTEGER DEFAULT 0")
    if "domain" not in cols:
        db.execute("ALTER TABLE chunks ADD COLUMN domain TEXT DEFAULT 'general'")
    if "feedback_boost" not in cols:
        db.execute("ALTER TABLE chunks ADD COLUMN feedback_boost REAL DEFAULT 1.0")

    # Search feedback log
    db.execute("""
        CREATE TABLE IF NOT EXISTS search_log (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            query TEXT NOT NULL,
            query_domain TEXT,
            result_ids TEXT,
            result_count INTEGER,
            searched_at TEXT DEFAULT CURRENT_TIMESTAMP
        )
    """)

    db.commit()


def chunk_markdown(filepath):
    """Split a markdown file into sections at ## headers."""
    sections = []
    current_header = "intro"
    current_lines = []

    try:
        with open(filepath, "r", errors="replace") as f:
            for line in f:
                if line.startswith("## "):
                    if current_lines:
                        text = "\n".join(current_lines).strip()
                        if len(text) > 20:  # Skip near-empty sections
                            sections.append((current_header, text))
                    current_header = line.strip("# \n")
                    current_lines = []
                elif line.startswith("# ") and not current_lines:
                    # Top-level header, use as section header
                    current_header = line.strip("# \n")
                else:
                    current_lines.append(line.rstrip())

        # Last section
        if current_lines:
            text = "\n".join(current_lines).strip()
            if len(text) > 20:
                sections.append((current_header, text))

    except (IOError, OSError):
        pass

    # If no sections found (no ## headers), treat whole file as one chunk
    if not sections:
        try:
            with open(filepath, "r", errors="replace") as f:
                text = f.read().strip()
                if len(text) > 20:
                    sections.append(("full", text))
        except (IOError, OSError):
            pass

    # Truncate very long chunks (>2000 chars) to keep embeddings focused
    truncated = []
    for header, text in sections:
        if len(text) > 2000:
            truncated.append((header, text[:2000]))
        else:
            truncated.append((header, text))

    return truncated


def content_hash(text):
    return hashlib.md5(text.encode()).hexdigest()


def _is_excluded(filepath):
    """Check if a file path matches any exclusion pattern."""
    for pat in EXCLUDE_PATTERNS:
        if pat in filepath:
            return True
    return False


def find_markdown_files():
    """Find all .md files in configured search directories."""
    files = []

    # Personal-OS-v2 directories (recursive)
    for subdir in SEARCH_DIRS:
        full_path = os.path.join(PERSONAL_OS, subdir)
        if os.path.isdir(full_path):
            for md in glob.glob(os.path.join(full_path, "**", "*.md"), recursive=True):
                if not _is_excluded(md):
                    files.append(md)

    # Root-level .md files (non-recursive — catches CLAUDE.md, HEARTBEAT.md, etc.)
    if INDEX_ROOT_FILES:
        for md in glob.glob(os.path.join(PERSONAL_OS, "*.md")):
            if not _is_excluded(md):
                files.append(md)

    # Auto-memory directory
    if os.path.isdir(AUTO_MEMORY):
        for md in glob.glob(os.path.join(AUTO_MEMORY, "**", "*.md"), recursive=True):
            if not _is_excluded(md):
                files.append(md)

    return files


def index_files(db, model, force=False):
    """Index markdown files — only re-index files whose mtime changed."""
    files = find_markdown_files()
    print(f"Found {len(files)} markdown files to index")

    # Get existing file mtimes from DB
    existing = {}
    for row in db.execute("SELECT DISTINCT file_path, file_mtime FROM chunks"):
        existing[row[0]] = row[1]

    indexed = 0
    skipped = 0
    chunks_total = 0

    for filepath in files:
        try:
            mtime = os.path.getmtime(filepath)
        except OSError:
            continue

        # Skip if file hasn't changed (unless force)
        if not force and filepath in existing and abs(existing[filepath] - mtime) < 1:
            skipped += 1
            continue

        # Remove old chunks for this file
        db.execute("DELETE FROM chunks WHERE file_path = ?", (filepath,))

        # Chunk the file
        sections = chunk_markdown(filepath)
        if not sections:
            continue

        # Embed all chunks
        texts = [f"{header}: {text}" for header, text in sections]
        embeddings = model.encode(texts, show_progress_bar=False, normalize_embeddings=True)

        # Insert chunks
        domain = classify_domain(filepath)
        for (header, text), emb in zip(sections, embeddings):
            chash = content_hash(text)
            emb_blob = emb.astype(np.float32).tobytes()
            db.execute("""
                INSERT INTO chunks (file_path, section_header, chunk_text, file_mtime, content_hash, embedding, domain)
                VALUES (?, ?, ?, ?, ?, ?, ?)
            """, (filepath, header, text, mtime, chash, emb_blob, domain))

        chunks_total += len(sections)
        indexed += 1

        if indexed % 10 == 0:
            db.commit()

    # Rebuild FTS index (drop and recreate to avoid corruption)
    db.execute("DROP TABLE IF EXISTS chunks_fts")
    db.execute("""
        CREATE VIRTUAL TABLE chunks_fts USING fts5(
            chunk_id,
            section_header,
            chunk_text
        )
    """)
    db.execute("""
        INSERT INTO chunks_fts(chunk_id, section_header, chunk_text)
        SELECT CAST(id AS TEXT), section_header, chunk_text FROM chunks
    """)
    db.commit()

    # Remove chunks for deleted files
    indexed_paths = set(files)
    db_paths = set(r[0] for r in db.execute("SELECT DISTINCT file_path FROM chunks"))
    stale = db_paths - indexed_paths
    if stale:
        for p in stale:
            db.execute("DELETE FROM chunks WHERE file_path = ?", (p,))
        db.commit()
        print(f"Removed {len(stale)} stale files from index")

    total_chunks = db.execute("SELECT COUNT(*) FROM chunks").fetchone()[0]
    print(f"Indexed {indexed} files ({chunks_total} chunks), skipped {skipped} unchanged")
    print(f"Total index: {total_chunks} chunks from {len(files)} files")
    return indexed


def compute_feedback(db):
    """Analyze search_log to compute per-chunk feedback boosts.

    Runs after indexing. Reads search history and adjusts chunk scores:
    - Domain-specific chunks (only returned for their own domain) get boosted
    - Noise chunks (returned for many unrelated domains) get penalized
    - Requires 30+ logged searches to be meaningful

    Writes feedback_boost (0.5-1.5) to chunks table. Applied during search.
    """
    total_searches = db.execute("SELECT COUNT(*) FROM search_log").fetchone()[0]
    if total_searches < 30:
        print(f"Feedback: skipped ({total_searches} searches, need 30+)")
        return

    rows = db.execute("SELECT query_domain, result_ids FROM search_log WHERE result_ids != ''").fetchall()

    # Count per-chunk: how many times returned, and for which domains
    chunk_stats = {}
    for query_domain, result_ids_str in rows:
        if not result_ids_str:
            continue
        for cid_str in result_ids_str.split(","):
            try:
                cid = int(cid_str.strip())
            except ValueError:
                continue
            if cid not in chunk_stats:
                chunk_stats[cid] = {"total": 0, "domains": {}}
            chunk_stats[cid]["total"] += 1
            if query_domain:
                chunk_stats[cid]["domains"][query_domain] = chunk_stats[cid]["domains"].get(query_domain, 0) + 1

    if not chunk_stats:
        return

    # Get chunk domains from DB
    all_cids = list(chunk_stats.keys())
    chunk_domains = {}
    for batch_start in range(0, len(all_cids), 500):
        batch = all_cids[batch_start:batch_start + 500]
        placeholders = ",".join("?" * len(batch))
        for row in db.execute(f"SELECT id, COALESCE(domain, 'general') FROM chunks WHERE id IN ({placeholders})", batch):
            chunk_domains[row[0]] = row[1]

    updated = 0
    for cid, stats in chunk_stats.items():
        chunk_domain = chunk_domains.get(cid, "general")
        total = stats["total"]
        domains = stats["domains"]

        # Specificity: what fraction of appearances are for this chunk's own domain?
        own_domain_hits = domains.get(chunk_domain, 0)
        specificity = own_domain_hits / total if total > 0 else 0.5

        # Noise: how many different domains return this chunk?
        unique_domains = len(domains)
        noise = unique_domains / max(len(DOMAIN_KEYWORDS), 1)

        # Compute boost:
        # High specificity → boost (chunk is domain-relevant)
        # High noise → penalize (chunk is generic/matches everything)
        boost = 1.0
        boost += 0.3 * (specificity - 0.5)   # range: -0.15 to +0.15
        boost -= 0.3 * max(noise - 0.3, 0)   # penalize if spans many domains
        boost = max(0.5, min(1.5, boost))     # clamp

        db.execute("UPDATE chunks SET feedback_boost = ? WHERE id = ?", (boost, cid))
        updated += 1

    db.commit()
    print(f"Feedback: updated {updated} chunks from {total_searches} logged searches")


# --- Search ---

stopwords = {'a', 'an', 'the', 'is', 'are', 'was', 'were', 'be', 'been',
             'of', 'to', 'in', 'for', 'on', 'at', 'by', 'with', 'from',
             'it', 'its', 'that', 'this', 'do', 'did', 'does', 'what',
             'how', 'when', 'where', 'why', 'who', 'which', 'can', 'we',
             'i', 'my', 'our', 'you', 'your', 'me', 'us', 'and', 'or', 'not'}


def search_fts(db, query, limit=60):
    terms = [t for t in query.split() if len(t) > 1 and t.lower() not in stopwords]
    if not terms:
        return {}

    safe_query = " OR ".join(f'"{t}"' for t in terms[:10])
    try:
        rows = db.execute("""
            SELECT CAST(fts.chunk_id AS INTEGER), fts.rank
            FROM chunks_fts fts
            WHERE chunks_fts MATCH ?
            ORDER BY fts.rank
            LIMIT ?
        """, (safe_query, limit)).fetchall()
    except Exception:
        return {}

    if not rows:
        return {}

    ranks = [abs(r[1]) for r in rows]
    max_rank = max(ranks) if ranks else 1
    return {r[0]: 1.0 - (abs(r[1]) / max_rank) if max_rank > 0 else 0 for r in rows}


def search_semantic(db, model, query, limit=60):
    if model is None:
        return {}

    query_emb = model.encode([query], normalize_embeddings=True)[0]

    rows = db.execute("""
        SELECT id, embedding FROM chunks WHERE embedding IS NOT NULL
    """).fetchall()

    scores = []
    for cid, emb_blob in rows:
        emb = np.frombuffer(emb_blob, dtype=np.float32)
        if len(emb) == EMBEDDING_DIM:
            sim = float(np.dot(query_emb, emb))
            scores.append((cid, sim))

    scores.sort(key=lambda x: -x[1])
    top = scores[:limit]

    if not top:
        return {}

    max_sim = top[0][1]
    min_sim = top[-1][1] if len(top) > 1 else 0
    spread = max_sim - min_sim if max_sim != min_sim else 1
    return {cid: (sim - min_sim) / spread for cid, sim in top}


def hybrid_search(db, model, query, limit=15, mode="hybrid", boost_accessed=False, query_domain=None):
    fts_scores = {}
    sem_scores = {}

    if mode in ("hybrid", "keyword"):
        fts_scores = search_fts(db, query, limit=limit * 3)
    if mode in ("hybrid", "semantic"):
        sem_scores = search_semantic(db, model, query, limit=limit * 3)

    all_ids = set(fts_scores.keys()) | set(sem_scores.keys())

    # Pre-fetch access counts, domains, and feedback boosts
    chunk_meta = {}
    if all_ids:
        placeholders = ",".join("?" * len(all_ids))
        for row in db.execute(
            f"SELECT id, COALESCE(access_count, 0), COALESCE(domain, 'general'), COALESCE(feedback_boost, 1.0) FROM chunks WHERE id IN ({placeholders})",
            list(all_ids)
        ).fetchall():
            chunk_meta[row[0]] = {"access_count": row[1], "domain": row[2], "feedback_boost": row[3]}

    combined = []

    for cid in all_ids:
        fts = fts_scores.get(cid, 0)
        sem = sem_scores.get(cid, 0)

        if mode == "hybrid":
            score = FTS_WEIGHT * fts + SEMANTIC_WEIGHT * sem
        elif mode == "keyword":
            score = fts
        else:
            score = sem

        meta = chunk_meta.get(cid, {})

        # Domain boost: if query is about trading and chunk is from Trading/, boost it
        if query_domain and meta.get("domain") == query_domain:
            score *= DOMAIN_BOOST

        # Feedback boost: learned from search history (specificity vs noise)
        score *= meta.get("feedback_boost", 1.0)

        # Access count boost: chunks that were useful before get a mild boost
        if boost_accessed:
            import math
            ac = meta.get("access_count", 0)
            score *= math.log(ac + 2)  # log(2)=0.69 for never-accessed, log(22)=3.09 for 20-access

        if score >= SCORE_THRESHOLD:
            combined.append((cid, score, fts, sem))

    combined.sort(key=lambda x: -x[1])
    return combined[:limit]


def increment_access(db, ids):
    """Increment access_count for chunks that were returned in search results."""
    if not ids:
        return
    placeholders = ",".join("?" * len(ids))
    db.execute(f"UPDATE chunks SET access_count = COALESCE(access_count, 0) + 1 WHERE id IN ({placeholders})", ids)
    db.commit()


def format_results(db, results):
    """Format search results for context injection."""
    if not results:
        return ""

    ids = [r[0] for r in results]
    increment_access(db, ids)
    placeholders = ",".join("?" * len(ids))
    rows = db.execute(f"""
        SELECT id, file_path, section_header, chunk_text
        FROM chunks WHERE id IN ({placeholders})
    """, ids).fetchall()

    chunk_map = {r[0]: r for r in rows}

    lines = ["# Relevant Context (markdown search)\n"]

    for cid, score, fts, sem in results:
        chunk = chunk_map.get(cid)
        if not chunk:
            continue

        _, fpath, header, text = chunk

        # Make path relative for display
        rel_path = fpath
        for prefix in [PERSONAL_OS, AUTO_MEMORY]:
            if fpath.startswith(prefix):
                rel_path = fpath[len(prefix):]
                break

        # Truncate text for injection
        display_text = text[:500]
        if len(text) > 500:
            display_text += "..."

        lines.append(f"**[{rel_path}] {header}** (score: {score:.2f})")
        lines.append(f"{display_text}\n")

    return "\n".join(lines)


def display_results(db, results, verbose=False):
    """Display results in terminal."""
    if not results:
        print("No results found.")
        return

    ids = [r[0] for r in results]
    increment_access(db, ids)
    placeholders = ",".join("?" * len(ids))
    rows = db.execute(f"""
        SELECT id, file_path, section_header, chunk_text
        FROM chunks WHERE id IN ({placeholders})
    """, ids).fetchall()

    chunk_map = {r[0]: r for r in rows}

    print(f"\n{'#':>4} {'Score':>6} {'FTS':>5} {'Sem':>5} {'File':<40} Section")
    print("-" * 90)

    for cid, score, fts, sem in results:
        chunk = chunk_map.get(cid)
        if not chunk:
            continue
        _, fpath, header, text = chunk

        # Shorten path
        rel = os.path.basename(fpath)
        print(f"#{cid:>3} {score:>6.3f} {fts:>5.2f} {sem:>5.2f} {rel:<40} {header[:30]}")
        if verbose:
            print(f"     {text[:120]}")


def main():
    parser = argparse.ArgumentParser(description="Markdown-first hybrid search")
    parser.add_argument("--index", action="store_true", help="Index/reindex markdown files")
    parser.add_argument("--force", action="store_true", help="Force reindex all files")
    parser.add_argument("--query", "-q", type=str, help="Search query")
    parser.add_argument("--top", "-n", type=int, default=15, help="Number of results")
    parser.add_argument("--mode", choices=["hybrid", "keyword", "semantic"], default="hybrid")
    parser.add_argument("--verbose", "-v", action="store_true")
    parser.add_argument("--format", choices=["terminal", "inject"], default="terminal")
    parser.add_argument("--stats", action="store_true", help="Show access count distribution")
    parser.add_argument("--prune-candidates", action="store_true",
                        help="Show chunks with zero access older than 30 days")
    parser.add_argument("--boost-accessed", action="store_true",
                        help="Weight results by relevance * log(access_count + 1)")
    args = parser.parse_args()

    os.makedirs(os.path.dirname(DB_PATH), exist_ok=True)
    db = sqlite3.connect(DB_PATH, timeout=10)
    db.execute("PRAGMA journal_mode=WAL")
    init_db(db)

    if args.index:
        print("Loading sentence-transformer model...")
        model = get_model()
        t0 = time.time()
        index_files(db, model, force=args.force)
        compute_feedback(db)
        print(f"Indexing took {time.time() - t0:.1f}s")

    if args.stats:
        total = db.execute("SELECT COUNT(*) FROM chunks").fetchone()[0]
        zero = db.execute("SELECT COUNT(*) FROM chunks WHERE COALESCE(access_count, 0) = 0").fetchone()[0]
        low = db.execute("SELECT COUNT(*) FROM chunks WHERE access_count BETWEEN 1 AND 5").fetchone()[0]
        mid = db.execute("SELECT COUNT(*) FROM chunks WHERE access_count BETWEEN 6 AND 20").fetchone()[0]
        high = db.execute("SELECT COUNT(*) FROM chunks WHERE access_count > 20").fetchone()[0]
        print(f"\n--- Access Count Distribution ({total} total chunks) ---")
        print(f"  0 accesses:    {zero:>5}  ({100*zero/total:.1f}%)" if total else "  No chunks")
        print(f"  1-5 accesses:  {low:>5}  ({100*low/total:.1f}%)" if total else "")
        print(f"  6-20 accesses: {mid:>5}  ({100*mid/total:.1f}%)" if total else "")
        print(f"  20+ accesses:  {high:>5}  ({100*high/total:.1f}%)" if total else "")

    if args.prune_candidates:
        cutoff = (datetime.now() - timedelta(days=30)).strftime("%Y-%m-%d %H:%M:%S")
        candidates = db.execute("""
            SELECT id, file_path, section_header, created_at
            FROM chunks
            WHERE COALESCE(access_count, 0) = 0
              AND created_at < ?
            ORDER BY created_at ASC
        """, (cutoff,)).fetchall()
        print(f"\n--- Prune Candidates: {len(candidates)} chunks (0 access, >30 days old) ---")
        for cid, fpath, header, created in candidates[:50]:
            rel = os.path.basename(fpath)
            print(f"  #{cid:>4}  {created[:10]}  {rel:<35}  {header[:40]}")
        if len(candidates) > 50:
            print(f"  ... and {len(candidates) - 50} more")

    if args.query:
        model = get_model() if args.mode in ("hybrid", "semantic") else None
        qd = detect_query_domain(args.query)
        t0 = time.time()
        results = hybrid_search(db, model, args.query, limit=args.top, mode=args.mode,
                                boost_accessed=args.boost_accessed, query_domain=qd)
        elapsed = time.time() - t0

        # Log the search for feedback tracking
        try:
            result_ids = ",".join(str(r[0]) for r in results)
            db.execute("""
                INSERT INTO search_log (query, query_domain, result_ids, result_count)
                VALUES (?, ?, ?, ?)
            """, (args.query[:500], qd, result_ids, len(results)))
            db.commit()
        except Exception:
            pass

        if args.format == "inject":
            print(format_results(db, results))
        else:
            display_results(db, results, verbose=args.verbose)
            domain_info = f", domain={qd}" if qd else ""
            print(f"\n({elapsed:.2f}s, mode={args.mode}{domain_info})")

    db.close()


if __name__ == "__main__":
    main()
