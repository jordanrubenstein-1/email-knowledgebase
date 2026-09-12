"""
Analyze HAV email performance around Memorial Day 2025 (May 23–26, 2025).
"""
import os
import re
import yaml
from pathlib import Path
from datetime import date
from collections import defaultdict

CAMPAIGNS_DIR = Path("/Users/mina.cohen/AI Email/email-knowledgebase/campaigns")
TARGET_DATES = {
    date(2025, 5, 22), date(2025, 5, 23), date(2025, 5, 24),
    date(2025, 5, 25), date(2025, 5, 26), date(2025, 5, 27),
}
DATE_LABEL = {
    date(2025, 5, 22): "Thu 5/22",
    date(2025, 5, 23): "Fri 5/23",
    date(2025, 5, 24): "Sat 5/24",
    date(2025, 5, 25): "Sun 5/25",
    date(2025, 5, 26): "Mon 5/26 (Memorial Day)",
    date(2025, 5, 27): "Tue 5/27",
}

NAME_DATE_RE = re.compile(r'_(\d{4})_(\d{2})_(\d{2})_')

def extract_date_from_name(name: str):
    m = NAME_DATE_RE.search(name)
    if m:
        return date(int(m.group(1)), int(m.group(2)), int(m.group(3)))
    return None

def detect_type(name: str) -> str:
    parts = name.split("_")
    if "PT" in parts:
        return "Plain-Text"
    if "D" in parts:
        return "Designed"
    return "Unknown"

def detect_audience(name: str) -> str:
    name_upper = name.upper()
    if "_PC_" in name_upper:
        return "DPS"
    if "_CONV_" in name_upper:
        return "CONV"
    return "General"

def load_campaigns():
    results = []
    seen_ids = set()
    for path in CAMPAIGNS_DIR.glob("*.yaml"):
        try:
            with open(path) as f:
                data = yaml.safe_load(f)
        except Exception:
            continue

        if not data:
            continue
        if data.get("brand") != "HAV":
            continue
        if data.get("channel") != "email":
            continue
        # Exclude canvas steps (triggered journeys); accept missing braze_type (older YAMLs are batch campaigns)
        if data.get("braze_type") == "canvas_step":
            continue

        name = data.get("name", "")

        # Use dates.send_date first (most reliable), then extract from name, then first_sent
        send_date = None
        raw_send_date = data.get("dates", {}).get("send_date")
        if raw_send_date:
            try:
                from datetime import datetime
                if isinstance(raw_send_date, date):
                    send_date = raw_send_date
                else:
                    send_date = datetime.strptime(str(raw_send_date), "%Y-%m-%d").date()
            except Exception:
                pass

        if send_date is None:
            send_date = extract_date_from_name(name)

        # Fallback to first_sent
        if send_date is None:
            first_sent = data.get("dates", {}).get("first_sent")
            if first_sent:
                try:
                    if hasattr(first_sent, "date"):
                        send_date = first_sent.date()
                    else:
                        from datetime import datetime
                        send_date = datetime.fromisoformat(str(first_sent).replace("Z", "+00:00")).date()
                except Exception:
                    pass

        if send_date not in TARGET_DATES:
            continue

        # Deduplicate by campaign ID
        campaign_id = data.get("id") or data.get("braze_id")
        if campaign_id and campaign_id in seen_ids:
            continue
        if campaign_id:
            seen_ids.add(campaign_id)

        perf = data.get("performance_summary", {})
        total_sends = perf.get("total_sends", 0)
        open_rate = perf.get("open_rate")
        click_rate = perf.get("click_rate")

        # Subject line
        subject = ""
        sends = data.get("sends", [])
        if sends and isinstance(sends, list) and len(sends) > 0:
            subject = sends[0].get("subject", "") or ""

        results.append({
            "name": name,
            "send_date": send_date,
            "braze_type": data.get("braze_type"),
            "email_type": detect_type(name),
            "audience": detect_audience(name),
            "total_sends": total_sends,
            "open_rate": open_rate,
            "click_rate": click_rate,
            "subject": subject,
        })

    results.sort(key=lambda x: (x["send_date"], x["name"]))
    return results

def fmt_pct(val):
    if val is None:
        return "N/A"
    return f"{val * 100:.1f}%"

def fmt_num(val):
    if val is None:
        return "N/A"
    return f"{val:,}"

def main():
    campaigns = load_campaigns()
    print(f"Found {len(campaigns)} HAV email batch campaigns between May 22–27, 2025\n")

    # --- Full campaign table ---
    print("=" * 130)
    print(f"{'Date':<20} {'Audience':<8} {'Type':<12} {'Sends':>8} {'OR%':>7} {'CR%':>7}  Subject / Campaign Name")
    print("=" * 130)
    for c in campaigns:
        label = DATE_LABEL.get(c["send_date"], str(c["send_date"]))
        subj = c["subject"][:55] if c["subject"] else f"[{c['name'][:55]}]"
        print(f"{label:<20} {c['audience']:<8} {c['email_type']:<12} {fmt_num(c['total_sends']):>8} {fmt_pct(c['open_rate']):>7} {fmt_pct(c['click_rate']):>7}  {subj}")

    # --- Day-by-day summary ---
    print("\n" + "=" * 70)
    print("DAY-BY-DAY SUMMARY")
    print("=" * 70)
    by_day = defaultdict(list)
    for c in campaigns:
        by_day[c["send_date"]].append(c)

    for d in sorted(by_day.keys()):
        day_campaigns = by_day[d]
        ors = [c["open_rate"] for c in day_campaigns if c["open_rate"] is not None]
        avg_or = sum(ors) / len(ors) if ors else None
        print(f"\n{DATE_LABEL[d]}  ({len(day_campaigns)} sends)")
        for c in day_campaigns:
            print(f"  [{c['audience']:<7}] [{c['email_type']:<11}]  OR: {fmt_pct(c['open_rate'])}  CR: {fmt_pct(c['click_rate'])}  Sends: {fmt_num(c['total_sends'])}")
            subj = c["subject"][:80] if c["subject"] else ""
            if subj:
                print(f"           Subject: \"{subj}\"")
        if avg_or is not None:
            print(f"  --> Avg OR: {avg_or * 100:.1f}%")

    # --- PT vs Designed comparison ---
    print("\n" + "=" * 70)
    print("PLAIN-TEXT vs DESIGNED COMPARISON")
    print("=" * 70)
    by_type = defaultdict(list)
    for c in campaigns:
        by_type[c["email_type"]].append(c)

    for etype in ["Plain-Text", "Designed", "Unknown"]:
        group = by_type.get(etype, [])
        if not group:
            continue
        ors = [c["open_rate"] for c in group if c["open_rate"] is not None]
        avg_or = sum(ors) / len(ors) if ors else None
        crs = [c["click_rate"] for c in group if c["click_rate"] is not None]
        avg_cr = sum(crs) / len(crs) if crs else None
        total_sends_all = sum(c["total_sends"] for c in group if c["total_sends"])
        print(f"\n{etype} ({len(group)} campaign{'s' if len(group) != 1 else ''})")
        print(f"  Avg Open Rate:  {avg_or * 100:.1f}%" if avg_or else "  Avg Open Rate: N/A")
        print(f"  Avg Click Rate: {avg_cr * 100:.2f}%" if avg_cr else "  Avg Click Rate: N/A")
        print(f"  Total Sends:    {total_sends_all:,}")

    # --- Top performer ---
    print("\n" + "=" * 70)
    print("TOP PERFORMERS")
    print("=" * 70)
    with_or = [c for c in campaigns if c["open_rate"] is not None]
    if with_or:
        top = sorted(with_or, key=lambda x: x["open_rate"], reverse=True)
        print("\nTop 5 by Open Rate:")
        for i, c in enumerate(top[:5], 1):
            label = DATE_LABEL.get(c["send_date"], str(c["send_date"]))
            subj = c["subject"][:60] if c["subject"] else c["name"][:60]
            print(f"  {i}. [{label}] [{c['audience']}/{c['email_type']}]  OR: {fmt_pct(c['open_rate'])}  CR: {fmt_pct(c['click_rate'])}")
            print(f"       Subject: \"{subj}\"")

    with_cr = [c for c in campaigns if c["click_rate"] is not None]
    if with_cr:
        top_cr = sorted(with_cr, key=lambda x: x["click_rate"], reverse=True)
        print("\nTop 5 by Click Rate:")
        for i, c in enumerate(top_cr[:5], 1):
            label = DATE_LABEL.get(c["send_date"], str(c["send_date"]))
            subj = c["subject"][:60] if c["subject"] else c["name"][:60]
            print(f"  {i}. [{label}] [{c['audience']}/{c['email_type']}]  CR: {fmt_pct(c['click_rate'])}  OR: {fmt_pct(c['open_rate'])}")
            print(f"       Subject: \"{subj}\"")

if __name__ == "__main__":
    main()
