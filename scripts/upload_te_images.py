"""
Upload cropped TE flow screenshots to Figma via REST API and collect image hashes.
Uses the /v1/images endpoint (POST) to upload images and get back image hashes
that can be used in plugin fills.

Usage:
    python scripts/upload_te_images.py
Outputs:
    scripts/te_image_hashes.json  — {msg_id: imageHash}
"""
import os, json, sys, tempfile, requests
from pathlib import Path
from PIL import Image
from dotenv import load_dotenv

load_dotenv()

TOKEN    = os.getenv("FIGMA_ACCESS_TOKEN")
FILE_KEY = "dtgM4oqjnYueUniBESjCHJ"
BASE     = Path(__file__).parent.parent
SS_DIR   = BASE / "campaigns" / "screenshots"
OUT_FILE = Path(__file__).parent / "te_image_hashes.json"

CARD_W = 260

# All (msg_id, screenshot_slug) pairs needed for the board
STEPS = [
    # Welcome Series
    ("RexA77", "klv-flow-flow-welcome-series-t01-RexA77"),
    ("VmM9pi", "klv-flow-flow-welcome-series-t02-VmM9pi"),
    ("U7K4a4", "klv-flow-flow-welcome-series-t03-U7K4a4"),
    ("YeYBsf", "klv-flow-flow-welcome-series-t04-YeYBsf"),
    ("Yamm6R", "klv-flow-flow-welcome-series-t05-Yamm6R"),
    ("YjHZ4R", "klv-flow-flow-welcome-series-t06-YjHZ4R"),
    ("VcTHRZ", "klv-flow-flow-welcome-series-t07-VcTHRZ"),
    ("SGJpcT", "klv-flow-flow-welcome-series-t08-SGJpcT"),
    ("S3GkrK", "klv-flow-flow-welcome-series-t09-S3GkrK"),
    ("Rwv4fe", "klv-flow-flow-welcome-series-t10-Rwv4fe"),
    ("TgTVBc", "klv-flow-flow-welcome-series-t11-TgTVBc"),
    ("VJX7Vb", "klv-flow-flow-welcome-series-t12-VJX7Vb"),
    ("QZBWMT", "klv-flow-flow-welcome-series-t13-QZBWMT"),
    ("Y4jugu", "klv-flow-flow-welcome-series-t14-Y4jugu"),
    # Trade Welcome June 2026
    ("Tmjisd", "klv-flow-trade_program-welcome-june2026-t01-Tmjisd"),
    ("SDEZuc", "klv-flow-trade_program-welcome-june2026-t02-SDEZuc"),
    ("RW2Gwb", "klv-flow-trade_program-welcome-june2026-t05-RW2Gwb"),
    ("RiZDTy", "klv-flow-trade_program-welcome-june2026-t06-RiZDTy"),
    ("Renpya", "klv-flow-trade_program-welcome-june2026-t07-Renpya"),
    ("VmBWQm", "klv-flow-trade_program-welcome-june2026-t08-VmBWQm"),
    ("Wx2MJd", "klv-flow-trade_program-welcome-june2026-t09-Wx2MJd"),
    ("UDXDSk", "klv-flow-trade_program-welcome-june2026-t10-UDXDSk"),
    ("XBNngF", "klv-flow-trade_program-welcome-june2026-t11-XBNngF"),
    # Trade Welcome July 2025
    ("W3GLND", "klv-flow-trade_program-welcome-july2025-t01-W3GLND"),
    ("RKcGPE", "klv-flow-trade_program-welcome-july2025-t02-RKcGPE"),
    ("REzsug", "klv-flow-trade_program-welcome-july2025-t03-REzsug"),
    ("S3GJ4H", "klv-flow-trade_program-welcome-july2025-t04-S3GJ4H"),
    ("Xb6BxY", "klv-flow-trade_program-welcome-july2025-t05-Xb6BxY"),
    ("RHbGF9", "klv-flow-trade_program-welcome-july2025-t06-RHbGF9"),
    ("XCR9tP", "klv-flow-trade_program-welcome-july2025-t07-XCR9tP"),
    ("WDijgA", "klv-flow-trade_program-welcome-july2025-t08-WDijgA"),
    ("W3ugDD", "klv-flow-trade_program-welcome-july2025-t09-W3ugDD"),
    # Trade Post-Purchase
    ("Vhpnpq", "klv-flow-flow-sr_post-purchase_trade-t01-Vhpnpq"),
    ("WsNdhg", "klv-flow-flow-sr_post-purchase_trade-t02-WsNdhg"),
    ("XCd4b8", "klv-flow-flow-sr_post-purchase_trade-t03-XCd4b8"),
    ("UEyjbw", "klv-flow-flow-sr_post-purchase_trade-t05-UEyjbw"),
    # Browse Abandonment
    ("Tb2443", "klv-flow-flow-sh_abandoned-browse2-t01-Tb2443"),
    # Create Account
    ("QTWspr", "klv-flow-flow-co_create-account-t01-QTWspr"),
    ("T9nd5j", "klv-flow-flow-co_create-account-t02-T9nd5j"),
    ("YwDRAL", "klv-flow-flow-co_create-account-t03-YwDRAL"),
    # Cart Abandonment
    ("SQvLwU", "klv-flow-flow-sh_abandoned-cart2-t01-SQvLwU"),
    ("VbjsiC", "klv-flow-flow-sh_abandoned-cart2-t02-VbjsiC"),
    # Post-Consultation
    ("TjbnSg", "klv-flow-flow-co_post-consultation_ecom-t01-TjbnSg"),
    ("SJLAsw", "klv-flow-flow-co_post-consultation_ecom-t02-SJLAsw"),
    ("Xf9rja", "klv-flow-flow-co_post-consultation_ecom-t03-Xf9rja"),
    ("UdgGBM", "klv-flow-flow-co_post-consultation_ecom-t04-UdgGBM"),
    ("Su5ZfP", "klv-flow-flow-co_post-consultation_ecom-t05-Su5ZfP"),
    ("R9HdBK", "klv-flow-flow-co_post-consultation_ecom-t06-R9HdBK"),
    ("VX4PHP", "klv-flow-flow-co_post-consultation_ecom-t07-VX4PHP"),
]

MAX_H = 2400  # cap display height


def autocrop(path, pad=2):
    img = Image.open(path).convert("RGBA")
    bg = img.getpixel((0, 0))
    pix = img.load()
    w, h = img.size
    top    = next((y for y in range(h)         for x in range(w) if pix[x,y][:3] != bg[:3]), 0)
    bottom = next((y for y in range(h-1,-1,-1) for x in range(w) if pix[x,y][:3] != bg[:3]), h)
    left   = next((x for x in range(w)         for y in range(h) if pix[x,y][:3] != bg[:3]), 0)
    right  = next((x for x in range(w-1,-1,-1) for y in range(h) if pix[x,y][:3] != bg[:3]), w)
    return img.crop((max(0,left-pad), max(0,top-pad), min(w,right+pad), min(h,bottom+pad)))


def upload_image(png_bytes: bytes) -> str:
    """Upload image to Figma via /v1/files/{key}/images and return imageHash."""
    url = f"https://api.figma.com/v1/files/{FILE_KEY}/images"
    resp = requests.post(
        url,
        headers={
            "X-Figma-Token": TOKEN,
            "Content-Type":  "image/png",
        },
        data=png_bytes,
    )
    if resp.status_code != 200:
        raise RuntimeError(f"Upload failed {resp.status_code}: {resp.text[:200]}")
    data = resp.json()
    # Response: {"imageHash": "...", "url": "..."}
    return data.get("imageHash") or data.get("url", "")


def main():
    if not TOKEN:
        print("ERROR: FIGMA_ACCESS_TOKEN not set in .env")
        sys.exit(1)

    # Load existing hashes if partial run
    IH = {}
    if OUT_FILE.exists():
        IH = json.loads(OUT_FILE.read_text())
        print(f"Loaded {len(IH)} existing hashes from {OUT_FILE.name}")

    tmpdir = tempfile.mkdtemp()
    errors = []

    for i, (msg_id, slug) in enumerate(STEPS, 1):
        if msg_id in IH:
            print(f"  [{i:02d}/{len(STEPS)}] SKIP (cached): {msg_id}")
            continue

        src = SS_DIR / f"{slug}.png"
        if not src.exists():
            print(f"  [{i:02d}/{len(STEPS)}] MISSING screenshot: {src.name}")
            errors.append(msg_id)
            continue

        # Autocrop
        cropped = autocrop(src)
        cw, ch = cropped.size
        fh = min(round(ch * CARD_W / cw), MAX_H)

        # If capped, also crop the source image height proportionally before upload
        if fh < round(ch * CARD_W / cw):
            max_src_h = round(MAX_H * cw / CARD_W)
            cropped = cropped.crop((0, 0, cw, min(ch, max_src_h)))

        tmp_path = f"{tmpdir}/{msg_id}.png"
        cropped.save(tmp_path, "PNG")
        png_bytes = open(tmp_path, "rb").read()

        try:
            image_hash = upload_image(png_bytes)
            IH[msg_id] = image_hash
            print(f"  [{i:02d}/{len(STEPS)}] OK  {msg_id}: {image_hash[:20]}...  (display {fh}px)")
        except Exception as e:
            print(f"  [{i:02d}/{len(STEPS)}] ERROR {msg_id}: {e}")
            errors.append(msg_id)

        # Save after each upload (resume-safe)
        OUT_FILE.write_text(json.dumps(IH, indent=2))

    print(f"\nDone. {len(IH)} hashes saved to {OUT_FILE}")
    if errors:
        print(f"Failed: {errors}")
    return IH


if __name__ == "__main__":
    main()
