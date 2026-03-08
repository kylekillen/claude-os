---
name: notes-review
description: Use this skill when the user says "there's notes to review", "got notes in my email", "received feedback", "producer notes came in", "network notes", or mentions reviewing notes on a project.
session-management: true
---

# Notes Review Workflow

<!--
COMPACTION-SAFE SUMMARY:
Step 0: Run memory search Python code BEFORE reviewing notes.
Output: "Memory search: Found X sessions, Y memories for [PROJECT]"
Show the RAW OUTPUT. NEVER skip this. NEVER fake the output.
If prior notes sessions found: Read them to understand prior discussions.
-->

**Session Management:** See `~/.claude/skills/_templates/session-management.md` — update state file on launch, pause, close, and resume.

Collaborative process for triaging and discussing creative notes with Kyle.

## STEP 0: MEMORY SEARCH (REQUIRED - DO NOT SKIP)

**STOP. Search for prior notes discussions on this project.**

Replace `PROJECT_NAME` with the actual project (e.g., "imposter syndrome", "man on fire").

```python
from pathlib import Path
import json
from datetime import datetime, timedelta

creds = json.loads((Path.home() / ".config/personal-os/credentials.json").read_text())
sb = creds["supabase"]
from supabase import create_client
supabase = create_client(sb["url"], sb["service_role_key"])

TARGET = "PROJECT_NAME"  # REPLACE with actual project name

# 1. Search pos_sessions for prior notes work
sessions = supabase.table("pos_sessions").select("*").ilike("summary", f"%{TARGET}%notes%").order("ended_at", desc=True).limit(5).execute()

# 2. Semantic search for notes discussions
semantic_ok = False
try:
    from sentence_transformers import SentenceTransformer
    model = SentenceTransformer('all-MiniLM-L6-v2')
    query = f"notes review feedback discussion {TARGET}"
    embedding = model.encode(query[:4000], convert_to_numpy=True).tolist()
    memories = supabase.rpc("search_memories", {
        "query_embedding": embedding,
        "match_threshold": 0.25,
        "match_count": 5
    }).execute()
    semantic_ok = True
except ImportError:
    memories = None
    print("WARNING: sentence-transformers not installed")
except Exception as e:
    memories = None
    print(f"Semantic search error: {e}")

print(f"\n=== MEMORY SEARCH FOR '{TARGET}' NOTES ===")
print(f"Prior notes sessions: {len(sessions.data) if sessions.data else 0}")
print(f"Related memories: {len(memories.data) if memories and memories.data else 0}")
print(f"Semantic: {'enabled' if semantic_ok else 'DISABLED'}")
```

**REQUIRED OUTPUT:** "Memory search: Found [N] sessions, [M] memories for [PROJECT] notes"

| Situation | Action |
|-----------|--------|
| **Prior sessions found** | Read session logs for prior verdicts (EXECUTE/CONCEDE/FIGHT/GARBAGE) |
| **Zero results** | Say: "No prior notes sessions - starting fresh" |
| **Search fails** | STOP and ask Kyle before proceeding |

**DO NOT PROCEED until you have shown the actual search output.**

---

## Prerequisites

Before starting, read Kyle's writing style guide:
```
~/.claude/skills/writing-style.md
```

This primes you for how Kyle approaches notes: triage first, fire bullets and reload, look for the note behind the note.

## Step 1: Find the Notes

Search Gmail for the notes:
```bash
python3 "/Users/kylekillen/Library/CloudStorage/GoogleDrive-kyle.killen@gmail.com/My Drive/Personal-OS-v2/system/scripts/google_api.py" gmail search "[project name] notes OR feedback"
```

If notes are in an attachment:
```bash
python3 "/Users/kylekillen/Library/CloudStorage/GoogleDrive-kyle.killen@gmail.com/My Drive/Personal-OS-v2/system/scripts/google_api.py" gmail attachments "[project name]"
python3 "/Users/kylekillen/Library/CloudStorage/GoogleDrive-kyle.killen@gmail.com/My Drive/Personal-OS-v2/system/scripts/google_api.py" gmail download <msg_id> <att_id> /tmp/notes.pdf
```

Extract text from PDF if needed:
```bash
pdftotext /tmp/notes.pdf /tmp/notes.txt
```

## Step 2: Find the Project Document

Search Drive for the document being noted:
```bash
python3 "/Users/kylekillen/Library/CloudStorage/GoogleDrive-kyle.killen@gmail.com/My Drive/Personal-OS-v2/system/scripts/google_api.py" drive search "[project name] pitch OR script"
```

Export to markdown:
```bash
python3 "/Users/kylekillen/Library/CloudStorage/GoogleDrive-kyle.killen@gmail.com/My Drive/Personal-OS-v2/system/scripts/google_api.py" drive export <file_id> /tmp/project-doc.md
```

## Step 2b: Supporting Materials

If Kyle asks about supporting materials (bullet points, earlier drafts, audio transcripts, etc.):

1. Search Drive for related files in the project folder
2. If Kyle says he wants to **"edit"** or **"work on"** a supporting doc:
   - Export/copy the **actual text** into a markdown file
   - Add a "New Ideas" section at the bottom for appending
   - **DO NOT summarize** - preserve the original text verbatim
3. If Kyle says **"open"** a file, he wants the text itself, not a summary
4. These become working documents we can add to during discussion

## Step 2c: Audio Files / Walkthroughs

Search for associated audio recordings:
```bash
python3 "/Users/kylekillen/Library/CloudStorage/GoogleDrive-kyle.killen@gmail.com/My Drive/Personal-OS-v2/system/scripts/google_api.py" drive search "[project name] walkthrough OR audio OR recording"
```

If found, download and transcribe:
```bash
python3 "/Users/kylekillen/Library/CloudStorage/GoogleDrive-kyle.killen@gmail.com/My Drive/Personal-OS-v2/system/scripts/google_api.py" drive download <file_id> /tmp/[project]-audio.m4a
whisper /tmp/[project]-audio.m4a --model base --output_format txt --output_dir /tmp/
```

## Step 3: Set Up Working Files

**Important:** Create files IN THE PROJECT FOLDER, not in drafts/.

1. Find the project folder:
   ```
   Personal-OS-v2/Screenwriting/Active/[Project Name]/
   ```

2. Create a `producer-notes/` subfolder if it doesn't exist:
   ```bash
   mkdir -p "Personal-OS-v2/Screenwriting/Active/[Project Name]/producer-notes"
   ```

3. Create working files there:
   - `[project]-draft.md` — the document being noted (for reference)
   - `[project]-notes-discussion.md` — will grow as we talk
   - `[project]-transcript.md` — if audio was transcribed

Tell Kyle to open the files in VS Code.

## Step 4: Triage the Notes

Go through notes ONE AT A TIME, conversationally. For each note:

1. Read the note aloud (Kyle prefers hearing to reading)
2. Give your take: good note, neutral, or trouble?
3. Ask Kyle's instinct
4. Discuss until there's a verdict
5. Append the verdict and reasoning to the discussion file

### Verdicts to assign:
- **EXECUTE** - Good note, do it
- **CONCEDE** - Neutral, worth doing to build capital
- **FIGHT** - Trouble note, defend against it
- **GARBAGE** - Misunderstanding, easy clarification fixes it

### Always look for:
- The note behind the note (what they can't articulate)
- Whether big notes will obviate smaller ones
- Arguments Kyle can use when pushing back

## Step 5: Files Are Already in Drive

Since we created files directly in the project's `producer-notes/` folder, they're already syncing to Drive. No upload step needed.

When done or pausing, just ensure the discussion file is saved.

## Rules

1. **Triage before execution** - Never start revising until all notes are discussed
2. **One note at a time** - Don't overwhelm with the full list
3. **Kyle's instincts lead** - You offer perspective, he decides
4. **Update the file as you go** - The discussion is the artifact
5. **Style guide is your primer** - Reference it for Kyle's philosophy
