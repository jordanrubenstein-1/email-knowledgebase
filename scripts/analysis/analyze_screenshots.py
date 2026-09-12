#!/usr/bin/env python3
"""
Analyze email screenshots using Claude vision API.

Extracts detailed creative attributes:
- layout: hero_only, hero_products, hero_categories, product_grid, editorial, text_only
- content_type: sale_announcement, sale_reminder, product_launch, product_showcase, content, event
- hero_style: lifestyle_photo, product_photo, illustration, text_overlay, animated
- hero_description: natural language description of hero image content
- cta_visibility: prominent, subtle, inline_links, none_visible
- offer_visibility: hero_overlay, header_banner, above_fold, below_fold, none
- offer_text: the actual offer text if visible
- product_categories: list of product types shown
- tone: aspirational, promotional, personal, informational
- color_palette: dominant colors
"""

import anthropic
import base64
import yaml
import json
import os
import argparse
from pathlib import Path
from dotenv import load_dotenv
from concurrent.futures import ThreadPoolExecutor, as_completed
import time

load_dotenv()

VISION_PROMPT = """Analyze this email screenshot and extract the following attributes in JSON format:

{
  "layout": "hero_only" | "hero_products" | "hero_categories" | "product_grid" | "editorial" | "text_only",
  "content_type": "sale_announcement" | "sale_reminder" | "product_launch" | "product_showcase" | "content" | "event" | "transactional",
  "hero_style": "lifestyle_photo" | "product_photo" | "illustration" | "text_overlay" | "animated" | "none",
  "hero_description": "detailed description of the hero image content (room type, furniture, colors, mood)",
  "cta_visibility": "prominent" | "subtle" | "inline_links" | "none_visible",
  "cta_types": ["list", "of", "CTA", "texts"],
  "offer_visibility": "hero_overlay" | "header_banner" | "above_fold" | "below_fold" | "none",
  "offer_text": "the actual offer text if visible (e.g. '25% OFF SITEWIDE')",
  "product_categories": ["list", "of", "product", "types"],
  "tone": "aspirational" | "promotional" | "personal" | "informational",
  "color_palette": ["dominant", "colors"]
}

Guidelines:
- layout: hero_only = 1-2 images focused on hero, hero_products = hero + product listings, product_grid = grid of products
- hero_description: Be specific about room type, furniture style, colors, lighting, mood. E.g. "modern living room with beige sectional, potted plants, natural light, minimalist decor"
- If no hero image, set hero_style to "none" and hero_description to "n/a"
- For text-only emails, set layout to "text_only"
- Extract actual CTA button/link texts for cta_types

Return ONLY valid JSON, no markdown or explanation."""


def encode_image(image_path: Path, max_size_bytes: int = 3_500_000) -> str:
    """Encode image to base64, resizing if needed to stay under API limit."""
    from PIL import Image
    import io

    # Read original file
    with open(image_path, "rb") as f:
        data = f.read()

    img = Image.open(io.BytesIO(data))

    # Also check dimensions (API max is 8000px)
    max_dim = 7000
    needs_resize = len(data) > max_size_bytes or img.width > max_dim or img.height > max_dim

    if not needs_resize:
        return base64.standard_b64encode(data).decode("utf-8")

    # Calculate scale factor for size
    size_scale = (max_size_bytes / len(data)) ** 0.5 * 0.8 if len(data) > max_size_bytes else 1.0
    # Calculate scale factor for dimensions
    dim_scale = min(max_dim / img.width, max_dim / img.height) if max(img.width, img.height) > max_dim else 1.0
    # Use the smaller scale
    scale = min(size_scale, dim_scale)

    new_width = int(img.width * scale)
    new_height = int(img.height * scale)

    img_resized = img.resize((new_width, new_height), Image.Resampling.LANCZOS)

    # Save to bytes with compression
    buffer = io.BytesIO()
    img_resized.save(buffer, format='PNG', optimize=True)
    resized_data = buffer.getvalue()

    # If still too large, use JPEG
    if len(resized_data) > max_size_bytes:
        buffer = io.BytesIO()
        if img_resized.mode == 'RGBA':
            img_resized = img_resized.convert('RGB')
        img_resized.save(buffer, format='JPEG', quality=85, optimize=True)
        resized_data = buffer.getvalue()

    return base64.standard_b64encode(resized_data).decode("utf-8")


def analyze_screenshot(client: anthropic.Anthropic, screenshot_path: Path, campaign_id: str) -> dict:
    """Analyze a single screenshot using Claude vision."""
    try:
        image_data = encode_image(screenshot_path)
        media_type = "image/png" if screenshot_path.suffix.lower() == ".png" else "image/jpeg"

        message = client.messages.create(
            model="claude-sonnet-4-20250514",
            max_tokens=1024,
            messages=[
                {
                    "role": "user",
                    "content": [
                        {
                            "type": "image",
                            "source": {
                                "type": "base64",
                                "media_type": media_type,
                                "data": image_data,
                            },
                        },
                        {
                            "type": "text",
                            "text": VISION_PROMPT,
                        }
                    ],
                }
            ],
        )

        response_text = message.content[0].text
        # Parse JSON from response
        try:
            vision_data = json.loads(response_text)
        except json.JSONDecodeError:
            # Try to extract JSON from response
            import re
            json_match = re.search(r'\{[\s\S]+\}', response_text)
            if json_match:
                vision_data = json.loads(json_match.group())
            else:
                print(f"Failed to parse JSON for {campaign_id}: {response_text[:200]}")
                return None

        return {
            "campaign_id": campaign_id,
            "screenshot": str(screenshot_path),
            "vision": vision_data,
        }

    except Exception as e:
        print(f"Error analyzing {campaign_id}: {e}")
        return None


def get_sample_campaigns(campaigns_dir: Path, n_per_brand: int = 25) -> list:
    """Select top and bottom performers by brand."""
    campaigns = []
    for f in campaigns_dir.glob('*.yaml'):
        if f.name.startswith('_'):
            continue
        with open(f) as file:
            data = yaml.safe_load(file)
        if not data:
            continue

        # Skip transactional/system emails
        campaign_type = data.get('campaign_type', '')
        if campaign_type == 'transactional':
            continue

        name = data.get('name', '').lower()
        skip_terms = [
            'transactional', 'order confirmation', 'password', 'receipt', 'order shipped',
            'notification', 'system email', 'order_received', 'order_confirmation',
            'zoom_call', 'new_messages', 'design_ready', 'design_proposal', 'vision_board',
            '3d_design', 'final_order', 'lunes'
        ]
        if any(x in name for x in skip_terms):
            continue

        perf = data.get('performance_summary', {})
        sends = data.get('sends', [])
        if perf.get('total_delivered', 0) >= 1000 and sends:
            screenshot = sends[0].get('screenshot')
            if screenshot:
                campaigns.append({
                    'id': f.stem,
                    'brand': data.get('brand', 'Unknown'),
                    'click_rate': perf.get('click_rate', 0),
                    'screenshot': campaigns_dir / screenshot,
                    'name': data.get('name', ''),
                    'campaign_type': campaign_type,  # For HAV DPS vs merch analysis
                })

    # Select per brand
    selected = []
    for brand in ['HAV', 'CZ', 'BUR', 'STF', 'ID']:
        brand_camps = [c for c in campaigns if c['brand'] == brand]
        if not brand_camps:
            continue

        # Sort by click rate
        sorted_camps = sorted(brand_camps, key=lambda x: x['click_rate'], reverse=True)

        # Take top half and bottom half
        top_n = n_per_brand // 2
        bottom_n = n_per_brand - top_n

        selected.extend(sorted_camps[:top_n])  # Top performers
        selected.extend(sorted_camps[-bottom_n:])  # Bottom performers

    return selected


def main():
    parser = argparse.ArgumentParser(description='Analyze email screenshots with Claude vision')
    parser.add_argument('--campaigns-dir', default='campaigns', help='Path to campaigns directory')
    parser.add_argument('--output', default='creative/vision_analysis.yaml', help='Output file path')
    parser.add_argument('--n-per-brand', type=int, default=25, help='Number of campaigns per brand')
    parser.add_argument('--workers', type=int, default=3, help='Number of parallel workers')
    parser.add_argument('--dry-run', action='store_true', help='List campaigns without analyzing')
    args = parser.parse_args()

    campaigns_dir = Path(args.campaigns_dir)
    output_path = Path(args.output)
    output_path.parent.mkdir(parents=True, exist_ok=True)

    # Get sample campaigns
    samples = get_sample_campaigns(campaigns_dir, args.n_per_brand)
    print(f"Selected {len(samples)} campaigns for analysis")

    # Show breakdown by brand
    by_brand = {}
    for s in samples:
        brand = s['brand']
        by_brand[brand] = by_brand.get(brand, 0) + 1
    for brand, count in sorted(by_brand.items()):
        print(f"  {brand}: {count}")

    if args.dry_run:
        print("\nSample campaigns:")
        for s in samples[:10]:
            print(f"  [{s['brand']}] {s['name'][:50]} (click: {s['click_rate']*100:.2f}%)")
        return

    # Initialize Anthropic client
    client = anthropic.Anthropic()

    # Analyze screenshots
    results = []
    start_time = time.time()

    def process(campaign):
        if not campaign['screenshot'].exists():
            print(f"Screenshot not found: {campaign['screenshot']}")
            return None
        result = analyze_screenshot(client, campaign['screenshot'], campaign['id'])
        if result and campaign.get('campaign_type'):
            result['campaign_type'] = campaign['campaign_type']
        return result

    with ThreadPoolExecutor(max_workers=args.workers) as executor:
        futures = {executor.submit(process, c): c for c in samples}
        for i, future in enumerate(as_completed(futures)):
            result = future.result()
            if result:
                results.append(result)
            elapsed = time.time() - start_time
            avg_per = elapsed / (i + 1)
            remaining = (len(samples) - i - 1) * avg_per
            print(f"Progress: {i+1}/{len(samples)} ({elapsed:.0f}s elapsed, ~{remaining:.0f}s remaining)")

    # Save results
    output_data = {
        'generated': time.strftime('%Y-%m-%d %H:%M:%S'),
        'total_analyzed': len(results),
        'campaigns': results
    }

    with open(output_path, 'w') as f:
        yaml.dump(output_data, f, default_flow_style=False, allow_unicode=True, sort_keys=False)

    print(f"\nSaved {len(results)} analyses to {output_path}")
    print(f"Total time: {time.time() - start_time:.0f}s")


if __name__ == '__main__':
    main()
