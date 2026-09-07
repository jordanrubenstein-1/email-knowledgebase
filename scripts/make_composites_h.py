"""
Horizontal composite panels for FigJam.
Each canvas = one wide image: thumbnail of top of each email arranged side by side.
Much more readable at FigJam zoom levels than tall vertical strips.
"""

from pathlib import Path
from PIL import Image, ImageDraw, ImageFont

SC  = Path("/Users/nicole.poulson/email-knowledgebase/campaigns/screenshots")
OUT = SC / "composites"
OUT.mkdir(exist_ok=True)

THUMB_W    = 360          # width of each email thumbnail
THUMB_H    = 520          # crop: top N pixels of email (above the fold)
STEP_LABEL_H = 44         # height of label bar under each thumb
TITLE_W    = 260          # left title column width
GAP        = 16           # gap between thumbnails
PAD        = 24           # outer padding
BG         = (235, 235, 235)
TITLE_BG   = (30,  30,  30)
TITLE_FG   = (255, 255, 255)
LABEL_BG   = (60,  60,  60)
LABEL_FG   = (255, 255, 255)
PLACEHOLDER_COLOR = (195, 195, 195)
PLACEHOLDER_FG    = (120, 120, 120)

try:
    font_title = ImageFont.truetype("/System/Library/Fonts/Helvetica.ttc", 22)
    font_sub   = ImageFont.truetype("/System/Library/Fonts/Helvetica.ttc", 14)
    font_label = ImageFont.truetype("/System/Library/Fonts/Helvetica.ttc", 13)
except Exception:
    font_title = font_sub = font_label = ImageFont.load_default()


def make_panel(canvas_title: str, subtitle: str, steps: list, filename: str):
    """
    steps: list of (label: str, screenshot_path: Path | None)
    """
    n = len(steps)
    total_w = PAD + TITLE_W + GAP + n * (THUMB_W + GAP) + PAD
    total_h = PAD + THUMB_H + STEP_LABEL_H + PAD

    img = Image.new("RGB", (total_w, total_h), BG)
    draw = ImageDraw.Draw(img)

    # ── Title column ─────────────────────────────────────────────────────────
    title_box_h = total_h - 2 * PAD
    draw.rectangle([PAD, PAD, PAD + TITLE_W, PAD + title_box_h], fill=TITLE_BG)
    # Wrap title text
    draw.text((PAD + 14, PAD + 18), canvas_title, font=font_title, fill=TITLE_FG)
    draw.text((PAD + 14, PAD + 18 + 34), subtitle, font=font_sub, fill=(180, 180, 180))

    # ── Thumbnails ───────────────────────────────────────────────────────────
    x = PAD + TITLE_W + GAP
    for label, p in steps:
        y_thumb = PAD
        y_label = PAD + THUMB_H

        if p is not None and Path(p).exists():
            src = Image.open(p).convert("RGB")
            # scale to THUMB_W, then crop top THUMB_H pixels
            ratio = THUMB_W / src.width
            new_h = int(src.height * ratio)
            src = src.resize((THUMB_W, max(new_h, THUMB_H)), Image.LANCZOS)
            thumb = src.crop((0, 0, THUMB_W, THUMB_H))
            img.paste(thumb, (x, y_thumb))
        else:
            # SMS placeholder
            draw.rectangle([x, y_thumb, x + THUMB_W, y_thumb + THUMB_H],
                           fill=PLACEHOLDER_COLOR)
            msg1 = "SMS step"
            msg2 = "(opted-in subscribers only)"
            draw.text((x + THUMB_W // 2 - 38, y_thumb + THUMB_H // 2 - 18),
                      msg1, font=font_sub, fill=PLACEHOLDER_FG)
            draw.text((x + THUMB_W // 2 - 90, y_thumb + THUMB_H // 2 + 4),
                      msg2, font=font_label, fill=PLACEHOLDER_FG)

        # Step label
        draw.rectangle([x, y_label, x + THUMB_W, y_label + STEP_LABEL_H],
                       fill=LABEL_BG)
        # Wrap label to 2 lines if needed
        lines = label.split(": ", 1)
        if len(lines) == 2:
            draw.text((x + 8, y_label + 6),  lines[0] + ":", font=font_label, fill=(180, 180, 180))
            draw.text((x + 8, y_label + 22), lines[1],        font=font_label, fill=LABEL_FG)
        else:
            draw.text((x + 8, y_label + 14), label, font=font_label, fill=LABEL_FG)

        x += THUMB_W + GAP

    out_path = OUT / filename
    img.save(out_path, "PNG")
    print(f"✓ {filename}  {total_w}×{total_h}px  ({out_path.stat().st_size // 1024} KB)")
    return out_path


# ── Canvas definitions ─────────────────────────────────────────────────────
CANVASES = [
    (
        "Welcome\n— General",
        "Trigger: New subscriber",
        [
            ("T1 EM: Welcome to Burrow",              SC / "canvas-welcome-flow-general-t1-e62bb422.png"),
            ("T2 EM: Your room, realized",             SC / "canvas-welcome-flow-general-t2-53d2aace.png"),
            ("T3 EM: We like your style",              SC / "canvas-welcome-flow-general-t3-5f5f4ce5.png"),
            ("T4 EM: Choosing furniture takes time",   SC / "canvas-welcome-flow-general-t4-3d70e6e4.png"),
            ("T5 EM: Have you considered…",            SC / "canvas-welcome-flow-general-t5-877ae7a1.png"),
            ("T6 EM: Still thinking it over?",         SC / "canvas-welcome-flow-general-t6-598a16ff.png"),
        ],
        "panel-welcome-general.png",
    ),
    (
        "Post-Order\nWelcome",
        "Trigger: First order placed",
        [
            ("T1 EM: Welcome to the fam",              SC / "canvas-post-order-welcome-to-new-subscribers-t1-eb805a94.png"),
            ("T2 EM: Your next chapter",               SC / "canvas-post-order-welcome-to-new-subscribers-t2-5a5b4f43.png"),
            ("T3 EM: Sit back and relax",              SC / "canvas-post-order-welcome-to-new-subscribers-t3-2cf0cab1.png"),
            ("T4 EM: Refer a friend",                  SC / "canvas-post-order-welcome-to-new-subscribers-t4-2a5dde7f.png"),
        ],
        "panel-post-order-welcome.png",
    ),
    (
        "Abandon\nBrowse\nMulti Product",
        "Trigger: Browse ≥2 products",
        [
            ("T1 EM: Still thinking it over?",         SC / "canvas-abandon-browse-multi-product-t1-2e9b7807.png"),
            ("T2 SMS: Cart reminder",                  None),
            ("T3 EM: We Like Your Style",              SC / "canvas-abandon-browse-multi-product-t3-87c4dd97.png"),
            ("T4 SMS: Final nudge",                    None),
        ],
        "panel-abandon-browse-multi.png",
    ),
    (
        "Abandon\nBrowse\nProduct Viewed",
        "Trigger: Browse single product",
        [
            ("T1 EM: Still thinking it over?",         SC / "canvas-abandon-browse-product-viewed-t1-a3b17256.png"),
            ("T2 SMS: Cart reminder",                  None),
            ("T3 EM: We Like Your Style",              SC / "canvas-abandon-browse-product-viewed-t3-d37d0bfe.png"),
            ("T4 SMS: Final nudge",                    None),
        ],
        "panel-abandon-browse-product.png",
    ),
    (
        "Abandon\nCart",
        "Trigger: Cart updated, no purchase",
        [
            ("T1 EM: You left something behind",       SC / "canvas-abandon-cart-cart-updated-t1-7a696095.png"),
            ("T2 SMS: Cart reminder",                  None),
            ("T3 EM: Your cart misses you",            SC / "canvas-abandon-cart-cart-updated-t3-0f358f66.png"),
            ("T4 EM: Last call for your cart",         SC / "canvas-abandon-cart-cart-updated-t4-476ef1ef.png"),
            ("T5 SMS: Final nudge",                    None),
            ("T6 EM: Final reminder",                  SC / "canvas-abandon-cart-cart-updated-t6-f5afc812.png"),
        ],
        "panel-abandon-cart.png",
    ),
    (
        "Swatch\nPost-Purchase",
        "Trigger: Swatch order placed",
        [
            ("T1 EM: Your swatches arrived?",          SC / "canvas-swatch-post-purchase-t1-31f11c68.png"),
            ("T2 EM: Make a decision",                 SC / "canvas-swatch-post-purchase-t2-2baac239.png"),
            ("T3 EM: Last chance",                     SC / "canvas-swatch-post-purchase-t3-8407a055.png"),
        ],
        "panel-swatch-post-purchase.png",
    ),
    (
        "Post-Order\nCross-Sell",
        "Trigger: Order delivered",
        [
            ("T1 EM: Complete your space",             SC / "canvas-post-order-cross-sell-t1-abfae1b7.png"),
        ],
        "panel-post-order-cross-sell.png",
    ),
    (
        "Transactional\nFlows",
        "Order / shipping updates",
        [
            ("Order Confirmation",                     SC / "canvas-order-confirmation-t1-acd00408.png"),
            ("Shipping Confirmation",                  SC / "canvas-shipping-confirmation-t1-e2316e3f.png"),
            ("Out for Delivery",                       SC / "canvas-out-for-delivery-t1-d58aa9c7.png"),
            ("Delivery Confirmation",                  SC / "canvas-delivery-confirmation-t1-d1824954.png"),
            ("Post-Shipment RAF",                      SC / "canvas-post-shipment-delivered-raf-t1-a5da3eb2.png"),
        ],
        "panel-transactional.png",
    ),
]


if __name__ == "__main__":
    print(f"Generating {len(CANVASES)} horizontal panels...\n")
    for title, subtitle, steps, filename in CANVASES:
        make_panel(title, subtitle, steps, filename)
    print(f"\nDone → {OUT}")
