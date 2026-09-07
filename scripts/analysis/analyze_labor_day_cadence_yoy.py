"""
Labor Day email cadence, YoY comparison, all brands.

Origin: Stang asked for ID's next-week email schedule comped to last year's
flighting, then asked for the comp to be aligned by distance-from-sale (not
calendar week, since Labor Day fell 6 days later in 2026 than 2025), then
asked for the same cut across all 6 brands.

Four scoping methods were tried before landing on the one that actually
holds up. Documenting all four here (not just the winner) because each
failure mode is a real trap someone will hit again on a future sale-cadence
comp if this file only shows the final answer:

  1. Calendar week comp (rejected) — "next week" vs. "same week last year"
     breaks whenever the anchor holiday moves. Labor Day is the first Monday
     of September, so it drifts year to year; a fixed calendar week silently
     compares two different points in the sale.

  2. Whole Aug 1-Sep 30 window (rejected) — wide enough to catch the full
     sale, but also wide enough to catch several *other* unrelated sales
     (Rug Event, Flash Sale, Bedroom Refresh Sale, Weekender Sale, etc.).
     Declines measured here reflect general email volume, not Labor Day
     cadence specifically.

  3. Category-tag isolation (rejected) — filtering to rows tagged "Labor Day
     Event" looks like the fix, but the tag is applied by DATE OVERLAP
     against data/sale_schedules.yaml, not by content. When a second sale
     (e.g. ID's Warehouse Sale, which ran the entire Labor Day period in
     2026) is active on the same date, unrelated content picks up the
     "Labor Day" tag too. Produced impossible swings (ID appearing to jump
     +32%, BUR flipping from a decline to +24%) driven by tagging overlap,
     not real cadence change.

  4. Name-based content matching (rejected) — tried filtering on whether the
     campaign/task name mentions "Labor Day" directly. Fails harder than #3:
     2025 rows are the actual Braze/Klaviyo campaign name, which spells out
     the sale name by convention. 2026 rows are Asana TASK names, which this
     team's own naming standard deliberately shortens (e.g. "AM Reminder"
     instead of repeating "Labor Day" in every task title). The two years
     are labeled by non-comparable conventions, so text matching produced
     nonsense (e.g. an apparent 1167% "change" for HAV).

  5. Date-window distance-from-anchor (USED) — count sends by calendar
     distance from Labor Day itself, independent of category tags or naming
     conventions. This is the only method where every brand moved the same
     direction and the magnitude was plausible across all six.

Important nuance on top of method #5, NOT a rejection of it: the fixed
±1-week window answers "did the daily sending RATE around Labor Day drop,"
not "did TOTAL email volume for the whole event drop." Each brand's real
promotional span (EA launch through Extension end, from
data/sale_schedules.yaml) is genuinely longer in 2026 for most brands
(longer Extensions, an added EA phase, in ID's case an earlier "DE
Backpocket Preview" phase). Counting the full real span therefore shows a
very different picture — HAV/ID/BUR/TI roughly flat-to-up, only CZ/STF
still clearly down, total volume ~flat (205 -> 206) — because a wider
window naturally catches more sends, independent of any real rate change.
This is the same unequal-window-width trap as method #2, just from the
other direction (unequal widths instead of one too-wide fixed window).
Both numbers are correct; they answer different questions. See
`full_span_counts()` below and the "Important nuance" section in
reports/labor-day-cadence-yoy-2026.md.

QA pass with Jordan Rubenstein (2026-08-28) found one real methodology gap,
now fixed in this script:
  - HAV counted some combined sends as one instead of two. In 2025, HAV
    always split Pre-Converted (DPS) and Converted (MP) audiences into
    separate Asana tickets, so each showed up as its own row. In 2026, some
    tickets are titled "DPS and MP: ..." (or, in one case, have a blank
    Audience field) and represent a single ticket covering both audiences —
    still 2 actual sends, not 1. `split_hav_combined_tickets()` below splits
    each of these into 2 rows to match how 2025 was counted. This moved
    HAV's +/-1-week window total from 21 to 24.
  - Confirmed already handled, no change needed: the 3 ID segment-variant PT
    sends (Cart Abandoners/Engaged/Swatchees, 9/1/25) and the 2 Extension
    retargeting variants (365Day/90Day, 9/5/25) are genuinely distinct sends
    to distinct audiences — already counted as separate rows. The 2 BUR
    "[delete]"-prefixed duplicate/test rows are excluded by
    JUNK_NAME_PATTERN below.

Known data-quality caveats (open as of 2026-08-28, NOT yet resolved in this
script):
  - At least one Asana ticket for an email BANNER (not an actual email send)
    was found with Channel = Email, which would inflate a raw Channel=Email
    count if not caught. It fell outside the +/-1-week window used here, so
    it does not affect the headline numbers below, but similar mistagging
    may exist elsewhere in the wider Aug-Sep pull.
  - A separate STF ticket's Channel field was being confirmed with Mina at
    the time of this analysis; if it's a real email, it needs including.
  - Neither issue has been swept for across the full dataset. Do that before
    trusting the whole-window totals in reports/labor_day_cadence_2026_asana_snapshot.json
    for anything beyond directional context.

Usage:
    uv run python scripts/analysis/analyze_labor_day_cadence_yoy.py

Inputs:
  - campaigns/*.yaml               2025 actuals (this repo's knowledgebase)
  - data/sale_schedules.yaml       sale phase date ranges, for the category-tag
                                    method shown here for reference/comparison only
  - reports/labor_day_cadence_2026_asana_snapshot.json
                                    2026 planned schedule, pulled via Asana MCP
                                    (Brand + Channel=Email custom fields, Lacy
                                    copy-subtask rows excluded, blank-Type rows
                                    excluded, [delete]/Test_Send rows excluded)
                                    on 2026-08-28. Asana access wasn't available
                                    from this script directly — regenerate this
                                    snapshot via a fresh Asana pull (see
                                    CLAUDE.md's Asana Integration section) if a
                                    later comparison needs current data.
"""

import datetime
import glob
import json
import re
from collections import defaultdict

import yaml

BRANDS = ["HAV", "CZ", "ID", "BUR", "STF", "TI"]
JUNK_NAME_PATTERN = re.compile(r"\[delete\]|_test_send|do not use", re.IGNORECASE)
SNAPSHOT_PATH = "reports/labor_day_cadence_2026_asana_snapshot.json"
HAV_COMBINED_PATTERN = re.compile(r"^DPS and MP:", re.IGNORECASE)
HAV_COMBINED_BLANK_AUDIENCE_NAMES = {"Items in Your Design Are on Sale"}


def split_hav_combined_tickets(hav_rows):
    """See module docstring: HAV 2026 sometimes files one Asana ticket that
    covers both DPS and MP audiences, where 2025 always used two separate
    tickets. Split each combined ticket into 2 rows so the two years count
    on the same basis."""
    out = []
    for r in hav_rows:
        is_combined = HAV_COMBINED_PATTERN.match(r["name"]) or r["name"] in HAV_COMBINED_BLANK_AUDIENCE_NAMES
        if is_combined:
            out.append({**r, "name": r["name"] + " (DPS)"})
            out.append({**r, "name": r["name"] + " (MP)"})
        else:
            out.append(r)
    return out


def labor_day(year):
    """First Monday of September for the given year."""
    d = datetime.date(year, 9, 1)
    d += datetime.timedelta(days=(7 - d.weekday()) % 7)
    return d


def load_2025_actuals(start, end):
    """Pull real sent campaigns from campaigns/*.yaml, deduped by id, Trade
    and junk (test/deleted-duplicate) sends excluded."""
    by_brand = defaultdict(dict)
    for path in glob.glob("campaigns/*.yaml"):
        try:
            with open(path) as f:
                rec = yaml.safe_load(f)
        except Exception:
            continue
        if not rec or rec.get("brand") not in BRANDS or rec.get("channel") != "email":
            continue
        send_date = (rec.get("dates") or {}).get("send_date")
        if not send_date or not (start <= send_date <= end):
            continue
        name = rec.get("name", "")
        if "TRADE" in name.upper() or JUNK_NAME_PATTERN.search(name):
            continue
        by_brand[rec["brand"]][rec.get("id")] = {"date": send_date, "name": name}
    return {b: list(v.values()) for b, v in by_brand.items()}


def load_2026_snapshot():
    with open(SNAPSHOT_PATH) as f:
        return json.load(f)


# Each brand's real Labor Day promotional span (EA launch through Extension
# end), pulled from data/sale_schedules.yaml. Hardcoded as a snapshot rather
# than re-queried live because sale_schedules.yaml syncs daily from Asana and
# could drift after this analysis was written -- regenerate this dict from
# the source file if a later run needs current dates.
FULL_SPANS = {
    "HAV": {2025: ("2025-08-07", "2025-09-03"), 2026: ("2026-08-06", "2026-09-15")},
    "CZ":  {2025: ("2025-08-19", "2025-09-08"), 2026: ("2026-08-18", "2026-09-15")},
    "ID":  {2025: ("2025-08-19", "2025-09-08"), 2026: ("2026-08-13", "2026-09-15")},
    "BUR": {2025: ("2025-08-19", "2025-09-09"), 2026: ("2026-08-18", "2026-09-20")},
    "STF": {2025: ("2025-08-21", "2025-09-08"), 2026: ("2026-08-20", "2026-09-08")},
    "TI":  {2025: ("2025-08-21", "2025-09-08"), 2026: ("2026-08-18", "2026-09-15")},
}


def full_span_counts(rows_by_brand, year):
    """Count sends within each brand's own real EA-through-Extension dates
    for the given year. Unlike date_window_counts(), window width varies by
    brand and year -- that's the point (it measures the real event), and
    also why it answers a different question than the trusted metric. See
    module docstring."""
    counts = {}
    for brand in BRANDS:
        start, end = FULL_SPANS[brand][year]
        counts[brand] = sum(1 for r in rows_by_brand.get(brand, []) if start <= r["date"] <= end)
    return counts


def date_window_counts(rows_by_brand, year, offset_start, offset_end):
    """Count sends within [offset_start, offset_end] days of that year's
    Labor Day. This is the method that actually holds up — see module
    docstring for why the other three don't."""
    ld = labor_day(year)
    counts = {}
    for brand in BRANDS:
        n = 0
        for r in rows_by_brand.get(brand, []):
            offset = (datetime.date.fromisoformat(r["date"]) - ld).days
            if offset_start <= offset <= offset_end:
                n += 1
        counts[brand] = n
    return counts


def main():
    ld_2025, ld_2026 = labor_day(2025), labor_day(2026)
    print(f"Labor Day 2025: {ld_2025} ({ld_2025.strftime('%A')})")
    print(f"Labor Day 2026: {ld_2026} ({ld_2026.strftime('%A')})  <- {(ld_2026 - ld_2025).days - 365} days later than a fixed 365-day comp would assume\n")

    window_start = f"{ld_2025.year}-08-01"
    window_end = f"{ld_2025.year}-09-30"
    rows_2025 = load_2025_actuals(window_start, window_end)
    rows_2026_raw = load_2026_snapshot()
    rows_2026 = {b: [{"date": r["date"], "name": r["name"]} for r in rows_2026_raw.get(b, [])] for b in BRANDS}
    rows_2026["HAV"] = split_hav_combined_tickets(rows_2026["HAV"])

    print("=== Whole Aug 1-Sep 30 window (method #2 — rejected, shown for reference) ===")
    for b in BRANDS:
        n25, n26 = len(rows_2025.get(b, [])), len(rows_2026.get(b, []))
        print(f"  {b:5s}  2025={n25:3d}  2026={n26:3d}  ({(n26 - n25) / n25 * 100:+.0f}%)")

    print("\n=== Date-window +/-1 week around Labor Day (method #5 — trusted metric) ===")
    c25 = date_window_counts(rows_2025, 2025, -7, 6)
    c26 = date_window_counts(rows_2026, 2026, -7, 6)
    tot25 = tot26 = 0
    for b in BRANDS:
        n25, n26 = c25[b], c26[b]
        tot25 += n25
        tot26 += n26
        print(f"  {b:5s}  2025={n25:3d}  2026={n26:3d}  ({(n26 - n25) / n25 * 100:+.0f}%)")
    print(f"  {'TOTAL':5s}  2025={tot25:3d}  2026={tot26:3d}  ({(tot26 - tot25) / tot25 * 100:+.0f}%)")

    print("\n=== Full real promotional span, EA through Extension (rate vs. volume nuance) ===")
    fs25 = full_span_counts(rows_2025, 2025)
    fs26 = full_span_counts(rows_2026, 2026)
    ftot25 = ftot26 = 0
    for b in BRANDS:
        n25, n26 = fs25[b], fs26[b]
        ftot25 += n25
        ftot26 += n26
        print(f"  {b:5s}  2025={n25:3d}  2026={n26:3d}  ({(n26 - n25) / n25 * 100:+.0f}%)")
    print(f"  {'TOTAL':5s}  2025={ftot25:3d}  2026={ftot26:3d}  ({(ftot26 - ftot25) / ftot25 * 100:+.0f}%)")
    print("  ^ Different window widths per brand/year by design -- answers")
    print("    'did total volume change,' not 'did the daily rate change.'")

    print("\nSee reports/labor-day-cadence-yoy-2026.md for full methodology, caveats, and verification plan.")


if __name__ == "__main__":
    main()
