#!/usr/bin/env python3
"""
One-off script: patch Figma template field into June 2026 HAV email Asana tasks.
Only updates the Figma line — does not touch any other field, date, or content.

Designed emails only (Type = Batch & Blast). Skips PT, Push, SMS.
"""

import os
import re
import sys
import time
import html as _html
from typing import Optional, Dict

import requests

# ── env ────────────────────────────────────────────────────────────────────────
_env_path = os.path.join(os.path.dirname(__file__), "..", ".env")
if os.path.exists(_env_path):
    with open(_env_path) as _f:
        for _line in _f:
            _line = _line.strip()
            if "=" in _line and not _line.startswith("#"):
                _k, _v = _line.split("=", 1)
                os.environ.setdefault(_k.strip(), _v.strip().strip('"').strip("'"))

ASANA_TOKEN = os.environ.get("ASANA_ACCESS_TOKEN", "")
if not ASANA_TOKEN:
    sys.exit("ASANA_ACCESS_TOKEN not set")

ASANA_BASE = "https://app.asana.com/api/1.0"
HEADERS = {"Authorization": f"Bearer {ASANA_TOKEN}", "Accept": "application/json"}

# ── Asana GIDs ─────────────────────────────────────────────────────────────────
ASANA_PROJECT_GID = "1207522423363072"  # Master CRM
FIELD_BRAND = "1207522425689880"
BRAND_HAV = "1207522425689881"
FIELD_CHANNEL = "1207562370794988"
CHANNEL_EMAIL = "1207562370794989"
FIELD_TYPE = "1207522425689987"
TYPE_BATCH_BLAST = "1209982215610998"
TYPE_PT = "1207522425689988"

# ── HAV Figma constants (inlined to avoid heavy create_calendar_tasks import) ──
HAV_FIGMA_FILE_KEY = "CgGj7mTdp9SSj975u2mP4F"
HAV_FIGMA_TEMPLATES: Dict[str, Dict] = {
    "theme_01":     {"node_id": "12:312", "name": "Theme 01"},
    "gif_body":     {"node_id": "7:36",   "name": "Gif + Body"},
    "style_feature":{"node_id": "12:920", "name": "Style Feature"},
    "this_or_that": {"node_id": "14:76",  "name": "This or That"},
    "why_havenly":  {"node_id": "15:211", "name": "Why Havenly"},
    "ai":           {"node_id": "44:55",  "name": "AI"},
}
HAV_FIGMA_KICKERS: Dict[str, Dict] = {
    "5_stars":       {"node_id": "15:212", "name": "5 Stars 01"},
    "categories":    {"node_id": "17:384", "name": "Categories"},
    "b_partners":    {"node_id": "17:402", "name": "B. Partners"},
    "dps_kicker":    {"node_id": "9:240",  "name": "DPS Kicker"},
    "mp_kicker":     {"node_id": "9:244",  "name": "MP Kicker"},
    "havenly_ai":    {"node_id": "18:688", "name": "Havenly AI"},
    "value_prop_dps":{"node_id": "20:1037","name": "HAV Value Prop DPS"},
}


def _figma_url(node_id: str) -> str:
    return (
        f"https://www.figma.com/design/{HAV_FIGMA_FILE_KEY}"
        f"/Havenly-Lifecycle-Templates?node-id={node_id.replace(':', '-')}&m=dev"
    )


def pick_template_rule_based(story: str, audience: str) -> Dict:
    """Rule-based HAV template + kicker selection from task name."""
    s = story.lower()

    # Template
    if any(x in s for x in ["before and after", "room transformation"]):
        t_key = "gif_body"
    elif any(x in s for x in ["why havenly", "how it works"]):
        t_key = "why_havenly"
    elif any(x in s for x in ["this or that"]):
        t_key = "this_or_that"
    elif s.strip() == "ai" or any(x in s for x in ["havenly ai", "ai 1", "ai living", "ai feature", " ai "]):
        t_key = "ai"
    elif any(x in s for x in ["nancy meyers", "designer feature", "lauren andresky",
                                "style feature", "moodboard", "rugs", "outdoor living",
                                "earth tones", "curated"]):
        t_key = "style_feature"
    else:
        t_key = "theme_01"  # editorial, blog, sale

    t = HAV_FIGMA_TEMPLATES[t_key]
    result = {
        "template_key": t_key,
        "template_name": t["name"],
        "figma_url": _figma_url(t["node_id"]),
    }

    # Kicker — AI template (hero-only) always needs one; everything else stands alone
    if t_key == "ai":
        k_key = "dps_kicker" if audience == "DPS" else "5_stars"
        k = HAV_FIGMA_KICKERS[k_key]
        result["kicker_name"] = k["name"]
        result["kicker_figma_url"] = _figma_url(k["node_id"])

    return result


# ── Asana helpers ──────────────────────────────────────────────────────────────

def fetch_hav_email_tasks_june() -> list:
    """Page through Master CRM and return HAV email tasks due in May-30 to June 2026."""
    tasks = []
    url = f"{ASANA_BASE}/tasks"
    params = {
        "project": ASANA_PROJECT_GID,
        "opt_fields": "gid,name,due_on,custom_fields",
        "limit": 100,
    }
    while True:
        r = requests.get(url, headers=HEADERS, params=params)
        r.raise_for_status()
        data = r.json()
        for t in data.get("data", []):
            due = t.get("due_on", "") or ""
            if not (due >= "2026-05-28" and due <= "2026-07-01"):
                continue
            cf = {f["gid"]: f for f in t.get("custom_fields", [])}
            brand_val = ((cf.get(FIELD_BRAND) or {}).get("enum_value") or {}).get("gid", "")
            if brand_val != BRAND_HAV:
                continue
            chan_val = ((cf.get(FIELD_CHANNEL) or {}).get("enum_value") or {}).get("gid", "")
            if chan_val != CHANNEL_EMAIL:
                continue
            tasks.append(t)
        nxt = data.get("next_page")
        if nxt and nxt.get("offset"):
            params["offset"] = nxt["offset"]
        else:
            break
    return tasks


def get_task_type(task: dict) -> str:
    cf = {f["gid"]: f for f in task.get("custom_fields", [])}
    type_val = ((cf.get(FIELD_TYPE) or {}).get("enum_value") or {}).get("gid", "")
    if type_val == TYPE_BATCH_BLAST:
        return "batch_blast"
    if type_val == TYPE_PT:
        return "pt"
    return "other"


def get_html_notes(gid: str) -> str:
    r = requests.get(f"{ASANA_BASE}/tasks/{gid}", headers=HEADERS,
                     params={"opt_fields": "html_notes"})
    r.raise_for_status()
    return r.json().get("data", {}).get("html_notes", "") or ""


def infer_audience(name: str) -> str:
    if name.startswith("DPS and MP:") or name.startswith("DPS and MP "):
        return "both"
    if name.startswith("DPS:") or name.startswith("DPS "):
        return "DPS"
    if name.startswith("MP:") or name.startswith("MP "):
        return "MP"
    return ""


def story_from_name(name: str) -> str:
    for prefix in ("DPS and MP: ", "DPS: ", "MP: "):
        if name.startswith(prefix):
            return name[len(prefix):]
    return name


def _href(url: str) -> str:
    """Build an <a> tag with & properly escaped for XML/HTML."""
    href_url = url.replace("&", "&amp;")
    return f'<a href="{href_url}">{url}</a>'


def build_figma_li(template: dict) -> str:
    """Build replacement for the existing <li><strong>Figma:</strong>...</li>.

    Returns one or two <li> entries (template + optional kicker).
    Asana's html_notes is strict XML — no <br> tags, & must be &amp; in hrefs.
    """
    t_name = _html.escape(template["template_name"])
    result = f"<li><strong>Figma:</strong> {t_name} — {_href(template['figma_url'])}</li>"

    k_name = template.get("kicker_name", "")
    k_url = template.get("kicker_figma_url", "")
    if k_name:
        k_esc = _html.escape(k_name)
        result += f"<li>Kicker: {k_esc} — {_href(k_url)}</li>"

    return result


def inject_figma(html_notes: str, figma_li: str) -> str:
    """Replace existing Figma <li> or insert it after LP / Creative Direction."""
    figma_re = re.compile(r'<li><strong>Figma:</strong>.*?</li>', re.DOTALL | re.IGNORECASE)
    if figma_re.search(html_notes):
        return figma_re.sub(figma_li, html_notes, count=1)

    lp_re = re.compile(r'(<li><strong>LP:</strong>.*?</li>)', re.DOTALL | re.IGNORECASE)
    if lp_re.search(html_notes):
        return lp_re.sub(r'\1\n' + figma_li, html_notes, count=1)

    cd_re = re.compile(r'(<li><strong>Creative Direction:</strong>.*?</li>)', re.DOTALL | re.IGNORECASE)
    if cd_re.search(html_notes):
        return cd_re.sub(r'\1\n' + figma_li, html_notes, count=1)

    sl_re = re.compile(r'(<li><strong>SL/PH)', re.IGNORECASE)
    if sl_re.search(html_notes):
        return sl_re.sub(figma_li + '\n' + r'\1', html_notes, count=1)

    if "</body>" in html_notes:
        return html_notes.replace("</body>", figma_li + "</body>", 1)
    return html_notes + figma_li


# ── main ───────────────────────────────────────────────────────────────────────

def main(dry_run: bool = False):
    print("Fetching June 2026 HAV email tasks...")
    tasks = fetch_hav_email_tasks_june()
    print(f"Found {len(tasks)} HAV email tasks (May 28 – Jun 30)")

    designed = [t for t in tasks if get_task_type(t) == "batch_blast"]
    print(f"{len(designed)} are Batch & Blast (designed) — will patch Figma field\n")

    success = 0
    skipped = 0
    errors = []

    for t in designed:
        gid = t["gid"]
        name = t["name"]
        due = t.get("due_on", "")
        audience = infer_audience(name)
        story = story_from_name(name)

        template = pick_template_rule_based(story, audience)
        print(f"  [{due}] {name}")
        print(f"    → {template['template_name']}"
              + (f" + {template['kicker_name']}" if template.get("kicker_name") else ""))

        if dry_run:
            skipped += 1
            continue

        try:
            html_notes = get_html_notes(gid)
        except Exception as e:
            print(f"    ✗ fetch html_notes failed: {e}")
            errors.append(gid)
            time.sleep(0.5)
            continue

        figma_li = build_figma_li(template)
        new_notes = inject_figma(html_notes, figma_li)

        if new_notes == html_notes:
            print(f"    ⚠ no change (injection had no effect)")
            skipped += 1
            time.sleep(0.3)
            continue

        try:
            r = requests.put(
                f"{ASANA_BASE}/tasks/{gid}",
                headers=HEADERS,
                json={"data": {"html_notes": new_notes}},
            )
            r.raise_for_status()
            print(f"    ✓ Updated")
            success += 1
        except Exception as e:
            print(f"    ✗ PUT failed: {e}")
            errors.append(gid)

        time.sleep(0.4)

    print(f"\nDone. {success} updated, {skipped} skipped, {len(errors)} errors")
    if errors:
        print(f"Error GIDs: {errors}")


if __name__ == "__main__":
    dry = "--dry-run" in sys.argv
    if dry:
        print("DRY RUN — no changes will be written\n")
    main(dry_run=dry)
