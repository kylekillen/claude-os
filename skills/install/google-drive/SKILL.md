---
name: install-google-drive
description: Install Google Drive integration via google_api.py
version: 1.0.0
installs:
  - google-api-drive
requires:
  bins: ["python3"]
  credentials:
    - ~/.config/personal-os/token.json
    - ~/.config/personal-os/credentials.json
---

# Install: Google Drive Integration

## What This Installs

- Google Drive operations via `google_api.py` script
- List, search, download, export, upload, mkdir, move, delete

## Steps

### 1. Set Up OAuth Credentials

Place at:
- `~/.config/personal-os/credentials.json`
- `~/.config/personal-os/token.json`

### 2. Verify

```bash
SCRIPT="~/.claude/scripts/google_api.py"
python3 "$SCRIPT" drive list <your-folder-id>
```

## Script Commands

```bash
SCRIPT="~/.claude/scripts/google_api.py"

python3 "$SCRIPT" drive list <folder_id>
python3 "$SCRIPT" drive search "query"
python3 "$SCRIPT" drive download <file_id> /tmp/filename.pdf
python3 "$SCRIPT" drive export <file_id> /tmp/filename.md    # Google Workspace files
python3 "$SCRIPT" drive upload /tmp/file.md <folder_id>
python3 "$SCRIPT" drive mkdir "folder-name" <parent_folder_id>
python3 "$SCRIPT" drive move <file_id> <new_parent_id>
python3 "$SCRIPT" drive delete <file_id>
```

## Key Folder IDs

Replace `<folder_id>` placeholders with your actual Google Drive folder IDs. To find your folder ID:
1. Open the folder in Google Drive
2. Look at the URL: `https://drive.google.com/drive/folders/YOUR_FOLDER_ID`
3. Copy the ID after `/folders/`

## Rules

1. Never delete files without asking Kyle first
2. Use `export` for Google Workspace files — `download` will fail on these
3. Use `download` for regular files (PDFs, images)
4. After uploading, confirm file ID and location
