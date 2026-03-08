---
name: workout-log
description: Use this skill when Kyle mentions "log workout", "tonal workout", "finished my workout", "workout screenshot", or wants to record exercise data.
---

# Workout Logging

## Workflow

### 1. Get the Screenshot

Check Personal OS v2 root folder for workout photos:
```bash
ls "/Users/kylekillen/Library/CloudStorage/GoogleDrive-kyle.killen@gmail.com/My Drive/Personal-OS-v2/" | grep -iE "(screenshot|PXL|\.(jpg|jpeg|png|heic)$)"
```

If not found, ask Kyle where it is.

**Note:** macOS screenshots and phone photos may have unusual names or no extension.

### 2. Parse the Data

Read the image and extract:
- **Date** (from screenshot header or filename)
- **Program** (e.g., "Ackeem Emmons · Upper · Advanced · Workout 7")
- **Duration** (MM:SS)
- **Volume** (lbs) - total weight lifted
- **Time Under Tension** (MM:SS)
- **Movement Target** (%)
- **Calories**
- **Movements count** (from tab label)

### 3. Save to Supabase

```python
from supabase import create_client
from pathlib import Path
import json

creds = json.loads((Path.home() / ".config/personal-os/credentials.json").read_text())
sb = creds["supabase"]
client = create_client(sb["url"], sb["service_role_key"])

workout = {
    "date": "YYYY-MM-DD",
    "workout_type": "Tonal",
    "program": "Program name from screenshot",
    "duration_minutes": 30.73,  # Convert MM:SS to decimal
    "total_volume_lbs": 13219,
    "time_under_tension": "11:43",  # Keep as string
    "calories": 153,
    "movement_target_pct": 100,
    "movements": 8,
    "source": "tonal"
}

result = client.table("health_workouts").insert(workout).execute()
print(f"Workout logged: {result.data[0]['id']}")
```

### 4. Delete the Screenshot

Remove the photo to keep Personal OS clean:
```bash
rm "/Users/kylekillen/Library/CloudStorage/GoogleDrive-kyle.killen@gmail.com/My Drive/Personal-OS-v2/[filename]"
```

### 5. Summarize

Report:
- Date logged
- Program name
- Volume (lbs)
- Duration
- Weekly context if available (query recent workouts)

## Check Recent Workouts

```python
from supabase import create_client
from pathlib import Path
import json

creds = json.loads((Path.home() / ".config/personal-os/credentials.json").read_text())
sb = creds["supabase"]
client = create_client(sb["url"], sb["service_role_key"])

result = client.table("health_workouts").select("*").order("date", desc=True).limit(7).execute()
for w in result.data:
    print(f"{w['date']}: {w['total_volume_lbs']} lbs - {w['program']}")
```

## Supabase Schema

Table: `health_workouts`

| Column | Type | Notes |
|--------|------|-------|
| id | UUID | Auto-generated |
| date | DATE | Workout date |
| workout_type | TEXT | "Tonal", "Gym", etc. |
| program | TEXT | Full program name |
| duration_minutes | NUMERIC | Decimal minutes |
| total_volume_lbs | NUMERIC | Total weight lifted |
| time_under_tension | TEXT | MM:SS format |
| calories | INTEGER | Calories burned |
| movement_target_pct | INTEGER | Tonal movement target |
| movements | INTEGER | Number of movements |
| notes | TEXT | Optional notes |
| source | TEXT | Default "tonal" |
| created_at | TIMESTAMPTZ | Auto-generated |
