---
name: large-file-processing
description: Use this skill when the user asks to "parse PDF", "read tax return", "process large file", "read medical records", "parse lab results", or when handling any PDF over 500KB.
---

# Large File Processing

Safely process large PDFs without crashing the session.

## Critical Rule

Anthropic's native PDF reading handles files up to several MB. Use the Read tool for PDF files directly:

```bash
# Check file size first
ls -lh /path/to/file.pdf
```

If the file is extremely large or the Read tool fails, extract text manually or request that the user provide a summary.

## Workflow

1. Check file size with `ls -lh`
2. Use Claude's native PDF reading via the Read tool
3. Extract key information and summarize findings
4. Report findings to the user in plain English
5. Archive original PDFs if needed (use google-drive skill)

## Rules

1. Anthropic's native PDF reading is the primary method — no external scripts needed
2. Summarize key findings rather than reproducing entire documents
3. If Read tool fails on large files, request text extraction or a summary from the user
