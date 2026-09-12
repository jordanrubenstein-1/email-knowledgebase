#!/usr/bin/env python3
"""
Import campaigns and flows (triggered journeys) from Klaviyo.

Fetches campaigns/flows, their messages (subjects, HTML, variants), and analytics.
Outputs YAML files matching the existing campaign schema used for Braze imports.

Supported brands (Klaviyo):  TI (The Inside), TE (The Expert)

Usage:
    uv run python scripts/import_klaviyo.py --brand TI
    uv run python scripts/import_klaviyo.py --brand TE --skip-existing
    uv run python scripts/import_klaviyo.py --brand TI --include-flows
    uv run python scripts/import_klaviyo.py --brand TI --flows-only --dry-run
    uv run python scripts/import_klaviyo.py --brand TI --workers 8 --limit 20

Options:
    --brand NAME        Brand code (TI, TE)
    --skip-existing     Skip campaigns/flows that already have YAML files
    --workers N         Parallel API workers (default: 5)
    --dry-run           Print without writing files
    --include-flows     Also import Klaviyo Flows (triggered journeys)
    --flows-only        Only import Flows, skip regular campaigns
    --limit N           Limit number of campaigns/flows (for testing)
    --output DIR        Output directory (default: campaigns/)

Schema notes:
    - YAML schema is identical to Braze campaigns, with two extra fields at the bottom:
        klaviyo_type: campaign | flow
        klaviyo_message_id: {id}
    - braze_type field is preserved (campaign / canvas_step) for schema compatibility
    - Klaviyo "Received Email" metric = both total_sends and total_delivered
      (Klaviyo does not distinguish sent from delivered)
    - TI collision handling: if a Braze YAML exists with the same slug, Klaviyo
      file gets a 'klv-' prefix to preserve both records
"""

from __future__ import annotations

import os
import re
import sys
import argparse
import threading
from datetime import datetime
from pathlib import Path
from concurrent.futures import ThreadPoolExecutor, as_completed

from dotenv import load_dotenv
import yaml

# Load .env from project root
load_dotenv(Path(__file__).parent.parent / ".env")

# ---------------------------------------------------------------------------
# Reuse shared utilities from Braze import pipeline
# ---------------------------------------------------------------------------
sys.path.insert(0, str(Path(__file__).parent))
from import_braze import (
    classify_category,
    infer_brand_from_name,
    infer_campaign_type,
    infer_theme,
    slugify,
    extract_date_from_name,
)
from flatten_canvases import infer_flow_type
from utils.klaviyo_client import KlaviyoClient
from analysis.analyze_html_structure import analyze_html


# ---------------------------------------------------------------------------
# Brand config
# ---------------------------------------------------------------------------

KLAVIYO_BRANDS = {"TI", "TE"}

BRAND_ALIASES = {
    "ti": "TI",
    "the inside": "TI",
    "te": "TE",
    "the expert": "TE",
}


def normalize_brand(brand: str) -> str:
    if not brand:
        print("Error: --brand is required (TI or TE)")
        sys.exit(1)
    return BRAND_ALIASES.get(brand.lower(), brand.upper())


def init_client(brand: str) -> KlaviyoClient:
    brand = normalize_brand(brand)
    if brand not in KLAVIYO_BRANDS:
        print(f"Error: brand '{brand}' is not a Klaviyo brand. Supported: {KLAVIYO_BRANDS}")
        sys.exit(1)
    api_key = os.environ.get(f"KLAVIYO_API_KEY_{brand}")
    if not api_key:
        print(f"Error: KLAVIYO_API_KEY_{brand} not set in .env")
        print(f"Add: KLAVIYO_API_KEY_{brand}=pk_your_private_key")
        print("Get from Klaviyo: Settings > API Keys > Private API Keys")
        sys.exit(1)
    return KlaviyoClient(api_key=api_key, brand=brand)


# ---------------------------------------------------------------------------
# YAML filename helpers
# ---------------------------------------------------------------------------

def build_campaign_id_index(output_dir: Path) -> dict[str, str]:
    """Scan existing YAMLs once and map klaviyo_campaign_id -> filename.

    Used so re-imports of a renamed campaign (rename, "Clone" prefix, apostrophe
    encoding drift, etc.) update the existing file in place instead of creating a
    duplicate under the new name's slug — name-based lookup alone can't catch this
    since the campaign ID, not the name, is the stable identity.
    """
    index: dict[str, str] = {}
    for path in output_dir.glob("*.yaml"):
        try:
            data = yaml.safe_load(path.read_text(encoding="utf-8"))
        except Exception:
            continue
        if not data or data.get("klaviyo_type") != "campaign":
            continue
        cid = data.get("klaviyo_campaign_id")
        if cid:
            index[cid] = path.name
    return index


def make_filename(name: str, output_dir: Path, prefix: str = "") -> str:
    """Generate YAML filename, adding 'klv-' prefix if a Braze file exists with same slug."""
    slug = slugify(name)
    candidate = f"{prefix}{slug}.yaml"
    existing = output_dir / f"{slug}.yaml"
    if existing.exists() and not prefix:
        try:
            data = yaml.safe_load(existing.read_text(encoding="utf-8"))
            if data and not data.get("klaviyo_type"):
                # Existing file is a Braze file — use klv- prefix
                candidate = f"klv-{slug}.yaml"
        except Exception:
            pass
    return candidate


def yaml_exists(name: str, output_dir: Path) -> bool:
    """Check whether a YAML file already exists for this campaign name."""
    slug = slugify(name)
    return (
        (output_dir / f"{slug}.yaml").exists()
        or (output_dir / f"klv-{slug}.yaml").exists()
    )


# ---------------------------------------------------------------------------
# HTML helpers
# ---------------------------------------------------------------------------

def extract_image_urls(html: str) -> list[str]:
    """Extract image URLs from HTML content."""
    if not html:
        return []
    urls = []
    # <img src="...">
    for url in re.findall(r'<img[^>]+src=["\']([^"\']+)["\']', html, re.IGNORECASE):
        if not url.startswith("data:") and "{{" not in url:
            urls.append(url)
    # background-image: url(...)
    for url in re.findall(r'background(?:-image)?:\s*url\(["\']?([^"\')\s]+)["\']?\)', html, re.IGNORECASE):
        if not url.startswith("data:") and "{{" not in url:
            urls.append(url)
    return list(dict.fromkeys(urls))[:10]  # deduplicate, cap at 10


def save_html(html: str, slug: str, html_dir: Path) -> str | None:
    """Save HTML content to campaigns/html/{slug}.html. Returns relative path."""
    if not html:
        return None
    html_dir.mkdir(exist_ok=True)
    filepath = html_dir / f"{slug}.html"
    filepath.write_text(html, encoding="utf-8")
    return f"html/{slug}.html"


def _add_structure(record: dict, html_dir: Path) -> None:
    """Analyze HTML structure and add 'structure' key to record in-place."""
    sends = record.get("sends", [])
    if not sends:
        return
    html_file = sends[0].get("html_file")
    if not html_file:
        return
    html_path = html_dir / Path(html_file).name
    if not html_path.exists():
        return
    structure = analyze_html(html_path)
    if structure:
        record["structure"] = structure


# ---------------------------------------------------------------------------
# Campaign transform
# ---------------------------------------------------------------------------

def transform_campaign(
    campaign: dict,
    messages: list[dict],
    analytics: dict,
    default_brand: str,
    html_dir: Path | None = None,
    dry_run: bool = False,
) -> dict:
    """Convert Klaviyo campaign + messages to our YAML schema.

    analytics: performance_summary dict from get_campaign_analytics_report() (per-campaign).
    """
    attrs = campaign.get("attributes", {})
    campaign_id = campaign.get("id", "")
    name = attrs.get("name") or campaign_id

    brand = infer_brand_from_name(name) or default_brand
    category = classify_category(name)
    theme = infer_theme(name)

    # Dates — send_time is the actual send datetime; created_at is campaign creation
    send_time = attrs.get("send_time") or attrs.get("scheduled_at")
    created = attrs.get("created_at")
    name_date = extract_date_from_name(name)

    dates: dict = {}
    if created:
        dates["created"] = created[:10] if len(created) >= 10 else created
    if send_time:
        dates["first_sent"] = send_time
        dates["last_sent"] = send_time
    elif name_date:
        dates["first_sent"] = name_date
        dates["last_sent"] = name_date

    # Build sends list
    sends = []
    for msg in messages:
        msg_attrs = msg.get("attributes", {})
        msg_id = msg.get("id", "")
        # subject/preheader live inside the 'content' dict; name is 'label'
        content_dict = msg_attrs.get("content") or {}
        html_content = msg.get("_html", "")  # injected by get_campaign_messages()

        send: dict = {
            "id": msg_id,
            "channel": "email",
            "name": msg_attrs.get("label") or "Variant A",
            "subject": content_dict.get("subject") or "",
            "preheader": content_dict.get("preview_text") or "",
        }

        # Save HTML and extract image URLs
        if html_content and html_dir and not dry_run:
            slug = slugify(name)
            html_rel = save_html(html_content, slug, html_dir)
            if html_rel:
                send["html_file"] = html_rel
                send["image_urls"] = extract_image_urls(html_content)

        sends.append(send)

    # Analytics are per-campaign (not per-message) from campaign-values-reports
    perf_summary: dict = {
        "total_sends": analytics.get("total_sends", 0),
        "total_delivered": analytics.get("total_delivered", 0),
        "total_opens": analytics.get("total_opens", 0),
        "total_clicks": analytics.get("total_clicks", 0),
        "unique_opens": analytics.get("unique_opens", 0),
        "unique_clicks": analytics.get("unique_clicks", 0),
        "open_rate": analytics.get("open_rate", 0.0),
        "click_rate": analytics.get("click_rate", 0.0),
        "total_open_rate": analytics.get("total_open_rate", 0.0),
        "total_click_rate": analytics.get("total_click_rate", 0.0),
        "total_unsubscribes": analytics.get("total_unsubscribes", 0),
    }
    if analytics.get("total_bounces"):
        perf_summary["total_bounces"] = analytics["total_bounces"]

    record: dict = {
        "id": f"klaviyo-{campaign_id}",
        "name": name,
        "brand": brand,
        "channel": "email",
        "category": category,
        "type": infer_campaign_type(name, None),
        "braze_type": "campaign",
        "campaign_type": "One-Time Send",
        "dates": dates,
        "sends": sends,
        "performance_summary": perf_summary,
        # Klaviyo-specific fields (always last)
        "klaviyo_type": "campaign",
        "klaviyo_campaign_id": campaign_id,
        "klaviyo_message_id": messages[0].get("id") if messages else None,
    }
    if theme:
        record["theme"] = theme

    return record


# ---------------------------------------------------------------------------
# SMS campaign transform
# ---------------------------------------------------------------------------

def transform_sms_campaign(
    campaign: dict,
    messages: list[dict],
    analytics: dict,
    default_brand: str,
) -> dict:
    """Convert a Klaviyo SMS campaign to YAML schema."""
    attrs = campaign.get("attributes", {})
    campaign_id = campaign.get("id", "")
    name = attrs.get("name") or campaign_id

    brand = infer_brand_from_name(name) or default_brand
    category = classify_category(name)
    theme = infer_theme(name)

    send_time = attrs.get("send_time") or attrs.get("scheduled_at")
    created = attrs.get("created_at")
    name_date = extract_date_from_name(name)

    dates: dict = {}
    if created:
        dates["created"] = created[:10] if len(created) >= 10 else created
    if send_time:
        dates["first_sent"] = send_time
        dates["last_sent"] = send_time
    elif name_date:
        dates["first_sent"] = name_date
        dates["last_sent"] = name_date

    sends = []
    for msg in messages:
        msg_attrs = msg.get("attributes", {})
        msg_id = msg.get("id", "")
        content_dict = msg_attrs.get("content") or {}
        sends.append({
            "id": msg_id,
            "channel": "sms",
            "name": msg_attrs.get("label") or "SMS",
            "body": content_dict.get("body") or "",
        })

    perf_summary: dict = {
        "total_sends":        analytics.get("total_sends", 0),
        "total_delivered":    analytics.get("total_delivered", 0),
        "total_opens":        0,
        "total_clicks":       analytics.get("total_clicks", 0),
        "unique_opens":       0,
        "unique_clicks":      analytics.get("unique_clicks", 0),
        "open_rate":          0.0,
        "click_rate":         analytics.get("click_rate", 0.0),
        "total_open_rate":    0.0,
        "total_click_rate":   analytics.get("total_click_rate", 0.0),
        "total_unsubscribes": analytics.get("total_unsubscribes", 0),
    }

    record: dict = {
        "id":            f"klaviyo-{campaign_id}",
        "name":          name,
        "brand":         brand,
        "channel":       "sms",
        "category":      category,
        "type":          infer_campaign_type(name, None),
        "braze_type":    "campaign",
        "campaign_type": "One-Time Send",
        "dates":         dates,
        "sends":         sends,
        "performance_summary": perf_summary,
        "klaviyo_type":        "campaign",
        "klaviyo_campaign_id": campaign_id,
        "klaviyo_message_id":  messages[0].get("id") if messages else None,
    }
    if theme:
        record["theme"] = theme
    return record


# ---------------------------------------------------------------------------
# Flow (triggered journey) transform
# ---------------------------------------------------------------------------

def transform_flow_message(
    flow: dict,
    action: dict,
    message: dict,
    seq_pos: int,
    analytics: dict,
    default_brand: str,
    html_dir: Path | None = None,
    dry_run: bool = False,
) -> dict:
    """Convert a Klaviyo flow message step to canvas_step YAML schema."""
    flow_id = flow.get("id", "")
    flow_attrs = flow.get("attributes", {})
    flow_name = flow_attrs.get("name") or flow_id

    msg_attrs = message.get("attributes", {})
    msg_id = message.get("id", "")
    # HTML is injected as msg["_html"] by get_flow_action_messages
    html_content = message.get("_html", "")
    # subject/preheader live inside the content dict
    content_dict = msg_attrs.get("content") or {}

    brand = default_brand
    category = classify_category(flow_name) or "other"
    flow_type = infer_flow_type(flow_name)
    theme = infer_theme(flow_name)

    # Step name: prefer message name, fall back to flow + step
    step_name = msg_attrs.get("name") or f"{flow_name} - Step {seq_pos}"

    created = flow_attrs.get("created")
    updated = flow_attrs.get("updated")
    dates: dict = {}
    if created:
        dates["created"] = created[:10] if len(created) >= 10 else created
        # Flows don't have a single send_date; use flow created as first_sent lower bound
        dates["first_sent"] = created[:10] if len(created) >= 10 else created
    if updated and updated != created:
        dates["last_sent"] = updated[:10] if len(updated) >= 10 else updated

    send: dict = {
        "id": msg_id,
        "channel": "email",
        "name": "Message",
        "subject": content_dict.get("subject") or content_dict.get("subject_line") or "",
        "preheader": content_dict.get("preview_text") or "",
    }

    if html_content and html_dir and not dry_run:
        # Use msg_id-based slug to stay within 50-char limit and avoid collisions
        flow_slug = slugify(flow_name)[:30]
        slug = f"klv-flow-{flow_slug}-t{seq_pos:02d}-{msg_id[:8]}"[:50]
        html_rel = save_html(html_content, slug, html_dir)
        if html_rel:
            send["html_file"] = html_rel
            send["image_urls"] = extract_image_urls(html_content)

    record = {
        "id": f"klaviyo-{msg_id}",
        "name": step_name,
        "brand": brand,
        "channel": "email",
        "category": category,
        "type": infer_campaign_type(flow_name, None),
        "braze_type": "canvas_step",
        "campaign_type": "Triggered Journey",
        "canvas_id": flow_id,
        "canvas_name": flow_name,
        "flow_type": flow_type,
        "sequence_position": seq_pos,
        "dates": dates,
        "sends": [send],
        "performance_summary": analytics or {
            "total_sends": 0,
            "total_delivered": 0,
            "total_opens": 0,
            "total_clicks": 0,
            "unique_opens": 0,
            "unique_clicks": 0,
            "open_rate": 0.0,
            "click_rate": 0.0,
            "total_open_rate": 0.0,
            "total_click_rate": 0.0,
            "total_unsubscribes": 0,
        },
        # Klaviyo-specific fields (always last)
        "klaviyo_type": "flow",
        "klaviyo_message_id": msg_id,
    }
    if theme:
        record["theme"] = theme
    return record


# ---------------------------------------------------------------------------
# SMS flow message transform
# ---------------------------------------------------------------------------

def transform_sms_flow_message(
    flow: dict,
    action: dict,
    message: dict,
    seq_pos: int,
    analytics: dict,
    default_brand: str,
) -> dict:
    """Convert a Klaviyo SMS flow action step to canvas_step YAML schema."""
    flow_id = flow.get("id", "")
    flow_attrs = flow.get("attributes", {})
    flow_name = flow_attrs.get("name") or flow_id

    msg_attrs = message.get("attributes", {})
    msg_id = message.get("id", "")
    content_dict = msg_attrs.get("content") or {}

    brand = default_brand
    category = classify_category(flow_name) or "other"
    flow_type = infer_flow_type(flow_name)
    theme = infer_theme(flow_name)

    step_name = msg_attrs.get("name") or f"{flow_name} - SMS Step {seq_pos}"
    created = flow_attrs.get("created")
    dates: dict = {}
    if created:
        dates["created"] = created[:10] if len(created) >= 10 else created

    record = {
        "id":            f"klaviyo-{msg_id}",
        "name":          step_name,
        "brand":         brand,
        "channel":       "sms",
        "category":      category,
        "type":          infer_campaign_type(flow_name, None),
        "braze_type":    "canvas_step",
        "campaign_type": "Triggered Journey",
        "canvas_id":     flow_id,
        "canvas_name":   flow_name,
        "flow_type":     flow_type,
        "sequence_position": seq_pos,
        "dates":         dates,
        "sends":         [{
            "id":      msg_id,
            "channel": "sms",
            "name":    "SMS",
            "body":    content_dict.get("body") or "",
        }],
        "performance_summary": analytics or {
            "total_sends": 0, "total_delivered": 0, "total_opens": 0,
            "total_clicks": 0, "unique_opens": 0, "unique_clicks": 0,
            "open_rate": 0.0, "click_rate": 0.0,
            "total_open_rate": 0.0, "total_click_rate": 0.0,
            "total_unsubscribes": 0,
        },
        "klaviyo_type":       "flow",
        "klaviyo_message_id": msg_id,
    }
    if theme:
        record["theme"] = theme
    return record


# ---------------------------------------------------------------------------
# File write
# ---------------------------------------------------------------------------

def write_record(
    data: dict,
    output_dir: Path,
    dry_run: bool = False,
    id_index: dict[str, str] | None = None,
    id_index_lock: threading.Lock | None = None,
) -> str:
    """Write a campaign/flow record to YAML. Returns filename written.

    When id_index is provided and data has a klaviyo_campaign_id already present
    in the index, reuses that existing filename (overwrite in place) instead of
    computing a fresh name-based slug — prevents duplicate files when a campaign
    was renamed since its last import. See build_campaign_id_index().
    """
    cid = data.get("klaviyo_campaign_id")
    filename = None
    if id_index is not None and cid:
        lock_ctx = id_index_lock if id_index_lock is not None else threading.Lock()
        with lock_ctx:
            filename = id_index.get(cid)
            if filename is None:
                filename = make_filename(data["name"], output_dir)
                id_index[cid] = filename
    else:
        filename = make_filename(data["name"], output_dir)
    filepath = output_dir / filename

    if dry_run:
        print(yaml.dump(data, default_flow_style=False, sort_keys=False)[:600])
        print(f"  → Would write: {filepath}")
        return filename

    with open(filepath, "w", encoding="utf-8") as f:
        yaml.dump(data, f, default_flow_style=False, sort_keys=False, allow_unicode=True)
    return filename


def write_flow_record(data: dict, output_dir: Path, dry_run: bool = False) -> str:
    """Write a flow step record. Uses canvas-step specific filename."""
    seq = data.get("sequence_position", 1)
    klv_id = data.get("klaviyo_message_id", "")[:8]
    flow_slug = slugify(data["canvas_name"])[:30]
    channel_token = "-sms" if data.get("channel") == "sms" else ""
    filename = f"klv-flow-{flow_slug}{channel_token}-t{seq:02d}-{klv_id}.yaml"
    filepath = output_dir / filename

    if dry_run:
        print(yaml.dump(data, default_flow_style=False, sort_keys=False)[:600])
        print(f"  → Would write: {filepath}")
        return filename

    with open(filepath, "w", encoding="utf-8") as f:
        yaml.dump(data, f, default_flow_style=False, sort_keys=False, allow_unicode=True)
    return filename


# ---------------------------------------------------------------------------
# Main
# ---------------------------------------------------------------------------

def main():
    parser = argparse.ArgumentParser(description="Import campaigns and flows from Klaviyo")
    parser.add_argument("--brand", type=str, required=True, help="Brand code (TI, TE)")
    parser.add_argument("--dry-run", action="store_true", help="Print without writing files")
    parser.add_argument("--output", type=str, default="campaigns", help="Output directory")
    parser.add_argument("--limit", type=int, default=None, help="Limit number of campaigns")
    parser.add_argument("--skip-existing", action="store_true", help="Skip campaigns that already have files")
    parser.add_argument("--skip-analytics", action="store_true",
                        help="Skip analytics API calls (write zeros). Use backfill_klaviyo_analytics.py later.")
    parser.add_argument("--workers", type=int, default=5, help="Parallel API workers (default: 5)")
    parser.add_argument("--include-flows", action="store_true", help="Also import Klaviyo Flows (triggered journeys)")
    parser.add_argument("--flows-only", action="store_true", help="Only import Flows, skip regular campaigns")
    parser.add_argument("--include-sms", action="store_true", help="Also import standalone SMS campaigns (SMS flow actions are always included when --include-flows is set)")
    args = parser.parse_args()

    brand = normalize_brand(args.brand)
    client = init_client(brand)

    script_dir = Path(__file__).parent
    output_dir = script_dir.parent / args.output
    output_dir.mkdir(exist_ok=True)
    html_dir = output_dir / "html"

    print_lock = threading.Lock()
    processed: list[dict] = []
    processed_lock = threading.Lock()

    # ID-based index so re-imports of renamed campaigns update the existing file
    # in place instead of creating a duplicate under the new name's slug.
    id_index = build_campaign_id_index(output_dir)
    id_index_lock = threading.Lock()

    # Discover metric IDs once (cached for all workers)
    print(f"[klaviyo:{brand}] Discovering metric IDs...")
    client.discover_metric_ids()

    # ============================================
    # CAMPAIGNS
    # ============================================
    campaigns_skipped = 0
    if not args.flows_only:
        print(f"\n[klaviyo:{brand}] Fetching sent campaigns...")
        campaigns = client.get_campaigns()
        print(f"Found {len(campaigns)} sent campaigns")

        if args.limit:
            campaigns = campaigns[: args.limit]
            print(f"Limited to {args.limit}")

        if args.skip_existing:
            before = len(campaigns)
            campaigns = [c for c in campaigns if not yaml_exists(c.get("attributes", {}).get("name", c["id"]), output_dir)]
            campaigns_skipped = before - len(campaigns)
            if campaigns_skipped:
                print(f"Skipping {campaigns_skipped} existing campaigns")

        if campaigns:
            print(f"Processing {len(campaigns)} campaigns with {args.workers} workers...\n")
            completed_count = [0]
            total_count = len(campaigns)

            def process_campaign(campaign: dict):
                try:
                    campaign_id = campaign["id"]
                    attrs = campaign.get("attributes", {})
                    name = attrs.get("name", campaign_id)

                    messages = client.get_campaign_messages(campaign_id)

                    # Analytics: one call per campaign (skippable to avoid rate limits)
                    if args.skip_analytics:
                        analytics = client._empty_analytics()
                    else:
                        send_date = (attrs.get("send_time") or attrs.get("scheduled_at") or "2024-07-01")[:10]
                        analytics = client.get_campaign_analytics_report(campaign_id, start_date=send_date)

                    data = transform_campaign(
                        campaign, messages, analytics, brand,
                        html_dir=None if args.dry_run else html_dir,
                        dry_run=args.dry_run,
                    )

                    # Save HTML (injected as msg["_html"] by get_campaign_messages)
                    if not args.dry_run:
                        for msg in messages:
                            html_content = msg.get("_html", "")
                            if html_content:
                                slug = slugify(name)
                                for send in data["sends"]:
                                    if send.get("id") == msg["id"] and "html_file" not in send:
                                        html_rel = save_html(html_content, slug, html_dir)
                                        if html_rel:
                                            send["html_file"] = html_rel
                                            send["image_urls"] = extract_image_urls(html_content)

                        _add_structure(data, html_dir)
                        write_record(data, output_dir, id_index=id_index, id_index_lock=id_index_lock)

                    with processed_lock:
                        processed.append(data)
                        completed_count[0] += 1
                        count = completed_count[0]

                    status = "(dry-run)" if args.dry_run else "done"
                    with print_lock:
                        print(f"[{count}/{total_count}] {name[:55]}... {status}")

                    return data

                except Exception as e:
                    with print_lock:
                        print(f"[ERROR] {campaign.get('attributes', {}).get('name', campaign['id'])[:50]}: {e}")
                    return None

            with ThreadPoolExecutor(max_workers=args.workers) as executor:
                futures = {executor.submit(process_campaign, c): c for c in campaigns}
                for future in as_completed(futures):
                    pass

            campaign_count = len([p for p in processed if p.get("klaviyo_type") == "campaign"])
            print(f"\nProcessed {campaign_count} campaigns")

    # ============================================
    # SMS CAMPAIGNS
    # ============================================
    if args.include_sms and not args.flows_only:
        print(f"\n[klaviyo:{brand}] Fetching SMS campaigns...")
        sms_campaigns = client.get_campaigns(channel="sms")
        print(f"Found {len(sms_campaigns)} sent SMS campaigns")

        if args.limit:
            sms_campaigns = sms_campaigns[:args.limit]

        if args.skip_existing:
            before = len(sms_campaigns)
            sms_campaigns = [c for c in sms_campaigns if not yaml_exists(c.get("attributes", {}).get("name", c["id"]), output_dir)]
            skipped = before - len(sms_campaigns)
            if skipped:
                print(f"Skipping {skipped} existing SMS campaigns")

        if sms_campaigns:
            print(f"Processing {len(sms_campaigns)} SMS campaigns with {args.workers} workers...\n")
            sms_completed = [0]
            sms_total = len(sms_campaigns)

            def process_sms_campaign(campaign: dict):
                try:
                    campaign_id = campaign["id"]
                    attrs = campaign.get("attributes", {})
                    name = attrs.get("name", campaign_id)

                    messages = client.get_campaign_messages(campaign_id)

                    if args.skip_analytics:
                        analytics = client._empty_analytics()
                    else:
                        send_date = (attrs.get("send_time") or attrs.get("scheduled_at") or "2024-07-01")[:10]
                        analytics = client.get_campaign_analytics_report(
                            campaign_id, start_date=send_date, channel="sms"
                        )

                    data = transform_sms_campaign(campaign, messages, analytics, brand)

                    if not args.dry_run:
                        write_record(data, output_dir, id_index=id_index, id_index_lock=id_index_lock)
                    else:
                        print(yaml.dump(data, default_flow_style=False, sort_keys=False)[:400])

                    with processed_lock:
                        processed.append(data)
                        sms_completed[0] += 1
                        count = sms_completed[0]

                    status = "(dry-run)" if args.dry_run else "done"
                    with print_lock:
                        print(f"[SMS {count}/{sms_total}] {name[:55]}... {status}")
                    return data

                except Exception as e:
                    with print_lock:
                        print(f"[ERROR SMS] {campaign.get('attributes', {}).get('name', campaign['id'])[:50]}: {e}")
                    return None

            with ThreadPoolExecutor(max_workers=args.workers) as executor:
                futures = {executor.submit(process_sms_campaign, c): c for c in sms_campaigns}
                for future in as_completed(futures):
                    pass

            sms_count = len([p for p in processed if p.get("channel") == "sms" and p.get("klaviyo_type") == "campaign"])
            print(f"\nProcessed {sms_count} SMS campaigns")

    # ============================================
    # FLOWS (Triggered Journeys)
    # ============================================
    flows_skipped = 0
    if args.include_flows or args.flows_only:
        print(f"\n[klaviyo:{brand}] Fetching flows...")
        flows = client.get_flows()
        print(f"Found {len(flows)} flows")

        if args.limit and args.flows_only:
            flows = flows[: args.limit]
            print(f"Limited to {args.limit}")

        if flows:
            print(f"Processing {len(flows)} flows with {args.workers} workers...\n")
            completed_count = [0]
            total_count = len(flows)

            def process_flow(flow: dict):
                try:
                    flow_id = flow["id"]
                    flow_name = flow.get("attributes", {}).get("name", flow_id)
                    records = []

                    actions = client.get_flow_actions(flow_id)
                    email_actions = [a for a in actions if a.get("attributes", {}).get("action_type", "").upper() == "SEND_EMAIL"]
                    # SMS flow steps are captured unconditionally (not gated behind
                    # --include-sms, which only governs standalone SMS *campaign*
                    # import above) — same gap/fix as Braze canvas SMS steps.
                    sms_actions   = [a for a in actions if a.get("attributes", {}).get("action_type", "").upper() == "SEND_SMS"]

                    for seq_pos, action in enumerate(email_actions, start=1):
                        messages = client.get_flow_action_messages(action["id"])

                        for msg in messages:
                            msg_id = msg["id"]

                            analytics = client._empty_analytics()

                            data = transform_flow_message(
                                flow, action, msg, seq_pos, analytics, brand,
                                html_dir=None if args.dry_run else html_dir,
                                dry_run=args.dry_run,
                            )

                            if not args.dry_run:
                                _add_structure(data, html_dir)
                                write_flow_record(data, output_dir)

                            records.append(data)

                    for seq_pos, action in enumerate(sms_actions, start=1):
                        messages = client.get_flow_action_messages(action["id"])

                        for msg in messages:
                            data = transform_sms_flow_message(
                                flow, action, msg, seq_pos, client._empty_analytics(), brand,
                            )
                            if not args.dry_run:
                                write_flow_record(data, output_dir)
                            records.append(data)

                    with processed_lock:
                        processed.extend(records)
                        completed_count[0] += 1
                        count = completed_count[0]

                    status = f"{len(records)} steps" if records else "no steps"
                    with print_lock:
                        print(f"[Flow {count}/{total_count}] {flow_name[:50]}... {status}")

                    return records

                except Exception as e:
                    with print_lock:
                        print(f"[ERROR Flow] {flow.get('attributes', {}).get('name', flow['id'])[:50]}: {e}")
                    return []

            with ThreadPoolExecutor(max_workers=args.workers) as executor:
                futures = {executor.submit(process_flow, f): f for f in flows}
                for future in as_completed(futures):
                    pass

            flow_step_count = len([p for p in processed if p.get("klaviyo_type") == "flow"])
            print(f"\nProcessed {flow_step_count} flow message steps")

    # Summary
    print()
    c_count = len([p for p in processed if p.get("klaviyo_type") == "campaign"])
    f_count = len([p for p in processed if p.get("klaviyo_type") == "flow"])
    print(f"Done! Imported to {output_dir}:")
    if c_count:
        print(f"  - {c_count} campaigns")
    if f_count:
        print(f"  - {f_count} flow steps (triggered journey messages)")
    if campaigns_skipped:
        print(f"  - Skipped {campaigns_skipped} existing campaigns")
    if args.dry_run:
        print("  (dry-run — no files written)")
    else:
        print(f"\nNext: generate screenshots with:")
        print(f"  uv run python scripts/backfill_html_screenshots.py --brand {brand}")


if __name__ == "__main__":
    main()
