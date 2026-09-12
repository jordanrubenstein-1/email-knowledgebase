#!/usr/bin/env python3
"""
List Havenly (HAV) Campaign and Canvas emails by from-address (t.havenly.com vs mail.havenly.com).

Campaigns: last sent in past month, name does NOT start with P_.
Canvases: last entry in past month (triggered journeys).

Requires BRAZE_API_KEY_HAV (or BRAZE_API_KEY) and BRAZE_BASE_URL_HAV in .env.
"""

import sys
from concurrent.futures import ThreadPoolExecutor, as_completed
from datetime import datetime, timedelta, timezone
from pathlib import Path

# Project root and scripts for import_braze
_root = Path(__file__).resolve().parent.parent.parent
_scripts = _root / "scripts"
sys.path.insert(0, str(_root))
sys.path.insert(0, str(_scripts))
from dotenv import load_dotenv
load_dotenv(_root / ".env")

from import_braze import (
    init_config,
    get_campaigns,
    get_campaign_details,
    get_canvases,
    get_canvas_details,
    infer_brand_from_name,
    parse_date,
)

T_DOMAIN = "t.havenly.com"
WORKERS = 10


def main():
    init_config("HAV")

    def uses_t_havenly(from_str):
        if not from_str:
            return False
        return T_DOMAIN in (from_str or "").lower()

    now = datetime.now(timezone.utc)
    cutoff = now - timedelta(days=30)

    print("Fetching campaigns from Braze (HAV API key — all campaigns are Havenly)...")
    campaigns = get_campaigns(include_archived=True)
    # HAV API key is brand-specific, so ALL returned campaigns are Havenly
    # (don't filter by name containing HAV — transactional emails like "Password Reset" lack it)
    name_ok = [c for c in campaigns if not (c.get("name") or "").strip().startswith("P_")]
    print(f"Total campaigns: {len(campaigns)}, name not starting with P_: {len(name_ok)}")
    print("Fetching details (last_sent + from address)...")

    results_t = []   # from t.havenly.com (the 4)
    results_other = []  # past month, name not P_, from NOT t.havenly.com
    with ThreadPoolExecutor(max_workers=WORKERS) as executor:
        future_to_c = {executor.submit(get_campaign_details, c["id"]): c for c in name_ok}
        for future in as_completed(future_to_c):
            c = future_to_c[future]
            try:
                details = future.result()
            except Exception as e:
                print(f"  Error {c.get('name', c['id'])}: {e}", file=sys.stderr)
                continue
            if not details or "messages" not in details:
                continue
            last_sent = parse_date(details.get("last_sent"))
            if not last_sent:
                continue
            if last_sent.tzinfo is None:
                last_sent = last_sent.replace(tzinfo=timezone.utc)
            if last_sent < cutoff:
                continue
            for msg_id, msg in details.get("messages", {}).items():
                if msg.get("channel") != "email":
                    continue
                from_addr = msg.get("from") or ""
                subject = (msg.get("subject") or "")[:60]
                row = {"name": c["name"], "from": from_addr, "subject": subject}
                if uses_t_havenly(from_addr):
                    results_t.append(row)
                else:
                    results_other.append(row)
                break

    # --- Report: t.havenly.com (the 4) ---
    print()
    print(f"--- Havenly Campaigns (last month, name not P_*) sent from @{T_DOMAIN} ---")
    print(f"Total: {len(results_t)}")
    print()
    for r in results_t:
        print(f"  {r['name']}")
        print(f"    From: {r['from']}")
        if r.get("subject"):
            print(f"    Subject: {r['subject']}...")
        print()

    # --- Report: all other campaigns (past month, name not P_, excluding the 4 above) ---
    print()
    print("--- All other Havenly Campaigns (last month, name not P_*) — excluding the 4 above ---")
    print(f"Total: {len(results_other)}")
    print()
    for r in sorted(results_other, key=lambda x: x["name"]):
        print(f"  {r['name']}")
        print(f"    From: {r['from']}")
        if r.get("subject"):
            print(f"    Subject: {r['subject']}...")
        print()

    # ========== CANVASES ==========
    print()
    print("========== CANVASES (triggered journeys) ==========")
    print("Fetching canvases from Braze...")
    canvases = get_canvases()
    hav_cv = [cv for cv in canvases if infer_brand_from_name(cv.get("name", "")) == "HAV"]
    if not hav_cv:
        hav_cv = list(canvases)  # HAV API key: assume all canvases are Havenly if none match by name
        print(f"Total canvases: {len(canvases)} (all treated as HAV — none matched by name)")
    else:
        print(f"Total canvases: {len(canvases)}, HAV by name: {len(hav_cv)}")
    cv_past_month = []
    for cv in hav_cv:
        last_entry = parse_date(cv.get("last_entry"))
        if not last_entry:
            continue
        if last_entry.tzinfo is None:
            last_entry = last_entry.replace(tzinfo=timezone.utc)
        if last_entry >= cutoff:
            cv_past_month.append(cv)
    if not cv_past_month and hav_cv:
        print("(Canvas list has no last_entry; using all HAV canvases.)")
        cv_past_month = hav_cv
    print(f"Canvases to check (last month or all): {len(cv_past_month)}")

    print("Fetching canvas details (from address per email step)...")
    canvas_t = []
    canvas_other = []
    canvas_chart = []  # canvas_name, step_name, from_variant (Havenly/hello vs Rachel from Havenly)
    with ThreadPoolExecutor(max_workers=WORKERS) as executor:
        future_to_cv = {executor.submit(get_canvas_details, cv["id"]): cv for cv in cv_past_month}
        for future in as_completed(future_to_cv):
            cv = future_to_cv[future]
            try:
                details = future.result()
            except Exception as e:
                print(f"  Error {cv.get('name', cv['id'])}: {e}", file=sys.stderr)
                continue
            if not details or "steps" not in details:
                continue
            last_entry = parse_date(details.get("last_entry"))
            if last_entry and last_entry.tzinfo is None:
                last_entry = last_entry.replace(tzinfo=timezone.utc)
            if last_entry and last_entry < cutoff:
                continue
            canvas_name = cv["name"]
            for step in details.get("steps", []):
                if step.get("type") != "message":
                    continue
                for msg_id, msg in (step.get("messages") or {}).items():
                    if msg.get("channel") != "email":
                        continue
                    from_addr = msg.get("from") or ""
                    subject = (msg.get("subject") or "")[:60]
                    step_name = step.get("name") or msg_id
                    display = f"{canvas_name} → {step_name}"
                    row = {"name": display, "from": from_addr, "subject": subject}
                    # From variant: "Rachel from Havenly" vs "Havenly (hello)"
                    from_variant = "Rachel from Havenly" if "Rachel" in from_addr else "Havenly (hello)"
                    canvas_chart.append({"canvas_name": canvas_name, "step_name": step_name, "from_variant": from_variant})
                    if uses_t_havenly(from_addr):
                        canvas_t.append(row)
                    else:
                        canvas_other.append(row)
                    break

    print()
    print(f"--- Havenly Canvas steps (last month) sent from @{T_DOMAIN} ---")
    print(f"Total: {len(canvas_t)}")
    print()
    for r in sorted(canvas_t, key=lambda x: x["name"]):
        print(f"  {r['name']}")
        print(f"    From: {r['from']}")
        if r.get("subject"):
            print(f"    Subject: {r['subject']}...")
        print()

    print()
    print("--- All other Havenly Canvas steps (last month) ---")
    print(f"Total: {len(canvas_other)}")
    print()
    for r in sorted(canvas_other, key=lambda x: x["name"]):
        print(f"  {r['name']}")
        print(f"    From: {r['from']}")
        if r.get("subject"):
            print(f"    Subject: {r['subject']}...")
        print()

    # Chart: Canvas name | Step name | From variant (hello vs Rachel from Havenly)
    print()
    print("--- Canvas From-Address Chart (Canvas | Step | Variant) ---")
    all_chart = sorted(canvas_chart, key=lambda x: (x["canvas_name"], x["step_name"], x["from_variant"]))
    col1, col2, col3 = "Canvas name", "Step name", "From variant"
    w1 = max(len(col1), max(len(r["canvas_name"]) for r in all_chart) if all_chart else 0)
    w2 = max(len(col2), max(len(r["step_name"]) for r in all_chart) if all_chart else 0)
    w3 = max(len(col3), max(len(r["from_variant"]) for r in all_chart) if all_chart else 0)
    w1, w2, w3 = max(w1, 12), max(w2, 12), max(w3, 20)
    print(f"| {col1:<{w1}} | {col2:<{w2}} | {col3:<{w3}} |")
    print(f"|{'-' * (w1 + 2)}|{'-' * (w2 + 2)}|{'-' * (w3 + 2)}|")
    for r in all_chart:
        print(f"| {r['canvas_name']:<{w1}} | {r['step_name']:<{w2}} | {r['from_variant']:<{w3}} |")
    return 0


if __name__ == "__main__":
    sys.exit(main())
