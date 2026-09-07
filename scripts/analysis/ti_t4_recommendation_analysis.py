"""
TI T4 Recommendation Conversion Analysis

1. Stream OrderDelivered events → collect profile IDs (fast, ~6K events)
2. Stream cancellations/refunds/unsubscribes globally → explain receipt gap
3. Per profile: query Received Email filtered by profile_id → confirm T4 receipt
4. Per confirmed T4 recipient: query OrderPlaced → get recs + subsequent orders
5. Measure whether T4 recipients bought their recommended products

Flow:  RYqsRt — [NEW] Order Delivered: NONSWATCH Post Purchase Flow
T4 message ID: VNVeN8

Usage:
    uv run python scripts/analysis/ti_t4_recommendation_analysis.py
    uv run python scripts/analysis/ti_t4_recommendation_analysis.py --days 180 --window 90 --debug
"""

import argparse
import os
import sys
from collections import Counter, defaultdict
from datetime import datetime, timedelta, timezone

from dotenv import load_dotenv

load_dotenv()

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", ".."))
from scripts.utils.klaviyo_client import KlaviyoClient

T4_MESSAGE_ID       = "VNVeN8"
RECEIVED_EMAIL      = "PACe5d"
ORDER_DELIVERED     = "VEiMkP"
ORDER_PLACED        = "Krer26"
ORDER_CANCELLED_API = "JLihKS"   # OrderCancelled (API/new)
ORDER_CANCELLED_SHP = "MkrNCT"   # Cancelled Order (Shopify/legacy)
ORDER_REFUNDED_API  = "KtmQnN"   # OrderRefunded
ORDER_REFUNDED_SHP  = "JUYSvM"   # Refunded Order (Shopify/legacy)
UNSUB_EMAIL         = "SPLrry"   # Unsubscribed from Email Marketing
UNSUB_LIST          = "MbAmEe"   # Unsubscribed from List


def get_profile_events(client, metric_id, profile_id, start_iso, end_iso):
    params = {
        "filter": (
            f'equals(metric_id,"{metric_id}"),'
            f'equals(profile_id,"{profile_id}"),'
            f'greater-than(datetime,{start_iso}),'
            f'less-than(datetime,{end_iso})'
        ),
        "fields[event]": "datetime,event_properties",
        "sort": "datetime",
        "page[size]": 200,
    }
    results = []
    next_url = "/events/"
    is_first = True
    while next_url:
        data = client._get(next_url, params=params) if is_first else client._get(next_url)
        is_first = False
        if not data:
            break
        results.extend(data.get("data", []))
        next_url = (data.get("links") or {}).get("next")
    return results


def stream_metric(client, metric_id, start_iso, end_iso, callback):
    params = {
        "filter": (
            f'equals(metric_id,"{metric_id}"),'
            f'greater-than(datetime,{start_iso}),'
            f'less-than(datetime,{end_iso})'
        ),
        "fields[event]": "datetime,event_properties",
        "sort": "datetime",
        "page[size]": 200,
    }
    total = 0
    next_url = "/events/"
    is_first = True
    while next_url:
        data = client._get(next_url, params=params) if is_first else client._get(next_url)
        is_first = False
        if not data:
            break
        for ev in data.get("data", []):
            callback(ev)
            total += 1
        next_url = (data.get("links") or {}).get("next")
    return total


def profile_id_of(ev):
    return ev.get("relationships", {}).get("profile", {}).get("data", {}).get("id")


def parse_dt(ev):
    s = ev.get("attributes", {}).get("datetime", "")
    return datetime.fromisoformat(s.replace("Z", "+00:00")) if s else None


def _norm(s):
    return s.strip().lower() if s else ""


def parse_order_event(ev):
    props = ev.get("attributes", {}).get("event_properties", {})
    dt = parse_dt(ev)

    def _extract(items_list):
        skus, names, frames = set(), set(), set()
        for i in items_list:
            if not isinstance(i, dict):
                continue
            sku = (i.get("SKU") or i.get("sku", "")).upper()
            name = _norm(i.get("name", ""))
            frame = _norm(i.get("frame", ""))
            if sku:   skus.add(sku)
            if name:  names.add(name)
            if frame: frames.add(frame)
        return skus, names, frames

    item_skus, item_names, item_frames = _extract(props.get("Items", []))
    rec_skus,  rec_names,  rec_frames  = _extract(props.get("recommended_products", []))

    return (
        dt,
        (item_skus, item_names, item_frames),
        (rec_skus,  rec_names,  rec_frames),
        props.get("recommended_products", []),
        props.get("Items", []),
    )


def main(lookback_days=180, purchase_window_days=90, t4_delay_days=27, debug=False):
    api_key = os.environ.get("KLAVIYO_API_KEY_TI")
    if not api_key:
        sys.exit("KLAVIYO_API_KEY_TI not set in .env")

    client = KlaviyoClient(api_key, "TI")

    now = datetime.now(timezone.utc)
    t4_start            = now - timedelta(days=lookback_days)
    t4_eligibility_cutoff = now - timedelta(days=t4_delay_days)
    order_start         = t4_start - timedelta(days=60)

    t4_start_iso   = t4_start.strftime("%Y-%m-%dT%H:%M:%SZ")
    order_start_iso = order_start.strftime("%Y-%m-%dT%H:%M:%SZ")
    order_end_iso   = (now + timedelta(days=1)).strftime("%Y-%m-%dT%H:%M:%SZ")
    now_iso         = now.strftime("%Y-%m-%dT%H:%M:%SZ")

    # ------------------------------------------------------------------
    # Step 1: Stream OrderDelivered → eligible profiles + total_shipments
    # ------------------------------------------------------------------
    print(f"\n[1/4] Streaming OrderDelivered events (past {lookback_days} days)...")

    deliveries: dict[str, list[datetime]] = defaultdict(list)
    multi_shipment_profiles: set[str] = set()
    total_delivered_events = 0

    def handle_delivery(ev):
        nonlocal total_delivered_events
        pid = profile_id_of(ev)
        dt  = parse_dt(ev)
        props = ev.get("attributes", {}).get("event_properties", {})
        funnel = props.get("funnel", "")
        if pid and dt and funnel != "swatch":
            total_delivered_events += 1
            deliveries[pid].append(dt)
            # total_shipments = 1 filter: Klaviyo flow only sends to first-time deliveries
            total_shipments = props.get("total_shipments", 1)
            try:
                if int(total_shipments) > 1:
                    multi_shipment_profiles.add(pid)
            except (TypeError, ValueError):
                pass

    stream_metric(client, ORDER_DELIVERED, t4_start_iso, now_iso, handle_delivery)

    # Exclude profiles whose ONLY deliveries are within the T4 delay window
    recent_only_profiles = 0
    eligible_deliveries: dict[str, list[datetime]] = {}
    for pid, dts in deliveries.items():
        old_enough = [d for d in dts if d <= t4_eligibility_cutoff]
        if old_enough:
            eligible_deliveries[pid] = old_enough
        else:
            recent_only_profiles += 1

    eligible_pids = set(eligible_deliveries.keys())
    multi_shipment_eligible = multi_shipment_profiles & eligible_pids

    print(f"  Non-swatch OrderDelivered events: {total_delivered_events:,}")
    print(f"  Unique non-swatch profiles:       {len(deliveries):,}")
    print(f"  Excluded — delivery < {t4_delay_days}d ago:  {recent_only_profiles:,}")
    print(f"  Eligible (delivery >= {t4_delay_days}d ago): {len(eligible_pids):,}")
    print(f"    Of which total_shipments > 1:   {len(multi_shipment_eligible):,}  (flow skips these)")

    # ------------------------------------------------------------------
    # Step 2: Stream cancellations / refunds / unsubscribes globally
    # ------------------------------------------------------------------
    print(f"\n[2/4] Streaming cancellations, refunds, and unsubscribes...")

    cancelled_pids:   set[str] = set()
    refunded_pids:    set[str] = set()
    unsub_email_pids: set[str] = set()

    def collect_pids(target_set):
        def _cb(ev):
            pid = profile_id_of(ev)
            if pid and pid in eligible_pids:
                target_set.add(pid)
        return _cb

    for metric_id in (ORDER_CANCELLED_API, ORDER_CANCELLED_SHP):
        stream_metric(client, metric_id, t4_start_iso, now_iso, collect_pids(cancelled_pids))

    for metric_id in (ORDER_REFUNDED_API, ORDER_REFUNDED_SHP):
        stream_metric(client, metric_id, t4_start_iso, now_iso, collect_pids(refunded_pids))

    for metric_id in (UNSUB_EMAIL, UNSUB_LIST):
        stream_metric(client, metric_id, t4_start_iso, now_iso, collect_pids(unsub_email_pids))

    # Mutual-exclusion for funnel clarity (each profile counted in first bucket only)
    multi_only     = multi_shipment_eligible - cancelled_pids - refunded_pids - unsub_email_pids
    cancelled_only = cancelled_pids - multi_shipment_eligible
    refunded_only  = refunded_pids  - multi_shipment_eligible - cancelled_pids
    unsub_only     = unsub_email_pids - multi_shipment_eligible - cancelled_pids - refunded_pids
    # Profiles excluded for multiple reasons
    excluded_any   = multi_shipment_eligible | cancelled_pids | refunded_pids | unsub_email_pids

    print(f"  Cancelled (overlap w/ eligible):  {len(cancelled_pids):,}")
    print(f"  Refunded  (overlap w/ eligible):  {len(refunded_pids):,}")
    print(f"  Unsubscribed email (overlap):     {len(unsub_email_pids):,}")

    # ------------------------------------------------------------------
    # Step 3: Per-profile T4 receipt check + order query
    # ------------------------------------------------------------------
    print(f"\n[3/4] Querying {len(eligible_pids):,} profiles for T4 receipt and orders...")

    confirmed_t4:    dict[str, datetime] = {}
    orders_by_profile: dict[str, list[dict]] = {}

    for i, (pid, delivery_dts) in enumerate(eligible_deliveries.items(), 1):
        if i % 250 == 0:
            print(f"    ... {i:,}/{len(eligible_pids):,} profiles processed", flush=True)

        received_evs = get_profile_events(client, RECEIVED_EMAIL, pid, t4_start_iso, now_iso)
        for ev in received_evs:
            props = ev.get("attributes", {}).get("event_properties", {})
            if props.get("$message") == T4_MESSAGE_ID:
                dt = parse_dt(ev)
                if dt and (pid not in confirmed_t4 or dt < confirmed_t4[pid]):
                    confirmed_t4[pid] = dt

        if pid not in confirmed_t4:
            continue

        order_evs = get_profile_events(client, ORDER_PLACED, pid, order_start_iso, order_end_iso)
        profile_orders = []
        for ev in order_evs:
            dt, items, recs_parsed, recs, raw_items = parse_order_event(ev)
            if dt:
                profile_orders.append({
                    "datetime":   dt,
                    "item_skus":  items[0], "item_names": items[1], "item_frames": items[2],
                    "rec_skus":   recs_parsed[0], "rec_names": recs_parsed[1], "rec_frames": recs_parsed[2],
                    "recs":       recs,
                    "raw_items":  raw_items,
                })
        profile_orders.sort(key=lambda x: x["datetime"])
        orders_by_profile[pid] = profile_orders

    confirmed_not_excluded = len(confirmed_t4)
    print(f"  Profiles confirmed T4 received: {confirmed_not_excluded:,}")

    # ------------------------------------------------------------------
    # Step 4: Analyze recommendation conversion
    # ------------------------------------------------------------------
    print(f"\n[4/4] Analyzing (purchase window: {purchase_window_days}d after T4)...")

    has_triggering_order = 0
    has_recs = 0
    bought_anything = 0
    bought_rec_sku = bought_rec_name = bought_rec_frame = 0

    rec_category_bought_frame: Counter = Counter()
    rec_product_bought_frame:  Counter = Counter()
    missed_by_category: Counter = Counter()

    debug_buyers: list[dict] = []   # for --debug

    for pid, t4_dt in confirmed_t4.items():
        deadline      = t4_dt + timedelta(days=purchase_window_days)
        profile_orders = orders_by_profile.get(pid, [])

        triggering = next(
            (o for o in reversed(profile_orders) if o["datetime"] <= t4_dt), None
        )
        if not triggering:
            continue
        has_triggering_order += 1

        rec_skus, rec_names, rec_frames, recs = (
            triggering["rec_skus"], triggering["rec_names"],
            triggering["rec_frames"], triggering["recs"],
        )
        if not rec_frames:
            continue
        has_recs += 1

        post_orders = [o for o in profile_orders if t4_dt < o["datetime"] <= deadline]
        if not post_orders:
            for r in recs:
                if isinstance(r, dict):
                    missed_by_category[r.get("category", "Unknown")] += 1
            continue

        bought_anything += 1
        hit_sku = hit_name = hit_frame = False

        for order in post_orders:
            if order["item_skus"] & rec_skus:   hit_sku = True
            if order["item_names"] & rec_names: hit_name = True
            frame_overlap = order["item_frames"] & rec_frames
            if frame_overlap:
                hit_frame = True
                for r in recs:
                    if isinstance(r, dict) and _norm(r.get("frame", "")) in frame_overlap:
                        rec_category_bought_frame[r.get("category", "Unknown")] += 1
                        rec_product_bought_frame[r.get("name", "?")] += 1

        if hit_sku:   bought_rec_sku   += 1
        if hit_name:  bought_rec_name  += 1
        if hit_frame: bought_rec_frame += 1
        else:
            for r in recs:
                if isinstance(r, dict):
                    missed_by_category[r.get("category", "Unknown")] += 1

        if debug:
            debug_buyers.append({
                "pid": pid,
                "t4_dt": t4_dt,
                "triggering_dt": triggering["datetime"],
                "recs": recs,
                "post_orders": post_orders,
                "hit_frame": hit_frame,
            })

    # ------------------------------------------------------------------
    # Report
    # ------------------------------------------------------------------
    def pct(n, d):
        return f"{n/d*100:.1f}%" if d else "—"

    t4_total = len(confirmed_t4)
    total    = len(eligible_pids)

    print("\n" + "=" * 65)
    print("TI T4 RECOMMENDATION CONVERSION ANALYSIS")
    print("=" * 65)
    print(f"Lookback: {lookback_days}d  |  Purchase window: {purchase_window_days}d after T4  |  T4 delay: {t4_delay_days}d")

    print("\n── DELIVERY FUNNEL ──────────────────────────────────────────")
    print(f"  Non-swatch profiles, delivery >= {t4_delay_days}d ago:  {total:>5,}")
    print(f"  Flow skip — total_shipments > 1:           -{len(multi_shipment_eligible):>4,}  ({pct(len(multi_shipment_eligible), total)})")
    print(f"  Flow exit — cancelled/refunded:            -{len(cancelled_pids | refunded_pids):>4,}  ({pct(len(cancelled_pids | refunded_pids), total)})")
    print(f"  Flow skip — unsubscribed from email:       -{len(unsub_email_pids):>4,}  ({pct(len(unsub_email_pids), total)})")
    explained = len(multi_shipment_eligible | cancelled_pids | refunded_pids | unsub_email_pids)
    unexplained = total - t4_total - explained
    print(f"  Explained exclusions (total, may overlap): -{explained:>4,}")
    print(f"  Confirmed T4 received:                      {t4_total:>5,}  ({pct(t4_total, total)})")
    print(f"  Still unaccounted for:                      {max(0, unexplained):>5,}")

    print("\n── RECOMMENDATION ANALYSIS ──────────────────────────────────")
    print(f"  T4 recipients with triggering order:       {has_triggering_order:>5,}  ({pct(has_triggering_order, t4_total)})")
    print(f"  T4 recipients with recommendations:        {has_recs:>5,}  ({pct(has_recs, t4_total)})")
    if has_recs:
        print(f"\n  Of {has_recs:,} recipients with recs (within {purchase_window_days}d):")
        print(f"    Bought ANYTHING:              {bought_anything:>4,}  ({pct(bought_anything, has_recs)})")
        print(f"    Bought rec — frame (broadest):{bought_rec_frame:>4,}  ({pct(bought_rec_frame, has_recs)})")
        print(f"    Bought rec — name:            {bought_rec_name:>4,}  ({pct(bought_rec_name, has_recs)})")
        print(f"    Bought rec — SKU (strictest): {bought_rec_sku:>4,}  ({pct(bought_rec_sku, has_recs)})")
        if bought_anything:
            print(f"    Of buyers, frame match rate:  {bought_rec_frame:>4,}  ({pct(bought_rec_frame, bought_anything)})")

    print("\n  Recommended categories converted (frame):")
    for cat, cnt in rec_category_bought_frame.most_common(10):
        print(f"    {cnt:>4}  {cat}")
    if not rec_category_bought_frame:
        print("    (none)")

    print("\n  Recommended categories NOT purchased (missed — frame):")
    for cat, cnt in missed_by_category.most_common(10):
        print(f"    {cnt:>4}  {cat}")

    # ------------------------------------------------------------------
    # Debug: detail for each buyer
    # ------------------------------------------------------------------
    if debug and debug_buyers:
        print("\n" + "=" * 65)
        print(f"DEBUG — {len(debug_buyers)} buyers, what they were recommended vs. bought")
        print("=" * 65)
        for b in debug_buyers:
            print(f"\nProfile: {b['pid']}")
            print(f"  Triggering order: {b['triggering_dt'].strftime('%Y-%m-%d')}")
            print(f"  T4 received:      {b['t4_dt'].strftime('%Y-%m-%d')}")
            print(f"  Frame match: {'YES' if b['hit_frame'] else 'NO'}")
            print("  Recommended frames:")
            seen = set()
            for r in b["recs"]:
                if isinstance(r, dict):
                    frame = r.get("frame", "?")
                    if frame not in seen:
                        seen.add(frame)
                        print(f"    - {frame}  ({r.get('category','?')})  [{r.get('name','')}]")
            print("  Bought after T4:")
            for o in b["post_orders"]:
                print(f"    {o['datetime'].strftime('%Y-%m-%d')}:")
                for item in o.get("raw_items", []):
                    if isinstance(item, dict):
                        print(f"      • {item.get('name','?')}  frame={item.get('frame','?')}  cat={item.get('category','?')}")

    print("\nDone.")


if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("--days",     type=int,  default=180)
    parser.add_argument("--window",   type=int,  default=90)
    parser.add_argument("--t4-delay", type=int,  default=27)
    parser.add_argument("--debug",    action="store_true")
    args = parser.parse_args()
    main(
        lookback_days=args.days,
        purchase_window_days=args.window,
        t4_delay_days=args.t4_delay,
        debug=args.debug,
    )
