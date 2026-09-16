#!/usr/bin/env python3
"""
Backfill HTML body content for existing canvas step YAML files.

For each canvas step YAML that lacks an html_file reference, fetches the
email body from Braze (one canvas/details call per canvas, not per step),
saves the HTML, and patches the YAML with a sends section containing the
html_file pointer.

Usage:
    uv run python scripts/backfill_canvas_html.py
    uv run python scripts/backfill_canvas_html.py --brand CZ
    uv run python scripts/backfill_canvas_html.py --dry-run
"""

import argparse
from collections import defaultdict
from pathlib import Path

import yaml

from import_braze import (
    init_config,
    get_canvas_details,
    slugify,
    normalize_brand,
)


BRANDS = ['HAV', 'CZ', 'BUR', 'STF', 'ID']


def load_canvas_steps_missing_html(campaigns_dir, brand=None):
    """Return canvas step YAMLs that have no html_file in their sends."""
    missing = []
    for f in campaigns_dir.glob('*.yaml'):
        if f.name.startswith('_'):
            continue
        with open(f) as fh:
            data = yaml.safe_load(fh)
        if not data:
            continue
        if data.get('braze_type') != 'canvas_step':
            continue
        if data.get('channel') != 'email':
            continue
        if brand and data.get('brand') != brand:
            continue

        # Check for existing html_file in sends
        has_html = any(
            s.get('html_file')
            for s in (data.get('sends') or [])
        )
        if not has_html:
            missing.append({'file': f, 'data': data})

    return missing


def build_msg_body_map(canvas_details):
    """Return {msg_id: body} for all email messages in a canvas."""
    msg_bodies = {}
    for step in canvas_details.get('steps', []):
        if step.get('type') != 'message':
            continue
        for msg_id, msg_data in step.get('messages', {}).items():
            if msg_data.get('channel') == 'email':
                body = msg_data.get('body', '')
                if body:
                    msg_bodies[msg_id] = body
    return msg_bodies


def patch_yaml(filepath, data, html_filename, html_body):
    """Add/update the sends section in a canvas step YAML with html_file."""
    sends = data.get('sends') or []

    if sends:
        # Update the first email send
        for send in sends:
            if send.get('channel') == 'email' or not send.get('channel'):
                send['html_file'] = f'html/{html_filename}'
                break
    else:
        # Build a minimal sends entry from top-level fields
        sends = [{
            'id': data.get('id', ''),
            'channel': 'email',
            'name': data.get('name', ''),
            'subject': data.get('subject', ''),
            'preheader': data.get('preheader', ''),
            'html_file': f'html/{html_filename}',
        }]

    data['sends'] = sends

    with open(filepath, 'w') as f:
        yaml.dump(data, f, default_flow_style=False, sort_keys=False, allow_unicode=True)


def main():
    parser = argparse.ArgumentParser(description='Backfill HTML for canvas step YAMLs')
    parser.add_argument('--brand', type=str, help='Process only this brand')
    parser.add_argument('--dry-run', action='store_true', help='Print without writing')
    args = parser.parse_args()

    campaigns_dir = Path(__file__).parent.parent / 'campaigns'
    html_dir = campaigns_dir / 'html'
    html_dir.mkdir(exist_ok=True)

    brand_filter = normalize_brand(args.brand) if args.brand else None
    brands_to_process = [brand_filter] if brand_filter else BRANDS

    total_updated = 0
    total_skipped = 0
    total_no_body = 0

    for brand in brands_to_process:
        print(f'\n=== {brand} ===')
        init_config(brand)

        steps = load_canvas_steps_missing_html(campaigns_dir, brand=brand)
        print(f'  {len(steps)} canvas steps missing html_file')

        if not steps:
            continue

        # Group by canvas_id to minimize API calls
        by_canvas = defaultdict(list)
        for step in steps:
            by_canvas[step['data']['canvas_id']].append(step)

        print(f'  {len(by_canvas)} unique canvases to fetch')

        for canvas_id, canvas_steps in by_canvas.items():
            canvas_name = canvas_steps[0]['data'].get('canvas_name', canvas_id[:8])
            print(f'  Fetching: {canvas_name[:50]}...')

            details = get_canvas_details(canvas_id)
            if not details:
                print(f'    [SKIP] No details returned')
                total_skipped += len(canvas_steps)
                continue

            msg_bodies = build_msg_body_map(details)

            for step in canvas_steps:
                data = step['data']
                filepath = step['file']
                msg_id = data.get('id', '')
                seq_pos = data.get('sequence_position', 0)
                msg_id_short = msg_id[:8]
                html_filename = f"canvas-{slugify(canvas_name)}-t{seq_pos}-{msg_id_short}.html"
                html_path = html_dir / html_filename

                body = msg_bodies.get(msg_id)
                if not body:
                    print(f'    [NO BODY] {data.get("name", msg_id[:8])}')
                    total_no_body += 1
                    continue

                if args.dry_run:
                    print(f'    Would save: {html_filename} -> patch {filepath.name}')
                    total_updated += 1
                    continue

                with open(html_path, 'w', encoding='utf-8') as f:
                    f.write(body)

                patch_yaml(filepath, data, html_filename, body)
                print(f'    [OK] {data.get("name", msg_id[:8])} -> {html_filename}')
                total_updated += 1

    print(f'\n{"[DRY RUN] " if args.dry_run else ""}Updated: {total_updated}, No body: {total_no_body}, Skipped: {total_skipped}')


if __name__ == '__main__':
    main()
