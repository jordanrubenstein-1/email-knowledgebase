"""Generate per-canvas composite strip images for FigJam upload."""

from pathlib import Path
from PIL import Image, ImageDraw, ImageFont

SC = Path("/Users/nicole.poulson/email-knowledgebase/campaigns/screenshots")
OUT = SC / "composites"
OUT.mkdir(exist_ok=True)

IMG_W = 640          # width each email thumb is resized to
LABEL_H = 40         # height of label bar above each thumb
PLACEHOLDER_H = 200  # height of grey placeholder for SMS/missing
PADDING = 20         # vertical gap between steps
BG_COLOR = (245, 245, 245)
LABEL_BG = (50, 50, 50)
LABEL_FG = (255, 255, 255)
PLACEHOLDER_COLOR = (200, 200, 200)
PLACEHOLDER_TEXT_COLOR = (100, 100, 100)

try:
    font = ImageFont.truetype("/System/Library/Fonts/Helvetica.ttc", 18)
    small_font = ImageFont.truetype("/System/Library/Fonts/Helvetica.ttc", 14)
except Exception:
    font = ImageFont.load_default()
    small_font = font


def make_composite(title: str, steps: list, filename: str):
    """
    steps: list of (label: str, screenshot_path: Path | None)
    None path = SMS-only or missing → grey placeholder
    """
    # First pass: build list of (label, image_or_none, height)
    items = []
    for label, p in steps:
        if p is not None and Path(p).exists():
            im = Image.open(p).convert("RGB")
            ratio = IMG_W / im.width
            h = int(im.height * ratio)
            im = im.resize((IMG_W, h), Image.LANCZOS)
            items.append((label, im, LABEL_H + h))
        else:
            items.append((label, None, LABEL_H + PLACEHOLDER_H))

    # Title bar height
    TITLE_H = 60
    total_h = TITLE_H + sum(h + PADDING for _, _, h in items) + PADDING

    canvas = Image.new("RGB", (IMG_W, total_h), BG_COLOR)
    draw = ImageDraw.Draw(canvas)

    # Draw title
    draw.rectangle([0, 0, IMG_W, TITLE_H], fill=(30, 30, 30))
    draw.text((16, 16), title, font=font, fill=(255, 255, 255))

    y = TITLE_H + PADDING
    for label, im, block_h in items:
        # Label bar
        draw.rectangle([0, y, IMG_W, y + LABEL_H], fill=LABEL_BG)
        draw.text((12, y + 10), label, font=small_font, fill=LABEL_FG)
        y += LABEL_H

        if im is not None:
            canvas.paste(im, (0, y))
            y += im.height
        else:
            # Grey placeholder
            draw.rectangle([0, y, IMG_W, y + PLACEHOLDER_H], fill=PLACEHOLDER_COLOR)
            msg = "SMS step — no email creative"
            draw.text((IMG_W // 2 - 120, y + PLACEHOLDER_H // 2 - 10),
                      msg, font=small_font, fill=PLACEHOLDER_TEXT_COLOR)
            y += PLACEHOLDER_H

        y += PADDING

    out_path = OUT / filename
    canvas.save(out_path, "PNG")
    print(f"✓ {filename}  ({out_path.stat().st_size // 1024} KB)")
    return out_path


# ── Canvas definitions ─────────────────────────────────────────────────────
CANVASES = [
    (
        "Welcome — General",
        [
            ("T1 EM: Welcome to Burrow", SC / "canvas-welcome-flow-general-t1-e62bb422.png"),
            ("T2 EM: Your room, realized", SC / "canvas-welcome-flow-general-t2-53d2aace.png"),
            ("T3 EM: We like your style", SC / "canvas-welcome-flow-general-t3-5f5f4ce5.png"),
            ("T4 EM: Choosing furniture takes time", SC / "canvas-welcome-flow-general-t4-3d70e6e4.png"),
            ("T5 EM: Have you considered…", SC / "canvas-welcome-flow-general-t5-877ae7a1.png"),
            ("T6 EM: Still thinking it over?", SC / "canvas-welcome-flow-general-t6-598a16ff.png"),
        ],
        "welcome-general.png",
    ),
    (
        "Post-Order Welcome",
        [
            ("T1 EM: Welcome to the Burrow fam", SC / "canvas-post-order-welcome-to-new-subscribers-t1-eb805a94.png"),
            ("T2 EM: Your next chapter starts here", SC / "canvas-post-order-welcome-to-new-subscribers-t2-5a5b4f43.png"),
            ("T3 EM: Sit back and relax", SC / "canvas-post-order-welcome-to-new-subscribers-t3-2cf0cab1.png"),
            ("T4 EM: Refer a friend", SC / "canvas-post-order-welcome-to-new-subscribers-t4-2a5dde7f.png"),
        ],
        "post-order-welcome.png",
    ),
    (
        "Abandon Browse — Multi Product",
        [
            ("T1 EM: Still thinking it over?", SC / "canvas-abandon-browse-multi-product-t1-2e9b7807.png"),
            ("T2 SMS: [opted-in only]", None),
            ("T3 EM: We Like Your Style", SC / "canvas-abandon-browse-multi-product-t3-87c4dd97.png"),
            ("T4 SMS: [opted-in only]", None),
        ],
        "abandon-browse-multi-product.png",
    ),
    (
        "Abandon Browse — Product Viewed",
        [
            ("T1 EM: Still thinking it over?", SC / "canvas-abandon-browse-product-viewed-t1-a3b17256.png"),
            ("T2 SMS: [opted-in only]", None),
            ("T3 EM: We Like Your Style", SC / "canvas-abandon-browse-product-viewed-t3-d37d0bfe.png"),
            ("T4 SMS: [opted-in only]", None),
        ],
        "abandon-browse-product-viewed.png",
    ),
    (
        "Abandon Cart — Cart Updated",
        [
            ("T1 EM: You left something behind", SC / "canvas-abandon-cart-cart-updated-t1-7a696095.png"),
            ("T2 SMS: [opted-in only]", None),
            ("T3 EM: Your cart misses you", SC / "canvas-abandon-cart-cart-updated-t3-0f358f66.png"),
            ("T4 EM: Last call for your cart", SC / "canvas-abandon-cart-cart-updated-t4-476ef1ef.png"),
            ("T5 SMS: [opted-in only]", None),
            ("T6 EM: Final reminder", SC / "canvas-abandon-cart-cart-updated-t6-f5afc812.png"),
        ],
        "abandon-cart.png",
    ),
    (
        "Swatch Post-Purchase",
        [
            ("T1 EM: Your swatches have arrived?", SC / "canvas-swatch-post-purchase-t1-31f11c68.png"),
            ("T2 EM: Make a decision", SC / "canvas-swatch-post-purchase-t2-2baac239.png"),
            ("T3 EM: Last chance", SC / "canvas-swatch-post-purchase-t3-8407a055.png"),
        ],
        "swatch-post-purchase.png",
    ),
    (
        "Post-Order Cross-Sell",
        [
            ("T1 EM: Complete your space", SC / "canvas-post-order-cross-sell-t1-abfae1b7.png"),
        ],
        "post-order-cross-sell.png",
    ),
    (
        "Transactional Flows",
        [
            ("Order Confirmation T1", SC / "canvas-order-confirmation-t1-acd00408.png"),
            ("Shipping Confirmation T1", SC / "canvas-shipping-confirmation-t1-e2316e3f.png"),
            ("Out for Delivery T1", SC / "canvas-out-for-delivery-t1-d58aa9c7.png"),
            ("Delivery Confirmation T1", SC / "canvas-delivery-confirmation-t1-d1824954.png"),
            ("Post-Shipment RAF T1", SC / "canvas-post-shipment-delivered-raf-t1-a5da3eb2.png"),
        ],
        "transactional-flows.png",
    ),
]

if __name__ == "__main__":
    print(f"Generating {len(CANVASES)} composite images...\n")
    paths = []
    for title, steps, filename in CANVASES:
        path = make_composite(title, steps, filename)
        paths.append(str(path))
    print(f"\nDone. Output: {OUT}")
    for p in paths:
        print(f"  {p}")
