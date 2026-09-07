"""
Backfill TE campaign analytics from a Klaviyo CSV export.

Three operations:
  1. Update performance_summary for existing YAMLs that have total_sends: 0
  2. Backfill attributed_revenue + attributed_purchases for all matched YAMLs
  3. Create minimal YAML stubs for campaigns in the CSV but missing from the knowledgebase

Usage:
    uv run python scripts/backfill_te_analytics_from_csv.py --csv path/to/klaviyo_campaigns.csv
    uv run python scripts/backfill_te_analytics_from_csv.py --csv path/to/klaviyo_campaigns.csv --dry-run
    uv run python scripts/backfill_te_analytics_from_csv.py --csv path/to/klaviyo_campaigns.csv --revenue-only
"""

import argparse
import csv
import re
import sys
import uuid
from datetime import datetime, timezone
from pathlib import Path

import yaml

CAMPAIGNS_DIR = Path(__file__).parent.parent / "campaigns"


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def slugify(name: str) -> str:
    slug = re.sub(r"[^\w\s-]", "", name.lower())
    slug = re.sub(r"[-\s]+", "-", slug).strip("-")
    return slug[:50]


def parse_rate(value: str) -> float:
    """Parse '25.39%' or '0.2539' → 0.2539 (always a 0–1 float)."""
    v = value.strip().rstrip("%")
    try:
        f = float(v)
        return f / 100 if f > 1 else f
    except ValueError:
        return 0.0


def parse_int(value: str) -> int:
    try:
        return int(float(value.strip()))
    except (ValueError, AttributeError):
        return 0


def parse_send_time(value: str) -> str | None:
    """Parse '2021-03-05 09:01:31' → ISO8601 UTC string."""
    for fmt in ("%Y-%m-%d %H:%M:%S", "%Y-%m-%d %H:%M", "%Y-%m-%d"):
        try:
            dt = datetime.strptime(value.strip(), fmt).replace(tzinfo=timezone.utc)
            return dt.isoformat()
        except ValueError:
            continue
    return None


def load_csv(csv_path: Path) -> dict[str, dict]:
    """Load CSV keyed by Campaign ID."""
    campaigns = {}
    with open(csv_path, newline="", encoding="utf-8-sig") as f:
        for row in csv.DictReader(f):
            cid = row["Campaign ID"].strip()
            if cid:
                campaigns[cid] = row
    return campaigns


def load_yaml(path: Path) -> dict | None:
    try:
        data = yaml.safe_load(path.read_text(encoding="utf-8"))
        return data if isinstance(data, dict) else None
    except Exception:
        return None


def dump_yaml(data: dict, path: Path, dry_run: bool) -> None:
    content = yaml.dump(data, default_flow_style=False, sort_keys=False, allow_unicode=True)
    if dry_run:
        print(f"  [dry-run] would write {path.name}")
    else:
        path.write_text(content, encoding="utf-8")


def parse_float(value: str) -> float:
    try:
        return float(str(value).strip())
    except (ValueError, AttributeError):
        return 0.0


def performance_from_row(row: dict) -> dict:
    total_sends = parse_int(row.get("Total Recipients", "0"))
    total_delivered = parse_int(row.get("Successful Deliveries", "0"))
    total_opens = parse_int(row.get("Unique Opens", "0"))
    total_clicks = parse_int(row.get("Unique Clicks", "0"))
    total_unsubscribes = parse_int(row.get("Unsubscribes", "0"))
    open_rate = round(total_opens / total_sends, 4) if total_sends else 0.0
    click_rate = round(total_clicks / total_sends, 4) if total_sends else 0.0
    attributed_revenue = round(parse_float(row.get("Showroom OR Consultations Purchase Value", "0")), 2)
    attributed_purchases = parse_int(row.get("Unique Showroom OR Consultations Purchase", "0"))
    return {
        "total_sends": total_sends,
        "total_delivered": total_delivered,
        "total_opens": total_opens,
        "total_clicks": total_clicks,
        "open_rate": open_rate,
        "click_rate": click_rate,
        "total_unsubscribes": total_unsubscribes,
        "attributed_revenue": attributed_revenue,
        "attributed_purchases": attributed_purchases,
    }


def make_stub(row: dict, campaign_id: str) -> dict:
    """Create a minimal YAML record from a CSV row (no HTML available)."""
    name = row.get("Campaign Name", "").strip()
    send_time_str = row.get("Send Time", "").strip()
    sent_iso = parse_send_time(send_time_str)
    date_created = sent_iso[:10] if sent_iso else None

    return {
        "id": f"klaviyo-{campaign_id}",
        "name": name,
        "brand": "TE",
        "channel": "email",
        "category": "other",
        "type": "announcement",
        "braze_type": "campaign",
        "campaign_type": "One-Time Send",
        "dates": {
            "created": date_created,
            "first_sent": sent_iso,
            "last_sent": sent_iso,
        },
        "sends": [
            {
                "id": str(uuid.uuid4()),
                "channel": "email",
                "name": name,
                "subject": row.get("Subject", "").strip() or None,
                "preheader": None,
                "html_file": None,
                "screenshot": None,
                "image_urls": [],
            }
        ],
        "performance_summary": performance_from_row(row),
        "klaviyo_type": "campaign",
        "klaviyo_campaign_id": campaign_id,
        "klaviyo_message_id": None,
    }


# ---------------------------------------------------------------------------
# Main
# ---------------------------------------------------------------------------

def main():
    parser = argparse.ArgumentParser(description="Backfill TE analytics from Klaviyo CSV export")
    parser.add_argument("--csv", required=True, help="Path to Klaviyo CSV export")
    parser.add_argument("--dry-run", action="store_true", help="Preview changes without writing")
    parser.add_argument("--revenue-only", action="store_true", help="Only backfill revenue fields, skip send/open/click updates")
    args = parser.parse_args()

    csv_path = Path(args.csv).expanduser()
    if not csv_path.exists():
        print(f"ERROR: CSV not found: {csv_path}", file=sys.stderr)
        sys.exit(1)

    print(f"Loading CSV: {csv_path}")
    csv_data = load_csv(csv_path)
    print(f"  {len(csv_data)} campaigns in CSV")

    # Build index of existing TE YAMLs keyed by klaviyo_campaign_id
    print("Indexing existing TE campaign YAMLs...")
    yaml_index: dict[str, Path] = {}
    for yaml_path in CAMPAIGNS_DIR.glob("*.yaml"):
        data = load_yaml(yaml_path)
        if data and data.get("brand") == "TE" and data.get("klaviyo_campaign_id"):
            yaml_index[data["klaviyo_campaign_id"]] = yaml_path
    print(f"  {len(yaml_index)} existing TE campaigns with klaviyo_campaign_id")

    updated = 0
    revenue_backfilled = 0
    skipped_no_change = 0
    created = 0
    errors = 0

    for campaign_id, row in csv_data.items():
        perf = performance_from_row(row)

        if campaign_id in yaml_index:
            # --- Update existing YAML ---
            yaml_path = yaml_index[campaign_id]
            data = load_yaml(yaml_path)
            if not data:
                print(f"  WARN: could not parse {yaml_path.name}")
                errors += 1
                continue

            existing_summary = data.get("performance_summary", {})
            existing_sends = existing_summary.get("total_sends", 0)
            existing_revenue = existing_summary.get("attributed_revenue", None)

            changed = False

            if not args.revenue_only and existing_sends == 0:
                # Full analytics update
                data["performance_summary"] = perf
                changed = True
                updated += 1
                if args.dry_run:
                    print(f"  UPDATE {yaml_path.name} → {perf['total_sends']:,} sends, {perf['open_rate']:.1%} OR")
            elif existing_revenue is None:
                # Revenue backfill only — preserve existing send/open/click data
                data["performance_summary"]["attributed_revenue"] = perf["attributed_revenue"]
                data["performance_summary"]["attributed_purchases"] = perf["attributed_purchases"]
                changed = True
                revenue_backfilled += 1
                if args.dry_run:
                    print(f"  REVENUE {yaml_path.name} → ${perf['attributed_revenue']:,.2f} ({perf['attributed_purchases']} purchases)")
            else:
                skipped_no_change += 1
                continue

            if changed:
                dump_yaml(data, yaml_path, args.dry_run)

        else:
            # --- Create new stub YAML ---
            name = row.get("Campaign Name", "").strip()
            if not name:
                continue

            slug = slugify(name)
            candidate = CAMPAIGNS_DIR / f"{slug}.yaml"
            # Avoid collision with existing Braze file
            if candidate.exists():
                existing = load_yaml(candidate)
                if existing and not existing.get("klaviyo_type"):
                    candidate = CAMPAIGNS_DIR / f"klv-{slug}.yaml"

            stub = make_stub(row, campaign_id)
            dump_yaml(stub, candidate, args.dry_run)
            created += 1
            if args.dry_run:
                print(f"  CREATE {candidate.name} — {name} ({perf['total_sends']:,} sends)")

    print()
    print("=" * 50)
    print(f"Updated (full analytics):       {updated}")
    print(f"Revenue backfilled:             {revenue_backfilled}")
    print(f"Skipped (no change needed):     {skipped_no_change}")
    print(f"Created (new stubs):            {created}")
    if errors:
        print(f"Errors:                         {errors}")
    if args.dry_run:
        print("\n[dry-run] No files were written.")


if __name__ == "__main__":
    main()
