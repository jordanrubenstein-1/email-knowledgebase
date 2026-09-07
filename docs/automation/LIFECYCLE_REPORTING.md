# Lifecycle Reporting Automation

Automated generation of lifecycle reports (Batch & Blast, SMS, Triggers, Summary) from Braze and GA4 data, replacing the manual CSV download + ChatGPT script workflow.

## Usage

```bash
# Weekly report (week ending Saturday)
uv run python scripts/generate_lifecycle_report.py --brand CZ --week-ending 2026-01-25
uv run python scripts/generate_lifecycle_report.py --brand ID --week-ending 2026-01-25

# Custom date range
uv run python scripts/generate_lifecycle_report.py --brand CZ --start 2026-01-19 --end 2026-01-25

# Custom output path
uv run python scripts/generate_lifecycle_report.py --brand CZ --week-ending 2026-01-25 --out reports/cz_week_01_25.xlsx
```

## Requirements

- **.env**:
  - `BRAZE_API_KEY` or `BRAZE_API_KEY_{BRAND}` (e.g. BRAZE_API_KEY_CZ)
  - `BRAZE_BASE_URL` or `BRAZE_BASE_URL_{BRAND}`
  - Snowflake credentials: `SNOWFLAKE_ACCOUNT`, `SNOWFLAKE_USER`, `SNOWFLAKE_DATABASE`, `SNOWFLAKE_SCHEMA`, etc.

- **Brands**: CZ, ID, BUR (GA4 schemas configured in `import_ga4_metrics_snowflake.py`)

## Output

Excel file with sheets:

- **Summary** — Rollups: Batch & Blast, SMS, Triggers, Grand Total
- **Batch & Blast** — Email campaigns with Long Tail / main B&B subtotals
- **SMS** — SMS campaigns
- **Triggers** — Canvas steps (Cart Abandon, Browse Abandon, etc.)

Default path: `reports/Combined_Braze_GA4_Report_{brand}_{MM_DD}_FINAL.xlsx`

## Components

| Script | Role |
|--------|------|
| `generate_lifecycle_report.py` | Entry point; parses dates, orchestrates fetch + build |
| `braze_api_client.py` | Fetches Braze campaign/canvas analytics by date range |
| `combine_braze_ga4.py` | Merges GA4 + Braze, classifies B&B/SMS/Triggers, outputs Excel |
| `import_ga4_metrics_snowflake.py` | `query_ga4_for_lifecycle_report()` — GA4 data from Snowflake |

## Scheduling

For weekly automation (e.g. Mondays for prior week):

```bash
# Example cron (run Mondays 8am for week ending prior Saturday)
0 8 * * 1 cd /path/to/email-knowledgebase && uv run python scripts/generate_lifecycle_report.py --brand CZ --week-ending $(date -v-2d +\%Y-\%m-\%d)
```

## Troubleshooting

- **No Braze data**: Check `BRAZE_API_KEY` and `BRAZE_BASE_URL`; ensure brand filter matches campaign names (e.g. CZ campaigns contain "CZ").
- **No GA4 data**: Verify Snowflake credentials and schema for brand (LANDING_CITIZENRY_GA4, LANDING_INTERIORDEFINE_GA4, etc.).
- **Merge mismatches**: GA4 `Session campaign` must match Braze campaign/canvas step names. Normalize casing if needed.
- **TRADE excluded**: Per reporting instructions, campaigns with "TRADE" in name are excluded.

## LY (Last Year) Support

Not yet implemented. To add:

1. Run same logic for `(start - 1 year, end - 1 year)` when `--include-ly`
2. Append LY rows to Summary sheet per existing spreadsheet layout
