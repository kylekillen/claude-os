---
name: install-voice-transcription
description: Install local Whisper speech-to-text for voice memos, voicemails, and audio files
version: 1.0.0
installs:
  - whisper-cpp
  - audio-transcription-pipeline
requires:
  bins: ["brew"]
---

# Install: Voice Transcription (Local Whisper)

## What This Installs

- `whisper.cpp` compiled for Apple Silicon — fully local, no API keys, no cloud upload
- Supports WAV, MP3, M4A, OGG, FLAC audio files
- ~2GB model download (one-time), then runs instantly

## Steps

### 1. Install whisper.cpp

```bash
brew install whisper-cpp
```

Or build from source for Apple Silicon optimization:
```bash
git clone https://github.com/ggerganov/whisper.cpp ~/whisper.cpp
cd ~/whisper.cpp && make -j
```

### 2. Download Model

```bash
# Medium model (good balance of speed/accuracy)
~/.claude/scripts/download-whisper-model.sh medium
# Or use whisper.cpp's built-in downloader:
cd ~/whisper.cpp && bash models/download-ggml-model.sh medium
```

### 3. Create Transcription Script

Write `~/.claude/scripts/transcribe.sh`:
```bash
#!/bin/bash
# Usage: transcribe.sh <audio-file> [output-file]
INPUT="$1"
OUTPUT="${2:-/tmp/transcription.txt}"
whisper-cpp --model ~/.local/share/whisper.cpp/ggml-medium.bin \
  --file "$INPUT" --output-txt --output-file "$OUTPUT"
cat "$OUTPUT"
```

### 4. Verify

```bash
chmod +x ~/.claude/scripts/transcribe.sh
# Test with any audio file:
~/.claude/scripts/transcribe.sh /path/to/audio.m4a
```

## Usage

When you encounter an audio file (voice memo, voicemail, recording):
```bash
~/.claude/scripts/transcribe.sh "/path/to/audio.m4a"
```

For producer call recordings, transcribe then use the notes-review workflow.
