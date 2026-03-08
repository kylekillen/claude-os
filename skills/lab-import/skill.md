---
name: lab-import
description: Use this skill when Kyle mentions "new labs", "lab results came in", "got my labs back", "import labs", or receiving new laboratory test results.
---

# Lab Results Import to Supabase

Import lab results from PDFs into the `health_labs` table in Supabase.

## Key Paths

```
SCRIPTS="/Users/kylekillen/Library/CloudStorage/GoogleDrive-kyle.killen@gmail.com/My Drive/Personal-OS-v2/system/scripts"
LAB_FOLDER="/Users/kylekillen/Library/CloudStorage/GoogleDrive-kyle.killen@gmail.com/My Drive/Personal-OS-v2/Health/lab-reports"
```

## Workflow

### 1. Get the PDF

If Kyle provides a path, use that. Otherwise search email:

```bash
SCRIPT="/Users/kylekillen/Library/CloudStorage/GoogleDrive-kyle.killen@gmail.com/My Drive/Personal-OS-v2/system/scripts/google_api.py"
python3 "$SCRIPT" gmail attachments "lab results has:attachment newer_than:14d"
```

Download attachment if needed:
```bash
python3 "$SCRIPT" gmail download <msg_id> <att_id> /tmp/lab-results.pdf
```

### 2. Check File Size

**CRITICAL:** If PDF > 500KB, use the `large-file-processing` skill first.

### 3. Read and Parse the PDF

Read the PDF using Claude's native PDF reading. Extract ALL lab values into this JSON format:

```json
[
  {
    "test_name": "Creatinine",
    "test_date": "2025-08-04",
    "value": 1.35,
    "unit": "mg/dL",
    "reference_low": 0.6,
    "reference_high": 1.3,
    "flag": "high"
  }
]
```

**Required fields:** test_name, test_date, value
**Optional fields:** unit, reference_low, reference_high, flag, notes, category

If flag is omitted, it will be calculated from reference ranges.

### 4. Confirm with Kyle

Present the extracted values in a table:

```
Date: 2025-08-04 | Source: Quest

| Test              | Value  | Unit    | Range       | Flag   |
|-------------------|--------|---------|-------------|--------|
| Creatinine        | 1.35   | mg/dL   | 0.6-1.3     | HIGH   |
| eGFR              | 62     | mL/min  | 60-130      | normal |
...

Ready to import X results to Supabase. Proceed? (y/n)
```

### 5. Flag Critical Results

**STOP and alert Kyle immediately for:**
- Critical values (way outside range)
- eGFR < 45 (significant kidney concern)
- Creatinine > 2.0 (unless expected)
- Any value flagged "critical" by the lab

### 6. Import to Supabase

Save the JSON to a temp file and run the import:

```bash
# Write extracted labs to temp file
cat > /tmp/labs_to_import.json << 'EOF'
[... the JSON array ...]
EOF

# Import to Supabase
python3 "$SCRIPTS/lab_import.py" /tmp/labs_to_import.json --source "Quest"

# Or dry-run first to preview:
python3 "$SCRIPTS/lab_import.py" /tmp/labs_to_import.json --source "Quest" --dry-run
```

### 7. Archive the PDF

```bash
# Name format: TestType_MonthYear.pdf
cp /tmp/lab-results.pdf "$LAB_FOLDER/CMP_Jan2026.pdf"
```

### 8. View Recent Labs

```bash
python3 "$SCRIPTS/lab_import.py" --list-recent
```

## Supabase Schema Reference

```sql
health_labs (
  id UUID PRIMARY KEY,
  test_date DATE NOT NULL,
  test_name TEXT NOT NULL,
  category TEXT,           -- Lipids, Thyroid, Metabolic, CBC, etc.
  value NUMERIC NOT NULL,
  unit TEXT,
  reference_low NUMERIC,
  reference_high NUMERIC,
  flag TEXT,               -- normal, high, low, critical
  source TEXT,             -- Quest, Labcorp, InsideTracker, etc.
  notes TEXT,
  created_at TIMESTAMPTZ
)
```

**Duplicate handling:** Same test_date + test_name = UPDATE existing record.

## Categories (auto-detected)

- **Metabolic:** sodium, potassium, glucose, creatinine, BUN, eGFR, etc.
- **Lipids:** LDL, HDL, triglycerides, ApoB, Lp(a)
- **Thyroid:** TSH, T3, T4
- **CBC:** WBC, RBC, hemoglobin, platelets
- **Hormones:** testosterone, estradiol, cortisol, DHEA
- **Liver:** AST, ALT, alkaline phosphatase
- **Vitamins:** Vitamin D, B12, folate, iron, ferritin
- **Kidney:** Cystatin C, microalbumin, ACR
- **Inflammation:** CRP, hs-CRP, homocysteine

## Kyle-Specific Context

| Test | Kyle's Typical | Notes |
|------|----------------|-------|
| Creatinine | 1.35-1.60 | Elevated due to muscle mass (Cystatin C confirms kidney is fine) |
| eGFR | 60-75 | Borderline is muscle mass artifact, not kidney disease |
| Testosterone | 400-900 | On TRT - varies with injection timing |

Read more context at: `Personal-OS-v2/Health/KNOWLEDGE.md`

## Common Sources

- **Quest** - Quest Diagnostics
- **Labcorp** - LabCorp
- **InsideTracker** - InsideTracker blood panels
- **Intermountain** - Intermountain Healthcare MyChart
- **Biorestoration** - TRT provider
