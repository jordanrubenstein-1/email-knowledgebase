#!/usr/bin/env python3
"""
Flatten canvas email and SMS steps into individual campaign records.

Each email/SMS step in a canvas becomes its own campaign record with:
- Standard campaign fields (subject/preheader or body, brand, etc.)
- Canvas metadata (canvas_id, canvas_name, sequence_position, flow_type)
- Per-step analytics (sends, opens/clicks for that specific step and channel)

Usage:
    uv run python scripts/flatten_canvases.py
    uv run python scripts/flatten_canvases.py --brand HAV
    uv run python scripts/flatten_canvases.py --dry-run
"""

import argparse
import re
from pathlib import Path
from datetime import datetime, timedelta, timezone

import yaml

from import_braze import (
    init_config,
    get_canvases,
    get_canvas_details,
    braze_request,
    get_base_url,
    get_api_key,
    slugify,
    normalize_brand,
    classify_category,
)
import requests


def infer_flow_type(canvas_name):
    """Infer flow type from canvas name."""
    name_lower = canvas_name.lower()

    if any(x in name_lower for x in ['cart abandon', 'abandoned cart', 'cart viewed', 'abandon cart']):
        return 'cart_abandonment'
    if any(x in name_lower for x in ['browse abandon', 'abandoned browse', 'product browse', 'abandon browse', 'collection abandon']):
        return 'browse_abandonment'
    if any(x in name_lower for x in ['welcome', 'onboarding', 'profile complete', 'room profile']):
        return 'welcome_series'
    if any(x in name_lower for x in ['post purchase', 'post-purchase', 'order confirmation', 'post order']):
        return 'post_purchase'
    if any(x in name_lower for x in ['winback', 'win-back', 're-engage', 'soft bounce']):
        return 'winback'
    if any(x in name_lower for x in ['swatch']):
        return 'swatch_followup'
    if any(x in name_lower for x in ['back in stock', 'bis resubscribe']):
        return 'back_in_stock'
    if any(x in name_lower for x in ['price drop']):
        return 'price_drop'
    if any(x in name_lower for x in ['nps', 'survey']):
        return 'survey'
    if any(x in name_lower for x in ['trade welcome', 'trade series']):
        return 'trade_welcome'
    if any(x in name_lower for x in ['checkout abandon']):
        return 'checkout_abandonment'
    if any(x in name_lower for x in ['design fee', 'design abandon']):
        return 'design_abandonment'

    return 'other_flow'


def get_canvas_step_analytics(canvas_id, brand, first_entry=None):
    """Fetch canvas step analytics over full lifetime, paginating in 14-day windows.

    Returns a dict of {step_id: {sent, delivered, unique_opens, unique_clicks, ...}}.
    """
    init_config(brand)

    url = f'{get_base_url()}/canvas/data_series'
    headers = {'Authorization': f'Bearer {get_api_key()}'}

    end_date = datetime.now(timezone.utc).replace(tzinfo=None)
    start_date = first_entry if first_entry else (end_date - timedelta(days=365))
    if isinstance(start_date, str):
        start_date = datetime.fromisoformat(start_date.replace('Z', '+00:00')).replace(tzinfo=None)

    step_totals = {}
    current_end = end_date

    while current_end > start_date:
        window_days = min(14, (current_end - start_date).days + 1)
        params = {
            'canvas_id': canvas_id,
            'length': window_days,
            'ending_at': current_end.strftime('%Y-%m-%dT%H:%M:%S+00:00'),
            'include_step_breakdown': 'true',
            'include_variant_breakdown': 'true',
        }
        response = requests.get(url, headers=headers, params=params)
        if response.status_code != 200:
            break

        data = response.json()
        stats_list = data.get('data', {}).get('stats', [])
        for day_data in stats_list:
            for step_id, step_data in day_data.get('step_stats', {}).items():
                if step_id not in step_totals:
                    step_totals[step_id] = {
                        'name': step_data.get('name', ''),
                        # Revenue is reported per step, not per channel — a step with
                        # both an email and sms variant would report the same revenue
                        # for each. Not fixable from this API; don't double-count by
                        # summing revenue across both channel records for one step.
                        'revenue': 0,
                        'email': {
                            'sent': 0, 'delivered': 0,
                            'opens': 0, 'unique_opens': 0,
                            'clicks': 0, 'unique_clicks': 0,
                            'unsubscribes': 0, 'bounces': 0,
                        },
                        'sms': {
                            # SMS has no opens/unique_clicks fields at all (Braze
                            # doesn't track SMS opens) and no unsubscribes/bounces
                            # keys — the real fields are opt_out (unsub-equivalent)
                            # and rejected (bounce-equivalent).
                            'sent': 0, 'delivered': 0,
                            'clicks': 0,
                            'unsubscribes': 0, 'bounces': 0,
                        },
                    }
                for email_stats in step_data.get('messages', {}).get('email', []):
                    bucket = step_totals[step_id]['email']
                    bucket['sent'] += email_stats.get('sent', 0)
                    bucket['delivered'] += email_stats.get('delivered', 0)
                    bucket['opens'] += email_stats.get('opens', 0)
                    bucket['unique_opens'] += email_stats.get('unique_opens', 0)
                    bucket['clicks'] += email_stats.get('clicks', 0)
                    bucket['unique_clicks'] += email_stats.get('unique_clicks', 0)
                    bucket['unsubscribes'] += email_stats.get('unsubscribes', 0)
                    bucket['bounces'] += email_stats.get('bounces', 0)
                for sms_stats in step_data.get('messages', {}).get('sms', []):
                    bucket = step_totals[step_id]['sms']
                    bucket['sent'] += sms_stats.get('sent', 0)
                    bucket['delivered'] += sms_stats.get('delivered', 0)
                    bucket['clicks'] += sms_stats.get('clicks', 0)
                    bucket['unsubscribes'] += sms_stats.get('opt_out', 0)
                    bucket['bounces'] += sms_stats.get('rejected', 0)
                step_totals[step_id]['revenue'] += step_data.get('revenue', 0)

        current_end = current_end - timedelta(days=window_days)

    return step_totals


def extract_sequence_position(step_name):
    """Extract sequence position (T1, T2, etc.) from step name."""
    # Look for patterns like T1, T2, T3 or _T1_, _T2_
    match = re.search(r'[_\s]T(\d+)[_\s]', step_name, re.IGNORECASE)
    if match:
        return int(match.group(1))

    # Look for patterns like Step 1, Step 2
    match = re.search(r'Step\s*(\d+)', step_name, re.IGNORECASE)
    if match:
        return int(match.group(1))

    return None


def flatten_canvas(canvas_id, brand, output_dir, dry_run=False):
    """Flatten a single canvas into individual step records."""
    init_config(brand)

    html_dir = output_dir / 'html'
    html_dir.mkdir(exist_ok=True)

    # Get canvas details
    details = get_canvas_details(canvas_id)
    if not details:
        return []

    canvas_name = details.get('name', '')
    channels = details.get('channels', [])

    # Skip canvases with no channel info at all
    if not channels:
        return []

    # Skip canvases with no recent entries — lifetime numbers won't have changed
    last_entry = details.get('last_entry')
    if last_entry:
        last_entry_dt = datetime.fromisoformat(last_entry.replace('Z', '+00:00'))
        days_since = (datetime.now(timezone.utc) - last_entry_dt).days
        if days_since > 18:
            print(f"  Skipping {canvas_name[:50]} — no entries in {days_since} days")
            return []

    # Get step analytics (paginated across full canvas lifetime)
    first_entry = details.get('first_entry')
    step_totals = get_canvas_step_analytics(canvas_id, brand, first_entry=first_entry)

    # Extract email + sms steps from canvas details
    steps = details.get('steps', [])
    flattened_steps = []
    sequence_num = 0

    for step in steps:
        if step.get('type') != 'message':
            continue

        messages = step.get('messages', {})
        for msg_id, msg_data in messages.items():
            msg_channel = msg_data.get('channel')
            if msg_channel not in ('email', 'sms'):
                continue

            sequence_num += 1
            step_id = step.get('id')
            step_name = step.get('name', '')
            seq_pos = extract_sequence_position(step_name) or sequence_num
            msg_id_short = msg_id[:8]

            # Get analytics for this step, scoped to this message's channel
            step_analytics = step_totals.get(step_id, {}).get(msg_channel, {})
            step_revenue = step_totals.get(step_id, {}).get('revenue', 0)
            total_sends = step_analytics.get('sent', 0)

            record = {
                'id': msg_id,
                'name': step_name,
                'brand': brand,
                'channel': msg_channel,
                'category': classify_category(step_name) or classify_category(canvas_name),
                'braze_type': 'canvas_step',
                'campaign_type': 'Triggered Journey',

                # Canvas metadata
                'canvas_id': canvas_id,
                'canvas_name': canvas_name,
                'flow_type': infer_flow_type(canvas_name),
                'sequence_position': seq_pos,
            }

            if msg_channel == 'email':
                html_body = msg_data.get('body', '')
                html_filename = f"canvas-{slugify(canvas_name)}-t{seq_pos}-{msg_id_short}.html"

                # Save HTML file
                if html_body and not dry_run:
                    html_path = html_dir / html_filename
                    with open(html_path, 'w', encoding='utf-8') as f:
                        f.write(html_body)

                send_record = {
                    'id': msg_id,
                    'channel': 'email',
                    'name': step_name,
                    'subject': msg_data.get('subject', ''),
                    'preheader': msg_data.get('preheader', ''),
                }
                if html_body:
                    send_record['html_file'] = f'html/{html_filename}'

                # Top-level for backward compat + analysis scripts
                record['subject'] = msg_data.get('subject', '')
                record['preheader'] = msg_data.get('preheader', '')
                record['sends'] = [send_record]
                record['filename'] = f"canvas-{slugify(canvas_name)}-t{seq_pos}-{msg_id_short}.yaml"
            else:
                sms_body = msg_data.get('body', '')

                send_record = {
                    'id': msg_id,
                    'channel': 'sms',
                    'name': step_name,
                    'body': sms_body,
                }
                if msg_data.get('media_items'):
                    send_record['media_items'] = msg_data['media_items']

                # Top-level for backward compat + analysis scripts (mirrors
                # how email keeps subject/preheader both top-level and in sends[])
                record['body'] = sms_body
                record['sends'] = [send_record]
                # -sms- token disambiguates from email step files for human
                # scanning/grep — msg_id suffix already guarantees uniqueness
                record['filename'] = f"canvas-{slugify(canvas_name)}-sms-t{seq_pos}-{msg_id_short}.yaml"

            record['dates'] = {
                'first_sent': details.get('first_entry'),
                'last_sent': details.get('last_entry'),
            }
            record['performance_summary'] = {}

            # Add performance if we have sends
            if total_sends > 0:
                if msg_channel == 'email':
                    record['performance_summary'] = {
                        'total_sends': total_sends,
                        'total_delivered': step_analytics.get('delivered', 0),
                        'total_opens': step_analytics.get('unique_opens', 0),
                        'total_clicks': step_analytics.get('unique_clicks', 0),
                        'open_rate': round(step_analytics.get('unique_opens', 0) / total_sends, 4),
                        'click_rate': round(step_analytics.get('unique_clicks', 0) / total_sends, 4),
                    }
                else:
                    # No opens/open_rate for SMS — Braze doesn't track SMS opens,
                    # so omit the keys entirely rather than zero-fill them.
                    record['performance_summary'] = {
                        'total_sends': total_sends,
                        'total_delivered': step_analytics.get('delivered', 0),
                        'total_clicks': step_analytics.get('clicks', 0),
                        'click_rate': round(step_analytics.get('clicks', 0) / total_sends, 4),
                    }
                if step_analytics.get('unsubscribes', 0) > 0:
                    record['performance_summary']['total_unsubscribes'] = step_analytics['unsubscribes']
                if step_analytics.get('bounces', 0) > 0:
                    record['performance_summary']['total_bounces'] = step_analytics['bounces']
                if step_revenue > 0:
                    record['performance_summary']['total_revenue'] = round(step_revenue, 2)

            flattened_steps.append(record)

    # Write individual records
    written = []
    for record in flattened_steps:
        filename = record.pop('filename')
        filepath = output_dir / filename

        if dry_run:
            has_html = bool(record['sends'][0].get('html_file')) if record.get('sends') else False
            print(f"Would write: {filepath}")
            if record['channel'] == 'email':
                print(f"  Subject: {record['subject'][:50]}...")
            else:
                print(f"  Body: {record['body'][:50]}...")
            print(f"  Flow: {record['flow_type']}, Position: T{record['sequence_position']}, Channel: {record['channel']}, HTML: {has_html}")
            if record['performance_summary']:
                perf = record['performance_summary']
                clicks_str = f"Clicks: {perf.get('click_rate', 0)*100:.1f}%"
                if 'open_rate' in perf:
                    print(f"  Sends: {perf.get('total_sends', 0)}, Opens: {perf.get('open_rate', 0)*100:.1f}%, {clicks_str}")
                else:
                    print(f"  Sends: {perf.get('total_sends', 0)}, {clicks_str}")
        else:
            with open(filepath, 'w') as f:
                yaml.dump(record, f, default_flow_style=False, sort_keys=False, allow_unicode=True)
            written.append(record)

    return written


def main():
    parser = argparse.ArgumentParser(description='Flatten canvas steps into campaign records')
    parser.add_argument('--brand', type=str, help='Process only this brand')
    parser.add_argument('--output', type=str, default='campaigns', help='Output directory')
    parser.add_argument('--dry-run', action='store_true', help='Print without writing')
    args = parser.parse_args()

    output_dir = Path(__file__).parent.parent / args.output
    output_dir.mkdir(exist_ok=True)

    brands = [args.brand] if args.brand else ['HAV', 'CZ', 'BUR', 'STF', 'ID']

    total_steps = 0

    for brand in brands:
        brand = normalize_brand(brand)
        print(f"\n=== Processing {brand} canvases ===")

        init_config(brand)
        canvases = get_canvases()

        for canvas in canvases:
            details = get_canvas_details(canvas['id'])
            if not details or not details.get('channels'):
                continue

            print(f"  {canvas['name'][:50]}...")
            steps = flatten_canvas(canvas['id'], brand, output_dir, args.dry_run)
            total_steps += len(steps)

            if steps and not args.dry_run:
                print(f"    -> {len(steps)} steps")

    print(f"\n{'Would create' if args.dry_run else 'Created'} {total_steps} canvas step records")


if __name__ == '__main__':
    main()
