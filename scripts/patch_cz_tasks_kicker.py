"""
One-off script: update 12 CZ Asana tasks (6/9+) to apply the 2026-06-09 kicker rules:
  - Remove "Link farm" from kicker sections
  - Add "Sale link farm header [IMAGE]" as the last delivered slice for sale-date tasks
  - Increment "Slices to deliver" count for sale tasks

Run: uv run python scripts/patch_cz_tasks_kicker.py [--dry-run]
"""

import os
import re
import sys
import time
import argparse
import requests
from dotenv import load_dotenv

load_dotenv()

ASANA_BASE_URL = "https://app.asana.com/api/1.0"


def asana_headers():
    token = os.environ.get("ASANA_ACCESS_TOKEN")
    if not token:
        print("Error: ASANA_ACCESS_TOKEN not set in .env")
        sys.exit(1)
    return {
        "Authorization": f"Bearer {token}",
        "Content-Type": "application/json",
        "Accept": "application/json",
    }


def asana_get(gid):
    resp = requests.get(
        f"{ASANA_BASE_URL}/tasks/{gid}",
        headers=asana_headers(),
        params={"opt_fields": "name,html_notes,due_on"},
    )
    if resp.status_code == 429:
        time.sleep(int(resp.headers.get("Retry-After", 30)))
        resp = requests.get(
            f"{ASANA_BASE_URL}/tasks/{gid}",
            headers=asana_headers(),
            params={"opt_fields": "name,html_notes,due_on"},
        )
    resp.raise_for_status()
    return resp.json()["data"]


def asana_update_html_notes(gid, html_notes, dry_run=False):
    if dry_run:
        print("  [DRY RUN] would update html_notes")
        return True
    resp = requests.put(
        f"{ASANA_BASE_URL}/tasks/{gid}",
        headers=asana_headers(),
        json={"data": {"html_notes": html_notes}},
    )
    if resp.status_code == 429:
        time.sleep(int(resp.headers.get("Retry-After", 30)))
        resp = requests.put(
            f"{ASANA_BASE_URL}/tasks/{gid}",
            headers=asana_headers(),
            json={"data": {"html_notes": html_notes}},
        )
    if resp.status_code not in (200, 201):
        print(f"  ERROR {resp.status_code}: {resp.text[:300]}")
        return False
    return True


def remove_link_farm(html: str) -> str:
    """Remove <li>Link farm...</li> items from the HTML."""
    return re.sub(r"<li>Link farm[^<]*</li>", "", html)


def add_sale_lf_header(html: str, lf_copy: str) -> str:
    """
    Append a Sale link farm header slice as the last item in the body copy ul,
    and increment the Slices to deliver count.
    """
    # Find the highest slice number already in the HTML
    slice_nums = [int(x) for x in re.findall(r"Slice (\d+)", html)]
    next_num = max(slice_nums) + 1 if slice_nums else 1

    # Increment Slices to deliver count (only if that line exists)
    html = re.sub(
        r"Slices to deliver: (\d+)",
        lambda m: f"Slices to deliver: {int(m.group(1)) + 1}",
        html,
    )

    # Build the new slice HTML
    import html as _html_mod
    safe_copy = _html_mod.escape(lf_copy, quote=False)
    new_slice = (
        f"<li>Slice {next_num} — Sale link farm header"
        f"<ul><li>{safe_copy}</li>"
        f"<li>Link: https://www.the-citizenry.com/</li></ul></li>"
    )

    # Insert before the last </ul></body>
    idx = html.rfind("</ul></body>")
    if idx == -1:
        print("  WARNING: could not find </ul></body> — appending to end of body")
        html = html.rstrip("</body>").rstrip() + new_slice + "</ul></body>"
    else:
        html = html[:idx] + new_slice + html[idx:]

    return html


# Task spec: (gid, remove_lf, add_sale_lf, lf_copy)
TASKS = [
    (
        "1213983391817474",
        True, False,
        None,
        "Style Guide: Entryway Styling",
    ),
    (
        "1213983434646767",
        False, True,
        "Summer Retreat Sale / [discount TBD]",
        "Archive Sale (6/12)",
    ),
    (
        "1213983389813075",
        False, True,
        "Summer Retreat Sale / [discount TBD]",
        "MTO Furniture (6/13)",
    ),
    (
        "1213983390190349",
        True, False,
        None,
        "Washable Rugs",
    ),
    (
        "1213983390147043",
        True, False,
        None,
        "Swatch Push",
    ),
    (
        "1213983390271753",
        True, True,
        "Fourth of July Event / [discount TBD]",
        "Back in Stock (6/23)",
    ),
    (
        "1213983390294886",
        False, True,
        "Fourth of July Event / [discount TBD]",
        "Archive Sale (6/25)",
    ),
    (
        "1213983416381627",
        True, True,
        "Fourth of July Event / [discount TBD]",
        "The Portugal Capsule",
    ),
    (
        "1213983390113299",
        True, True,
        "Fourth of July Event / [discount TBD]",
        "Celebrating Summer",
    ),
    (
        "1213983416161012",
        True, True,
        "Fourth of July Event / [discount TBD]",
        "Linen Bedding",
    ),
    (
        "1213983392124795",
        True, True,
        "Fourth of July Event / [discount TBD]",
        "Pillow Pairings",
    ),
    (
        "1213983415818736",
        True, False,
        None,
        "Hinoki Mirrors",
    ),
]


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--dry-run", action="store_true")
    args = parser.parse_args()
    dry_run = args.dry_run

    if dry_run:
        print("=== DRY RUN — no changes will be written ===\n")

    for gid, remove_lf, add_sale, lf_copy, label in TASKS:
        print(f"[{gid}] {label}")
        task = asana_get(gid)
        html = task.get("html_notes", "")

        if not html:
            print("  SKIP: no html_notes")
            continue

        original = html

        if remove_lf:
            if re.search(r"<li>Link farm", html):
                html = remove_link_farm(html)
                print("  ✓ removed link farm")
            else:
                print("  ~ no link farm found (skip remove)")

        if add_sale:
            if "Sale link farm header" in html:
                print("  ~ sale link farm header already present (skip add)")
            else:
                html = add_sale_lf_header(html, lf_copy)
                print(f"  ✓ added sale link farm header: {lf_copy!r}")

        if html == original:
            print("  = no changes needed")
            continue

        # Show a snippet of the modified kicker / end section for verification
        m = re.search(r"<li>Slice \d+ — Kicker.*?</li>", html, re.DOTALL)
        if m:
            print(f"  → kicker now: {m.group(0)[:150]}")
        m2 = re.search(r"<li>Slice \d+ — Sale link farm header.*?</li>", html, re.DOTALL)
        if m2:
            print(f"  → lf header: {m2.group(0)[:150]}")
        slices_m = re.search(r"Slices to deliver: \d+", html)
        if slices_m:
            print(f"  → {slices_m.group(0)}")

        ok = asana_update_html_notes(gid, html, dry_run=dry_run)
        if ok and not dry_run:
            print("  ✓ updated in Asana")
        time.sleep(0.3)

    print("\nDone.")


if __name__ == "__main__":
    main()
