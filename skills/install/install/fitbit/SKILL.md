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

The script lives at `system/scripts/fitbit_api.py` in Personal-OS-v2.

It provides:
- `get_activity()` — steps, distance, calories, active minutes, resting HR
- `get_sleep()` — duration, efficiency, stages (deep/light/REM)
- `get_heart()` — heart rate zones
- `sync` command — pushes to Supabase `health_vitals`

### 4. Verify

```bash
cd "Personal-OS-v2/system/scripts" && python3 fitbit_api.py sync
```

## Usage

**Sync data and write JSON:**
```bash
cd "Personal-OS-v2/system/scripts" && python3 -c "
import json, fitbit_api
from datetime import datetime
activity = fitbit_api.get_activity()
sleep = fitbit_api.get_sleep()
heart = fitbit_api.get_heart()
data = {
    'lastUpdated': datetime.now().isoformat(),
    'date': datetime.now().strftime('%Y-%m-%d'),
    'activity': {
        'steps': activity['summary']['steps'],
        'distance_miles': round(activity['summary']['distances'][0]['distance'] * 0.621371, 2),
        'calories_out': activity['summary']['caloriesOut'],
        'active_minutes': activity['summary']['fairlyActiveMinutes'] + activity['summary']['veryActiveMinutes'],
        'resting_heart_rate': activity['summary'].get('restingHeartRate'),
    },
    'sleep': None,
    'heart': heart.get('activities-heart', [{}])[0].get('value', {})
}
if sleep.get('sleep'):
    s = sleep['sleep'][0]
    summary = s.get('levels', {}).get('summary', {})
    data['sleep'] = {
        'duration_hours': round(s['duration'] / 3600000, 2),
        'efficiency': s['efficiency'],
        'deep_minutes': summary.get('deep', {}).get('minutes', 0),
        'rem_minutes': summary.get('rem', {}).get('minutes', 0),
    }
print(json.dumps(data, indent=2))
" > "Personal-OS-v2/Health/data/fitbit-current.json"
```

**Sync to Supabase:**
```bash
cd "Personal-OS-v2/system/scripts" && python3 fitbit_api.py sync
```

## Key Paths

- Script: `system/scripts/fitbit_api.py`
- Output: `Health/data/fitbit-current.json`
- Supabase table: `health_vitals`
