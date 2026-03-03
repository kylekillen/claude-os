---
name: install-fitbit
description: Install Fitbit API sync for health data dashboard
version: 1.0.0
installs:
  - fitbit-api-script
  - health-data-sync
requires:
  bins: ["python3"]
  packages: ["supabase"]
  credentials:
    - ~/.config/personal-os/fitbit_credentials.json
    - ~/.config/personal-os/fitbit_token.json
---

# Install: Fitbit Health Sync

## What This Installs

- `fitbit_api.py` script for OAuth-authenticated Fitbit API access
- JSON data pipeline to `Health/data/fitbit-current.json`
- Supabase sync to `health_vitals` table

## Steps

### 1. Install Dependencies

```bash
pip install supabase
```

### 2. Configure Credentials

Place OAuth credentials at:
- `~/.config/personal-os/fitbit_credentials.json` — client ID/secret
- `~/.config/personal-os/fitbit_token.json` — OAuth refresh token

### 3. Create Sync Script

The script lives at `~/.claude/scripts/fitbit_api.py`.

It provides:
- `get_activity()` — steps, distance, calories, active minutes, resting HR
- `get_sleep()` — duration, efficiency, stages (deep/light/REM)
- `get_heart()` — heart rate zones
- `sync` command — pushes to Supabase `health_vitals`

### 4. Verify

```bash
python3 ~/.claude/scripts/fitbit_api.py sync
```

## Usage

**Sync data and write JSON:**
```bash
python3 ~/.claude/scripts/fitbit_api.py sync > ~/Documents/health/fitbit-current.json
```

**Or manually sync to Supabase:**
```bash
python3 ~/.claude/scripts/fitbit_api.py sync
```

## Key Paths

- Script: `~/.claude/scripts/fitbit_api.py`
- Output: `~/Documents/health/fitbit-current.json`
- Supabase table: `health_vitals`
