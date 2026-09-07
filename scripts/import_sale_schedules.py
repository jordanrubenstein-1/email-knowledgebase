#!/usr/bin/env python3
"""
Import sale/promo schedules from the Asana Promo Tracking Board or local files.

Supports:
- Auto-sync from Asana Promo Tracking Board (recommended; requires ASANA_ACCESS_TOKEN)
- Google Sheets via API (legacy; requires GOOGLE_SHEETS_API_KEY or service account)
- Local CSV files
- Local Excel files (.xlsx, .xls)

Usage:
    # Auto-sync from Asana Promo Tracking Board (recommended)
    uv run python scripts/import_sale_schedules.py --source asana

    # Sync with dry run (preview without writing)
    uv run python scripts/import_sale_schedules.py --source asana --dry-run

    # From Google Sheets (legacy; requires API setup)
    uv run python scripts/import_sale_schedules.py --source sheets --url "https://docs.google.com/spreadsheets/d/..."

    # From local CSV
    uv run python scripts/import_sale_schedules.py --source csv --file path/to/sales.csv

    # From local Excel
    uv run python scripts/import_sale_schedules.py --source excel --file path/to/sales.xlsx --sheet "2024-25 Sale One-Sheet"
"""

import os
import sys
import argparse
import re
from pathlib import Path
from datetime import datetime
from typing import List, Dict, Any, Optional, Tuple

from dotenv import load_dotenv
import yaml
try:
    import pandas as pd
    HAS_PANDAS = True
except ImportError:
    HAS_PANDAS = False

# Load .env from project root
load_dotenv(Path(__file__).parent.parent / ".env")

# Brand normalization mapping
BRAND_ALIASES = {
    "hav": "HAV",
    "havenly": "HAV",
    "havenly dps": "HAV",
    "havenly mkpl": "HAV",
    "havenly marketplace": "HAV",
    "cz": "CZ",
    "the citizenry": "CZ",
    "citizenry": "CZ",
    "id": "ID",
    "interior define": "ID",
    "bur": "BUR",
    "burrow": "BUR",
    "stf": "STF",
    "st. frank": "STF",
    "st frank": "STF",
    "ti": "TI",
    "the inside": "TI",
}

# Havenly sub-brand → audience mapping.
# DPS (Design Program Services) targets pre-converted users (PC).
# Marketplace / Merch targets converted users (CONV).
HAVENLY_AUDIENCE_MAP = {
    "havenly dps": "PC",
    "havenly mkpl": "CONV",
    "havenly marketplace": "CONV",
}


def normalize_brand(brand_str: str) -> Optional[str]:
    """Normalize brand name to standard code."""
    if not brand_str:
        return None
    brand_lower = str(brand_str).strip().lower()
    return BRAND_ALIASES.get(brand_lower, brand_lower.upper())


def parse_date(date_str: Any) -> Optional[str]:
    """Parse various date formats and return ISO date string (YYYY-MM-DD)."""
    if not date_str:
        return None
    
    # Handle datetime objects
    if isinstance(date_str, datetime):
        return date_str.strftime("%Y-%m-%d")
    
    date_str = str(date_str).strip()
    if not date_str or date_str.lower() in ["", "nan", "none", "n/a"]:
        return None
    
    # Try common date formats
    formats = [
        "%Y-%m-%d",
        "%m/%d/%Y",
        "%m-%d-%Y",
        "%d/%m/%Y",
        "%d-%m-%Y",
        "%Y/%m/%d",
    ]
    
    for fmt in formats:
        try:
            dt = datetime.strptime(date_str, fmt)
            return dt.strftime("%Y-%m-%d")
        except ValueError:
            continue
    
    # Try parsing with dateutil if available
    try:
        from dateutil import parser
        dt = parser.parse(date_str)
        return dt.strftime("%Y-%m-%d")
    except (ImportError, ValueError):
        pass
    
    print(f"Warning: Could not parse date: {date_str}")
    return None


def create_sale_id(brand: str, name: str, start_date: str) -> str:
    """Create a unique sale ID from brand, name, and date."""
    # Clean name for ID
    clean_name = re.sub(r'[^a-z0-9]+', '-', name.lower())
    clean_name = re.sub(r'^-+|-+$', '', clean_name)
    return f"{brand.lower()}-{clean_name}-{start_date}"


def read_google_sheets(url: str, sheet_name: Optional[str] = None, start_row: int = 1) -> List[Dict[str, Any]]:
    """Read data from Google Sheets using API or CSV export."""
    try:
        import requests
    except ImportError:
        print("Error: requests library required for Google Sheets API")
        sys.exit(1)
    
    # Extract sheet ID from URL
    sheet_id_match = re.search(r'/spreadsheets/d/([a-zA-Z0-9-_]+)', url)
    if not sheet_id_match:
        print(f"Error: Invalid Google Sheets URL: {url}")
        sys.exit(1)
    
    sheet_id = sheet_id_match.group(1)
    
    # Try API key method first
    api_key = os.environ.get("GOOGLE_SHEETS_API_KEY")
    if api_key:
        # Get sheet metadata to find sheet ID
        metadata_url = f"https://sheets.googleapis.com/v4/spreadsheets/{sheet_id}?key={api_key}"
        try:
            resp = requests.get(metadata_url)
            resp.raise_for_status()
            metadata = resp.json()
            
            # Find sheet by name or use first sheet
            target_sheet_id = None
            for sheet in metadata.get("sheets", []):
                if sheet_name and sheet["properties"]["title"] == sheet_name:
                    target_sheet_id = sheet["properties"]["sheetId"]
                    break
                elif not sheet_name and not target_sheet_id:
                    target_sheet_id = sheet["properties"]["sheetId"]
            
            if not target_sheet_id:
                print(f"Error: Sheet '{sheet_name}' not found")
                sys.exit(1)
            
            # Get data
            range_name = f"{sheet_name or metadata['sheets'][0]['properties']['title']}!A{start_row}:Z"
            data_url = f"https://sheets.googleapis.com/v4/spreadsheets/{sheet_id}/values/{range_name}?key={api_key}"
            resp = requests.get(data_url)
            resp.raise_for_status()
            data = resp.json()
            
            if not data.get("values"):
                return []
            
            # Parse into list of dicts
            headers = [h.lower().strip() for h in data["values"][0]]
            rows = []
            for row in data["values"][1:]:
                if not any(row):  # Skip empty rows
                    continue
                row_dict = {}
                for i, header in enumerate(headers):
                    row_dict[header] = row[i] if i < len(row) else ""
                rows.append(row_dict)
            
            return rows
        except Exception as e:
            print(f"Error reading Google Sheets via API: {e}")
            print("Falling back to CSV export method...")
    
    # Fallback: CSV export
    csv_url = f"https://docs.google.com/spreadsheets/d/{sheet_id}/export?format=csv&gid=0"
    try:
        resp = requests.get(csv_url)
        resp.raise_for_status()
        import csv
        from io import StringIO
        
        reader = csv.DictReader(StringIO(resp.text))
        return [dict(row) for row in reader]
    except Exception as e:
        print(f"Error reading Google Sheets CSV export: {e}")
        sys.exit(1)


# ---------------------------------------------------------------------------
# Promo Calendar sync helpers
# ---------------------------------------------------------------------------

# Known tab name patterns for the Promo Calendar Google Sheet.
# Tabs matching these patterns (with a year >= current year) are synced.
SYNC_TAB_PATTERNS = [
    r"^1H\s+(\d{4})$",           # "1H 2026"
    r"^2H\s+(\d{4})$",           # "2H 2026"
    r"^(\d{4})\s+Sale One-Sheet", # "2026 Sale One-Sheet"
    r"^BFCM\s+(\d{4})$",         # "BFCM 2026"
    r"^MDW\s+(\d{4})$",          # "MDW 2026"
    r"^JUN-AUG\s+(\d{4})$",      # "JUN-AUG 2025"
]


def _infer_year_from_tab(tab_name: str) -> Optional[int]:
    """Extract the year from a tab name, or None if no year found."""
    for pattern in SYNC_TAB_PATTERNS:
        m = re.search(pattern, tab_name, re.IGNORECASE)
        if m:
            return int(m.group(1))
    # Fallback: look for any 4-digit year in the name
    m = re.search(r"(\d{4})", tab_name)
    if m:
        return int(m.group(1))
    return None


def discover_sync_tabs(sheet_id: str, api_key: str) -> List[Tuple[str, int]]:
    """Discover tabs in the Promo Calendar sheet that cover current/future dates.

    Returns a list of (tab_name, inferred_year) tuples, sorted by year.
    Only tabs whose inferred year >= current year are included.
    """
    try:
        import requests as _requests
    except ImportError:
        print("Error: requests library required for Google Sheets API")
        sys.exit(1)

    current_year = datetime.now().year

    # Fetch sheet metadata to get all tab names
    metadata_url = (
        f"https://sheets.googleapis.com/v4/spreadsheets/{sheet_id}"
        f"?key={api_key}&fields=sheets.properties.title"
    )
    try:
        resp = _requests.get(metadata_url)
        resp.raise_for_status()
    except Exception as e:
        print(f"Error fetching sheet metadata: {e}")
        sys.exit(1)

    all_tabs = [
        sheet["properties"]["title"]
        for sheet in resp.json().get("sheets", [])
    ]

    matched: List[Tuple[str, int]] = []
    for tab_name in all_tabs:
        year = _infer_year_from_tab(tab_name)
        if year is None:
            continue
        if year < current_year:
            continue
        # Verify it matches one of our known patterns (not random tabs with a year)
        for pattern in SYNC_TAB_PATTERNS:
            if re.search(pattern, tab_name, re.IGNORECASE):
                matched.append((tab_name, year))
                break

    # Sort by year, then tab name
    matched.sort(key=lambda t: (t[1], t[0]))
    return matched


def _fetch_tab_rows(sheet_id: str, api_key: str, tab_name: str) -> List[List[str]]:
    """Fetch all rows from a single tab as lists of cell strings."""
    try:
        import requests as _requests
    except ImportError:
        print("Error: requests library required")
        sys.exit(1)

    range_name = _requests.utils.quote(f"'{tab_name}'!A1:Z")
    url = (
        f"https://sheets.googleapis.com/v4/spreadsheets/{sheet_id}"
        f"/values/{range_name}?key={api_key}&valueRenderOption=FORMATTED_VALUE"
    )
    resp = _requests.get(url)
    if resp.status_code != 200:
        print(f"  Warning: could not fetch tab '{tab_name}': {resp.status_code}")
        return []

    values = resp.json().get("values", [])
    return values


def parse_promo_calendar_tab(
    rows: List[List[str]],
    tab_name: str,
) -> List[Dict[str, Any]]:
    """Parse the grouped promo-calendar format used in 1H/2H/Sale-One-Sheet tabs.

    Expected column layout (0-indexed):
      A (0): Often empty or section header
      B (1): Brand name *or* sub-event name (e.g. "Pres Day Sale Extension")
      C (2): Sale name *or* date range (for continuation rows)
      D (3): Date range (for brand-header rows) *or* empty
      E (4): Discount / offer details

    Brand-header rows have a recognized brand in col B.
    Continuation rows reuse the last-seen brand.

    For Havenly, the sub-brand (DPS vs Marketplace) is preserved via
    ``havenly_audience``: PC (pre-converted, DPS) or CONV (converted, Marketplace).
    """
    year = _infer_year_from_tab(tab_name) or datetime.now().year

    sales: List[Dict[str, Any]] = []
    current_brand: Optional[str] = None
    current_havenly_audience: Optional[str] = None  # PC or CONV for HAV
    # Track the "parent" sale name established by the brand-header row
    current_sale_name: Optional[str] = None

    for row in rows:
        # Pad row to at least 5 columns
        while len(row) < 5:
            row.append("")

        col_a = str(row[0]).strip() if row[0] else ""
        col_b = str(row[1]).strip() if row[1] else ""
        col_c = str(row[2]).strip() if row[2] else ""
        col_d = str(row[3]).strip() if row[3] else ""
        col_e = str(row[4]).strip() if row[4] else ""

        # Skip empty / header rows
        if not col_b and not col_c and not col_d:
            continue
        # Skip rows that look like column headers
        if col_b.lower() in ("brand", ""):
            if col_c.lower() in ("sale name", "name of promo", "promo name", "dates", ""):
                continue

        # ---- Determine if this is a brand-header row or continuation ----
        brand_candidate = normalize_brand(col_b)
        is_brand_row = brand_candidate is not None and brand_candidate in (
            "HAV", "CZ", "ID", "BUR", "STF", "TI",
        )

        if is_brand_row:
            current_brand = brand_candidate
            # Detect Havenly sub-brand (DPS → PC, Marketplace → CONV)
            col_b_lower = col_b.lower()
            current_havenly_audience = HAVENLY_AUDIENCE_MAP.get(col_b_lower)
            # Brand-header: col C = sale name, col D = dates, col E = discount
            sale_name = col_c if col_c else col_b
            dates_str = col_d
            discount = col_e
            current_sale_name = sale_name
        else:
            # Continuation row: col B = sub-event name, col C = dates
            if not current_brand:
                continue  # No brand context yet
            sale_name = col_b if col_b else current_sale_name or f"Sale {year}"
            dates_str = col_c
            discount = col_d if col_d else col_e

        if not dates_str:
            continue

        # ---- Parse date ranges from the dates string ----
        date_ranges = _parse_dates_for_year(dates_str, year)
        if not date_ranges:
            continue

        for dr in date_ranges:
            full_name = sale_name
            if dr["label"] and dr["label"] != "general" and len(date_ranges) > 1:
                full_name = f"{sale_name} ({dr['label'].upper()})"

            sale = {
                "id": create_sale_id(current_brand, full_name, dr["start_date"]),
                "brand": current_brand,
                "name": full_name,
                "start_date": dr["start_date"],
                "end_date": dr["end_date"],
            }
            # Attach Havenly audience if applicable
            if current_brand == "HAV" and current_havenly_audience:
                sale["havenly_audience"] = current_havenly_audience

            if discount and discount.lower() not in ("", "nan", "none"):
                sale["discount"] = discount

            sales.append(sale)

    return sales


def _parse_dates_for_year(dates_str: str, year: int) -> List[Dict[str, str]]:
    """Parse date-range strings like 'Wed 2/4 - Mon 2/16' into ISO dates.

    Handles:
      - Simple ranges: "2/4 - 2/16", "Wed 2/4 - Mon 2/16"
      - Labeled ranges: "EA: 11/11 - 11/12\nMain Event: 11/13 - 12/2"
      - Full dates with year: "2/4/2026 - 2/16/2026"
    """
    if not dates_str or not isinstance(dates_str, str):
        return []

    # First try the existing multi-range parser
    ranges = parse_multiple_date_ranges(dates_str, year)
    if ranges:
        return ranges

    # Fallback: try a simple "M/D - M/D" with optional day-of-week prefixes
    pattern = r"(?:[A-Za-z]+\s+)?(\d{1,2})[/-](\d{1,2})(?:\s*-\s*(?:[A-Za-z]+\s+)?(\d{1,2})[/-](\d{1,2}))?"
    m = re.search(pattern, dates_str)
    if m:
        month1, day1 = int(m.group(1)), int(m.group(2))
        month2 = int(m.group(3)) if m.group(3) else month1
        day2 = int(m.group(4)) if m.group(4) else day1
        try:
            start = f"{year}-{month1:02d}-{day1:02d}"
            end = f"{year}-{month2:02d}-{day2:02d}"
            return [{"start_date": start, "end_date": end, "label": "general"}]
        except (ValueError, TypeError):
            pass

    return []


def sync_from_promo_calendar(dry_run: bool = False) -> List[Dict[str, Any]]:
    """Discover and parse all current/future tabs from the Promo Calendar sheet.

    Returns the list of parsed sale records.
    """
    try:
        import requests as _requests  # noqa: F811
    except ImportError:
        print("Error: requests library required. Install with: uv pip install requests")
        sys.exit(1)

    sheet_id = os.environ.get("PROMO_CALENDAR_SHEET_ID")
    api_key = os.environ.get("GOOGLE_SHEETS_API_KEY")

    if not sheet_id:
        print("Error: PROMO_CALENDAR_SHEET_ID not set in .env")
        print("Add the Promo Calendar sheet ID to .env:")
        print("  PROMO_CALENDAR_SHEET_ID=1-oyVfD7ZpYOoeVnKNFVMAc9wAeiiF-J3jmRbl3qzx5c")
        sys.exit(1)
    if not api_key:
        print("Error: GOOGLE_SHEETS_API_KEY not set in .env")
        print("Add your Google Sheets API key to .env:")
        print("  GOOGLE_SHEETS_API_KEY=your_key_here")
        print("Get one at: https://console.cloud.google.com/apis/credentials")
        sys.exit(1)

    # Step 1: discover tabs
    print("Discovering tabs in Promo Calendar sheet...")
    tabs = discover_sync_tabs(sheet_id, api_key)
    if not tabs:
        print("No current/future tabs found in the Promo Calendar sheet.")
        return []

    print(f"Found {len(tabs)} tab(s) to sync:")
    for tab_name, tab_year in tabs:
        print(f"  - {tab_name} (year {tab_year})")

    # Step 2: fetch and parse each tab
    all_sales: List[Dict[str, Any]] = []
    for tab_name, tab_year in tabs:
        print(f"\nFetching tab '{tab_name}'...")
        rows = _fetch_tab_rows(sheet_id, api_key, tab_name)
        if not rows:
            print(f"  No data in tab '{tab_name}'")
            continue

        sales = parse_promo_calendar_tab(rows, tab_name)
        print(f"  Parsed {len(sales)} sale record(s)")
        all_sales.extend(sales)

    # Deduplicate by sale ID (later tabs override earlier ones)
    deduped: Dict[str, Dict[str, Any]] = {}
    for sale in all_sales:
        deduped[sale["id"]] = sale

    result = list(deduped.values())
    print(f"\nTotal: {len(result)} unique sale record(s) from {len(tabs)} tab(s)")
    return result


# ---------------------------------------------------------------------------
# Asana sync
# ---------------------------------------------------------------------------

ASANA_PROMO_PROJECT_GID = "1213996005172086"
ASANA_BRAND_FIELD_GID = "1213996005172093"

# Asana Brand enum display name → (brand_code, havenly_audience)
_ASANA_BRAND_MAP = {
    "Havenly DPS": ("HAV", "PC"),
    "Havenly Marketplace": ("HAV", "CONV"),
    "Interior Define": ("ID", None),
    "Burrow": ("BUR", None),
    "Citizenry": ("CZ", None),
    "The Inside": ("TI", None),
    "St Frank": ("STF", None),
}


def _parse_asana_promo_task(task: Dict[str, Any]) -> Optional[Dict[str, Any]]:
    """Parse a single Asana promo task into a sale record. Returns None if incomplete."""
    start_date = task.get("start_on")
    end_date = task.get("due_on")
    if not start_date or not end_date:
        return None

    # Brand from custom field
    brand_code = None
    havenly_audience = None
    for field in task.get("custom_fields", []):
        if field.get("gid") == ASANA_BRAND_FIELD_GID:
            enum_val = field.get("enum_value") or {}
            brand_name = enum_val.get("name", "")
            mapped = _ASANA_BRAND_MAP.get(brand_name)
            if mapped:
                brand_code, havenly_audience = mapped
            break

    if not brand_code:
        return None

    task_name = task.get("name", "")
    notes = task.get("notes", "") or ""
    lines = [l.strip() for l in notes.splitlines()]

    # Sale name: look for "SALE NAME:" in notes, else strip [Brand] prefix from task name
    name = None
    for line in lines:
        m = re.search(r"SALE NAME:\s*(.+)", line, re.IGNORECASE)
        if m and m.group(1).strip():
            name = m.group(1).strip()
            break
    if not name:
        name = re.sub(r"^\[.*?\]\s*", "", task_name).strip() or task_name

    # Discount: prefer "PROMO - B2C:" line, else first substantive line that looks like an offer
    discount = ""
    for line in lines:
        m = re.search(r"PROMO\s*-\s*B2C:\s*(.+)", line, re.IGNORECASE)
        if m and m.group(1).strip():
            discount = m.group(1).strip()
            break
    if not discount:
        skip_prefixes = (
            "brand:", "for internal", "for creative", "sale name:",
            "sale date", "sale #", "surprise", "sale start", "sale end",
            "sale period", "value prop:", "code:", "pricing on site:",
        )
        for line in lines:
            if line and not any(line.lower().startswith(p) for p in skip_prefixes):
                discount = line
                break

    sale: Dict[str, Any] = {
        "brand": brand_code,
        "start_date": start_date,
        "end_date": end_date,
        "name": name,
        "discount": discount,
        "id": create_sale_id(brand_code, name, start_date),
    }
    if havenly_audience:
        sale["havenly_audience"] = havenly_audience
    return sale


def sync_from_asana(dry_run: bool = False) -> List[Dict[str, Any]]:
    """Fetch all tasks from the Asana Promo Tracking board and return sale records."""
    try:
        import requests as _requests
    except ImportError:
        print("Error: requests library required. Install with: uv pip install requests")
        sys.exit(1)

    token = os.environ.get("ASANA_ACCESS_TOKEN")
    if not token:
        print("Error: ASANA_ACCESS_TOKEN not set in .env")
        sys.exit(1)

    headers = {"Authorization": f"Bearer {token}", "Accept": "application/json"}
    base = "https://app.asana.com/api/1.0"
    fields = "name,notes,start_on,due_on,custom_fields"

    # Paginate through all project tasks
    all_tasks = []
    params: Dict[str, Any] = {"opt_fields": fields, "limit": 100}
    url = f"{base}/projects/{ASANA_PROMO_PROJECT_GID}/tasks"
    while url:
        resp = _requests.get(url, headers=headers, params=params)
        if resp.status_code != 200:
            print(f"Error fetching Asana tasks: {resp.status_code} {resp.text}")
            sys.exit(1)
        body = resp.json()
        all_tasks.extend(body.get("data", []))
        next_page = body.get("next_page")
        if next_page and next_page.get("offset"):
            params = {"opt_fields": fields, "limit": 100, "offset": next_page["offset"]}
        else:
            url = None

    print(f"Fetched {len(all_tasks)} tasks from Asana promo project")

    sales = []
    skipped = 0
    for task in all_tasks:
        sale = _parse_asana_promo_task(task)
        if sale:
            sales.append(sale)
        else:
            skipped += 1

    if skipped:
        print(f"Skipped {skipped} tasks (missing brand or dates)")

    # Deduplicate by ID
    deduped = {s["id"]: s for s in sales}
    result = list(deduped.values())
    print(f"Parsed {len(result)} unique sale record(s) from Asana")
    return result


def read_csv_file(file_path: Path, start_row: int = 0) -> List[Dict[str, Any]]:
    """Read data from CSV file."""
    try:
        import csv
    except ImportError:
        print("Error: csv module required (should be built-in)")
        sys.exit(1)
    
    rows = []
    with open(file_path, 'r', encoding='utf-8') as f:
        reader = csv.DictReader(f)
        # Skip rows before start_row
        for i, row in enumerate(reader):
            if i < start_row:
                continue
            rows.append(dict(row))
    
    return rows


def read_excel_file(file_path: Path, sheet_name: Optional[str] = None, start_row: int = 0) -> List[Dict[str, Any]]:
    """Read data from Excel file."""
    try:
        import pandas as pd
    except ImportError:
        print("Error: pandas library required for Excel files. Install with: uv pip install pandas openpyxl")
        sys.exit(1)
    
    try:
        # Read Excel file
        excel_file = pd.ExcelFile(file_path)
        
        # Select sheet
        if sheet_name:
            if sheet_name not in excel_file.sheet_names:
                print(f"Error: Sheet '{sheet_name}' not found. Available sheets: {excel_file.sheet_names}")
                sys.exit(1)
            df = pd.read_excel(excel_file, sheet_name=sheet_name, header=0)
        else:
            df = pd.read_excel(excel_file, header=0)
        
        # Skip rows before start_row
        if start_row > 0:
            df = df.iloc[start_row:]
        
        # Convert to list of dicts
        # Don't replace NaT/NA to preserve datetime objects
        return df.to_dict('records')
    except Exception as e:
        print(f"Error reading Excel file: {e}")
        sys.exit(1)


def parse_sale_row(row: Dict[str, Any], expected_columns: Dict[str, str]) -> Optional[Dict[str, Any]]:
    """Parse a single row into a sale record."""
    # Handle both string keys (column names) and integer keys (column indices)
    def get_value(key_pattern):
        """Get value from row matching key pattern (case-insensitive)."""
        for key, value in row.items():
            key_str = str(key).lower()
            if key_pattern.lower() in key_str:
                return value
        return None
    
    # Convert row to list for easier indexing (pandas gives us integer indices)
    values_list = list(row.values()) if isinstance(row, dict) else row
    
    # Try to find brand - check column 1 (index 1) which is typically BRAND column
    brand = None
    if len(values_list) > 1:
        brand_value = values_list[1]
        if brand_value:
            brand = normalize_brand(str(brand_value))
    
    # Also check if any value looks like a brand code
    if not brand:
        for value in values_list:
            if value and isinstance(value, str):
                normalized = normalize_brand(value)
                if normalized and normalized in ["HAV", "CZ", "ID", "BUR", "STF", "TI"]:
                    brand = normalized
                    break
    
    if not brand:
        return None
    
    if not brand:
        return None
    
    # Extract other fields
    sale_data = {"brand": brand}
    
    # Find and parse dates - dates are typically in column 2 (index 2)
    # Handle multiple date ranges (e.g., "EA: 11/11 - 11/12\nMain Event: 11/13 - 12/2")
    start_date = None
    end_date = None
    
    # Try to infer year from context (assume 2025 for 2024-25 sheet, 2026 for 1H 2026)
    year = 2025  # Default, can be overridden
    
    # Check column 2 first (where dates typically are)
    dates_value = None
    if len(values_list) > 2:
        dates_value = values_list[2]
    
    # Also check all values for date patterns
    all_date_values = [dates_value] if dates_value else []
    all_date_values.extend([v for v in values_list if v and isinstance(v, str) and ('/' in str(v) or '-' in str(v))])
    
    for value in all_date_values:
        if not value or not isinstance(value, str):
            continue
        
        value_str = str(value).strip()
        
        # First, look for "Main Event" date range (preferred)
        main_event_pattern = r'Main Event[:\s]*(\d{1,2})[/-](\d{1,2})\s*-\s*(\d{1,2})[/-](\d{1,2})'
        main_match = re.search(main_event_pattern, value_str, re.IGNORECASE)
        if main_match:
            month1, day1, month2, day2 = main_match.groups()
            try:
                start_date = f"{year}-{int(month1):02d}-{int(day1):02d}"
                end_date = f"{year}-{int(month2):02d}-{int(day2):02d}"
                break  # Found Main Event, use it
            except (ValueError, TypeError):
                continue
        
        # If no Main Event, look for EA or general date ranges
        if not start_date:
            # Try EA pattern: "Public EA: 11/11 - 11/12" or "EA: 11/11 - 11/12"
            ea_pattern = r'(?:Public\s+)?EA[:\s]*(\d{1,2})[/-](\d{1,2})\s*-\s*(\d{1,2})[/-](\d{1,2})'
            ea_match = re.search(ea_pattern, value_str, re.IGNORECASE)
            if ea_match:
                month1, day1, month2, day2 = ea_match.groups()
                try:
                    start_date = f"{year}-{int(month1):02d}-{int(day1):02d}"
                    end_date = f"{year}-{int(month2):02d}-{int(day2):02d}"
                    # Don't break - continue to see if there's a Main Event
                except (ValueError, TypeError):
                    continue
        
        # If still no date, try general pattern: "8/7 - 9/2" or "Thu 8/7 - Wed 8/13" or "Fri 11/15 - Tue 12/3"
        if not start_date:
            # Pattern that handles day names: "Fri 11/15 - Tue 12/3" or "11/15 - 12/3"
            date_range_pattern = r'(?:[A-Za-z]+\s+)?(\d{1,2})[/-](\d{1,2})(?:\s*-\s*(?:[A-Za-z]+\s+)?(\d{1,2})[/-](\d{1,2}))?'
            match = re.search(date_range_pattern, value_str)
            if match:
                month1, day1 = match.groups()[:2]
                month2, day2 = match.groups()[2:] if match.groups()[2] else (None, None)
                try:
                    start_date = f"{year}-{int(month1):02d}-{int(day1):02d}"
                    if month2 and day2:
                        end_date = f"{year}-{int(month2):02d}-{int(day2):02d}"
                    else:
                        end_date = start_date
                    # Don't break - continue to see if there's a Main Event or EA
                except (ValueError, TypeError):
                    continue
    
    # Fallback: try explicit date columns or datetime objects
    if not start_date:
        # Check if column 0 or column 2 are datetime objects
        if len(values_list) > 0:
            col0_value = values_list[0]
            if isinstance(col0_value, (pd.Timestamp, datetime)) if HAS_PANDAS else isinstance(col0_value, datetime):
                try:
                    start_date = col0_value.strftime("%Y-%m-%d")
                except:
                    pass
        
        if not start_date and len(values_list) > 2:
            col2_value = values_list[2]
            if isinstance(col2_value, (pd.Timestamp, datetime)) if HAS_PANDAS else isinstance(col2_value, datetime):
                try:
                    start_date = col2_value.strftime("%Y-%m-%d")
                    # Check if there's an end date in a nearby column
                    if len(values_list) > 3:
                        col3_value = values_list[3]
                        if isinstance(col3_value, (pd.Timestamp, datetime)) if HAS_PANDAS else isinstance(col3_value, datetime):
                            try:
                                end_date = col3_value.strftime("%Y-%m-%d")
                            except:
                                pass
                except:
                    pass
        
        # Also try parsing from dict keys
        if isinstance(row, dict):
            for key, value in row.items():
                key_str = str(key).lower()
                if "start" in key_str and "date" in key_str:
                    start_date = parse_date(value)
                elif "end" in key_str and "date" in key_str:
                    end_date = parse_date(value)
                elif "date" in key_str and not start_date:
                    start_date = parse_date(value)
    
    if not start_date:
        return None  # Must have at least start date
    
    sale_data["start_date"] = start_date
    sale_data["end_date"] = end_date or start_date
    
    if not start_date:
        return None  # Must have at least start date
    
    sale_data["start_date"] = start_date
    sale_data["end_date"] = end_date or start_date
    
    # Find sale name - usually in column 3 (index 3) which is "NAME OF PROMO"
    name = None
    if len(values_list) > 3:
        # Column 3 is typically the sale name
        potential_name = values_list[3]
        if potential_name and isinstance(potential_name, str):
            name = str(potential_name).strip()
            if name and name.lower() not in ["", "nan", "none", "n/a"]:
                # Check if it's actually a date range, skip if so
                if not re.search(r'\d{1,2}[/-]\d{1,2}', name):
                    pass  # Good name
                else:
                    name = None
    
    # Fallback: check column names/indices
    if not name:
        for i, value in enumerate(values_list):
            if value and isinstance(value, str):
                value_str = str(value).strip()
                # Skip if it looks like a date or brand
                if not re.search(r'\d{1,2}[/-]\d{1,2}', value_str) and value_str not in ["HAV", "CZ", "ID", "BUR", "STF", "TI", "Interior Define"]:
                    if len(value_str) > 3:  # Reasonable name length
                        name = value_str
                        break
    
    sale_data["name"] = name or f"Sale {start_date}"
    
    # Find discount/offer - usually in a later column
    for value in values_list[2:]:  # Skip first two columns (brand, name)
        if value and isinstance(value, str):
            value_str = str(value).strip()
            if any(keyword in value_str.lower() for keyword in ["%", "off", "discount", "code"]):
                sale_data["discount"] = value_str
                break
    
    # Create ID
    sale_data["id"] = create_sale_id(brand, sale_data["name"], start_date)
    
    return sale_data


def parse_multiple_date_ranges(dates_str: str, year: int = 2025) -> List[Dict[str, str]]:
    """Parse a dates string that may contain multiple date ranges.
    
    Returns list of {start_date, end_date, label} dicts.
    """
    if not dates_str or not isinstance(dates_str, str):
        return []
    
    date_ranges = []
    
    # Look for labeled ranges: "Main Event: 11/13 - 12/2", "EA: 11/11 - 11/12", etc.
    # Order matters - more specific patterns first
    patterns = [
        (r'Main Event[:\s]*(\d{1,2})[/-](\d{1,2})\s*-\s*(\d{1,2})[/-](\d{1,2})', 'main'),
        (r'Cyber Week Extension[:\s]*(\d{1,2})[/-](\d{1,2})\s*-\s*(\d{1,2})[/-](\d{1,2})', 'extension'),
        (r'(?:Public\s+)?EA[:\s]*(\d{1,2})[/-](\d{1,2})\s*-\s*(\d{1,2})[/-](\d{1,2})', 'ea'),
        (r'(?:EOY|End of Year)\s+Sale\s+Extension[:\s]*(\d{1,2})[/-](\d{1,2})\s*-\s*(\d{1,2})[/-](\d{1,2})', 'extension'),
        (r'Extension[:\s]*(\d{1,2})[/-](\d{1,2})\s*-\s*(\d{1,2})[/-](\d{1,2})', 'extension'),
    ]
    
    # Track found ranges to avoid duplicates
    found_ranges = set()
    
    for pattern, label in patterns:
        matches = re.finditer(pattern, dates_str, re.IGNORECASE)
        for match in matches:
            month1, day1, month2, day2 = match.groups()
            try:
                start_date = f"{year}-{int(month1):02d}-{int(day1):02d}"
                end_date = f"{year}-{int(month2):02d}-{int(day2):02d}"
                range_key = (start_date, end_date)
                if range_key not in found_ranges:
                    found_ranges.add(range_key)
                    date_ranges.append({
                        "start_date": start_date,
                        "end_date": end_date,
                        "label": label
                    })
            except (ValueError, TypeError):
                continue
    
    # If no labeled ranges found, try general pattern (handles day names like "Fri 11/15 - Tue 12/3")
    if not date_ranges:
        general_pattern = r'(?:[A-Za-z]+\s+)?(\d{1,2})[/-](\d{1,2})\s*-\s*(?:[A-Za-z]+\s+)?(\d{1,2})[/-](\d{1,2})'
        match = re.search(general_pattern, dates_str)
        if match:
            month1, day1, month2, day2 = match.groups()
            try:
                start_date = f"{year}-{int(month1):02d}-{int(day1):02d}"
                end_date = f"{year}-{int(month2):02d}-{int(day2):02d}"
                date_ranges.append({
                    "start_date": start_date,
                    "end_date": end_date,
                    "label": "general"
                })
            except (ValueError, TypeError):
                pass
    
    return date_ranges


def import_sale_schedules(
    source: str,
    file_path: Optional[Path] = None,
    url: Optional[str] = None,
    sheet_name: Optional[str] = None,
    start_row: int = 0,
    expected_columns: Optional[Dict[str, str]] = None
) -> List[Dict[str, Any]]:
    """Import sale schedules from various sources."""
    
    if expected_columns is None:
        expected_columns = {
            "brand": "brand",
            "name": "sale name",
            "start_date": "start date",
            "end_date": "end date",
            "discount": "discount",
            "type": "type",
        }
    
    # Read data based on source
    if source == "sheets":
        if not url:
            print("Error: --url required for Google Sheets source")
            sys.exit(1)
        rows = read_google_sheets(url, sheet_name, start_row)
    elif source == "csv":
        if not file_path:
            print("Error: --file required for CSV source")
            sys.exit(1)
        rows = read_csv_file(file_path, start_row)
    elif source == "excel":
        if not file_path:
            print("Error: --file required for Excel source")
            sys.exit(1)
        rows = read_excel_file(file_path, sheet_name, start_row)
    else:
        print(f"Error: Unknown source: {source}")
        sys.exit(1)
    
    # Parse rows into sale records
    # Handle rows with multiple date ranges by creating separate sale records
    sales = []
    # Infer year from sheet name
    year = 2025  # Default
    if sheet_name:
        if '2024' in sheet_name or 'BFCM 2024' in sheet_name or 'ID 2024' in sheet_name:
            year = 2024
        elif '2026' in sheet_name or '1H 2026' in sheet_name:
            year = 2026
    
    # Track current brand for continuation rows (where brand cell is empty)
    current_brand = None
    
    for row in rows:
        # Convert row to list for easier indexing
        # pandas to_dict('records') gives us dicts with column names as keys
        # We need to handle both dict and list formats
        if isinstance(row, dict):
            # Get values in order (dicts preserve insertion order in Python 3.7+)
            values_list = list(row.values())
            # Also try to get by position if keys are integers
            if any(isinstance(k, int) for k in row.keys()):
                # Keys are integers, use them directly
                max_key = max(k for k in row.keys() if isinstance(k, int))
                values_list = [row.get(i, '') for i in range(max_key + 1)]
            # If keys are strings (like 'Unnamed: 0'), preserve the dict but extract values
            # The values should be in insertion order
        else:
            values_list = list(row) if hasattr(row, '__iter__') else [row]
        
        # Get brand - check column 0 first (some sheets have brand in col 0), then column 1
        brand = None
        # Try column 0
        if len(values_list) > 0:
            brand_value = values_list[0]
            # Check if value is valid (not NaN, None, or empty string)
            brand_str = ''
            if brand_value is not None:
                if HAS_PANDAS:
                    # Check for pandas NaN
                    try:
                        if pd.notna(brand_value):
                            brand_str = str(brand_value).strip()
                    except:
                        brand_str = str(brand_value).strip() if brand_value else ''
                else:
                    brand_str = str(brand_value).strip() if brand_value else ''
            
            # Validate brand string
            if brand_str and brand_str.lower() not in ['nan', 'none', '', 'unnamed: 0']:
                normalized = normalize_brand(brand_str)
                if normalized and normalized in ["HAV", "CZ", "ID", "BUR", "STF", "TI"]:
                    brand = normalized
                    current_brand = brand  # Update current brand
        
        # Try column 1 if column 0 didn't work
        if not brand and len(values_list) > 1:
            brand_value = values_list[1]
            brand_str = ''
            if brand_value is not None:
                if HAS_PANDAS:
                    try:
                        if pd.notna(brand_value):
                            brand_str = str(brand_value).strip()
                    except:
                        brand_str = str(brand_value).strip() if brand_value else ''
                else:
                    brand_str = str(brand_value).strip() if brand_value else ''
            
            if brand_str and brand_str.lower() not in ['nan', 'none', '', 'unnamed: 1']:
                normalized = normalize_brand(brand_str)
                if normalized and normalized in ["HAV", "CZ", "ID", "BUR", "STF", "TI"]:
                    brand = normalized
                    current_brand = brand
        
        # If no brand in this row but we have a current brand, use it (continuation row)
        if not brand and current_brand:
            brand = current_brand
        
        if not brand:
            continue
        
        # Get sale name - try column 1 first (for continuation rows), then column 3
        name = None
        if len(values_list) > 1:
            name_value = values_list[1]
            if name_value and isinstance(name_value, str):
                name_str = str(name_value).strip()
                # Skip if it looks like a date or is empty
                if name_str and not re.search(r'\d{1,2}[/-]\d{1,2}', name_str) and name_str.lower() not in ['nan', 'none', '']:
                    name = ' '.join(name_str.split())
        
        # Fallback to column 3
        if not name and len(values_list) > 3:
            name_value = values_list[3]
            if name_value and isinstance(name_value, str):
                name_str = str(name_value).strip()
                if name_str and name_str.lower() not in ['nan', 'none', '']:
                    name = ' '.join(name_str.split())
        
        # Get dates - check if columns 2 and 3 are datetime objects
        dates_value = None
        start_date_dt = None
        end_date_dt = None
        
        # Check for datetime objects in the row (could be in any column)
        # Look for datetime objects that could be start/end dates
        if isinstance(row, dict):
            # Check specific known column keys first (for structured sheets)
            # Column 2 is typically 'LY PROMO COMP' or similar, column 3 is 'NAME OF PROMO'
            # But dates might be in different columns depending on sheet structure
            for key, value in row.items():
                if isinstance(value, datetime):
                    if not start_date_dt:
                        start_date_dt = value
                    elif not end_date_dt and value != start_date_dt:
                        # Use the second datetime as end date
                        end_date_dt = value
                        break  # Found both, stop looking
                elif HAS_PANDAS and isinstance(value, pd.Timestamp):
                    if not start_date_dt:
                        start_date_dt = value
                    elif not end_date_dt and value != start_date_dt:
                        end_date_dt = value
                        break
        else:
            # Check column 2 for start date (datetime object)
            if len(values_list) > 2:
                col2_value = values_list[2]
                # Check for datetime objects (pandas Timestamp or Python datetime)
                if isinstance(col2_value, datetime):
                    start_date_dt = col2_value
                elif HAS_PANDAS and isinstance(col2_value, pd.Timestamp):
                    start_date_dt = col2_value
                elif hasattr(col2_value, 'strftime') and not isinstance(col2_value, str):
                    # Try to use it as datetime
                    try:
                        start_date_dt = col2_value
                    except:
                        pass
            
            # Check column 3 for end date (datetime object) - but only if it's not the name
            if len(values_list) > 3:
                col3_value = values_list[3]
                # Check if it's a datetime (not a string name)
                if isinstance(col3_value, datetime):
                    end_date_dt = col3_value
                elif HAS_PANDAS and isinstance(col3_value, pd.Timestamp):
                    end_date_dt = col3_value
                elif hasattr(col3_value, 'strftime') and not isinstance(col3_value, str):
                    # Try to use it as datetime
                    try:
                        end_date_dt = col3_value
                    except:
                        pass
        
        # If we found datetime objects, use them directly
        if start_date_dt:
            try:
                # Convert to string dates
                if HAS_PANDAS and isinstance(start_date_dt, pd.Timestamp):
                    start_date = start_date_dt.strftime("%Y-%m-%d")
                else:
                    start_date = start_date_dt.strftime("%Y-%m-%d")
                
                if end_date_dt:
                    if HAS_PANDAS and isinstance(end_date_dt, pd.Timestamp):
                        end_date = end_date_dt.strftime("%Y-%m-%d")
                    else:
                        end_date = end_date_dt.strftime("%Y-%m-%d")
                else:
                    end_date = start_date
                
                # Create sale record directly
                sale_name = name or f"Sale {start_date}"
                sale = {
                    "id": create_sale_id(brand, sale_name, start_date),
                    "brand": brand,
                    "name": sale_name,
                    "start_date": start_date,
                    "end_date": end_date,
                }
                
                if discount:
                    sale["discount"] = discount
                
                sales.append(sale)
                continue  # Skip the rest of the parsing
            except Exception as e:
                # Fall through to text parsing if datetime conversion fails
                pass
        
        # Otherwise, try text-based date parsing
        if len(values_list) > 2:
            dates_value = values_list[2]
        
        if not dates_value:
            # Try old parsing method as fallback
            sale = parse_sale_row(row, expected_columns)
            if sale:
                sales.append(sale)
            continue
        
        # Parse multiple date ranges (use inferred year)
        date_ranges = parse_multiple_date_ranges(str(dates_value), year)
        
        # Get discount/offer (column 4)
        discount = None
        if len(values_list) > 4:
            discount_value = values_list[4]
            if discount_value and isinstance(discount_value, str):
                discount = str(discount_value).strip()
        
        # Create a sale record for each date range
        # Prefer Main Event, but include all ranges
        if date_ranges:
            for date_range in date_ranges:
                sale_name = name or f"Sale {date_range['start_date']}"
                # Add label to name if not Main Event and there are multiple ranges
                if date_range['label'] != 'main' and len(date_ranges) > 1:
                    sale_name = f"{sale_name} ({date_range['label'].upper()})"
                
                sale = {
                    "id": create_sale_id(brand, sale_name, date_range['start_date']),
                    "brand": brand,
                    "name": sale_name,
                    "start_date": date_range['start_date'],
                    "end_date": date_range['end_date'],
                }
                
                if discount:
                    sale["discount"] = discount
                
                sales.append(sale)
        else:
            # If no date ranges found, try the old parsing method
            sale = parse_sale_row(row, expected_columns)
            if sale:
                sales.append(sale)
    
    return sales


def main():
    parser = argparse.ArgumentParser(description="Import sale/promo schedules from Google Sheets or local files")
    parser.add_argument("--source", choices=["asana", "sync", "sheets", "csv", "excel"], required=True,
                       help="Data source type. 'asana' syncs from the Asana Promo Tracking board (recommended). 'sync' reads from the legacy Promo Calendar Google Sheet.")
    parser.add_argument("--file", type=str, help="Path to local CSV or Excel file")
    parser.add_argument("--url", type=str, help="Google Sheets URL")
    parser.add_argument("--sheet", type=str, help="Sheet name (for Excel or Google Sheets)")
    parser.add_argument("--start-row", type=int, default=0,
                       help="Row number to start reading from (0-indexed, excluding header)")
    parser.add_argument("--output", type=str, default="data/sale_schedules.yaml",
                       help="Output YAML file path")
    parser.add_argument("--append", action="store_true",
                       help="Append to existing sale schedules instead of overwriting")
    parser.add_argument("--dry-run", action="store_true",
                       help="Print parsed sales without writing to file")
    
    args = parser.parse_args()
    
    output_path = Path(__file__).parent.parent / args.output

    # ---- Asana sync mode ----
    if args.source == "asana":
        sales = sync_from_asana(dry_run=args.dry_run)

        if args.dry_run:
            print("\nParsed sales (preview):")
            for sale in sales[:20]:
                discount_preview = f" | {sale['discount'][:60]}" if sale.get("discount") else ""
                aud = f" [{sale['havenly_audience']}]" if sale.get("havenly_audience") else ""
                print(f"  - {sale['brand']}{aud}: {sale['name']} ({sale['start_date']} to {sale['end_date']}){discount_preview}")
            if len(sales) > 20:
                print(f"  ... and {len(sales) - 20} more")
            return

        # Merge strategy: Asana is authoritative for current and future sales.
        # Sales that have already ended are preserved for historical analysis.
        # This means date changes in Asana automatically remove the old entry.
        existing_sales = []
        if output_path.exists():
            with open(output_path) as f:
                data = yaml.safe_load(f) or {}
                existing_sales = data.get("sales", [])

        today = datetime.now().strftime("%Y-%m-%d")

        # Split existing entries into already-ended (keep) vs current/future (replace with Asana)
        historical: Dict[str, Any] = {}
        replaced_count = 0
        for s in existing_sales:
            end = s.get("end_date") or s.get("start_date") or ""
            if str(end) < today:
                historical[s["id"]] = s
            else:
                replaced_count += 1

        # Build output: preserved historical + fresh Asana data for current/future
        merged: Dict[str, Any] = dict(historical)
        for sale in sales:
            merged[sale["id"]] = sale

        asana_ids = {s["id"] for s in sales}
        removed = sum(1 for s in existing_sales
                      if str(s.get("end_date") or s.get("start_date") or "") >= today
                      and s["id"] not in asana_ids)
        added = sum(1 for s in sales if s["id"] not in {e["id"] for e in existing_sales})

        output_path.parent.mkdir(parents=True, exist_ok=True)
        with open(output_path, "w") as f:
            yaml.dump({
                "sales": list(merged.values()),
                "last_updated": datetime.now().isoformat(),
            }, f, default_flow_style=False, sort_keys=False)

        print(f"\nWrote {len(merged)} total sale records to {output_path}")
        print(f"  - {len(historical)} historical (already ended, preserved)")
        print(f"  - {len(sales)} current/future from Asana ({added} new, {removed} stale removed)")
        return

    # ---- Sync mode: auto-discover tabs from Promo Calendar ----
    if args.source == "sync":
        sales = sync_from_promo_calendar(dry_run=args.dry_run)

        if args.dry_run:
            print("\nParsed sales (preview):")
            for sale in sales[:20]:
                discount_preview = ""
                if sale.get("discount"):
                    discount_preview = f" | {sale['discount'][:60]}..."
                print(f"  - {sale['brand']}: {sale['name']} ({sale['start_date']} to {sale['end_date']}){discount_preview}")
            if len(sales) > 20:
                print(f"  ... and {len(sales) - 20} more")
            return

        # Sync mode always merges with existing historical data
        existing_sales = []
        if output_path.exists():
            with open(output_path) as f:
                data = yaml.safe_load(f) or {}
                existing_sales = data.get("sales", [])

        # Determine which existing sales are "historical" (year < current year)
        current_year = datetime.now().year
        historical = {}
        current_and_future = {}
        for s in existing_sales:
            try:
                sale_year = int(s.get("start_date", "")[:4])
            except (ValueError, TypeError):
                sale_year = 0
            if sale_year < current_year:
                historical[s["id"]] = s
            else:
                current_and_future[s["id"]] = s

        # Replace current/future sales with freshly synced data
        merged = dict(historical)
        for sale in sales:
            merged[sale["id"]] = sale

        # Write
        output_path.parent.mkdir(parents=True, exist_ok=True)
        with open(output_path, "w") as f:
            yaml.dump({
                "sales": list(merged.values()),
                "last_updated": datetime.now().isoformat(),
            }, f, default_flow_style=False, sort_keys=False)

        print(f"\nWrote {len(merged)} total sale records to {output_path}")
        print(f"  - {len(historical)} historical (preserved)")
        print(f"  - {len(merged) - len(historical)} current/future (synced)")
        return

    # ---- Legacy import modes (sheets, csv, excel) ----
    start_row = args.start_row
    
    print(f"Importing sale schedules from {args.source}...")
    sales = import_sale_schedules(
        source=args.source,
        file_path=Path(args.file) if args.file else None,
        url=args.url,
        sheet_name=args.sheet,
        start_row=start_row,
    )
    
    print(f"Parsed {len(sales)} sale records")
    
    if args.dry_run:
        print("\nParsed sales:")
        for sale in sales[:10]:  # Show first 10
            print(f"  - {sale['brand']}: {sale['name']} ({sale['start_date']} to {sale.get('end_date', 'N/A')})")
        if len(sales) > 10:
            print(f"  ... and {len(sales) - 10} more")
        return
    
    # Load existing sales if appending
    existing_sales = []
    if args.append and output_path.exists():
        with open(output_path) as f:
            data = yaml.safe_load(f) or {}
            existing_sales = data.get("sales", [])
    
    # Merge sales (avoid duplicates by ID)
    all_sales = {s["id"]: s for s in existing_sales}
    for sale in sales:
        all_sales[sale["id"]] = sale
    
    # Write to YAML
    output_path.parent.mkdir(parents=True, exist_ok=True)
    with open(output_path, "w") as f:
        yaml.dump({
            "sales": list(all_sales.values()),
            "last_updated": datetime.now().isoformat(),
        }, f, default_flow_style=False, sort_keys=False)
    
    print(f"Wrote {len(all_sales)} sale records to {output_path}")


if __name__ == "__main__":
    main()
