"""
Local HTTP server that serves autocropped TE flow screenshots for the Figma plugin.

Usage:
    python scripts/serve_te_screenshots.py
    # Serves on http://localhost:8899
    # Request: GET /RexA77.png  →  autocropped version of klv-flow-...-RexA77.png

Stop with Ctrl+C.
"""
import os, io, sys
from pathlib import Path
from http.server import BaseHTTPRequestHandler, HTTPServer
from PIL import Image

BASE   = Path(__file__).parent.parent
SS_DIR = BASE / "campaigns" / "screenshots"
PORT   = 8899
CARD_W = 260
MAX_H  = 2400

SLUG = {
    # Welcome Series
    "RexA77": "klv-flow-flow-welcome-series-t01-RexA77",
    "VmM9pi": "klv-flow-flow-welcome-series-t02-VmM9pi",
    "U7K4a4": "klv-flow-flow-welcome-series-t03-U7K4a4",
    "YeYBsf": "klv-flow-flow-welcome-series-t04-YeYBsf",
    "Yamm6R": "klv-flow-flow-welcome-series-t05-Yamm6R",
    "YjHZ4R": "klv-flow-flow-welcome-series-t06-YjHZ4R",
    "VcTHRZ": "klv-flow-flow-welcome-series-t07-VcTHRZ",
    "SGJpcT": "klv-flow-flow-welcome-series-t08-SGJpcT",
    "S3GkrK": "klv-flow-flow-welcome-series-t09-S3GkrK",
    "Rwv4fe": "klv-flow-flow-welcome-series-t10-Rwv4fe",
    "TgTVBc": "klv-flow-flow-welcome-series-t11-TgTVBc",
    "VJX7Vb": "klv-flow-flow-welcome-series-t12-VJX7Vb",
    "QZBWMT": "klv-flow-flow-welcome-series-t13-QZBWMT",
    "Y4jugu": "klv-flow-flow-welcome-series-t14-Y4jugu",
    # Trade Welcome June 2026
    "Tmjisd": "klv-flow-trade_program-welcome-june2026-t01-Tmjisd",
    "SDEZuc": "klv-flow-trade_program-welcome-june2026-t02-SDEZuc",
    "RW2Gwb": "klv-flow-trade_program-welcome-june2026-t05-RW2Gwb",
    "RiZDTy": "klv-flow-trade_program-welcome-june2026-t06-RiZDTy",
    "Renpya": "klv-flow-trade_program-welcome-june2026-t07-Renpya",
    "VmBWQm": "klv-flow-trade_program-welcome-june2026-t08-VmBWQm",
    "Wx2MJd": "klv-flow-trade_program-welcome-june2026-t09-Wx2MJd",
    "UDXDSk": "klv-flow-trade_program-welcome-june2026-t10-UDXDSk",
    "XBNngF": "klv-flow-trade_program-welcome-june2026-t11-XBNngF",
    # Trade Welcome July 2025
    "W3GLND": "klv-flow-trade_program-welcome-july2025-t01-W3GLND",
    "RKcGPE": "klv-flow-trade_program-welcome-july2025-t02-RKcGPE",
    "REzsug": "klv-flow-trade_program-welcome-july2025-t03-REzsug",
    "S3GJ4H": "klv-flow-trade_program-welcome-july2025-t04-S3GJ4H",
    "Xb6BxY": "klv-flow-trade_program-welcome-july2025-t05-Xb6BxY",
    "RHbGF9": "klv-flow-trade_program-welcome-july2025-t06-RHbGF9",
    "XCR9tP": "klv-flow-trade_program-welcome-july2025-t07-XCR9tP",
    "WDijgA": "klv-flow-trade_program-welcome-july2025-t08-WDijgA",
    "W3ugDD": "klv-flow-trade_program-welcome-july2025-t09-W3ugDD",
    # Trade Post-Purchase
    "Vhpnpq": "klv-flow-flow-sr_post-purchase_trade-t01-Vhpnpq",
    "WsNdhg": "klv-flow-flow-sr_post-purchase_trade-t02-WsNdhg",
    "XCd4b8": "klv-flow-flow-sr_post-purchase_trade-t03-XCd4b8",
    "UEyjbw": "klv-flow-flow-sr_post-purchase_trade-t05-UEyjbw",
    # Browse Abandonment
    "Tb2443": "klv-flow-flow-sh_abandoned-browse2-t01-Tb2443",
    # Create Account
    "QTWspr": "klv-flow-flow-co_create-account-t01-QTWspr",
    "T9nd5j": "klv-flow-flow-co_create-account-t02-T9nd5j",
    "YwDRAL": "klv-flow-flow-co_create-account-t03-YwDRAL",
    # Cart Abandonment
    "SQvLwU": "klv-flow-flow-sh_abandoned-cart2-t01-SQvLwU",
    "VbjsiC": "klv-flow-flow-sh_abandoned-cart2-t02-VbjsiC",
    # Post-Consultation
    "TjbnSg": "klv-flow-flow-co_post-consultation_ecom-t01-TjbnSg",
    "SJLAsw": "klv-flow-flow-co_post-consultation_ecom-t02-SJLAsw",
    "Xf9rja": "klv-flow-flow-co_post-consultation_ecom-t03-Xf9rja",
    "UdgGBM": "klv-flow-flow-co_post-consultation_ecom-t04-UdgGBM",
    "Su5ZfP": "klv-flow-flow-co_post-consultation_ecom-t05-Su5ZfP",
    "R9HdBK": "klv-flow-flow-co_post-consultation_ecom-t06-R9HdBK",
    "VX4PHP": "klv-flow-flow-co_post-consultation_ecom-t07-VX4PHP",
}

# Cache autocropped images in memory
_cache = {}


def autocrop(path, pad=2):
    img = Image.open(path).convert("RGBA")
    bg = img.getpixel((0, 0))
    pix = img.load()
    w, h = img.size
    top    = next((y for y in range(h)         for x in range(w) if pix[x, y][:3] != bg[:3]), 0)
    bottom = next((y for y in range(h-1,-1,-1) for x in range(w) if pix[x, y][:3] != bg[:3]), h)
    left   = next((x for x in range(w)         for y in range(h) if pix[x, y][:3] != bg[:3]), 0)
    right  = next((x for x in range(w-1,-1,-1) for y in range(h) if pix[x, y][:3] != bg[:3]), w)
    return img.crop((max(0, left-pad), max(0, top-pad), min(w, right+pad), min(h, bottom+pad)))


def get_png_bytes(msg_id):
    if msg_id in _cache:
        return _cache[msg_id]

    slug = SLUG.get(msg_id)
    if not slug:
        return None
    src = SS_DIR / f"{slug}.png"
    if not src.exists():
        return None

    cropped = autocrop(src)
    cw, ch = cropped.size

    # Cap height
    max_src_h = round(MAX_H * cw / CARD_W)
    if ch > max_src_h:
        cropped = cropped.crop((0, 0, cw, max_src_h))

    buf = io.BytesIO()
    cropped.save(buf, "PNG")
    data = buf.getvalue()
    _cache[msg_id] = data
    return data


class Handler(BaseHTTPRequestHandler):
    def log_message(self, fmt, *args):
        print(f"  {self.address_string()} {fmt % args}")

    def do_OPTIONS(self):
        self.send_response(200)
        self.send_header("Access-Control-Allow-Origin", "*")
        self.send_header("Access-Control-Allow-Methods", "GET, OPTIONS")
        self.end_headers()

    def do_GET(self):
        path = self.path.lstrip("/")
        if not path.endswith(".png"):
            self.send_response(404)
            self.end_headers()
            return

        msg_id = path[:-4]  # strip .png
        data = get_png_bytes(msg_id)

        if data is None:
            self.send_response(404)
            self.end_headers()
            self.wfile.write(f"Not found: {msg_id}".encode())
            return

        self.send_response(200)
        self.send_header("Content-Type", "image/png")
        self.send_header("Content-Length", str(len(data)))
        self.send_header("Access-Control-Allow-Origin", "*")
        self.end_headers()
        self.wfile.write(data)


if __name__ == "__main__":
    print(f"TE Screenshot Server starting on http://localhost:{PORT}")
    print(f"Serving {len(SLUG)} autocropped email screenshots")
    print("Stop with Ctrl+C\n")
    server = HTTPServer(("localhost", PORT), Handler)
    try:
        server.serve_forever()
    except KeyboardInterrupt:
        print("\nStopped.")
