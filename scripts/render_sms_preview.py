"""
Generate phone-mockup style SMS preview images for FigJam boards.

Renders each SMS step as a white rounded-rectangle bubble on a grey
iOS-style background, matching the BW reference at FigJam node 163-242.

Usage:
    uv run python scripts/render_sms_preview.py
    uv run python scripts/render_sms_preview.py --brand ID --canvas sms-welcome

Output: campaigns/screenshots/rendered/sms-{brand}-{canvas}-t{N}.png
"""

import re
import sys
import textwrap
import argparse
from pathlib import Path
from PIL import Image, ImageDraw, ImageFont

OUT_DIR = Path("campaigns/screenshots/rendered")
OUT_DIR.mkdir(parents=True, exist_ok=True)

# ── SMS step definitions ────────────────────────────────────────────────────

ID_SMS_WELCOME_STEPS = [
    {
        "step": 1,
        "name": "TRG_SMS_2025_07_ID_Welcome_T1",
        "timing": "Day 0",
        "label": "Welcome + 10% off code",
        "body": (
            "Interior Define: Welcome to Interior Define! "
            "Use code WELCOME10 for 10% off your first purchase. "
            "Happy Customizing! [link]"
        ),
    },
    {
        "step": 2,
        "name": "TRG_SMS_2025_07_ID_Welcome_T2",
        "timing": "~Day 1",
        "label": "Save our contact",
        "body": (
            "Interior Define: Let's make this official! "
            "Save our contact for exclusive updates and offers."
        ),
    },
    {
        "step": 3,
        "name": "TRG_SMS_2025_07_ID_Welcome_T3",
        "timing": "~Day 3",
        "label": "Fan favorites",
        "body": (
            "Interior Define: These best sellers made us think of you! "
            "Check out our fan favorites: [link]"
        ),
    },
    {
        "step": 4,
        "name": "TRG_SMS_2025_07_ID_Welcome_T4",
        "timing": "~Day 7",
        "label": "Discount reminder",
        "body": (
            "Interior Define: Ready to transform your space? "
            "Your 10% off code WELCOME10 is waiting. "
            "Start customizing: [link]"
        ),
    },
    {
        "step": 5,
        "name": "TRG_SMS_2025_07_ID_Welcome_T5",
        "timing": "~Day 10",
        "label": "Order free swatches",
        "body": (
            "Interior Define: It all starts with a swatch. "
            "Choose from our collection of over 150+ fabrics. "
            "Order free swatches: [link]"
        ),
    },
    {
        "step": 6,
        "name": "TRG_SMS_2025_07_ID_Welcome_T6",
        "timing": "~Day 14",
        "label": "Quick ship",
        "body": (
            "Interior Define: Made-to-order pieces, made fast. "
            "Get yours in 6–8 weeks when you order now. "
            "Shop quick ship: [link]"
        ),
    },
    {
        "step": 7,
        "name": "TRG_SMS_2025_07_ID_Welcome_T7",
        "timing": "~Day 18",
        "label": "Geo: Store invite",
        "body": (
            "Interior Define: [Geo-targeted]\n"
            "Store invite for subscribers near Santa Monica, CA.\n"
            "Content personalised by zip code."
        ),
    },
    {
        "step": 8,
        "name": "TRG_SMS_2025_07_ID_Welcome_T8",
        "timing": "~Day 21",
        "label": "Pet-friendly fabrics",
        "body": (
            "Interior Define: We welcome furry friends on our furniture — "
            "sharp claws, muddy paws, and shedding seasons are no match "
            "for our performance fabrics. Read the Guide: [link]"
        ),
    },
]

CANVAS_REGISTRY = {
    ("ID", "sms-welcome"): ID_SMS_WELCOME_STEPS,
}


# ── Image rendering ─────────────────────────────────────────────────────────

BG_COLOR = (239, 238, 244)      # iOS SMS screen grey
BUBBLE_COLOR = (255, 255, 255)  # White message bubble
TEXT_COLOR = (28, 28, 30)       # iOS near-black
LINK_COLOR = (0, 122, 255)      # iOS blue for [link]
CANVAS_W = 260
BUBBLE_MARGIN_X = 10
BUBBLE_MARGIN_TOP = 14
BUBBLE_PADDING_X = 12
BUBBLE_PADDING_Y = 10
BUBBLE_RADIUS = 14
BOTTOM_PAD = 14
FONT_SIZE = 12
LINE_SPACING = 4


def _load_font(size: int):
    for path in [
        "/System/Library/Fonts/Helvetica.ttc",
        "/System/Library/Fonts/SFNSText.ttf",
        "/usr/share/fonts/truetype/dejavu/DejaVuSans.ttf",
    ]:
        try:
            return ImageFont.truetype(path, size)
        except Exception:
            pass
    return ImageFont.load_default()


def _wrap_text(text: str, font, max_px: int) -> list[str]:
    """Word-wrap text to fit within max_px, returning list of lines."""
    lines = []
    for paragraph in text.split("\n"):
        words = paragraph.split()
        if not words:
            lines.append("")
            continue
        current = words[0]
        for w in words[1:]:
            trial = current + " " + w
            bbox = font.getbbox(trial)
            if bbox[2] - bbox[0] <= max_px:
                current = trial
            else:
                lines.append(current)
                current = w
        lines.append(current)
    return lines


def render_sms_bubble(body: str, output_path: Path) -> Path:
    """Render a single SMS body text as a phone-mockup PNG."""
    font = _load_font(FONT_SIZE)
    line_h = FONT_SIZE + LINE_SPACING

    max_text_w = CANVAS_W - 2 * BUBBLE_MARGIN_X - 2 * BUBBLE_PADDING_X
    lines = _wrap_text(body, font, max_text_w)

    text_block_h = len(lines) * line_h - LINE_SPACING
    bubble_w = CANVAS_W - 2 * BUBBLE_MARGIN_X
    bubble_h = text_block_h + 2 * BUBBLE_PADDING_Y
    canvas_h = BUBBLE_MARGIN_TOP + bubble_h + BOTTOM_PAD

    img = Image.new("RGB", (CANVAS_W, canvas_h), BG_COLOR)
    draw = ImageDraw.Draw(img)

    # Draw bubble (rounded rectangle)
    bx0 = BUBBLE_MARGIN_X
    by0 = BUBBLE_MARGIN_TOP
    bx1 = bx0 + bubble_w
    by1 = by0 + bubble_h
    draw.rounded_rectangle([bx0, by0, bx1, by1], radius=BUBBLE_RADIUS, fill=BUBBLE_COLOR)

    # Draw text line by line, colouring [link] in blue
    tx = bx0 + BUBBLE_PADDING_X
    ty = by0 + BUBBLE_PADDING_Y
    for line in lines:
        if "[link]" in line:
            parts = line.split("[link]")
            cx = tx
            for i, part in enumerate(parts):
                draw.text((cx, ty), part, font=font, fill=TEXT_COLOR)
                cx += font.getlength(part)
                if i < len(parts) - 1:
                    draw.text((cx, ty), "[link]", font=font, fill=LINK_COLOR)
                    cx += font.getlength("[link]")
        else:
            draw.text((tx, ty), line, font=font, fill=TEXT_COLOR)
        ty += line_h

    img.save(output_path, "PNG")
    return output_path


# ── CLI ─────────────────────────────────────────────────────────────────────

def main():
    parser = argparse.ArgumentParser(description="Render SMS preview images for FigJam boards")
    parser.add_argument("--brand", default="ID", help="Brand code (e.g. ID)")
    parser.add_argument("--canvas", default="sms-welcome", help="Canvas slug (e.g. sms-welcome)")
    args = parser.parse_args()

    key = (args.brand.upper(), args.canvas.lower())
    steps = CANVAS_REGISTRY.get(key)
    if not steps:
        print(f"No step definitions found for {key}. Available: {list(CANVAS_REGISTRY.keys())}", file=sys.stderr)
        sys.exit(1)

    print(f"Rendering {len(steps)} SMS preview(s) for {args.brand} {args.canvas}...\n")
    for step in steps:
        fname = f"sms-{args.brand.lower()}-{args.canvas}-t{step['step']}.png"
        out_path = OUT_DIR / fname
        render_sms_bubble(step["body"], out_path)
        kb = out_path.stat().st_size // 1024
        print(f"  ✓ {fname}  {kb} KB")

    print(f"\nDone → {OUT_DIR}")


if __name__ == "__main__":
    main()
