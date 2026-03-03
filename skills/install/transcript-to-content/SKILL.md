---
name: install-transcript-to-content
description: Install pipeline for converting call recordings and transcripts into structured notes
version: 1.0.0
installs:
  - transcript-processing-pipeline
requires:
  installed: ["voice-transcription"]
---

# Install: Transcript → Structured Content Pipeline

## What This Installs

- Pipeline that takes audio recordings or raw transcripts and produces structured notes
- Designed for: producer calls, pitch meetings, network notes calls, writers room recordings
- Outputs to the appropriate project's notes directory

## Steps

### 1. Ensure Voice Transcription is Installed

This depends on `install/voice-transcription`. Run that first if not installed.

### 2. Create Processing Script

Write `~/.claude/scripts/process-transcript.py` that:
1. Accepts audio file or text transcript
2. If audio: runs whisper transcription
3. Parses transcript into:
   - Action items (with assignees if mentioned)
   - Key decisions made
   - Open questions
   - Notes organized by topic
4. Outputs structured Markdown

### 3. Verify

```bash
# From audio:
python3 ~/.claude/scripts/process-transcript.py /path/to/recording.m4a --project "Imposter Syndrome"

# From text:
python3 ~/.claude/scripts/process-transcript.py /path/to/transcript.txt --project "Magic"
```

## Usage

When Kyle says "just got off a call" or provides a recording:
1. Transcribe the audio (if not already text)
2. Run through the processing pipeline
3. Save to `Screenwriting/Active/[Project]/producer-notes/`
4. Present structured summary for review
