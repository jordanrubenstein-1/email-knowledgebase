# Email Knowledgebase

A structured repository of email marketing campaigns, templates, and creative assets. Designed to be queried by AI assistants for campaign planning, creative suggestions, and performance analysis.

## Structure

```
├── schema.yaml          # Data structure definitions
├── campaigns/           # Campaign files (one per promotion)
├── templates/           # Reusable email template definitions
├── creative/            # Subject lines, preheaders by theme
└── playbooks/           # Reusable campaign patterns
```

## Common Queries

### Planning a new campaign
1. Check `playbooks/` for relevant patterns (e.g., sale-promotion.yaml)
2. Search `campaigns/` for similar past campaigns by type/theme
3. Pull creative from `creative/subject-lines.yaml` and `creative/preheaders.yaml`
4. Reference `templates/` for image requirements

### Analyzing past performance
1. Read the specific campaign file in `campaigns/`
2. Review `sends` array for channel breakdown
3. Check `metrics` for each send
4. Read `performance_summary.learnings` for insights

### Finding creative inspiration
1. Browse `creative/subject-lines.yaml` by category
2. Filter by `performance: high` for proven winners
3. Check `campaigns` field to see where they were used

## Importing Data

### Setup
```bash
# Install uv if you haven't: https://docs.astral.sh/uv/
cp .env.example .env
# Edit .env with your API keys
```

### Import from Braze
```bash
uv run python scripts/import_braze.py --days 90 --dry-run  # Preview
uv run python scripts/import_braze.py --days 90            # Import
```

### Import from Asana
```bash
uv run python scripts/import_asana.py --list-projects                 # See projects
uv run python scripts/import_asana.py --project "Email Calendar 2024" # Import
```

### Merge Sources
```bash
uv run python scripts/merge_sources.py --dry-run  # Preview matches
uv run python scripts/merge_sources.py            # Apply
```

### Import GA4 Metrics
```bash
# First, check if you have GA4 access (see GA4_ACCESS_CHECK.md)
uv run python scripts/test_ga4_access.py --brand HAV

# Import GA4 conversion data (sessions, purchases, revenue) for campaigns
uv run python scripts/import_ga4_metrics.py --brand HAV
uv run python scripts/import_ga4_metrics.py --all --attribution-days 14
uv run python scripts/import_ga4_metrics.py --brand CZ --dry-run  # Preview
```

## Adding New Data

### New Campaign
Create `campaigns/{year}-{name-slug}.yaml` following the schema. Include:
- All sends with dates and channels
- Subject lines and preheaders for emails
- Metrics once available
- Learnings in performance_summary

### New Template
Create `templates/{id}.yaml` with structure and image slots.

### New Creative
Add entries to `creative/subject-lines.yaml` or `creative/preheaders.yaml` under the appropriate category.

## Schema Reference

See `schema.yaml` for complete field definitions and types.
