---
name: install-markitdown
description: Install Microsoft markitdown for converting PDFs, Office docs, images, and audio to Markdown
version: 1.0.0
installs:
  - markitdown-cli
  - markitdown-mcp
requires:
  bins: ["pip3"]
---

# Install: markitdown (Universal File → Markdown Converter)

## What This Installs

- `markitdown` CLI and Python library (87K GitHub stars)
- Converts: PDF, DOCX, PPTX, XLSX, HTML, images (with OCR), audio (with Whisper) → clean Markdown
- Optional MCP server mode for direct tool access

## Steps

### 1. Install

```bash
pip3 install 'markitdown[all]'
```

The `[all]` extra includes OCR, audio transcription, and all format support.

### 2. Test

```bash
markitdown /path/to/document.pdf
markitdown /path/to/spreadsheet.xlsx
```

### 3. Optional: MCP Server

```bash
pip3 install 'markitdown[mcp]'
```

Add to `~/.claude/settings.json` under `mcpServers`:
```json
"markitdown": {
  "command": "python3",
  "args": ["-m", "markitdown.mcp"]
}
```

### 4. Verify

```bash
markitdown --help
echo "Hello World" | markitdown
```

## Usage

When you encounter any document file Kyle provides:
```bash
# PDF (tax returns, investment statements, lab reports)
markitdown "/path/to/document.pdf"

# Word docs (screenplay notes, contracts)
markitdown "/path/to/notes.docx"

# PowerPoint (pitch decks)
markitdown "/path/to/pitch.pptx"

# Excel (financial data)
markitdown "/path/to/data.xlsx"
```

Output is clean Markdown that Claude can read directly.
