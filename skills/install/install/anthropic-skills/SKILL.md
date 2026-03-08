---
name: install-anthropic-skills
description: Install official Anthropic production skills (PDF, DOCX, PPTX, XLSX, etc.)
version: 1.0.0
installs:
  - anthropic-pdf
  - anthropic-docx
  - anthropic-pptx
  - anthropic-xlsx
  - anthropic-webapp-testing
  - anthropic-skill-creator
  - anthropic-mcp-builder
requires:
  bins: ["npx"]
---

# Install: Anthropic Official Skills

## What This Installs

17 official Anthropic skills via `openskills`:

| Skill | What It Does |
|-------|-------------|
| `pdf` | Create, extract, merge, split PDFs; fill forms |
| `docx` | Create/edit Word documents with tracked changes |
| `pptx` | Create/edit PowerPoint presentations |
| `xlsx` | Create/edit Excel spreadsheets with formulas |
| `webapp-testing` | Local web app testing via Playwright |
| `skill-creator` | Interactive builder for new custom skills |
| `mcp-builder` | Guidance for creating MCP servers |
| `canvas-design` | Visual art design in PNG/PDF |
| `frontend-design` | React + Tailwind design patterns |
| `web-artifacts-builder` | Complex HTML artifacts |
| `doc-coauthoring` | Collaborative document authoring |
| `algorithmic-art` | Generative art with p5.js |
| `slack-gif-creator` | Animated GIF generation |
| `theme-factory` | Design theme creation |
| `brand-guidelines` | Anthropic brand application |
| `internal-comms` | Status reports, newsletters |

## Steps

### 1. Install

```bash
npx openskills install anthropics/skills --global --yes
```

### 2. Verify

Check skills are in `~/.claude/skills/`:
```bash
ls ~/.claude/skills/pdf ~/.claude/skills/docx ~/.claude/skills/xlsx
```

## Usage

These skills auto-activate based on context:
- Kyle provides a PDF → use `pdf` skill to extract/process
- Kyle needs a pitch deck → use `pptx` skill to create PowerPoint
- Kyle needs financial analysis → use `xlsx` skill for spreadsheets
- Kyle needs a Word document → use `docx` skill
