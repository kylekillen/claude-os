---
name: large-file-processing
description: Use this skill when the user asks to "parse PDF", "read tax return", "process large file", "read medical records", "parse lab results", or when handling any PDF over 500KB.
---

# Large File Processing

Safely process large PDFs without crashing the session.

## Critical Rule

NEVER read files over 500KB directly. Always check size first:

```bash
ls -lh /path/to/file.pdf
```

If over 500KB, use the chunking scripts below.

## Processing Scripts

```bash
# Financial PDFs (tax returns, statements, K-1s)
python3 /Users/kylekillen/Library/CloudStorage/GoogleDrive-kyle.killen@gmail.com/My Drive/Personal-OS-v2/system/scripts/parse_tax_return.py /path/to/file.pdf

# Medical PDFs (lab reports, medical records)
python3 /Users/kylekillen/Library/CloudStorage/GoogleDrive-kyle.killen@gmail.com/My Drive/Personal-OS-v2/system/scripts/parse_health_pdf.py /path/to/file.pdf
```

These scripts:
1. Chunk the PDF into manageable pieces
2. Process each chunk via Haiku
3. Return a structured summary

## Workflow

1. Check file size with `ls -lh`
2. If >500KB, use appropriate chunking script
3. Review the output summary
4. Archive the original PDF in Drive (use google-drive skill)
5. Report findings to Kyle in plain English

## Rules

1. Output is a summary, not the full document
2. Always archive original PDFs after processing
3. If the script fails, report the error — don't try to read the file directly
