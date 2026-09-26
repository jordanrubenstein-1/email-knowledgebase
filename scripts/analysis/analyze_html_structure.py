#!/usr/bin/env python3
"""
Analyze HTML structure of email campaigns and update campaign YAML files.

Extracts:
- image_count: Total images
- link_count: Total clickable links
- has_gif: Whether email contains animated GIF
- hero_width: Width of first/hero image
- layout_type: Inferred layout (hero_only, product_grid, text_only, editorial)
"""

import re
import yaml
from pathlib import Path
from concurrent.futures import ThreadPoolExecutor
import argparse


def analyze_html(html_path: Path) -> dict:
    """Extract structural features from email HTML."""
    try:
        html = html_path.read_text(encoding='utf-8', errors='ignore')
    except Exception as e:
        print(f"Error reading {html_path}: {e}")
        return {}

    # Count images
    images = re.findall(r'<img[^>]+>', html, re.I)
    image_count = len(images)

    # Check for GIFs
    has_gif = bool(re.search(r'\.gif["\?\s>]', html, re.I))

    # Get hero image width (first image with width attr)
    hero_width = None
    width_match = re.search(r'<img[^>]+width=["\']?(\d+)', html, re.I)
    if width_match:
        hero_width = int(width_match.group(1))

    # Count links
    links = re.findall(r'<a\s+[^>]*href=["\'][^"\']+["\']', html, re.I)
    link_count = len(links)

    # Infer layout type
    if image_count == 0 and link_count > 0:
        layout_type = "text_only"
    elif image_count <= 2 and link_count < 8:
        layout_type = "hero_only"
    elif image_count >= 5:
        layout_type = "product_grid"
    elif image_count <= 4:
        layout_type = "editorial"
    else:
        layout_type = "mixed"

    return {
        'image_count': image_count,
        'link_count': link_count,
        'has_gif': has_gif,
        'hero_width': hero_width,
        'layout_type': layout_type,
    }


def update_campaign_yaml(campaign_path: Path, html_dir: Path) -> bool:
    """Update a campaign YAML file with structure data."""
    try:
        with open(campaign_path, 'r') as f:
            data = yaml.safe_load(f)

        if not data:
            return False

        # Find the HTML file reference
        sends = data.get('sends', [])
        if not sends:
            return False

        html_file = sends[0].get('html_file')
        if not html_file:
            return False

        # Construct full HTML path
        html_path = html_dir / Path(html_file).name
        if not html_path.exists():
            # Try alternative path construction
            html_path = Path('campaigns') / html_file
            if not html_path.exists():
                return False

        # Analyze HTML
        structure = analyze_html(html_path)
        if not structure:
            return False

        # Update YAML data
        data['structure'] = structure

        # Write back
        with open(campaign_path, 'w') as f:
            yaml.dump(data, f, default_flow_style=False, allow_unicode=True, sort_keys=False)

        return True

    except Exception as e:
        print(f"Error updating {campaign_path}: {e}")
        return False


def main():
    parser = argparse.ArgumentParser(description='Analyze HTML structure of email campaigns')
    parser.add_argument('--campaigns-dir', default='campaigns', help='Path to campaigns directory')
    parser.add_argument('--html-dir', default='campaigns/html', help='Path to HTML files directory')
    parser.add_argument('--workers', type=int, default=10, help='Number of parallel workers')
    parser.add_argument('--dry-run', action='store_true', help='Print analysis without updating files')
    args = parser.parse_args()

    campaigns_dir = Path(args.campaigns_dir)
    html_dir = Path(args.html_dir)

    # Find all campaign YAML files
    campaign_files = [f for f in campaigns_dir.glob('*.yaml') if not f.name.startswith('_')]
    print(f"Found {len(campaign_files)} campaign files")

    if args.dry_run:
        # Just analyze a few samples
        for f in campaign_files[:5]:
            with open(f) as file:
                data = yaml.safe_load(file)
            if data and data.get('sends'):
                html_file = data['sends'][0].get('html_file')
                if html_file:
                    html_path = html_dir / Path(html_file).name
                    if html_path.exists():
                        structure = analyze_html(html_path)
                        print(f"\n{f.name}:")
                        for k, v in structure.items():
                            print(f"  {k}: {v}")
        return

    # Update all campaigns
    updated = 0
    skipped = 0

    def process_campaign(campaign_path):
        if update_campaign_yaml(campaign_path, html_dir):
            return True
        return False

    with ThreadPoolExecutor(max_workers=args.workers) as executor:
        results = list(executor.map(process_campaign, campaign_files))

    updated = sum(results)
    skipped = len(results) - updated

    print(f"\nCompleted: {updated} updated, {skipped} skipped")


if __name__ == '__main__':
    main()
