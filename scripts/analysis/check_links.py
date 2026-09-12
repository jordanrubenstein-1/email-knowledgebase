"""
Check TI and SF links for liveness and compare against existing guide.
"""

import csv
import requests
import concurrent.futures
from pathlib import Path

HEADERS = {
    "User-Agent": (
        "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) "
        "AppleWebKit/537.36 (KHTML, like Gecko) "
        "Chrome/120.0.0.0 Safari/537.36"
    )
}


def check_url(name_url: tuple) -> dict:
    name, url = name_url
    url = url.strip()
    try:
        r = requests.get(url, headers=HEADERS, timeout=10, allow_redirects=True)
        return {"name": name, "url": url, "status": r.status_code, "live": r.status_code < 400}
    except Exception as e:
        return {"name": name, "url": url, "status": f"ERROR: {e}", "live": False}


def load_csv(path: str, name_col: int = 0, url_col: int = 1, skip_header: bool = True):
    rows = []
    with open(path, newline="", encoding="utf-8") as f:
        reader = csv.reader(f)
        for i, row in enumerate(reader):
            if i == 0 and skip_header:
                continue
            if len(row) > url_col and row[url_col].strip().startswith("http"):
                rows.append((row[name_col].strip(), row[url_col].strip()))
    return rows


def normalize_url(url: str) -> str:
    """Strip www. for comparison."""
    return url.replace("https://www.", "https://").rstrip("/")


# ── Load CSVs ────────────────────────────────────────────────────────────────
ti_links = load_csv("/Users/jordan.rubenstein/Downloads/TI Collection Pages - Sheet1.csv")
sf_links = load_csv("/Users/jordan.rubenstein/Downloads/SF Collection Pages - Sheet1.csv")

print(f"TI links: {len(ti_links)}")
print(f"SF links: {len(sf_links)}")

# ── Load existing guide URLs ─────────────────────────────────────────────────
guide_path = Path("/Users/jordan.rubenstein/Downloads/email-knowledgebase/email-knowledgebase/reports/email-link-guide.md")
guide_text = guide_path.read_text()
existing_urls = set()
for line in guide_text.splitlines():
    for part in line.split("`"):
        if part.startswith("https://"):
            existing_urls.add(normalize_url(part))

print(f"Existing guide URLs: {len(existing_urls)}")

# ── Check all TI links ───────────────────────────────────────────────────────
print("\n=== Checking TI links ===")
with concurrent.futures.ThreadPoolExecutor(max_workers=20) as pool:
    ti_results = list(pool.map(check_url, ti_links))

# ── Check all SF links ───────────────────────────────────────────────────────
print("=== Checking SF links ===")
with concurrent.futures.ThreadPoolExecutor(max_workers=20) as pool:
    sf_results = list(pool.map(check_url, sf_links))

# ── Report ───────────────────────────────────────────────────────────────────
def report(results, label):
    live = [r for r in results if r["live"]]
    dead = [r for r in results if not r["live"]]
    print(f"\n── {label} ──")
    print(f"  Live:  {len(live)}")
    print(f"  Dead:  {len(dead)}")
    if dead:
        for r in dead:
            print(f"    ✗ [{r['status']}] {r['name']} → {r['url']}")

report(ti_results, "TI")
report(sf_results, "SF")

# ── New SF links (live, not already in guide) ────────────────────────────────
print("\n=== SF links NOT in existing guide (live only) ===")
new_sf = []
for r in sf_results:
    if r["live"] and normalize_url(r["url"]) not in existing_urls:
        new_sf.append(r)
print(f"  New live SF links: {len(new_sf)}")
for r in new_sf:
    print(f"  + {r['name']}: {r['url']}")

# ── Write results to file ────────────────────────────────────────────────────
out = Path("/Users/jordan.rubenstein/Downloads/email-knowledgebase/email-knowledgebase/scripts/analysis/link_check_results.txt")
lines = []

lines.append("=== TI RESULTS ===")
for r in ti_results:
    status = "LIVE" if r["live"] else f"DEAD ({r['status']})"
    lines.append(f"  [{status}] {r['name']}: {r['url']}")

lines.append("\n=== SF DEAD LINKS ===")
for r in sf_results:
    if not r["live"]:
        lines.append(f"  [{r['status']}] {r['name']}: {r['url']}")

lines.append("\n=== SF NEW LIVE LINKS (not in existing guide) ===")
for r in new_sf:
    lines.append(f"  {r['name']}: {r['url']}")

out.write_text("\n".join(lines))
print(f"\nResults written to {out}")
