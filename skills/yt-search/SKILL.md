---
name: yt-search
description: Search YouTube for videos, get metadata, and extract transcripts. Use when the user asks to find YouTube videos, search YouTube, get video info, or pull transcripts.
user_invocable: true
---

# YouTube Search Skill

Search YouTube, retrieve video metadata, and extract transcripts using yt-dlp.

## Script Location

`~/.claude/scripts/yt-search.py`

## Commands

### Search YouTube
```bash
python3 ~/.claude/scripts/yt-search.py search "claude code skills" -n 20
```
Returns JSON array: title, url, author, views, duration, date.

### Get Video Info
```bash
python3 ~/.claude/scripts/yt-search.py info "https://www.youtube.com/watch?v=VIDEO_ID"
```
Returns detailed metadata including description.

### Get Transcript
```bash
python3 ~/.claude/scripts/yt-search.py transcript "https://www.youtube.com/watch?v=VIDEO_ID"
```
Returns plain text transcript (auto-generated captions).

## Integration with NotebookLM

YouTube URLs can be sent directly to NotebookLM as sources — NotebookLM processes them natively (extracts captions itself). The typical workflow:

1. **Search**: `yt-search.py search "topic" -n 20` to find relevant videos
2. **Review**: Present results to user for approval
3. **Send to NotebookLM**: `notebooklm create --title "Research Topic"` then add URLs as sources
4. **Analyze**: Ask NotebookLM questions about the corpus
5. **Deliverables**: Request infographics, podcasts, flashcards, etc.

### Full Pipeline Example
```bash
# Step 1: Search
python3 ~/.claude/scripts/yt-search.py search "autonomous AI agents 2026" -n 15

# Step 2: Create notebook and add sources
notebooklm create --title "AI Agents Research"
# Then add each URL as a source via notebooklm commands

# Step 3: Query
notebooklm query "What are the top trends in autonomous AI agents?"

# Step 4: Generate deliverables
notebooklm generate audio_overview
notebooklm generate mind_map
```

## Parameters

| Param | Default | Description |
|-------|---------|-------------|
| query | required | Search terms |
| -n / --count | 10 | Number of results (max ~50) |

## Output Format (search)

```json
[
  {
    "title": "Video Title",
    "url": "https://www.youtube.com/watch?v=...",
    "author": "Channel Name",
    "views": 12345,
    "duration": "15:32",
    "date": "20260301"
  }
]
```

## Notes

- yt-dlp binary: `~/brainrot-radio/venv/bin/yt-dlp`
- Transcripts use auto-generated captions (not all videos have them)
- For NotebookLM integration, prefer sending URLs directly — NotebookLM handles caption extraction
- Search is rate-limited by YouTube; keep queries reasonable
