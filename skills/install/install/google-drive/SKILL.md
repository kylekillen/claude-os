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
SCRIPT="Personal-OS-v2/system/scripts/google_api.py"
python3 "$SCRIPT" drive list 1v6jNAXU0svaiCLhUjXOO2LC-jarVIhrK
```

## Script Commands

```bash
SCRIPT="Personal-OS-v2/system/scripts/google_api.py"

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

| Folder | ID |
|--------|-----|
| Personal-OS (root) | `1v6jNAXU0svaiCLhUjXOO2LC-jarVIhrK` |
| Financial | `1I0cJK1Pw6jh5NSa1lfwQ9Fo_ZWgbeQfm` |
| Health | `1osDVyk3jLFShJNLOEV6jQQ5Dlc9jA99U` |
| sessions | `16WUTvwYmNpvWrXAmoQ231GBa961W3bdF` |
| capabilities | `1dm_Nz9yvALdbdaZpp9f-opAQnqXVwKvM` |
| system | `187jRcf85mKJliqnW0rP2P5rD8ftGQ5B9` |

## Rules

1. Never delete files without asking Kyle first
2. Use `export` for Google Workspace files — `download` will fail on these
3. Use `download` for regular files (PDFs, images)
4. After uploading, confirm file ID and location
