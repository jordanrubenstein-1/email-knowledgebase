#!/usr/bin/env python3
"""
figma_to_braze_email.py

Takes a Figma email design and creates a Braze email template from image slices.

Exports SLICE nodes and component FRAME nodes from a Figma email frame,
downloads them as PNGs, uploads to Braze media library, and creates a template.

Usage:
    uv run python scripts/figma_to_braze_email.py \\
        --figma-url "https://www.figma.com/design/GTvWfOQZMlk7sLPl5Hqu1g/...?node-id=391-69" \\
        --template-name "P_EM_2026_05_21_BW_D_Nomad_New_Fabrics" \\
        --brand BUR \\
        --subject "Introducing Nomad in New Fabrics"

    # Dry run — download images and show HTML without uploading or creating template
    uv run python scripts/figma_to_braze_email.py ... --dry-run

    # List email frames on the Email page without exporting
    uv run python scripts/figma_to_braze_email.py \\
        --figma-url "https://www.figma.com/design/GTvWfOQZMlk7sLPl5Hqu1g/..." \\
        --list-frames
"""

import argparse
import os
import re
import sys
from pathlib import Path
from typing import Optional

import requests
from dotenv import load_dotenv

load_dotenv(Path(__file__).parent.parent / ".env")

FIGMA_TOKEN = os.getenv("FIGMA_ACCESS_TOKEN")
BRAZE_BASE_URL = os.getenv("BRAZE_BASE_URL", "https://rest.iad-07.braze.com").rstrip("/")

FIGMA_EMAIL_WIDTH = 900   # Figma designs are 900px wide
EMAIL_DISPLAY_WIDTH = 600  # Standard email display width


def parse_figma_url(url: str):
    file_match = re.search(r"figma\.com/(?:design|file)/([A-Za-z0-9]+)", url)
    if not file_match:
        raise ValueError(f"Cannot parse Figma file key from URL: {url}")
    file_key = file_match.group(1)
    node_match = re.search(r"node-id=([0-9]+)[:\-]([0-9]+)", url)
    node_id = f"{node_match.group(1)}:{node_match.group(2)}" if node_match else None
    return file_key, node_id


def figma_get(path: str, params: dict = None):
    resp = requests.get(
        f"https://api.figma.com/v1{path}",
        headers={"X-Figma-Token": FIGMA_TOKEN},
        params=params or {},
        timeout=60,
    )
    resp.raise_for_status()
    return resp.json()


def get_node(file_key: str, node_id: str):
    data = figma_get(f"/files/{file_key}/nodes", {"ids": node_id, "depth": 2})
    return data["nodes"][node_id]["document"]


def list_email_page_frames(file_key: str):
    """Return all top-level FRAME children from every page named 'Email'."""
    data = figma_get(f"/files/{file_key}", {"depth": 1})
    frames = []
    for page in data["document"]["children"]:
        if page["name"].lower() == "email":
            page_data = figma_get(f"/files/{file_key}/nodes", {"ids": page["id"], "depth": 2})
            page_doc = page_data["nodes"][page["id"]]["document"]
            for child in page_doc.get("children", []):
                if child["type"] == "FRAME":
                    bb = child.get("absoluteBoundingBox", {})
                    frames.append({
                        "id": child["id"],
                        "name": child["name"],
                        "w": bb.get("width", 0),
                        "h": bb.get("height", 0),
                    })
    return frames


def collect_export_rows(node: dict):
    """
    Walk direct children and collect SLICE and FRAME nodes sorted by Y position.
    Groups into rows: elements within 5px of each other vertically share a row.
    FRAME nodes at the same Y as a SLICE are skipped (SLICE takes precedence).
    """
    children = node.get("children", [])
    slices = [c for c in children if c["type"] == "SLICE"]
    slice_ys = set()
    for s in slices:
        bb = s.get("absoluteBoundingBox", {})
        slice_ys.add(round(bb.get("y", 0)))

    exportable = []
    for child in children:
        t = child["type"]
        if t not in ("SLICE", "FRAME"):
            continue
        bb = child.get("absoluteBoundingBox", {})
        y = round(bb.get("y", 0))
        if t == "FRAME" and any(abs(y - sy) < 5 for sy in slice_ys):
            continue
        exportable.append(child)

    exportable.sort(key=lambda n: (
        n["absoluteBoundingBox"].get("y", 0),
        n["absoluteBoundingBox"].get("x", 0),
    ))

    rows = []
    i = 0
    while i < len(exportable):
        row = [exportable[i]]
        y0 = exportable[i]["absoluteBoundingBox"].get("y", 0)
        i += 1
        while i < len(exportable) and abs(exportable[i]["absoluteBoundingBox"].get("y", 0) - y0) < 5:
            row.append(exportable[i])
            i += 1
        rows.append(row)

    return rows


def export_frame_as_png(file_key: str, frame_node_id: str, scale: float = 2.0) -> str:
    """Export an entire frame as a single PNG. Returns the download URL."""
    data = figma_get(
        f"/images/{file_key}",
        {"ids": frame_node_id, "format": "png", "scale": scale},
    )
    url = data["images"].get(frame_node_id)
    if not url:
        raise ValueError(f"No image URL returned for frame {frame_node_id}")
    return url


def download_image(url: str, dest: Path):
    resp = requests.get(url, timeout=120)
    resp.raise_for_status()
    dest.write_bytes(resp.content)


def crop_slices(frame_png: Path, rows: list, frame_bb: dict, scale: float, out_dir: Path) -> dict:
    """
    Crop individual slice images from the full-frame PNG.
    Returns {node_id: local_path}.
    """
    from PIL import Image

    img = Image.open(frame_png)
    frame_x = frame_bb["x"]
    frame_y = frame_bb["y"]

    paths = {}
    for row in rows:
        for node in row:
            nid = node["id"]
            bb = node["absoluteBoundingBox"]
            # Convert absolute Figma coordinates to relative pixel coords in the PNG
            rel_x = round((bb["x"] - frame_x) * scale)
            rel_y = round((bb["y"] - frame_y) * scale)
            rel_w = round(bb["width"] * scale)
            rel_h = round(bb["height"] * scale)
            crop_box = (rel_x, rel_y, rel_x + rel_w, rel_y + rel_h)
            cropped = img.crop(crop_box)
            slug = slugify(node["name"])[:40]
            dest = out_dir / f"{slug}-{nid.replace(':', '_')}.png"
            cropped.save(dest, "PNG")
            paths[nid] = dest
    return paths


def upload_to_media_library(image_path: Path, brand: str = "BUR") -> Optional[str]:
    """Upload image to Braze media library via REST API. Returns CDN URL or None."""
    media_key = os.getenv(f"BRAZE_API_KEY_MEDIA_{brand.upper()}")
    if not media_key:
        raise ValueError(f"BRAZE_API_KEY_MEDIA_{brand.upper()} not set in .env")
    ext = image_path.suffix.lstrip(".")
    with open(image_path, "rb") as f:
        resp = requests.post(
            f"{BRAZE_BASE_URL}/media_library/create",
            headers={"Authorization": f"Bearer {media_key}"},
            files={"asset_file": (image_path.name, f, f"image/{ext}")},
            data={"name": image_path.name},
            timeout=60,
        )
    if not resp.ok:
        print(f"  [warn] upload failed ({resp.status_code}): {resp.text[:200]}")
        return None
    body = resp.json()
    assets = body.get("new_assets", [])
    return assets[0]["url"] if assets else None


def upload_images(local_paths: dict, brand: str = "BUR") -> dict:
    """Upload all images to Braze media library. Returns {node_id: cdn_url}."""
    results = {}
    for node_id, image_path in local_paths.items():
        print(f"  Uploading {image_path.name}...")
        cdn_url = upload_to_media_library(image_path, brand)
        if cdn_url:
            print(f"    → {cdn_url}")
        else:
            print(f"    [warn] no URL returned")
            cdn_url = ""
        results[node_id] = cdn_url
    return results


def generate_email_html(rows: list, image_url_map: dict) -> str:
    scale = EMAIL_DISPLAY_WIDTH / FIGMA_EMAIL_WIDTH  # 600/900

    # Each row gets its own table to avoid column-width sharing between
    # single-column and multi-column rows in email clients.
    tables = []
    for row in rows:
        if len(row) == 1:
            node = row[0]
            url = image_url_map.get(node["id"], "")
            bb = node["absoluteBoundingBox"]
            display_h = round(bb["height"] * scale)
            tables.append(
                f'<table width="{EMAIL_DISPLAY_WIDTH}" cellpadding="0" cellspacing="0" border="0"'
                f' style="margin:0 auto;font-size:0;">\n'
                f'  <tr>\n'
                f'    <td><img src="{url}" width="{EMAIL_DISPLAY_WIDTH}" height="{display_h}"'
                f' style="display:block;max-width:100%;border:0;" alt=""></td>\n'
                f'  </tr>\n'
                f'</table>'
            )
        else:
            col_w = EMAIL_DISPLAY_WIDTH // len(row)
            cells = []
            for node in sorted(row, key=lambda n: n["absoluteBoundingBox"].get("x", 0)):
                url = image_url_map.get(node["id"], "")
                bb = node["absoluteBoundingBox"]
                display_h = round(bb["height"] * scale)
                cells.append(
                    f'    <td width="{col_w}" style="font-size:0;line-height:0;">'
                    f'<img src="{url}" width="{col_w}" height="{display_h}"'
                    f' style="display:block;max-width:100%;border:0;" alt=""></td>'
                )
            tables.append(
                f'<table width="{EMAIL_DISPLAY_WIDTH}" cellpadding="0" cellspacing="0" border="0"'
                f' style="margin:0 auto;font-size:0;">\n'
                f'  <tr>\n' + "\n".join(cells) + '\n  </tr>\n'
                f'</table>'
            )

    body = "\n".join(tables)
    return (
        f'<!DOCTYPE html>\n<html lang="en">\n<head>\n'
        f'<meta charset="utf-8">\n'
        f'<meta name="viewport" content="width=device-width, initial-scale=1.0">\n'
        f'</head>\n'
        f'<body style="margin:0;padding:0;background:#ffffff;">\n'
        f'{body}\n'
        f'</body>\n</html>'
    )


def create_braze_template(template_name: str, subject: str, html_body: str, api_key: str) -> Optional[str]:
    resp = requests.post(
        f"{BRAZE_BASE_URL}/templates/email/create",
        headers={"Authorization": f"Bearer {api_key}", "Content-Type": "application/json"},
        json={"template_name": template_name, "subject": subject, "body": html_body},
        timeout=30,
    )
    if not resp.ok:
        print(f"Template creation failed ({resp.status_code}): {resp.text[:400]}")
        return None
    return resp.json().get("email_template_id")


def slugify(name: str) -> str:
    return re.sub(r"[^a-z0-9]+", "-", name.lower()).strip("-")


def main():
    parser = argparse.ArgumentParser(description="Export a Figma email frame to Braze as image slices.")
    parser.add_argument("--figma-url", required=True, help="Figma file URL (with node-id for specific frame)")
    parser.add_argument("--template-name", help="Braze template name (e.g. P_EM_2026_05_21_BW_D_Nomad_New_Fabrics)")
    parser.add_argument("--brand", default="BUR", help="Brand code (BUR, CZ, HAV, etc.)")
    parser.add_argument("--subject", default="", help="Email subject line")
    parser.add_argument("--scale", type=float, default=2.0, help="Image export scale (default 2.0 = 2x)")
    parser.add_argument("--dry-run", action="store_true", help="Download images and print HTML; skip upload + template creation")
    parser.add_argument("--list-frames", action="store_true", help="List email frames in the file and exit")
    parser.add_argument("--output-dir", help="Save exported images to this directory (default: temp dir)")
    args = parser.parse_args()

    if not FIGMA_TOKEN:
        print("Error: FIGMA_ACCESS_TOKEN not set in .env")
        sys.exit(1)

    file_key, node_id = parse_figma_url(args.figma_url)

    if args.list_frames:
        print(f"Fetching Email page frames from file {file_key}...")
        frames = list_email_page_frames(file_key)
        print(f"\nFound {len(frames)} email frames:\n")
        for f in frames:
            print(f"  [{f['id']}] {f['name']}  ({f['w']:.0f}x{f['h']:.0f})")
        return

    if not node_id:
        print("Error: no node-id in Figma URL. Use ?node-id=XXX-YYY or --list-frames to browse.")
        sys.exit(1)

    brand = args.brand.upper()
    api_key = os.getenv(f"BRAZE_API_KEY_{brand}") or os.getenv("BRAZE_API_KEY_ID")
    if not api_key:
        print(f"Error: BRAZE_API_KEY_{brand} not set in .env (needed for template creation)")
        sys.exit(1)

    print(f"Fetching Figma node {node_id} from file {file_key}...")
    node = get_node(file_key, node_id)
    print(f"Frame: {node['name']}")

    rows = collect_export_rows(node)
    all_nodes = [n for row in rows for n in row]
    print(f"\nFound {len(rows)} row(s), {len(all_nodes)} exportable node(s):")
    for i, row in enumerate(rows):
        if len(row) == 1:
            n = row[0]
            bb = n["absoluteBoundingBox"]
            print(f"  Row {i+1}: [{n['type']}] {n['name']}  {bb['width']:.0f}x{bb['height']:.0f}")
        else:
            print(f"  Row {i+1}: {len(row)}-column row")
            for n in row:
                bb = n["absoluteBoundingBox"]
                print(f"    [{n['type']}] {n['name']}  {bb['width']:.0f}x{bb['height']:.0f}")

    if not all_nodes:
        print("\nNo exportable nodes found. Add SLICE or named FRAME children to the email frame.")
        sys.exit(1)

    # Set up output directory
    if args.output_dir:
        out_dir = Path(args.output_dir)
        out_dir.mkdir(parents=True, exist_ok=True)
    else:
        import tempfile
        out_dir = Path(tempfile.mkdtemp(prefix="figma_email_"))

    print(f"\nExporting full frame at {args.scale}x scale...")
    frame_png_url = export_frame_as_png(file_key, node_id, scale=args.scale)
    frame_png = out_dir / "frame_full.png"
    print(f"Downloading full frame PNG...")
    download_image(frame_png_url, frame_png)
    print(f"  Saved to {frame_png}")

    frame_bb = node["absoluteBoundingBox"]
    print(f"\nCropping {len(all_nodes)} slice(s)...")
    local_paths = crop_slices(frame_png, rows, frame_bb, args.scale, out_dir)
    for nid, path in local_paths.items():
        print(f"  {path.name}")

    # Upload to Braze media library (or use placeholder URLs in dry-run)
    image_url_map = {}
    if args.dry_run:
        print("\n[dry-run] Skipping Braze media upload.")
        for nid, path in local_paths.items():
            image_url_map[nid] = f"file://{path}"
    else:
        print(f"\nUploading {len(local_paths)} image(s) to Braze media library...")
        image_url_map = upload_images(local_paths, brand)

    html = generate_email_html(rows, image_url_map)

    template_name = args.template_name or slugify(node["name"])
    subject = args.subject or template_name

    if args.dry_run:
        html_path = out_dir / "preview.html"
        html_path.write_text(html)
        print(f"\n[dry-run] HTML saved to: {html_path}")
        print(f"Images saved to: {out_dir}/")
        print(f"\nRows: {len(rows)}, Nodes: {len(all_nodes)}")
    else:
        print(f"\nCreating Braze template '{template_name}'...")
        template_id = create_braze_template(template_name, subject, html, api_key)
        if template_id:
            print(f"Template created: {template_id}")
            print(f"View at: {os.getenv('BRAZE_DASHBOARD_URL', 'https://dashboard-07.braze.com/')}engagement/templates/email/{template_id}")
        else:
            html_path = out_dir / "preview.html"
            html_path.write_text(html)
            print(f"Template creation failed. HTML saved to: {html_path}")


if __name__ == "__main__":
    main()
