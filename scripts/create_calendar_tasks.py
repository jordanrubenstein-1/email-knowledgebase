#!/usr/bin/env python3
"""
Create Asana tasks from the master marketing calendar Google Sheet.

Reads 5 tabs (HAV, CZ, ID+BUR, TI+SF, TRADE) and creates tasks in the
Master CRM (Email & SMS) project with correct custom fields.

Usage:
    # Preview all tasks
    uv run python scripts/create_calendar_tasks.py --dry-run

    # Preview one brand, one month
    uv run python scripts/create_calendar_tasks.py --dry-run --brand STF --month 3

    # Create tasks for real
    uv run python scripts/create_calendar_tasks.py --brand STF --month 3

    # Delete previously created tasks
    uv run python scripts/create_calendar_tasks.py --delete --brand STF --month 3
"""

import html as _html
import os
import sys
import argparse
import glob
import json
import random
import re
import time
from pathlib import Path
from datetime import datetime, timedelta
from typing import List, Dict, Any, Optional, Tuple

from dotenv import load_dotenv
import requests
import yaml

sys.path.insert(0, str(Path(__file__).parent))
from utils.resend_source import (  # noqa: E402
    RESEND_DIRECTION_PREFIX,
    detect_resend,
    find_resend_source,
    format_campaign_reference,
    normalize_resend_direction,
)

# Load .env from project root
load_dotenv(Path(__file__).parent.parent / ".env")

# ---------------------------------------------------------------------------
# Constants
# ---------------------------------------------------------------------------

SHEET_ID = "1S3YEx-f7aOTrqZgD4VUbQ7-XKunMIyUYkWJ2d1CGR4o"
ASANA_BASE_URL = "https://app.asana.com/api/1.0"
ASANA_PROJECT_GID = "1207522423363072"

MAPPING_FILE = Path(__file__).parent.parent / "data" / "calendar_task_mapping.yaml"
STF_PRODUCT_LOG_FILE = Path(__file__).parent.parent / "data" / "stf_product_suggestions_log.yaml"

# Asana custom field GIDs
FIELD_BRAND = "1207522425689880"
FIELD_CHANNEL = "1207562370794988"
FIELD_TYPE = "1207522425689987"
FIELD_TASK_STATUS = "1209982215610993"
FIELD_CATEGORY = "1207522425689885"
FIELD_SUBJECT_LINE = "1207522425689914"
FIELD_PRE_HEADER = "1207522425689916"
FIELD_TRADE_BRAND = "1210233166197147"   # "Trade Brand" — fill out when Brand=Trade
FIELD_AUDIENCE = "1207522425689896"      # Audience (HAV DPS/MP split)
FIELD_SEGMENT = "1211927654349290"       # Segment (Full File / Engaged)
FIELD_SEND_TIME = "1212524397761931"     # "Send time" text field (e.g. "4:00 PM")

# Trade Brand enum option GIDs
TRADE_BRAND_INTERIOR_DEFINE = "1210233166197148"

# Audience enum option GIDs (HAV)
AUDIENCE_PRE_CONVERTED = "1207522425689897"   # Pre-converted (DPS)
AUDIENCE_CUSTOMERS = "1207522425689898"       # Customers (MP)

# Segment enum option GIDs
SEGMENT_FULL_FILE = "1211927654349291"
SEGMENT_ENGAGED = "1211927654349292"

# Brand enum option GIDs
BRAND_OPTIONS = {
    "HAV": "1207522425689881",   # Havenly
    "CZ": "1207553690167887",    # The Citizenry
    "ID": "1207522425689882",    # Interior Define
    "BUR": "1208572919795447",   # Burrow
    "TI": "1207522425689883",    # The Inside
    "STF": "1207881071843537",   # St. Frank
    "TRADE": "1208130746998739", # Trade
}

# Channel: Email
CHANNEL_EMAIL = "1207562370794989"

# Type: Batch & Blast
TYPE_BATCH_BLAST = "1209982215610998"

# Task Status: Awaiting Design (Awaiting Creative)
STATUS_AWAITING_DESIGN = "1209982215610994"
# Task Status: Awaiting Copy
STATUS_AWAITING_COPY = "1213916481930051"

# Category enum option GIDs
CATEGORY_OPTIONS = {
    "sale_merch": "1207522425689886",      # Sale (Merchandise)
    "editorial": "1207522425689887",       # Editorial/Content
    "product_launch": "1207522425689888",  # New/Product Launch
    "product_category": "1207522425689889", # Product/Category
    "dps": "1207522425689891",             # DPS
    "trade": "1209467829907871",           # Trade
}

# Tab definitions: tab name → list of brand column configs
TAB_CONFIGS = {
    "HAV": [
        {
            "brand": "HAV",
            "date_col": 1,
            "day_col": 2,
            "story_col": 6,    # CONTENT
            "lp_col": None,
            "notes_col": None,
            "subject_col": 8,  # SL
            "preheader_col": 9, # PH
            "promo_col": 4,    # MKT PROMO
            "banners_col": 7,  # BANNERS
        }
    ],
    "CZ": [
        {
            "brand": "CZ",
            "date_col": 1,
            "day_col": 2,
            "story_col": 6,    # STORY
            "lp_col": 7,       # LP
            "notes_col": 9,    # NOTES
            "subject_col": None,
            "preheader_col": None,
        }
    ],
    "ID + BUR": [
        {
            "brand": "ID",
            "date_col": 1,
            "day_col": 2,
            "story_col": 8,    # STORY (ID section)
            "lp_col": 9,       # LANDING PAGE
            "notes_col": 11,   # NOTES
            "subject_col": None,
            "preheader_col": None,
        },
        {
            "brand": "BUR",
            "date_col": 1,     # Shared date column
            "day_col": 2,
            "story_col": 17,   # STORY (BUR section)
            "lp_col": 18,      # LANDING PAGE
            "notes_col": 20,   # NOTES
            "subject_col": None,
            "preheader_col": None,
        }
    ],
    "TI + SF": [
        {
            "brand": "TI",
            "date_col": 1,
            "day_col": 2,
            "story_col": 8,    # STORY (TI section)
            "lp_col": 9,       # LANDING PAGE
            "assets_col": 10,  # ASSETS (col K)
            "notes_col": 11,   # NOTES
            "subject_col": None,
            "preheader_col": None,
        },
        {
            "brand": "STF",
            "date_col": 1,     # Shared date column
            "day_col": 2,
            "story_col": 17,   # STORY (SF section)
            "lp_col": 18,      # LANDING PAGE
            "notes_col": 20,   # NOTES
            "subject_col": None,
            "preheader_col": None,
        }
    ],
    "TRADE": [
        {
            "brand": "TRADE",
            "date_col": 1,
            "day_col": 2,
            "brand_col": 3,    # TRADE tab has explicit brand column
            "story_col": 9,    # STORY
            "lp_col": 10,      # LANDING PAGE
            "notes_col": 12,   # NOTES
            "subject_col": None,
            "preheader_col": None,
        }
    ],
}

# Rows to skip — month markers, headers, empty placeholders
SKIP_PATTERNS = re.compile(
    r"^(january|february|march|april|may|june|july|august|september|"
    r"october|november|december|jan|feb|mar|apr|jun|jul|aug|sep|oct|nov|dec|"
    r"--|tbd|n/?a|week of|content|story|email type|date|day)$",
    re.IGNORECASE,
)


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def get_asana_token() -> str:
    token = os.environ.get("ASANA_ACCESS_TOKEN")
    if not token:
        print("Error: ASANA_ACCESS_TOKEN not set in .env")
        sys.exit(1)
    return token


def get_sheets_api_key() -> Optional[str]:
    return os.environ.get("GOOGLE_SHEETS_API_KEY")


def asana_headers() -> Dict[str, str]:
    return {
        "Authorization": f"Bearer {get_asana_token()}",
        "Content-Type": "application/json",
        "Accept": "application/json",
    }


def asana_request(method: str, endpoint: str, json_data: Optional[dict] = None,
                  params: Optional[dict] = None) -> Optional[dict]:
    """Make an Asana API request with rate-limit handling."""
    url = f"{ASANA_BASE_URL}/{endpoint}"
    resp = requests.request(method, url, headers=asana_headers(),
                            json=json_data, params=params)

    if resp.status_code == 429:
        retry_after = int(resp.headers.get("Retry-After", 30))
        print(f"  Rate limited — waiting {retry_after}s...")
        time.sleep(retry_after)
        resp = requests.request(method, url, headers=asana_headers(),
                                json=json_data, params=params)

    if resp.status_code not in (200, 201):
        print(f"  Asana error {resp.status_code}: {resp.text[:300]}")
        return None

    return resp.json().get("data")


def fetch_sheet_tab(tab_name: str) -> Tuple[List[List[str]], List[List[Dict[str, str]]]]:
    """Fetch all rows from a Google Sheet tab.

    Returns (rows, hyperlinks) where:
    - rows: list of row lists (cell display values)
    - hyperlinks: parallel list of row lists with {"text": ..., "link": ...} dicts
    """
    api_key = get_sheets_api_key()
    if not api_key:
        print("Error: GOOGLE_SHEETS_API_KEY not set in .env")
        print("Add your Google Sheets API key to .env:")
        print("  GOOGLE_SHEETS_API_KEY=your_key_here")
        sys.exit(1)

    range_name = requests.utils.quote(f"'{tab_name}'!A1:Z")

    # Fetch with includeGridData to get hyperlinks
    url = (
        f"https://sheets.googleapis.com/v4/spreadsheets/{SHEET_ID}"
        f"?key={api_key}&ranges={range_name}&includeGridData=true"
        f"&fields=sheets.data.rowData.values.hyperlink,"
        f"sheets.data.rowData.values.formattedValue,"
        f"sheets.data.rowData.values.textFormatRuns"
    )
    resp = requests.get(url)
    if resp.status_code != 200:
        print(f"Error fetching tab '{tab_name}': {resp.status_code} {resp.text[:200]}")
        return [], []

    rows = []
    hyperlinks = []
    data = resp.json()
    for row_data in (data.get("sheets", [{}])[0]
                     .get("data", [{}])[0]
                     .get("rowData", [])):
        vals = row_data.get("values", [])
        row = []
        row_links = []
        for v in vals:
            text = v.get("formattedValue", "")
            # Cell-level hyperlink
            link = v.get("hyperlink", "")
            # Also check for inline rich-text links in textFormatRuns
            inline_links = []
            for run in v.get("textFormatRuns", []):
                uri = run.get("format", {}).get("link", {}).get("uri", "")
                if uri:
                    inline_links.append(uri)
            row.append(text)
            row_links.append({
                "text": text,
                "link": link,
                "inline_links": inline_links,
            })
        rows.append(row)
        hyperlinks.append(row_links)

    return rows, hyperlinks


def parse_date_mmdd(date_str: str) -> Optional[str]:
    """Parse MM/DD date (no year) → YYYY-MM-DD.

    Jul-Dec → 2025, Jan-Jun → 2026.
    """
    if not date_str:
        return None
    date_str = str(date_str).strip()

    # Try MM/DD
    m = re.match(r"^(\d{1,2})/(\d{1,2})$", date_str)
    if not m:
        # Try MM/DD/YYYY or MM/DD/YY
        m2 = re.match(r"^(\d{1,2})/(\d{1,2})/(\d{2,4})$", date_str)
        if m2:
            month, day, year = int(m2.group(1)), int(m2.group(2)), int(m2.group(3))
            if year < 100:
                year += 2000
            try:
                return datetime(year, month, day).strftime("%Y-%m-%d")
            except ValueError:
                return None
        return None

    month, day = int(m.group(1)), int(m.group(2))
    year = 2025 if month >= 7 else 2026
    try:
        return datetime(year, month, day).strftime("%Y-%m-%d")
    except ValueError:
        return None


def cell(row: List[str], idx: Optional[int]) -> str:
    """Safely get a cell value from a row, returning empty string if missing."""
    if idx is None or idx >= len(row):
        return ""
    val = row[idx]
    if val is None:
        return ""
    return str(val).strip()


def should_skip_row(story: str) -> bool:
    """Return True if this row should be skipped (empty, placeholder, header)."""
    if not story:
        return True
    if SKIP_PATTERNS.match(story):
        return True
    # Skip very short non-word entries
    if len(story) <= 2 and not story.isalpha():
        return True
    return False


def infer_category(story: str, tab_name: str) -> str:
    """Infer category from task name keywords. Returns category key."""
    if tab_name == "TRADE":
        return "trade"

    lower = story.lower()

    # Sale / promo
    sale_kw = ["sale", "promo", "clearance", "% off", "bogo", "discount",
               "flash", "markdown", "save ", "savings"]
    if any(kw in lower for kw in sale_kw):
        return "sale_merch"

    # Product/category features — check before editorial so "feature" doesn't
    # accidentally match the editorial branch for "Category Feature: X" emails.
    # Keep this list specific; individual product words (pillow, wallpaper, etc.)
    # are too broad and cause false positives on editorial task names.
    product_cat_kw = ["category feature", "fabric by the yard", "fbty",
                      "surfboard", "skateboard"]
    if any(kw in lower for kw in product_cat_kw):
        return "product_category"

    # Editorial / content / story / pop culture / UGC
    editorial_kw = ["editorial", "destination", "insider report", "gift guide",
                    "style guide", "lookbook", "how to", "tips", "guide",
                    "story", "spotlight", "feature", "trend report",
                    "moodboard", "mood board", "oscars", "color edit",
                    "ugc", "user generated", "pop culture", "content",
                    "potm", "print of the month", "swatch push", "swatch talk"]
    if any(kw in lower for kw in editorial_kw):
        return "editorial"

    # New arrivals / product launch
    launch_kw = ["launch", "new arrival", "introducing", "just dropped",
                 "now available", "new collection", "debut", "new drop",
                 "newness"]
    if any(kw in lower for kw in launch_kw):
        return "product_launch"

    # DPS
    if "dps" in lower:
        return "dps"

    return "product_category"


# ---------------------------------------------------------------------------
# SL/PH generation via Claude API
# ---------------------------------------------------------------------------

# Cache: brand → list of {subject, preheader, category} from past campaigns
_brand_examples_cache: Dict[str, List[Dict[str, str]]] = {}

# Lazy-loaded sale schedules for during-sale detection
_sale_schedules_cache: Optional[List[Dict]] = None


def _get_sale_schedules() -> List[Dict]:
    global _sale_schedules_cache
    if _sale_schedules_cache is None:
        try:
            from scripts.utils.sale_matcher import load_sale_schedules
            _sale_schedules_cache = load_sale_schedules()
        except Exception:
            _sale_schedules_cache = []
    return _sale_schedules_cache

BRAND_FULL_NAMES = {
    "HAV": "Havenly",
    "CZ": "The Citizenry",
    "ID": "Interior Define",
    "BUR": "Burrow",
    "TI": "The Inside",
    "STF": "St. Frank",
    "TRADE": "Trade",
}

# CZ Figma template catalog — sourced from Figma MCP (file K043FA15z83zW2fhOkTH7J, section 824:974)
# Each entry: node_id, use_cases, slices (typed), auto_modules
# Slice types: "image" (AI-generated), "text" (copy-only, no image). Only "image" slices count
# toward Slices to deliver.
#
# Slice structure follows the 2026-06-05 CZ consolidation rules (see CLAUDE.md "CZ Email Slice
# Structure … — confirmed"): (1) Logo bar + Hero always merge into ONE slice; (2) adjacent slices
# that share the same destination link merge into that slice too. The sale banner, cycled kicker,
# and sale link-farm header are added at render time (build_html_notes) during an active sale —
# do NOT encode them as slices here (except Template F, whose hero is itself the archive-sale
# message and keeps an inline Sale banner slice that render special-cases).
# Reconciled 2026-07-20 to match the confirmed per-template spec. Regenerate the doc mirror with
# `uv run python scripts/generate_figma_templates_doc.py` after editing.
CZ_FIGMA_FILE_KEY = "K043FA15z83zW2fhOkTH7J"
CZ_FIGMA_TEMPLATES = {
    "A": {
        "name": "Multi-Hero",
        "node_id": "789:178",
        "use_cases": "MTO furniture, specific product feature (e.g. Potomac Bed), product launch, artisan story",
        "slices": [
            {"name": "Logo, hero, and sections", "type": "image", "fields": [
                "HED: [product or collection headline]",
                "Hero CTA: [link text beneath hero headline, e.g. 'Shop the Collection']",
                "Section 1 Visual: [describe the first image section]",
                "Section 1 DEK: [caption/narrative for first section]",
                "Section 2 Visual: [describe the second image section]",
                "Section 2 DEK: [caption/narrative for second section]",
                "Section 3 Visual: [describe the third image section]",
                "Section 3 DEK: [caption/narrative for third section]",
                "Section 3 CTA: [final section CTA text, if present]",
                "Link: [main LP]",
            ]},
        ],
        "auto_modules": ["One kicker (cycled — Swatches / New Arrivals / Fair Trade Guaranteed)"],
    },
    "B": {
        "name": "Product Feature Full Bleed",
        "node_id": "832:988",
        "use_cases": "sale last chance or reminder, gift guides, single strong product feature",
        "slices": [
            {"name": "Logo bar, eyebrow, and HED", "type": "image", "fields": [
                "Sale terms bar: [1-sentence urgency line under the logo, e.g. 'Hurry, up to 25% off ends at midnight.'] (optional — include only during an active sale)",
                "Eyebrow: [small label above hero, e.g. 'New Arrival' or 'Last Chance']",
                "HED: [product or sale headline — large display type over a full-bleed background]",
                "Link: [hero/sale LP]",
            ]},
            {"name": "Category 1 — full width", "type": "image", "fields": [
                "CTA: [category link text, e.g. 'Shop Rugs →']",
                "Link: [category page URL]",
            ]},
            {"name": "Category 2 — 50/50 left", "type": "image", "fields": [
                "Layout: 50/50 (paired with Category 3 in the same row)",
                "CTA: [category link text]",
                "Link: [category page URL]",
            ]},
            {"name": "Category 3 — 50/50 right", "type": "image", "fields": [
                "Layout: 50/50 (paired with Category 2 in the same row)",
                "CTA: [category link text]",
                "Link: [category page URL]",
            ]},
            {"name": "Category 4 — full width", "type": "image", "fields": [
                "CTA: [category link text]",
                "Link: [category page URL]",
            ]},
            {"name": "CTA over background image", "type": "image", "fields": [
                "CTA: [main button CTA text, e.g. 'Shop Up to 25% Off']",
                "Link: [hero/sale LP]",
            ]},
        ],
        "auto_modules": ["Built-in kicker (cycled — Archive Sale / New Arrivals / Back in Stock / Fair Trade Guaranteed)"],
    },
    "C": {
        "name": "Destination",
        "node_id": "789:240",
        "use_cases": "destination editorial, travel and culture storytelling (e.g. Kyoto, Japan)",
        "slices": [
            {"name": "Logo bar and hero", "type": "image", "fields": [
                "Eyebrow: [small label, e.g. 'Cities That Inspire']",
                "HED: [destination name, e.g. 'Kyoto, Japan']",
                "Hero CTA: [CTA button, e.g. 'Explore the Capsule']",
                "Link: [destination capsule LP]",
            ]},
            {"name": "Meet Us in [Destination]", "type": "image", "fields": [
                "Body HED: [section headline for the body narrative]",
                "Body DEK: [1–2 sentences about the destination and its connection to The Citizenry]",
                "Body CTA: [first CTA, e.g. 'Explore the Capsule']",
                "Final CTA: [dark full-bleed bottom banner CTA, e.g. 'The [Destination] Capsule >']",
                "Link: [destination capsule LP]",
            ]},
        ],
        "auto_modules": [],
    },
    "D": {
        "name": "Get the Look",
        "node_id": "789:412",
        "use_cases": "shop the look, styled room feature, bedding layers, pillow pairings, UGC, rugs",
        "slices": [
            {"name": "Logo, hero, and body copy", "type": "image", "fields": [
                "HED: [styled look name, e.g. 'the autumn LIVING ROOM']",
                "Hero CTA: [first CTA above the product grid]",
                "DEK: [1–2 sentence styling narrative]",
                "Link: [hero LP]",
            ]},
            {"name": "Product Image 1 — 50/50 left", "type": "image", "fields": [
                "Layout: 50/50 (paired with Product Image 2 in the same row)",
                "Name: [name of product shown in image 1]",
                "Link: [product page URL]",
            ]},
            {"name": "Product Image 2 — 50/50 right", "type": "image", "fields": [
                "Layout: 50/50 (paired with Product Image 1 in the same row)",
                "Name: [name of product shown in image 2]",
                "Link: [product page URL]",
            ]},
            {"name": "Product Image 3 — 50/50 left", "type": "image", "fields": [
                "Layout: 50/50 (paired with Product Image 4 in the same row)",
                "Name: [name of product shown in image 3]",
                "Link: [product page URL]",
            ]},
            {"name": "Product Image 4 — 50/50 right", "type": "image", "fields": [
                "Layout: 50/50 (paired with Product Image 3 in the same row)",
                "Name: [name of product shown in image 4]",
                "Link: [product page URL]",
            ]},
            {"name": "CTA button", "type": "image", "no_visual": True, "fields": [
                "CTA: [final button CTA text]",
                "Link: [hero LP]",
            ]},
        ],
        "auto_modules": ["YMAL"],
    },
    "E": {
        "name": "Color Edit",
        "node_id": "789:445",
        "use_cases": "color palette editorial, seasonal color story",
        "slices": [
            {"name": "Logo bar and hero", "type": "image", "fields": [
                "Eyebrow: Color Edit",
                "HED: [PALETTE NAME in all caps, e.g., 'GOLDEN HOUR']",
                "DEK: [2–3 palette keywords + a one-sentence mood line, e.g., 'Turmeric. Saffron. Mustard. The warm, golden hues to bring an instant mood boost.']",
                "Hero CTA: Shop the Edit",
                "Link: [color edit LP]",
            ]},
            {"name": "Color swatches + mosaic", "type": "image", "fields": [
                "Swatches: [color palette swatches row for the palette]",
                "Mosaic: [4–6 product/lifestyle shots from the palette — textiles, ceramics, art, rugs, accents — arranged as a mosaic grid]",
                "CTA: Shop the Edit",
                "Link: [color edit LP]",
            ]},
        ],
        "auto_modules": ["One kicker (cycled — Back in Stock / Swatches)"],
    },
    "F": {
        "name": "Archive Sale",
        "node_id": "789:527",
        "use_cases": "archive sale, clearance sale, end-of-season sale with new styles added",
        "slices": [
            {"name": "Logo, hero, body copy, photo grid, and CTA", "type": "image", "fields": [
                "Eyebrow: [small label, e.g. 'New Styles Added']",
                "HED: The Archive Sale",
                "Hero CTA: Shop up to 70% off  [FIXED — always 70% off, never use active promo discount]",
                "DEK: [1–2 sentences driving urgency, e.g. 'Last of the archive. Bring home the pieces you've had your eye on.']",
                "Body CTA: Shop Archive Sale",
                "Photo grid: [6 photos — row 1 (1 large left + 2 stacked right), row 2 (2 stacked left + 1 large right) — product/lifestyle shots from the archive]",
                "CTA button: Shop Archive Sale",
                "Link: https://www.the-citizenry.com/collections/archive-sale",
            ]},
        ],
        "auto_modules": ["50/50 New Arrivals + Back in Stock kicker (cycled — one variant)"],
    },
    "G": {
        "name": "Furniture by Room",
        "node_id": "789:579",
        "use_cases": "furniture by room, shop by room, UGC, rugs, MTO furniture",
        "slices": [
            {"name": "Logo bar, hero, and intro copy", "type": "image", "fields": [
                "HED: [e.g. 'Room by Room' or custom headline]",
                "Hero CTA: [main CTA above room sections]",
                "DEK: [1–2 sentence intro copy row]",
                "Link: [hero LP]",
            ]},
            {"name": "Category 1", "type": "image", "fields": [
                "HED: [category name, e.g. 'Bedroom']",
                "DEK: [1–2 sentences for this category]",
                "CTA: Shop Now >",
                "Link: [category 1 LP]",
            ]},
            {"name": "Category 2", "type": "image", "fields": [
                "HED: [category name, e.g. 'Living Room']",
                "DEK: [1–2 sentences for this category]",
                "CTA: Shop Now >",
                "Link: [category 2 LP]",
            ]},
            {"name": "Category 3", "type": "image", "fields": [
                "HED: [category name, e.g. 'Bath']",
                "DEK: [1–2 sentences for this category]",
                "CTA: Shop Now >",
                "Link: [category 3 LP]",
            ]},
            {"name": "Category 4", "type": "image", "fields": [
                "HED: [category name, e.g. 'Kitchen']",
                "DEK: [1–2 sentences for this category]",
                "CTA: Shop Now >",
                "Link: [category 4 LP]",
            ]},
            {"name": "CTA button", "type": "image", "no_visual": True, "fields": [
                "CTA: [e.g. 'Shop All Furniture']",
                "Link: [hero LP]",
            ]},
        ],
        "auto_modules": [],
    },
    "H": {
        "name": "Shop by Category",
        "node_id": "811:737",
        "use_cases": "sale launch, early access, sale reminder, last chance, bedding sale, shop by category",
        "slices": [
            {"name": "Logo and hero", "type": "image", "fields": [
                "HED: [sale event name or headline]",
                "Hero CTA: [main CTA button text]",
                "Link: [hero LP]",
            ]},
            {"name": "Category Block 1", "type": "image", "fields": [
                "Eyebrow: [discount or label, e.g. '25% OFF']",
                "HED: [category name, e.g. 'heirloom rugs']",
                "Link: [category page URL]",
            ]},
            {"name": "Category Block 2", "type": "image", "fields": [
                "Eyebrow: [discount or label]",
                "HED: [category name]",
                "Link: [category page URL]",
            ]},
            {"name": "Category Block 3", "type": "image", "fields": [
                "Eyebrow: [discount or label]",
                "HED: [category name]",
                "Link: [category page URL]",
            ]},
            {"name": "Category Block 4", "type": "image", "fields": [
                "Eyebrow: [discount or label]",
                "HED: [category name]",
                "Link: [category page URL]",
            ]},
            {"name": "Category Block 5", "type": "image", "fields": [
                "Eyebrow: [discount or label]",
                "HED: [category name]",
                "Link: [category page URL]",
            ]},
            {"name": "Category Block 6", "type": "image", "optional": True, "fields": [
                "Eyebrow: [discount or label] (optional)",
                "HED: [category name] (optional)",
                "Link: [category page URL] (optional)",
            ]},
        ],
        "auto_modules": ["YMAL"],
    },
    "I": {
        "name": "Rugs",
        "node_id": "811:800",
        "use_cases": "rugs feature, rug sale, rug-focused editorial",
        "slices": [
            {"name": "Logo bar, hero, and all content", "type": "image", "fields": [
                "Eyebrow: [small label, e.g. 'hand-woven']",
                "HED: [main headline, e.g. 'HEIRLOOMS']",
                "Hero CTA: [CTA text, e.g. 'Shop the Sale']",
                "Body DEK: [1–2 sentences about the rugs]",
                "Body CTA: [body section CTA text]",
                "Product grid: [rug product/lifestyle shots]",
                "Link: [rugs LP]",
            ]},
        ],
        "auto_modules": ["YMAL"],
    },
    "J": {
        "name": "Hero Only",
        "node_id": "824:975",
        "use_cases": "spring preview, collection launch, specific product feature, Meadow Press",
        "slices": [
            {"name": "Logo bar and hero", "type": "image", "fields": [
                "HED: [main headline]",
                "DEK: [1–2 sentence description]",
                "CTA: [button CTA text]",
                "Link: [hero LP]",
            ]},
        ],
        "auto_modules": ["YMAL"],
    },
    "K": {
        "name": "Back in Stock",
        "node_id": "876:1171",
        "use_cases": "back in stock announcement, restocked products",
        "slices": [
            {"name": "Logo bar and hero", "type": "image", "fields": [
                "HED: Back In Stock",
                "DEK: [1–2 sentences, e.g. 'Your favorite items are back…']",
                "Hero CTA: Shop Now",
                "Link: [hero LP / BIS LP]",
            ]},
        ],
        "auto_modules": ["One kicker (cycled — YMAL / Archive Sale / Fair Trade Guaranteed)"],
    },
    "L": {
        "name": "Monthly Edit",
        "node_id": "1363:434",
        "use_cases": "monthly edit, trend forecast, newsletter, seasonal recap",
        "slices": [
            {"name": "Logo bar and hero", "type": "image", "fields": [
                "Eyebrow: [volume/date label, e.g. 'VOL. / 05.26']",
                "HED: [e.g. 'THE MAY EDIT']",
                "DEK: [1–2 sentences setting the month's mood]",
                "CTA: [first CTA button text — ghost button]",
                "Link: [hero LP]",
            ]},
            {"name": "Section 1", "type": "image", "fields": [
                "Eyebrow: [section label, e.g. 'BACK IN STOCK']",
                "HED: [section headline, e.g. 'best-sellers']",
                "DEK: [1 sentence]",
                "CTA: [CTA text]",
                "Link: [relevant URL for this section — LP if it matches the content, else infer collection URL]",
            ]},
            {"name": "Section 2", "type": "image", "fields": [
                "Eyebrow: [section label, e.g. 'BEDDING SPOTLIGHT']",
                "HED: [section headline]",
                "DEK: [1 sentence]",
                "CTA: [CTA text]",
                "Link: [relevant URL for this section — LP if it matches the content, else infer collection URL]",
            ]},
            {"name": "Section 3", "type": "image", "fields": [
                "Eyebrow: [section label, e.g. 'TRAVEL SPOTLIGHT']",
                "HED: [section headline]",
                "DEK: [1 sentence]",
                "CTA: [CTA text]",
                "Link: [relevant URL for this section — LP if it matches the content, else infer collection URL]",
            ]},
        ],
        "auto_modules": ["Kicker 1 (cycled — Archive Sale / Fair Trade Guaranteed / New Arrivals / Back in Stock / Swatches)", "Kicker 3 (cycled — different from Kicker 1)"],
    },
    "M": {
        "name": "General Edit",
        "node_id": "1382:566",
        "use_cases": "The Spa Edit, bedding guide, bath essentials, shop by category editorial",
        "slices": [
            {"name": "Logo bar and hero", "type": "image", "fields": [
                "Eyebrow: [small label, e.g. 'Bath Essentials']",
                "HED: [e.g. 'THE SPA EDIT']",
                "DEK: [1–2 sentences about the category edit]",
                "CTA: [CTA button text]",
                "Link: [hero LP]",
            ]},
            {"name": "Category 1 — full width", "type": "image", "fields": [
                "CTA: [category link text, e.g. 'Shop Bath Towels →']",
                "Link: [category page URL]",
            ]},
            {"name": "Category 2 — 50/50 left", "type": "image", "fields": [
                "Layout: 50/50 (paired with Category 3 in the same row)",
                "CTA: [category link text]",
                "Link: [category page URL]",
            ]},
            {"name": "Category 3 — 50/50 right", "type": "image", "fields": [
                "Layout: 50/50 (paired with Category 2 in the same row)",
                "CTA: [category link text]",
                "Link: [category page URL]",
            ]},
            {"name": "Category 4 — full width", "type": "image", "fields": [
                "CTA: [category link text, e.g. 'Shop All Bath →']",
                "Link: [category page URL]",
            ]},
        ],
        "auto_modules": ["YMAL"],
    },
    "N": {
        "name": "UGC",
        "node_id": "1672:446",
        "use_cases": "UGC campaign, community showcase, customer-styled photos",
        "slices": [
            {"name": "Logo bar and hero (UGC photo 1)", "type": "image", "fields": [
                "HED: [e.g. 'Spring, Styled by You']",
                "DEK: [1–2 sentences about the community theme]",
                "CTA: [CTA text, e.g. 'Shop Now' — ghost button]",
                "Name: [product tag — name of product shown in hero photo]",
                "Instagram handle: @[handle of person who took hero photo]",
                "Link: [hero LP]",
            ]},
            {"name": "UGC photo 2", "type": "image", "fields": [
                "Name: [product tag — name of product shown in photo 2]",
                "Instagram handle: @[handle of person who took photo 2]",
                "Link: [product page URL]",
            ]},
            {"name": "UGC photo 3", "type": "image", "fields": [
                "Name: [product tag — name of product shown in photo 3]",
                "Instagram handle: @[handle of person who took photo 3]",
                "Link: [product page URL]",
            ]},
            {"name": "CTA button", "type": "image", "no_visual": True, "fields": [
                "CTA: [final button CTA text, e.g. 'Shop Now']",
                "Link: [hero LP]",
            ]},
        ],
        "auto_modules": ["YMAL"],
    },
    "O": {
        "name": "Meet the Makers",
        "node_id": "1735:760",
        "use_cases": "artisan story, maker spotlight, destination with craft narrative",
        "slices": [
            {"name": "Logo bar, hero, and maker story", "type": "image", "fields": [
                "Eyebrow: Meet the Makers",
                "HED: [maker or artisan name, e.g. 'SUNHOUSE CRAFT']",
                "DEK: [2–3 sentences about the artisan, their craft, and location]",
                "CTA: [CTA text, e.g. 'Meet the Maker >']",
                "Link: [artisan LP]",
            ]},
        ],
        "auto_modules": ["One kicker (cycled — Fair Trade Guaranteed / YMAL)"],
    },
}

# ---------------------------------------------------------------------------
# BW (Burrow) Figma template catalog
# Sourced from Figma file iOd6uooBKdfJGHboJ8wLvJ (Burrow-Email-CRM-Templates)
# Display names match Nicole's convention: "{Section} V{N}" (section name minus "Emails").
# ---------------------------------------------------------------------------

BW_FIGMA_FILE_KEY = "iOd6uooBKdfJGHboJ8wLvJ"

BW_FIGMA_TEMPLATES: Dict[str, Dict] = {
    # ── Collection Spotlight: single product or collection deep-dive ──────────
    "cs_v1": {
        "node_id": "5:30",
        "name": "Collection Spotlight V1",
        "image_count": 4,
        "use_cases": ["single chair", "accent piece", "dining chair", "single product story"],
        "description": "Hero + single product feature with callout text + 2 lifestyle photos + small product row. Best for a single chair or accent piece.",
        "slices": [
            {"name": "Logo & hero", "type": "image", "layout": "Full width", "fields": [
                "Eyebrow: [only if on sale, e.g. sale name/discount]",
                "HED: [product or collection title]",
                "DEK: [body copy]",
                "CTA: [e.g. 'Shop Now →']",
                "Link: [product/collection LP]",
            ]},
            {"name": "Feature collage", "type": "image", "layout": "Full width", "fields": [
                "Row 1 HED: [row 1 headline]",
                "Row 1 Body: [row 1 body copy]",
                "Row 1 CTA: [row 1 CTA, e.g. 'Shop Now']",
                "Row 2 HED: [row 2 headline]",
                "Row 2 Body: [row 2 body copy]",
                "Row 2 CTA: [row 2 CTA]",
                "Link: [LP]",
            ]},
            {"name": "Kicker", "type": "image", "layout": "Full width", "fields": [
                "HED: [kicker headline]",
                "Body: [kicker body copy]",
                "CTA: [kicker CTA]",
                "Link: [category LP]",
            ]},
        ],
    },
    "cs_v2": {
        "node_id": "5:67",
        "name": "Collection Spotlight V2",
        "image_count": 8,
        "use_cases": ["shelving", "storage", "new arrivals", "many SKUs", "system", "bookcase"],
        "description": "Full-bleed hero + lifestyle + specs + 2×3 product grid. Best for shelving/storage lines with many SKUs.",
        "slices": [
            {"name": "Logo & hero", "type": "image", "layout": "Full width", "fields": [
                "HED: [hero headline]",
                "DEK: [body copy]",
                "CTA: [e.g. 'Shop Now →']",
                "Link: [hero LP]",
            ]},
            {"name": "Feature collage", "type": "image", "layout": "Full width", "fields": [
                "Row 1 HED: [row 1 headline]",
                "Row 1 Body: [row 1 body copy]",
                "Row 1 CTA: [row 1 CTA]",
                "Callout labels: [labels on the full-width image between the two rows]",
                "Row 2 HED: [row 2 headline]",
                "Row 2 Body: [row 2 body copy]",
                "Row 2 CTA: [row 2 CTA]",
                "Link: [LP]",
            ]},
            {"name": "Product-grid header", "type": "image", "layout": "Full width", "fields": [
                "HED: [e.g. 'Shop more with [Title]']",
                "Link: [same as hero]",
            ]},
            {"name": "Product 1", "type": "image", "layout": "50/50 left", "fields": [
                "Name: [product name]", "Link: [product page]",
            ]},
            {"name": "Product 2", "type": "image", "layout": "50/50 right", "fields": [
                "Name: [product name]", "Link: [product page]",
            ]},
            {"name": "Product 3", "type": "image", "layout": "50/50 left", "fields": [
                "Name: [product name]", "Link: [product page]",
            ]},
            {"name": "Product 4", "type": "image", "layout": "50/50 right", "fields": [
                "Name: [product name]", "Link: [product page]",
            ]},
            {"name": "Product 5", "type": "image", "layout": "50/50 left", "fields": [
                "Name: [product name]", "Link: [product page]",
            ]},
            {"name": "Product 6", "type": "image", "layout": "50/50 right", "fields": [
                "Name: [product name]", "Link: [product page]",
            ]},
        ],
    },
    "cs_v3": {
        "node_id": "5:143",
        "name": "Collection Spotlight V3",
        "image_count": 5,
        "use_cases": ["sofa launch", "sleeper sofa", "performance fabric", "feature highlights", "sofa features"],
        "description": "Dark full-bleed hero with large text overlay + feature callout icon row + lifestyle + 2×2 variant grid. Best for a sofa or sleeper launch with feature callouts.",
        "slices": [
            {"name": "Logo & hero", "type": "image", "layout": "Full width", "fields": [
                "HED: [top/bottom frame text, e.g. 'SHIFT' / 'SLEEPER']",
                "DEK: [body copy]",
                "CTA: [e.g. 'Shop Now →']",
                "Link: [hero LP]",
            ]},
            {"name": "Feature callouts", "type": "image", "layout": "Full width", "fields": [
                "HED: [feature headline]",
                "Feature callout text: [e.g. 'Deep, plush cushions' / 'Maximum comfort']",
                "Feature callouts: [icon row, e.g. Quick conversion / Queen size / Durable fabric]",
                "Link: [same as hero]",
            ]},
            {"name": "Full-width image", "type": "image", "layout": "Full width", "fields": [
                "Link: [same as hero]",
            ]},
            {"name": "Product-grid header", "type": "image", "layout": "Full width", "fields": [
                "HED: [header headline]",
                "Body: [optional supporting copy]",
                "Link: [same as hero]",
            ]},
            {"name": "Product 1", "type": "image", "layout": "50/50 left", "fields": [
                "Name: [product name]", "Link: [product page]",
            ]},
            {"name": "Product 2", "type": "image", "layout": "50/50 right", "fields": [
                "Name: [product name]", "Link: [product page]",
            ]},
            {"name": "Product 3", "type": "image", "layout": "50/50 left", "fields": [
                "Name: [product name]", "Link: [product page]",
            ]},
            {"name": "Product 4", "type": "image", "layout": "50/50 right", "fields": [
                "Name: [product name]", "Link: [product page]",
            ]},
        ],
    },
    "cs_v4": {
        "node_id": "5:226",
        "name": "Collection Spotlight V4",
        "image_count": 6,
        "use_cases": ["named collection", "collection launch", "sofa collection", "multiple colorways", "sectional collection"],
        "description": "Full-bleed lifestyle hero + icon feature row + collection browsing rows. Best for a named sofa/seating collection with multiple configs.",
        "slices": [
            {"name": "Logo & hero", "type": "image", "layout": "Full width", "fields": [
                "HED: [collection title]",
                "CTA: [button, e.g. 'Make It Yours at 25% Off →' — sale wording when on sale]",
                "Link: [collection LP]",
            ]},
            {"name": "Intro + icons", "type": "image", "layout": "Full width", "fields": [
                "HED: [intro headline]",
                "DEK: [description]",
                "CTA: [button, e.g. 'Shop Now']",
                "Feature callouts: [icon row, e.g. Easy assembly / Extreme comfort / Fast shipping]",
                "Link: [LP]",
            ]},
            {"name": "Full-width image", "type": "image", "layout": "Full width", "fields": [
                "Link: [same as hero]",
            ]},
            {"name": "Editorial grid", "type": "image", "layout": "Full width", "fields": [
                "Row 1 HED: [row 1 headline]",
                "Row 1 Body: [row 1 body copy]",
                "Row 1 CTA: [row 1 CTA, e.g. 'Shop Now →']",
                "Row 2 HED: [row 2 headline]",
                "Row 2 Body: [row 2 body copy]",
                "Row 2 CTA: [row 2 CTA]",
                "Link: [LP]",
            ]},
            {"name": "Product-grid header", "type": "image", "layout": "Full width", "fields": [
                "HED: [e.g. 'Explore all [Collection] now 25% off']",
                "Link: [same as hero]",
            ]},
            {"name": "Product 1", "type": "image", "layout": "50/50 left", "fields": [
                "Name: [product name]", "Link: [product page]",
            ]},
            {"name": "Product 2", "type": "image", "layout": "50/50 right", "fields": [
                "Name: [product name]", "Link: [product page]",
            ]},
            {"name": "Product 3", "type": "image", "layout": "50/50 left", "fields": [
                "Name: [product name]", "Link: [product page]",
            ]},
            {"name": "Product 4", "type": "image", "layout": "50/50 right", "fields": [
                "Name: [product name]", "Link: [product page]",
            ]},
            {"name": "Product 5", "type": "image", "layout": "50/50 left", "fields": [
                "Name: [product name]", "Link: [product page]",
            ]},
            {"name": "Product 6", "type": "image", "layout": "50/50 right", "fields": [
                "Name: [product name]", "Link: [product page]",
            ]},
            {"name": "Kicker", "type": "image", "layout": "Full width", "fields": [
                "HED: [kicker headline]",
                "Body: [kicker body copy]",
                "CTA: [kicker CTA]",
                "Link: [category/collection LP]",
            ]},
        ],
    },
    "cs_v5": {
        "node_id": "5:404",
        "name": "Collection Spotlight V5",
        "image_count": 5,
        "use_cases": ["editorial", "lifestyle heavy", "brand story", "comfort claims", "aspirational"],
        "description": "5 stacked full-bleed lifestyle images with text overlays, minimal product shots. Very editorial/brand storytelling.",
        "slices": [
            {"name": "Logo & hero", "type": "image", "layout": "Full width", "fields": [
                "Eyebrow: [short hero eyebrow]",
                "HED: [short & large headline]",
                "CTA: [near the bottom, e.g. 'Shop Russet →']",
                "Link: [collection LP]",
            ]},
            {"name": "Value prop 1", "type": "image", "layout": "Full width", "fields": [
                "Value prop: [~2 words, e.g. 'cloudlike comfort']",
                "Link: [collection LP]",
            ]},
            {"name": "Value prop 2", "type": "image", "layout": "Full width", "fields": [
                "Value prop: [~2 words]",
                "Link: [collection LP]",
            ]},
            {"name": "Value prop 3", "type": "image", "layout": "Full width", "fields": [
                "Value prop: [~2 words]",
                "Link: [collection LP]",
            ]},
            {"name": "Value prop 4", "type": "image", "layout": "Full width", "fields": [
                "Value prop: [~2 words]",
                "Link: [collection LP]",
            ]},
            {"name": "CTA image", "type": "image", "layout": "Full width", "fields": [
                "CTA: [~2 words, e.g. 'Shop Russet →']",
                "Link: [collection LP]",
            ]},
        ],
    },
    "cs_v6": {
        "node_id": "5:469",
        "name": "Collection Spotlight V6",
        "image_count": 5,
        "use_cases": ["media console", "TV stand", "game day", "entertainment furniture", "specific product"],
        "description": "Hero + product feature with specs + lifestyle + 2×2 product grid. Best for media/entertainment furniture or a feature-forward specific product.",
        "slices": [
            {"name": "Logo & hero", "type": "image", "layout": "Full width", "fields": [
                "HED: [hero headline]",
                "DEK: [body copy]",
                "CTA: [e.g. 'Shop Now →']",
                "Link: [hero LP]",
            ]},
            {"name": "Feature collage", "type": "image", "layout": "Full width", "fields": [
                "Row 1 HED: [row 1 headline]",
                "Row 1 Body: [row 1 body copy]",
                "Row 1 CTA: [row 1 CTA, e.g. 'Shop Now']",
                "Callout labels: [labels on the full-width feature image between the two rows]",
                "Row 2 HED: [row 2 headline]",
                "Row 2 Body: [row 2 body copy]",
                "Row 2 CTA: [row 2 CTA]",
                "Link: [LP]",
            ]},
            {"name": "Product-grid header", "type": "image", "layout": "Full width", "fields": [
                "HED: [copy over the grid]",
                "Link: [same as hero]",
            ]},
            {"name": "Product 1", "type": "image", "layout": "50/50 left", "fields": [
                "Name: [product name]", "Link: [product page]",
            ]},
            {"name": "Product 2", "type": "image", "layout": "50/50 right", "fields": [
                "Name: [product name]", "Link: [product page]",
            ]},
            {"name": "Product 3", "type": "image", "layout": "50/50 left", "fields": [
                "Name: [product name]", "Link: [product page]",
            ]},
            {"name": "Product 4", "type": "image", "layout": "50/50 right", "fields": [
                "Name: [product name]", "Link: [product page]",
            ]},
        ],
    },
    "cs_v7": {
        "node_id": "5:533",
        "name": "Collection Spotlight V7",
        "image_count": 6,
        "use_cases": ["flagship sofa", "large seating collection", "many configurations", "sofa family"],
        "description": "Lifestyle hero + feature icon row + sofa browsing section + product grid. Best for flagship sofa families with many configurations.",
        "slices": [
            {"name": "Logo & hero", "type": "image", "layout": "Full width", "fields": [
                "HED: [hero headline]",
                "Body: [copy near the bottom]",
                "CTA: [button, e.g. 'Shop Now →']",
                "Link: [hero LP]",
            ]},
            {"name": "Feature block", "type": "image", "layout": "Full width", "fields": [
                "HED: [feature headline]",
                "Body: [feature body copy]",
                "CTA: [e.g. 'Shop Now']",
                "Feature callouts: [3 icons, e.g. Durable upholstery / Hardwood frame / Built-in charger]",
                "Link: [LP]",
            ]},
            {"name": "Product-grid header", "type": "image", "layout": "Full width", "fields": [
                "HED: [header headline]",
                "Body: [header body copy]",
                "CTA: [e.g. 'Shop Now']",
                "Link: [same as hero]",
            ]},
            {"name": "Product 1", "type": "image", "layout": "50/50 left", "fields": [
                "Name: [product title, e.g. product name over tan background]", "Link: [product page]",
            ]},
            {"name": "Product 2", "type": "image", "layout": "50/50 right", "fields": [
                "Name: [product title]", "Link: [product page]",
            ]},
            {"name": "Product 3", "type": "image", "layout": "Full width", "fields": [
                "Name: [product title]", "Link: [product page]",
            ]},
            {"name": "Product 4", "type": "image", "layout": "50/50 left", "fields": [
                "Name: [product title]", "Link: [product page]",
            ]},
            {"name": "Product 5", "type": "image", "layout": "50/50 right", "fields": [
                "Name: [product title]", "Link: [product page]",
            ]},
            {"name": "Kicker", "type": "image", "layout": "Full width", "fields": [
                "HED: [kicker headline]",
                "Body: [short kicker body copy]",
                "CTA: [e.g. 'Shop Seating' — replace with the kicker topic, e.g. Shop Seating / Shop Outdoor]",
                "Link: [category LP]",
            ]},
        ],
    },
    # ── Multi Collection Spotlight: multiple categories or 3+ products ────────
    "mcs_v1": {
        "node_id": "7:1094",
        "name": "Multi Collection Spotlight V1",
        "image_count": 6,
        "use_cases": ["outdoor", "patio", "two categories", "spring", "summer", "outdoor seating and dining"],
        "description": "Hero + 2 collection sections each with lifestyle + icon row + 2 products. Best for outdoor or 2-category emails.",
        "slices": [
            {"name": "Logo & hero", "type": "image", "layout": "Full width", "fields": [
                "HED: [hero headline]",
                "DEK: [body; include sale name when on sale]",
                "CTA: [e.g. 'Shop Now →']",
                "Link: [hero LP]",
            ]},
            {"name": "Section 1 header", "type": "image", "layout": "Full width", "fields": [
                "HED: [collection 1 name]",
                "Body: [section 1 body copy]",
                "CTA: [e.g. 'Shop Now']",
                "Feature callouts: [3 icons, e.g. Quick-drying foam / FSC-certified teak / All-weather fabric]",
                "Link: [section 1 LP]",
            ]},
            {"name": "Section 1 lifestyle image", "type": "image", "layout": "Full width", "fields": [
                "Link: [section 1 LP]",
            ]},
            {"name": "Section 2 header", "type": "image", "layout": "Full width", "fields": [
                "HED: [collection 2 name]",
                "Body: [section 2 body copy]",
                "CTA: [section 2 CTA]",
                "Feature callouts: [3 icons]",
                "Link: [section 2 LP]",
            ]},
            {"name": "Section 2 lifestyle image", "type": "image", "layout": "Full width", "fields": [
                "Link: [section 2 LP]",
            ]},
            {"name": "Kicker", "type": "image", "layout": "Full width", "fields": [
                "HED: [kicker headline]",
                "Body: [kicker body copy]",
                "CTA: [e.g. 'Shop Outdoor' — swap topic]",
                "Link: [category LP]",
            ]},
        ],
    },
    "mcs_v2": {
        "node_id": "7:1138",
        "name": "Multi Collection Spotlight V2",
        "image_count": 10,
        "use_cases": ["sectional showcase", "find your fit", "multiple sofas", "large seating collection"],
        "description": "Hero + 3–4 collection sections each with lifestyle + 2 products. Best for large sofa or sectional collections.",
        "slices": [
            {"name": "Logo & hero", "type": "image", "layout": "Full width", "fields": [
                "HED: [hero headline]",
                "DEK: [body copy]",
                "CTA: [e.g. 'Shop Now →']",
                "Link: [hero LP]",
            ]},
            {"name": "Section 1 lifestyle image + collage header", "type": "image", "layout": "Full width", "fields": [
                "HED: [collection 1 name]",
                "Body: [section 1 body copy]",
                "CTA: [e.g. 'Shop Now']",
                "Link: [collection 1 LP]",
            ]},
            {"name": "Section 1 Product 1", "type": "image", "layout": "50/50 left", "fields": [
                "Name: [product name]", "Colorway: [colorway/fabric name]", "Link: [product 1 page]",
            ]},
            {"name": "Section 1 Product 2", "type": "image", "layout": "50/50 right", "fields": [
                "Name: [product name]", "Colorway: [colorway/fabric name]", "Link: [product 2 page]",
            ]},
            {"name": "Section 2 lifestyle image + collage header", "type": "image", "layout": "Full width", "fields": [
                "HED: [collection 2 name]",
                "Body: [section 2 body copy]",
                "CTA: [section 2 CTA]",
                "Link: [collection 2 LP]",
            ]},
            {"name": "Section 2 Product 1", "type": "image", "layout": "50/50 left", "fields": [
                "Name: [product name]", "Colorway: [colorway/fabric name]", "Link: [product 1 page]",
            ]},
            {"name": "Section 2 Product 2", "type": "image", "layout": "50/50 right", "fields": [
                "Name: [product name]", "Colorway: [colorway/fabric name]", "Link: [product 2 page]",
            ]},
            {"name": "Section 3 lifestyle image + collage header", "type": "image", "layout": "Full width", "fields": [
                "HED: [collection 3 name]",
                "Body: [section 3 body copy]",
                "CTA: [section 3 CTA]",
                "Link: [collection 3 LP]",
            ]},
            {"name": "Section 3 Product 1", "type": "image", "layout": "50/50 left", "fields": [
                "Name: [product name]", "Colorway: [colorway/fabric name]", "Link: [product 1 page]",
            ]},
            {"name": "Section 3 Product 2", "type": "image", "layout": "50/50 right", "fields": [
                "Name: [product name]", "Colorway: [colorway/fabric name]", "Link: [product 2 page]",
            ]},
        ],
    },
    "mcs_v3": {
        "node_id": "7:1223",
        "name": "Multi Collection Spotlight V3",
        "image_count": 4,
        "use_cases": ["bestsellers", "top picks", "staff picks", "curated edit", "3 products"],
        "description": "Dark banner/hero + 3 products stacked with alternating lifestyle images. Best for a curated edit or bestsellers featuring 3 items.",
        "slices": [
            {"name": "Logo & hero", "type": "image", "layout": "Full width", "fields": [
                "HED: [e.g. 'More to Love']",
                "Product collage callout: [e.g. 'Span Sleeper Sofa']",
                "Body: [body copy]",
                "CTA: [e.g. 'Shop Now →']",
                "Link: [hero LP]",
            ]},
            {"name": "Product feature 1", "type": "image", "layout": "Full width", "fields": [
                "HED: [product name]", "Body: [body copy]", "CTA: [e.g. 'Shop Now']", "Link: [product page]",
            ]},
            {"name": "Product feature 2", "type": "image", "layout": "Full width", "fields": [
                "HED: [product name]", "Body: [body copy]", "CTA: [e.g. 'Shop Now']", "Link: [product page]",
            ]},
            {"name": "Product feature 3", "type": "image", "layout": "Full width", "fields": [
                "HED: [product name]", "Body: [body copy]", "CTA: [e.g. 'Shop Now']", "Link: [product page]",
            ]},
        ],
    },
    "mcs_v4": {
        "node_id": "7:1248",
        "name": "Multi Collection Spotlight V4",
        "image_count": 5,
        "use_cases": ["outdoor", "clean editorial", "3 categories", "alternating layout"],
        "description": "Full-bleed hero + 3 product/category sections in alternating left/right layout. Clean and editorial.",
        "slices": [
            {"name": "Logo & hero", "type": "image", "layout": "Full width", "fields": [
                "HED: [hero headline]",
                "DEK: [body; include sale name when on sale]",
                "CTA: [e.g. 'Shop Now →']",
                "Link: [hero LP]",
            ]},
            {"name": "Section 1", "type": "image", "layout": "Full width", "fields": [
                "HED: [category 1 name]",
                "Body: [section 1 body copy]",
                "CTA: [e.g. 'Shop Now']",
                "Link: [category 1 LP — the whole thumbnail row shares this one link]",
            ]},
            {"name": "Section 2", "type": "image", "layout": "Full width", "fields": [
                "HED: [category 2 name]",
                "Body: [section 2 body copy]",
                "CTA: [section 2 CTA]",
                "Link: [category 2 LP]",
            ]},
            {"name": "Section 3", "type": "image", "layout": "Full width", "fields": [
                "HED: [category 3 name]",
                "Body: [section 3 body copy]",
                "CTA: [section 3 CTA]",
                "Link: [category 3 LP]",
            ]},
        ],
    },
    "mcs_v5": {
        "node_id": "7:1281",
        "name": "Multi Collection Spotlight V5",
        "image_count": 7,
        "use_cases": ["dining", "multi-category dining", "chairs and tables", "counter stools", "dining room", "small spaces dining"],
        "description": "Dark full-bleed hero + 3 category sections (e.g. dining chairs / tables / stools) each with headline + product row. Best for dining room multi-category emails.",
        "slices": [
            {"name": "Logo & hero", "type": "image", "layout": "Full width", "fields": [
                "HED: [hero headline]",
                "DEK: [body copy]",
                "CTA: [e.g. 'Shop Now →']",
                "Link: [hero LP]",
            ]},
            {"name": "Category 1 feature", "type": "image", "layout": "Full width", "fields": [
                "HED: [e.g. 'Dining Chairs']",
                "Body: [category 1 body copy]",
                "CTA: [button, e.g. 'Shop Now →']",
                "Link: [category 1 LP]",
            ]},
            {"name": "Category 2 product-grid header", "type": "image", "layout": "Full width", "fields": [
                "HED: [e.g. 'Dining Tables']",
                "Link: [category 2 LP]",
            ]},
            {"name": "Product 1", "type": "image", "layout": "50/50 left", "fields": [
                "Name: [product name]", "Link: [product page]",
            ]},
            {"name": "Product 2", "type": "image", "layout": "50/50 right", "fields": [
                "Name: [product name]", "Link: [product page]",
            ]},
            {"name": "Product 3", "type": "image", "layout": "50/50 left", "fields": [
                "Name: [product name]", "Link: [product page]",
            ]},
            {"name": "Product 4", "type": "image", "layout": "50/50 right", "fields": [
                "Name: [product name]", "Link: [product page]",
            ]},
            {"name": "Category 2 CTA button", "type": "image", "layout": "Full width", "no_visual": True, "fields": [
                "CTA: [e.g. 'Shop Now →']",
                "Link: [category 2 LP]",
            ]},
            {"name": "Category 3 feature", "type": "image", "layout": "Full width", "fields": [
                "HED: [e.g. 'Counter Stools']",
                "Body: [category 3 body copy]",
                "CTA: [button]",
                "Link: [category 3 LP]",
            ]},
        ],
    },
    "mcs_v6": {
        "node_id": "7:1337",
        "name": "Multi Collection Spotlight V6",
        "image_count": 12,
        "use_cases": ["gift guide", "whole home", "holiday", "multi-room", "living dining storage", "gifting"],
        "description": "Hero + 3+ room sections (living/dining/storage) each with lifestyle + product pair. Very long. Best for gift guide or whole-home editorial.",
        "slices": [
            {"name": "Logo & hero", "type": "image", "layout": "Full width", "fields": [
                "HED: [e.g. 'Home for the Holidays']",
                "DEK: [body copy]",
                "CTA: [button, e.g. 'Shop Now →']",
                "Link: [hero LP]",
            ]},
            {"name": "Room 1 lifestyle image", "type": "image", "layout": "Full width", "fields": [
                "HED: [e.g. 'Seating']",
                "Body: [room 1 body copy]",
                "CTA: [e.g. 'Shop Now']",
                "Link: [category LP]",
            ]},
            {"name": "Room 1 Product 1", "type": "image", "layout": "Full width", "fields": [
                "Name: [product name]", "Link: [product page]",
            ]},
            {"name": "Room 1 Product 2", "type": "image", "layout": "50/50 left", "fields": [
                "Name: [product name]", "Link: [product page]",
            ]},
            {"name": "Room 1 Product 3", "type": "image", "layout": "50/50 right", "fields": [
                "Name: [product name]", "Link: [product page]",
            ]},
            {"name": "Room 2 lifestyle image", "type": "image", "layout": "Full width", "fields": [
                "HED: [e.g. 'Dining']",
                "Body: [room 2 body copy]",
                "CTA: [room 2 CTA]",
                "Link: [category LP]",
            ]},
            {"name": "Room 2 Product 1", "type": "image", "layout": "Full width", "fields": [
                "Name: [product name]", "Link: [product page]",
            ]},
            {"name": "Room 2 Product 2", "type": "image", "layout": "50/50 left", "fields": [
                "Name: [product name]", "Link: [product page]",
            ]},
            {"name": "Room 2 Product 3", "type": "image", "layout": "50/50 right", "fields": [
                "Name: [product name]", "Link: [product page]",
            ]},
            {"name": "Room 3 lifestyle image", "type": "image", "layout": "Full width", "fields": [
                "HED: [e.g. 'Storage']",
                "Body: [room 3 body copy]",
                "CTA: [room 3 CTA]",
                "Link: [category LP]",
            ]},
            {"name": "Room 3 Product 1", "type": "image", "layout": "Full width", "fields": [
                "Name: [product name]", "Link: [product page]",
            ]},
            {"name": "Room 3 Product 2", "type": "image", "layout": "50/50 left", "fields": [
                "Name: [product name]", "Link: [product page]",
            ]},
            {"name": "Room 3 Product 3", "type": "image", "layout": "50/50 right", "fields": [
                "Name: [product name]", "Link: [product page]",
            ]},
        ],
    },
    "mcs_v7": {
        "node_id": "7:1396",
        "name": "Multi Collection Spotlight V7",
        "image_count": 6,
        "use_cases": ["storage", "organization", "shelving", "media console", "clutter", "home office storage"],
        "description": "Dark tagline hero + 3 storage product sections with lifestyle + product grid. Best for storage or organization campaigns.",
        "slices": [
            {"name": "Logo & hero", "type": "image", "layout": "Full width", "fields": [
                "HED: [e.g. 'Clutter? Conquered.']",
                "DEK: [body copy]",
                "CTA: [e.g. 'Shop Now →']",
                "Link: [hero LP]",
            ]},
            {"name": "Section 1", "type": "image", "layout": "Full width", "fields": [
                "HED: [e.g. Title Shelves]",
                "Body: [section 1 body copy]",
                "CTA: [e.g. 'Shop Now']",
                "Feature callouts: [e.g. Built-in Desk / Expandable Design / Scratch-resistant]",
                "Link: [collection LP]",
            ]},
            {"name": "Section 1 Product 1", "type": "image", "layout": "50/50 left", "fields": [
                "Name: [product name]", "Link: [product page]",
            ]},
            {"name": "Section 1 Product 2", "type": "image", "layout": "50/50 right", "fields": [
                "Name: [product name]", "Link: [product page]",
            ]},
            {"name": "Feature interstitial", "type": "image", "layout": "Full width", "fields": [
                "HED: [e.g. Index Wall Shelves]",
                "Body: [interstitial body copy]",
                "CTA: [interstitial CTA]",
                "Feature callouts: [feature callouts]",
                "Link: [collection LP]",
            ]},
            {"name": "Section 2", "type": "image", "layout": "Full width", "fields": [
                "HED: [e.g. Opera Console]",
                "Body: [section 2 body copy]",
                "CTA: [section 2 CTA]",
                "Feature callouts: [feature callouts]",
                "Link: [collection LP]",
            ]},
            {"name": "Section 2 Product 1", "type": "image", "layout": "50/50 left", "fields": [
                "Name: [product name]", "Link: [product page]",
            ]},
            {"name": "Section 2 Product 2", "type": "image", "layout": "50/50 right", "fields": [
                "Name: [product name]", "Link: [product page]",
            ]},
        ],
    },
    "mcs_v8": {
        "node_id": "7:1444",
        "name": "Multi Collection Spotlight V8",
        "image_count": 6,
        "use_cases": ["dining room", "4 products", "tables and chairs", "modern dining"],
        "description": "Hero + 4 dining products in alternating lifestyle/product layout. Best for modern dining room with 4 individual items.",
        "slices": [
            {"name": "Logo & hero", "type": "image", "layout": "Full width", "fields": [
                "HED: [hero headline]",
                "DEK: [body copy]",
                "CTA: [e.g. 'Shop Now →']",
                "Link: [hero LP]",
            ]},
            {"name": "Product feature 1", "type": "image", "layout": "Full width", "fields": [
                "HED: [product name]", "Body: [body copy]", "CTA: [e.g. 'Shop Now']", "Link: [product page]",
            ]},
            {"name": "Product feature 2", "type": "image", "layout": "Full width", "fields": [
                "HED: [product name]", "Body: [body copy]", "CTA: [CTA]", "Link: [product page]",
            ]},
            {"name": "Product feature 3", "type": "image", "layout": "Full width", "fields": [
                "HED: [product name]", "Body: [body copy]", "CTA: [CTA]", "Link: [product page]",
            ]},
            {"name": "Product feature 4", "type": "image", "layout": "Full width", "fields": [
                "HED: [product name]", "Body: [body copy]", "CTA: [CTA]", "Link: [product page]",
            ]},
            {"name": "Kicker", "type": "image", "layout": "Full width", "fields": [
                "HED: [kicker headline]",
                "Body: [kicker body copy]",
                "CTA: [e.g. 'Shop All Dining']",
                "Link: [category LP]",
            ]},
        ],
    },
    "mcs_v9": {
        "node_id": "7:1811",
        "name": "Multi Collection Spotlight V9",
        "image_count": 5,
        "use_cases": ["sale", "seating sale", "promotional seating", "presidents day", "take a seat"],
        "description": "Hero + 4 products in alternating layout with sale pricing/tags visible. Best for seating sales.",
        "slices": [
            {"name": "Logo & hero", "type": "image", "layout": "Full width", "fields": [
                "HED: [e.g. 'Take a Seat']",
                "DEK: [body; include sale name/discount]",
                "CTA: [e.g. 'Shop Now →']",
                "Link: [hero LP]",
            ]},
            {"name": "Product feature 1", "type": "image", "layout": "Full width", "fields": [
                "Feature callouts: [product feature callouts]",
                "HED: [product name]",
                "CTA: [e.g. 'Shop Now']",
                "Link: [product page]",
            ]},
            {"name": "Product feature 2", "type": "image", "layout": "Full width", "fields": [
                "Feature callouts: [product feature callouts]",
                "HED: [product name]",
                "CTA: [CTA]",
                "Link: [product page]",
            ]},
            {"name": "Product feature 3", "type": "image", "layout": "Full width", "fields": [
                "Feature callouts: [product feature callouts]",
                "HED: [product name]",
                "CTA: [CTA]",
                "Link: [product page]",
            ]},
            {"name": "Product feature 4", "type": "image", "layout": "Full width", "fields": [
                "Feature callouts: [product feature callouts]",
                "HED: [product name]",
                "CTA: [CTA]",
                "Link: [product page]",
            ]},
            {"name": "Kicker", "type": "image", "layout": "Full width", "fields": [
                "HED: [e.g. 'Get it by Thanksgiving']",
                "Body: [may include a shipping-deadline date]",
                "CTA: [e.g. 'Shop Now →']",
                "Link: [category LP]",
            ]},
        ],
    },
    "mcs_v10": {
        "node_id": "7:1494",
        "name": "Multi Collection Spotlight V10",
        "image_count": 5,
        "use_cases": ["color story", "new colorways", "fabric launch", "seasonal color refresh"],
        "description": "Hero + 3 products in alternating lifestyle/product layout featuring specific colorways. Best for colorway or fabric launches.",
        "slices": [
            {"name": "Logo & hero", "type": "image", "layout": "Full width", "fields": [
                "Eyebrow: [e.g. 'Our Take on Cloud Dancer']",
                "HED: [hero headline]",
                "DEK: [body copy]",
                "CTA: [e.g. 'Shop Now →']",
                "Link: [hero LP]",
            ]},
            {"name": "Product feature 1", "type": "image", "layout": "Full width", "fields": [
                "HED: [product name + colorway]", "Body: [body copy]", "CTA: [e.g. 'Shop Now']", "Link: [product page]",
            ]},
            {"name": "Product feature 2", "type": "image", "layout": "Full width", "fields": [
                "HED: [product name + colorway]", "Body: [body copy]", "CTA: [CTA]", "Link: [product page]",
            ]},
            {"name": "Product feature 3", "type": "image", "layout": "Full width", "fields": [
                "HED: [product name + colorway]", "Body: [body copy]", "CTA: [CTA]", "Link: [product page]",
            ]},
            {"name": "Kicker", "type": "image", "layout": "Full width", "fields": [
                "HED: [e.g. 'Need It Fast?']",
                "Body: [kicker body copy]",
                "CTA: [e.g. 'Shop Now']",
                "Link: [category LP, e.g. quick-ship]",
            ]},
        ],
    },
    "mcs_v11": {
        "node_id": "7:1556",
        "name": "Multi Collection Spotlight V11",
        "image_count": 9,
        "use_cases": ["small space", "apartment", "first home", "city living", "compact furniture"],
        "description": "Hero + 3 sections (seating / sleeping / storage) each with lifestyle + product grid. Best for small-space or apartment campaigns.",
        "slices": [
            {"name": "Logo & hero", "type": "image", "layout": "Full width", "fields": [
                "HED: [e.g. 'Small Space. Big Thinking.']",
                "DEK: [body copy]",
                "CTA: [e.g. 'Shop Now →']",
                "Link: [hero LP]",
            ]},
            {"name": "Section 1", "type": "image", "layout": "Full width", "fields": [
                "HED: [e.g. 'Compact, Configured']",
                "Body: [section 1 body copy]",
                "CTA: [if present in the Figma]",
                "Link: [category LP]",
            ]},
            {"name": "Section 1 Product 1", "type": "image", "layout": "50/50 left", "fields": [
                "Name: [product name]", "Link: [product page]",
            ]},
            {"name": "Section 1 Product 2", "type": "image", "layout": "50/50 right", "fields": [
                "Name: [product name]", "Link: [product page]",
            ]},
            {"name": "Section 1 Product 3", "type": "image", "layout": "50/50 left", "fields": [
                "Name: [product name]", "Link: [product page]",
            ]},
            {"name": "Section 1 Product 4", "type": "image", "layout": "50/50 right", "fields": [
                "Name: [product name]", "Link: [product page]",
            ]},
            {"name": "Section 2", "type": "image", "layout": "Full width", "fields": [
                "HED: [e.g. 'One Sofa, Real Sleep']",
                "Body: [section 2 body copy]",
                "CTA: [if present]",
                "Link: [category LP]",
            ]},
            {"name": "Section 2 Product 1", "type": "image", "layout": "50/50 left", "fields": [
                "Name: [product name]", "Link: [product page]",
            ]},
            {"name": "Section 2 Product 2", "type": "image", "layout": "50/50 right", "fields": [
                "Name: [product name]", "Link: [product page]",
            ]},
            {"name": "Section 3", "type": "image", "layout": "Full width", "fields": [
                "HED: [e.g. 'One System, Smart Storage']",
                "Body: [section 3 body copy]",
                "CTA: [if present]",
                "Link: [category LP]",
            ]},
            {"name": "Section 3 Product 1", "type": "image", "layout": "50/50 left", "fields": [
                "Name: [product name]", "Link: [product page]",
            ]},
            {"name": "Section 3 Product 2", "type": "image", "layout": "50/50 right", "fields": [
                "Name: [product name]", "Link: [product page]",
            ]},
            {"name": "Section 3 Product 3", "type": "image", "layout": "50/50 left", "fields": [
                "Name: [product name]", "Link: [product page]",
            ]},
            {"name": "Section 3 Product 4", "type": "image", "layout": "50/50 right", "fields": [
                "Name: [product name]", "Link: [product page]",
            ]},
        ],
    },
    "mcs_v12": {
        "node_id": "7:1689",
        "name": "Multi Collection Spotlight V12",
        "image_count": 7,
        "use_cases": ["bedroom", "sleep", "bed frame", "nightstand", "dresser", "bedroom refresh"],
        "description": "Hero + 3 bedroom sections (bed / nightstand / storage) with lifestyle + product pair. Best for bedroom collection emails.",
        "slices": [
            {"name": "Logo & hero", "type": "image", "layout": "Full width", "fields": [
                "HED: [e.g. 'Lose an Hour. Gain the Glow.']",
                "DEK: [body copy]",
                "CTA: [e.g. 'Shop Now →']",
                "Link: [hero LP]",
            ]},
            {"name": "Section 1", "type": "image", "layout": "Full width", "fields": [
                "HED: [e.g. 'The Foundation of a Good Night']",
                "Feature callouts: [e.g. Attached headboard / Corner-secured joinery]",
                "Link: [category LP]",
            ]},
            {"name": "Section 1 Product 1", "type": "image", "layout": "50/50 left", "fields": [
                "Name: [product name]", "Link: [product page]",
            ]},
            {"name": "Section 1 Product 2", "type": "image", "layout": "50/50 right", "fields": [
                "Name: [product name]", "Link: [product page]",
            ]},
            {"name": "Section 2", "type": "image", "layout": "Full width", "fields": [
                "HED: [e.g. 'Everything Within Reach']",
                "Feature callouts: [feature callouts]",
                "Link: [category LP]",
            ]},
            {"name": "Section 2 Product 1", "type": "image", "layout": "50/50 left", "fields": [
                "Name: [product name]", "Link: [product page]",
            ]},
            {"name": "Section 2 Product 2", "type": "image", "layout": "50/50 right", "fields": [
                "Name: [product name]", "Link: [product page]",
            ]},
            {"name": "Section 3", "type": "image", "layout": "Full width", "fields": [
                "HED: [e.g. 'Streamlined Storage']",
                "Feature callouts: [feature callouts]",
                "Link: [category LP]",
            ]},
            {"name": "Section 3 Product 1", "type": "image", "layout": "50/50 left", "fields": [
                "Name: [product name]", "Link: [product page]",
            ]},
            {"name": "Section 3 Product 2", "type": "image", "layout": "50/50 right", "fields": [
                "Name: [product name]", "Link: [product page]",
            ]},
        ],
    },
    "mcs_v13": {
        "node_id": "7:1752",
        "name": "Multi Collection Spotlight V13",
        "image_count": 5,
        "use_cases": ["dining tables", "extendable tables", "gathering", "3 tables", "expandable"],
        "description": "Hero + 3 dining table spotlights each with lifestyle + 2 variants. Best for a dining table focus with multiple table options.",
        "slices": [
            {"name": "Logo & hero", "type": "image", "layout": "Full width", "fields": [
                "HED: [e.g. 'Built to Gather']",
                "DEK: [body copy]",
                "CTA: [e.g. 'Shop Now →']",
                "Link: [hero LP]",
            ]},
            {"name": "Spotlight 1", "type": "image", "layout": "Full width", "fields": [
                "HED: [table name]",
                "Body: [body copy]",
                "Name: [product name incl. finish, e.g. 'Serif Extendable Dining Table in Oak']",
                "CTA button: [e.g. 'Shop Now →']",
                "Link: [product page]",
            ]},
            {"name": "Spotlight 2", "type": "image", "layout": "Full width", "fields": [
                "HED: [table name]",
                "Body: [body copy]",
                "Name: [product name incl. finish]",
                "CTA button: [CTA]",
                "Link: [product page]",
            ]},
            {"name": "Spotlight 3", "type": "image", "layout": "Full width", "fields": [
                "HED: [table name]",
                "Body: [body copy]",
                "Name: [product name incl. finish]",
                "CTA button: [CTA]",
                "Link: [product page]",
            ]},
        ],
    },
    "mcs_v14": {
        "node_id": "7:1632",
        "name": "Multi Collection Spotlight V14",
        "image_count": 8,
        "use_cases": ["whole home refresh", "new arrivals", "seasonal", "multiple rooms", "new year"],
        "description": "Hero + 3–4 room sections (living/dining/den) each with lifestyle + 2 products. Best for whole-home or new arrivals campaigns.",
        "slices": [
            {"name": "Logo & hero", "type": "image", "layout": "Full width", "fields": [
                "HED: [e.g. 'New Year, New Style']",
                "DEK: [body copy]",
                "CTA: [e.g. 'Shop Now →']",
                "Link: [hero LP]",
            ]},
            {"name": "Room 1", "type": "image", "layout": "Full width", "fields": [
                "HED: [e.g. 'For the Living Room']",
                "Body: [room 1 body copy]",
                "CTA: [e.g. 'Shop Now']",
                "Link: [category LP]",
            ]},
            {"name": "Room 1 Product 1", "type": "image", "layout": "50/50 left", "fields": [
                "Name: [product name]", "Link: [product page]",
            ]},
            {"name": "Room 1 Product 2", "type": "image", "layout": "50/50 right", "fields": [
                "Name: [product name]", "Link: [product page]",
            ]},
            {"name": "Room 2", "type": "image", "layout": "Full width", "fields": [
                "HED: [e.g. 'For the Dining Room']",
                "Body: [room 2 body copy]",
                "CTA: [room 2 CTA]",
                "Link: [category LP]",
            ]},
            {"name": "Room 2 Product 1", "type": "image", "layout": "50/50 left", "fields": [
                "Name: [product name]", "Link: [product page]",
            ]},
            {"name": "Room 2 Product 2", "type": "image", "layout": "50/50 right", "fields": [
                "Name: [product name]", "Link: [product page]",
            ]},
            {"name": "Room 3", "type": "image", "layout": "Full width", "fields": [
                "HED: [e.g. 'For the Den']",
                "Body: [room 3 body copy]",
                "CTA: [room 3 CTA]",
                "Link: [category LP]",
            ]},
            {"name": "Room 3 Product 1", "type": "image", "layout": "50/50 left", "fields": [
                "Name: [product name]", "Link: [product page]",
            ]},
            {"name": "Room 3 Product 2", "type": "image", "layout": "50/50 right", "fields": [
                "Name: [product name]", "Link: [product page]",
            ]},
            {"name": "Kicker", "type": "image", "layout": "Full width", "fields": [
                "HED: [e.g. 'Take a Seat']",
                "Body: [kicker body copy]",
                "CTA: [e.g. 'Shop All Seating']",
                "Link: [category LP]",
            ]},
        ],
    },
    # ── Retail Event: in-store/physical event announcements ───────────────────
    "re_v1": {
        "node_id": "2:30",
        "name": "Retail Event V1",
        "image_count": 2,
        "use_cases": ["retail event", "sip and sit", "in-store event", "promo announcement"],
        "description": "Full-bleed sofa hero with event details overlay + small promo callout. Compact event announcement.",
        "slices": [
            {"name": "Logo & hero", "type": "image", "layout": "Full width", "fields": [
                "Eyebrow: [event name, e.g. 'The Sip & Sit Event']",
                "HED: [tagline, e.g. 'Best Weekend Ever']",
                "DEK: [offer + invite copy]",
                "Event dates: [e.g. 'February 14th & February 15th']",
                "Event hours: [e.g. 'Open to Close']",
                "Location: ['Your Local Burrow Studio']",
                "CTA: [e.g. 'Find My Store →']",
                "Link: https://burrow.com/showrooms",
            ]},
            {"name": "Secondary promo banner", "type": "image", "layout": "Full width", "fields": [
                "Eyebrow: [e.g. 'Last Chance']",
                "HED: [e.g. 'Up to 70% Off Clearance Styles']",
                "CTA: [e.g. 'Shop Now']",
                "Link: [category/clearance LP]",
            ]},
        ],
    },
    "re_v2": {
        "node_id": "2:74",
        "name": "Retail Event V2",
        "image_count": 4,
        "use_cases": ["retail event invite", "sip and sit", "RSVP", "event details", "when and where"],
        "description": "Full-bleed hero + event when/where info blocks + venue photos. Best for detailed retail event invitations.",
        "slices": [
            {"name": "Logo & hero", "type": "image", "layout": "Full width", "fields": [
                "Eyebrow: [e.g. 'You're Invited To']",
                "HED: [event name, e.g. 'Sip & Sit']",
                "DEK: [offer + invite copy]",
                "CTA: [e.g. 'Find My Store →']",
                "Link: https://burrow.com/showrooms",
            ]},
            {"name": "When & Where + design consult", "type": "image", "layout": "Full width", "fields": [
                "When: [event date(s) + hours, e.g. 'Saturday, 02/07, open to close' / 'Sunday, 02/08, open to close']",
                "Where: ['Your local Burrow Studio']",
                "HED: [e.g. 'Make It Yours']",
                "Body: [e.g. design-consult pitch]",
                "CTA: [e.g. 'Find My Store']",
                "Fine print: [e.g. 'Terms apply. Select studios only.']",
                "Link: https://burrow.com/showrooms",
            ]},
        ],
    },
    "re_v3": {
        "node_id": "2:136",
        "name": "Retail Event V3",
        "image_count": 2,
        "use_cases": ["retail event", "sip and sit", "in-store", "compact event"],
        "description": "Product/lifestyle hero + event text + trending styles section. Compact retail event with product showcase.",
        "slices": [
            {"name": "Logo & hero", "type": "image", "layout": "Full width", "fields": [
                "Eyebrow: [e.g. 'You're Invited']",
                "HED: [event name, e.g. 'Sip & Sit']",
                "DEK: [offer + invite copy]",
                "Event dates: [e.g. 'November 22nd & November 23rd']",
                "Event hours: [e.g. 'Open to Close']",
                "Location: ['Your Local Burrow Studio']",
                "CTA: [e.g. 'Find My Store →']",
                "Link: https://burrow.com/showrooms",
            ]},
            {"name": "Cross-promo banner", "type": "image", "layout": "Full width", "fields": [
                "HED: [e.g. 'Trending styles for every corner']",
                "Body: [e.g. bestsellers pitch]",
                "CTA: [e.g. 'Shop Best Sellers']",
                "Link: [best-sellers LP]",
            ]},
        ],
    },
    # ── Fabric Spotlight: material and fabric stories ─────────────────────────
    "fab_v1": {
        "node_id": "2:275",
        "name": "Fabric Spotlight V1",
        "image_count": 5,
        "use_cases": ["single fabric", "performance fabric", "chenille", "fabric launch", "material story"],
        "description": "Fabric close-up hero + story copy + lifestyle + product grid showing the fabric across styles. Best for a single fabric launch.",
        "slices": [
            {"name": "Logo & hero", "type": "image", "layout": "Full width", "fields": [
                "Eyebrow: [e.g. 'Fabric Spotlight']",
                "HED: [fabric name]",
                "DEK: [body copy]",
                "CTA: [e.g. 'Order 5 Free Swatches →']",
                "Link: https://burrow.com/swatches",
            ]},
            {"name": "Fabric story", "type": "image", "layout": "Full width", "fields": [
                "HED: [story headline]",
                "Body: [story body copy]",
                "CTA: [e.g. 'Shop Now']",
                "Swatch thumbnails: [3 swatch thumbnails]",
                "Link: [collection LP]",
            ]},
            {"name": "Product 1", "type": "image", "layout": "50/50 left", "fields": [
                "Name: [product name]", "Colorway: [colorway/fabric name]", "Link: [product page]",
            ]},
            {"name": "Product 2", "type": "image", "layout": "50/50 right", "fields": [
                "Name: [product name]", "Colorway: [colorway/fabric name]", "Link: [product page]",
            ]},
            {"name": "Product 3", "type": "image", "layout": "50/50 left", "fields": [
                "Name: [product name]", "Colorway: [colorway/fabric name]", "Link: [product page]",
            ]},
            {"name": "Product 4", "type": "image", "layout": "50/50 right", "fields": [
                "Name: [product name]", "Colorway: [colorway/fabric name]", "Link: [product page]",
            ]},
            {"name": "Swatch kicker", "type": "image", "layout": "Full width", "fields": [
                "HED: [e.g. 'Order 5 Free Swatches']",
                "Body: [kicker body copy]",
                "CTA: [e.g. 'Shop Swatches']",
                "Link: https://burrow.com/swatches",
            ]},
        ],
    },
    "fab_v2": {
        "node_id": "3:30",
        "name": "Multi Fabric Spotlight V2",
        "image_count": 8,
        "use_cases": ["multiple fabrics", "fabric collection", "performance fabrics", "all fabrics"],
        "description": "Hero + 3 fabric sections each with description + lifestyle + swatches/products. Best for a full fabric collection overview.",
        "slices": [
            {"name": "Logo & hero", "type": "image", "layout": "Full width", "fields": [
                "Eyebrow: [e.g. 'Order 5 Free Swatches']",
                "HED: [e.g. 'Performance Fabrics']",
                "DEK: [body copy]",
                "Feature callouts: [3 icons, e.g. Free of harmful toxins / Ultra-tight weave / Stain & liquid resistant]",
                "CTA: [e.g. 'Shop Now →']",
                "Link: [hero LP]",
            ]},
            {"name": "Fabric section 1", "type": "image", "layout": "Full width", "fields": [
                "HED: [fabric name]", "Body: [body copy]", "CTA: [e.g. 'Shop Now']", "Link: [fabric LP]",
            ]},
            {"name": "Fabric section 2", "type": "image", "layout": "Full width", "fields": [
                "HED: [fabric name]", "Body: [body copy]", "CTA: [CTA]", "Link: [fabric LP]",
            ]},
            {"name": "Fabric section 3", "type": "image", "layout": "Full width", "fields": [
                "HED: [fabric name]", "Body: [body copy]", "CTA: [CTA]", "Link: [fabric LP]",
            ]},
            {"name": "Swatch kicker", "type": "image", "layout": "Full width", "fields": [
                "HED: [e.g. 'Order 5 Free Swatches']",
                "Body: [kicker body copy]",
                "CTA: [e.g. 'Shop Swatches']",
                "Link: https://burrow.com/swatches",
            ]},
        ],
    },
    "fab_v3": {
        "node_id": "3:154",
        "name": "Fabric Spotlight V2",
        "image_count": 6,
        "use_cases": ["fabric deep dive", "flatweave", "stain resistant", "durable", "single fabric with features"],
        "description": "Dark hero + feature callout icons + product grid across multiple sofa styles. Best for a feature-forward single fabric story.",
        "slices": [
            {"name": "Logo & hero", "type": "image", "layout": "Full width", "fields": [
                "Eyebrow: [e.g. 'Just Dropped']",
                "HED: [fabric name]",
                "DEK: [body copy]",
                "CTA: [e.g. 'Order 5 Free Swatches →']",
                "Link: https://burrow.com/swatches",
            ]},
            {"name": "Feature callouts", "type": "image", "layout": "Full width", "fields": [
                "Row 1 HED: [row 1 headline]",
                "Row 1 Body: [row 1 body copy]",
                "Row 1 CTA: [row 1 CTA, e.g. 'Order Free Swatches']",
                "Row 2 HED: [row 2 headline]",
                "Row 2 Body: [row 2 body copy]",
                "Row 2 CTA: [row 2 CTA]",
                "Link: https://burrow.com/swatches",
            ]},
            {"name": "Product-grid header", "type": "image", "layout": "Full width", "fields": [
                "HED: [e.g. 'Shop performance flatweave on our bestselling sofas']",
                "Link: [same as hero]",
            ]},
            {"name": "Product 1", "type": "image", "layout": "50/50 left", "fields": [
                "Name: [product name]", "Colorway: [colorway/fabric name]", "Link: [product page]",
            ]},
            {"name": "Product 2", "type": "image", "layout": "50/50 right", "fields": [
                "Name: [product name]", "Colorway: [colorway/fabric name]", "Link: [product page]",
            ]},
            {"name": "Product 3", "type": "image", "layout": "50/50 left", "fields": [
                "Name: [product name]", "Colorway: [colorway/fabric name]", "Link: [product page]",
            ]},
            {"name": "Product 4", "type": "image", "layout": "50/50 right", "fields": [
                "Name: [product name]", "Colorway: [colorway/fabric name]", "Link: [product page]",
            ]},
            {"name": "Product 5", "type": "image", "layout": "50/50 left", "fields": [
                "Name: [product name]", "Colorway: [colorway/fabric name]", "Link: [product page]",
            ]},
            {"name": "Product 6", "type": "image", "layout": "50/50 right", "fields": [
                "Name: [product name]", "Colorway: [colorway/fabric name]", "Link: [product page]",
            ]},
            {"name": "Swatch kicker", "type": "image", "layout": "Full width", "fields": [
                "HED: [e.g. 'The First Step to the Perfect Piece']",
                "CTA: [e.g. 'Order 5 Free Swatches →']",
                "Link: https://burrow.com/swatches",
            ]},
        ],
    },
    "fab_v4": {
        "node_id": "3:230",
        "name": "Multi Fabric Spotlight V1",
        "image_count": 5,
        "use_cases": ["leather", "premium material", "3 products in material", "material story"],
        "description": "Editorial hero + 3 products with alternating lifestyle + description. Best for leather or premium material stories.",
        "slices": [
            {"name": "Logo & hero", "type": "image", "layout": "Full width", "fields": [
                "Eyebrow: [e.g. 'Sink Into']",
                "HED: [e.g. 'Laid-back Leather']",
                "DEK: [body; include sale name/discount when on sale]",
                "CTA: [e.g. 'Shop Now →']",
                "Link: [hero LP]",
            ]},
            {"name": "Spotlight 1", "type": "image", "layout": "Full width", "fields": [
                "HED: [product name]",
                "Body: [body copy]",
                "Name: [product name incl. material, e.g. 'Range Pro 3-Seat Sofa in Camel Leather']",
                "CTA button: [e.g. 'Shop Now →']",
                "Link: [product page]",
            ]},
            {"name": "Spotlight 2", "type": "image", "layout": "Full width", "fields": [
                "HED: [product name]",
                "Body: [body copy]",
                "Name: [product name incl. material]",
                "CTA button: [CTA]",
                "Link: [product page]",
            ]},
            {"name": "Spotlight 3", "type": "image", "layout": "Full width", "fields": [
                "HED: [product name]",
                "Body: [body copy]",
                "Name: [product name incl. material]",
                "CTA button: [CTA]",
                "Link: [product page]",
            ]},
        ],
    },
    # ── Quick Ship: in-stock / fast delivery ──────────────────────────────────
    "qs_v1": {
        "node_id": "7:2",
        "name": "Quick Ship V1",
        "image_count": 4,
        "use_cases": ["quick ship", "in stock", "fast delivery", "ready to ship"],
        "description": "Lifestyle hero with Quick Ship messaging + intro text + 2×2 product grid. Standard quick-ship email.",
        "slices": [
            {"name": "Logo & hero", "type": "image", "layout": "Full width", "fields": [
                "HED: [e.g. 'Quick-Ship Steals']",
                "DEK: [body; include sale name/discount when on sale]",
                "CTA: [e.g. 'Shop Now →']",
                "Link: https://burrow.com/ready-to-ship",
            ]},
            {"name": "Story header", "type": "image", "layout": "Full width", "fields": [
                "HED: [e.g. 'Ready to go, and 25% off']",
                "Body: [body copy]",
                "CTA: [e.g. 'Shop Now']",
                "Link: https://burrow.com/ready-to-ship",
            ]},
            {"name": "Product 1", "type": "image", "layout": "50/50 left", "fields": [
                "Link: [product page]",
            ]},
            {"name": "Product 2", "type": "image", "layout": "50/50 right", "fields": [
                "Link: [product page]",
            ]},
            {"name": "Product 3", "type": "image", "layout": "Full width", "fields": [
                "Link: [product page]",
            ]},
            {"name": "Product 4", "type": "image", "layout": "50/50 left", "fields": [
                "Link: [product page]",
            ]},
            {"name": "Product 5", "type": "image", "layout": "50/50 right", "fields": [
                "Link: [product page]",
            ]},
        ],
    },
    "qs_v2": {
        "node_id": "7:336",
        "name": "Quick Ship V2",
        "image_count": 3,
        "use_cases": ["quick ship sale", "percent off", "promotional quick ship", "presidents day sale"],
        "description": "Promo % off hero + lifestyle + product grid. Best for quick-ship combined with a sale promotion.",
        "slices": [
            {"name": "Logo & hero", "type": "image", "layout": "Full width", "fields": [
                "HED: [e.g. 'Up to 35% Off']",
                "DEK: [body; include sale name/discount]",
                "CTA: [e.g. 'Shop Now →']",
                "Link: https://burrow.com/ready-to-ship",
            ]},
            {"name": "Story header", "type": "image", "layout": "Full width", "fields": [
                "HED: [e.g. 'Designs ready when you are']",
                "Body: [body copy]",
                "CTA: [e.g. 'Shop Now']",
                "Link: https://burrow.com/ready-to-ship",
            ]},
            {"name": "Product 1", "type": "image", "layout": "50/50 left", "fields": [
                "Name: [product name]", "Link: [product page]",
            ]},
            {"name": "Product 2", "type": "image", "layout": "50/50 right", "fields": [
                "Name: [product name]", "Link: [product page]",
            ]},
            {"name": "Product 3", "type": "image", "layout": "50/50 left", "fields": [
                "Name: [product name]", "Link: [product page]",
            ]},
            {"name": "Product 4", "type": "image", "layout": "50/50 right", "fields": [
                "Name: [product name]", "Link: [product page]",
            ]},
            {"name": "Product 5", "type": "image", "layout": "50/50 left", "fields": [
                "Name: [product name]", "Link: [product page]",
            ]},
            {"name": "Product 6", "type": "image", "layout": "50/50 right", "fields": [
                "Name: [product name]", "Link: [product page]",
            ]},
        ],
    },
    "qs_v3": {
        "node_id": "7:447",
        "name": "Quick Ship V3",
        "image_count": 5,
        "use_cases": ["quick ship editorial", "seating quick ship", "take a seat"],
        "description": "Full-bleed hero + 4 products in alternating layout. More editorial quick-ship format.",
        "slices": [
            {"name": "Logo & hero", "type": "image", "layout": "Full width", "fields": [
                "HED: [e.g. 'Take a Seat']",
                "DEK: [body; include sale name/discount]",
                "CTA: [e.g. 'Shop Now →']",
                "Link: https://burrow.com/ready-to-ship",
            ]},
            {"name": "Product feature 1", "type": "image", "layout": "Full width", "fields": [
                "Feature callouts: [product feature callouts]",
                "HED: [product name]",
                "CTA: [e.g. 'Shop Now']",
                "Link: [product page]",
            ]},
            {"name": "Product feature 2", "type": "image", "layout": "Full width", "fields": [
                "Feature callouts: [product feature callouts]",
                "HED: [product name]",
                "CTA: [CTA]",
                "Link: [product page]",
            ]},
            {"name": "Product feature 3", "type": "image", "layout": "Full width", "fields": [
                "Feature callouts: [product feature callouts]",
                "HED: [product name]",
                "CTA: [CTA]",
                "Link: [product page]",
            ]},
            {"name": "Product feature 4", "type": "image", "layout": "Full width", "fields": [
                "Feature callouts: [product feature callouts]",
                "HED: [product name]",
                "CTA: [CTA]",
                "Link: [product page]",
            ]},
            {"name": "Kicker", "type": "image", "layout": "Full width", "fields": [
                "HED: [e.g. 'Get it by Thanksgiving']",
                "Body: [may include a shipping-deadline date]",
                "CTA: [e.g. 'Shop Now →']",
                "Link: [category LP]",
            ]},
        ],
    },
    # ── Best Sellers ──────────────────────────────────────────────────────────
    "bs_v1": {
        "node_id": "6:558",
        "name": "Best Sellers V1",
        "image_count": 5,
        "use_cases": ["bestsellers", "flagship pieces", "top products", "comfort story"],
        "description": "Hero + 3–4 products stacked with alternating lifestyle images. Editorial feel, best for showcasing flagship bestsellers.",
        "slices": [
            {"name": "Logo & hero", "type": "image", "layout": "Full width", "fields": [
                "HED: [e.g. 'Comfort, Built In']",
                "DEK: [body copy]",
                "CTA: [e.g. 'Shop Now →']",
                "Link: https://burrow.com/collections/best-sellers",
            ]},
            {"name": "Product feature 1", "type": "image", "layout": "Full width", "fields": [
                "HED: [product name]", "Body: [body copy]", "CTA: [e.g. 'Shop Now']", "Link: [product page]",
            ]},
            {"name": "Product feature 2", "type": "image", "layout": "Full width", "fields": [
                "HED: [product name]", "Body: [body copy]", "CTA: [CTA]", "Link: [product page]",
            ]},
            {"name": "Product feature 3", "type": "image", "layout": "Full width", "fields": [
                "HED: [product name]", "Body: [body copy]", "CTA: [CTA]", "Link: [product page]",
            ]},
            {"name": "Product feature 4", "type": "image", "layout": "Full width", "fields": [
                "HED: [product name]", "Body: [body copy]", "CTA: [CTA]", "Link: [product page]",
            ]},
        ],
    },
    "bs_v2": {
        "node_id": "6:763",
        "name": "Best Sellers V2",
        "image_count": 4,
        "use_cases": ["wishlist", "gift guide", "curated bestsellers", "lifestyle heavy"],
        "description": "Full-bleed hero + product lifestyle spotlights. Lifestyle-heavy, great for gift-guide or wishlist-style emails.",
        "slices": [
            {"name": "Logo & hero", "type": "image", "layout": "Full width", "fields": [
                "HED: [e.g. \"The Styles on Everyone's Wishlist\"]",
                "DEK: [body; include sale name/discount when on sale]",
                "CTA: [e.g. 'Shop Now →']",
                "Link: https://burrow.com/collections/best-sellers",
            ]},
            {"name": "Category tile 1", "type": "image", "layout": "50/50 left", "fields": [
                "CTA: [e.g. 'Shop Modular Seating →']",
                "Link: [category LP]",
            ]},
            {"name": "Category tile 2", "type": "image", "layout": "50/50 right", "fields": [
                "CTA: [e.g. 'Shop Modular Seating →']",
                "Link: [category LP]",
            ]},
            {"name": "Category tile 3", "type": "image", "layout": "Full width", "fields": [
                "CTA: [e.g. 'Shop Sleeper Sofas →']",
                "Link: [category LP]",
            ]},
            {"name": "Category tile 4", "type": "image", "layout": "50/50 left", "fields": [
                "CTA: [e.g. 'Shop Storage →']",
                "Link: [category LP]",
            ]},
            {"name": "Category tile 5", "type": "image", "layout": "50/50 right", "fields": [
                "CTA: [e.g. 'Shop Storage →']",
                "Link: [category LP]",
            ]},
        ],
    },
    "bs_v3": {
        "node_id": "6:700",
        "name": "Best Sellers V3",
        "image_count": 7,
        "use_cases": ["sale bestsellers", "percent off seating", "collection breakdown", "multiple sofa collections"],
        "description": "Hero + collection-by-collection list each with name + tagline + lifestyle + products. Best for sale emails covering multiple collections.",
        "slices": [
            {"name": "Logo & hero", "type": "image", "layout": "Full width", "fields": [
                "Eyebrow: [e.g. 'Up To']",
                "HED: [e.g. '30% Off Seating']",
                "DEK: [body, if present]",
                "CTA: [e.g. 'Shop Now →']",
                "Link: https://burrow.com/collections/best-sellers",
            ]},
            {"name": "Collection feature 1", "type": "image", "layout": "Full width", "fields": [
                "HED: [collection name]", "Body: [body copy]", "CTA: [e.g. 'Shop Now']", "Link: [collection LP]",
            ]},
            {"name": "Collection feature 2", "type": "image", "layout": "Full width", "fields": [
                "HED: [collection name]", "Body: [body copy]", "CTA: [CTA]", "Link: [collection LP]",
            ]},
            {"name": "Collection feature 3", "type": "image", "layout": "Full width", "fields": [
                "HED: [collection name]", "Body: [body copy]", "CTA: [CTA]", "Link: [collection LP]",
            ]},
            {"name": "Collection feature 4", "type": "image", "layout": "Full width", "fields": [
                "HED: [collection name]", "Body: [body copy]", "CTA: [CTA]", "Link: [collection LP]",
            ]},
            {"name": "Collection feature 5", "type": "image", "layout": "Full width", "fields": [
                "HED: [collection name]", "Body: [body copy]", "CTA: [CTA]", "Link: [collection LP]",
            ]},
            {"name": "Kicker", "type": "image", "layout": "Full width", "fields": [
                "HED: [e.g. 'The best seat in the house']",
                "Body: [kicker body copy]",
                "CTA: [e.g. 'Shop Seating']",
                "Link: [category LP]",
            ]},
        ],
    },
    "bs_v4": {
        "node_id": "7:382",
        "name": "Best Sellers V4",
        "image_count": 5,
        "use_cases": ["seating bestsellers", "promotional seating", "take a seat"],
        "description": "Hero + 4 products in alternating layout. Best for seating bestsellers with a promotional angle.",
        "slices": [
            {"name": "Logo & hero", "type": "image", "layout": "Full width", "fields": [
                "HED: [e.g. 'Take a Seat']",
                "DEK: [body; include sale name/discount]",
                "CTA: [e.g. 'Shop Now →']",
                "Link: https://burrow.com/collections/best-sellers",
            ]},
            {"name": "Product feature 1", "type": "image", "layout": "Full width", "fields": [
                "Feature callouts: [product feature callouts]",
                "HED: [product name]",
                "CTA: [e.g. 'Shop Now']",
                "Link: [product page]",
            ]},
            {"name": "Product feature 2", "type": "image", "layout": "Full width", "fields": [
                "Feature callouts: [product feature callouts]",
                "HED: [product name]",
                "CTA: [CTA]",
                "Link: [product page]",
            ]},
            {"name": "Product feature 3", "type": "image", "layout": "Full width", "fields": [
                "Feature callouts: [product feature callouts]",
                "HED: [product name]",
                "CTA: [CTA]",
                "Link: [product page]",
            ]},
            {"name": "Product feature 4", "type": "image", "layout": "Full width", "fields": [
                "Feature callouts: [product feature callouts]",
                "HED: [product name]",
                "CTA: [CTA]",
                "Link: [product page]",
            ]},
            {"name": "Kicker", "type": "image", "layout": "Full width", "fields": [
                "HED: [e.g. 'Get it by Thanksgiving']",
                "Body: [kicker body copy]",
                "CTA: [e.g. 'Shop Now →']",
                "Link: [category LP]",
            ]},
        ],
    },
}

# BUR standalone kicker / link-farm modules (reference catalog).
# These are optional add-ons a copywriter/designer can append to a send; BW has no
# deterministic auto-cycling rule (unlike CZ), so generate_bw_email_brief() does NOT
# auto-attach them. Kept as data for briefing reference and future wiring — mirrors
# STF_KICKERS' status (reference-only, manual-add).
# Node IDs from docs/figma-templates.md "Link Farms — Reusable Kicker Modules".
BW_KICKERS: Dict[str, Dict] = {
    "bur_partner_blocks": {"node_id": "1:97", "name": "BUR Partner Blocks", "layout": "50/50 grid",
                            "description": "Cross-brand partner kicker — 5 lifestyle-photo tiles (Havenly, The Citizenry, The Inside, Interior Define, St. Frank) with brand name overlaid in white text."},
    "category_lifestyle_block": {"node_id": "7:1870", "name": "Category Lifestyle Block", "layout": "50/50 grid",
                                  "description": "Category link-farm kicker — lifestyle photo tiles per category (Seating, Dining, Bedroom, Sleeper Sofas, Storage, Outdoor); category list is flexible per send."},
    "category_footer_block": {"node_id": "7:1912", "name": "Category Footer Block", "layout": "50/50 grid",
                               "description": "Category link-farm kicker — solid-color text-button variant of Category Lifestyle Block (Sofas, Sectionals, Dining, Bedroom, Sleeper Sofas, Storage); category list is flexible per send."},
}

# STF (St. Frank) Figma template catalog — per-template, slice-by-slice
# ---------------------------------------------------------------------------
# Sourced from Figma file Bnne2c9xMqh3fiUp3VfLIM, "Templates Updated" page (node 252:2).
# Each entry is ONE of the 13 confirmed consumer templates, with a structured
# `slices` list (same shape as CZ_FIGMA_TEMPLATES) so generate_stf_email_brief()
# can emit a numbered, slice-by-slice Body Copy section like CZ/TI.
#
# Slice schema:
#   name     — exact slice name (used verbatim in the brief header)
#   type     — "image" (a deliverable design slice) or "text" (content block, no asset)
#   layout   — "Full width" | "50/50 left" | "50/50 right"  (from Figma frame geometry;
#              900px canvas → 450 = half. Rendered as the first "Layout:" field per slice.)
#   fields   — list of "Label: [placeholder]" strings. Labels reuse the CZ copy-field
#              set (HED/DEK/CTA/Eyebrow/Name/Hero CTA/Body HED/Body DEK/Body CTA/
#              Instagram handle) so highlight_copy_value() highlights copywriter-reviewed values.
#   optional — True = designer/copywriter adds only when the send warrants it
#   no_visual— True = image slice with no AI visual direction (CTA button, copy band, kicker)
#
# Node IDs verified 2026-07-20. NOTE: CLAUDE.md's template table had the T7/T8 node
# IDs transposed — the sale hero ("The Gallery Sale") is 252:2283 (t7) and the 3-trend
# editorial ("Fall Trends") is 252:2386 (t8). This catalog uses the verified assignment.
# URL format: ?node-id={id_hyphenated}&m=dev
# ---------------------------------------------------------------------------

STF_FIGMA_FILE_KEY = "Bnne2c9xMqh3fiUp3VfLIM"

STF_FIGMA_TEMPLATES: Dict[str, Dict] = {
    "t1": {
        "node_id": "252:96",
        "name": "Template 1 — Studio By STF (long editorial)",
        "use_cases": ["studio", "custom furniture", "MTO furniture", "made-to-order", "long editorial", "craft story"],
        "description": "Studio By STF long editorial — hero + copy + photo collage grid + optional Shop More Styles kicker.",
        "slices": [
            {"name": "Logo bar and hero", "type": "image", "layout": "Full width", "fields": [
                "Eyebrow: [hero eyebrow, e.g. 'The Studio Collection']",
                "HED: [hero headline]",
                "Link: [hero LP]",
            ]},
            {"name": "Body copy and photo collage", "type": "image", "layout": "Full width", "fields": [
                "Eyebrow: [body eyebrow]",
                "DEK: [1–2 sentence craft/story narrative]",
                "CTA: [body CTA]",
                "Link: [same as hero]",
            ]},
            {"name": "Shop More Styles kicker", "type": "image", "layout": "Full width", "no_visual": True, "optional": True, "fields": [
                "CTA: [Shop More Styles]",
                "Link: [category LP]",
            ]},
        ],
    },
    "t2": {
        "node_id": "252:164",
        "name": "Template 2 — Studio By STF (short + swatch callout)",
        "use_cases": ["studio", "shorter send", "swatch callout", "explore swatches", "category grid"],
        "description": "Studio short — hero + Explore Swatches callout + Shop More Styles header + 2×2 category grid.",
        "slices": [
            {"name": "Logo bar and hero", "type": "image", "layout": "Full width", "fields": [
                "HED: [hero headline]",
                "Link: [hero LP]",
            ]},
            {"name": "Explore Swatches callout", "type": "image", "layout": "Full width", "fields": [
                "CTA: [Explore Swatches]",
                "Link: https://www.stfrank.com/collections/swatches",
            ]},
            {"name": "Shop More Styles header", "type": "image", "layout": "Full width", "fields": [
                "HED: [Shop More Styles]",
                "Link: [same as hero]",
            ]},
            {"name": "Category 1", "type": "image", "layout": "50/50 left", "fields": [
                "Name: [category label, e.g. 'New Releases']",
                "Link: [category LP]",
            ]},
            {"name": "Category 2", "type": "image", "layout": "50/50 right", "fields": [
                "Name: [category label]",
                "Link: [category LP]",
            ]},
            {"name": "Category 3", "type": "image", "layout": "50/50 left", "fields": [
                "Name: [category label]",
                "Link: [category LP]",
            ]},
            {"name": "Category 4", "type": "image", "layout": "50/50 right", "fields": [
                "Name: [category label]",
                "Link: [category LP]",
            ]},
        ],
    },
    "t3": {
        "node_id": "252:854",
        "name": "Template 3 — Color Edit",
        "use_cases": ["color edit", "color story", "palette", "print", "pattern"],
        "description": "Color edit — palette hero + section header + 2×2 category/product grid.",
        "slices": [
            {"name": "Logo bar and color palette hero", "type": "image", "layout": "Full width", "fields": [
                "Eyebrow: [color story eyebrow]",
                "HED: [color/palette name]",
                "DEK: [1–2 sentence color story]",
                "CTA: [hero CTA]",
                "Link: [hero LP]",
            ]},
            {"name": "Section header", "type": "image", "layout": "Full width", "fields": [
                "HED: [section headline]",
                "Link: [same as hero]",
            ]},
            {"name": "Category 1", "type": "image", "layout": "50/50 left", "fields": [
                "Eyebrow: [category eyebrow]",
                "HED: [category headline]",
                "CTA: [category CTA]",
                "Link: [category LP]",
            ]},
            {"name": "Category 2", "type": "image", "layout": "50/50 right", "fields": [
                "Eyebrow: [category eyebrow]",
                "HED: [category headline]",
                "CTA: [category CTA]",
                "Link: [category LP]",
            ]},
            {"name": "Category 3", "type": "image", "layout": "50/50 left", "fields": [
                "Eyebrow: [category eyebrow]",
                "HED: [category headline]",
                "CTA: [category CTA]",
                "Link: [category LP]",
            ]},
            {"name": "Category 4", "type": "image", "layout": "50/50 right", "fields": [
                "Eyebrow: [category eyebrow]",
                "HED: [category headline]",
                "CTA: [category CTA]",
                "Link: [category LP]",
            ]},
        ],
    },
    "t4": {
        "node_id": "252:1038",
        "name": "Template 4 — Print of the Month",
        "use_cases": ["POTM", "print of the month", "featured print", "print spotlight"],
        "description": "Print of the Month — featured print hero + body header + 2×2 product variants + CTA.",
        "slices": [
            {"name": "Logo bar and hero", "type": "image", "layout": "Full width", "fields": [
                "Eyebrow: [print eyebrow, e.g. 'Print of the Month']",
                "HED: [print name]",
                "DEK: [1–2 sentence print origin/story]",
                "CTA: [hero CTA]",
                "Link: [print LP]",
            ]},
            {"name": "Body header", "type": "image", "layout": "Full width", "fields": [
                "Body HED: [body headline, e.g. 'An Instant Icon']",
                "Body DEK: [supporting copy]",
                "Link: [same as hero]",
            ]},
            {"name": "Product variant 1", "type": "image", "layout": "50/50 left", "fields": [
                "Name: [product name]",
                "Link: [product LP]",
            ]},
            {"name": "Product variant 2", "type": "image", "layout": "50/50 right", "fields": [
                "Name: [product name]",
                "Link: [product LP]",
            ]},
            {"name": "Product variant 3", "type": "image", "layout": "50/50 left", "fields": [
                "Name: [product name]",
                "Link: [product LP]",
            ]},
            {"name": "Product variant 4", "type": "image", "layout": "50/50 right", "fields": [
                "Name: [product name]",
                "Link: [product LP]",
            ]},
            {"name": "CTA button", "type": "image", "layout": "Full width", "no_visual": True, "fields": [
                "Body CTA: [closing CTA]",
                "Link: [same as hero]",
            ]},
        ],
    },
    "t5": {
        "node_id": "252:1229",
        "name": "Template 5 — Pattern Drenching",
        "use_cases": ["pattern drenching", "full-bleed pattern", "bold pattern", "maximalism"],
        "description": "Pattern drenching — single full-bleed bold pattern hero image with eyebrow/HED/CTA.",
        "slices": [
            {"name": "Logo bar and full-bleed hero", "type": "image", "layout": "Full width", "fields": [
                "Eyebrow: [hero eyebrow]",
                "HED: [hero headline]",
                "CTA: [hero CTA]",
                "Link: [hero LP]",
            ]},
        ],
    },
    "t6": {
        "node_id": "252:2035",
        "name": "Template 6 — Product Feature / Design Edit",
        "use_cases": ["product feature", "design edit", "outdoor", "pillows", "fabric", "lifestyle feature", "two-section product edit"],
        "description": "Product/lifestyle feature — hero + two product sections (4 products each, 50/50) + closer.",
        "slices": [
            {"name": "Logo bar and hero", "type": "image", "layout": "Full width", "fields": [
                "HED: [hero headline]",
                "DEK: [hero supporting copy]",
                "Hero CTA: [hero CTA]",
                "Link: [hero LP]",
            ]},
            {"name": "Section 1 header", "type": "image", "layout": "Full width", "fields": [
                "Eyebrow: [optional — only if an active sale, e.g. '25% Off']",
                "HED: [section 1 headline]",
                "Link: [section 1 LP]",
            ]},
            {"name": "Section 1 Product 1", "type": "image", "layout": "50/50 left", "fields": [
                "Name: [product name]", "Link: [product LP]",
            ]},
            {"name": "Section 1 Product 2", "type": "image", "layout": "50/50 right", "fields": [
                "Name: [product name]", "Link: [product LP]",
            ]},
            {"name": "Section 1 Product 3", "type": "image", "layout": "50/50 left", "fields": [
                "Name: [product name]", "Link: [product LP]",
            ]},
            {"name": "Section 1 Product 4", "type": "image", "layout": "50/50 right", "fields": [
                "Name: [product name]", "Link: [product LP]",
            ]},
            {"name": "Section 2 header", "type": "image", "layout": "Full width", "fields": [
                "HED: [section 2 headline]",
                "Link: [section 2 LP]",
            ]},
            {"name": "Section 2 Product 1", "type": "image", "layout": "50/50 left", "fields": [
                "Name: [product name]", "Link: [product LP]",
            ]},
            {"name": "Section 2 Product 2", "type": "image", "layout": "50/50 right", "fields": [
                "Name: [product name]", "Link: [product LP]",
            ]},
            {"name": "Section 2 Product 3", "type": "image", "layout": "50/50 left", "fields": [
                "Name: [product name]", "Link: [product LP]",
            ]},
            {"name": "Section 2 Product 4", "type": "image", "layout": "50/50 right", "fields": [
                "Name: [product name]", "Link: [product LP]",
            ]},
            {"name": "Closer", "type": "image", "layout": "Full width", "fields": [
                "HED: [closing section headline]",
                "DEK: [closing supporting copy]",
                "CTA: [closing CTA]",
                "Link: [closer LP]",
            ]},
        ],
    },
    "t7": {
        "node_id": "252:2283",
        "name": "Template 7 — Sale Hero / Last Chance",
        "use_cases": ["sale", "last chance", "final hours", "single hero", "sale announcement", "gallery sale"],
        "description": "Single full-width sale hero image + CTA only. The hero IS the sale message — no separate sale banner is added.",
        "is_sale_hero": True,
        "slices": [
            {"name": "Logo bar and hero", "type": "image", "layout": "Full width", "fields": [
                "Eyebrow: [e.g. 'Last Chance to Shop']",
                "HED: [sale name, e.g. 'The Gallery Sale']",
                "DEK: [discount + categories, e.g. '25% off Art, Wallpaper, & Curtains']",
                "Hero CTA: [Shop Now]",
                "Link: [sale LP or homepage]",
            ]},
        ],
    },
    "t8": {
        "node_id": "252:2386",
        "name": "Template 8 — Trends / Seasonal Edit",
        "use_cases": ["trends", "seasonal edit", "three trends", "trend report", "fall trends", "seasonal trends"],
        "description": "3 named trends (each: photo + copy + CTA) + Shop More Styles header + 2×2 category grid.",
        "slices": [
            {"name": "Logo bar and hero", "type": "image", "layout": "Full width", "fields": [
                "Eyebrow: [e.g. 'The Just In']",
                "HED: [edit name, e.g. 'Fall Trends']",
                "Link: [hero LP]",
            ]},
            {"name": "Trend 1", "type": "image", "layout": "Full width", "fields": [
                "HED: [trend 1 name]",
                "DEK: [trend 1 copy]",
                "CTA: [trend 1 CTA]",
                "Link: [trend 1 LP]",
            ]},
            {"name": "Trend 2", "type": "image", "layout": "Full width", "fields": [
                "HED: [trend 2 name]",
                "DEK: [trend 2 copy]",
                "CTA: [trend 2 CTA]",
                "Link: [trend 2 LP]",
            ]},
            {"name": "Trend 3", "type": "image", "layout": "Full width", "fields": [
                "HED: [trend 3 name]",
                "DEK: [trend 3 copy]",
                "CTA: [trend 3 CTA]",
                "Link: [trend 3 LP]",
            ]},
            {"name": "Shop More Styles header", "type": "image", "layout": "Full width", "fields": [
                "HED: [Shop More Styles]",
                "Link: [same as hero]",
            ]},
            {"name": "Category 1", "type": "image", "layout": "50/50 left", "fields": [
                "Name: [category label]", "Link: [category LP]",
            ]},
            {"name": "Category 2", "type": "image", "layout": "50/50 right", "fields": [
                "Name: [category label]", "Link: [category LP]",
            ]},
            {"name": "Category 3", "type": "image", "layout": "50/50 left", "fields": [
                "Name: [category label]", "Link: [category LP]",
            ]},
            {"name": "Category 4", "type": "image", "layout": "50/50 right", "fields": [
                "Name: [category label]", "Link: [category LP]",
            ]},
        ],
    },
    "t9": {
        "node_id": "252:427",
        "name": "Template 9 — UGC (Styled By You)",
        "use_cases": ["UGC", "styled by you", "influencer", "customer photos", "community", "instagram"],
        "description": "Hero UGC photo + 2 more UGC photos with product tags + Instagram handles + CTA button.",
        "slices": [
            {"name": "Logo bar and hero (UGC photo 1)", "type": "image", "layout": "Full width", "fields": [
                "HED: [Styled By You headline]",
                "DEK: [intro copy]",
                "Hero CTA: [Shop Now]",
                "Name: [featured product name]",
                "Instagram handle: @[handle]",
                "Link: [hero LP]",
            ]},
            {"name": "UGC photo 2", "type": "image", "layout": "Full width", "fields": [
                "Name: [featured product name]",
                "Instagram handle: @[handle]",
                "Link: [product LP]",
            ]},
            {"name": "UGC photo 3", "type": "image", "layout": "Full width", "fields": [
                "Name: [featured product name]",
                "Instagram handle: @[handle]",
                "Link: [product LP]",
            ]},
            {"name": "CTA button", "type": "image", "layout": "Full width", "no_visual": True, "fields": [
                "CTA: [Shop Now]",
                "Link: [same as hero]",
            ]},
        ],
    },
    "t10": {
        "node_id": "252:2654",
        "name": "Template 10 — Destination",
        "use_cases": ["destination", "travel", "editorial journey", "Lake Como", "Milan", "Paris"],
        "description": "Destination editorial — hero + 3 destination sections (HED/DEK/CTA each) + kicker.",
        "slices": [
            {"name": "Logo bar and hero", "type": "image", "layout": "Full width", "fields": [
                "HED: [destination headline]",
                "DEK: [1–2 sentence destination intro]",
                "Hero CTA: [hero CTA]",
                "Link: [hero LP]",
            ]},
            {"name": "Section 1", "type": "image", "layout": "Full width", "fields": [
                "HED: [section 1 headline]", "DEK: [section 1 copy]", "CTA: [section 1 CTA]", "Link: [section 1 LP]",
            ]},
            {"name": "Section 2", "type": "image", "layout": "Full width", "fields": [
                "HED: [section 2 headline]", "DEK: [section 2 copy]", "CTA: [section 2 CTA]", "Link: [section 2 LP]",
            ]},
            {"name": "Section 3", "type": "image", "layout": "Full width", "fields": [
                "HED: [section 3 headline]", "DEK: [section 3 copy]", "CTA: [section 3 CTA]", "Link: [section 3 LP]",
            ]},
            {"name": "Kicker", "type": "image", "layout": "Full width", "fields": [
                "HED: [kicker headline]", "CTA: [kicker CTA]", "Link: [kicker LP]",
            ]},
        ],
    },
    "t11": {
        "node_id": "252:1439",
        "name": "Template 11 — Moodboard / Lookbook",
        "use_cases": ["moodboard", "seasonal moodboard", "mosaic", "lifestyle collage", "typographic hero"],
        "description": "Seasonal moodboard — typographic hero + intro copy + lifestyle collage grid + category links.",
        "slices": [
            {"name": "Logo bar and hero", "type": "image", "layout": "Full width", "fields": [
                "HED: [big typographic moodboard name]",
                "Link: [hero LP]",
            ]},
            {"name": "Intro copy", "type": "image", "layout": "Full width", "fields": [
                "Body DEK: [1–2 sentence intro]",
                "Body CTA: [intro CTA]",
                "Link: [same as hero]",
            ]},
            {"name": "Lifestyle collage grid", "type": "image", "layout": "Full width", "fields": [
                "DEK: [optional collage caption]",
                "Link: [same as hero]",
            ]},
            {"name": "Category links", "type": "image", "layout": "Full width", "optional": True, "fields": [
                "CTA: [Shop More Styles]",
                "Link: [category LP]",
            ]},
        ],
    },
    "t12": {
        "node_id": "252:1611",
        "name": "Template 12 — Lookbook / Seasonal Launch",
        "use_cases": ["lookbook", "seasonal launch", "collection launch", "date callout"],
        "description": "Lookbook / seasonal launch — single hero image + date callout + CTA.",
        "slices": [
            {"name": "Logo bar and hero", "type": "image", "layout": "Full width", "fields": [
                "HED: [launch/lookbook headline]",
                "Hero CTA: [hero CTA]",
                "Date: [launch/event date callout]",
                "Link: [hero LP]",
            ]},
        ],
    },
    "t13": {
        "node_id": "252:2783",
        "name": "Template 13 — Back in Stock",
        "use_cases": ["back in stock", "BIS", "restocked", "available again", "waitlist"],
        "description": "Hero-only back-in-stock announcement + copy band.",
        "slices": [
            {"name": "Logo bar and hero", "type": "image", "layout": "Full width", "fields": [
                "HED: [back-in-stock headline]",
                "Hero CTA: [Shop Now]",
                "Link: [BIS/hero LP]",
            ]},
            {"name": "Copy band", "type": "image", "layout": "Full width", "no_visual": True, "fields": [
                "DEK: [back-in-stock supporting copy]",
                "Link: [same as hero]",
            ]},
        ],
    },
}

# STF standalone kicker / category blocks (reference catalog).
# These are optional add-ons a copywriter/designer can append to a send; STF has no
# deterministic auto-cycling rule (unlike CZ), so generate_stf_email_brief() does NOT
# auto-attach them. Kept as data for briefing reference and future wiring.
# Node IDs from the "Templates Updated" page (252:2). Layout per Figma geometry.
STF_KICKERS: Dict[str, Dict] = {
    "swatch_kicker_1": {"node_id": "252:2473", "name": "Swatch Kicker 1", "layout": "Full width",
                         "description": "Explore Swatches — minimal callout."},
    "category_block_1": {"node_id": "252:2484", "name": "Category Block 1", "layout": "Full width",
                          "description": "Shop More Styles — stacked text links."},
    "category_block_2": {"node_id": "252:2514", "name": "Category Block 2", "layout": "50/50 grid",
                          "description": "Sale only — 'X% Off Sitewide' 6-cell category grid (50/50 pairs)."},
    "category_block_3": {"node_id": "252:2552", "name": "Category Block 3", "layout": "50/50 grid",
                          "description": "Shop More Styles — 2×2 photo grid (50/50 pairs)."},
    "swatch_kicker_2": {"node_id": "252:2571", "name": "Swatch Kicker 2", "layout": "Full width",
                         "description": "Explore Swatches — with lifestyle image."},
    "edit_kicker_1": {"node_id": "252:2594", "name": "Edit Kicker 1", "layout": "50/50 pair",
                       "description": "'Tis the Season edit kicker (50/50 pair)."},
    "category_block_4": {"node_id": "252:2603", "name": "Category Block 4", "layout": "Full width",
                          "description": "Sale reminders — 'Up to X% Off' 4 full-width category rows."},
    "category_block_5": {"node_id": "252:2620", "name": "Category Block 5", "layout": "Full width",
                          "description": "Alternate 'Tis the Season kicker."},
}

# ---------------------------------------------------------------------------
# STF canonical link map — single source for both SMS and email brief LPs.
# data/stf_links.yaml is the source of truth; this dict is derived from it.
_stf_links_path = Path(__file__).parent.parent / "data" / "stf_links.yaml"
with open(_stf_links_path) as _f:
    _stf_links_data = yaml.safe_load(_f)
# Maps label → URL path (slug only, no domain) for use in STF_EMAIL_IDEAS lp fields.
_STF_LP: Dict[str, str] = {
    item["label"]: "/" + item["url"].split("stfrank.com/", 1)[-1]
    for section in _stf_links_data.values()
    if isinstance(section, list)
    for item in section
}

# ---------------------------------------------------------------------------
# BUR (Burrow) canonical link map — single source for both SMS and email brief LPs.
# data/bur_links.yaml is the source of truth; used directly by generate_bw_email_brief().
_bur_links_path = Path(__file__).parent.parent / "data" / "bur_links.yaml"
with open(_bur_links_path) as _f:
    _bur_links_data = yaml.safe_load(_f)

# ---------------------------------------------------------------------------
# STF filler email ideas
# Used to suggest gap-filling emails when a week is under the target send
# count (typically 3/week). Each entry has:
#   name          — human-readable task name (used verbatim as the Asana task name)
#   type          — "standalone" or "category_feature" (umbrella type)
#   parent        — for category_feature entries, the parent type name
#   asana_category — Asana category option GID
#   figma_section — LEGACY / unused at runtime: references the old coarse
#                   STF_FIGMA_TEMPLATES section keys (print/product/studio/…) that were
#                   replaced by per-template keys (t1–t13). Kept only as a human hint.
#   lp            — default LP slug on stfrank.com (None = TBD / merch to provide)
#                   Sourced from _STF_LP (derived from data/stf_links.yaml)
#   notes         — any caveats, inventory warnings, or briefing notes
#   available     — False = do NOT suggest (e.g. bedding out of stock)
#   recency_days  — minimum days since last send of this type before re-using
# ---------------------------------------------------------------------------
STF_EMAIL_IDEAS: List[Dict] = [
    {
        "name": "POTM",
        "type": "standalone",
        "parent": None,
        "asana_category": CATEGORY_OPTIONS["editorial"],
        "figma_section": "print",
        "lp": _STF_LP.get("Prints"),
        "notes": "Monthly send — one per month. Feature the current month's print.",
        "available": True,
        "recency_days": 28,
    },
    {
        "name": "Color Edit",
        "type": "standalone",
        "parent": None,
        "asana_category": CATEGORY_OPTIONS["editorial"],
        "figma_section": "print",
        "lp": None,  # merch to build a color edit LP or fallback to /collections/prints
        "notes": "Color story across prints. LP TBD from merch — fallback: /collections/prints.",
        "available": True,
        "recency_days": 21,
    },
    {
        "name": "Print Spotlight",
        "type": "standalone",
        "parent": None,
        "asana_category": CATEGORY_OPTIONS["editorial"],
        "figma_section": "print",
        "lp": _STF_LP.get("Prints"),
        "notes": "Deep-dive on a single print — origin story, styling, across product types.",
        "available": True,
        "recency_days": 21,
    },
    {
        "name": "Trend Report",
        "type": "standalone",
        "parent": None,
        "asana_category": CATEGORY_OPTIONS["editorial"],
        "figma_section": "moodboard",
        "lp": _STF_LP.get("Best Sellers"),
        "notes": "Seasonal trend report. Avoid sending more than once per season (~90 days).",
        "available": True,
        "recency_days": 90,
    },
    {
        "name": "Destination",
        "type": "standalone",
        "parent": None,
        "asana_category": CATEGORY_OPTIONS["editorial"],
        "figma_section": "destinations",
        "lp": None,  # merch to build destination LP or fallback to /collections/decor
        "notes": "Destination editorial. LP TBD — merch may build a destination-specific LP.",
        "available": True,
        "recency_days": 21,
    },
    {
        "name": "UGC",
        "type": "standalone",
        "parent": None,
        "asana_category": CATEGORY_OPTIONS["editorial"],
        "figma_section": "ugc",
        "lp": None,
        "notes": "CRM to connect with Martha Sniezek/social on UGC content to feature.",
        "available": True,
        "recency_days": 21,
    },
    # --- Category Features ---
    {
        "name": "Category Feature: Pillows",
        "type": "category_feature",
        "parent": "Category Features",
        "asana_category": CATEGORY_OPTIONS["product_category"],
        "figma_section": "product",
        "lp": _STF_LP.get("Pillows"),
        "notes": "Interior/decorative pillows. Distinct from Outdoor Pillows.",
        "available": True,
        "recency_days": 42,
    },
    {
        "name": "Category Feature: Outdoor Pillows",
        "type": "category_feature",
        "parent": "Category Features",
        "asana_category": CATEGORY_OPTIONS["product_category"],
        "figma_section": "product",
        "lp": _STF_LP.get("Outdoor Pillows"),
        "notes": "Outdoor-specific pillow feature. Best in spring/summer.",
        "available": True,
        "recency_days": 42,
    },
    {
        "name": "Category Feature: FBTY",
        "type": "category_feature",
        "parent": "Category Features",
        "asana_category": CATEGORY_OPTIONS["product_category"],
        "figma_section": "product",
        "lp": _STF_LP.get("Fabric by the Yard"),
        "notes": "Interior fabric by the yard. Keep distinct from Outdoor FBTY.",
        "available": True,
        "recency_days": 42,
    },
    {
        "name": "Category Feature: Outdoor FBTY",
        "type": "category_feature",
        "parent": "Category Features",
        "asana_category": CATEGORY_OPTIONS["product_category"],
        "figma_section": "product",
        "lp": _STF_LP.get("Outdoor Fabric"),
        "notes": "Outdoor performance fabric by the yard. Best in spring/summer.",
        "available": True,
        "recency_days": 42,
    },
    {
        "name": "Category Feature: Wallpaper",
        "type": "category_feature",
        "parent": "Category Features",
        "asana_category": CATEGORY_OPTIONS["product_category"],
        "figma_section": "product",
        "lp": _STF_LP.get("Wallpaper"),
        "notes": None,
        "available": True,
        "recency_days": 42,
    },
    {
        "name": "Category Feature: Furniture",
        "type": "category_feature",
        "parent": "Category Features",
        "asana_category": CATEGORY_OPTIONS["product_category"],
        "figma_section": "studio",
        "lp": _STF_LP.get("Furniture"),
        "notes": "Use Studio By STF template. Can also feature suzani upholstered pieces.",
        "available": True,
        "recency_days": 42,
    },
    {
        "name": "Category Feature: Curtains",
        "type": "category_feature",
        "parent": "Category Features",
        "asana_category": CATEGORY_OPTIONS["product_category"],
        "figma_section": "product",
        "lp": _STF_LP.get("Curtains"),
        "notes": "Highlight French pleat and/or rod pocket styles. "
                 "Sub-collections: /collections/french-pleat-curtains, /collections/rod-pocket-curtains.",
        "available": True,
        "recency_days": 42,
    },
    {
        "name": "Category Feature: Surfboards",
        "type": "category_feature",
        "parent": "Category Features",
        "asana_category": CATEGORY_OPTIONS["product_category"],
        "figma_section": "surfboards",
        "lp": _STF_LP.get("Surfboards"),
        "notes": "Unique STF category. Alternate between the 2 surfboard templates.",
        "available": True,
        "recency_days": 60,
    },
    {
        "name": "Swatch Push",
        "type": "category_feature",
        "parent": "Category Features",
        "asana_category": CATEGORY_OPTIONS["editorial"],
        "figma_section": "product",
        "lp": _STF_LP.get("Swatches"),
        "notes": "Drive free swatch orders. Add Swatch Kicker (node 1-489) from Figma file.",
        "available": True,
        "recency_days": 35,
    },
    {
        "name": "Category Feature: Throws",
        "type": "category_feature",
        "parent": "Category Features",
        "asana_category": CATEGORY_OPTIONS["product_category"],
        "figma_section": "product",
        "lp": _STF_LP.get("Throws"),
        "notes": "Small category — limited inventory. Use sparingly; confirm stock before briefing.",
        "available": True,
        "recency_days": 60,
    },
    {
        "name": "Category Feature: Bedding",
        "type": "category_feature",
        "parent": "Category Features",
        "asana_category": CATEGORY_OPTIONS["product_category"],
        "figma_section": "product",
        "lp": _STF_LP.get("Bedding"),
        "notes": "NOT currently available — bedding is largely out of stock. Do not suggest until re-stocked.",
        "available": False,
        "recency_days": 42,
    },
]

# Convenience: only ideas currently available to suggest
STF_EMAIL_IDEAS_AVAILABLE: List[Dict] = [
    idea for idea in STF_EMAIL_IDEAS if idea["available"]
]

# ---------------------------------------------------------------------------
# STF product suggestion — Snowflake best-seller queries + variety tracking
# ---------------------------------------------------------------------------

# SQL WHERE clause fragments for PROD.ANALYTICS_ST_FRANK.order_items.
# Keyed by the idea name from STF_EMAIL_IDEAS so they match automatically.
STF_PRODUCT_CATEGORY_FILTERS: Dict[str, str] = {
    "Category Feature: Pillows": (
        "PRODUCT_TYPE = 'Pillow' AND ITEM_TITLE NOT ILIKE '%Outdoor%'"
    ),
    "Category Feature: Outdoor Pillows": (
        "PRODUCT_TYPE = 'Pillow' AND ITEM_TITLE ILIKE '%Outdoor%'"
    ),
    "Category Feature: FBTY": (
        "PRODUCT_TYPE IN ('Fabric by the Yard', 'Material') "
        "AND ITEM_TITLE NOT ILIKE '%Wallpaper%' "
        "AND ITEM_TITLE NOT ILIKE '%Outdoor%' "
        "AND ITEM_TITLE NOT ILIKE '%Performance%'"
    ),
    "Category Feature: Outdoor FBTY": (
        "(PRODUCT_TYPE IN ('Fabric by the Yard', 'Material', 'Yardage') "
        "AND (ITEM_TITLE ILIKE '%Outdoor%' OR ITEM_TITLE ILIKE '%Performance%'))"
    ),
    "Category Feature: Wallpaper": (
        "ITEM_TITLE ILIKE '%Wallpaper%'"
    ),
    "Category Feature: Furniture": (
        "PRODUCT_TYPE = 'Furniture'"
    ),
    "Category Feature: Curtains": (
        "PRODUCT_TYPE = 'Curtains'"
    ),
    "Category Feature: Surfboards": (
        "PRODUCT_TYPE = 'Surfboard'"
    ),
    "Category Feature: Throws": (
        "PRODUCT_TYPE IN ('Blanket', 'Textile') "
        "AND (ITEM_TITLE ILIKE '%Throw%' OR ITEM_TITLE ILIKE '%Blanket%')"
    ),
    "Swatch Push": (
        "PRODUCT_TYPE = 'Swatch'"
    ),
}


def _stf_product_url(title: str) -> str:
    """Convert a product title to a stfrank.com product URL."""
    handle = title.lower()
    handle = re.sub(r"[^a-z0-9\s-]", "", handle)
    handle = re.sub(r"\s+", "-", handle.strip())
    return f"https://www.stfrank.com/products/{handle}"


def _load_stf_product_log() -> Dict[str, List[Dict]]:
    """Load the STF product suggestions log ({category: [{name, date}, ...]})."""
    if not STF_PRODUCT_LOG_FILE.exists():
        return {}
    with open(STF_PRODUCT_LOG_FILE) as f:
        data = yaml.safe_load(f) or {}
    return data.get("suggestions", {})


def _save_stf_product_log(log: Dict[str, List[Dict]]) -> None:
    """Persist the STF product suggestions log."""
    STF_PRODUCT_LOG_FILE.parent.mkdir(parents=True, exist_ok=True)
    with open(STF_PRODUCT_LOG_FILE, "w") as f:
        yaml.dump(
            {"suggestions": log, "last_updated": datetime.now().isoformat()},
            f,
            allow_unicode=True,
        )


def _get_category_filter_for_story(story: str) -> Optional[Tuple[str, str]]:
    """Return (idea_name, sql_filter) for the given story, or None if not applicable.

    For POTM / Print Spotlight, derives a filter from the print name in the story.
    For Category Feature emails, looks up STF_PRODUCT_CATEGORY_FILTERS directly.
    """
    story_lower = story.lower()

    # Direct match against known category filters
    for idea_name, sql_filter in STF_PRODUCT_CATEGORY_FILTERS.items():
        if idea_name.lower() in story_lower:
            return idea_name, sql_filter

    # POTM / Print Spotlight — extract print name after the colon
    potm_match = re.match(r"(?:potm|print spotlight|print of the month)[:\s]+(.+)", story, re.I)
    if potm_match:
        print_name = potm_match.group(1).strip()
        # Escape single quotes for SQL
        safe_name = print_name.replace("'", "''")
        sql_filter = f"ITEM_TITLE ILIKE '%{safe_name}%'"
        return story, sql_filter

    return None


def fetch_stf_best_sellers(sql_filter: str, limit: int = 20) -> List[Dict]:
    """Query PROD.ANALYTICS_ST_FRANK for best-selling products matching sql_filter.

    Returns list of dicts with keys: name, product_type, revenue, units, url.
    Returns [] on any error (Snowflake unavailable, query fails, etc.).
    """
    try:
        sys.path.insert(0, str(Path(__file__).parent))
        from snowflake_client import get_snowflake_client  # type: ignore
    except ImportError:
        return []

    query = f"""
        SELECT
            oi.ITEM_TITLE                          AS name,
            oi.PRODUCT_TYPE                        AS product_type,
            ROUND(SUM(oi.GROSS_ITEM_REVENUE), 2)  AS revenue,
            SUM(oi.QUANTITY)                       AS units
        FROM PROD.ANALYTICS_ST_FRANK.order_items oi
        JOIN PROD.ANALYTICS_ST_FRANK.orders o ON oi.ORDER_ID = o.ORDER_ID
        WHERE o.ORDER_CREATED_AT >= DATEADD('day', -90, CURRENT_DATE())
          AND o.FINANCIAL_STATUS IN ('paid', 'partially_refunded')
          AND ({sql_filter})
        GROUP BY 1, 2
        ORDER BY revenue DESC
        LIMIT {int(limit)}
    """
    try:
        client = get_snowflake_client(schema="ANALYTICS_ST_FRANK", database="PROD")
        rows = client.execute_query(query)
        results = []
        for row in (rows or []):
            title = row.get("NAME") or row.get("name", "")
            if title:
                results.append({
                    "name": title,
                    "product_type": row.get("PRODUCT_TYPE") or row.get("product_type", ""),
                    "revenue": float(row.get("REVENUE") or row.get("revenue") or 0),
                    "units": int(row.get("UNITS") or row.get("units") or 0),
                    "url": _stf_product_url(title),
                })
        return results
    except Exception as e:
        print(f"  [STF products] Snowflake query failed: {e}")
        return []


def get_stf_product_suggestions(
    story: str,
    n: int = 4,
    recency_days: int = 60,
    send_date: Optional[str] = None,
) -> List[Dict]:
    """Return up to n best-selling STF products for the given email story,
    skipping products suggested in the last recency_days to ensure variety.

    Logs chosen products to STF_PRODUCT_LOG_FILE so they won't repeat soon.

    Returns [] if no category filter applies to this story type.
    """
    filter_result = _get_category_filter_for_story(story)
    if not filter_result:
        return []

    idea_name, sql_filter = filter_result
    ref_date = datetime.strptime(send_date, "%Y-%m-%d").date() if send_date else datetime.today().date()

    # Load recently suggested products for this category
    log = _load_stf_product_log()
    recent_entries = log.get(idea_name, [])
    recently_used: set = set()
    for entry in recent_entries:
        try:
            used_date = datetime.strptime(entry["date"], "%Y-%m-%d").date()
            if (ref_date - used_date).days < recency_days:
                recently_used.add(entry["name"].lower())
        except (KeyError, ValueError):
            continue

    # Fetch a large pool from Snowflake and filter out recently used
    pool = fetch_stf_best_sellers(sql_filter, limit=40)
    fresh = [p for p in pool if p["name"].lower() not in recently_used]

    # If we've cycled through everything, relax and use the full pool
    candidates = fresh if len(fresh) >= n else pool

    chosen = candidates[:n]

    # Log the chosen products
    if chosen and send_date:
        updated_log = dict(log)
        existing = updated_log.get(idea_name, [])
        for p in chosen:
            existing.append({"name": p["name"], "date": send_date})
        # Keep only entries newer than 180 days to avoid unbounded file growth
        cutoff = ref_date
        from datetime import timedelta
        keep_cutoff = cutoff - timedelta(days=180)
        existing = [
            e for e in existing
            if datetime.strptime(e["date"], "%Y-%m-%d").date() >= keep_cutoff
        ]
        updated_log[idea_name] = existing
        _save_stf_product_log(updated_log)

    return chosen


def format_stf_products_for_notes(products: List[Dict]) -> List[str]:
    """Format product suggestion dicts into html_notes bullet strings."""
    lines = []
    for p in products:
        lines.append(f"{p['name']} — {p['url']}")
    return lines


def suggest_stf_filler(
    week_sends: List[str],
    recent_sends: List[Dict],
    n_needed: int,
    reference_date_str: str,
) -> List[Dict]:
    """Suggest STF filler email ideas to hit the weekly send target.

    Args:
        week_sends:         List of task-name strings already planned for the week.
        recent_sends:       List of dicts with keys 'name' (task name) and
                            'send_date' (YYYY-MM-DD string) for sends in the
                            past ~90 days.
        n_needed:           How many additional emails to suggest.
        reference_date_str: The Monday of the target week as 'YYYY-MM-DD'.

    Returns:
        List of up to n_needed STF_EMAIL_IDEAS entries, ranked by best fit.
    """
    from datetime import date as _date, datetime as _dt

    ref_date = _dt.strptime(reference_date_str, "%Y-%m-%d").date()

    # Build a map of idea name → most recent send date
    def _normalize(s: str) -> str:
        return s.lower().strip()

    recent_map: Dict[str, _date] = {}
    for r in recent_sends:
        name = _normalize(r.get("name", ""))
        try:
            d = _dt.strptime(r["send_date"], "%Y-%m-%d").date()
        except (KeyError, ValueError):
            continue
        # Match by keyword overlap with idea names
        for idea in STF_EMAIL_IDEAS_AVAILABLE:
            idea_lower = _normalize(idea["name"])
            if idea_lower in name or name in idea_lower:
                existing = recent_map.get(idea["name"])
                if existing is None or d > existing:
                    recent_map[idea["name"]] = d

    # Names already planned this week (normalized)
    planned = {_normalize(s) for s in week_sends}

    candidates = []
    for idea in STF_EMAIL_IDEAS_AVAILABLE:
        idea_lower = _normalize(idea["name"])

        # Skip if already planned this week
        if any(idea_lower in p or p in idea_lower for p in planned):
            continue

        # Compute days since last send
        last_sent = recent_map.get(idea["name"])
        days_since = (ref_date - last_sent).days if last_sent else 999

        # Skip if sent too recently
        if days_since < idea["recency_days"]:
            continue

        candidates.append((days_since, idea))

    # Sort by longest time since last sent (most overdue first)
    candidates.sort(key=lambda x: -x[0])
    return [idea for _, idea in candidates[:n_needed]]


# ID (Interior Define) Figma template catalog
# Sourced from Figma file oFsPeUJ1s8oK5s6mbLl376 (Lifecycle: Email Template Library).
# Core Designs A–BNDL are individual templates (use v1 node IDs shown here).
# Specialty sections (Swatch Talk, In Stock, Retail, Guides) are section-level — designer picks within.
# URL format: ?node-id={id_hyphenated}
# ---------------------------------------------------------------------------

ID_FIGMA_FILE_KEY = "oFsPeUJ1s8oK5s6mbLl376"

ID_FIGMA_TEMPLATES: Dict[str, Dict] = {
    "A": {
        "node_id": "1:760",
        "name": "Core Design A",
        "use_cases": ["seasonal editorial", "lifestyle story", "multi-room", "editorial", "fall focus"],
        "description": "Full lifestyle editorial — stacked hero room vignettes with CTAs. Best for seasonal editorial or lifestyle story.",
    },
    "B": {
        "node_id": "1:920",
        "name": "Core Design B",
        "use_cases": ["multi-product", "named products", "shop the look", "multiple chairs", "multiple pieces"],
        "description": "Multi-product editorial — lifestyle hero + individually named products with CTAs. Best for featuring multiple named products.",
    },
    "C": {
        "node_id": "1:1032",
        "name": "Collection",
        "use_cases": ["single collection", "collection launch", "product spotlight", "sofa launch", "one product"],
        "description": "Single collection spotlight — large hero + detail shots + fabric customization CTA. Best for launching one specific collection.",
    },
    "D": {
        "node_id": "1:1092",
        "name": "Made for Me",
        "use_cases": ["MTO", "made to order", "customization", "personalization", "UGC", "testimonial"],
        "description": "Personalization-led — lifestyle room + customer testimonial + customization features list. Best for MTO/customization story.",
    },
    "E": {
        "node_id": "1:1411",
        "name": "Product Focus",
        "use_cases": ["new arrivals", "product drop", "multiple new products", "arrivals"],
        "description": "New Arrivals — large hero + individual product cards stacked vertically. Best for new product drops.",
    },
    "F": {
        "node_id": "2:197",
        "name": "Collection Focus",
        "use_cases": ["bedroom", "bed frame", "furniture story", "craftsmanship", "single product with story"],
        "description": "Single product hero + craftsmanship/story copy + lifestyle bedroom context. Best for bedroom collection or furniture with a story.",
    },
    "G": {
        "node_id": "2:385",
        "name": "Category Feature",
        "use_cases": ["new arrivals category", "shop by category", "category browse", "arrivals with categories"],
        "description": "Lifestyle hero + category browse section below. Best for new arrivals with a shop-by-category CTA.",
    },
    "H": {
        "node_id": "2:467",
        "name": "Product Categories",
        "use_cases": ["category browse", "accent edit", "accessories", "multi-category grid", "lighting", "rugs", "tables", "accent"],
        "description": "Editorial hero + multi-category product grid (2×2 or 2×3). Best for accent/accessory edits or multi-category browse.",
    },
    "I": {
        "node_id": "1:3253",
        "name": "Lifestyle + Product Highlight",
        "use_cases": ["dining", "entertaining", "room editorial", "dining chairs", "dining tables", "room focus"],
        "description": "Room-specific editorial — hero + 3 curated sections with product pairs. Best for dining/entertaining room focus.",
    },
    "J": {
        "node_id": "1:3331",
        "name": "Render Body Send",
        "use_cases": ["sale", "percent off", "sale products", "promotion", "pricing", "sale email"],
        "description": "Sale product listing — lifestyle hero + individual product cards with sale prices. Best for sale sends with product highlights.",
    },
    "K": {
        "node_id": "2:2119",
        "name": "Graphic Number Treatment",
        "use_cases": ["new arrivals graphic", "numbered products", "bold type", "editorial new arrivals", "graphic"],
        "description": 'Typography-led — bold "new new new" treatment + numbered product list. Best for new arrivals with a graphic/editorial feel.',
    },
    "L": {
        "node_id": "1:3565",
        "name": "Editorial Highlight",
        "use_cases": ["editorial", "catalog", "design inspiration", "storytelling", "room story", "editorial catalog"],
        "description": "Editorial catalog style — hero + 3 side-by-side editorial story sections. Best for design inspiration or editorial storytelling.",
    },
    "M": {
        "node_id": "2:2314",
        "name": "Hero Grid",
        "use_cases": ["hero grid", "product grid", "many products", "grid layout"],
        "description": "Hero + product grid layout.",
    },
    "N": {
        "node_id": "2:2374",
        "name": "Hero Gif",
        "use_cases": ["quick ship", "fast delivery", "in stock", "MTO awareness", "delivery time", "faster"],
        "description": '"Faster by Design" — single product hero + Quick Ship/MTO dual messaging. Best for Quick Ship promo or MTO awareness.',
    },
    "BNDL": {
        "node_id": "51:1161",
        "name": "Hero BNDL",
        "use_cases": ["bundle", "BNDL", "buy now decide later", "fabric selection", "BNDL program"],
        "description": '"Buy now / Decide later" split-screen sofa comparison. Best for the BNDL program or fabric-selection concept.',
    },
    "swatch_talk": {
        "node_id": "2:2194",
        "name": "Swatch Talk",
        "use_cases": ["swatch talk", "swatches", "fabric samples", "swatch editorial", "fabric colors"],
        "description": "Swatch Talk section — multiple layouts for fabric/swatch-focused sends.",
    },
    "instock": {
        "node_id": "2:2313",
        "name": "In Stock + Quick Ship",
        "use_cases": ["in stock", "quick ship", "fast delivery", "available now", "in-stock"],
        "description": "In Stock and Quick Ship section — layouts for in-stock availability campaigns.",
    },
    "retail": {
        "node_id": "2:2195",
        "name": "Retail",
        "use_cases": ["retail event", "partner event", "sip and sit", "showroom", "in-store event", "event invite"],
        "description": "Retail section — templates for showroom events, partner events, and in-store experiences.",
    },
    "guides": {
        "node_id": "2:2196",
        "name": "Guides",
        "use_cases": ["buying guide", "sectional guide", "rug guide", "comfort guide", "how to choose", "guide", "educational"],
        "description": "Guides section — educational templates for sectional, rug, and comfort buying guides.",
    },
}

# TI (The Inside) Figma template catalog
# Sourced from Figma file B2DuEEQLOCrQNhY3iKTkhi (TI Templates).
# URL format: ?node-id={id_hyphenated}
# ---------------------------------------------------------------------------

TI_FIGMA_FILE_KEY = "B2DuEEQLOCrQNhY3iKTkhi"

TI_FIGMA_TEMPLATES: Dict[str, Dict] = {
    "potm": {
        "node_id": "174:32",
        "name": "POTM — Print of the Month",
        "use_cases": ["print of the month", "POTM", "single print spotlight", "featured print", "print hero"],
        "description": "Single print spotlight — hero + editorial copy + product CTA.",
        "slices_text": (
            'Slice 1 — Hero · Logo / Eyebrow: "PRINT OF THE MONTH" (fixed) / HED: [print name] / DEK: [editorial copy] / CTA: [CTA copy] / Link: [print LP]\n'
            "Slice 2 — Lifestyle image · Descriptor: [2–4 words, italicized, e.g. print name] / Link: [print LP]\n"
            "Slice 3 — Image (no copy) · Link: [print LP]\n"
            "Slice 4 — CTA block · Copy: [above-CTA copy] / CTA: [CTA copy] / Link: [print LP]"
        ),
    },
    "swatch_story": {
        "node_id": "174:76",
        "name": "Swatch Story — Swatch / Trend Print Story",
        "use_cases": ["swatch story", "trend print", "multiple swatches", "swatch grid", "print trend", "seasonal print round-up", "fabric edit"],
        "description": "Hero + multi-swatch product image grid (3 rows default).",
        "slices_text": (
            "Slice 1 — Hero · Logo / HED: [theme title] / Sub-HED: [italic phrase] / DEK: [editorial copy] / CTA: [CTA copy] / Note: hero includes swatch image overlaid on background — deliver as one asset / Link: https://www.theinside.com/fabric-swatches\n"
            "Slice 2 — Swatch grid [full-width; 3 rows, alternating swatch image side] · Row 1: Image left / Copy right · Print name: [name] / Descriptor: [2–3 word tag] · Row 2: Copy left / Image right · Print name: [name] / Descriptor: [2–3 word tag] · Row 3: Image left / Copy right · Print name: [name] / Descriptor: [2–3 word tag] / Link: https://www.theinside.com/fabric-swatches\n"
            "Slice 3 — CTA block · Background image / HED: [copy] / CTA: [CTA copy] / Link: https://www.theinside.com/fabric-swatches"
        ),
    },
    "swatch_party": {
        "node_id": "174:3",
        "name": "Swatch Party — Swatch Edit",
        "use_cases": ["swatch party", "free swatches", "swatch promo", "order swatches", "swatch offer"],
        "description": "Evergreen swatch promo — animated GIF cycling through prints. All copy is fixed.",
        "slices_text": (
            'Slice 1 — Full email · Logo / HED: "Swatch Party" (fixed) / CTA: "ORDER FREE SWATCHES" (fixed) / DEK: "Major savings are right around the corner. Get a head start and bring home five free swatches now." (fixed) / Promo code: "USE CODE: 5FREESWATCHES" (fixed) / Animated GIF: [prints to feature — background + swatch image per print, cycling] / Link: https://www.theinside.com/fabric-swatches'
        ),
    },
    "product_multi": {
        "node_id": "174:202",
        "name": "Product Multi — Multi-Category Product Feature",
        "use_cases": ["multi-category", "three products", "product feature", "beds and curtains", "soft goods", "outdoor", "product round-up", "category mix"],
        "description": "Hero + 3 product/collection lifestyle images. Optional BNDL kicker.",
        "slices_text": (
            "Slice 1 — Hero · Logo / HED: [headline] / DEK: [editorial copy] / CTA: [CTA copy] / Link: [collection LP]\n"
            "Slice 2 — Product/Collection 1 · Lifestyle image / Name: [product or collection name] / Color/variant: [if single product] or short descriptor: [if collection] / Link: [product or collection LP]\n"
            "Slice 3 — Product/Collection 2 · Lifestyle image / Name: [product or collection name] / Color/variant: [if single product] or short descriptor: [if collection] / Link: [product or collection LP]\n"
            "Slice 4 — Product/Collection 3 · Lifestyle image / Name: [product or collection name] / Color/variant: [if single product] or short descriptor: [if collection] / Link: [product or collection LP]\n"
            "[Optional BNDL kicker]"
        ),
    },
    "product_single": {
        "node_id": "174:351",
        "name": "Product Single — Product Category / Hero",
        "use_cases": ["single category hero", "ottoman feature", "one product", "one category", "hero only", "product spotlight", "influencer", "UGC product"],
        "description": "Full-email hero with large editorial HED + product image inset + CTA.",
        "slices_text": (
            "Slice 1 — Full email · Logo / HED: [headline] / Background image + product image inset (baked into one asset) / CTA: [CTA copy] / Instagram handle: @[handle] (include only when featuring influencer content, otherwise omit) / Link: [product or collection LP]"
        ),
    },
    "seating": {
        "node_id": "174:144",
        "name": "Seating — Seating / Product Category",
        "use_cases": ["seating", "chairs", "best of seating", "accent chairs", "benches", "ottomans", "numbered products", "3 chairs", "product lineup"],
        "description": "Hero + 3 numbered products (50/50 layout, alternating) + footer CTA. Optional BNDL kicker.",
        "slices_text": (
            'Slice 1 — Hero · Logo / Eyebrow: "THE BEST OF" (default; adjust if needed) / HED: [headline] / CTA: [CTA copy] / Link: [collection LP]\n'
            'Slice 2 — Product 1 [image left, copy right] · no. 1 / Product name: [name] / DEK: [1 sentence] / CTA: "SHOP NOW" (fixed) / Link: [product LP]\n'
            'Slice 3 — Product 2 [copy left, image right] · no. 2 / Product name: [name] / DEK: [1 sentence] / CTA: "SHOP NOW" (fixed) / Link: [product LP]\n'
            'Slice 4 — Product 3 [image left, copy right] · no. 3 / Product name: [name] / DEK: [1 sentence] / CTA: "SHOP NOW" (fixed) / Link: [product LP]\n'
            "Slice 5 — Footer CTA · Background image / HED: [copy] / CTA: [CTA copy] / Link: [collection LP]\n"
            "[Optional BNDL kicker]"
        ),
    },
    "color_edit": {
        "node_id": "175:607",
        "name": "Color Edit — Color Edit",
        "use_cases": ["color edit", "color story", "color theme", "greens", "blues", "neutrals", "color palette", "shop by color", "color trend"],
        "description": "Color theme hero + 2×2 product category grid + swatch kicker (default).",
        "slices_text": (
            'Slice 1 — Hero + subhead · Logo / HED: [color theme headline] / DEK: [editorial copy] / CTA: [CTA copy] / Subhead: "designer-loved style" (default; can vary — note: subhead sits on a separate light tan background row below the hero image, not overlaid on it) / Link: [color/collection LP]\n'
            "Slice 2 — Category 1 [50/50 — top left of grid] · Image / Category label: [label] overlaid on plain background color bar / Link: [category LP]\n"
            "Slice 3 — Category 2 [50/50 — top right of grid] · Image / Category label: [label] overlaid on plain background color bar / Link: [category LP]\n"
            "Slice 4 — Category 3 [50/50 — bottom left of grid] · Image / Category label: [label] overlaid on plain background color bar / Link: [category LP]\n"
            "Slice 5 — Category 4 [50/50 — bottom right of grid] · Image / Category label: [label] overlaid on plain background color bar / Link: [category LP]\n"
            "[Default: Swatch kicker · HED: [color theme, e.g. 'Go-to Greens:'] / Fabric name: [italic] / CTA: [CTA copy] / Link: https://www.theinside.com/fabric-swatches]"
        ),
    },
    "destination": {
        "node_id": "175:501",
        "name": "Destination — Travel / Destination Editorial",
        "use_cases": ["travel", "destination", "travel edit", "scotland", "highlands", "abroad", "landscape", "wanderlust", "destination editorial"],
        "description": "Destination editorial — landscape hero + editorial section + lifestyle image + CTA block.",
        "slices_text": (
            'Slice 1 — Hero · Logo / Eyebrow: "TRAVEL EDIT" (fixed) / Destination: [destination name, e.g. "SCOTLAND"] / HED: [destination headline] / CTA: [CTA copy] / Link: [destination edit LP]\n'
            "Slice 2 — Editorial · Light background / HED: [section headline] / DEK: [editorial copy] / Inline link: [anchor text, e.g. 'shop the edit'] / Oval-framed lifestyle image / Link: [destination edit LP]\n"
            "Slice 3 — Lifestyle image · Full-bleed image / Short italic copy: [2–5 word descriptor overlaid on image] / Link: [destination edit LP]\n"
            "Slice 4 — CTA block · Layered destination + interior images / HED: [copy] / CTA: [CTA copy] / Link: [destination edit LP]"
        ),
    },
    "dining": {
        "node_id": "175:562",
        "name": "Dining — Dining / Hosting / Entertaining",
        "use_cases": ["dining", "hosting", "entertaining", "brunch", "table setting", "dinner party", "table linens", "dining chairs", "hosting season"],
        "description": "Hosting editorial — lifestyle hero + two editorial sections + lifestyle image + CTA block.",
        "slices_text": (
            "Slice 1 — Hero · Logo / Eyebrow: [e.g. 'IT'S HOSTING TIME'] / HED: [headline] / CTA: [CTA copy] / Link: [collection LP]\n"
            "Slice 2 — Editorial 1 · Light background / HED: [section headline] / DEK: [editorial copy] / Inline link: [anchor text, e.g. 'shop dining chairs'] / Decorative framed lifestyle image / Link: [category LP]\n"
            "Slice 3 — Lifestyle image · Full-bleed image / Short italic copy: [2–5 word descriptor overlaid] / Link: [collection LP]\n"
            "Slice 4 — Editorial 2 · Light background / HED: [section headline] / DEK: [editorial copy] / Inline link: [anchor text, e.g. 'shop table linens'] / Lifestyle image / Link: [category LP]\n"
            "Slice 5 — CTA block · Background image / HED: [copy] / CTA: [CTA copy] / Link: [collection LP]"
        ),
    },
}

# ---------------------------------------------------------------------------
# TI kicker catalog
# Keyed by kicker key. sale_only=True means only used during active promos.
# ---------------------------------------------------------------------------
TI_KICKER_FILE_KEY = "B2DuEEQLOCrQNhY3iKTkhi"

TI_KICKERS: Dict[str, Dict] = {
    "bndl_a": {
        "node_id": "1:1297",
        "name": "BNDL Kicker A",
        "sale_only": True,
        "description": "Floral print background, dashed border box, centered layout. % off changes per promo; border can change to match email.",
        "slices_text": (
            "Kicker — BNDL Kicker A (1 slice) · "
            "'Buy Now. Decide Later.' / "
            "'Decisions are hard. Buy now, select your fabric later (and still get up to {pct} off).' / "
            "CTA: 'SHOP THE SALE' / Background border: [match to email] / "
            "Link: https://www.theinside.com/"
        ),
    },
    "bndl_b": {
        "node_id": "1:1393",
        "name": "BNDL Kicker B",
        "sale_only": True,
        "description": "Solid color background, half-and-half layout. % off changes per promo; background color can change to match email.",
        "slices_text": (
            "Kicker — BNDL Kicker B (1 slice) · "
            "'Buy now. Decide later.' / "
            "'Decisions are hard. Buy now, select your fabric later (and still get up to {pct} off).' / "
            "CTA: 'SHOP NOW' / Background color: [match to email] / "
            "Link: https://www.theinside.com/"
        ),
    },
    "swatch_a": {
        "node_id": "1:1287",
        "name": "Swatch Kicker A",
        "sale_only": False,
        "description": "Floral background, cream centered box. Fixed copy. Border can change to match email.",
        "slices_text": (
            "Kicker — Swatch Kicker A (1 slice) · "
            "HED: 'Find your favorite fabric' (fixed) / "
            "DEK: 'When you\\'ve got 100+ fabrics to choose from, falling in love is kind of inevitable.' (fixed) / "
            "CTA: 'GET SWOONING' (fixed) / Border: [match to email] / "
            "Link: https://www.theinside.com/fabric-swatches"
        ),
    },
    "swatch_b": {
        "node_id": "1:1403",
        "name": "Swatch Kicker B",
        "sale_only": False,
        "description": "Fabric print background, white box. Fixed copy. Border can change to match email.",
        "slices_text": (
            "Kicker — Swatch Kicker B (1 slice) · "
            "HED: 'Swoon-Worthy Swatches' (fixed) / "
            "DEK: 'When you\\'ve got 100+ fabrics to choose from, falling in love is kind of inevitable.' (fixed) / "
            "CTA: 'shop now →' (fixed) / Border: [match to email] / "
            "Link: https://www.theinside.com/fabric-swatches"
        ),
    },
    "link_farm_a": {
        "node_id": "1:1345",
        "name": "Link Farm A",
        "sale_only": True,
        "description": "Photo grid with % off overlays per category. 6 slices. % off is per-category — leave as placeholder.",
        "slices_text": (
            "Kicker — Link Farm A (6 slices) [% off per category — fill in from promo]:\n"
            "  Kicker Slice 1 — Beds [full-width] · [% off] / Link: https://www.theinside.com/c/bedroom-furniture/beds\n"
            "  Kicker Slice 2 — Curtains [50/50 left] · [% off] / Link: https://www.theinside.com/c/home-decor/curtains\n"
            "  Kicker Slice 3 — Ottomans [50/50 right] · [% off] / Link: https://www.theinside.com/c/living-room-furniture/ottomans\n"
            "  Kicker Slice 4 — Curtains [50/50 left] · [% off] / Link: https://www.theinside.com/c/home-decor/curtains\n"
            "  Kicker Slice 5 — Chairs [50/50 right] · [% off] / Link: https://www.theinside.com/c/living-room-furniture/chairs\n"
            "  Kicker Slice 6 — Sofas [full-width] · [% off] / Link: https://www.theinside.com/c/living-room-furniture/sofas"
        ),
    },
    "link_farm_b": {
        "node_id": "1:1311",
        "name": "Link Farm B",
        "sale_only": True,
        "description": "Text-based category grid on solid color background. 7 slices. Sale name, % off, and colors change per send.",
        "slices_text": (
            "Kicker — Link Farm B (7 slices) [sale name, % off, and colors change per send]:\n"
            "  Kicker Slice 1 — Header [full-width] · Eyebrow: '{sale_name_upper}' / Headline: 'Up To {pct} Off' / Link: https://www.theinside.com/\n"
            "  Kicker Slice 2 — Beds [50/50 left] · Link: https://www.theinside.com/c/bedroom-furniture/beds\n"
            "  Kicker Slice 3 — Furniture [50/50 right] · Link: https://www.theinside.com/collections/furniture\n"
            "  Kicker Slice 4 — Curtains [50/50 left] · Link: https://www.theinside.com/c/home-decor/curtains\n"
            "  Kicker Slice 5 — Ottomans [50/50 right] · Link: https://www.theinside.com/c/living-room-furniture/ottomans\n"
            "  Kicker Slice 6 — Outdoor [50/50 left] · Link: https://www.theinside.com/collections/outdoorliving\n"
            "  Kicker Slice 7 — Accent Chairs [50/50 right] · Link: https://www.theinside.com/c/living-room-furniture/chairs"
        ),
    },
}

# Trade Figma template catalog
# Sourced from Figma file e7qLewGYDpx18n5dqxV0sa (HAVENLY BRANDS TRADE).
# Keyed by sub-brand (HAV, ID, CZ, TI, STF), then template letter.
# URL format: ?node-id={id_hyphenated}
# ---------------------------------------------------------------------------

TRADE_FIGMA_FILE_KEY = "e7qLewGYDpx18n5dqxV0sa"

TRADE_FIGMA_TEMPLATES: Dict[str, Dict[str, Dict]] = {
    "HAV": {
        "A": {
            "node_id": "1075:6",
            "name": "Sale Feature A",
            "use_cases": ["sale", "discount", "DPS marketplace split", "multi-brand sale", "promo"],
            "description": "Hero discount + DPS/marketplace split CTA. Best for sale events or multi-brand promotions.",
        },
        "B": {
            "node_id": "1075:410",
            "name": "Sale Feature B",
            "use_cases": ["sale", "brand grid", "multiple brands", "alternate sale layout"],
            "description": "Alternate sale layout with brand grid — best for sends featuring multiple brands in one email.",
        },
        "C": {
            "node_id": "1075:698",
            "name": "Sale Feature C",
            "use_cases": ["sale", "benefits", "reasons to buy", "value prop", "sale with callouts"],
            "description": "Sale hero with benefits/reasons-to-buy footer. Best for sale sends that need to justify the offer.",
        },
        "D": {
            "node_id": "1075:996",
            "name": "Grid Layout",
            "use_cases": ["non-sale", "products", "collections", "editorial", "showcasing", "no promo"],
            "description": "Non-sale send showcasing multiple products/collections in a grid. Best for editorial or product-focused Trade sends.",
        },
    },
    "ID": {
        "A": {
            "node_id": "1075:2007",
            "name": "In Stock",
            "use_cases": ["in stock", "available", "quick ship", "in-stock collection", "product grid"],
            "description": "In-stock collection hero + product grid. Best for in-stock or quick-ship Trade sends.",
        },
        "B": {
            "node_id": "1075:2284",
            "name": "Editorial Edit",
            "use_cases": ["editorial", "brand story", "seasonal", "lifestyle", "storytelling"],
            "description": "Brand story or seasonal editorial. Best for lifestyle-led or brand-narrative Trade sends.",
        },
        "C": {
            "node_id": "1075:2117",
            "name": "Contract Grade",
            "use_cases": ["contract grade", "COM", "durability", "trade features", "performance", "commercial"],
            "description": "Trade-specific durability/COM features. Best for highlighting contract-grade or trade-exclusive product features.",
        },
        "D": {
            "node_id": "1075:2583",
            "name": "Category Highlight",
            "use_cases": ["category", "sofas", "dining", "single category", "deep dive", "category focus"],
            "description": "Single category deep-dive (sofas, dining, etc.). Best for category-specific Trade sends.",
        },
        "E": {
            "node_id": "1075:2454",
            "name": "Designer Spotlight",
            "use_cases": ["designer", "partnership", "trade program", "spotlight", "designer story"],
            "description": "Designer partnerships or Trade program spotlights. Best for featuring a designer or Trade program story.",
        },
    },
    "CZ": {
        "A": {
            "node_id": "1075:3536",
            "name": "Editorial Edit",
            "use_cases": ["editorial", "brand intro", "artisan story", "brand story", "origin"],
            "description": "Brand intro or artisan story. Best for editorial or brand-narrative CZ Trade sends.",
        },
        "B": {
            "node_id": "1075:3746",
            "name": "Hero Only",
            "use_cases": ["hero only", "simple", "single image", "announcement", "clean"],
            "description": "Single full-bleed hero. Best for simple announcements or strong single-image moments.",
        },
        "C": {
            "node_id": "1075:3719",
            "name": "Seasonal Moodboard",
            "use_cases": ["seasonal", "moodboard", "collection preview", "editorial", "mood"],
            "description": "Seasonal collection previews. Best for new season or collection mood-driven sends.",
        },
        "D": {
            "node_id": "1075:3794",
            "name": "Product Highlight",
            "use_cases": ["product launch", "new product", "hero product", "single product"],
            "description": "Hero product launch. Best for featuring a specific new product.",
        },
        "E": {
            "node_id": "1075:3862",
            "name": "Product Highlight Alt",
            "use_cases": ["product highlight", "alternate layout", "product feature", "second option"],
            "description": "Alternate product highlight layout. Use when D has been used recently.",
        },
        "F": {
            "node_id": "1075:3930",
            "name": "Swatches",
            "use_cases": ["swatches", "material", "fabric", "Trade swatch program", "samples"],
            "description": "Trade swatch programs or material stories.",
        },
        "G": {
            "node_id": "1075:4047",
            "name": "Room Categories",
            "use_cases": ["broad assortment", "multiple rooms", "room categories", "shop by room", "full range"],
            "description": "Broad assortment across multiple room types. Best for wide-ranging Trade sends.",
        },
    },
    "TI": {
        "A": {
            "node_id": "1075:4881",
            "name": "Print Feature",
            "use_cases": ["print", "pattern", "new print", "pattern launch", "textile print"],
            "description": "New print or pattern launches.",
        },
        "B": {
            "node_id": "1075:5061",
            "name": "Inside(r) Report",
            "use_cases": ["trend", "curated edit", "roundup", "insider", "editor's picks"],
            "description": "Trend roundups or curated edit sends.",
        },
        "C": {
            "node_id": "1075:5208",
            "name": "Editorial Edit",
            "use_cases": ["editorial", "brand story", "seasonal", "lifestyle"],
            "description": "Brand story or seasonal editorial.",
        },
        "D": {
            "node_id": "1075:5263",
            "name": "Fabrics",
            "use_cases": ["fabric", "COM", "Trade fabric", "material story", "textiles"],
            "description": "Fabric story or COM/Trade fabric program.",
        },
        "E": {
            "node_id": "1075:5417",
            "name": "Category Feature",
            "use_cases": ["category", "specific category", "category campaign", "focus"],
            "description": "Category-specific campaigns.",
        },
        "F": {
            "node_id": "1075:5694",
            "name": "Seasonal Preview",
            "use_cases": ["new season", "collection preview", "seasonal", "preview", "upcoming"],
            "description": "New season or collection preview.",
        },
    },
    "STF": {
        "A": {
            "node_id": "1075:7058",
            "name": "Editorial Edit",
            "use_cases": ["editorial", "brand story", "origin", "craft", "artisan"],
            "description": "Brand story or origin/craft sends.",
        },
        "B": {
            "node_id": "1075:7200",
            "name": "Fabric Feature",
            "use_cases": ["fabric", "textile", "material", "Trade fabric", "fabric story"],
            "description": "Fabric or textile-focused Trade sends.",
        },
        "C": {
            "node_id": "1075:7625",
            "name": "Hero Only",
            "use_cases": ["hero only", "single product", "lifestyle moment", "clean", "simple"],
            "description": "Single product or lifestyle moment.",
        },
        "D": {
            "node_id": "1075:7391",
            "name": "Editorial Category",
            "use_cases": ["top picks", "curated", "assortment", "editorial category", "product edit"],
            "description": '"Top Picks" curated product assortment.',
        },
        "E": {
            "node_id": "1075:7496",
            "name": "Behind the Scenes",
            "use_cases": ["artisan", "behind the scenes", "process", "craft story", "maker", "how it's made"],
            "description": "Artisan spotlights or process storytelling.",
        },
    },
}

# ---------------------------------------------------------------------------
# HAV (Havenly) Figma template catalog
# Sourced from Figma file CgGj7mTdp9SSj975u2mP4F (Havenly-Lifecycle-Templates)
# Core Designs section only. Blog Feature template excluded (moving away from Hideaway branding).
# URL format: ?node-id={id_hyphenated}&m=dev
# ---------------------------------------------------------------------------

HAV_FIGMA_FILE_KEY = "CgGj7mTdp9SSj975u2mP4F"

# Slice structure per HAV template, confirmed with Mina 2026-07-13 (see CLAUDE.md
# "Template & Kicker Field Reference"). Every template's Hero slice is Full width and
# always includes Logo (not listed per-slice since it's constant). `slices` holds the
# fixed leading slice(s); `repeatable_section` (when present) describes the shape of the
# variable-count additional slices generate_hav_email_brief() asks the AI to repeat.
# Unlike CZ/STF/BUR, HAV sections all point at the email's single top-level LP — no
# per-slice Link field — except This or That, which always links to the fixed LP below.
HAV_FIGMA_TEMPLATES: Dict[str, Dict] = {
    "theme_01": {
        "node_id": "12:312",
        "name": "Theme 01",
        "use_cases": ["editorial", "newsletter", "blog feature", "seasonal", "general", "hideaway", "trend roundup", "color palette", "wood tones", "mixing styles", "feng shui"],
        "description": "Multi-section editorial layout. Best for content-rich editorial sends, blog posts, seasonal newsletters, and general brand stories.",
        "slices": [{"name": "Hero", "type": "image", "fields": ["HED", "DEK", "CTA"]}],
        "repeatable_section": {"label": "Section", "fields": ["HED", "DEK"]},
    },
    "gif_body": {
        "node_id": "7:36",
        "name": "Gif + Body",
        "use_cases": ["before and after", "blog", "editorial", "GIF animation", "room transformation", "hideaway", "animation"],
        "description": "Hero GIF or animation + body copy. Best for Before & After room transformations, blog post features, and editorial sends with motion.",
        "slices": [{"name": "Hero", "type": "image", "fields": ["HED", "DEK", "CTA"]}],
    },
    "style_feature": {
        "node_id": "12:920",
        "name": "Style Feature",
        "use_cases": ["style feature", "moodboard", "get the look", "curated style", "product spotlight", "designer pick", "earth tones"],
        "description": "Hero lifestyle image with styled product feature. Best for style guides, moodboards, and curated look sends.",
        "slices": [{"name": "Hero", "type": "image", "fields": ["HED", "DEK", "CTA"]}],
        "repeatable_section": {"label": "Section", "fields": ["HED", "CTA"]},
    },
    "this_or_that": {
        "node_id": "14:76",
        "name": "This or That",
        "use_cases": ["this or that", "interactive", "vote", "poll", "A/B choice", "engagement", "two styles"],
        "description": "Interactive voting format. Best for 'This or That' engagement emails where subscribers choose between two styles.",
        "slices": [{"name": "Hero", "type": "image", "fields": ["HED", "DEK", "CTA"]}],
        "repeatable_section": {
            "label": "Section", "is_pair": True,
            "option_a_fields": ["HED", "Visual", "Label"],
            "option_b_fields": ["Visual", "Label"],
            "fixed_link": "https://havenly.com/exp/interior-design-ideas",
        },
    },
    "why_havenly": {
        "node_id": "15:211",
        "name": "Why Havenly",
        "use_cases": ["why havenly", "brand value", "how it works", "value prop", "DPS education", "design service", "introduce Havenly"],
        "description": "Brand value proposition format. Best for Why Havenly / How It Works educational emails, especially for DPS prospects.",
        "slices": [{"name": "Hero", "type": "image", "fields": ["HED", "DEK", "CTA"]}],
    },
    "ai": {
        "node_id": "44:55",
        "name": "AI",
        "use_cases": ["AI", "Havenly AI", "hero only", "simple announcement", "single image", "hero send", "launch"],
        "description": "Clean hero-only format. Best for Havenly AI feature emails and any hero-only announcement. Works well with a kicker attached.",
        "slices": [{"name": "Hero", "type": "image", "fields": ["HED", "DEK", "CTA"]}],
    },
}

# Kicker modules — optional add-on blocks that attach below the main template.
# audiences: which audience segments the kicker is designed for.
HAV_FIGMA_KICKERS: Dict[str, Dict] = {
    "5_stars": {
        "node_id": "15:212",
        "name": "5 Stars 01",
        "use_cases": ["testimonials", "reviews", "social proof", "5 star", "customer quote"],
        "description": "5-star testimonial/review block. Adds social proof to any editorial or sale send.",
        "audiences": ["DPS", "MP"],
    },
    "categories": {
        "node_id": "17:384",
        "name": "Categories",
        "use_cases": ["shop by category", "category grid", "browse", "multiple categories", "sale"],
        "description": "Shop-by-category grid. Best for sale emails or general browse CTAs.",
        "audiences": ["MP"],
    },
    "b_partners": {
        "node_id": "17:402",
        "name": "B. Partners",
        "use_cases": ["brand partners", "partner brands", "shop brands"],
        "description": "Brand partners block.",
        "audiences": ["MP"],
    },
    "dps_kicker": {
        "node_id": "9:240",
        "name": "DPS Kicker",
        "use_cases": ["DPS CTA", "book a designer", "design service", "get started", "DPS"],
        "description": "DPS-specific footer kicker with design service CTA. Use on DPS audience emails.",
        "audiences": ["DPS"],
    },
    "mp_kicker": {
        "node_id": "9:244",
        "name": "MP Kicker",
        "use_cases": ["MP CTA", "marketplace", "shop now", "marketplace browse"],
        "description": "MP-specific footer kicker. Use on MP/Converted audience emails.",
        "audiences": ["MP"],
    },
    "havenly_ai": {
        "node_id": "18:688",
        "name": "Havenly AI",
        "use_cases": ["AI feature", "Havenly AI", "AI tools", "cross-promote AI"],
        "description": "Havenly AI feature kicker. Pair with non-AI template sends to cross-promote the AI feature.",
        "audiences": ["DPS", "MP"],
    },
    "value_prop_dps": {
        "node_id": "20:1037",
        "name": "HAV Value Prop DPS",
        "use_cases": ["DPS value prop", "how it works", "design service education", "DPS onboarding"],
        "description": "HAV value proposition block for DPS prospects.",
        "audiences": ["DPS"],
    },
    "5_stars_02": {
        "node_id": "15:233",
        "name": "5 Stars 02",
        "use_cases": ["testimonials", "reviews", "social proof", "5 star", "customer quote"],
        "description": "Alternate 5-star testimonial/review block layout. Adds social proof to any editorial or sale send.",
        "audiences": ["DPS", "MP"],
    },
    "value_prop_mp": {
        "node_id": "18:565",
        "name": "HAV Value Prop MP",
        "use_cases": ["MP value prop", "why shop havenly", "marketplace education", "price match", "single checkout"],
        "description": "HAV value proposition block for Marketplace shoppers (price match, single checkout, vendor communication, designer commission).",
        "audiences": ["MP"],
    },
    "havenly_ai_b": {
        "node_id": "7:55",
        "name": "B. Havenly AI",
        "use_cases": ["AI feature", "Havenly AI", "AI tools", "cross-promote AI", "free download"],
        "description": "Alternate Havenly AI feature kicker (\"Great Design, Fast\" / \"Shop It Instantly\" two-column layout with Free Download CTA). Pair with non-AI template sends to cross-promote the AI feature.",
        "audiences": ["DPS", "MP"],
    },
    "a_partners": {
        "node_id": "20:1118",
        "name": "A. Partners",
        "use_cases": ["brand partners", "partner brands", "shop brands", "cross-brand products"],
        "description": "Cross-brand partner product callouts with pricing (Interior Define, The Citizenry, Burrow, The Inside, St. Frank).",
        "audiences": ["MP"],
    },
    "c_partners": {
        "node_id": "21:10",
        "name": "C. Partners",
        "use_cases": ["brand partners", "partner brands", "shop brands"],
        "description": "Alternate cross-brand partner grid layout (Interior Define, St. Frank, The Inside, Burrow, The Citizenry, Havenly).",
        "audiences": ["MP"],
    },
    "design_package_b": {
        "node_id": "16:255",
        "name": "B. Design Package",
        "use_cases": ["design package CTA", "book a designer", "design service", "DPS"],
        "description": "Single design-package CTA block. Simpler alternative to the A. Design Packages pricing comparison.",
        "audiences": ["DPS"],
    },
    "design_packages_a": {
        "node_id": "22:135",
        "name": "A. Design Packages",
        "use_cases": ["design package pricing", "online design", "in-person design", "book a designer", "DPS"],
        "description": "Online vs. In-Person design package pricing comparison block.",
        "audiences": ["DPS"],
    },
    "tier_sale": {
        "node_id": "171:9",
        "name": "Tier Sale",
        "use_cases": ["tiered discount", "spend more save more", "sale", "tier sale"],
        "description": "Tiered discount callout block (e.g. $2500+/$1250+/$750+ spending tiers, plus an extra flat discount). Use on sale emails with a tiered offer structure.",
        "audiences": ["DPS", "MP"],
    },
}

# CZ kicker module mapping — which modules appear per template.
# appended: fixed modules always included (order = display order).
# cycle_pool: options rotated across sends using LRU; the least-recently-used kicker
#   is always picked first, so the sequence naturally spreads across all options.
#   Template L uses two picks from its pool (for Kicker 1 + Kicker 3 slots).
CZ_KICKER_MAP: Dict[str, Dict] = {
    "A": {
        "appended": [],
        "cycle_pool": ["swatches", "fair_trade_guaranteed", "archive_sale"],
    },
    "B": {
        "appended": [],
        "cycle_pool": ["archive_sale", "back_in_stock", "fair_trade_guaranteed"],
    },
    "C": {
        "appended": [],
        "cycle_pool": ["fair_trade_guaranteed", "archive_sale"],
    },
    "D": {
        "appended": [],
        "cycle_pool": ["ymal", "archive_sale", "back_in_stock"],
    },
    "E": {
        "appended": [],
        "cycle_pool": ["back_in_stock", "swatches", "archive_sale"],
    },
    "F": {
        "appended": [],
        "cycle_pool": ["nais_5050_1", "nais_5050_2"],
    },
    "G": {
        "appended": [],
        "cycle_pool": ["archive_sale", "back_in_stock", "ymal"],
    },
    "H": {
        "appended": [],
        "cycle_pool": ["ymal", "archive_sale", "back_in_stock"],
    },
    "I": {
        "appended": [],
        "cycle_pool": ["ymal", "archive_sale", "back_in_stock"],
    },
    "J": {
        "appended": [],
        "cycle_pool": ["ymal", "archive_sale", "back_in_stock", "fair_trade_guaranteed"],
    },
    "K": {
        # back_in_stock excluded — the email itself is a BIS send
        "appended": [],
        "cycle_pool": ["ymal", "archive_sale", "fair_trade_guaranteed"],
    },
    "L": {
        "appended": [],
        "cycle_pool": ["archive_sale", "fair_trade_guaranteed", "back_in_stock", "swatches"],
        "two_slots": True,  # picks two different kickers from pool (Kicker 1 + Kicker 3)
    },
    "M": {
        "appended": [],
        "cycle_pool": ["ymal", "archive_sale", "back_in_stock"],
    },
    "N": {
        "appended": [],
        "cycle_pool": ["ymal", "archive_sale", "back_in_stock"],
    },
    "O": {
        "appended": [],
        "cycle_pool": ["fair_trade_guaranteed", "archive_sale", "ymal"],
    },
}

_KICKER_DISPLAY_NAMES: Dict[str, str] = {
    "ymal": "YMAL",
    "swatches": "Swatches",
    "back_in_stock": "Back in Stock",
    "archive_sale": "Archive Sale",
    "fair_trade_guaranteed": "Fair Trade Guaranteed",
}

# Variant IDs for kicker types that have multiple content block versions.
# The auto-builder sets kicker_id = <chosen variant> before calling ${kicker}.
_KICKER_VARIANTS: Dict[str, List[str]] = {
    "archive_sale": ["archive-1", "archive-2", "archive-3", "archive-4", "archive-5"],
    "fair_trade_guaranteed": ["fair-trade-1", "fair-trade-2", "fair-trade-3"],
    "back_in_stock": ["back-in-stock-1", "back-in-stock-2"],
    "swatches": ["swatches"],
}

# Fallback kickers used when an appended kicker is blocked by the back-to-back rule.
_APPENDED_FALLBACKS: Dict[str, List[str]] = {
    "ymal": ["fair_trade_guaranteed"],
}

# Tracks kicker picks made during the current briefing run so cycling works
# across a full month batch (not just from historical YAMLs).
_cz_kicker_run_state: List[Tuple] = []  # list of (send_date, kicker_key)
# Tracks which specific variant was used for within-type LRU rotation.
_cz_kicker_variant_run_state: List[Tuple] = []  # list of (send_date, kicker_key, variant_id)


def _get_asana_cz_kickers(days_back: int = 14) -> List[Tuple]:
    """Scan recent Asana CZ tasks for kicker picks not yet reflected in campaign YAMLs.

    Handles the cross-run gap: when tasks are briefed in separate invocations,
    _cz_kicker_run_state is empty and upcoming-campaign YAMLs may not exist yet.
    This call fills in that blind spot by reading the actual task notes.
    Silent-fails if ASANA_ACCESS_TOKEN is not set or the request errors.
    """
    from datetime import timedelta
    token = os.environ.get("ASANA_ACCESS_TOKEN")
    if not token:
        return []

    cutoff = (datetime.utcnow().date() - timedelta(days=days_back)).isoformat()
    name_to_key = {v.lower(): k for k, v in _KICKER_DISPLAY_NAMES.items()}
    results: List[Tuple] = []
    try:
        resp = requests.get(
            f"{ASANA_BASE_URL}/workspaces/5257710284167/tasks/search",
            headers={"Authorization": f"Bearer {token}", "Accept": "application/json"},
            params={
                "custom_fields.1207522425689880.value": "1207553690167887",  # Brand = The Citizenry
                "due_on.after": cutoff,
                "opt_fields": "due_on,notes",
            },
            timeout=10,
        )
        if resp.status_code != 200:
            return []
        for task in (resp.json().get("data") or []):
            due_on = task.get("due_on")
            if not due_on:
                continue
            try:
                task_date = datetime.strptime(due_on, "%Y-%m-%d").date()
            except Exception:
                continue
            notes = task.get("notes") or ""
            in_kicker = False
            next_line_is_kicker = False
            for line in notes.splitlines():
                # Format 1: standalone "Kicker modules:" section (older format)
                if "Kicker modules:" in line:
                    in_kicker = True
                    next_line_is_kicker = False
                    continue
                # Format 2: "Slice X — Kicker [content block - no slice needed]" embedded in Body Copy
                if "Kicker [content block" in line:
                    next_line_is_kicker = True
                    in_kicker = False
                    continue
                if next_line_is_kicker:
                    stripped = line.strip()
                    if stripped:
                        line_lower = stripped.lower()
                        for display_lower, key in name_to_key.items():
                            if line_lower.startswith(display_lower):
                                results.append((task_date, key))
                                vm = re.search(r'\(kicker_id:\s*([^\)]+)\)', stripped)
                                if vm:
                                    _cz_kicker_variant_run_state.append((task_date, key, vm.group(1).strip()))
                                break
                    next_line_is_kicker = False
                    continue
                if in_kicker:
                    if line.startswith("*"):
                        line_lower = line.lstrip("* ").lower()
                        for display_lower, key in name_to_key.items():
                            if line_lower.startswith(display_lower):
                                results.append((task_date, key))
                                vm = re.search(r'\(kicker_id:\s*([^\)]+)\)', line)
                                if vm:
                                    _cz_kicker_variant_run_state.append((task_date, key, vm.group(1).strip()))
                                break
                    elif line.strip():
                        in_kicker = False
    except Exception:
        pass
    return results


def _get_recent_cz_kickers(days_back: int = 60) -> List[Tuple]:
    """Return (date, kicker_key) pairs from YAML history + Asana + current run state."""
    from datetime import timedelta
    campaigns_dir = Path(__file__).parent.parent / "campaigns"
    cutoff = datetime.utcnow().date() - timedelta(days=days_back)
    results: List[Tuple] = []
    try:
        for f in glob.glob(str(campaigns_dir / "*.yaml")):
            with open(f) as fh:
                data = yaml.safe_load(fh)
            if not data or data.get("brand") != "CZ":
                continue
            km = data.get("kicker_module")
            if not km:
                continue
            dates_block = data.get("dates") or {}
            # Prefer first_sent (sent campaigns); fall back to send_date (upcoming drafts)
            date_raw = (
                dates_block.get("first_sent")
                or dates_block.get("last_sent")
                or dates_block.get("send_date")
            )
            if not date_raw:
                continue
            try:
                date_str = str(date_raw)
                campaign_date = (
                    datetime.fromisoformat(date_str.replace("Z", "+00:00")).date()
                    if "T" in date_str
                    else datetime.strptime(date_str, "%Y-%m-%d").date()
                )
                if campaign_date >= cutoff:
                    results.append((campaign_date, km))
            except Exception:
                continue
    except Exception:
        pass
    # Asana lookup covers tasks briefed in prior runs whose YAMLs don't exist yet
    results.extend(_get_asana_cz_kickers(days_back=min(days_back, 14)))
    return results + list(_cz_kicker_run_state)


def pick_cz_kicker(template_letter: str, send_date_str: str,
                   exclude: Optional[str] = None) -> Optional[str]:
    """Pick a kicker from the cycle pool, avoiding the immediately prior kicker-bearing email.

    Blocks whichever kicker was used in the most recent kicker-bearing email before
    send_date — regardless of how many calendar days ago it was — so consecutive sends
    never reuse the same kicker even when non-kicker emails fall in between.

    exclude: skip this key in addition to blocked ones (used for L's second slot pick).
    Records the choice in _cz_kicker_run_state so subsequent calls in the same batch
    are aware of earlier picks.
    """
    kmap = CZ_KICKER_MAP.get(template_letter)
    if not kmap:
        return None
    pool = kmap.get("cycle_pool", [])
    if not pool:
        return None

    try:
        send_date = datetime.fromisoformat(send_date_str).date() if "T" in send_date_str else datetime.strptime(send_date_str, "%Y-%m-%d").date()
    except Exception:
        send_date = datetime.utcnow().date()

    recent = _get_recent_cz_kickers()
    _link_farms = {"text_link_farm", "image_link_farm"}

    # Block the kicker from the immediately prior kicker-bearing email (not a calendar-day window).
    prior = sorted(
        [(d, k) for (d, k) in recent if d < send_date and k not in _link_farms],
        key=lambda x: x[0],
        reverse=True,
    )
    blocked = {prior[0][1]} if prior else set()
    if exclude:
        blocked.add(exclude)

    from datetime import date as _date

    def last_used(k: str) -> _date:
        dates = [d for (d, n) in recent if n == k]
        return max(dates) if dates else _date.min

    available = [k for k in pool if k not in blocked]
    if not available:
        available = list(pool)

    # Among available options, always prefer the least-recently-used so the
    # selection naturally rotates across the full briefing run (not just 2-day window).
    available.sort(key=last_used)

    chosen = available[0]
    _cz_kicker_run_state.append((send_date, chosen))
    return chosen


def pick_kicker_variant(kicker_key: str, send_date) -> Optional[str]:
    """Pick the LRU variant ID for a kicker type (within-type cycling).

    Uses _cz_kicker_variant_run_state so a full monthly batch cycles through
    all variants of a given kicker type before repeating any.
    """
    from datetime import date as _date
    variants = _KICKER_VARIANTS.get(kicker_key, [])
    if not variants:
        return None
    if len(variants) == 1:
        _cz_kicker_variant_run_state.append((send_date, kicker_key, variants[0]))
        return variants[0]

    recent = [(d, vid) for (d, kt, vid) in _cz_kicker_variant_run_state if kt == kicker_key]

    def last_used(v: str) -> _date:
        dates = [d for (d, vid) in recent if vid == v]
        return max(dates) if dates else _date.min

    chosen = sorted(variants, key=last_used)[0]
    _cz_kicker_variant_run_state.append((send_date, kicker_key, chosen))
    return chosen


_BEDDING_KEYWORDS = {
    "bedding", "bed", "linen", "linens", "duvet", "sheet", "sheets", "pillow",
    "pillows", "pillowcase", "quilt", "blanket", "throw", "comforter", "sham",
}


def _is_bedding_send(story: str) -> bool:
    """Return True if the send story/content is bedding-specific."""
    words = re.findall(r"[a-z]+", story.lower())
    return bool(_BEDDING_KEYWORDS.intersection(words))


def _format_kicker_label(kicker_key: str, send_date, story: str = "") -> str:
    """Return the task description line for a single kicker module.

    For kicker types with variant IDs, appends (kicker_id: <id>) so the
    auto-builder knows which content block variant to wire up.
    """
    # Special cases with their own fixed labels (50/50 blocks, etc.)
    _fixed = {
        "nais_5050_1": "50/50 New Arrivals + Back in Stock (content block new-arrivals-in-stock-1)",
        "nais_5050_2": "50/50 New Arrivals + Back in Stock (content block new-arrivals-in-stock-2)",
    }
    if kicker_key in _fixed:
        return _fixed[kicker_key]

    name = _KICKER_DISPLAY_NAMES.get(kicker_key, kicker_key)

    if kicker_key == "ymal":
        return name  # content block: {{content_blocks.${product_recs}}}

    # Bedding-specific sends use the bedding-swatches variant instead of swatches.
    if kicker_key == "swatches" and story and _is_bedding_send(story):
        variant = "bedding-swatches"
        _cz_kicker_variant_run_state.append((send_date, kicker_key, variant))
        return f"{name} (kicker_id: {variant})"

    variant = pick_kicker_variant(kicker_key, send_date)
    if not variant:
        return name

    return f"{name} (kicker_id: {variant})"


def format_cz_kicker_section(template_letter: str, send_date_str: str, story: str = "") -> str:
    """Return the kicker section for a CZ task description in AI-parseable format."""
    kmap = CZ_KICKER_MAP.get(template_letter)
    if not kmap:
        return ""

    appended = kmap.get("appended", [])
    pool = kmap.get("cycle_pool", [])
    two_slots = kmap.get("two_slots", False)

    try:
        send_date = (
            datetime.fromisoformat(send_date_str).date()
            if "T" in send_date_str
            else datetime.strptime(send_date_str, "%Y-%m-%d").date()
        )
    except Exception:
        send_date = datetime.utcnow().date()

    modules: List[str] = []

    if pool:
        first = pick_cz_kicker(template_letter, send_date_str) or pool[0]
        modules.append(first)
        if two_slots:
            second = pick_cz_kicker(template_letter, send_date_str, exclude=first) or next(
                (k for k in pool if k != first), pool[0]
            )
            modules.append(second)

    # Apply back-to-back check to appended (fixed) kickers.
    # Block the kicker from the immediately prior kicker-bearing email so consecutive
    # sends never reuse the same kicker even with non-kicker emails in between.
    recent = _get_recent_cz_kickers()
    _link_farms = {"text_link_farm", "image_link_farm"}
    prior = sorted(
        [(d, k) for (d, k) in recent if d < send_date and k not in _link_farms],
        key=lambda x: x[0],
        reverse=True,
    )
    blocked = {prior[0][1]} if prior else set()

    for kicker_key in appended:
        if kicker_key in blocked:
            fallbacks = _APPENDED_FALLBACKS.get(kicker_key, [])
            substitute = next((fb for fb in fallbacks if fb not in blocked), None)
            if substitute:
                print(f"  [kicker] {kicker_key} blocked for {send_date_str} (back-to-back) — using {substitute}")
                modules.append(substitute)
                _cz_kicker_run_state.append((send_date, substitute))
            else:
                modules.append(kicker_key)
                _cz_kicker_run_state.append((send_date, kicker_key))
        else:
            modules.append(kicker_key)
            _cz_kicker_run_state.append((send_date, kicker_key))

    if not modules:
        return "Kicker: None"

    lines = ["Kicker modules:"]
    for m in modules:
        lines.append(f"* {_format_kicker_label(m, send_date, story=story)}")
    return "\n".join(lines)


def load_brand_examples(brand: str) -> List[Dict[str, str]]:
    """Load past SL/PH examples from campaign YAMLs for a brand."""
    if brand in _brand_examples_cache:
        return _brand_examples_cache[brand]

    campaigns_dir = Path(__file__).parent.parent / "campaigns"
    examples = []
    for f in glob.glob(str(campaigns_dir / "*.yaml")):
        with open(f) as fh:
            data = yaml.safe_load(fh)
        if not data or data.get("brand") != brand:
            continue
        for send in data.get("sends", []):
            sl = send.get("subject", "")
            ph = send.get("preheader", "")
            if sl:
                examples.append({
                    "subject": sl,
                    "preheader": ph or "",
                    "category": data.get("category", ""),
                })

    _brand_examples_cache[brand] = examples
    return examples


def generate_sl_ph(record: Dict[str, str]) -> Optional[str]:
    """Generate 2 paired SL/PH options using Claude API.

    Returns formatted text block or None if API key missing/call fails.
    """
    api_key = os.environ.get("ANTHROPIC_API_KEY")
    if not api_key:
        return None

    brand = record["brand"]
    category = infer_category(record["story"], record["source_tab"])
    brand_name = BRAND_FULL_NAMES.get(brand, brand)

    # Load past examples, preferring same category
    all_examples = load_brand_examples(brand)
    cat_examples = [e for e in all_examples if e["category"] == category]
    if len(cat_examples) < 5:
        cat_examples = all_examples
    # Take up to 20 recent examples
    sample = cat_examples[:20]

    examples_text = "\n".join(
        f"SL: {e['subject']}\nPH: {e['preheader']}"
        for e in sample if e["subject"]
    )

    prompt = f"""Generate 2 subject line and pre-header options for this email campaign.

Brand: {brand_name}
Email topic: {record['story']}
Category: {category}
{f"Promo: {record['promo']}" if record.get('promo') else ""}
{f"Notes: {record['notes']}" if record.get('notes') else ""}

Here are past {brand_name} subject lines and pre-headers for reference — match this tone, style, and length exactly:

{examples_text}

Rules:
- Subject lines: short and punchy (3-7 words), confident, aspirational
- Pre-headers: start with a lowercase letter, no ending punctuation, complement the SL without repeating it
- Each option should be a paired SL + PH that work together

Return ONLY this format, nothing else:
Option 1:
SL: [subject line]
PH: [pre-header]

Option 2:
SL: [subject line]
PH: [pre-header]"""

    for attempt in range(1, 4):
        try:
            resp = requests.post(
                "https://api.anthropic.com/v1/messages",
                headers={
                    "x-api-key": api_key,
                    "anthropic-version": "2023-06-01",
                    "content-type": "application/json",
                },
                json={
                    "model": "claude-haiku-4-5-20251001",
                    "max_tokens": 200,
                    "messages": [{"role": "user", "content": prompt}],
                },
                timeout=15,
            )
            if resp.status_code != 200:
                print(f"  ⚠ generate_sl_ph: HTTP {resp.status_code} on attempt {attempt}/3 for '{record.get('story', '')}'")
                if attempt < 3:
                    time.sleep(2)
                continue

            text = resp.json()["content"][0]["text"].strip()
            text = text.replace("\\n", "\n")  # Haiku sometimes outputs literal \n instead of newlines
            if "Option 1:" in text and "Option 2:" in text:
                return text
            print(f"  ⚠ generate_sl_ph: unexpected response format on attempt {attempt}/3 for '{record.get('story', '')}': {text[:80]!r}")
            if attempt < 3:
                time.sleep(2)
        except Exception as e:
            print(f"  ⚠ generate_sl_ph: exception on attempt {attempt}/3 for '{record.get('story', '')}': {e}")
            if attempt < 3:
                time.sleep(2)

    print(f"  ✗ generate_sl_ph: all 3 attempts failed for '{record.get('story', '')}' — SL/PH will be missing from task")
    return None


def generate_email_direction(record: Dict[str, str],
                             inventory_context: Optional[str] = None) -> Optional[str]:
    """Generate a brief creative direction + content outline using Claude API.

    Args:
        record: Calendar record with brand, story, promo, notes, etc.
        inventory_context: Optional formatted inventory text to inject into prompt.

    Returns formatted text block or None if API key missing/call fails.
    """
    api_key = os.environ.get("ANTHROPIC_API_KEY")
    if not api_key:
        return None

    brand = record["brand"]
    category = infer_category(record["story"], record["source_tab"])
    brand_name = BRAND_FULL_NAMES.get(brand, brand)

    # Load past examples for tone context
    all_examples = load_brand_examples(brand)
    cat_examples = [e for e in all_examples if e["category"] == category]
    if len(cat_examples) < 5:
        cat_examples = all_examples
    sample = cat_examples[:10]

    examples_text = "\n".join(
        f"SL: {e['subject']}" for e in sample if e["subject"]
    )

    # Build inventory section if available
    inventory_section = ""
    product_bullet = "• [Product/offer to feature]"
    if inventory_context:
        inventory_section = f"""
Currently in-stock products for {brand_name}:
{inventory_context}

IMPORTANT: Only suggest products from this list or categories represented here.
"""
        product_bullet = "• [Product/offer to feature — choose from in-stock products above]"

    prompt = f"""Write a brief creative direction for this email campaign.

Brand: {brand_name}
Email topic: {record['story']}
Category: {category}
{f"Promo: {record['promo']}" if record.get('promo') else ""}
{f"Notes: {record['notes']}" if record.get('notes') else ""}
{f"Banners: {record['banners']}" if record.get('banners') else ""}

Here are past {brand_name} subject lines for tone reference:
{examples_text}
{inventory_section}
Return ONLY this format, nothing else:
[1-2 sentence creative brief — goal, key message, tone]

• [Hero section description]
{product_bullet}
• [Supporting content element]
• [CTA and destination]"""

    try:
        resp = requests.post(
            "https://api.anthropic.com/v1/messages",
            headers={
                "x-api-key": api_key,
                "anthropic-version": "2023-06-01",
                "content-type": "application/json",
            },
            json={
                "model": "claude-haiku-4-5-20251001",
                "max_tokens": 300,
                "messages": [{"role": "user", "content": prompt}],
            },
            timeout=15,
        )
        if resp.status_code != 200:
            return None

        text = resp.json()["content"][0]["text"].strip()
        text = text.replace("\\n", "\n")  # Haiku sometimes outputs literal \n instead of newlines
        # Validate it has the expected format (bullet points for outline)
        if "•" in text:
            return text
        return None
    except Exception:
        return None


def build_cz_prompt(record: Dict[str, str],
                     inventory_context: Optional[str] = None) -> str:
    """Pure prompt-builder for CZ designed emails - no API call, no API key required.

    Prefer this + parse_cz_response() over generate_cz_email_brief() when a live Claude
    Code session is doing the briefing (the normal case - see "Calendar Task Creation
    Workflow" in CLAUDE.md): generate the completion yourself as the acting session,
    then call parse_cz_response(text) to get the same figma_brief dict. This avoids
    generate_cz_email_brief()'s dependency on the shared ANTHROPIC_API_KEY prepaid
    credit balance, which periodically runs dry (see docs/lifecycle-figjam-stats-update.md)
    and fails that function silently (returns None, no error surfaced).
    """
    # Load known CZ URLs from data file
    _cz_links_path = os.path.join(os.path.dirname(__file__), "..", "data", "cz_links.yaml")
    _cz_collections_text = ""
    _cz_products_text = ""
    try:
        with open(_cz_links_path) as _f:
            _cz_links = yaml.safe_load(_f)
        _cz_collections_text = "\n".join(
            f"  {c['url']} — {c['label']}"
            for c in _cz_links.get("collections", [])
        )

        # Determine if this is an archive sale email — if so, all products are allowed
        _story_lower = record.get("story", "").lower()
        _is_archive_sale = any(kw in _story_lower for kw in ("archive sale", "archive", "clearance"))

        # For non-archive-sale emails, filter out products in the Archive Sale collection
        _archive_handles: set = set()
        if not _is_archive_sale:
            try:
                from scripts.utils.inventory_checker import get_archive_sale_product_handles
                _archive_handles = get_archive_sale_product_handles("CZ")
            except Exception:
                pass

        def _extract_handle(url: str) -> str:
            # e.g. https://www.the-citizenry.com/products/eshana-sandstone-bowl → eshana-sandstone-bowl
            return url.rstrip("/").rsplit("/", 1)[-1]

        _cz_products_text = "\n".join(
            f"  {p['url']} — {p['name']}"
            for p in _cz_links.get("products", [])
            if _is_archive_sale or _extract_handle(p["url"]) not in _archive_handles
        )
    except Exception:
        pass

    # Build template catalog for the prompt — describe each slice so Claude knows the structure
    def _describe_template_slices(slices: list, auto_modules: list) -> str:
        lines = []
        for i, s in enumerate(slices, 1):
            opt = " (optional)" if s.get("optional") else ""
            if s["type"] == "brand_asset":
                lines.append(f"  Slice {i} — {s['name']} [brand asset — The Citizenry logo, no generation needed]{opt}")
            elif s["type"] == "image":
                fields = list(s.get("fields", []))
                if not any("Link:" in f for f in fields):
                    fields.append("Link: [URL from lists above]")
                field_list = "\n".join(f"      {f}" for f in fields)
                if s.get("no_visual"):
                    lines.append(
                        f"  Slice {i} — {s['name']} [IMAGE — fill fields only, no visual direction needed]{opt}\n"
                        f"{field_list}"
                    )
                else:
                    lines.append(
                        f"  Slice {i} — {s['name']} [IMAGE — write Visual: brief + fill text fields]{opt}\n"
                        f"      Visual: ...\n"
                        f"{field_list}"
                    )
            elif s["type"] == "text":
                fields = list(s.get("fields", []))
                if not any("Link:" in f for f in fields):
                    fields.append("Link: [URL from lists above]")
                field_list = "\n".join(f"      {f}" for f in fields)
                lines.append(f"  Slice {i} — {s['name']} [text-only — fill fields, no image]{opt}\n{field_list}")
        for mod in auto_modules:
            lines.append(f"  [{mod} — auto-generated, no content needed]")
        return "\n".join(lines)

    templates_detail = "\n\n".join(
        f"{letter}. {t['name']} — use for: {t['use_cases']}\n"
        + _describe_template_slices(t["slices"], t.get("auto_modules", []))
        for letter, t in CZ_FIGMA_TEMPLATES.items()
    )

    _inventory_auto_fetched = False
    if inventory_context is None:
        inventory_context = _get_cz_inventory_context(record)
        _inventory_auto_fetched = True

    if inventory_context:
        inventory_section = (
            f"\nCurrently in-stock products for The Citizenry (with real colorway/finish "
            f"options where they exist):\n{inventory_context}\n"
            "Only suggest products from this list. A product's real colorway/finish "
            "options, if any exist, are listed directly under it as \"colorways/finishes: "
            "...\" - if you name a specific color or fabric for that product, it MUST be "
            "one of those values, verbatim. Never invent a color/finish for a product that "
            "has no colorways/finishes line at all.\n"
        )
    elif _inventory_auto_fetched:
        inventory_section = (
            "\nNo live inventory data was available for this brief beyond the static "
            "PRODUCTS list below. Because of that, do NOT name a specific colorway/finish "
            "for any product you cannot verify — describe it generically instead.\n"
        )
    else:
        inventory_section = ""

    prompt = f"""You are briefing a The Citizenry designed email campaign. Do three things:

1. SELECT the best Figma template from the list below based on the email topic and use cases.
2. WRITE a 1-sentence creative direction (goal, key message, and tone).
3. GENERATE structured body copy — slice by slice for the selected template. Keep The Citizenry's voice: artisanal, warm, globally inspired, confident but understated. No emojis.

Slice name rules:
- Use the EXACT slice name from the template definition — never abbreviate or simplify it.
- If the slice name includes a layout suffix like "— 50/50 left" or "— 50/50 right", that suffix MUST appear in the output header (e.g., "Slice 2 — Product Image 1 — 50/50 left [IMAGE]", NOT "Slice 2 — Product Image 1 [IMAGE]").

Slice type rules:
- [brand asset]: Output the slice header line only — no content needed (logo is a fixed file).
- [IMAGE]: Write "  Visual: [1–2 sentences for an AI image generator — describe composition, featured products by name, styling props, mood, lighting]" then fill in each text field on its own line. For sale category blocks, one concise sentence for Visual is enough (e.g., "Flat-lay of linen bedding in warm natural tones.").
- [text-only]: Fill in text fields only — no Visual line.
- [auto-generated]: List in brackets — no content needed.

Discount rules:
- Template F (Archive Sale): the Archive Sale always has UP TO 70% OFF — never use the Promo line's discount percentage for Archive Sale CTAs. Always write "Shop up to 70% off" (not "25% off" or any other promo discount). The Promo line only applies to the Sale banner (Slice 1), not to the Archive Sale hero or body copy.

Product rules:
- NEVER suggest a product that is not in the PRODUCTS list below — do not invent product names or URLs.
- NEVER suggest a product from The Citizenry's Archive Sale collection in a non-archive-sale email. Archive Sale items are end-of-life clearance products and must only appear in Template F (Archive Sale) emails. If the email topic does not explicitly say "Archive Sale" or "clearance", all suggested products must come from the regular full-price catalog.
- If a slice's Visual/copy names a specific color, material, or finish for a product, only do so if you're actually certain it's real for that product — never invent one. Add its own "Colorway: <value>" line right after the product's Name/HED line so the correct variant can be verified and linked; omit it if the Visual/copy doesn't call out a specific color/finish. An invented colorway will cause the brief to be rejected and regenerated.

Link rules — fill every Link: field with a URL from the lists below. Only use URLs from these lists; do not invent URLs.
- Hero (and any single-slice template): use the Recommended LP if one is provided above; otherwise use https://www.the-citizenry.com/
- Sale banner (when auto-inserted as Slice 1): https://www.the-citizenry.com/
- Archive Sale hero: https://www.the-citizenry.com/collections/archive-sale
- Category blocks (H's Category Blocks, G's Room slices, M's Category 1–4 slices, B's Category Block Links): pick the best-matching collection URL from the COLLECTIONS list below
- Product modules (D's Product Images, N's UGC Photos, N's Featured product link): pick the best-matching product URL from the PRODUCTS list below; if no match exists, fall back to the most relevant collection URL
- L's Section 1/2/3: use the LP if it matches the section's content; otherwise pick the most relevant collection URL
- All other editorial sections below the hero (A's Section 1/2/3, C's Body section and Kicker, etc.): use the same URL as the hero

COLLECTIONS (use for category/editorial links):
{_cz_collections_text}

PRODUCTS (use for individual product links):
{_cz_products_text}

Email topic: {record['story']}
{f"Promo: {record['promo']}" if record.get('promo') else ""}
{f"Notes: {record['notes']}" if record.get('notes') else ""}
{f"Landing page: {record['landing_page']}" if record.get('landing_page') else ""}
{inventory_section}
TEMPLATES:
{templates_detail}

Return ONLY this exact format — no extra commentary:
TEMPLATE: [Letter]. [Name]
DIRECTION: [1-sentence creative direction]
BODY_COPY:
Slice 1 — [EXACT slice name from template] [brand asset]

Slice 2 — [EXACT slice name from template, including any "— 50/50 left" or "— 50/50 right" suffix] [IMAGE]
  Visual: [visual description]
  [Field]: [value]
  [Field]: [value]

[Auto-module — auto-generated]"""
    # Re-run send: tell the model how to frame DIRECTION (no-op for normal rows).
    _resend_block = resend_prompt_instruction(record)
    if _resend_block:
        prompt += "\n" + _resend_block
    return prompt


def parse_cz_response(text: str) -> Optional[Dict[str, str]]:
    """Pure response-parser for CZ designed emails - no API call.

    Parses the exact TEMPLATE:/DIRECTION:/BODY_COPY: format requested by
    build_cz_prompt() (whether the completion came from the Anthropic API or was
    generated directly by the acting Claude session). Returns the same dict shape
    generate_cz_email_brief() used to return, or None if parsing fails outright
    (unrecognized template letter, etc.).

    Raises SliceBriefValidationError - deliberately NOT caught by this function's own
    `except Exception: return None` - if the parsed body copy has duplicate product/
    category slots (see _warn_duplicate_products()). Do not catch this and fall back to
    creating/updating the Asana task anyway: regenerate the completion addressing the
    error message and re-parse. A None return means "couldn't parse at all" and an
    exception means "parsed, but the content is structurally wrong" - callers must
    handle these two failure modes differently, not collapse them into one retry path.
    """
    try:
        text = text.strip().replace("\\n", "\n")

        lines = text.split("\n")
        template_letter = None
        direction = None
        body_copy_lines = []
        in_body_copy = False

        for line in lines:
            if line.startswith("TEMPLATE:"):
                val = line.replace("TEMPLATE:", "").strip()
                m = re.match(r"^([A-O])\.\s+(.+)$", val)
                if m:
                    template_letter = m.group(1).upper()
            elif line.startswith("DIRECTION:"):
                direction = line.replace("DIRECTION:", "").strip()
            elif line.startswith("BODY_COPY:"):
                in_body_copy = True
            elif in_body_copy:
                # Preserve blank lines (slice separators); strip indentation from non-blank lines
                body_copy_lines.append(line.strip() if line.strip() else "")

        if not template_letter or template_letter not in CZ_FIGMA_TEMPLATES:
            return None

        template_data = CZ_FIGMA_TEMPLATES[template_letter]
        body_copy_lines = _enforce_5050_pairing(body_copy_lines)
        _warn_duplicate_products(body_copy_lines, template_slices=template_data["slices"])
        body_copy_lines = _resolve_product_slice_links(body_copy_lines, template_slices=template_data["slices"], brand="CZ")
        _warn_generic_link_for_product_slice(body_copy_lines, template_slices=template_data["slices"])
        body_copy_text = "\n".join(
            f"    {line}" if line else ""
            for line in body_copy_lines
        )

        return {
            "template_letter": template_letter,
            "template_name": template_data["name"],
            "template_node_id": template_data["node_id"],
            "direction": direction or "",
            "body_copy": body_copy_text,
        }
    except SliceBriefValidationError:
        raise
    except Exception:
        return None


def generate_cz_email_brief(record: Dict[str, str],
                             inventory_context: Optional[str] = None) -> Optional[Dict[str, str]]:
    """Convenience wrapper: calls the Anthropic API directly using ANTHROPIC_API_KEY.

    Prefer build_cz_prompt() + parse_cz_response() when a live Claude Code session is
    doing the briefing (see their docstrings) - this function's own API call depends on
    a shared prepaid credit balance that periodically runs dry, and fails silently
    (returns None) when it does. Kept for any fully-automated/headless caller that has
    no live session available to generate the completion itself.

    Returns dict with keys: template_letter, template_name, template_node_id, direction, body_copy
    or None on failure.
    """
    api_key = os.environ.get("ANTHROPIC_API_KEY")
    if not api_key:
        return None

    prompt = build_cz_prompt(record, inventory_context=inventory_context)

    try:
        resp = requests.post(
            "https://api.anthropic.com/v1/messages",
            headers={
                "x-api-key": api_key,
                "anthropic-version": "2023-06-01",
                "content-type": "application/json",
            },
            json={
                "model": "claude-haiku-4-5-20251001",
                "max_tokens": 2400,
                "messages": [{"role": "user", "content": prompt}],
            },
            timeout=45,
        )
        if resp.status_code != 200:
            return None

        text = resp.json()["content"][0]["text"]
        return parse_cz_response(text)
    except Exception:
        return None


def _describe_stf_slices(slices: list) -> str:
    """Render an STF template's slices into the prompt catalog text.

    Mirrors CZ's _describe_template_slices but surfaces the fixed Layout per slice
    (Full width / 50/50 left / 50/50 right) as the first field so the AI reproduces it.
    """
    lines = []
    for i, s in enumerate(slices, 1):
        opt = " (optional — include only if the send warrants it)" if s.get("optional") else ""
        fields = [f"Layout: {s.get('layout', 'Full width')}"] + list(s.get("fields", []))
        if not any(f.startswith("Link:") for f in fields):
            fields.append("Link: [URL from lists above]")
        field_list = "\n".join(f"      {f}" for f in fields)
        if s.get("no_visual"):
            lines.append(
                f"  Slice {i} — {s['name']} [IMAGE — fill fields only, no visual direction needed]{opt}\n"
                f"{field_list}"
            )
        else:
            lines.append(
                f"  Slice {i} — {s['name']} [IMAGE — write Visual: brief + fill text fields]{opt}\n"
                f"      Visual: ...\n"
                f"{field_list}"
            )
    return "\n".join(lines)


_stf_slice_header_re = re.compile(r"^Slice\s+\d+\s*[—–-]\s*(.+?)(?:\s*\[.*\])?\s*$")


def _stf_inject_layouts(body_copy_lines: List[str], template_key: str,
                         templates: Optional[Dict[str, Dict]] = None) -> List[str]:
    """Guarantee every slice block carries the correct Layout line.

    The layout is fixed per slice in the template catalog, so we do not trust the AI to
    echo it: for each parsed slice we drop any AI-written Layout line and re-insert the
    canonical one from the template (matched by slice name, falling back to slice order).

    `templates` defaults to STF_FIGMA_TEMPLATES (STF's own catalog); pass BW_FIGMA_TEMPLATES
    to reuse this same logic for Burrow.
    """
    if templates is None:
        templates = STF_FIGMA_TEMPLATES
    template = templates.get(template_key, {})
    slices = template.get("slices", [])
    by_name = {s["name"].strip().lower(): s.get("layout", "Full width") for s in slices}
    ordered_layouts = [s.get("layout", "Full width") for s in slices]

    out: List[str] = []
    slice_idx = -1  # index among slice headers seen so far
    for line in body_copy_lines:
        m = _stf_slice_header_re.match(line.strip())
        if m:
            slice_idx += 1
            out.append(line)
            name = m.group(1).strip().lower()
            layout = by_name.get(name)
            if layout is None and 0 <= slice_idx < len(ordered_layouts):
                layout = ordered_layouts[slice_idx]
            if layout:
                out.append(f"Layout: {layout}")
        elif line.strip().lower().startswith("layout:"):
            # Drop AI-emitted layout lines — the canonical one was inserted above.
            continue
        else:
            out.append(line)
    return out


_5050_header_suffix_re = re.compile(r"[—–-]\s*(50/50\s+(?:left|right))\s*$", re.IGNORECASE)


def _enforce_5050_pairing(body_copy_lines: List[str]) -> List[str]:
    """Guarantee every '50/50 left' slice has a matching '50/50 right' (and vice versa).

    A 50/50 pair renders as two side-by-side halves in the final email — an unpaired
    50/50 slice (e.g. 3 lefts, 2 rights) leaves a broken half-row with nothing next to
    it. Template definitions in STF_FIGMA_TEMPLATES/BW_FIGMA_TEMPLATES/CZ_FIGMA_TEMPLATES
    always define 50/50 slices in matched pairs, so an imbalance only happens when the
    AI-generated body copy drops a trailing slice (e.g. a repeatable product section cut
    short) or emits an odd count for a variable-length section. When that happens, drop
    the LAST slice on the over-represented side (majority side) so every remaining 50/50
    has its partner, renumber subsequent "Slice N —" headers to stay sequential, and
    decrement a leading "Slices to deliver: N" line if present.

    Confirmed real-world case: BUR "Opera Media Console Highlight" generated 3 finish
    slices (2 left, 1 right) instead of a clean pair — see
    memory/feedback_5050_pairing_rule.md.

    Layout detection supports two conventions so this same function works for both
    STF/BW (a dedicated "Layout: 50/50 left" field line) and CZ (no separate Layout
    line - "50/50 left"/"50/50 right" is a suffix on the slice name itself, e.g.
    "Slice 2 — Product Image 1 — 50/50 left [IMAGE]", per CZ_FIGMA_TEMPLATES' slice
    naming convention). A header-suffix match is used as the initial layout value; an
    explicit "Layout:" line only fills in when the header carried no suffix - it never
    overrides a header-suffix match. This matters because CZ's own field instructions
    also ask for a *separate*, wordier "Layout: 50/50 (paired with Product Image 2 in
    the same row)" line alongside the header suffix - if that were allowed to overwrite
    the cleanly-detected "50/50 left"/"50/50 right" value, the pairing count would never
    recognize it (the wordy text doesn't match either literal string) and this function
    would silently stop working for CZ. STF/BW headers never carry a suffix, so their
    behavior (Layout: line is the only source) is unchanged.
    """
    # Group lines into (header_idx, layout, block_line_indices) per slice.
    blocks: List[Dict[str, object]] = []
    current: Optional[Dict[str, object]] = None
    for idx, line in enumerate(body_copy_lines):
        m = _stf_slice_header_re.match(line.strip())
        if m:
            suffix_m = _5050_header_suffix_re.search(m.group(1).strip())
            initial_layout = suffix_m.group(1).lower() if suffix_m else None
            current = {"start": idx, "layout": initial_layout, "end": len(body_copy_lines)}
            if blocks:
                blocks[-1]["end"] = idx
            blocks.append(current)
        elif current is not None and current.get("layout") is None and line.strip().lower().startswith("layout:"):
            current["layout"] = line.strip()[len("layout:"):].strip().lower()

    left_idxs = [i for i, b in enumerate(blocks) if b["layout"] == "50/50 left"]
    right_idxs = [i for i, b in enumerate(blocks) if b["layout"] == "50/50 right"]
    if len(left_idxs) == len(right_idxs):
        return body_copy_lines

    drop_pool = left_idxs if len(left_idxs) > len(right_idxs) else right_idxs
    drop_block = blocks[drop_pool[-1]]
    header_text = body_copy_lines[drop_block["start"]].strip()
    print(
        f"[WARN] _enforce_5050_pairing: unpaired 50/50 slices "
        f"(left={len(left_idxs)}, right={len(right_idxs)}) — dropping '{header_text}' "
        f"to restore pairing. Review whether a different slice should have been kept."
    )

    out = [
        line for i, line in enumerate(body_copy_lines)
        if not (drop_block["start"] <= i < drop_block["end"])
    ]

    # Renumber "Slice N —" headers sequentially and decrement "Slices to deliver: N".
    renumbered: List[str] = []
    slice_num = 0
    for line in out:
        m = _stf_slice_header_re.match(line.strip())
        if m:
            slice_num += 1
            renumbered.append(re.sub(r"^Slice\s+\d+", f"Slice {slice_num}", line.strip(), count=1))
        elif line.strip().lower().startswith("slices to deliver:"):
            m2 = re.search(r"(\d+)", line)
            if m2:
                renumbered.append(re.sub(r"\d+", str(int(m2.group(1)) - 1), line, count=1))
            else:
                renumbered.append(line)
        else:
            renumbered.append(line)
    return renumbered


_bw_product_slice_header_re = re.compile(r"^(?:Section \d+ )?Product \d+$")


class SliceBriefValidationError(Exception):
    """Raised when a slice-by-slice designed-email brief fails a structural check
    against its own selected Figma template - a duplicate product/category slot, or a
    slice count that doesn't match the template. Callers (the parse_xxx_response() /
    build_html_notes() functions in this module) intentionally do NOT catch this and
    return a fallback brief - the whole point is that a broken brief must not become an
    Asana task at all. Whoever is briefing (almost always a live Claude Code session
    self-generating the completion per this file's "Calendar Task Creation Workflow"
    docstrings) should read the message, regenerate the completion to fix the specific
    issue named, and re-parse - not suppress the exception and proceed anyway.

    Confirmed need 2026-08-01: a batch of CZ tasks briefed 2026-07-15 shipped with
    wrong "Slices to deliver" counts, a Multi-Hero merge-rule violation, and a
    duplicated category CTA/link, all of which only produced a [WARN] print that
    nobody saw scroll by during a multi-task briefing session. Warn-only isn't enough
    for defects this mechanically detectable - see memory/project_cz_slice_qa.md.
    """


def _is_strict_product_link_field(field_text: str) -> bool:
    """True if a template's `Link: [...]` field text designates a single, specific
    product's own page - never a category/collection fallback.

    Started as a literal `"product page" in text` substring check, which missed real
    phrasings already in use across BW/STF/CZ templates: `[product LP]` (STF Template
    4/6), `[product 1 page]`/`[product 2 page]` (BW mcs_v2 and siblings' paired
    Section-N-Product-1/2 slices). Confirmed gap 2026-08-01 while auditing the BW
    product-link bug: `_warn_duplicate_products()`'s schema-driven detection silently
    skipped every slice using these phrasings because none contained the exact
    substring "product page" - the mechanical check simply never looked at them.

    Heuristic: text mentions "product" and either "page" or "lp", and does NOT also
    mention "collection" - `[product/collection LP]` and `[product or collection LP]`
    (TI's product_multi/product_single templates) are an intentional either/or fallback
    the AI picks based on content, not a hard single-product requirement, so they're
    excluded. Verified against every distinct `Link: [...]` field string in this file
    (2026-08-01): this heuristic classifies all of them correctly with no false
    positives/negatives against the current vocabulary.
    """
    ft = field_text.lower()
    if "collection" in ft:
        return False
    return "product" in ft and ("page" in ft or "lp" in ft)


def _warn_duplicate_products(body_copy_lines: List[str], template_slices: Optional[list] = None) -> None:
    """Raise SliceBriefValidationError if two single-item slices in the same body copy
    share an identical Name or Link - a signal the AI substituted a generic name/link
    for what should be distinct items (e.g. two slices both named "Field Ottoman", or
    both linking to the same /collections/... URL instead of their own product/category
    page).

    A slice counts as "single-item" one of two ways:
    - `template_slices` given (the template's own `slices` list from
      BW_FIGMA_TEMPLATES/STF_FIGMA_TEMPLATES/CZ_FIGMA_TEMPLATES): any slice whose field
      list declares a `Link:` field mentioning "product page" or "category" - this is
      schema-driven, so it catches every naming convention a template uses ("Product
      N", "Section N Product N", "Spotlight N", "Product Image N", "Category N",
      "Category Block N", etc.) without needing a new name pattern hardcoded per
      template. Confirmed by inspection 2026-08-01: every CZ/BW/STF field mentioning
      "product page" or "category" is a genuine distinct-item Link placeholder
      ("[product page]", "[product page URL]", "[category page URL]", "[category N
      LP]") - never a shared/merged-slice field like "[hero LP]" or "[main LP]", so
      broadening past just "product page" is safe. This closes a real gap: CZ's Task 9
      "Flash Sale Last Chance" (Product Feature Full Bleed) had a "Rugs" category slice
      whose CTA text and Link both duplicated the preceding "Furniture" slice verbatim -
      "product page" alone doesn't match category slices' "[category page URL]"
      wording, so category-level duplication needed its own coverage. Confirmed gap
      2026-08-01: BUR "Leather Highlight" (fab_v4 / Multi Fabric Spotlight V1) has
      "Spotlight 1/2/3" slices whose schema already says `Link: [product page]`, but
      the old name-only regex only matched "Product N" and silently missed them - all 3
      Spotlight slices shared one broken hero link instead of linking to their own
      product.
    - `template_slices` omitted (e.g. no template context available): falls back to the
      original `_bw_product_slice_header_re` name-pattern match ("Product N" / "Section
      N Product N") for backward compatibility.

    There's no safe mechanical FIX here (picking a genuinely different real product
    needs live inventory data this function doesn't have) - but "can't auto-fix" is not
    the same as "must only warn." Every violation is printed, then raised together so
    the brief cannot silently become an Asana task; the caller must regenerate.
    Confirmed real case: BUR "Field Collection Highlight" (cs_v7) had Product 3 and
    Product 5 both named "Field Ottoman" - see memory/feedback_5050_pairing_rule.md.
    """
    single_item_names: Optional[set] = None
    if template_slices is not None:
        single_item_names = {
            s["name"].strip().lower()
            for s in template_slices
            if any(
                "link:" in f.lower() and (_is_strict_product_link_field(f) or "category" in f.lower())
                for f in s.get("fields", [])
            )
        }

    slices: List[tuple] = []
    current_header: Optional[str] = None
    current_lines: List[str] = []
    for line in body_copy_lines:
        m = _stf_slice_header_re.match(line.strip())
        if m:
            if current_header is not None:
                slices.append((current_header, current_lines))
            current_header = m.group(1).strip()
            current_lines = []
        elif current_header is not None:
            current_lines.append(line)
    if current_header is not None:
        slices.append((current_header, current_lines))

    items = []
    for header, lines in slices:
        if single_item_names is not None:
            if header.strip().lower() not in single_item_names:
                continue
        elif not _bw_product_slice_header_re.match(header):
            continue
        name = None
        link = None
        for line in lines:
            s = line.strip()
            if s.lower().startswith("name:"):
                name = s.split(":", 1)[1].strip()
            elif s.lower().startswith("link:"):
                link = s.split(":", 1)[1].strip()
        items.append((header, name, link))

    names_seen: Dict[str, str] = {}
    links_seen: Dict[str, str] = {}
    violations: List[str] = []
    for header, name, link in items:
        if name:
            if name in names_seen:
                msg = (
                    f"'{names_seen[name]}' and '{header}' both have Name '{name}' - "
                    f"each slot should be a distinct product/category."
                )
                print(f"[ERROR] _warn_duplicate_products: {msg}")
                violations.append(msg)
            else:
                names_seen[name] = header
        if link and "NEEDS PRODUCT PAGE" in link.upper():
            # The unresolved "[NEEDS PRODUCT PAGE — resolve via resolve_product_link()]"
            # placeholder is INTENTIONALLY identical across every not-yet-resolved
            # single-product slice (see product_n_instruction) - it's a sentinel, not a
            # real shared link, and gets resolved to a distinct real URL per-slice by
            # _resolve_product_slice_links() right after this function runs. Flagging it
            # as a duplicate here would reject every multi-product-slice brief that
            # correctly followed instructions, before resolution ever got a chance to run.
            continue
        if link:
            if link in links_seen:
                msg = (
                    f"'{links_seen[link]}' and '{header}' both Link to '{link}' - each "
                    f"slot should link to its own page, not a shared/generic link."
                )
                print(f"[ERROR] _warn_duplicate_products: {msg}")
                violations.append(msg)
            else:
                links_seen[link] = header

    if violations:
        raise SliceBriefValidationError(
            "Duplicate product/category content in slice-by-slice brief:\n"
            + "\n".join(f"  - {v}" for v in violations)
        )


_product_page_link_re = re.compile(r"https?://[^/\s]+/products/", re.IGNORECASE)


def _warn_generic_link_for_product_slice(body_copy_lines: List[str], template_slices: list) -> None:
    """Raise SliceBriefValidationError when a slice whose template schema calls for ONE
    specific product's own page (`Link: [product page]` / `[product page URL]`, never a
    `[category ...]` field) doesn't actually link to a `/products/...` page - most often
    because it links to a generic `/collections/...` URL instead. Checks positively for
    `/products/` (rather than just excluding `/collections/`) so any other wrong-kind
    link (homepage, a reused hero LP, an unresolved placeholder) is caught too, not just
    the collection-link variant.

    Confirmed real bug, 2026-07-31 BW "Last Chance — up to 35% off" (Multi Collection
    Spotlight V9): all 4 "Product feature N" slices - Nomad Sofa, Range 3-Piece Sectional
    Lounger, Range Ottoman, and a "Sleeper Sofas" slot - linked to generic
    `/collections/...` pages instead of each product's own `/products/...` page, and one
    (Range Ottoman) linked to a completely mismatched collection (`/collections/shift`,
    not Range or even a Range-adjacent collection). `_warn_duplicate_products()` didn't
    catch this because every slice had a *different* wrong link - it only flags links
    *repeated* across slices, not links that are individually the wrong kind of page.

    Schema-driven the same way as `_warn_duplicate_products()`: any slice whose fields
    declare a `Link:` mentioning "product page" (and not "category", which legitimately
    points at a collection) is checked, regardless of what the slice is named ("Product
    N", "Product feature N", "Spotlight N", etc.) - so this covers every BW/STF/CZ
    template without a per-template name pattern. There's no safe mechanical fix (picking
    the right live product-page URL needs `resolve_product_link()` against real
    inventory, which this function doesn't have) - every violation is collected and
    raised together so the brief cannot silently become an Asana task; the caller must
    regenerate with real resolved product links.
    """
    single_item_names = {
        s["name"].strip().lower()
        for s in template_slices
        if any(
            "link:" in f.lower() and _is_strict_product_link_field(f)
            for f in s.get("fields", [])
        )
    }
    if not single_item_names:
        return

    slices: List[tuple] = []
    current_header: Optional[str] = None
    current_lines: List[str] = []
    for line in body_copy_lines:
        m = _stf_slice_header_re.match(line.strip())
        if m:
            if current_header is not None:
                slices.append((current_header, current_lines))
            current_header = m.group(1).strip()
            current_lines = []
        elif current_header is not None:
            current_lines.append(line)
    if current_header is not None:
        slices.append((current_header, current_lines))

    violations: List[str] = []
    for header, lines in slices:
        if header.strip().lower() not in single_item_names:
            continue
        link = None
        for line in lines:
            s = line.strip()
            if s.lower().startswith("link:"):
                link = s.split(":", 1)[1].strip()
        if link and not _product_page_link_re.search(link):
            msg = (
                f"'{header}' is a single-product slot but its Link ('{link}') is not "
                f"that product's own /products/... page."
            )
            print(f"[ERROR] _warn_generic_link_for_product_slice: {msg}")
            violations.append(msg)

    if violations:
        raise SliceBriefValidationError(
            "Product-page slice linked to a generic collection page instead of its own "
            "product page:\n" + "\n".join(f"  - {v}" for v in violations)
        )


_slice_name_field_re = re.compile(r"^name:\s*(.+)$", re.IGNORECASE)
_slice_colorway_field_re = re.compile(r"^colorway:\s*(.+)$", re.IGNORECASE)
_slice_link_field_re = re.compile(r"^link:\s*(.+)$", re.IGNORECASE)


def _resolve_product_slice_links(body_copy_lines: List[str], template_slices: list, brand: str) -> List[str]:
    """Mandatory, mechanical replacement for the old "whoever is briefing must remember to
    call resolve_product_link() by hand before finalizing" instruction. For every single-
    product slice (schema-driven the same way as _warn_duplicate_products()/
    _warn_generic_link_for_product_slice() — any slice whose template field list declares
    a `Link:` field matching _is_strict_product_link_field()), this:

    1. Reads the slice's Name (product title) and, if present, Colorway.
    2. Calls resolve_product_link(brand, name, colorway) — a live Snowflake + HTTP check,
       never a guess.
    3. If the product has no live page at all, or the stated colorway isn't a real live
       variant of it (resolve_product_link reports substituted=True), raises
       SliceBriefValidationError naming the real colorway(s) available — the brief cannot
       become an Asana task with an invented color, it must be regenerated.
    4. Otherwise rewrites the slice's Link line in place to the resolved, verified URL
       (with the correct Fabric=/finish query param when a colorway was given) — the brief
       never ships with a bare placeholder or an unresolved product link either.

    Confirmed root cause, BUR "Range Pro Highlight" (2026-08-02): the brief described
    colorways ("oatmeal", "charcoal", "warm gray") that don't exist for Range Pro at all —
    the real options are "Moss Green - Performance Flatweave", "Georgia Clay - Performance
    Chenille", and "Camel - Top Grain Leather" — and every "Product N" slice linked to a
    bare product URL with no Fabric param, because resolve_product_link() was documented as
    a manual post-generation step that nothing actually enforced running. Wiring this into
    parse_bw_response()/parse_stf_response()/parse_cz_response() — BEFORE
    _warn_generic_link_for_product_slice(), not after: that check rejects anything that
    isn't already a real "/products/..." URL, so it would reject the correctly-instructed
    "[NEEDS PRODUCT PAGE...]" placeholder itself before this function ever got a chance to
    resolve it, which is the likely reason the original incident brief had guessed bare
    product URLs instead of placeholders — writing the placeholder as instructed was
    unwinnable against that check. Running resolution first means the placeholder is
    already a real, verified URL by the time that check runs, and the check still catches
    anything else that isn't a placeholder or a real product URL (e.g. a collection link
    written directly, ignoring the placeholder instruction entirely) — makes both halves of
    that bug structurally impossible: an invented colorway blocks the brief instead of
    silently substituting, and
    a resolvable one is auto-linked instead of depending on a human to run the resolver.

    No-op (returns body_copy_lines unchanged) for templates with no single-product slices,
    or brands resolve_product_link() doesn't support (only BUR/CZ/STF have the Shopify
    PRODUCT/PRODUCT_VARIANT tables this depends on).
    """
    single_item_names = {
        s["name"].strip().lower()
        for s in template_slices
        if any(
            "link:" in f.lower() and _is_strict_product_link_field(f)
            for f in s.get("fields", [])
        )
    }
    if not single_item_names:
        return body_copy_lines

    try:
        from scripts.utils.inventory_checker import resolve_product_link, SHOPIFY_BRANDS
    except Exception:
        return body_copy_lines
    if brand not in SHOPIFY_BRANDS:
        return body_copy_lines

    # Re-derive slice spans as (header, start_idx, end_idx) so the Link line can be
    # rewritten in place without disturbing anything else in the slice.
    slice_spans: List[tuple] = []
    current_header: Optional[str] = None
    current_start: Optional[int] = None
    for i, line in enumerate(body_copy_lines):
        m = _stf_slice_header_re.match(line.strip())
        if m:
            if current_header is not None:
                slice_spans.append((current_header, current_start, i))
            current_header = m.group(1).strip()
            current_start = i
    if current_header is not None:
        slice_spans.append((current_header, current_start, len(body_copy_lines)))

    new_lines = list(body_copy_lines)
    violations: List[str] = []

    for header, start, end in slice_spans:
        if header.strip().lower() not in single_item_names:
            continue

        name = None
        colorway = None
        link_idx = None
        for i in range(start, end):
            s = new_lines[i].strip()
            m_name = _slice_name_field_re.match(s)
            if m_name:
                name = m_name.group(1).strip()
                continue
            m_color = _slice_colorway_field_re.match(s)
            if m_color:
                colorway = m_color.group(1).strip()
                continue
            m_link = _slice_link_field_re.match(s)
            if m_link:
                link_idx = i

        if not name or link_idx is None:
            # Nothing to resolve against, or no Link line to rewrite — a different
            # validator is responsible for a missing Name/Link field entirely.
            continue

        try:
            result = resolve_product_link(brand, name, colorway)
        except Exception:
            # Live lookup itself failed (e.g. no Snowflake/HTTP access) — don't block
            # brief creation on an infrastructure hiccup; leave the line as-is for a
            # human to resolve, same as the pre-existing manual fallback.
            continue

        if result is None:
            violations.append(
                f"'{header}' (Name: {name}) has no live product page on {brand} at all — "
                f"this product may be discontinued, or the name doesn't exactly match a "
                f"real, ACTIVE Shopify listing. Use a real product name or a category "
                f"slice instead."
            )
            continue

        if result["substituted"]:
            real_colorway = result.get("colorway") or "(no live colorway found for this product)"
            requested = f'"{colorway}"' if colorway else "(none stated)"
            violations.append(
                f"'{header}' (Name: {name}) requested colorway {requested}, which is not "
                f"a real, live variant of this product. A real, live colorway for this "
                f"product is: {real_colorway}. Regenerate this slice using a real colorway "
                f"for {name} — never invent one."
            )
            continue

        new_lines[link_idx] = f"Link: {result['url']}"

    if violations:
        raise SliceBriefValidationError(
            "Invented or unresolvable product colorway/link in slice-by-slice brief:\n"
            + "\n".join(f"  - {v}" for v in violations)
        )

    return new_lines


_slice_header_count_re = re.compile(r"^Slice\s+\d+\s*[—–-]")


def _warn_slice_count_mismatch(all_lines: List[str], expected_count: int, template_label: str) -> int:
    """Count the "Slice N — ..." headers actually present in `all_lines` and raise
    SliceBriefValidationError if that count doesn't match `expected_count`.

    Confirmed real bug (2026-07-15 CZ batch, e.g. "Back in Stock" and "MTO Sofas: Artisan
    Story"): the "Slices to deliver: N" line was computed from the template's own base
    slice count (plus a manually-tallied +1 per sale banner / +1 per sale link-farm
    header) BEFORE the AI's actual generated content was known, and in CZ's case, before
    a kicker slice was even appended - so it silently went stale whenever the AI's
    delivered slice count didn't match the template (an extra/missing product slot, a
    merged-vs-split section, e.g. Multi-Hero's required single-slice merge being split
    into several) or whenever a kicker was auto-attached after the count was already
    written. Multiple tasks in that batch declared "Slices to deliver: N" that didn't
    match what was actually enumerated, and the mismatch only ever produced a [WARN]
    print that went unnoticed during a multi-task briefing session - the task got
    created anyway.

    The fix is architectural, not just this check: callers must NOT write the AI's own
    or a pre-computed "Slices to deliver" line up front. Instead, assemble the FULL
    final slice list first - including any auto-inserted sale banner, kicker, or sale
    link-farm header, all of which sit outside the template's own base `slices` catalog
    entry - THEN call this function. On a match, its return value (not `expected_count`)
    is what the caller uses for the "Slices to deliver" line. On a mismatch, it raises
    instead of returning - there's no safe way to auto-correct WHICH slice is wrong
    (merged content that should've stayed split, an extra product slot, etc. all look
    identical from here), so the caller must regenerate rather than ship a mismatched
    brief.
    """
    actual = sum(1 for ln in all_lines if _slice_header_count_re.match(ln.strip()))
    if actual != expected_count:
        msg = (
            f"slice count mismatch for {template_label}: template + any auto-inserted "
            f"sale banner/kicker/sale-link-farm header predicts {expected_count} slices, "
            f"but {actual} are actually delivered — likely a merged/split template "
            f"section or an extra/missing product slot."
        )
        print(f"[ERROR] _warn_slice_count_mismatch: {msg}")
        raise SliceBriefValidationError(msg)
    return actual


def _renumber_slices_sequentially(all_lines: List[str]) -> List[str]:
    """Renumber every "Slice N — ..." header in `all_lines` to run 1, 2, 3, ... in
    order of appearance, leaving every other line untouched.

    Kicker/sale-link-farm position math (e.g. CZ's kicker_num/lf_num) reserves a slot
    for a template's *optional* slices whether or not the AI actually used one (e.g.
    Template K's optional "Product Image 3") - the total count still comes out right,
    but the numbering can skip (Slice 4 then Slice 6, no Slice 5). This closes those
    gaps without needing to fix every position formula that can produce one.
    """
    out: List[str] = []
    slice_num = 0
    for line in all_lines:
        if _slice_header_count_re.match(line.strip()):
            slice_num += 1
            out.append(re.sub(r"^Slice\s+\d+", f"Slice {slice_num}", line.strip(), count=1))
        else:
            out.append(line)
    return out


_link_field_url_re = re.compile(r"Link:\s*(https?://[^\s·]+)")


def _assert_links_live(all_lines: List[str], template_label: str, timeout: int = 10) -> None:
    """Extract every "Link: https://..." field from `all_lines` and HTTP-check it,
    raising SliceBriefValidationError if any URL doesn't return 200.

    Uses re.search (not full-line match) so it catches both the dedicated
    "Link: https://..." lines CZ/STF/BUR/HAV use, and TI's single-line
    dot-separated slice format (e.g. "Slice 2 — Name · Link: https://... ·
    Alt: ..."), where the Link field is one dot-separated segment among
    several on the same line, not the whole line.

    This is a brand-agnostic, type-agnostic safety net — it doesn't care whether a
    Link field is meant to be a product page, a collection page, or anything else;
    it only asserts that whatever URL ended up there is real and live. Added
    2026-07-31 after auditing product-link resolution and finding: (a) several
    single-slice templates (CZ's A/Multi-Hero and J/Hero Only, BW's Collection
    Spotlight V1) have use-cases implying a specific named product but a schema
    that never flags the slice as needing `resolve_product_link()`, so a wrong or
    hallucinated link could sail through undetected; and (b) even where
    `resolve_product_link()` IS correctly invoked, nothing previously re-verified
    the final URL actually landed in the brief. Rather than trying to schema-detect
    "this slice should have been a product link" (unreliable — BW's `cs_v1` Hero
    genuinely can be either a product OR a collection depending on the story), this
    checks the one thing that's unconditionally true regardless of link type: the
    URL must actually resolve. Deliberately does NOT judge whether the URL is the
    *most relevant* choice — only whether it's real. Catalog URLs (bur_links.yaml,
    cz_links.yaml, stf_links.yaml, ti_links.yaml) are already verified at authoring
    time; this catches drift after the fact, plus anything not sourced from a
    catalog at all (a hallucinated URL, a `resolve_product_link()` result, a raw
    Asana LP field).

    Every distinct URL is checked once regardless of how many slices repeat it
    (e.g. a sale banner and sale link-farm header often share the same homepage
    URL) — this keeps a template with N slices from taking N times as long only
    because several slices point at the same page.
    """
    urls = []
    seen = set()
    for line in all_lines:
        for m in _link_field_url_re.finditer(line):
            url = m.group(1).rstrip(".,;")
            if url not in seen:
                seen.add(url)
                urls.append(url)

    if not urls:
        return

    dead = []
    for url in urls:
        try:
            r = requests.get(url, timeout=timeout, allow_redirects=True)
            if r.status_code != 200:
                dead.append(f"{url} (HTTP {r.status_code})")
        except requests.RequestException as e:
            dead.append(f"{url} ({type(e).__name__})")

    if dead:
        msg = (
            f"dead/unreachable link(s) in {template_label} brief — these must be "
            f"real, live URLs before this brief can be finalized: "
            + "; ".join(dead)
        )
        print(f"[ERROR] _assert_links_live: {msg}")
        raise SliceBriefValidationError(msg)


_quick_ship_product_link_re = re.compile(
    r"https?://(?:www\.)?burrow\.com/products/[a-z0-9\-]+(?:\?[^\s\"'<>]*)?", re.IGNORECASE
)


def _assert_quick_ship_products(all_lines: List[str], template_key: str) -> None:
    """For BUR's Quick Ship templates (qs_v1/qs_v2/qs_v3), verify every /products/{handle}
    link in the brief is actually ready-to-ship IN THE SPECIFIC COLORWAY LINKED - not just
    a product that happens to be ready-to-ship in some other colorway. This is the
    mechanical backstop for _get_bur_inventory_context()'s Quick Ship grounding above,
    catching the case where the AI ignores that grounding (or no grounding was available)
    and names a plausible but non-ready-to-ship product/colorway anyway.

    Confirmed real case, 2026-08-02: "Quick Ship — Designed" (qs_v2) featured Nomad
    Loveseat and Span Storage Chaise - both real Burrow products, both correctly resolved
    to their own /products/... page via resolve_product_link(), but neither actually
    ready-to-ship (3-5 day and 8-10 week lead times respectively). A follow-up check found
    Quick Ship status is colorway-specific, not product-level: e.g. Nomad Sofa is only
    ready-to-ship in "Sienna - Performance Brushed Chenille" - a link to any other live,
    in-stock colorway of the same product would pass a product-level check but still be
    wrong. Compares each resolved link's full (handle + colorway) signature against
    get_ready_to_ship_variants()'s live-scraped signatures, the same way _assert_links_live()
    re-verifies link liveness after resolution rather than trusting the prompt.

    A handle with only colorway-specific listings (no bare/no-query listing) requires the
    brief's link to carry a matching colorway query string - a bare link to that handle
    cannot be confirmed ready-to-ship and is treated as a violation, since resolve_product_link()
    will happily return a bare link when no Colorway was named, silently picking whatever
    live variant happens to be first.

    Fails open (prints a warning, does not raise) if the live page can't be reached at all
    - an inability to verify is not the same as a confirmed violation, and raising on a
    lookup failure would make Quick Ship briefs impossible to finalize without live
    network access.
    """
    if not template_key.startswith("qs_"):
        return

    links_found = {
        m.group(0) for line in all_lines for m in _quick_ship_product_link_re.finditer(line)
    }
    if not links_found:
        return

    try:
        from scripts.utils.inventory_checker import get_ready_to_ship_variants, _normalize_product_link_signature, _normalized_signature
        ready_to_ship = get_ready_to_ship_variants("BUR")
    except Exception as e:
        print(f"[WARN] _assert_quick_ship_products: could not verify live Ready to Ship "
              f"inventory ({type(e).__name__}) - skipping Quick Ship product check.")
        return

    if ready_to_ship is None:
        print("[WARN] _assert_quick_ship_products: could not reach burrow.com/ready-to-ship "
              "- skipping Quick Ship product check.")
        return

    handle_re = re.compile(r"/products/([a-z0-9\-]+)", re.IGNORECASE)
    violations: List[str] = []
    for link in links_found:
        m = handle_re.search(link)
        if not m:
            continue
        handle = m.group(1).lower()
        signatures = ready_to_ship.get(handle)
        if signatures is None:
            violations.append(
                f"{link} — '{handle}' is not on the live Ready to Ship page at all."
            )
            continue
        normalized_signatures = {_normalized_signature(s) for s in signatures}
        if () in normalized_signatures:
            continue  # this handle has a bare/no-colorway listing — any link to it passes
        link_sig = _normalized_signature(_normalize_product_link_signature(link))
        # Subset match, not exact-equality: resolve_product_link() only ever sets ONE
        # query param (e.g. just "Fabric=..."), never the full multi-attribute combo
        # (Fabric + Leg Finish + Arm Style) the live page's own hrefs carry. A real,
        # correctly-resolved link's params must all appear within (not equal) some live
        # signature - requiring exact equality would reject every genuinely correct
        # single-param link a real brief ever produces.
        link_param_set = set(link_sig)
        if not link_param_set or not any(link_param_set.issubset(set(sig)) for sig in normalized_signatures):
            real_options = ", ".join(
                sorted({v for s in signatures if s for _, v in s})
            ) or "(no colorway options found)"
            violations.append(
                f"{link} — this colorway is not ready-to-ship for '{handle}'. Real "
                f"ready-to-ship colorway(s) for this product: {real_options}."
            )

    if violations:
        msg = (
            "product(s)/colorway(s) in this Quick Ship brief are not actually "
            "ready-to-ship:\n" + "\n".join(f"  - {v}" for v in violations)
            + "\nEvery product AND colorway featured in a Quick Ship email must match "
            "https://burrow.com/ready-to-ship exactly — swap these for genuine "
            "ready-to-ship product/colorway combinations."
        )
        print(f"[ERROR] _assert_quick_ship_products: {msg}")
        raise SliceBriefValidationError(msg)


def build_stf_prompt(record: Dict[str, str], during_sale: bool = False,
                      inventory_context: Optional[str] = None) -> str:
    """Pure prompt-builder for STF designed emails - no API call, no API key required.

    Prefer this + parse_stf_response() over generate_stf_email_brief() when a live
    Claude Code session is doing the briefing (see build_cz_prompt()'s docstring for why).

    Auto-fetches real inventory (including real colorway/finish options) via
    _get_stf_inventory_context() when inventory_context isn't explicitly passed - same
    pattern as build_bw_prompt(), added 2026-08-02 alongside the mandatory
    _resolve_product_slice_links() check so STF gets prompt-level grounding, not just
    the after-the-fact mechanical check.
    """
    _inventory_auto_fetched = False
    if inventory_context is None:
        inventory_context = _get_stf_inventory_context(record)
        _inventory_auto_fetched = True

    # STF link catalog (categories + product categories) from stf_links.yaml.
    def _links_text(section: str) -> str:
        return "\n".join(
            f"  {item['url']} — {item['label']}"
            for item in _stf_links_data.get(section, [])
            if isinstance(item, dict) and item.get("url")
        )
    _stf_categories_text = _links_text("categories")
    _stf_product_categories_text = _links_text("product_categories")

    templates_detail = "\n\n".join(
        f"[{key}] {t['name']} — {t['description']}\n"
        f"Use cases: {', '.join(t['use_cases'])}\n"
        + _describe_stf_slices(t["slices"])
        for key, t in STF_FIGMA_TEMPLATES.items()
    )

    if inventory_context:
        inventory_section = (
            f"\nCurrently available / suggested St. Frank products:\n{inventory_context}\n"
            "Prefer these when a slice needs a specific product name. A product's real "
            "colorway/finish options, if any exist, are listed directly under it as "
            "\"colorways/finishes: ...\" - if you name a specific color or fabric for that "
            "product, it MUST be one of those values, verbatim. Never invent a color/finish "
            "for a product that has no colorways/finishes line at all.\n"
        )
    elif _inventory_auto_fetched:
        inventory_section = (
            "\nNo live inventory data was available for this brief. Because of that, do NOT "
            "name specific product model variants or finishes/colorways you cannot verify. "
            "Default to general category names with a category-level link whenever a slice "
            "would otherwise need an unverified specific product name or colorway.\n"
        )
    else:
        inventory_section = ""

    sale_instruction = ""
    if during_sale:
        sale_instruction = (
            "\nThis email lands during an active sale. A sale banner is auto-added as Slice 1 "
            "for every template EXCEPT the dedicated sale hero (t7), so do NOT restate the "
            "discount in a hero eyebrow/HED unless you selected t7 (where the hero IS the sale).\n"
        )

    prompt = f"""You are briefing a St. Frank designed email campaign. Do three things:

1. SELECT the best Figma template from the list below based on the email topic and use cases.
2. WRITE a 1-sentence creative direction (goal, key message, tone). Keep St. Frank's voice: artfull, globally-inspired, elevated, warm; celebrates handcraft and pattern. No emojis.
3. GENERATE structured body copy — slice by slice for the selected template.
{sale_instruction}
Slice rules:
- Output slices in the SAME ORDER as the template definition, using the EXACT slice name.
- Reproduce the "Layout:" line exactly as given for each slice (Full width / 50/50 left / 50/50 right).
- [IMAGE]: write "  Visual: [1–2 sentences for an AI image generator — composition, featured products by name, styling props, mood, lighting]" then fill each text field. For [IMAGE — fill fields only] slices (CTA buttons, copy bands, kickers), skip the Visual line.

Product rules:
- Only use product names from the suggested-products list below when a slice needs a specific product; never invent product names or URLs.
- For ANY slice whose field list below includes "Link: [product page]" / "[product LP]" / "[product N page]" (a repeatable single-product grid slot - this applies no matter what the slice is named: "Product N", "Product variant N", "Section N Product N", etc. - check each template's own field list, not just the slice name): each one must be a distinct, specific product with a link to that product's own page. Never reuse the same Name or the same Link across more than one such slice in the same grid, and never use a category/collection name or link there (that belongs on a category-header slice instead, whose field says "[category LP]").
- The Link for one of these slices MUST be that one specific product's own page - stfrank.com/products/{{handle}}, never stfrank.com/collections/{{...}}. You cannot reliably guess the exact handle yourself, so write the literal placeholder "Link: [NEEDS PRODUCT PAGE — resolve via resolve_product_link()]" for these slices instead of a collection URL; this is resolved and verified AUTOMATICALLY after parsing, not a manual step.
- If a slice's Visual/copy names a specific color or fabric/finish for that product, never invent one - only name a colorway you're actually certain is real for that product, and add its own "Colorway: <value>" line right after the Name/HED line. If you're not certain a specific colorway is real, don't name one - describe the product generically instead. An invented colorway will cause the brief to be rejected and regenerated.

Link rules — fill every Link: field with a URL from the lists below; do not invent URLs.
- Hero / main CTA: use the Recommended LP if provided above; otherwise pick the best match below (or https://www.stfrank.com/ for a general sale).
- Category slices (field says "Link: [category LP]"): pick the best-matching product-category URL below.
- Single-product slices (field says "Link: [product page]" / "[product LP]" / similar — see the product rule above): do NOT use a category URL here — write the "[NEEDS PRODUCT PAGE — resolve via resolve_product_link()]" placeholder instead.

CATEGORIES (general LPs):
{_stf_categories_text}

PRODUCT CATEGORIES (use for category/product slice links):
{_stf_product_categories_text}

Email topic: {record['story']}
{f"Promo: {record['promo']}" if record.get('promo') else ""}
{f"Notes: {record['notes']}" if record.get('notes') else ""}
{f"Landing page: {record['landing_page']}" if record.get('landing_page') else ""}
{inventory_section}
TEMPLATES:
{templates_detail}

Return ONLY this exact format — no extra commentary:
TEMPLATE: [key, e.g. t6 or t3 or t8]
DIRECTION: [1-sentence creative direction]
BODY_COPY:
Slice 1 — [EXACT slice name] [IMAGE]
  Visual: [visual description]
  Layout: [layout]
  [Field]: [value]

Slice 2 — [EXACT slice name] [IMAGE]
  ..."""
    # Re-run send: tell the model how to frame DIRECTION (no-op for normal rows).
    _resend_block = resend_prompt_instruction(record)
    if _resend_block:
        prompt += "\n" + _resend_block
    return prompt


def parse_stf_response(text: str) -> Optional[Dict[str, str]]:
    """Pure response-parser for STF designed emails - no API call. See parse_cz_response()
    (including its note on SliceBriefValidationError - raised, not swallowed, on
    duplicate product/category content)."""
    try:
        text = text.strip().replace("\\n", "\n")
        lines = text.split("\n")

        template_key = None
        direction = None
        body_copy_lines: List[str] = []
        in_body_copy = False

        for line in lines:
            if line.startswith("TEMPLATE:"):
                val = line.replace("TEMPLATE:", "").strip().lower()
                if val in STF_FIGMA_TEMPLATES:
                    template_key = val
                else:
                    for k in STF_FIGMA_TEMPLATES:
                        if k == val or k in val.split():
                            template_key = k
                            break
            elif line.startswith("DIRECTION:"):
                direction = line.replace("DIRECTION:", "").strip()
            elif line.startswith("BODY_COPY:"):
                in_body_copy = True
            elif in_body_copy:
                body_copy_lines.append(line.strip() if line.strip() else "")

        if not template_key or template_key not in STF_FIGMA_TEMPLATES:
            return None

        # Guarantee correct per-slice Layout lines regardless of what the AI emitted.
        body_copy_lines = _stf_inject_layouts(body_copy_lines, template_key)
        body_copy_lines = _enforce_5050_pairing(body_copy_lines)

        t = STF_FIGMA_TEMPLATES[template_key]
        _warn_duplicate_products(body_copy_lines, template_slices=t["slices"])
        body_copy_lines = _resolve_product_slice_links(body_copy_lines, template_slices=t["slices"], brand="STF")
        _warn_generic_link_for_product_slice(body_copy_lines, template_slices=t["slices"])
        node_url = t["node_id"].replace(":", "-")
        figma_url = (
            f"https://www.figma.com/design/{STF_FIGMA_FILE_KEY}"
            f"/St.-Frank-Templates-2026?node-id={node_url}&m=dev"
        )
        body_copy_text = "\n".join(
            f"    {line}" if line else ""
            for line in body_copy_lines
        )

        return {
            "brand": "STF",
            "template_key": template_key,
            "template_name": t["name"],
            "template_node_id": t["node_id"],
            "figma_url": figma_url,
            "direction": direction or "",
            "body_copy": body_copy_text,
        }
    except SliceBriefValidationError:
        raise
    except Exception:
        return None


def generate_stf_email_brief(record: Dict[str, str], during_sale: bool = False,
                              inventory_context: Optional[str] = None) -> Optional[Dict[str, str]]:
    """Convenience wrapper: calls the Anthropic API directly. Prefer build_stf_prompt() +
    parse_stf_response() when a live Claude Code session is doing the briefing - see
    build_cz_prompt()'s docstring for why.

    Slice-by-slice like CZ/TI. Returns dict with keys: brand ("STF"), template_key,
    template_name, template_node_id, figma_url, direction, body_copy — or None on failure.
    """
    api_key = os.environ.get("ANTHROPIC_API_KEY")
    if not api_key:
        return None

    prompt = build_stf_prompt(record, during_sale=during_sale, inventory_context=inventory_context)

    try:
        resp = requests.post(
            "https://api.anthropic.com/v1/messages",
            headers={
                "x-api-key": api_key,
                "anthropic-version": "2023-06-01",
                "content-type": "application/json",
            },
            json={
                "model": "claude-haiku-4-5-20251001",
                "max_tokens": 2400,
                "messages": [{"role": "user", "content": prompt}],
            },
            timeout=45,
        )
        if resp.status_code != 200:
            return None

        text = resp.json()["content"][0]["text"]
        return parse_stf_response(text)
    except Exception:
        return None


# Named BUR collections/products worth a targeted inventory lookup when mentioned in a
# brief's story/notes. Confirmed 2026-07-31: several of these (e.g. Shift) turned out to
# be a single SKU, not a full sofa/loveseat/sectional lineup - the AI invented plausible
# but nonexistent model variants (e.g. "Shift Loveseat", "Nomad Sectional", "Union Ottoman")
# across ~15 of 44 briefed tasks because no real inventory was ever passed to the prompt.
_BUR_KNOWN_COLLECTIONS = [
    "Nomad", "Range", "Shift", "Union", "Field", "Pro & Plus", "Pro and Plus",
    "Chorus", "Gallery", "Listo", "Sonnet", "Opera", "Index",
    "Dining Tables", "Dining Chairs", "Dining Stools",
]

# Some collections are sub-categories of a broader topic word a story is likely to use
# generically (e.g. "dining essentials", "hosting") without spelling out each specific
# collection name verbatim. Expand these trigger words to their full set of real
# sub-collections so the AI still gets per-product grounding instead of falling through
# to the generic top-stocked fallback, which skews toward high-volume Nomad seating and
# will never surface a lower-stock category like dining tables (133 units) alongside
# Nomad Armchair (12,473 units). Confirmed gap 2026-07-31: "Hosting Highlight"'s story
# said "dining and hosting essentials" (not "dining tables"), matched nothing in
# _BUR_KNOWN_COLLECTIONS, and the AI repeated the generic "Dining Tables" category name
# and a category-level link across all 4 Product N slices instead of naming 4 distinct
# real products - see memory/feedback_5050_pairing_rule.md sibling note.
#
# "haiku"/"alto" map here rather than into _BUR_KNOWN_COLLECTIONS because they're
# individual product names, not Shopify collection titles - get_collection_products()
# matches against real collection names, and neither "Haiku" nor "Alto" (nor the
# previous bogus "Haiku Alto" entry) resolves to any collection; only the real "Dining
# Stools" collection does, and it correctly contains both stools. Confirmed bug
# 2026-08-02: "Haiku Alto Stools Highlight" (task asks for BOTH stools) got briefed as a
# single-product Alto-only send because "Haiku Alto" as a _BUR_KNOWN_COLLECTIONS entry
# silently returned zero inventory rows, and the single-product Collection Spotlight V1
# template picked for it reinforced a one-product narrative.
_BUR_TOPIC_EXPANSIONS = {
    "dining": ["Dining Tables", "Dining Chairs", "Dining Stools"],
    "haiku": ["Dining Stools"],
    "alto": ["Dining Stools"],
}

# Keywords that signal a Quick Ship-themed brief (BUR's qs_v1/qs_v2/qs_v3 templates).
# Checked BEFORE the generic _BUR_KNOWN_COLLECTIONS matching below, and — when matched —
# used EXCLUSIVELY (not merged with other collection matches), because a Quick Ship email
# must draw ONLY from the live Ready to Ship page's exact colorway-specific listings, not
# from a named collection's full lineup (which may include made-to-order/long-lead-time
# variants of the same product line). Confirmed gap 2026-08-02: "Quick Ship — Designed"
# (qs_v2) had no keyword in _BUR_KNOWN_COLLECTIONS matching "quick ship"/"ready to ship",
# so it silently fell through to the generic top-stocked fallback below and featured Nomad
# Loveseat ("Ships in 3-5 days") and Span Storage Chaise ("Ships in 8-10 weeks") — neither
# actually ready-to-ship — alongside genuinely ready-to-ship items.
_BUR_QUICK_SHIP_KEYWORDS = ("quick ship", "ready to ship", "ready-to-ship")

# Minimum collection-title length to consider as a story/notes match - filters out
# noise from single-word generic titles ("New", "Sale") that would false-positive on
# nearly every brief without adding real per-product grounding value.
_MIN_COLLECTION_TITLE_LEN = 4
# Cap how many matched collections get queried per brief, to bound Snowflake calls.
_MAX_MATCHED_COLLECTIONS = 6


def _match_real_collections(brand: str, story_notes: str) -> List[str]:
    """Find real, live Shopify collection names (via list_collection_titles()) that
    appear in a brief's story/notes text, WITHOUT hand-maintaining a static per-brand
    list like _BUR_KNOWN_COLLECTIONS - that approach drifts out of sync with the real
    catalog (e.g. the bogus "Haiku Alto" entry that silently matched zero rows,
    confirmed 2026-08-02) and CZ/STF never had one to begin with. Longer/more specific
    titles are checked first so a broad, generic match doesn't crowd out a more
    specific one when both would fit under _MAX_MATCHED_COLLECTIONS.

    Used by _get_stf_inventory_context()/_get_cz_inventory_context() - BUR keeps its
    existing hardcoded-list + topic-expansion approach (_BUR_KNOWN_COLLECTIONS /
    _BUR_TOPIC_EXPANSIONS) since it also encodes deliberate curation (e.g. mapping
    "haiku"/"alto" product names to the "Dining Stools" collection) that a pure
    real-title substring match wouldn't reproduce; this dynamic version is for brands
    with no existing curation to preserve.
    """
    try:
        from scripts.utils.inventory_checker import list_collection_titles
        titles = list_collection_titles(brand)
    except Exception:
        return []

    matched = []
    for title in sorted(titles, key=len, reverse=True):
        if len(title) < _MIN_COLLECTION_TITLE_LEN:
            continue
        if title.lower() in story_notes:
            matched.append(title)
        if len(matched) >= _MAX_MATCHED_COLLECTIONS:
            break
    return matched


def _get_stf_inventory_context(record: Dict[str, str]) -> Optional[str]:
    """Auto-fetch real STF inventory (including real colorway/finish options) for any
    real collection whose name is mentioned in the story/notes, falling back to
    top-stocked products generally. Mirrors _get_bur_inventory_context()'s shape, but
    matches against STF's real, live collection titles (_match_real_collections())
    instead of a hand-maintained list, since STF never had one.

    Returns None (not empty string) on any failure so build_stf_prompt() can
    distinguish "no data" from "checked, nothing found" and strengthen its no-invent
    instruction accordingly - same contract as _get_bur_inventory_context().
    """
    try:
        from scripts.utils.inventory_checker import (
            get_collection_products, get_top_stocked_products, format_inventory_for_prompt,
        )
    except Exception:
        return None

    story_notes = f"{record.get('story', '')} {record.get('notes', '')}".lower()

    try:
        matched = _match_real_collections("STF", story_notes)
        if matched:
            sections = []
            for coll in matched:
                products = get_collection_products("STF", coll, limit=15)
                if products:
                    sections.append(
                        f"{coll} collection:\n"
                        f"{format_inventory_for_prompt(products, max_items=15, include_variants=True)}"
                    )
            if sections:
                return "\n\n".join(sections)
        products = get_top_stocked_products("STF", limit=30)
        if products:
            return format_inventory_for_prompt(products, max_items=30)
        return None
    except Exception:
        return None


def _get_cz_inventory_context(record: Dict[str, str]) -> Optional[str]:
    """Auto-fetch real CZ inventory (including real colorway/finish options) for any
    real collection whose name is mentioned in the story/notes, falling back to
    top-stocked products generally. See _get_stf_inventory_context()'s docstring - same
    shape, same contract, CZ-scoped.

    Note: build_cz_prompt() also has its own static, curated data/cz_links.yaml
    products list used for the PRODUCTS section of the prompt (name + URL, no
    colorway data) - this function is a separate, additive source specifically for
    real colorway/finish grounding, not a replacement for that catalog.
    """
    try:
        from scripts.utils.inventory_checker import (
            get_collection_products, get_top_stocked_products, format_inventory_for_prompt,
        )
    except Exception:
        return None

    story_notes = f"{record.get('story', '')} {record.get('notes', '')}".lower()

    try:
        matched = _match_real_collections("CZ", story_notes)
        if matched:
            sections = []
            for coll in matched:
                products = get_collection_products("CZ", coll, limit=15)
                if products:
                    sections.append(
                        f"{coll} collection:\n"
                        f"{format_inventory_for_prompt(products, max_items=15, include_variants=True)}"
                    )
            if sections:
                return "\n\n".join(sections)
        products = get_top_stocked_products("CZ", limit=30)
        if products:
            return format_inventory_for_prompt(products, max_items=30)
        return None
    except Exception:
        return None


def _get_bur_inventory_context(record: Dict[str, str]) -> Optional[str]:
    """Auto-fetch real BUR inventory for any named collection mentioned in the story/
    notes, falling back to top-stocked products generally. Returns None (not empty
    string) on any failure (e.g. no Snowflake access) so callers can tell "no data"
    apart from "checked, nothing found" - build_bw_prompt() strengthens its no-invent
    instruction in that case instead of silently proceeding as if data was available.
    """
    try:
        from scripts.utils.inventory_checker import get_collection_products, get_top_stocked_products, format_inventory_for_prompt
    except Exception:
        return None

    story_notes = f"{record.get('story', '')} {record.get('notes', '')}".lower()

    if any(kw in story_notes for kw in _BUR_QUICK_SHIP_KEYWORDS):
        # Quick Ship status is COLORWAY-specific, not product-level - confirmed 2026-08-02:
        # the live /ready-to-ship page links to specific fabric/finish combos per product
        # (e.g. Nomad Sofa is only ready-to-ship in "Sienna - Performance Brushed
        # Chenille"), and neither Shopify collection membership nor Snowflake inventory
        # depth predicts this (Span Storage Chaise has 70-100+ units in every colorway yet
        # quotes an 8-10 week lead time on its own product page). So use the live-page-
        # scraped, colorway-precise formatter here, NOT get_collection_products() (which
        # only checks product-level collection membership and would re-introduce the same
        # imprecision this fix targets).
        try:
            from scripts.utils.inventory_checker import format_ready_to_ship_prompt_context
            ctx = format_ready_to_ship_prompt_context("BUR", limit=30)
            if ctx:
                return (
                    "Ready to Ship products (live-verified from burrow.com/ready-to-ship "
                    "— ONLY these products, AND ONLY the exact colorway/finish listed for "
                    "each, are actually ready-to-ship; a different colorway of the same "
                    "product is likely made-to-order with a much longer lead time):\n"
                    f"{ctx}"
                )
        except Exception:
            pass
        # Fall through to the generic matching/fallback below only if the live page
        # couldn't be reached at all - better to ground in something than nothing, but
        # this should be rare (see build_bw_prompt's no-invent instruction, which still
        # applies either way).

    matched = [c for c in _BUR_KNOWN_COLLECTIONS if c.lower() in story_notes]
    for topic, sub_collections in _BUR_TOPIC_EXPANSIONS.items():
        if topic in story_notes:
            matched.extend(c for c in sub_collections if c not in matched)

    try:
        if matched:
            sections = []
            for coll in matched:
                products = get_collection_products("BUR", coll, limit=15)
                if products:
                    sections.append(
                        f"{coll} collection:\n"
                        f"{format_inventory_for_prompt(products, max_items=15, include_variants=True)}"
                    )
            if sections:
                return "\n\n".join(sections)
        # No named collection matched (or none had products) - general fallback so the
        # AI still has SOME real grounding instead of none.
        products = get_top_stocked_products("BUR", limit=30)
        if products:
            return format_inventory_for_prompt(products, max_items=30)
        return None
    except Exception:
        return None


def build_bw_prompt(record: Dict[str, str], during_sale: bool = False,
                     inventory_context: Optional[str] = None) -> str:
    """Pure prompt-builder for BUR (Burrow) designed emails - no API call (to Anthropic;
    it does query Snowflake for real inventory, see below), no API key required. Prefer
    this + parse_bw_response() over generate_bw_email_brief() when a live Claude Code
    session is doing the briefing - see build_cz_prompt()'s docstring for why.

    Auto-fetches real inventory via _get_bur_inventory_context() when inventory_context
    isn't explicitly passed - this is what makes the "never invent product names" rule
    below actually enforceable instead of just a hopeful instruction with nothing behind
    it. Confirmed missing 2026-07-30/31: without this, the AI plausibly invented product
    model variants and finish/colorway names that don't exist across ~15 of 44 BW tasks
    (e.g. "Shift Loveseat" when Shift is really just one sleeper-sofa SKU; a 4th "Charcoal"
    finish for Opera Media Console, which only ships in Oak/Walnut/Blackened Oak).
    """
    _inventory_auto_fetched = False
    if inventory_context is None:
        inventory_context = _get_bur_inventory_context(record)
        _inventory_auto_fetched = True

    # BUR link catalog (categories + product categories) from bur_links.yaml.
    def _links_text(section: str) -> str:
        return "\n".join(
            f"  {item['url']} — {item['label']}"
            for item in _bur_links_data.get(section, [])
            if isinstance(item, dict) and item.get("url")
        )
    _bur_categories_text = _links_text("categories")
    _bur_product_categories_text = _links_text("product_categories")

    templates_detail = "\n\n".join(
        f"[{key}] {t['name']} — {t['description']}\n"
        f"Use cases: {', '.join(t['use_cases'])}\n"
        + _describe_stf_slices(t["slices"])
        for key, t in BW_FIGMA_TEMPLATES.items()
    )

    if inventory_context:
        inventory_section = (
            f"\nReal, in-stock Burrow products (verified from live inventory):\n{inventory_context}\n"
            "Every specific product name, model variant, and finish/colorway in your body copy MUST come "
            "from this list, verbatim - including collections mentioned generically in the email topic "
            "below. If a collection has only one real model (e.g. just one sofa, no loveseat/sectional "
            "variant), do not invent additional variants for it. If you need a product not covered by this "
            "list, use a general category name (e.g. \"Sofas\", \"Dining Chairs\") and a category-level link "
            "instead of a specific but unverified product name.\n"
            "A product's real colorway/finish options, if any exist, are listed directly under it as "
            "\"colorways/finishes: ...\" - if you name a specific color or fabric in a slice's Visual/copy "
            "for that product, it MUST be one of those values, verbatim (e.g. \"Georgia Clay - Performance "
            "Chenille\", not a shortened \"Georgia Clay\" or a paraphrase). Never invent a color/finish for a "
            "product that has no colorways/finishes line at all, and never describe a product's material as "
            "\"performance fabric\" or similar unless the named colorway is actually a fabric (not a leather "
            "or wood finish) — check the colorway text itself. If none of the real colorways fit the scene "
            "you want to describe, change the scene, don't invent a color.\n"
        )
    elif _inventory_auto_fetched:
        # Real inventory lookup was attempted and failed (e.g. no Snowflake access) -
        # this is NOT the same as "no products relevant to this email exist". Make the
        # no-invent rule load-bearing even without data to check against.
        inventory_section = (
            "\nNo live inventory data was available for this brief. Because of that, do NOT name "
            "specific product model variants or finishes/colorways you cannot verify (e.g. don't invent "
            "\"Nomad Sectional\" or \"Opera Media Console in Charcoal\" if you're not certain they're real "
            "products). Default to general category names (e.g. \"Sofas\", \"Dining Chairs\") with a "
            "category-level link whenever a slice would otherwise need an unverified specific product name.\n"
        )
    else:
        inventory_section = ""

    # ANY slice whose field list below includes "Link: [product page]" is a single-
    # product slot - regardless of whether the template names it "Product N", "Product
    # feature N", or "Spotlight N" - and is a repeatable grid where every slot must be a
    # distinct, specific product on its own /products/... page. The category-name
    # fallback above is for slices that are GENUINELY generic (e.g. a "Category feature"
    # or "Category CTA button" slice, whose field says "Link: [category LP]"), not for
    # these. Confirmed bugs:
    # (1) 2026-07-31 "Hosting Highlight" (mcs_v5) had 4 "Product N" slices meant to be 4
    # distinct dining tables, but no real inventory was found for "dining" (not in
    # _BUR_KNOWN_COLLECTIONS at the time), so the AI wrote the same generic "Dining
    # Tables" name + the same collection link into all 4 slots. (2) Same day, "Field
    # Collection Highlight" (cs_v7) had Product 3 and Product 5 both named "Field
    # Ottoman" - a real product name, but duplicated across two slots that should each
    # be a different item. (3) Several other tasks (Range Pro Highlight, Pro Plus
    # Highlight, Union Collection Highlight) had genuinely distinct Name values per
    # Product N slice, but EVERY slice's Link pointed at the same shared collection URL
    # instead of that specific product's own page - see memory/feedback_5050_pairing_rule.md.
    # (4) 2026-07-30 "Last Chance — up to 35% off" (mcs_v9) had 4 "Product feature N"
    # slices with genuinely distinct product names (Nomad Sofa, Range 3-Piece Sectional
    # Lounger, Range Ottoman, a sleeper sofa), but EVERY link was a generic
    # /collections/... URL instead of that product's own /products/... page, and one
    # (Range Ottoman) linked to a completely unrelated collection (/collections/shift) -
    # the earlier fix for this instruction only covered slices literally named
    # "Product N", so "Product feature N" (used by mcs_v8/v9/v10 and others) slipped
    # through untouched. `_warn_generic_link_for_product_slice()` is the mechanical
    # backstop for this specific failure mode; this instruction is the prompt-side fix.
    product_n_instruction = (
        "\nFor ANY slice whose field list below includes \"Link: [product page]\" (a "
        "repeatable single-product grid slot - this applies no matter what the slice is "
        "named: \"Product N\", \"Product feature N\", \"Spotlight N\", etc. - check each "
        "template's own field list above, not just the slice name): each one MUST be a "
        "distinct, specific named product with a link to that product's own page. "
        "Concretely:\n"
        "  - Never reuse the same Name/HED (even a real, verified product name) for more "
        "than one such slice in the same grid.\n"
        "  - Never reuse a category or collection name (e.g. \"Dining Tables\") as the "
        "Name/HED for one of these slices at all - that belongs on a Category feature/"
        "header slice, not a single-product slot.\n"
        "  - The Link MUST be that one specific product's own page - burrow.com/products/"
        "{{handle}}, never burrow.com/collections/{{...}} - even when every slice's Name "
        "is correctly distinct. You cannot reliably guess the exact handle yourself, so "
        "write the literal placeholder \"Link: [NEEDS PRODUCT PAGE — resolve via "
        "resolve_product_link()]\" for these slices instead of a collection URL. This is "
        "resolved and verified AUTOMATICALLY after parsing (not a manual step anymore) - "
        "if the colorway you named isn't real, the brief is rejected and you must "
        "regenerate with a real one from the colorways/finishes list, so get it right the "
        "first time rather than relying on the check to catch it.\n"
        "  - If the slice's Visual/copy names a specific color or fabric/finish for this "
        "product, ALSO add its own \"Colorway: <exact value>\" line (verbatim from that "
        "product's colorways/finishes list) immediately after the Name/HED line, so the "
        "correct variant can be linked - not just the base product page. Omit the "
        "Colorway line entirely if the Visual/copy doesn't call out a specific color.\n"
        "  - Never point more than one such slice's Link at the same URL, including a "
        "shared generic collection URL, even when every slice's Name is correctly "
        "distinct.\n"
        "If the inventory list above doesn't have enough distinct real products to fill "
        "every such slot for the relevant category, say so explicitly in your response "
        "rather than duplicating a placeholder name/link across the remaining slots.\n"
    )

    sale_instruction = ""
    if during_sale:
        sale_instruction = (
            "\nThis email lands during an active sale — reflect the sale name/discount "
            "naturally in the hero Eyebrow/CTA copy and in a closing kicker slice if the "
            "template has one, per Burrow's inline-sale convention (no separate sale banner "
            "slice — Burrow never prepends one, unlike CZ/STF).\n"
        )

    quick_ship_instruction = ""
    _story_notes_for_qs = f"{record.get('story', '')} {record.get('notes', '')}".lower()
    if any(kw in _story_notes_for_qs for kw in _BUR_QUICK_SHIP_KEYWORDS):
        quick_ship_instruction = (
            "\nThis is a Quick Ship email — Ready to Ship status is COLORWAY-SPECIFIC, "
            "not product-level: a product can be ready-to-ship in one fabric/finish and "
            "made-to-order (weeks-long lead time) in another. For every single-product "
            "slice, you MUST include a \"Colorway: <exact value>\" line using ONLY the "
            "ready-to-ship colorway(s) listed for that exact product in the Ready to Ship "
            "products list above — never omit the Colorway line here (unlike the general "
            "colorway rule below, which allows omitting it), and never use a colorway "
            "that isn't listed there for that product, even if it's a real colorway of "
            "that product in general. If a product in that list has no colorway to "
            "specify, omit the Colorway line for it.\n"
        )

    prompt = f"""You are briefing a Burrow designed email campaign. Do three things:

1. SELECT the best Figma template from the list below based on the email topic and use cases.
2. WRITE a 1-sentence creative direction (goal, key message, tone). Keep Burrow's voice: modern, direct, and approachable — modular furniture built for real life and small spaces, practical benefits over aspirational fluff, no jargon, no emojis.
3. GENERATE structured body copy — slice by slice for the selected template.
{sale_instruction}{quick_ship_instruction}
Slice rules:
- Output slices in the SAME ORDER as the template definition, using the EXACT slice name.
- Reproduce the "Layout:" line exactly as given for each slice (Full width / 50/50 left / 50/50 right).
- [IMAGE]: write "  Visual: [1–2 sentences for an AI image generator — composition, featured products by name, styling props, mood, lighting]" then fill each text field. For [IMAGE — fill fields only] slices (CTA buttons, copy bands, kickers), skip the Visual line.

Product rules:
- Only use product names, model variants, and finishes/colorways that appear verbatim in the real-inventory list below when a slice needs a specific product; never invent product names, variants, finishes, or URLs. When in doubt, use a general category name instead of guessing at a specific one.
- Never include a price or price range in any field — prices are not part of the brief.
{product_n_instruction}
Link rules — fill every Link: field with a URL from the lists below; do not invent URLs.
- Hero / main CTA: use the Recommended LP if provided above; otherwise pick the best match below (or https://burrow.com/ for a general sale).
- Category slices (field says "Link: [category LP]"): pick the best-matching product-category URL below.
- Single-product slices (field says "Link: [product page]" — see the product-slice rule above): do NOT use a category URL here — write the "[NEEDS PRODUCT PAGE — resolve via resolve_product_link()]" placeholder instead; a category link is only correct for genuinely generic category/kicker slices, never a named single-product slot.

CATEGORIES (general LPs):
{_bur_categories_text}

PRODUCT CATEGORIES (use for category/product slice links):
{_bur_product_categories_text}

Email topic: {record['story']}
{f"Promo: {record['promo']}" if record.get('promo') else ""}
{f"Notes: {record['notes']}" if record.get('notes') else ""}
{f"Landing page: {record['landing_page']}" if record.get('landing_page') else ""}
{inventory_section}
TEMPLATES:
{templates_detail}

Return ONLY this exact format — no extra commentary:
TEMPLATE: [key, e.g. cs_v1 or mcs_v6 or bs_v3]
DIRECTION: [1-sentence creative direction]
BODY_COPY:
Slice 1 — [EXACT slice name] [IMAGE]
  Visual: [visual description]
  Layout: [layout]
  [Field]: [value]

Slice 2 — [EXACT slice name] [IMAGE]
  ..."""
    # Re-run send: tell the model how to frame DIRECTION (no-op for normal rows).
    _resend_block = resend_prompt_instruction(record)
    if _resend_block:
        prompt += "\n" + _resend_block
    return prompt


def parse_bw_response(text: str) -> Optional[Dict[str, str]]:
    """Pure response-parser for BUR designed emails - no API call. See parse_cz_response()
    (including its note on SliceBriefValidationError - raised, not swallowed, on
    duplicate product/category content)."""
    try:
        text = text.strip().replace("\\n", "\n")
        lines = text.split("\n")

        template_key = None
        direction = None
        body_copy_lines: List[str] = []
        in_body_copy = False

        for line in lines:
            if line.startswith("TEMPLATE:"):
                val = line.replace("TEMPLATE:", "").strip().lower()
                if val in BW_FIGMA_TEMPLATES:
                    template_key = val
                else:
                    for k in BW_FIGMA_TEMPLATES:
                        if k == val or k in val.split():
                            template_key = k
                            break
            elif line.startswith("DIRECTION:"):
                direction = line.replace("DIRECTION:", "").strip()
            elif line.startswith("BODY_COPY:"):
                in_body_copy = True
            elif in_body_copy:
                body_copy_lines.append(line.strip() if line.strip() else "")

        if not template_key or template_key not in BW_FIGMA_TEMPLATES:
            return None

        # Guarantee correct per-slice Layout lines regardless of what the AI emitted.
        body_copy_lines = _stf_inject_layouts(body_copy_lines, template_key, templates=BW_FIGMA_TEMPLATES)
        body_copy_lines = _enforce_5050_pairing(body_copy_lines)

        t = BW_FIGMA_TEMPLATES[template_key]
        _warn_duplicate_products(body_copy_lines, template_slices=t["slices"])
        body_copy_lines = _resolve_product_slice_links(body_copy_lines, template_slices=t["slices"], brand="BUR")
        _warn_generic_link_for_product_slice(body_copy_lines, template_slices=t["slices"])
        node_url = t["node_id"].replace(":", "-")
        figma_url = (
            f"https://www.figma.com/design/{BW_FIGMA_FILE_KEY}"
            f"/Burrow-Email-CRM-Templates?node-id={node_url}"
        )
        body_copy_text = "\n".join(
            f"    {line}" if line else ""
            for line in body_copy_lines
        )

        return {
            "brand": "BUR",
            "template_key": template_key,
            "template_name": t["name"],
            "template_node_id": t["node_id"],
            "figma_url": figma_url,
            "direction": direction or "",
            "body_copy": body_copy_text,
        }
    except SliceBriefValidationError:
        raise
    except Exception:
        return None


def generate_bw_email_brief(record: Dict[str, str], during_sale: bool = False,
                             inventory_context: Optional[str] = None) -> Optional[Dict[str, str]]:
    """Convenience wrapper: calls the Anthropic API directly. Prefer build_bw_prompt() +
    parse_bw_response() when a live Claude Code session is doing the briefing - see
    build_cz_prompt()'s docstring for why.

    For BUR (Burrow) designed emails: select Figma template, write 1-sentence direction,
    generate body copy — slice by slice, across all 35 BW Figma templates.

    Returns dict with keys: brand ("BUR"), template_key, template_name, template_node_id,
    figma_url, direction, body_copy — or None on failure.
    """
    api_key = os.environ.get("ANTHROPIC_API_KEY")
    if not api_key:
        return None

    prompt = build_bw_prompt(record, during_sale=during_sale, inventory_context=inventory_context)

    try:
        resp = requests.post(
            "https://api.anthropic.com/v1/messages",
            headers={
                "x-api-key": api_key,
                "anthropic-version": "2023-06-01",
                "content-type": "application/json",
            },
            json={
                "model": "claude-haiku-4-5-20251001",
                "max_tokens": 3200,
                "messages": [{"role": "user", "content": prompt}],
            },
            timeout=45,
        )
        if resp.status_code != 200:
            return None

        text = resp.json()["content"][0]["text"]
        return parse_bw_response(text)
    except Exception:
        return None


def generate_id_sl_ph(record: Dict[str, str]) -> Optional[str]:
    """Generate a single SL/PH pair for Interior Define.

    Avoids generic "Your [noun] [verb]" formulas and discount-led openers.
    Leads with the specific product, collection, or story angle instead.
    """
    api_key = os.environ.get("ANTHROPIC_API_KEY")
    if not api_key:
        return None

    category = infer_category(record["story"], record["source_tab"])
    all_examples = load_brand_examples("ID")
    # Exclude auto-generated placeholder SLs: filter out generic "Your * " and "The * Off" patterns
    filtered = [
        e for e in all_examples
        if e["subject"]
        and not re.match(r"^your\b", e["subject"], re.I)
        and not re.match(r"^\d+%", e["subject"])
    ]
    cat_examples = [e for e in filtered if e["category"] == category]
    if len(cat_examples) < 5:
        cat_examples = filtered
    sample = cat_examples[:20]
    examples_text = "\n".join(
        f"SL: {e['subject']}\nPH: {e['preheader']}"
        for e in sample if e["subject"]
    )

    is_sale = bool(record.get("promo"))
    sale_guidance = ""
    if is_sale:
        sale_guidance = """
Sale send rules:
- Vary the approach: sometimes lead the SL with the product/content hook and put the discount in the PH; sometimes weave the discount into the SL naturally — mixing it up keeps the program feeling fresh
- Don't lead with a bare percentage as the very first word (e.g. "25% off sitewide ends tonight" is weak — the discount is doing all the work with no hook)
- For last-chance / final-hours sends: urgency framing is fine, but pair it with a specific product, collection name, or brand voice moment rather than just restating the percentage
"""

    prompt = f"""Generate one subject line and pre-header for this Interior Define email brief.

Email topic: {record['story']}
Category: {category}
{f"Promo: {record['promo']}" if record.get('promo') else ""}
{f"Notes: {record['notes']}" if record.get('notes') else ""}

Past Interior Define subject lines and pre-headers for tone reference:
{examples_text}

Rules:
- SL: <40 characters, sentence case, no ending punctuation
- PH: <90 characters, sentence case, with punctuation — complement the SL without repeating it
- Lead with the specific product, collection name, or story angle — not a generic aspiration
- Avoid "Your [noun] [verb]" formulas (e.g. "Your dream bedroom starts here", "Your table deserves better")
- Avoid "[Adjective] [noun] awaits/starts here/is calling" formulas — too generic
- Name the actual product, collection, or content hook when possible{sale_guidance}

Return ONLY this format:
SL: [subject line]
PH: [pre-header]"""

    for attempt in range(1, 4):
        try:
            resp = requests.post(
                "https://api.anthropic.com/v1/messages",
                headers={
                    "x-api-key": api_key,
                    "anthropic-version": "2023-06-01",
                    "content-type": "application/json",
                },
                json={
                    "model": "claude-haiku-4-5-20251001",
                    "max_tokens": 150,
                    "messages": [{"role": "user", "content": prompt}],
                },
                timeout=15,
            )
            if resp.status_code != 200:
                print(f"  ⚠ generate_id_sl_ph: HTTP {resp.status_code} on attempt {attempt}/3 for '{record.get('story', '')}'")
                if attempt < 3:
                    time.sleep(2)
                continue

            text = resp.json()["content"][0]["text"].strip()
            text = text.replace("\\n", "\n")
            if "SL:" in text and "PH:" in text:
                return text
            print(f"  ⚠ generate_id_sl_ph: unexpected response format on attempt {attempt}/3 for '{record.get('story', '')}': {text[:80]!r}")
            if attempt < 3:
                time.sleep(2)
        except Exception as e:
            print(f"  ⚠ generate_id_sl_ph: exception on attempt {attempt}/3 for '{record.get('story', '')}': {e}")
            if attempt < 3:
                time.sleep(2)

    print(f"  ✗ generate_id_sl_ph: all 3 attempts failed for '{record.get('story', '')}' — SL/PH will be missing from task")
    return None


def generate_cz_sl_ph(record: Dict[str, str]) -> Optional[str]:
    """Generate a single SL/PH pair for CZ — no options, no header."""
    api_key = os.environ.get("ANTHROPIC_API_KEY")
    if not api_key:
        return None

    category = infer_category(record["story"], record["source_tab"])
    all_examples = load_brand_examples("CZ")
    cat_examples = [e for e in all_examples if e["category"] == category]
    if len(cat_examples) < 5:
        cat_examples = all_examples
    sample = cat_examples[:15]
    examples_text = "\n".join(
        f"SL: {e['subject']}\nPH: {e['preheader']}"
        for e in sample if e["subject"]
    )

    prompt = f"""Generate one subject line and pre-header for this The Citizenry email.

Email topic: {record['story']}
Category: {category}
{f"Promo: {record['promo']}" if record.get('promo') else ""}
{f"Notes: {record['notes']}" if record.get('notes') else ""}

Past The Citizenry subject lines and pre-headers for tone reference:
{examples_text}

Rules:
- SL: <40 characters, sentence case, no ending punctuation, no emojis
- PH: <90 characters, sentence case with punctuation

Return ONLY this format:
SL: [subject line]
PH: [pre-header]"""

    for attempt in range(1, 4):
        try:
            resp = requests.post(
                "https://api.anthropic.com/v1/messages",
                headers={
                    "x-api-key": api_key,
                    "anthropic-version": "2023-06-01",
                    "content-type": "application/json",
                },
                json={
                    "model": "claude-haiku-4-5-20251001",
                    "max_tokens": 150,
                    "messages": [{"role": "user", "content": prompt}],
                },
                timeout=15,
            )
            if resp.status_code != 200:
                print(f"  ⚠ generate_cz_sl_ph: HTTP {resp.status_code} on attempt {attempt}/3 for '{record.get('story', '')}'")
                if attempt < 3:
                    time.sleep(2)
                continue

            text = resp.json()["content"][0]["text"].strip()
            text = text.replace("\\n", "\n")
            if "SL:" in text and "PH:" in text:
                return text
            print(f"  ⚠ generate_cz_sl_ph: unexpected response format on attempt {attempt}/3 for '{record.get('story', '')}': {text[:80]!r}")
            if attempt < 3:
                time.sleep(2)
        except Exception as e:
            print(f"  ⚠ generate_cz_sl_ph: exception on attempt {attempt}/3 for '{record.get('story', '')}': {e}")
            if attempt < 3:
                time.sleep(2)

    print(f"  ✗ generate_cz_sl_ph: all 3 attempts failed for '{record.get('story', '')}' — SL/PH will be missing from task")
    return None


def pick_bw_template(record: Dict[str, str]) -> Optional[Dict[str, str]]:
    """Select the best BW Figma template for a given Burrow email record.

    Returns dict with template_name, template_node_id, figma_url — or None.
    """
    api_key = os.environ.get("ANTHROPIC_API_KEY")
    if not api_key:
        return None

    catalog_lines = []
    for key, t in BW_FIGMA_TEMPLATES.items():
        catalog_lines.append(
            f"[{key}] {t['name']} — {t['description']} "
            f"Use cases: {', '.join(t['use_cases'])}."
        )
    catalog_text = "\n".join(catalog_lines)

    story = record.get("story", "")
    notes = record.get("notes", "")
    promo = record.get("promo", "")

    prompt = f"""Select the best Figma email template for this Burrow email campaign.

Email topic: {story}
{f"Notes: {notes}" if notes else ""}
{f"Promo: {promo}" if promo else ""}

Available templates:
{catalog_text}

Return ONLY the template key (e.g. mcs_v5). Nothing else."""

    try:
        resp = requests.post(
            "https://api.anthropic.com/v1/messages",
            headers={
                "x-api-key": api_key,
                "anthropic-version": "2023-06-01",
                "content-type": "application/json",
            },
            json={
                "model": "claude-haiku-4-5-20251001",
                "max_tokens": 20,
                "messages": [{"role": "user", "content": prompt}],
            },
            timeout=15,
        )
        if resp.status_code != 200:
            return None

        key = resp.json()["content"][0]["text"].strip().lower()
        if key not in BW_FIGMA_TEMPLATES:
            for k in BW_FIGMA_TEMPLATES:
                if k in key:
                    key = k
                    break
            else:
                return None

        t = BW_FIGMA_TEMPLATES[key]
        node_url = t["node_id"].replace(":", "-")
        return {
            "template_key": key,
            "template_name": t["name"],
            "template_node_id": t["node_id"],
            "figma_url": (
                f"https://www.figma.com/design/{BW_FIGMA_FILE_KEY}"
                f"/Burrow-Email-CRM-Templates?node-id={node_url}"
            ),
        }
    except Exception:
        return None


def pick_id_template(record: Dict[str, str]) -> Optional[Dict[str, str]]:
    """Select the best ID Figma template for a given Interior Define email record.

    Returns dict with template_name, template_node_id, figma_url — or None.
    """
    api_key = os.environ.get("ANTHROPIC_API_KEY")
    if not api_key:
        return None

    catalog_lines = []
    for key, t in ID_FIGMA_TEMPLATES.items():
        catalog_lines.append(
            f"[{key}] {t['name']} — {t['description']} "
            f"Use cases: {', '.join(t['use_cases'])}."
        )
    catalog_text = "\n".join(catalog_lines)

    story = record.get("story", "")
    notes = record.get("notes", "")
    promo = record.get("promo", "")

    prompt = f"""Select the best Figma email template for this Interior Define email campaign.

Email topic: {story}
{f"Notes: {notes}" if notes else ""}
{f"Promo: {promo}" if promo else ""}

Available templates:
{catalog_text}

Return ONLY the template key (e.g. C or instock). Nothing else."""

    try:
        resp = requests.post(
            "https://api.anthropic.com/v1/messages",
            headers={
                "x-api-key": api_key,
                "anthropic-version": "2023-06-01",
                "content-type": "application/json",
            },
            json={
                "model": "claude-haiku-4-5-20251001",
                "max_tokens": 20,
                "messages": [{"role": "user", "content": prompt}],
            },
            timeout=15,
        )
        if resp.status_code != 200:
            return None

        key = resp.json()["content"][0]["text"].strip()
        if key not in ID_FIGMA_TEMPLATES:
            key_lower = key.lower()
            for k in ID_FIGMA_TEMPLATES:
                if k.lower() == key_lower or k.lower() in key_lower:
                    key = k
                    break
            else:
                return None

        t = ID_FIGMA_TEMPLATES[key]
        node_url = t["node_id"].replace(":", "-")
        return {
            "template_key": key,
            "template_name": t["name"],
            "template_node_id": t["node_id"],
            "figma_url": (
                f"https://www.figma.com/design/{ID_FIGMA_FILE_KEY}"
                f"/Lifecycle--Email-Template-Library?node-id={node_url}"
            ),
        }
    except Exception:
        return None



def _extract_ti_discount(promo: str) -> str:
    """Extract discount % from a promo string like 'Memorial Day Sale — 25% off sitewide'.
    Returns e.g. '25%', or empty string if not found.
    """
    m = re.search(r'(\d+)%', promo or "")
    return f"{m.group(1)}%" if m else ""


def pick_ti_kicker(template_key: str, during_sale: bool) -> Optional[str]:
    """Return a TI kicker key for the given template + sale context, or None.

    Kickers are used sparingly for TI. Long editorial templates never get kickers.
    """
    if template_key == "potm":
        return "bndl_a" if during_sale else "swatch_a"
    if template_key == "swatch_story":
        return None
    if template_key == "swatch_party":
        return "link_farm_a" if during_sale else None
    if template_key == "product_multi":
        return "bndl_b" if during_sale else None
    if template_key == "product_single":
        return "link_farm_a" if during_sale else "swatch_b"
    if template_key == "seating":
        return "bndl_a" if during_sale else None
    if template_key == "color_edit":
        return "link_farm_b" if during_sale else "swatch_a"
    # destination and dining — long editorial, never a kicker
    return None


_ti_slice_line_re = re.compile(r"^Slice\s+\d+\s*[—–-]\s*(.+?)\s*·\s*(.*)$")


def _parse_ti_slice_fields(fields_str: str) -> Dict[str, str]:
    """Split a TI slice's ' / '-separated field string into a {label: value} dict.

    TI's body copy is one line per slice ("Slice N — [name] · [field]: [value] /
    [field]: [value] / ..."), not the multi-line block format CZ/STF/BW share, so it
    needs its own line parser. Segments with no colon (e.g. "Lifestyle image", a bare
    layout note) aren't fields — skip them. Splitting on " / " (space-slash-space) is
    safe even though some field labels contain an internal slash with no surrounding
    spaces (e.g. "Color/variant:") — that slash never has spaces around it.
    """
    fields: Dict[str, str] = {}
    for segment in fields_str.split(" / "):
        segment = segment.strip()
        if ":" not in segment:
            continue
        label, value = segment.split(":", 1)
        fields[label.strip().lower()] = value.strip()
    return fields


def _warn_duplicate_products_ti(body_copy_lines: List[str], slices_text: str) -> None:
    """TI counterpart to _warn_duplicate_products() - raises SliceBriefValidationError,
    see that function's docstring for the bug class this catches (two repeatable
    product/category slots sharing the same Name or Link instead of being distinct).

    TI needs its own version because its body copy is one line per slice, not a
    multi-line block, so _stf_slice_header_re can't parse it. Still schema-driven like
    the CZ/STF/BW version: a slice counts as "single-item" when the TEMPLATE's own
    catalog text (`slices_text` from TI_FIGMA_TEMPLATES) declares a Link field whose
    placeholder mentions "product" or "category" (e.g. "[product LP]", "[product or
    collection LP]", "[category LP]") - this catches templates like product_multi
    (Product/Collection 1-3), seating (Product 1-3), and color_edit (Category 1-4)
    without hardcoding slice names.
    """
    schema: Dict[str, bool] = {}
    for line in slices_text.split("\n"):
        m = _ti_slice_line_re.match(line.strip())
        if not m:
            continue
        slice_name, fields_str = m.group(1).strip().lower(), m.group(2)
        link_val = _parse_ti_slice_fields(fields_str).get("link", "")
        schema[slice_name] = "product" in link_val.lower() or "category" in link_val.lower()

    items = []
    for line in body_copy_lines:
        m = _ti_slice_line_re.match(line.strip())
        if not m:
            continue
        slice_name, fields_str = m.group(1).strip(), m.group(2)
        if not schema.get(slice_name.lower()):
            continue
        fields = _parse_ti_slice_fields(fields_str)
        items.append((f"Slice — {slice_name}", fields.get("name"), fields.get("link")))

    names_seen: Dict[str, str] = {}
    links_seen: Dict[str, str] = {}
    violations: List[str] = []
    for header, name, link in items:
        if name:
            if name in names_seen:
                msg = (
                    f"'{names_seen[name]}' and '{header}' both have Name '{name}' - "
                    f"each slot should be a distinct product/category."
                )
                print(f"[ERROR] _warn_duplicate_products_ti: {msg}")
                violations.append(msg)
            else:
                names_seen[name] = header
        if link:
            if link in links_seen:
                msg = (
                    f"'{links_seen[link]}' and '{header}' both Link to '{link}' - each "
                    f"slot should link to its own page, not a shared/generic link."
                )
                print(f"[ERROR] _warn_duplicate_products_ti: {msg}")
                violations.append(msg)
            else:
                links_seen[link] = header

    if violations:
        raise SliceBriefValidationError(
            "Duplicate product/category content in TI slice-by-slice brief:\n"
            + "\n".join(f"  - {v}" for v in violations)
        )


def build_ti_prompt(record: Dict[str, str], during_sale: bool = False) -> str:
    """Pure prompt-builder for TI designed emails - no API call, no API key required.

    Prefer this + parse_ti_response() over generate_ti_email_brief() when a live Claude
    Code session is doing the briefing - see build_cz_prompt()'s docstring for why.
    """
    # Load known TI URLs from data file
    _ti_links_path = os.path.join(os.path.dirname(__file__), "..", "data", "ti_links.yaml")
    _ti_categories_text = ""
    _ti_destinations_text = ""
    _ti_edits_text = ""
    _ti_prints_text = ""
    try:
        with open(_ti_links_path) as _f:
            _ti_links = yaml.safe_load(_f)
        _ti_categories_text = "\n".join(
            f"  {c['url']} — {c['label']}"
            for c in _ti_links.get("categories", [])
        )
        _ti_destinations_text = "\n".join(
            f"  {c['url']} — {c['label']}"
            for c in _ti_links.get("destinations", [])
        )
        _ti_edits_text = "\n".join(
            f"  {c['url']} — {c['label']}"
            for c in _ti_links.get("edits", [])
        )
        _ti_prints_text = "\n".join(
            f"  {c['url']} — {c['label']}"
            for c in _ti_links.get("prints", [])
        )
        _ti_product_categories_text = "\n".join(
            f"  {c['url']} — {c['label']}"
            for c in _ti_links.get("product_categories", [])
        )
    except Exception:
        _ti_product_categories_text = ""

    catalog_text = "\n\n".join(
        f"[{key}] {t['name']} — {t['description']}\n"
        f"Use cases: {', '.join(t['use_cases'])}\n"
        f"Slices:\n{t['slices_text']}"
        for key, t in TI_FIGMA_TEMPLATES.items()
    )

    story = record.get("story", "")
    notes = record.get("notes", "")
    promo = record.get("promo", "")
    lp = record.get("landing_page", "")

    sale_instruction = ""
    if during_sale and promo:
        sale_instruction = (
            f"\nThis email is sent during an active sale ({promo}). "
            "Prepend a sale banner slice (Slice 1 — Sale banner · Link: https://www.theinside.com/) "
            "and shift all other slice numbers up by 1."
        )

    links_section = f"""
LINK RULES — only use URLs from these lists; do not invent URLs.
- Hero and main CTA: use the LP provided if given; otherwise pick the best match from the lists below
- Destination emails (destination): pick the matching destination URL
- Print/swatch emails (potm, swatch_story, swatch_party, color_edit): use the matching print URL or https://www.theinside.com/fabric-swatches
- Product category links (beds, chairs, curtains, etc.): pick from PRODUCT CATEGORIES
- Edit-themed emails: pick the best match from EDITS
- General landing pages: pick from CATEGORIES

PRODUCT CATEGORIES (use for individual category links in product/color/seating templates):
{_ti_product_categories_text}

CATEGORIES (general LPs):
{_ti_categories_text}

DESTINATIONS:
{_ti_destinations_text}

EDITS:
{_ti_edits_text}

PRINTS:
{_ti_prints_text}"""

    prompt = f"""You are briefing a The Inside email campaign. Do three things:

1. SELECT the best Figma template from the list below based on the email topic.
2. WRITE a 1-sentence creative direction (goal, key message, tone). Keep The Inside's voice: editorial, confident, design-forward.
3. GENERATE structured body copy — slice by slice for the selected template. Fill in every bracketed field using the link lists provided.
{sale_instruction}

Email topic: {story}
{f"Notes: {notes}" if notes else ""}
{f"Promo: {promo}" if promo else ""}
{f"Landing page: {lp}" if lp else ""}
{links_section}

TEMPLATES:
{catalog_text}

Return ONLY this exact format — no extra commentary:
TEMPLATE: [key, e.g. potm or swatch_story or color_edit]
DIRECTION: [1-sentence creative direction]
BODY_COPY:
Slice 1 — [name] · [fields]
Slice 2 — [name] · [fields]
..."""
    # Re-run send: tell the model how to frame DIRECTION (no-op for normal rows).
    _resend_block = resend_prompt_instruction(record)
    if _resend_block:
        prompt += "\n" + _resend_block
    return prompt


def parse_ti_response(text: str, promo: str = "", during_sale: bool = False) -> Optional[Dict[str, str]]:
    """Pure response-parser for TI designed emails - no API call. See parse_cz_response()
    (including its note on SliceBriefValidationError - raised, not swallowed, on
    duplicate product/category content or a slice count that doesn't match the
    template).

    promo/during_sale must match what was passed to build_ti_prompt() for the same
    record - they drive kicker selection the same way generate_ti_email_brief() did.
    """
    try:
        text = text.strip().replace("\\n", "\n")
        lines = text.split("\n")

        template_key = None
        direction = None
        body_copy_lines = []
        in_body_copy = False

        for line in lines:
            if line.startswith("TEMPLATE:"):
                val = line.replace("TEMPLATE:", "").strip().lower()
                if val in TI_FIGMA_TEMPLATES:
                    template_key = val
                else:
                    for k in TI_FIGMA_TEMPLATES:
                        if k in val:
                            template_key = k
                            break
            elif line.startswith("DIRECTION:"):
                direction = line.replace("DIRECTION:", "").strip()
            elif line.startswith("BODY_COPY:"):
                in_body_copy = True
            elif in_body_copy:
                body_copy_lines.append(line.strip() if line.strip() else "")

        if not template_key:
            return None

        t = TI_FIGMA_TEMPLATES[template_key]
        _warn_duplicate_products_ti(body_copy_lines, t.get("slices_text", ""))
        # Sanity check only - the "Slices to deliver" line itself is computed downstream
        # in build_html_notes() by counting actual "Slice N —" lines (already correct,
        # unlike CZ/STF/BUR's former pre-computed count - see _warn_slice_count_mismatch()
        # docstring). This just flags drift from the template's own base slice count, plus
        # the sale banner the AI is instructed to prepend/renumber for itself when
        # during_sale (TI has no code-level banner injection the way CZ/STF/HAV do).
        _ti_base_slice_count = sum(
            1 for ln in t.get("slices_text", "").split("\n") if _ti_slice_line_re.match(ln.strip())
        )
        _warn_slice_count_mismatch(
            body_copy_lines, _ti_base_slice_count + (1 if during_sale else 0), f"TI {t['name']}"
        )
        node_url = t["node_id"].replace(":", "-")
        figma_url = (
            f"https://www.figma.com/design/{TI_FIGMA_FILE_KEY}"
            f"/TI-Templates?node-id={node_url}"
        )

        body_copy_text = "\n".join(
            f"    {line}" if line else ""
            for line in body_copy_lines
        )

        # Kicker selection
        kicker_key = pick_ti_kicker(template_key, during_sale)
        kicker_info: Dict[str, Optional[str]] = {
            "kicker_key": None,
            "kicker_name": None,
            "kicker_node_id": None,
            "kicker_figma_url": None,
            "kicker_slices_text": None,
        }
        if kicker_key and kicker_key in TI_KICKERS:
            k = TI_KICKERS[kicker_key]
            pct = _extract_ti_discount(promo)
            sale_parts = (promo or "").split(" — ")
            sale_name_upper = sale_parts[0].strip().upper() if sale_parts else ""
            kicker_slices = k["slices_text"].format(
                pct=pct or "[% off]",
                sale_name_upper=sale_name_upper or "[SALE NAME]",
            )
            kicker_node_url = k["node_id"].replace(":", "-")
            kicker_info = {
                "kicker_key": kicker_key,
                "kicker_name": k["name"],
                "kicker_node_id": k["node_id"],
                "kicker_figma_url": (
                    f"https://www.figma.com/design/{TI_KICKER_FILE_KEY}"
                    f"/TI-Templates?node-id={kicker_node_url}"
                ),
                "kicker_slices_text": kicker_slices,
            }

        return {
            "template_key": template_key,
            "template_name": t["name"],
            "template_node_id": t["node_id"],
            "figma_url": figma_url,
            "direction": direction or "",
            "body_copy": body_copy_text,
            **kicker_info,
        }
    except SliceBriefValidationError:
        raise
    except Exception:
        return None


def generate_ti_email_brief(record: Dict[str, str], during_sale: bool = False) -> Optional[Dict[str, str]]:
    """Convenience wrapper: calls the Anthropic API directly. Prefer build_ti_prompt() +
    parse_ti_response() when a live Claude Code session is doing the briefing - see
    build_cz_prompt()'s docstring for why.

    For TI designed emails: select Figma template, write 1-sentence direction, generate
    body copy. Returns dict with keys: template_key, template_name, template_node_id,
    figma_url, direction, body_copy or None on failure.
    """
    api_key = os.environ.get("ANTHROPIC_API_KEY")
    if not api_key:
        return None

    prompt = build_ti_prompt(record, during_sale=during_sale)

    try:
        resp = requests.post(
            "https://api.anthropic.com/v1/messages",
            headers={
                "x-api-key": api_key,
                "anthropic-version": "2023-06-01",
                "content-type": "application/json",
            },
            json={
                "model": "claude-haiku-4-5-20251001",
                "max_tokens": 1800,
                "messages": [{"role": "user", "content": prompt}],
            },
            timeout=45,
        )
        if resp.status_code != 200:
            return None

        text = resp.json()["content"][0]["text"]
        return parse_ti_response(text, promo=record.get("promo", ""), during_sale=during_sale)
    except Exception:
        return None


def pick_trade_template(record: Dict[str, str]) -> Optional[Dict[str, str]]:
    """Select the best Trade Figma template for a given trade email record.

    Uses record["brand"] (the sub-brand: HAV, ID, CZ, TI, STF) to look up
    the right brand's trade template section, then calls Haiku to pick within it.
    Returns dict with template_name, template_node_id, figma_url — or None.
    """
    api_key = os.environ.get("ANTHROPIC_API_KEY")
    if not api_key:
        return None

    sub_brand = record.get("brand", "")
    brand_templates = TRADE_FIGMA_TEMPLATES.get(sub_brand)
    if not brand_templates:
        return None

    catalog_lines = []
    for key, t in brand_templates.items():
        catalog_lines.append(
            f"[{key}] {t['name']} — {t['description']} "
            f"Use cases: {', '.join(t['use_cases'])}."
        )
    catalog_text = "\n".join(catalog_lines)

    story = record.get("story", "")
    notes = record.get("notes", "")

    prompt = f"""Select the best Figma email template for this {sub_brand} Trade email campaign.

Email topic: {story}
{f"Notes: {notes}" if notes else ""}

Available templates:
{catalog_text}

Return ONLY the template letter (e.g. A). Nothing else."""

    try:
        resp = requests.post(
            "https://api.anthropic.com/v1/messages",
            headers={
                "x-api-key": api_key,
                "anthropic-version": "2023-06-01",
                "content-type": "application/json",
            },
            json={
                "model": "claude-haiku-4-5-20251001",
                "max_tokens": 5,
                "messages": [{"role": "user", "content": prompt}],
            },
            timeout=15,
        )
        if resp.status_code != 200:
            return None

        key = resp.json()["content"][0]["text"].strip().upper()
        if key not in brand_templates:
            return None

        t = brand_templates[key]
        node_url = t["node_id"].replace(":", "-")
        return {
            "template_key": key,
            "template_name": f"{sub_brand} Trade — {t['name']}",
            "template_node_id": t["node_id"],
            "figma_url": (
                f"https://www.figma.com/design/{TRADE_FIGMA_FILE_KEY}"
                f"/HAVENLY-BRANDS-TRADE?node-id={node_url}"
            ),
        }
    except Exception:
        return None


def _describe_hav_template(key: str, t: Dict) -> str:
    """Render one HAV template's fixed Hero slice + repeatable-section instructions
    into the prompt catalog text for generate_hav_email_brief(). HAV templates vary in
    slice count per send (unlike CZ/STF/BUR's fixed-count templates), so this spells out
    a repeat rule instead of a literal slice list."""
    hero_fields = ", ".join(t["slices"][0]["fields"])
    lines = [
        f"[{key}] {t['name']} — {t['description']} Use cases: {', '.join(t['use_cases'])}.",
        f"  Slice 1 — Hero (Full width): {hero_fields}",
    ]
    rep = t.get("repeatable_section")
    if not rep:
        lines.append("  This template is always exactly 1 slice — do not add additional slices.")
    elif rep.get("is_pair"):
        lines.append(
            "  Then, for EACH additional round/category the content calls for (typically 2-3 total):\n"
            f"    Write a group label line: \"Section N — [category]\" (not a numbered slice itself)\n"
            f"    Slice — Option A (50/50 left): {', '.join(rep['option_a_fields'])}\n"
            f"    Slice — Option B (50/50 right): {', '.join(rep['option_b_fields'])}\n"
            f"    Both options in every section share Link: {rep['fixed_link']}"
        )
    else:
        lines.append(
            f"  Then repeat additional Slice N — Section N (Full width) blocks for however many "
            f"sections the content calls for (typically 2-4): {', '.join(rep['fields'])}"
        )
    return "\n".join(lines)


def build_hav_prompt(record: Dict[str, str], during_sale: bool = False) -> str:
    """Pure prompt-builder for HAV designed emails - no API call, no API key required.

    Prefer this + parse_hav_response() over generate_hav_email_brief() when a live
    Claude Code session is doing the briefing - see build_cz_prompt()'s docstring for why.
    """
    story = record.get("story", "")
    notes = record.get("notes", "")
    promo = record.get("promo", "")
    audience = _hav_infer_audience(story)

    templates_detail = "\n\n".join(
        _describe_hav_template(key, t) for key, t in HAV_FIGMA_TEMPLATES.items()
    )

    sale_instruction = ""
    if during_sale:
        sale_instruction = (
            "\nThis email lands during an active sale — a Sale Banner slice will be "
            "prepended automatically ahead of your Hero slice, so you do not need to force "
            "the sale terms into the Hero HED/DEK/CTA copy (a light natural nod is fine, but "
            "not required). Just write the Hero/section content on its own merits.\n"
        )

    prompt = f"""You are briefing a Havenly designed email campaign. Do three things:

1. SELECT the best Figma template from the list below based on the email topic and use cases.
2. WRITE a 1-sentence creative direction (goal, key message, tone). Keep Havenly's voice: warm, encouraging, design-forward — approachable expertise, not salesy. No emojis unless the send calls for it strategically.
3. GENERATE structured body copy — slice by slice for the selected template, per its repeat rule below.
{sale_instruction}
Slice rules:
- Output the Hero slice first, using the EXACT field list given for the selected template.
- For templates with a repeatable section, add as many additional slices as the content genuinely calls for — do not pad to hit a number.
- Do not write a Visual/Link field unless the template's instructions explicitly ask for one.

Email topic: {story}
Audience: {audience or "general"}
{f"Notes: {notes}" if notes else ""}
{f"Promo: {promo}" if promo else ""}

TEMPLATES:
{templates_detail}

Return ONLY this exact format — no extra commentary:
TEMPLATE: [key, e.g. theme_01]
DIRECTION: [1-sentence creative direction]
BODY_COPY:
Slice 1 — Hero [IMAGE]
  HED: [value]
  DEK: [value]
  CTA: [value]

Slice 2 — Section 1 [IMAGE]
  ..."""
    # Re-run send: tell the model how to frame DIRECTION (no-op for normal rows).
    _resend_block = resend_prompt_instruction(record)
    if _resend_block:
        prompt += "\n" + _resend_block
    return prompt


def parse_hav_response(text: str, audience: Optional[str] = None) -> Optional[Dict[str, str]]:
    """Pure response-parser for HAV designed emails - no API call. See parse_cz_response().

    audience must match what build_hav_prompt() was given for the same record - it
    drives the "ai" template's mandatory kicker pick the same way
    generate_hav_email_brief() did.
    """
    try:
        text = text.strip().replace("\\n", "\n")
        lines = text.split("\n")

        template_key = None
        direction = None
        body_copy_lines: List[str] = []
        in_body_copy = False

        for line in lines:
            if line.startswith("TEMPLATE:"):
                val = line.replace("TEMPLATE:", "").strip().lower()
                if val in HAV_FIGMA_TEMPLATES:
                    template_key = val
                else:
                    for k in HAV_FIGMA_TEMPLATES:
                        if k in val:
                            template_key = k
                            break
            elif line.startswith("DIRECTION:"):
                direction = line.replace("DIRECTION:", "").strip()
            elif line.startswith("BODY_COPY:"):
                in_body_copy = True
            elif in_body_copy:
                body_copy_lines.append(line.strip() if line.strip() else "")

        if not template_key or template_key not in HAV_FIGMA_TEMPLATES:
            return None

        t = HAV_FIGMA_TEMPLATES[template_key]
        node_url = t["node_id"].replace(":", "-")
        figma_url = (
            f"https://www.figma.com/design/{HAV_FIGMA_FILE_KEY}"
            f"/Havenly-Lifecycle-Templates?node-id={node_url}&m=dev"
        )
        body_copy_text = "\n".join(
            f"    {line}" if line else ""
            for line in body_copy_lines
        )

        result: Dict[str, str] = {
            "brand": "HAV",
            "template_key": template_key,
            "template_name": t["name"],
            "template_node_id": t["node_id"],
            "figma_url": figma_url,
            "direction": direction or "",
            "body_copy": body_copy_text,
        }

        # AI template is hero-only — always attach a kicker (reference only, no generated copy)
        if template_key == "ai":
            k_key = "dps_kicker" if audience == "DPS" else "5_stars"
            k = HAV_FIGMA_KICKERS[k_key]
            kicker_node_url = k["node_id"].replace(":", "-")
            result["kicker_name"] = k["name"]
            result["kicker_node_id"] = k["node_id"]
            result["kicker_figma_url"] = (
                f"https://www.figma.com/design/{HAV_FIGMA_FILE_KEY}"
                f"/Havenly-Lifecycle-Templates?node-id={kicker_node_url}&m=dev"
            )

        return result
    except Exception:
        return None


def generate_hav_email_brief(record: Dict[str, str], during_sale: bool = False) -> Optional[Dict[str, str]]:
    """Convenience wrapper: calls the Anthropic API directly. Prefer build_hav_prompt() +
    parse_hav_response() when a live Claude Code session is doing the briefing - see
    build_cz_prompt()'s docstring for why.

    For HAV designed emails: select Figma template, write 1-sentence direction,
    generate slice-by-slice body copy — same copy-first convention as CZ/STF/TI/BUR.

    HAV sections all point at the email's single top-level LP (record["landing_page"]) —
    no per-slice Link field, except This or That, which always links to the fixed
    interior-design-ideas LP per the standing This or That rule.

    Returns dict with keys: brand ("HAV"), template_key, template_name, template_node_id,
    figma_url, direction, body_copy, and — for the "ai" template only, which always pairs
    with a kicker — kicker_name, kicker_node_id, kicker_figma_url. Kicker copy itself is
    template chrome (static HED/CTA, or a real testimonial a human sources) and is never
    AI-generated, so no kicker body copy is produced here — only reference the module.
    Returns None on failure (missing API key, bad response, etc.).
    """
    api_key = os.environ.get("ANTHROPIC_API_KEY")
    if not api_key:
        return None

    prompt = build_hav_prompt(record, during_sale=during_sale)
    audience = _hav_infer_audience(record.get("story", ""))

    try:
        resp = requests.post(
            "https://api.anthropic.com/v1/messages",
            headers={
                "x-api-key": api_key,
                "anthropic-version": "2023-06-01",
                "content-type": "application/json",
            },
            json={
                "model": "claude-haiku-4-5-20251001",
                "max_tokens": 1800,
                "messages": [{"role": "user", "content": prompt}],
            },
            timeout=45,
        )
        if resp.status_code != 200:
            return None

        text = resp.json()["content"][0]["text"]
        return parse_hav_response(text, audience=audience)
    except Exception:
        return None


def _hav_infer_audience(story: str) -> str:
    """Return 'DPS', 'MP', 'both', or '' from a HAV story/task name prefix."""
    s = story or ""
    if s.startswith("DPS and MP:") or s.startswith("DPS and MP "):
        return "both"
    if s.startswith("DPS:") or s.startswith("DPS "):
        return "DPS"
    if s.startswith("MP:") or s.startswith("MP "):
        return "MP"
    return ""


# Per-audience sale banner destinations for HAV designed emails (confirmed 2026-07-30).
# DPS → design-service packages section; MP → marketplace sale collection.
_HAV_SALE_BANNER_LINKS = {
    "DPS": "https://havenly.com/#packages-section",
    "MP": "https://havenly.com/shop/collection/sale",
}


def _hav_sale_banner_body_lines(story: str, sale_label: str) -> List[str]:
    """Return the body-copy lines for the Sale Banner slice — always exactly one
    slice position (Slice 1), never two stacked slices. For a combined "DPS and MP"
    send there is no single audience for the whole list, so the banner is
    audience-conditional: both destinations are listed as alternate versions of that
    same Slice 1 (Braze/Liquid renders whichever matches the recipient's segment),
    not two additional banner slices appended one after another.
    """
    audience = _hav_infer_audience(story)
    if audience == "both":
        return [
            f"DPS: {sale_label} — Link: {_HAV_SALE_BANNER_LINKS['DPS']}",
            f"MP: {sale_label} — Link: {_HAV_SALE_BANNER_LINKS['MP']}",
        ]
    link = _HAV_SALE_BANNER_LINKS.get(audience, "https://havenly.com/")
    return [sale_label, f"Link: {link}"]


def _is_plain_text_story(story: str) -> bool:
    """Return True if the story name indicates a plain-text email."""
    s = (story or "").lower()
    return bool(re.search(r"\bpt\b", s) or "plain text" in s or "plain-text" in s or "plaintext" in s)


# ---------------------------------------------------------------------------
# PT (plain-text) body copy drafting — copy-first brands (HAV, CZ, STF, BUR, TI)
# ---------------------------------------------------------------------------
# Mirrors the build_xxx_prompt()/parse_xxx_response() pattern already used for
# designed-email slice copy (build_bw_prompt, build_cz_prompt, etc.), but for
# the full PT email body instead of slice-by-slice fields. Pure prompt-builder
# + pure parser, no API call — the acting Claude Code session generates the
# completion itself (following CLAUDE.md's "Preferred method — self-generate"),
# invoking that brand's copywriter skill first per the Skills section, then
# parses its own output with parse_pt_response().

_brand_config_cache: Optional[Dict] = None


def _load_brand_config() -> Dict:
    global _brand_config_cache
    if _brand_config_cache is None:
        _path = os.path.join(os.path.dirname(__file__), "..", "data", "brand_config.yaml")
        try:
            with open(_path) as f:
                _brand_config_cache = yaml.safe_load(f) or {}
        except Exception:
            _brand_config_cache = {}
    return _brand_config_cache


def _pt_signoff(brand: str) -> Dict[str, str]:
    """Return the brand's PT sign-off from data/brand_config.yaml's pt_email_styles.

    Keys: ``closing`` (the phrase), ``name`` (the name block, newline-joined),
    and ``name_lines`` (the same as a list).

    ID splits its name across two lines — ``default_signoff_name: "Lisa"`` plus
    ``default_signoff_name_extra: "The Interior Define Team"``.  Reading only
    the first key left the prompt asking for a two-line close, so AI-drafted ID
    briefs ended at "Lisa" while the Braze render (which rebuilds the block from
    the same config) added the team line — the brief Lacy reviewed was a line
    shorter than the email that actually sent.
    """
    styles = _load_brand_config().get("pt_email_styles", {}) or {}
    cfg = styles.get(brand, {}) or {}
    name_lines = [
        line
        for line in (
            cfg.get("default_signoff_name", ""),
            cfg.get("default_signoff_name_extra", ""),
        )
        if line
    ]
    return {
        "closing": cfg.get("default_signoff", "Best,"),
        "name": "\n".join(name_lines),
        "name_lines": name_lines,
    }


def _pt_signoff_block(signoff: Dict[str, str], indent: str = "") -> str:
    """Render a sign-off as indented lines: the phrase, then each name line."""
    lines = [signoff["closing"], *signoff["name_lines"]]
    return "\n".join(f"{indent}{line}" for line in lines if line)


# (filename, [top-level keys to include]) per brand — same data files the
# designed-email prompt builders already use for link sourcing.
_PT_LINKS_FILES = {
    "BUR": ("bur_links.yaml", ["categories", "product_categories"]),
    "CZ": ("cz_links.yaml", ["collections"]),
    "STF": ("stf_links.yaml", ["categories", "product_categories"]),
    "TI": ("ti_links.yaml", ["categories", "product_categories"]),
}


def _load_pt_link_catalog(brand: str) -> str:
    """Return a newline-delimited 'URL — label' catalog for the brand, or '' (e.g. HAV)."""
    cfg = _PT_LINKS_FILES.get(brand)
    if not cfg:
        return ""
    filename, keys = cfg
    path = os.path.join(os.path.dirname(__file__), "..", "data", filename)
    try:
        with open(path) as f:
            data = yaml.safe_load(f) or {}
    except Exception:
        return ""
    lines = []
    for key in keys:
        for item in data.get(key, []):
            if isinstance(item, dict) and item.get("url"):
                lines.append(f"  {item['url']} — {item.get('label', '')}")
    return "\n".join(lines)


# Platform-specific first-name personalization tags.  TI and TE are on
# Klaviyo, which uses Django-style templating and does NOT render Braze's
# "${attr}" Liquid form — it ships the raw tag as visible text.  Confirmed on
# the TI "Labor Day Event Last Chance PT" brief (task 1217247702094792), which
# was drafted with the Braze tag because this prompt used to hardcode it for
# every brand.  create_klaviyo_email.convert_braze_liquid() also fixes this at
# build time; emitting the right tag here keeps the Asana brief itself correct,
# which is what the copywriter reviews.
_PT_KLAVIYO_BRANDS = {"TI", "TE"}
_BRAZE_FIRST_NAME_TAG = "Hi {{${first_name} | default: 'there'}},"
_KLAVIYO_FIRST_NAME_TAG = "Hi {{ first_name|default:'there' }},"


def pt_greeting_tag(brand: str) -> str:
    """Return the first-name greeting line for *brand*'s sending platform."""
    if (brand or "").upper() in _PT_KLAVIYO_BRANDS:
        return _KLAVIYO_FIRST_NAME_TAG
    return _BRAZE_FIRST_NAME_TAG


_PT_COPYWRITER_SKILLS = {
    "HAV": "anthropic-skills:havenly-copywriter",
    "CZ": "anthropic-skills:citizenry-brand-voice",
    "ID": "anthropic-skills:interior-define-copywriter",
    "BUR": "anthropic-skills:burrow-copywriter",
    "STF": "anthropic-skills:st-frank-copywriter",
    "TI": "anthropic-skills:the-inside-copywriter",
}


def build_pt_prompt(brand: str, record: Dict[str, str], during_sale: bool = False) -> str:
    """Pure prompt-builder for a PT (plain-text) email body — no API call, no API key
    required. Covers the 5 copy-first brands (HAV, CZ, STF, BUR, TI). Companion to
    build_bw_prompt()/build_cz_prompt()/etc., but drafts the full PT body instead of
    designed-email slice copy.

    IMPORTANT: before generating the completion for this prompt, invoke that brand's
    copywriter skill per CLAUDE.md's Skills section (_PT_COPYWRITER_SKILLS[brand]) —
    this prompt only encodes structure/mechanics (greeting, links, signoff), not voice.
    """
    brand_name = BRAND_FULL_NAMES.get(brand, brand)
    signoff = _pt_signoff(brand)
    link_catalog = _load_pt_link_catalog(brand)
    lp = record.get("landing_page", "")

    link_section = ""
    if link_catalog:
        link_section = f"\nLINK CATALOG (pick the best match; never invent a URL):\n{link_catalog}\n"

    lp_line = f"\nRecommended landing page: {lp}\n" if lp else ""

    sale_instruction = ""
    if during_sale:
        sale_instruction = (
            "\nThis email sends during an active sale — the Promo details below should show "
            "up naturally in the copy (e.g. discount, sale name), but do NOT write a legal "
            "disclaimer sentence yourself; the build script appends that automatically.\n"
        )

    greeting_tag = pt_greeting_tag(brand)
    signoff_rule_block = _pt_signoff_block(signoff, indent="  ")
    signoff_format_block = _pt_signoff_block(signoff)
    skill_name = _PT_COPYWRITER_SKILLS.get(brand, "")
    skill_reminder = (
        f"\nBefore writing, make sure you've loaded the `{skill_name}` skill for {brand_name}'s "
        "voice and copy standards — this prompt only covers structure, not tone.\n"
        if skill_name else ""
    )

    prompt = f"""You are drafting a {brand_name} plain-text (PT) marketing email. Do three things:

1. WRITE a 1-sentence creative direction (goal, key message, tone).
2. WRITE one subject line — <40 characters, sentence case, no ending punctuation.
3. WRITE the full PT email body, following these rules exactly:

- Greeting: the very first line must be this personalization tag verbatim:
  {greeting_tag}
- Body: 2-4 short paragraphs in {brand_name}'s voice. Plain, conversational, no jargon.
  Use contractions ("it's," "here's," "you're," "don't," "tonight's") — this is how
  {brand_name} actually writes PT copy; spelled-out forms ("it is," "do not," "you are")
  read stiff and formal and should only appear where a contraction would sound wrong.
  Never mention the offer's URL or write it inline in a sentence — the destination is
  handled entirely by the CTA line below.
- CTA: after the last paragraph, on its own line, write a short call-to-action — 2-4 words,
  ending in an arrow, e.g. "Shop the Sale →" — using this priority order to decide where it
  points: (a) an explicit link already implied by the topic/notes below, (b) the recommended
  landing page, (c) the best match from the link catalog. Then on the line directly below it,
  write the URL alone. Do not put the URL anywhere else in the body.
- Closing: end with the brand's standard sign-off, each on its own line:
{signoff_rule_block}
{sale_instruction}{skill_reminder}
Email topic: {record.get('story', '')}
{f"Promo: {record.get('promo', '')}" if record.get('promo') else ""}
{f"Notes: {record.get('notes', '')}" if record.get('notes') else ""}
{lp_line}{link_section}
Return ONLY this exact format — no extra commentary:
DIRECTION: [1-sentence creative direction]
SL: [subject line]
BODY:
{greeting_tag}

[paragraph]

CTA: [Shop the Sale →]
CTA_URL: [URL]

{signoff_format_block}"""
    # Re-run send: tell the model how to frame DIRECTION (no-op for normal rows).
    _resend_block = resend_prompt_instruction(record)
    if _resend_block:
        prompt += "\n" + _resend_block
    return prompt


# Sentinel substituted for the CTA/CTA_URL pair inside a parsed PT body — lets
# callers reassemble the body with either a real <a href> anchor (html_notes)
# or a plain "text URL" fallback (plain-text notes), without re-parsing.
_PT_CTA_SENTINEL = "\x00CTA\x00"

_PT_CTA_LINE_RE = re.compile(r"^CTA:\s*(.+?)\s*$", re.IGNORECASE)
_PT_CTA_URL_LINE_RE = re.compile(r"^CTA_URL:\s*(.+?)\s*$", re.IGNORECASE)


def parse_pt_response(text: str) -> Optional[Dict[str, str]]:
    """Pure response-parser for a PT email body - no API call. See parse_bw_response().

    Returns dict with keys: direction, sl, body (CTA/CTA_URL lines collapsed into
    a single _PT_CTA_SENTINEL placeholder), cta_text, cta_url. Use
    render_pt_body_html()/render_pt_body_plain() to reassemble a display string —
    never re-embed cta_url as bare visible text (see the "CTA links must be HTML
    anchors" rule in CLAUDE.md).
    """
    try:
        text = text.strip().replace("\\n", "\n")
        lines = text.split("\n")

        direction = None
        sl = None
        body_lines: List[str] = []
        in_body = False

        for line in lines:
            if not in_body and line.startswith("DIRECTION:"):
                direction = line.replace("DIRECTION:", "").strip()
            elif not in_body and line.startswith("SL:"):
                sl = line.replace("SL:", "").strip()
            elif line.strip() == "BODY:" or line.strip().startswith("BODY:"):
                in_body = True
                rest = line.split("BODY:", 1)[1].strip() if "BODY:" in line else ""
                if rest:
                    body_lines.append(rest)
            elif in_body:
                body_lines.append(line)

        # Trim leading/trailing blank lines without collapsing intentional
        # blank lines between paragraphs.
        while body_lines and not body_lines[0].strip():
            body_lines.pop(0)
        while body_lines and not body_lines[-1].strip():
            body_lines.pop()

        if not sl or not body_lines:
            return None

        # Pull the CTA: / CTA_URL: pair out into structured fields, replacing
        # both lines with a single sentinel so the body can be reassembled with
        # either a real anchor (html_notes) or a plain fallback (notes).
        cta_text = ""
        cta_url = ""
        collapsed: List[str] = []
        i = 0
        while i < len(body_lines):
            m = _PT_CTA_LINE_RE.match(body_lines[i].strip())
            if m:
                cta_text = m.group(1).strip()
                j = i + 1
                while j < len(body_lines) and not body_lines[j].strip():
                    j += 1
                if j < len(body_lines):
                    m2 = _PT_CTA_URL_LINE_RE.match(body_lines[j].strip())
                    if m2:
                        cta_url = m2.group(1).strip()
                        i = j + 1
                        collapsed.append(_PT_CTA_SENTINEL)
                        continue
                collapsed.append(_PT_CTA_SENTINEL)
                i += 1
                continue
            collapsed.append(body_lines[i])
            i += 1

        body = "\n".join(collapsed)

        # Guard against the model writing the CTA as a literal inline HTML anchor
        # (e.g. `<a href="...">Shop the Sale.</a>`) instead of the required
        # `CTA: ... ` / `CTA_URL: ...` line pair. Undetected, that raw tag never
        # matches _PT_CTA_LINE_RE, so it survives as plain body text with cta_url
        # empty — render_pt_body_html() then just escapes it (visible `&lt;a
        # href=...&gt;` in html_notes) and render_pt_body_plain() ships it
        # untouched (literal `<a href=...>` in the sent plain-text email). Confirmed
        # 2026-08-05 on an ID PT send. `<strong>` is the only tag ever intentionally
        # emitted here, so anything else is a stray tag.
        _stray_tag_m = re.search(r'<(?!/?strong\b)[a-zA-Z][^>]*>', body, re.IGNORECASE) or \
            re.search(r'<(?!/?strong\b)[a-zA-Z][^>]*>', cta_text, re.IGNORECASE)
        if _stray_tag_m:
            raise SliceBriefValidationError(
                f"PT body/CTA contains a raw HTML tag ({_stray_tag_m.group(0)!r}) instead of "
                "the plain CTA:/CTA_URL: line format the prompt requires. Regenerate the "
                "completion with the CTA as plain text on its own 'CTA: ...' line followed by "
                "a bare 'CTA_URL: ...' line — never inline HTML markup — then re-parse."
            )

        return {
            "direction": direction or "",
            "sl": sl,
            "body": body,
            "cta_text": cta_text,
            "cta_url": cta_url,
        }
    except SliceBriefValidationError:
        raise
    except Exception:
        return None


def render_pt_body_html(brief: Dict[str, str], esc_fn) -> str:
    """Render a parsed PT brief's body for html_notes, with the CTA as a real
    <a href> anchor — satisfies build_pt_campaign.py's highest-priority explicit-
    link rule (_apply_link_rules Rule 1) instead of leaving a bare URL in the
    prose, which no rule matches and which build_pt_campaign.py would otherwise
    leave sitting as visible text in the final email.
    """
    body = brief.get("body", "")
    cta_text = brief.get("cta_text", "")
    cta_url = brief.get("cta_url", "")
    if _PT_CTA_SENTINEL not in body or not cta_url:
        return esc_fn(body)
    before, _, after = body.partition(_PT_CTA_SENTINEL)
    anchor = f'<a href="{cta_url}">{esc_fn(cta_text)}</a>'
    return f"{esc_fn(before)}{anchor}{esc_fn(after)}"


def render_pt_body_plain(brief: Dict[str, str]) -> str:
    """Render a parsed PT brief's body as plain text (CTA shown as 'text url')."""
    body = brief.get("body", "")
    cta_text = brief.get("cta_text", "")
    cta_url = brief.get("cta_url", "")
    cta_line = f"{cta_text} {cta_url}".strip()
    return body.replace(_PT_CTA_SENTINEL, cta_line)


def pick_hav_segment(record: Dict[str, str]) -> str:
    """Return the correct Segment GID for a HAV email task.

    Rules (validated against 100 historical HAV email tasks):
    - Sale emails (any type) → Full File
    - Combined DPS + MP sends → Full File
    - Big-name designer features, Before & After → Full File
    - Single-audience (DPS-only or MP-only) non-sale editorial → Engaged
    """
    story = record.get("story", "") or ""
    category = record.get("category", "") or ""
    s = story.lower()

    # Sale category always → Full File
    if category == "sale_merch":
        return SEGMENT_FULL_FILE

    # Sale keywords in name → Full File
    sale_keywords = [
        "sale", "launch", "early access", "ea launch", "ea reminder",
        "last chance", "final", "extension", "promo", "event launch",
        "items in your design",
    ]
    if any(kw in s for kw in sale_keywords):
        return SEGMENT_FULL_FILE

    # Combined DPS + MP → Full File (broad reach)
    audience = _hav_infer_audience(story)
    if audience == "both":
        return SEGMENT_FULL_FILE

    # Big-name designer features and evergreen broad-appeal content → Full File
    full_file_editorial = [
        "before and after", "room transformation", "designer feature",
        "nancy meyers", "lauren andresky",
    ]
    if any(kw in s for kw in full_file_editorial):
        return SEGMENT_FULL_FILE

    # Default: single-audience non-sale editorial → Engaged
    return SEGMENT_ENGAGED


def pick_hav_audience_gid(record: Dict[str, str]) -> Optional[str]:
    """Return the Audience custom field GID for a HAV email task, or None for combined sends.

    DPS-only  → Pre-converted (1207522425689897)
    MP-only   → Customers     (1207522425689898)
    Combined  → None (leave blank per CLAUDE.md)
    """
    audience = _hav_infer_audience(record.get("story", "") or "")
    if audience == "DPS":
        return AUDIENCE_PRE_CONVERTED
    if audience == "MP":
        return AUDIENCE_CUSTOMERS
    return None  # combined or unknown → leave blank


def _fallback_body_copy(letter: str) -> str:
    """Generate a placeholder body copy skeleton from the template slice definitions."""
    tmpl = CZ_FIGMA_TEMPLATES.get(letter, {})
    slices = tmpl.get("slices", [])
    auto_modules = tmpl.get("auto_modules", [])
    lines = []
    for i, s in enumerate(slices, 1):
        if s["type"] == "brand_asset":
            lines.append(f"Slice {i} — {s['name']} [brand asset]\n")
        elif s["type"] == "image":
            field_lines = "\n".join(f"  {f}" for f in s.get("fields", []))
            lines.append(f"Slice {i} — {s['name']} [IMAGE]\n  Visual: [describe composition, products, mood]\n{field_lines}\n")
        elif s["type"] == "text":
            field_lines = "\n".join(f"  {f}" for f in s.get("fields", []))
            lines.append(f"Slice {i} — {s['name']} [text-only]\n{field_lines}\n")
    for mod in auto_modules:
        lines.append(f"[{mod}]")
    return "\n".join(lines)


# ---------------------------------------------------------------------------
# Resend / re-run sends
# ---------------------------------------------------------------------------
# A calendar row flagged as a resend is a RE-RUN of a past send with fresh creative,
# delivered to the previous campaign's full audience — not a literal resend, and not
# non-openers only. Two things follow, both enforced here so no brand branch can
# drift: the creative direction has to say so, and the brief has to link the source.
# See CLAUDE.md "Resend / Re-Run Sends".

def resend_prompt_instruction(record: Optional[Dict[str, str]] = None,
                              task_name: str = "") -> str:
    """Prompt block for a re-run send — injected into every brand's brief prompt.

    Empty string when the row carries no resend signal, so non-resend prompts are
    byte-identical to before.
    """
    if not detect_resend(record, task_name):
        return ""
    return (
        "\nRESEND / RE-RUN SEND — this row re-runs a past campaign.\n"
        f"- Start DIRECTION with exactly: \"{RESEND_DIRECTION_PREFIX}\" then the creative angle.\n"
        "- Do NOT write \"resend to non-openers\" or any non-opener audience claim. These sends go "
        "to the previous campaign's full audience (openers and non-openers alike), and the creative "
        "is rebuilt fresh rather than re-sent as-is.\n"
        "- Write real slice-by-slice copy as normal. A re-run still needs new slices delivered; "
        "it is not a re-fire of an already-coded email.\n"
    )


def resolve_resend_source(record: Optional[Dict[str, str]] = None,
                          task_name: str = "",
                          brand: str = "",
                          send_date: Optional[str] = None) -> Optional[Dict[str, object]]:
    """Best-guess source campaign for a re-run send, or None.

    Thin wrapper over find_resend_source() that no-ops when the row isn't a resend.
    The Asana ticket URL is NOT resolved here — campaign YAMLs carry no asana gid, so
    the briefing session looks the source ticket up by `asana_search_name` and passes
    its permalink into build_html_notes(resend_source=...).
    """
    if not detect_resend(record, task_name):
        return None
    brand = brand or (record or {}).get("brand", "")
    if not brand:
        return None
    try:
        matches = find_resend_source(brand, task_name, before_date=send_date, top=1)
    except Exception as exc:  # never block a brief on lookup failure
        print(f"[WARN] resend source lookup failed for {task_name!r}: {exc}", file=sys.stderr)
        return None
    return matches[0] if matches else None


def _resend_of_value(resend_source: Optional[Dict[str, object]],
                     asana_url: Optional[str] = None) -> Optional[Tuple[str, str, str]]:
    """Return (label, asana_url, campaign_url) for the "Resend of:" brief line.

    Either URL may be an empty string when unresolved — the label alone still tells a
    designer which send this re-runs, which beats omitting the field.
    """
    if not resend_source:
        return None
    name = str(resend_source.get("campaign_name") or "").strip()
    if not name:
        return None
    sent = str(resend_source.get("send_date") or "").strip()
    subject = str(resend_source.get("subject") or "").strip()
    label = name
    if sent:
        label += f" (sent {sent}"
        label += f', SL "{subject}")' if subject else ")"
    elif subject:
        label += f' (SL "{subject}")'
    campaign_url = str(resend_source.get("campaign_url") or "")
    return label, (asana_url or ""), campaign_url


def apply_resend_direction(parts: List[str],
                           record: Optional[Dict[str, str]],
                           task_name: str,
                           resend_source: Optional[Dict[str, object]],
                           resend_asana_url: Optional[str],
                           *,
                           html: bool) -> List[str]:
    """Post-process an assembled brief: fix re-run wording, add the source links.

    Runs as a single pass over the finished `parts` list rather than inside each
    brand branch — every brand emits its own "Creative Direction:" line (5 separate
    branches in build_html_notes alone), and per-branch edits are exactly how the
    older slice rules drifted out of sync.
    """
    if not detect_resend(record, task_name):
        return parts

    prefix = "<strong>Creative Direction:</strong> " if html else "Email Direction\n"
    out: List[str] = []
    inserted = False
    for part in parts:
        if html and part.startswith(prefix):
            body = part[len(prefix):]
            part = prefix + normalize_resend_direction(body)
        elif not html and out and out[-1] == prefix:
            part = normalize_resend_direction(part)
        out.append(part)

        is_direction_line = (
            part.startswith(prefix) if html else (len(out) >= 2 and out[-2] == prefix)
        )
        if is_direction_line and not inserted:
            resolved = _resend_of_value(resend_source, resend_asana_url)
            if resolved:
                label, asana_url, campaign_url = resolved
                # No clickable campaign link (always the case for Braze — see
                # resend_source.py's module docstring): fall back to a date + title
                # reference the coder can search on, rather than dropping the field.
                campaign_ref = "" if campaign_url else format_campaign_reference(resend_source)
                if html:
                    bits = [_html.escape(label, quote=False)]
                    if asana_url:
                        bits.append(f'<a href="{asana_url}">Asana ticket</a>')
                    if campaign_url:
                        platform = "Klaviyo" if "klaviyo.com" in campaign_url else "Braze"
                        bits.append(f'<a href="{campaign_url}">{platform} campaign</a>')
                    elif campaign_ref:
                        bits.append(f"({_html.escape(campaign_ref, quote=False)})")
                    out.append("<strong>Resend of:</strong> " + " · ".join(bits))
                else:
                    line = f"Resend of: {label}"
                    if asana_url:
                        line += f"\n  Asana: {asana_url}"
                    if campaign_url:
                        line += f"\n  Campaign: {campaign_url}"
                    elif campaign_ref:
                        line += f"\n  ({campaign_ref})"
                    out.append(line)
            else:
                print(
                    f"[WARN] {task_name!r} is flagged as a resend but no source campaign was "
                    "resolved — look it up (scripts/utils/resend_source.py) and pass "
                    "resend_source= so the brief links the original.",
                    file=sys.stderr,
                )
            inserted = True
    return out


def build_description(record: Dict[str, str], sl_ph_text: Optional[str] = None,
                      direction_text: Optional[str] = None,
                      figma_brief: Optional[Dict[str, str]] = None,
                      during_sale: bool = False,
                      sale_name: Optional[str] = None,
                      sale_discount: Optional[str] = None,
                      brand_template: Optional[Dict[str, str]] = None,
                      products_text: Optional[List[str]] = None,
                      pt_brief: Optional[Dict[str, str]] = None,
                      resend_source: Optional[Dict[str, object]] = None,
                      resend_asana_url: Optional[str] = None,
                      task_name: str = "") -> str:
    """Build Asana task description from record fields."""
    parts = []

    if figma_brief and figma_brief.get("template_letter"):
        # CZ designed email format — matches the canonical example task layout
        letter = figma_brief["template_letter"]
        name = figma_brief["template_name"]
        node_id = figma_brief["template_node_id"]
        node_url = node_id.replace(":", "-")

        parts.append(
            f"Figma Template: {letter}. {name} (node-id={node_id})\n"
            f"https://www.figma.com/design/{CZ_FIGMA_FILE_KEY}/2026-CZ-EDITORIALS?node-id={node_url}"
        )
        if figma_brief.get("direction"):
            parts.append(f"\nCreative direction: {figma_brief['direction']}")
        if record.get("landing_page"):
            parts.append(f"\nRecommended LP: {record['landing_page']}")
        if record.get("notes"):
            parts.append(f"\nNotes: {record['notes']}")
        if record.get("promo"):
            parts.append(f"\nPromo: {record['promo']}")
        if record.get("assets_link"):
            parts.append(f"\nAssets: {record['assets_link']}")
        elif record.get("assets"):
            parts.append(f"\nAssets: see MKT calendar for assets link")
        if sl_ph_text:
            parts.append(f"\n{sl_ph_text}")
        template_slices = CZ_FIGMA_TEMPLATES[letter]["slices"]
        image_count = sum(
            1 for s in template_slices if s["type"] == "image" and not s.get("optional")
        )
        if during_sale:
            image_count += 1  # sale link farm header slice (designer-provided)
            image_count += 1  # prepended Slice 1 sale banner
        count_line = f"Slices to deliver: {image_count}\n"
        body_copy_text = figma_brief.get("body_copy") or _fallback_body_copy(letter)
        # F previously skipped this on the (confirmed false, 2026-08-01) assumption its
        # own Figma frame baked in a banner - see build_html_notes()'s matching note.
        if during_sale:
            # Sale banner becomes Slice 1 — shift all other slice numbers by +1
            body_copy_text = re.sub(
                r"Slice (\d+) —",
                lambda m: f"Slice {int(m.group(1)) + 1} —",
                body_copy_text,
            )
            sale_prefix = "    Slice 1 — Sale banner [auto-inserted Braze content block]\n"
        else:
            sale_prefix = ""
        parts.append(f"\nBody copy ({letter}. {name}):\n{count_line}\n{sale_prefix}{body_copy_text}")
        kicker_section = format_cz_kicker_section(letter, record.get("date", ""), story=record.get("story", ""))
        if kicker_section:
            parts.append(f"\n{kicker_section}")
        if during_sale:
            lf_copy = f"{sale_name} / {sale_discount}" if sale_name and sale_discount \
                else sale_name or "[sale name / discount]"
            parts.append(f"\nSale link farm header [IMAGE - designer provided]\n  {lf_copy}\n  Link: https://www.the-citizenry.com/")
        parts.append(f"\n[Auto-created from marketing calendar — {record['source_tab']} row {record['source_row']}]")
    elif figma_brief and figma_brief.get("brand") in ("STF", "BUR", "HAV"):
        # STF/BUR/HAV designed email — plain-text notes (html_notes overwrites this on PUT).
        name = figma_brief["template_name"]
        parts.append(f"Figma Template: {name}\n{figma_brief.get('figma_url', '')}")
        if figma_brief.get("kicker_name"):
            kicker_line = f"Kicker: {figma_brief['kicker_name']}"
            if figma_brief.get("kicker_figma_url"):
                kicker_line += f"\n{figma_brief['kicker_figma_url']}"
            parts.append(kicker_line)
        if figma_brief.get("direction"):
            parts.append(f"\nCreative direction: {figma_brief['direction']}")
        if record.get("landing_page"):
            parts.append(f"\nRecommended LP: {record['landing_page']}")
        if record.get("promo"):
            parts.append(f"\nPromo: {record['promo']}")
        if sl_ph_text:
            parts.append(f"\n{sl_ph_text}")
        if figma_brief.get("body_copy"):
            parts.append(f"\nBody copy ({name}):\n{figma_brief['body_copy']}")
        parts.append(f"\n[Auto-created from marketing calendar — {record['source_tab']} row {record['source_row']}]")
    else:
        # Standard format for all other brands
        if brand_template:
            parts.append(
                f"Figma Template: {brand_template['template_name']}\n"
                f"{brand_template['figma_url']}"
            )
            # Render optional kicker (HAV)
            if brand_template.get("kicker_name"):
                kicker_line = f"Kicker: {brand_template['kicker_name']}"
                if brand_template.get("kicker_figma_url"):
                    kicker_line += f"\n{brand_template['kicker_figma_url']}"
                parts.append(kicker_line)
        if products_text:
            parts.append("Suggested Products:\n" + "\n".join(f"  {p}" for p in products_text))
        if direction_text:
            parts.append("Email Direction\n")
            parts.append(direction_text)
            parts.append("\n---")
        if sl_ph_text:
            parts.append(f"SL/PH Suggestions (AI generated):\n\n{sl_ph_text}")
            parts.append("\n---")
        if pt_brief:
            parts.append(f"Proposed Body Copy (AI generated):\n\n{render_pt_body_plain(pt_brief)}")
            parts.append("\n---")
        if record.get("landing_page"):
            parts.append(f"Landing page: {record['landing_page']}")
        if record.get("assets_link"):
            parts.append(f"Assets: {record['assets_link']}")
        elif record.get("assets"):
            parts.append(f"Assets: see MKT calendar for assets link")
        if record.get("reference_link"):
            parts.append(f"Reference: {record['reference_link']}")
        for link in record.get("extra_links", []):
            parts.append(f"Link: {link}")
        if record.get("notes"):
            parts.append(f"Notes: {record['notes']}")
        if record.get("promo"):
            parts.append(f"Promo: {record['promo']}")
        if record.get("banners"):
            parts.append(f"Banners: {record['banners']}")
        parts.append(f"\n[Auto-created from marketing calendar — {record['source_tab']} row {record['source_row']}]")

    parts = apply_resend_direction(parts, record, task_name, resend_source,
                                   resend_asana_url, html=False)

    return "\n".join(parts)


# Copy field labels whose VALUES get a yellow highlight in every brand's designed
# email auto-brief (CZ, STF, TI, and the standard BUR/ID/HAV/Trade format), signaling
# to the human copyeditor that this text is AI-generated and needs review.
# Non-copy fields (Visual, Link, Layout, Background, etc.) are excluded.
_COPY_FIELD_LABELS = frozenset({
    "SL", "PH",
    "HED", "Hero CTA", "CTA", "CTA button",
    "Body", "Body CTA", "Final CTA", "Kicker CTA",
    "Eyebrow",
    "DEK", "Body HED", "Body DEK",
    "Sale Lock-up",
    "Name",
    "Featured product", "Photo credit",
    "Sale copy",
    # TI-specific copy fields
    "Sub-HED",
    "Descriptor",
    "Print name",
    "Destination",
    "Short italic copy",
    "Inline link",
    "Copy",
    "Animated GIF",
    "Category label",
    "Instagram handle",
    "Fabric name",
    "Color/variant",
})
# Keep legacy alias so any external references still resolve
_CZ_COPY_FIELD_LABELS = _COPY_FIELD_LABELS
_category_block_cta_re = re.compile(r"^Category Block \d+ CTA$")
# Numbered section/room/row fields the AI generates: "Section 1 DEK", "Room 2 CTA",
# "Row 1 HED", "Row 1 Body", etc. "Row N" covers the two-row feature-collage/editorial-
# grid slice fields defined in BW_FIGMA_TEMPLATES - confirmed missing 2026-07-30
# (Chorus Bed Highlight Slice 2 rendered with no highlighted copy at all because
# "Row 1 HED"/"Row 1 CTA" matched none of the three highlight rules). "Body" is
# included in the suffix set - bare/numbered Body paragraph copy is AI-generated and
# needs copyeditor review same as HED/CTA, confirmed 2026-07-30 (corrects the prior
# assumption that Body fields are deliberately excluded).
_numbered_section_copy_re = re.compile(
    r"^(?:Section|Room|Row) \d+ (?:DEK|CTA|HED|Eyebrow|Body)$"
)

# Yellow highlight wrapper for AI-generated copy values needing copyeditor review.
# Matches Asana's native highlighter markup (confirmed from a real Launched task) so
# auto-generated briefs render identically to a human manually highlighting text in
# Asana's UI. Applied to VALUES only — field labels (SL:, HED:, etc.) stay plain.
# Future BUR/ID branches: reuse render_body_copy_nested()/highlight_copy_value() for
# body copy — do not re-implement highlighting per brand.
_COPY_HIGHLIGHT_OPEN = (
    '<mark data-highlight-color="yellow" '
    'style="background-color: #feedd9; '
    'background-color: var(--color-richtext-highlight-background, #feedd9)">'
)
_COPY_HIGHLIGHT_CLOSE = "</mark>"


def build_html_notes(record: Dict[str, str], sl_ph_text: Optional[str] = None,
                     direction_text: Optional[str] = None,
                     figma_brief: Optional[Dict[str, str]] = None,
                     during_sale: bool = False,
                     sale_name: Optional[str] = None,
                     sale_discount: Optional[str] = None,
                     brand_template: Optional[Dict[str, str]] = None,
                     products_text: Optional[List[str]] = None,
                     pt_brief: Optional[Dict[str, str]] = None,
                     resend_source: Optional[Dict[str, object]] = None,
                     resend_asana_url: Optional[str] = None,
                     task_name: str = "") -> str:
    """Build html_notes for Asana rich-text.

    Top-level fields use \\n line breaks with <strong> labels.
    Sub-content (SL/PH lines, body copy lines) uses nested <ul><li> for indented bullets.
    Asana supports this hybrid; <br> and <p> are rejected.
    """
    def esc(text: str) -> str:
        # Unescape first so AI-returned HTML entities (e.g. &#x27;) don't get double-encoded
        return _html.escape(_html.unescape(text or ""), quote=False)

    def href(url: str) -> str:
        return f'<a href="{url}">{url}</a>'

    def nested_ul(lines_list: List[str]) -> str:
        items = "".join(f"<li>{esc(ln)}</li>" for ln in lines_list if ln)
        return f"<ul>{items}</ul>"

    def is_copy_field(label: str) -> bool:
        return (
            label in _COPY_FIELD_LABELS
            or bool(_category_block_cta_re.match(label))
            or bool(_numbered_section_copy_re.match(label))
        )

    def highlight_copy_value(line: str) -> str:
        """Wrap the value in a yellow highlight if this line's field label is copyeditor-reviewed.

        "Link:" fields are a special case: the visible text stays the bare URL (never
        highlighted - it's a structural field, not copy), but the URL itself is wrapped
        in a real <a href> anchor so it's clickable in Asana - previously rendered as
        plain escaped text with no anchor at all. Confirmed missing 2026-07-31.
        """
        if ": " not in line:
            return esc(line)
        label, value = line.split(": ", 1)
        if label == "Link" and value.strip().startswith(("http://", "https://")):
            url = value.strip()
            return f"{esc(label)}: {href(url)}"
        if is_copy_field(label):
            return f"{esc(label)}: {_COPY_HIGHLIGHT_OPEN}{esc(value)}{_COPY_HIGHLIGHT_CLOSE}"
        return esc(line)

    def render_body_copy_nested(all_lines: List[str]) -> str:
        """Render body copy lines: slice headers get their sub-fields as nested bullets.
        Type labels like [IMAGE] and [text-only] are stripped from headers;
        [content block...] is preserved since it carries meaning."""
        slice_re = re.compile(r"^Slice \d+")
        type_label_re = re.compile(r"\s*\[(IMAGE[^\]]*|text-only[^\]]*|brand asset[^\]]*)\]")

        def clean_header(line: str) -> str:
            return type_label_re.sub("", line).strip()

        html_parts = []
        i = 0
        while i < len(all_lines):
            line = all_lines[i]
            if not line:
                i += 1
                continue
            if slice_re.match(line):
                sub = []
                j = i + 1
                while j < len(all_lines):
                    nl = all_lines[j]
                    if slice_re.match(nl):
                        break
                    if nl:
                        sub.append(nl)
                    j += 1
                i = j
                header = clean_header(line)
                if sub:
                    nested = "".join(f"<li>{highlight_copy_value(s)}</li>" for s in sub)
                    html_parts.append(f"<li>{esc(header)}<ul>{nested}</ul></li>")
                else:
                    html_parts.append(f"<li>{esc(header)}</li>")
            else:
                html_parts.append(f"<li>{esc(line)}</li>")
                i += 1
        return "<ul>" + "".join(html_parts) + "</ul>"

    parts: List[str] = []

    if figma_brief and "template_letter" in figma_brief:
        # CZ designed email — matches CLAUDE.md 5-field format + Body Copy
        letter = figma_brief["template_letter"]
        name = figma_brief["template_name"]
        node_id = figma_brief["template_node_id"]
        node_url = node_id.replace(":", "-")
        figma_url = (
            f"https://www.figma.com/design/{CZ_FIGMA_FILE_KEY}"
            f"/2026-CZ-EDITORIALS?node-id={node_url}"
        )

        parts.append(f"<strong>Creative Direction:</strong> {esc(figma_brief.get('direction', ''))}")
        lp = record.get("landing_page", "")
        if lp:
            _assert_links_live([f"Link: {lp}"], "top-level LP field")
        parts.append(f"<strong>LP:</strong> {href(lp) if lp else ''}")
        parts.append(f"<strong>Figma:</strong> {esc(letter)}. {esc(name)} — {href(figma_url)}")

        if sl_ph_text:
            sl_lines = [ln.strip() for ln in sl_ph_text.strip().split("\n") if ln.strip()]
            sl_items = "".join(f"<li>{highlight_copy_value(ln)}</li>" for ln in sl_lines)
            parts.append(f"<strong>SL/PH (AI generated):</strong><ul>{sl_items}</ul>")

        if figma_brief.get("body_copy"):
            template_slices = CZ_FIGMA_TEMPLATES[letter]["slices"]
            image_count = sum(
                1 for s in template_slices if s["type"] == "image" and not s.get("optional")
            )
            if during_sale:
                image_count += 1  # sale link farm header slice (designer-provided)
                image_count += 1  # prepended Slice 1 sale banner
            total_slice_count = len(template_slices)

            body_copy_text = figma_brief["body_copy"]
            # Template F previously skipped this, on the assumption its own Figma frame
            # already baked in a sale banner - confirmed false 2026-08-01 (screenshot +
            # metadata check of node 789:527 shows no banner element at all, hidden or
            # otherwise; it goes straight from the logo into the Archive Sale hero). F
            # now gets the same code-injected banner as every other template.
            if during_sale:
                body_copy_text = re.sub(
                    r"Slice (\d+) —",
                    lambda m: f"Slice {int(m.group(1)) + 1} —",
                    body_copy_text,
                )
                lf_copy = f"{sale_name} / {sale_discount}" if sale_name and sale_discount \
                    else sale_name or "[sale name / discount]"
                # Was previously the bare string "Sale Banner" - not formatted as a real
                # "Slice N —" header at all, so it rendered with no nested fields and was
                # invisible to any "Slice N —" line count. Match the sale-link-farm
                # header's own field format (Sale copy: / Link:) below.
                sale_prefix_lines = [
                    "Slice 1 — Sale banner",
                    f"Sale copy: {lf_copy}",
                    "Link: https://www.the-citizenry.com/",
                ]
                during_sale_offset = 1
            else:
                sale_prefix_lines = []
                during_sale_offset = 0

            # Strip auto-module bracket lines — kicker is added below as a proper slice
            stripped_lines = [
                ln.strip() for ln in body_copy_text.split("\n")
                if ln.strip() and not ln.strip().startswith("[")
            ]
            all_lines = sale_prefix_lines + stripped_lines

            # Append kicker as the final numbered slice entry
            kicker_section = format_cz_kicker_section(letter, record.get("date", ""), story=record.get("story", ""))
            has_kicker = False
            if kicker_section and kicker_section != "Kicker: None":
                kicker_modules = [
                    ln.lstrip("* ").strip()
                    for ln in kicker_section.split("\n")
                    if ln.strip() and not ln.strip().startswith("Kicker modules:")
                ]
                if kicker_modules:
                    has_kicker = True
                    kicker_num = total_slice_count + during_sale_offset + 1
                    all_lines.append(f"Slice {kicker_num} — Kicker [content block - no slice needed]")
                    all_lines.extend(kicker_modules)

            # Append sale link farm header as the last delivered slice for sale emails
            if during_sale:
                lf_num = total_slice_count + during_sale_offset + 1 + (1 if has_kicker else 0)
                lf_copy = f"{sale_name} / {sale_discount}" if sale_name and sale_discount \
                    else sale_name or "[sale name / discount]"
                all_lines.append(f"Slice {lf_num} — Sale link farm header [IMAGE]")
                all_lines.append(f"Sale copy: {lf_copy}")
                all_lines.append("Link: https://www.the-citizenry.com/")

            # "Slices to deliver" is always the ACTUAL count of what's in all_lines at
            # this point, never a pre-computed guess - see _warn_slice_count_mismatch()
            # docstring for the bug this replaced. The kicker slice, if present, sits
            # outside CZ_FIGMA_TEMPLATES' own base slice list, so it's folded into
            # expected_count here rather than into image_count above.
            expected_count = image_count + (1 if has_kicker else 0)
            actual_count = _warn_slice_count_mismatch(all_lines, expected_count, f"CZ {letter}. {name}")
            all_lines = _renumber_slices_sequentially(all_lines)
            _assert_links_live(all_lines, f"CZ {letter}. {name}")
            all_lines = [f"Slices to deliver: {actual_count}"] + all_lines

            parts.append(
                f"<strong>Body Copy ({esc(letter)}. {esc(name)}):</strong>"
                + render_body_copy_nested(all_lines)
            )

    elif figma_brief and figma_brief.get("brand") in ("STF", "BUR"):
        # STF/BUR designed email — CZ-style structured slices, per-slice Layout. STF gets a
        # sale-banner prepend+renumber (like CZ); BUR does NOT — Burrow's sale messaging is
        # baked inline into the hero/kicker copy by the AI prompt, never a separate slice.
        # Neither brand auto-cycles kickers or appends a CZ-style sale link farm (both
        # brands' kickers/link-farms are manual/reference-only — STF_KICKERS / BW_KICKERS).
        tkey = figma_brief["template_key"]
        name = figma_brief["template_name"]
        figma_url = figma_brief["figma_url"]
        brand_is_stf = figma_brief.get("brand") == "STF"
        templates_catalog = STF_FIGMA_TEMPLATES if brand_is_stf else BW_FIGMA_TEMPLATES

        parts.append(f"<strong>Creative Direction:</strong> {esc(figma_brief.get('direction', ''))}")
        lp = record.get("landing_page", "")
        if lp:
            _assert_links_live([f"Link: {lp}"], "top-level LP field")
        parts.append(f"<strong>LP:</strong> {href(lp) if lp else ''}")
        parts.append(f'<strong>Figma:</strong> <a href="{figma_url}">{esc(name)}</a>')

        if sl_ph_text:
            sl_lines = [ln.strip() for ln in sl_ph_text.strip().split("\n") if ln.strip()]
            sl_items = "".join(f"<li>{highlight_copy_value(ln)}</li>" for ln in sl_lines)
            parts.append(f"<strong>SL/PH (AI generated):</strong><ul>{sl_items}</ul>")

        if figma_brief.get("body_copy"):
            template = templates_catalog.get(tkey, {})
            template_slices = template.get("slices", [])
            is_sale_hero = template.get("is_sale_hero", False)
            # Count of deliverable image slices (exclude optional add-ons).
            image_count = sum(
                1 for s in template_slices
                if s["type"] == "image" and not s.get("optional")
            )
            # BUR never gets a prepended sale-banner slice — sale is inline copy only.
            apply_banner = brand_is_stf and during_sale and not is_sale_hero
            if apply_banner:
                image_count += 1  # prepended sale banner slice

            body_copy_text = figma_brief["body_copy"]
            sale_prefix_lines: List[str] = []
            if apply_banner:
                # Sale banner becomes Slice 1 — shift all AI slice numbers by +1.
                body_copy_text = re.sub(
                    r"Slice (\d+) —",
                    lambda m: f"Slice {int(m.group(1)) + 1} —",
                    body_copy_text,
                )
                lf_copy = f"{sale_name} / {sale_discount}" if sale_name and sale_discount \
                    else sale_name or "[sale name / discount]"
                sale_prefix_lines = [
                    "Slice 1 — Sale banner",
                    "Layout: Full width",
                    f"Sale copy: {lf_copy}",
                    "Link: https://www.stfrank.com/",
                ]

            stripped_lines = [ln.strip() for ln in body_copy_text.split("\n") if ln.strip()]
            all_lines = sale_prefix_lines + stripped_lines

            # "Slices to deliver" is always the ACTUAL count of what's in all_lines,
            # never the pre-computed template-catalog guess — see
            # _warn_slice_count_mismatch() docstring (same fix applied to CZ above).
            brand_label = "STF" if brand_is_stf else "BUR"
            actual_count = _warn_slice_count_mismatch(all_lines, image_count, f"{brand_label} {name}")
            all_lines = _renumber_slices_sequentially(all_lines)
            _assert_links_live(all_lines, f"{brand_label} {name}")
            if not brand_is_stf:
                _assert_quick_ship_products(all_lines, tkey)
            all_lines = [f"Slices to deliver: {actual_count}"] + all_lines

            parts.append(
                f"<strong>Body Copy ({esc(name)}):</strong>"
                + render_body_copy_nested(all_lines)
            )

    elif figma_brief and figma_brief.get("brand") == "HAV":
        # HAV designed email — copy-first slice-by-slice, joining CZ/STF/TI/BUR as of
        # 2026-07-29. Templates have a variable section count per send (unlike the fixed
        # per-template slice lists CZ/STF/BUR use), so "Slices to deliver" is counted from
        # the AI's own output rather than a template catalog lookup — same approach TI uses.
        name = figma_brief["template_name"]
        figma_url = figma_brief["figma_url"]

        parts.append(f"<strong>Creative Direction:</strong> {esc(figma_brief.get('direction', ''))}")
        if during_sale and (sale_name or sale_discount):
            _promo_display = " — ".join(p for p in [sale_name, sale_discount] if p)
            parts.append(f"<strong>Promo:</strong> {esc(_promo_display)}")
        lp = record.get("landing_page", "")
        if lp:
            _assert_links_live([f"Link: {lp}"], "top-level LP field")
        parts.append(f"<strong>LP:</strong> {href(lp) if lp else ''}")
        parts.append(f'<strong>Figma:</strong> <a href="{figma_url}">{esc(name)}</a>')

        if sl_ph_text:
            sl_lines = [ln.strip() for ln in sl_ph_text.strip().split("\n") if ln.strip()]
            sl_items = "".join(f"<li>{highlight_copy_value(ln)}</li>" for ln in sl_lines)
            parts.append(f"<strong>SL/PH (AI generated):</strong><ul>{sl_items}</ul>")

        if figma_brief.get("body_copy"):
            body_lines = [
                ln.strip() for ln in figma_brief["body_copy"].split("\n") if ln.strip()
            ]
            slice_count = sum(1 for l in body_lines if l.startswith("Slice"))

            if during_sale:
                # Prepend the Sale Banner as Slice 1 — always exactly one slice position,
                # even for a combined "DPS and MP" send (that case lists both audience
                # destinations as alternate versions of the same slice, not two stacked
                # banner slices — see _hav_sale_banner_body_lines). Renumber the
                # AI-generated Hero/Section slices by 1 to make room for it.
                body_lines = [
                    re.sub(r"^Slice (\d+) —", lambda m: f"Slice {int(m.group(1)) + 1} —", ln)
                    for ln in body_lines
                ]
                sale_label = " — ".join(p for p in [sale_name, sale_discount] if p) or "Sale"
                banner_lines = ["Slice 1 — Sale banner"] + _hav_sale_banner_body_lines(
                    record.get("story", ""), sale_label
                )
                body_lines = banner_lines + body_lines
                slice_count += 1

            _assert_links_live(body_lines, f"HAV {name}")
            all_lines = [f"Slices to deliver: {slice_count}"] + body_lines
            parts.append(
                f"<strong>Body Copy ({esc(name)}):</strong>"
                + render_body_copy_nested(all_lines)
            )

        kicker_name = figma_brief.get("kicker_name")
        kicker_url = figma_brief.get("kicker_figma_url")
        if kicker_name:
            kicker_part = f'<a href="{kicker_url}">{esc(kicker_name)}</a>' if kicker_url else esc(kicker_name)
            parts.append(f"<strong>Kicker:</strong> {kicker_part}")

    elif figma_brief and "template_key" in figma_brief:
        # TI designed email
        name = figma_brief["template_name"]
        figma_url = figma_brief["figma_url"]

        parts.append(f"<strong>Creative Direction:</strong> {esc(figma_brief.get('direction', ''))}")
        lp = record.get("landing_page", "")
        if lp:
            _assert_links_live([f"Link: {lp}"], "top-level LP field")
        parts.append(f"<strong>LP:</strong> {href(lp) if lp else ''}")
        parts.append(f'<strong>Figma:</strong> <a href="{figma_url}">{esc(name)}</a>')

        if sl_ph_text:
            sl_lines = [ln.strip() for ln in sl_ph_text.strip().split("\n") if ln.strip()]
            sl_items = "".join(f"<li>{highlight_copy_value(ln)}</li>" for ln in sl_lines)
            parts.append(f"<strong>SL/PH (AI generated):</strong><ul>{sl_items}</ul>")

        if figma_brief.get("body_copy"):
            body_lines = [
                ln.strip() for ln in figma_brief["body_copy"].split("\n") if ln.strip()
            ]
            _assert_links_live(body_lines, f"TI {name}")
            all_lines = [f"Slices to deliver: {sum(1 for l in body_lines if l.startswith('Slice'))}"] + body_lines
            parts.append(
                f"<strong>Body Copy ({esc(name)}):</strong>"
                + render_body_copy_nested(all_lines)
            )

        kicker_name = figma_brief.get("kicker_name")
        kicker_url = figma_brief.get("kicker_figma_url")
        kicker_slices = figma_brief.get("kicker_slices_text")
        if kicker_name:
            kicker_figma_part = f'<a href="{kicker_url}">{esc(kicker_name)}</a>' if kicker_url else esc(kicker_name)
            if kicker_slices:
                kicker_lines = [ln.strip() for ln in kicker_slices.split("\n") if ln.strip()]
                kicker_nested = render_body_copy_nested(kicker_lines)
                parts.append(f"<strong>Kicker:</strong> {kicker_figma_part}{kicker_nested}")
            else:
                parts.append(f"<strong>Kicker:</strong> {kicker_figma_part}")

    else:
        # Standard format for other brands
        if direction_text:
            parts.append(f"<strong>Creative Direction:</strong> {esc(direction_text)}")

        # Promo details from Asana Promo Tracking calendar
        if during_sale and (sale_name or sale_discount):
            _promo_display = " — ".join(p for p in [sale_name, sale_discount] if p)
            parts.append(f"<strong>Promo:</strong> {esc(_promo_display)}")

        lp = record.get("landing_page", "")
        if lp:
            _assert_links_live([f"Link: {lp}"], "top-level LP field")
            parts.append(f"<strong>LP:</strong> {href(lp)}")

        if brand_template:
            t_name = esc(brand_template.get("template_name", ""))
            t_url = brand_template.get("figma_url", "")
            figma_part = f"{t_name} — {href(t_url)}" if t_url else t_name
            if figma_part:
                parts.append(f"<strong>Figma:</strong> {figma_part}")
            # Render optional kicker (HAV only)
            kicker_name = brand_template.get("kicker_name", "")
            kicker_url = brand_template.get("kicker_figma_url", "")
            if kicker_name:
                kicker_part = f"Kicker: {esc(kicker_name)} — {href(kicker_url)}" if kicker_url else f"Kicker: {esc(kicker_name)}"
                parts.append(kicker_part)

        if products_text:
            parts.append(f"<strong>Products:</strong>{nested_ul(products_text)}")

        if sl_ph_text:
            sl_lines = [ln.strip() for ln in sl_ph_text.strip().split("\n") if ln.strip()]
            sl_items = "".join(f"<li>{highlight_copy_value(ln)}</li>" for ln in sl_lines)
            parts.append(f"<strong>SL/PH (AI generated):</strong><ul>{sl_items}</ul>")

        if pt_brief:
            # Header must sit alone on its own line — build_pt_campaign.py's
            # _BODY_COPY_HEADER regex requires nothing else on that line, and
            # slices everything after it in as the real email body. The CTA
            # renders as a real <a href> anchor (never a bare URL in the prose)
            # so build_pt_campaign.py's explicit-link rule (highest priority)
            # picks it up instead of leaving the URL sitting as visible text.
            parts.append(
                f"<strong>Proposed Body Copy (AI generated):</strong>\n"
                f"{_COPY_HIGHLIGHT_OPEN}{render_pt_body_html(pt_brief, esc)}{_COPY_HIGHLIGHT_CLOSE}"
            )

    if not parts:
        return ""

    parts = apply_resend_direction(parts, record, task_name, resend_source,
                                   resend_asana_url, html=True)

    return "<body>" + "\n".join(parts) + "</body>"


def dedup_key(record: Dict[str, str]) -> str:
    """Create a unique key for dedup tracking."""
    return f"{record['brand']}|{record['date']}|{record['story']}"


# ---------------------------------------------------------------------------
# Tab parsers
# ---------------------------------------------------------------------------

def link_at(row_links: List[Dict[str, str]], idx: Optional[int]) -> str:
    """Get the hyperlink URL from a row_links entry, or empty string."""
    if idx is None or idx >= len(row_links):
        return ""
    return row_links[idx].get("link", "")


def parse_tab(tab_name: str, rows: List[List[str]],
              hyperlinks: Optional[List[List[Dict[str, str]]]] = None) -> List[Dict[str, str]]:
    """Parse a tab into normalized task records."""
    configs = TAB_CONFIGS.get(tab_name, [])
    if not configs:
        print(f"  Warning: No config for tab '{tab_name}', skipping")
        return []

    records = []
    current_date = None

    for row_idx, row in enumerate(rows):
        # Skip header rows (first few rows are typically headers)
        if row_idx < 2:
            continue

        row_links = hyperlinks[row_idx] if hyperlinks and row_idx < len(hyperlinks) else []

        # Try to parse date from the date column (shared across brand configs)
        date_col = configs[0]["date_col"]
        raw_date = cell(row, date_col)
        parsed_date = parse_date_mmdd(raw_date)
        if parsed_date:
            current_date = parsed_date

        # Process each brand config for this row
        for cfg in configs:
            story = cell(row, cfg["story_col"])

            if should_skip_row(story):
                continue

            # For TRADE tab, read brand from the brand column
            brand = cfg["brand"]
            if tab_name == "TRADE" and cfg.get("brand_col"):
                explicit_brand = cell(row, cfg["brand_col"]).upper()
                if explicit_brand in BRAND_OPTIONS:
                    brand = explicit_brand

            # Must have a date
            date_val = parsed_date or current_date
            if not date_val:
                continue

            # Extract hyperlinks from story and LP columns
            story_link = link_at(row_links, cfg["story_col"])
            lp_link = link_at(row_links, cfg.get("lp_col"))

            # Collect all links from all relevant columns for this brand
            all_links = set()
            cols_to_check = [cfg["story_col"], cfg.get("lp_col"),
                             cfg.get("assets_col"), cfg.get("notes_col"),
                             cfg.get("promo_col"), cfg.get("banners_col")]
            for col_idx in cols_to_check:
                if col_idx is None or col_idx >= len(row_links):
                    continue
                entry = row_links[col_idx]
                if entry.get("link"):
                    all_links.add(entry["link"])
                for il in entry.get("inline_links", []):
                    all_links.add(il)
            # Remove the story reference link from the "extra" set
            extra_links = all_links - {story_link} - {lp_link}

            assets_text = cell(row, cfg.get("assets_col"))
            assets_link = link_at(row_links, cfg.get("assets_col"))

            record = {
                "brand": brand,
                "story": story,
                "date": date_val,
                "landing_page": lp_link or cell(row, cfg.get("lp_col")),
                "assets": assets_text,
                "assets_link": assets_link,
                "notes": cell(row, cfg.get("notes_col")),
                "subject_line": cell(row, cfg.get("subject_col")),
                "preheader": cell(row, cfg.get("preheader_col")),
                "promo": cell(row, cfg.get("promo_col")) if cfg.get("promo_col") else "",
                "banners": cell(row, cfg.get("banners_col")) if cfg.get("banners_col") else "",
                "reference_link": story_link,
                "extra_links": sorted(extra_links) if extra_links else [],
                "source_tab": tab_name,
                "source_row": row_idx + 1,  # 1-indexed for human readability
                "is_trade": tab_name == "TRADE",
            }
            records.append(record)

    return records


# ---------------------------------------------------------------------------
# Asana task creation
# ---------------------------------------------------------------------------

def _parse_sale_discount(raw_discount: str) -> Optional[str]:
    """Clean up a raw discount string from sale_schedules.yaml.

    Strips prefixes like "DISCOUNT/OFFER:" and returns None for placeholder
    values like "PERIOD: 1H 2026" or "(PROPOSED)" that haven't been filled in yet.
    """
    if not raw_discount:
        return None
    _PLACEHOLDER_MARKERS = ("PERIOD:", "(PROPOSED)", "DETERMINED", "(TBD)")
    for line in raw_discount.splitlines():
        line = line.strip()
        if not line:
            continue
        if any(line.upper().startswith(m.upper()) or m.upper() in line.upper()
               for m in _PLACEHOLDER_MARKERS):
            return None
        for prefix in ("DISCOUNT/OFFER:", "OFFER:", "DISCOUNT:"):
            if line.upper().startswith(prefix):
                line = line[len(prefix):].strip()
                break
        if line:
            return line
    return None


def _get_sale_for_date(brand: str, date_str: str,
                       havenly_audience: Optional[str] = None) -> Dict[str, Any]:
    """Return active sale name/discount for any brand on the given date.

    Args:
        brand: Brand code (CZ, ID, BUR, STF, TI, HAV, TRADE)
        date_str: ISO date string
        havenly_audience: Optional "PC" or "CONV" for HAV audience-specific matching

    Returns:
        dict with during_sale (bool), sale_name (str|None), sale_discount (str|None),
        sale_start (str|None), sale_end (str|None) — the matched sale phase's raw
        'YYYY-MM-DD' start/end date strings, for first/last-day-of-sale comparisons.
    """
    result: Dict[str, Any] = {
        "during_sale": False, "sale_name": None, "sale_discount": None,
        "sale_start": None, "sale_end": None,
    }
    try:
        from scripts.utils.sale_matcher import parse_campaign_date, parse_sale_date
        schedules = _get_sale_schedules()
        date_obj = parse_campaign_date(date_str)
        if not date_obj:
            return result
        for sale in schedules:
            if sale.get("brand") != brand:
                continue
            if brand == "HAV" and havenly_audience:
                sale_audience = sale.get("havenly_audience")
                if sale_audience and sale_audience != havenly_audience:
                    continue
            s = parse_sale_date(sale.get("start_date"))
            e = parse_sale_date(sale.get("end_date")) or s
            if s and s <= date_obj <= e:
                result["during_sale"] = True
                result["sale_name"] = sale.get("name", "").strip() or None
                result["sale_discount"] = _parse_sale_discount(sale.get("discount") or "")
                result["sale_start"] = sale.get("start_date")
                result["sale_end"] = sale.get("end_date")
                break
    except Exception:
        pass
    return result


# --- BUR (Burrow) default Send time selection ------------------------------
# Confirmed with Jordan 2026-07-29. Applies only to BUR email tasks. The PM half of a
# same-day pair keeps the existing universal "4:00 PM" (set elsewhere in
# _assign_same_day_send_times) — these helpers only pick a value for the AM/solo record,
# which today is left blank for every brand.
_BW_FIRST_DAY_TIME = "11:00 AM"          # first day of sale — morning, not too early
_BW_LAST_DAY_EARLY_START = 7 * 60 + 30   # 7:30 AM
_BW_LAST_DAY_EARLY_END = 9 * 60 + 30     # 9:30 AM
_BW_AFTERNOON_START = 13 * 60            # 1:00 PM
_BW_AFTERNOON_END = 17 * 60              # 5:00 PM
_BW_REASONABLE_START = 7 * 60 + 30       # 7:30 AM
_BW_REASONABLE_END = 18 * 60             # 6:00 PM
_BW_AFTERNOON_WEIGHT = 0.7               # weight toward 1-5pm on non-sale-edge days


def _format_send_time(total_minutes: int) -> str:
    """Minutes since midnight -> '7:30 AM' / '4:00 PM' style string (matches the
    convention already used for the hardcoded same-day PM value)."""
    h24, m = divmod(total_minutes, 60)
    period = "AM" if h24 < 12 else "PM"
    h12 = h24 % 12 or 12
    return f"{h12}:{m:02d} {period}"


def _random_time_slot(start_min: int, end_min: int, step: int = 30) -> str:
    """Random time string on a `step`-minute grid within [start_min, end_min]."""
    start_snapped = ((start_min + step - 1) // step) * step
    end_snapped = (end_min // step) * step
    if end_snapped < start_snapped:
        end_snapped = start_snapped
    n_steps = (end_snapped - start_snapped) // step
    choice_min = start_snapped + random.randint(0, n_steps) * step
    return _format_send_time(choice_min)


def _bw_default_send_time(record: Dict[str, str]) -> str:
    """Pick a default Send time for a BUR (Burrow) email — AM/solo record only.

    Rules (confirmed with Jordan 2026-07-29):
    - First day of an active sale phase -> 11:00 AM (morning, but not so early the
      website may not have updated yet).
    - Last day of an active sale phase, WITHOUT "final hours" in the story/notes ->
      early AM, randomized within 7:30-9:30 AM. Applies whether this is a solo send
      or the AM half of a last-day double send.
    - Last day of an active sale phase WITH "final hours" in the story/notes -> falls
      through to the general variety rule below (a "final hours" send isn't meant to
      go out at 7:30 AM).
    - Otherwise -> vary the time for freshness: 70% chance of a random slot in the
      1:00-5:00 PM afternoon window, 30% chance of a random slot elsewhere in the
      7:30 AM-6:00 PM "reasonable hours" range (before 1pm or after 5pm).
    """
    story_notes = (record.get("story") or "") + " " + (record.get("notes") or "")
    has_final_hours = bool(re.search(r"final hours", story_notes, re.IGNORECASE))

    sale_ctx = _get_sale_for_date("BUR", record.get("date", ""))
    date_str = record.get("date", "")
    is_first_day = sale_ctx.get("during_sale") and sale_ctx.get("sale_start") == date_str
    is_last_day = sale_ctx.get("during_sale") and sale_ctx.get("sale_end") == date_str

    if is_first_day:
        return _BW_FIRST_DAY_TIME
    if is_last_day and not has_final_hours:
        return _random_time_slot(_BW_LAST_DAY_EARLY_START, _BW_LAST_DAY_EARLY_END)

    if random.random() < _BW_AFTERNOON_WEIGHT:
        return _random_time_slot(_BW_AFTERNOON_START, _BW_AFTERNOON_END)
    if random.random() < 0.5:
        return _random_time_slot(_BW_REASONABLE_START, _BW_AFTERNOON_START)
    return _random_time_slot(_BW_AFTERNOON_END, _BW_REASONABLE_END)


def _assign_same_day_send_times(
    records: List[Dict[str, str]], mapping: Dict[str, str]
) -> None:
    """Tag same-day same-brand pairs so the PM record gets send_time='4:00 PM'.

    Rules:
    - Two emails same brand+date → one AM, one PM.
    - HAV exception: one DPS + one MP → both AM (different audiences, not a conflict).
      Two DPS or two MP on the same day still require one PM.
    - PT email gets PM when paired with a designed email.
    - Otherwise the second record in the list gets PM.
    - If a same-day task already exists in the mapping, the new record is a second send
      and gets PM (HAV DPS/MP exception also applied when audience is detectable from story).
    """
    from collections import defaultdict

    # Build a map of (brand, date) → [existing story strings] from already-created tasks
    existing_brand_dates: Dict[tuple, List[str]] = defaultdict(list)
    for key in mapping:
        parts = key.split("|", 2)
        if len(parts) >= 3:
            existing_brand_dates[(parts[0], parts[1])].append(parts[2])

    # Group new records by (brand, date)
    by_brand_date: Dict[tuple, List[int]] = defaultdict(list)
    for idx, r in enumerate(records):
        by_brand_date[(r["brand"], r["date"])].append(idx)

    for (brand, date), indices in by_brand_date.items():
        group = [records[i] for i in indices]
        existing_stories = existing_brand_dates.get((brand, date), [])
        has_existing = bool(existing_stories)

        # Nothing to do for pairing, but BUR solo sends still get a default Send time.
        if len(indices) < 2 and not has_existing:
            if brand == "BUR":
                records[indices[0]]["send_time"] = _bw_default_send_time(records[indices[0]])
            continue

        # HAV exception: one DPS + one MP → both AM
        if brand == "HAV":
            if len(group) == 2 and not has_existing:
                aud_a = _hav_infer_audience(group[0].get("story", ""))
                aud_b = _hav_infer_audience(group[1].get("story", ""))
                if {aud_a, aud_b} == {"DPS", "MP"}:
                    continue
            elif len(group) == 1 and has_existing:
                # Can't look up the existing task's audience without an API call, but the
                # existing story string is in the mapping key — use it to infer audience.
                new_aud = _hav_infer_audience(group[0].get("story", ""))
                existing_auds = {_hav_infer_audience(s) for s in existing_stories}
                if new_aud == "DPS" and "MP" in existing_auds:
                    continue
                if new_aud == "MP" and "DPS" in existing_auds:
                    continue

        # Determine which record gets PM — priority cascade:
        # 1. Exactly one PT paired with a designed email → PT gets PM
        # 2. "Evening" or "PM" keyword in story/notes → that record gets PM
        # 3. "Final hours" keyword in story/notes → that record gets PM
        # 4. Single new record with an existing same-day task → new one always PM
        # 5. Fall back to second record in creation order

        def _signal_text(r: Dict[str, str]) -> str:
            return ((r.get("story") or "") + " " + (r.get("notes") or "")).strip()

        pt_indices = [
            indices[j] for j, r in enumerate(group)
            if _is_plain_text_story(r.get("story", ""))
        ]

        if len(pt_indices) == 1:
            # Mixed types: exactly one PT → PT is the PM send
            pm_global_idx = pt_indices[0]
        else:
            # Both same type (or both PT) — check keyword signals
            evening_pm_idx = next(
                (indices[j] for j, r in enumerate(group)
                 if re.search(r"\bevening\b|\bpm\b", _signal_text(r), re.IGNORECASE)),
                None,
            )
            final_hours_idx = next(
                (indices[j] for j, r in enumerate(group)
                 if re.search(r"final hours", _signal_text(r), re.IGNORECASE)),
                None,
            )
            if evening_pm_idx is not None:
                pm_global_idx = evening_pm_idx
            elif final_hours_idx is not None:
                pm_global_idx = final_hours_idx
            elif has_existing and len(indices) == 1:
                pm_global_idx = indices[0]
            else:
                pm_global_idx = indices[1]

        records[pm_global_idx]["send_time"] = "4:00 PM"
        preview = records[pm_global_idx]["story"][:45]
        print(f"  [same-day PM] {brand} {date}: '{preview}' → Send time = 4:00 PM")

        # BUR: the AM half of the pair still needs an explicit default (every other
        # brand leaves it blank for the build-time resolver to pick, but BUR now always
        # gets a first/last-day-aware or varied default per the AM/solo rules above).
        if brand == "BUR":
            for am_idx in indices:
                if am_idx == pm_global_idx:
                    continue
                records[am_idx]["send_time"] = _bw_default_send_time(records[am_idx])


def create_asana_task(record: Dict[str, str], generate_ai: bool = True,
                      inventory_context: Optional[str] = None) -> Optional[str]:
    """Create a single Asana task. Returns the task GID or None on failure.

    Args:
        record: Calendar record with brand, story, date, etc.
        generate_ai: Whether to generate AI content (direction + SL/PH).
        inventory_context: Optional pre-formatted inventory text for AI prompt.
    """
    category_key = infer_category(record["story"], record["source_tab"])
    category_gid = CATEGORY_OPTIONS.get(category_key)

    # Look up active sale from the Asana Promo Tracking calendar for this brand/date
    _hav_aud: Optional[str] = None
    if record["brand"] == "HAV":
        _inf = _hav_infer_audience(record.get("story", ""))
        _hav_aud = "PC" if _inf == "DPS" else "CONV" if _inf == "MP" else None
    sale_ctx = _get_sale_for_date(record["brand"], record["date"], havenly_audience=_hav_aud)
    during_sale = sale_ctx["during_sale"]
    sale_name = sale_ctx["sale_name"]
    sale_discount = sale_ctx["sale_discount"]

    # For non-CZ brands: inject sale info into record['promo'] so AI generation picks it up
    if during_sale and record["brand"] != "CZ" and not record.get("promo"):
        _promo_parts = [p for p in [sale_name, sale_discount] if p]
        if _promo_parts:
            record["promo"] = " — ".join(_promo_parts)

    # For STF consumer emails, fetch product suggestions to populate the Products field
    stf_products_text: Optional[List[str]] = None
    if record["brand"] == "STF" and not record.get("is_trade"):
        stf_products = get_stf_product_suggestions(
            record["story"], n=4, recency_days=60, send_date=record.get("date")
        )
        if stf_products:
            stf_products_text = format_stf_products_for_notes(stf_products)
            # Also inject product names into inventory_context for the AI direction prompt
            if not inventory_context:
                inventory_context = "Suggested products (based on best sellers):\n" + "\n".join(
                    f"- {p['name']} ({p.get('product_type', '')})" for p in stf_products
                )

    # Generate AI content — CZ gets Figma template + body copy; BUR gets template selection + direction; others get direction + SL/PH
    sl_ph_text = None
    direction_text = None
    figma_brief = None
    brand_template = None
    if generate_ai:
        if record["brand"] == "CZ" and not record.get("is_trade"):
            figma_brief = generate_cz_email_brief(record, inventory_context=inventory_context)
            sl_ph_text = generate_cz_sl_ph(record)
        elif record["brand"] == "TI" and not record.get("is_trade"):
            figma_brief = generate_ti_email_brief(record, during_sale=during_sale)
            sl_ph_text = generate_sl_ph(record)
        elif record["brand"] == "STF" and not record.get("is_trade"):
            figma_brief = generate_stf_email_brief(
                record, during_sale=during_sale, inventory_context=inventory_context
            )
            sl_ph_text = generate_sl_ph(record)
        elif record["brand"] == "BUR" and not record.get("is_trade"):
            figma_brief = generate_bw_email_brief(
                record, during_sale=during_sale, inventory_context=inventory_context
            )
            sl_ph_text = generate_sl_ph(record)
        elif record["brand"] == "HAV" and not record.get("is_trade"):
            figma_brief = generate_hav_email_brief(record, during_sale=during_sale)
            sl_ph_text = generate_sl_ph(record)
        else:
            if record.get("is_trade"):
                brand_template = pick_trade_template(record)
            elif record["brand"] == "ID":
                brand_template = pick_id_template(record)
            direction_text = generate_email_direction(record, inventory_context=inventory_context)
            if record["brand"] == "ID":
                sl_ph_text = generate_id_sl_ph(record)
            else:
                sl_ph_text = generate_sl_ph(record)

    needs_copy = record["brand"] in ("CZ", "STF", "TI", "BUR", "HAV") and not record.get("is_trade")
    custom_fields = {
        FIELD_BRAND: BRAND_OPTIONS.get(record["brand"]),
        FIELD_CHANNEL: CHANNEL_EMAIL,
        FIELD_TYPE: TYPE_BATCH_BLAST,
        FIELD_TASK_STATUS: STATUS_AWAITING_COPY if needs_copy else STATUS_AWAITING_DESIGN,
    }
    # Trade tasks: set the "Trade Brand" field to Interior Define
    if record["brand"] == "TRADE":
        custom_fields[FIELD_TRADE_BRAND] = TRADE_BRAND_INTERIOR_DEFINE
    if category_gid:
        custom_fields[FIELD_CATEGORY] = category_gid
    # HAV email tasks: set Audience (DPS/MP split) and Segment (Full File / Engaged)
    if record["brand"] == "HAV":
        audience_gid = pick_hav_audience_gid(record)
        if audience_gid:
            custom_fields[FIELD_AUDIENCE] = audience_gid
        custom_fields[FIELD_SEGMENT] = pick_hav_segment(record)
    # Same-day PM send: propagate send_time assigned by _assign_same_day_send_times
    if record.get("send_time"):
        custom_fields[FIELD_SEND_TIME] = record["send_time"]

    # Re-run send: resolve the source campaign so the brief links it. The Asana
    # permalink stays unresolved on this path (no Asana search here) — the campaign
    # link and the source's name/date still land in the brief.
    task_name = record["story"]
    resend_source = resolve_resend_source(record, task_name, record["brand"], record["date"])

    payload = {
        "data": {
            "name": task_name,
            "due_on": record["date"],
            "projects": [ASANA_PROJECT_GID],
            "notes": build_description(record, sl_ph_text, direction_text, figma_brief, during_sale,
                                       sale_name=sale_name, sale_discount=sale_discount,
                                       brand_template=brand_template,
                                       products_text=stf_products_text,
                                       resend_source=resend_source,
                                       task_name=task_name),
            "custom_fields": custom_fields,
        }
    }

    result = asana_request("POST", "tasks", json_data=payload)
    if result:
        task_gid = result.get("gid")
        # Patch html_notes so field labels render in bold (plain notes → no formatting)
        if task_gid:
            html_notes = build_html_notes(
                record, sl_ph_text, direction_text, figma_brief, during_sale,
                sale_name=sale_name, sale_discount=sale_discount,
                brand_template=brand_template,
                products_text=stf_products_text,
                resend_source=resend_source,
                task_name=task_name,
            )
            if html_notes:
                asana_request(
                    "PUT", f"tasks/{task_gid}",
                    json_data={"data": {"html_notes": html_notes}},
                )
        return task_gid
    return None


def delete_asana_task(task_gid: str) -> bool:
    """Delete an Asana task by GID."""
    result = asana_request("DELETE", f"tasks/{task_gid}")
    return result is not None


# ---------------------------------------------------------------------------
# Mapping file (dedup tracking)
# ---------------------------------------------------------------------------

def load_mapping() -> Dict[str, str]:
    """Load the dedup mapping file. Returns {dedup_key: asana_gid}."""
    if not MAPPING_FILE.exists():
        return {}
    with open(MAPPING_FILE) as f:
        data = yaml.safe_load(f) or {}
    return data.get("tasks", {})


def save_mapping(mapping: Dict[str, str]):
    """Save the dedup mapping file."""
    MAPPING_FILE.parent.mkdir(parents=True, exist_ok=True)
    with open(MAPPING_FILE, "w") as f:
        yaml.dump({
            "tasks": mapping,
            "last_updated": datetime.now().isoformat(),
        }, f, default_flow_style=False, sort_keys=False)


# ---------------------------------------------------------------------------
# CLI & main
# ---------------------------------------------------------------------------

def filter_records(records: List[Dict[str, str]], brand: Optional[str],
                   month: Optional[int]) -> List[Dict[str, str]]:
    """Filter records by brand and/or month."""
    filtered = records
    if brand:
        brand_upper = brand.upper()
        filtered = [r for r in filtered if r["brand"] == brand_upper]
    if month:
        filtered = [r for r in filtered
                    if datetime.strptime(r["date"], "%Y-%m-%d").month == month]
    return filtered


def print_preview(records: List[Dict[str, str]]):
    """Print a preview table of records."""
    if not records:
        print("No tasks to preview.")
        return

    print(f"\n{'#':>4}  {'Brand':<6} {'Date':<12} {'Category':<18} {'Story'}")
    print(f"{'—'*4}  {'—'*6} {'—'*12} {'—'*18} {'—'*40}")
    for i, r in enumerate(records, 1):
        cat = infer_category(r["story"], r["source_tab"])
        story_display = r["story"][:60] + ("..." if len(r["story"]) > 60 else "")
        print(f"{i:>4}  {r['brand']:<6} {r['date']:<12} {cat:<18} {story_display}")
    print(f"\nTotal: {len(records)} tasks")


def validate_hav_weekend_coverage(records: List[Dict[str, str]]) -> List[str]:
    """Flag any ISO week of HAV sends with no Saturday/Sunday coverage for an audience.

    Confirmed root cause (2026-07-31): a month+ of Mina's HAV briefing shipped with
    zero weekend sends because the source Google Sheet simply had no Sat/Sun rows
    filled in that month — nothing downstream (parse_tab, the HAV prompt/parse pair,
    _assign_same_day_send_times) has any weekday awareness, so a sheet gap like that
    passes through silently. This check can't fix a missing sheet row, but it makes
    the gap loud and visible before tasks are created instead of only being caught
    after the fact.

    Each audience (DPS, MP) needs its own weekend coverage — a combined "DPS and MP:"
    send, or any send whose audience prefix can't be determined, counts toward both.
    Returns a list of human-readable warnings; empty list means every week is covered.
    This is advisory, not a hard block: a partial-month pull (e.g. starting mid-week)
    legitimately won't have full coverage for its first/last week.
    """
    hav_records = [r for r in records if r.get("brand") == "HAV" and not r.get("is_trade")]
    if not hav_records:
        return []

    weeks: Dict[Tuple[int, int], List[Tuple[Any, Dict[str, str]]]] = {}
    for r in hav_records:
        d = datetime.strptime(r["date"], "%Y-%m-%d").date()
        key = d.isocalendar()[:2]  # (iso_year, iso_week)
        weeks.setdefault(key, []).append((d, r))

    warnings = []
    for key in sorted(weeks.keys()):
        entries = weeks[key]
        weekend_entries = [(d, r) for d, r in entries if d.isoweekday() in (6, 7)]

        covered = set()
        for _, r in weekend_entries:
            aud = _hav_infer_audience(r.get("story", ""))
            if aud in ("both", ""):
                covered.update({"DPS", "MP"})
            else:
                covered.add(aud)

        missing = {"DPS", "MP"} - covered
        if not missing:
            continue

        week_start = min(d for d, _ in entries)
        week_start -= timedelta(days=week_start.isoweekday() - 1)  # Monday of that ISO week
        week_label = week_start.strftime("%b %d")

        if not weekend_entries:
            warnings.append(f"Week of {week_label}: NO Saturday or Sunday HAV send scheduled at all.")
        else:
            warnings.append(
                f"Week of {week_label}: weekend HAV send missing for audience(s): "
                f"{', '.join(sorted(missing))}."
            )

    return warnings


# Sale windows shorter than this (Flash Sales, EA-only, most Extensions) don't
# historically get an "Items In Your Design" send — only the longer flagship
# events do (April Reset, Memorial Day Event, Fourth of July Event, Summer Sale,
# Labor Day Event, Black Friday Event, End of Year Sale, etc.).
_HAV_MAJOR_SALE_MIN_DAYS = 8

_ITEMS_IN_YOUR_DESIGN_RE = re.compile(
    r"items\s+in\s+your\s+design.*on\s+sale", re.IGNORECASE
)


def validate_hav_items_in_design_coverage(records: List[Dict[str, str]]) -> List[str]:
    """Flag any major HAV/MP (CONV) sale window with no "Items In Your Design Are On
    Sale" send planned.

    Confirmed root cause (2026-08-26): this recurring MP/CONV send (cart-callout —
    "the items already in your design are on sale, don't miss out") ran regularly
    through 2026-07-04 (during the Fourth of July Event) and then silently stopped —
    three subsequent major sale windows (Summer Sale, Flash Sale, Labor Day Event)
    went by with no instance briefed, and nothing in the pipeline would have caught
    it since story content isn't otherwise validated against the promo calendar.

    Only "major" sale windows count (see `_HAV_MAJOR_SALE_MIN_DAYS`) — short Flash
    Sales, EA-only windows, and most Extensions never got this send historically, so
    flagging those would be noise. Matches on story/notes text via
    `_ITEMS_IN_YOUR_DESIGN_RE`, not on Braze naming, since this check runs on raw
    sheet records before any campaign name is built.

    Returns a list of human-readable warnings; empty list means every major sale
    window overlapping this batch already has a matching send. Advisory only, same
    caveat as `validate_hav_weekend_coverage`: a partial pull that only grazes the
    edge of a sale window may not need one, so use judgment for edge dates.
    """
    hav_conv_records = [
        r
        for r in records
        if r.get("brand") == "HAV"
        and not r.get("is_trade")
        and _hav_infer_audience(r.get("story", "")) in ("MP", "both", "")
    ]
    if not hav_conv_records:
        return []

    batch_dates = [datetime.strptime(r["date"], "%Y-%m-%d").date() for r in hav_conv_records]
    batch_start, batch_end = min(batch_dates), max(batch_dates)

    from scripts.utils.sale_matcher import load_sale_schedules

    sales = load_sale_schedules()
    warnings = []
    for sale in sales:
        if sale.get("brand") != "HAV" or sale.get("havenly_audience") != "CONV":
            continue
        try:
            sale_start = datetime.strptime(str(sale["start_date"]), "%Y-%m-%d").date()
            sale_end = datetime.strptime(str(sale["end_date"]), "%Y-%m-%d").date()
        except (KeyError, ValueError):
            continue
        if (sale_end - sale_start).days + 1 < _HAV_MAJOR_SALE_MIN_DAYS:
            continue
        # Overlap between this sale window and the batch's date range
        overlap_start = max(sale_start, batch_start)
        overlap_end = min(sale_end, batch_end)
        if overlap_start > overlap_end:
            continue

        has_send = any(
            overlap_start <= datetime.strptime(r["date"], "%Y-%m-%d").date() <= overlap_end
            and _ITEMS_IN_YOUR_DESIGN_RE.search(f"{r.get('story', '')} {r.get('notes', '')}")
            for r in hav_conv_records
        )
        if not has_send:
            warnings.append(
                f'{sale.get("name", "Sale")} ({sale_start.strftime("%b %d")}–{sale_end.strftime("%b %d")}): '
                f'no "Items In Your Design Are On Sale" MP send planned.'
            )

    return warnings


def main():
    parser = argparse.ArgumentParser(
        description="Create Asana tasks from master marketing calendar"
    )
    parser.add_argument("--dry-run", action="store_true",
                        help="Preview tasks without creating them")
    parser.add_argument("--brand", type=str,
                        help="Filter to one brand (HAV, CZ, ID, BUR, TI, STF, TRADE)")
    parser.add_argument("--tab", type=str,
                        help="Process only one tab (HAV, CZ, 'ID + BUR', 'TI + SF', TRADE)")
    parser.add_argument("--month", type=int,
                        help="Filter to one month (1-12)")
    parser.add_argument("--start-row", type=int, default=0,
                        help="Start parsing from this row (0-indexed)")
    parser.add_argument("--delete", action="store_true",
                        help="Delete previously created tasks (respects --brand/--month)")
    parser.add_argument("--skip-ai", "--skip-sl-ph", action="store_true",
                        dest="skip_ai",
                        help="Skip AI-generated content (direction + SL/PH options)")
    parser.add_argument("--skip-inventory", action="store_true",
                        help="Skip inventory lookup (don't inject product data into AI prompts)")

    args = parser.parse_args()

    # --- Delete mode ---
    if args.delete:
        mapping = load_mapping()
        if not mapping:
            print("No tasks in mapping file to delete.")
            return

        # Filter mapping entries by brand/month if specified
        to_delete = {}
        for key, gid in mapping.items():
            parts = key.split("|")
            if len(parts) < 2:
                continue
            rec_brand, rec_date = parts[0], parts[1]

            if args.brand and rec_brand != args.brand.upper():
                continue
            if args.month:
                try:
                    rec_month = datetime.strptime(rec_date, "%Y-%m-%d").month
                    if rec_month != args.month:
                        continue
                except ValueError:
                    continue
            to_delete[key] = gid

        if not to_delete:
            print("No matching tasks to delete.")
            return

        print(f"Deleting {len(to_delete)} tasks...")
        if args.dry_run:
            for key, gid in to_delete.items():
                print(f"  Would delete: {key} (Asana GID: {gid})")
            return

        deleted = 0
        for key, gid in to_delete.items():
            if delete_asana_task(gid):
                del mapping[key]
                deleted += 1
                print(f"  Deleted: {key}")
            else:
                print(f"  Failed to delete: {key} (GID: {gid})")
            time.sleep(0.5)

        save_mapping(mapping)
        print(f"\nDeleted {deleted}/{len(to_delete)} tasks.")
        return

    # --- Fetch & parse ---
    tabs_to_process = TAB_CONFIGS.keys()
    if args.tab:
        if args.tab not in TAB_CONFIGS:
            print(f"Error: Unknown tab '{args.tab}'")
            print(f"Available tabs: {', '.join(TAB_CONFIGS.keys())}")
            sys.exit(1)
        tabs_to_process = [args.tab]

    all_records = []
    for tab_name in tabs_to_process:
        print(f"Fetching tab: {tab_name}...")
        rows, hyperlinks = fetch_sheet_tab(tab_name)
        if not rows:
            print(f"  No data found in tab '{tab_name}'")
            continue

        if args.start_row > 0:
            rows = rows[args.start_row:]
            hyperlinks = hyperlinks[args.start_row:] if hyperlinks else []

        records = parse_tab(tab_name, rows, hyperlinks)
        print(f"  Parsed {len(records)} records")
        all_records.extend(records)

    # Filter
    all_records = filter_records(all_records, args.brand, args.month)

    # Weekend-coverage safety net (HAV only) — a full month of sends with zero
    # Sat/Sun coverage has shipped before because the source sheet had no weekend
    # rows and nothing else in the pipeline checks for this. Warn loudly, don't block.
    weekend_warnings = validate_hav_weekend_coverage(all_records)
    if weekend_warnings:
        print("\n[WARN] HAV weekend coverage gap(s) detected — confirm with the sheet before proceeding:")
        for w in weekend_warnings:
            print(f"  [WARN] {w}")
        print()

    # Major-sale content safety net (HAV only) — "Items In Your Design Are On Sale"
    # (MP/CONV) ran during every flagship HAV sale for over a year, then silently
    # stopped after 2026-07-04 with nothing catching the gap. Warn loudly, don't block.
    items_in_design_warnings = validate_hav_items_in_design_coverage(all_records)
    if items_in_design_warnings:
        print('\n[WARN] HAV major-sale "Items In Your Design Are On Sale" gap(s) detected — confirm with the sheet owner before proceeding:')
        for w in items_in_design_warnings:
            print(f"  [WARN] {w}")
        print()

    # Dedup against existing mapping
    mapping = load_mapping()
    new_records = [r for r in all_records if dedup_key(r) not in mapping]
    skipped = len(all_records) - len(new_records)
    if skipped:
        print(f"\nSkipping {skipped} already-created tasks.")

    # --- Dry run ---
    if args.dry_run:
        print_preview(new_records)
        return

    # --- Create tasks ---
    if not new_records:
        print("\nNo new tasks to create.")
        return

    generate_ai = not args.skip_ai
    if generate_ai and not os.environ.get("ANTHROPIC_API_KEY"):
        print("\nNote: ANTHROPIC_API_KEY not set — skipping AI content generation.")
        print("Add to .env to enable: ANTHROPIC_API_KEY=your_key_here")
        generate_ai = False
    elif generate_ai:
        print("\nGenerating email direction + SL/PH options for each task (via Claude API)...")

    # Load inventory data per brand (if enabled and AI is active)
    inventory_by_brand: Dict[str, Optional[str]] = {}
    if generate_ai and not args.skip_inventory:
        try:
            from scripts.utils.inventory_checker import (
                get_top_stocked_products,
                format_inventory_for_prompt,
                close_all_clients as close_inventory_clients,
                SUPPORTED_BRANDS as INVENTORY_BRANDS,
            )
            # Pre-load inventory for each brand that appears in our records
            brands_needed = set(r["brand"] for r in new_records)
            for brand in brands_needed:
                if brand in INVENTORY_BRANDS:
                    try:
                        products = get_top_stocked_products(brand, limit=15)
                        inventory_by_brand[brand] = format_inventory_for_prompt(products)
                        print(f"  Loaded inventory for {brand}: {len(products)} products")
                    except Exception as e:
                        print(f"  Warning: Could not load inventory for {brand}: {e}")
                        inventory_by_brand[brand] = None
        except ImportError:
            print("  Note: inventory_checker not available — skipping inventory data.")
        except Exception as e:
            print(f"  Warning: Inventory loading failed: {e}")

    # Assign PM send times to same-day pairs before creation
    _assign_same_day_send_times(new_records, mapping)

    print(f"\nCreating {len(new_records)} tasks in Asana...")
    created = 0
    failed = 0

    try:
        for i, record in enumerate(new_records, 1):
            try:
                inv_context = inventory_by_brand.get(record["brand"])
                gid = create_asana_task(record, generate_ai=generate_ai,
                                        inventory_context=inv_context)
                if gid:
                    mapping[dedup_key(record)] = gid
                    created += 1
                    cat = infer_category(record["story"], record["source_tab"])
                    print(f"  [{i}/{len(new_records)}] Created: {record['brand']} "
                          f"{record['date']} — {record['story'][:50]} ({cat})")
                else:
                    failed += 1
                    print(f"  [{i}/{len(new_records)}] FAILED: {record['brand']} "
                          f"{record['date']} — {record['story'][:50]}")
            except Exception as e:
                failed += 1
                print(f"  [{i}/{len(new_records)}] ERROR: {e}")

            time.sleep(0.5)  # Rate limiting
    except KeyboardInterrupt:
        print("\n\nInterrupted! Saving progress...")
    finally:
        save_mapping(mapping)

    print(f"\nDone. Created: {created}, Failed: {failed}")

    # Clean up inventory connections
    if inventory_by_brand:
        try:
            close_inventory_clients()
        except Exception:
            pass


if __name__ == "__main__":
    main()
