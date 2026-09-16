# Lifecycle Report - Quick Start

Automated lifecycle reporting for CZ, ID, and BUR brands with Braze + GA4 data.

## Usage

### Option 1: Full API Mode (~7 min) - Fully Automated

```bash
# Generate report for week ending 1/25/26
python3 scripts/generate_lifecycle_report.py --brand CZ --week-ending 2026-01-25

# Custom date range
python3 scripts/generate_lifecycle_report.py --brand CZ --start 2026-01-19 --end 2026-01-25

# Specify output location
python3 scripts/generate_lifecycle_report.py --brand CZ --week-ending 2026-01-25 --out ~/Downloads/CZ_Report.xlsx
```

**Pros**: Fully automated, no manual downloads  
**Cons**: Takes ~7 minutes due to 855+ individual API calls

### Option 2: CSV Mode (~30 sec) - Faster

1. Download CSVs from Braze dashboard:
   - **Campaigns**: Analytics → Campaign Analytics → Export
   - **Canvas**: Analytics → Canvas Analytics → Export

2. Run report with CSVs:

```bash
python3 scripts/generate_lifecycle_report.py --brand CZ --week-ending 2026-01-25 \
  --braze-csv ~/Downloads/Braze_Campaign_Analytics.csv \
  --canvas-csv ~/Downloads/Braze_Canvas_Analytics.csv
```

**Pros**: Much faster (~30 seconds)  
**Cons**: Requires manual Braze CSV download

## Output

Excel file with 4 sheets:
- **Summary**: Aggregated metrics for Batch & Blast, SMS, Triggers
- **Batch & Blast**: Campaign-level detail for promotional emails
- **SMS**: Campaign-level detail for SMS
- **Triggers**: Canvas step-level detail for triggered journeys (Cart Abandon, Welcome, Post Purchase, etc.)

Default output: `reports/Combined_Braze_GA4_Report_{BRAND}_{MM_DD}_FINAL.xlsx`

## Requirements

- `.env` file with:
  - `BRAZE_API_KEY` or `BRAZE_API_KEY_{BRAND}` (for API mode)
  - `BRAZE_BASE_URL` or `BRAZE_BASE_URL_{BRAND}` (for API mode)
  - Snowflake credentials (always required for GA4 data)

## Troubleshooting

### Empty Triggers Sheet
- **Cause**: Canvas step names don't match GA4 campaign names
- **Solution**: Use CSV mode (Braze CSVs include proper message names)

### Slow Performance
- **Cause**: API mode fetches 855+ campaigns individually
- **Solution**: Use CSV mode for faster runs

### Missing Orders/Revenue
- **Cause**: GA4 data not matching campaign names
- **Fix**: Check campaign naming conventions in GA4

## Examples

```bash
# CZ weekly report (API mode)
python3 scripts/generate_lifecycle_report.py --brand CZ --week-ending 2026-01-25

# ID monthly report (API mode)
python3 scripts/generate_lifecycle_report.py --brand ID --start 2026-01-01 --end 2026-01-31

# BUR with CSV mode (fast)
python3 scripts/generate_lifecycle_report.py --brand BUR --week-ending 2026-01-25 \
  --braze-csv ~/Downloads/Braze_BUR.csv \
  --canvas-csv ~/Downloads/Canvas_BUR.csv
```

## Next Steps

For full automation details, see `docs/automation/LIFECYCLE_REPORTING.md`.
