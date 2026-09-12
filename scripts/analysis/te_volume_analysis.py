"""
TE (The Expert) email campaign volume analysis.
Part 1: Monthly sending volume Jan 2026 - Jun 2026 (all TE campaigns)
Part 2: TE trade campaigns all time (name contains "trade")
"""

import os
import yaml
from collections import defaultdict
from datetime import datetime, date

CAMPAIGNS_DIR = os.path.join(os.path.dirname(__file__), '../../campaigns')


def load_te_campaigns():
    campaigns = []
    for fname in os.listdir(CAMPAIGNS_DIR):
        if not fname.endswith('.yaml'):
            continue
        fpath = os.path.join(CAMPAIGNS_DIR, fname)
        try:
            with open(fpath, 'r') as f:
                data = yaml.safe_load(f)
        except Exception:
            continue
        if not isinstance(data, dict):
            continue
        if data.get('brand') != 'TE':
            continue
        campaigns.append(data)
    return campaigns


def get_send_date(c):
    """Return send_date as date object, or None."""
    dates = c.get('dates', {})
    sd = dates.get('send_date') if isinstance(dates, dict) else None
    if sd:
        if isinstance(sd, date):
            return sd
        try:
            return datetime.strptime(str(sd), '%Y-%m-%d').date()
        except Exception:
            pass
    return None


def get_total_sends(c):
    ps = c.get('performance_summary', {})
    if isinstance(ps, dict):
        return ps.get('total_sends', 0) or 0
    return 0


def part1_monthly_volume(campaigns):
    """All TE campaigns Jan 2026 - Jun 17 2026, grouped by month."""
    print("=" * 70)
    print("PART 1: TE Monthly Sending Volume (Jan 2026 – Jun 2026)")
    print("=" * 70)

    start = date(2026, 1, 1)
    end = date(2026, 6, 17)

    monthly = defaultdict(lambda: {'sends': 0, 'with_data': 0, 'without_data': 0, 'campaigns': []})

    for c in campaigns:
        sd = get_send_date(c)
        if sd is None or sd < start or sd > end:
            continue
        month_key = sd.strftime('%Y-%m')
        total = get_total_sends(c)
        monthly[month_key]['campaigns'].append(c)
        monthly[month_key]['sends'] += total
        if total > 0:
            monthly[month_key]['with_data'] += 1
        else:
            monthly[month_key]['without_data'] += 1

    print(f"\n{'Month':<12} {'Total Sends':>12} {'w/ Analytics':>14} {'No Analytics':>14} {'Total Campaigns':>16}")
    print("-" * 72)

    grand_sends = 0
    grand_with = 0
    grand_without = 0
    grand_total = 0

    for month_key in sorted(monthly.keys()):
        m = monthly[month_key]
        total_campaigns = m['with_data'] + m['without_data']
        print(f"{month_key:<12} {m['sends']:>12,} {m['with_data']:>14} {m['without_data']:>14} {total_campaigns:>16}")
        grand_sends += m['sends']
        grand_with += m['with_data']
        grand_without += m['without_data']
        grand_total += total_campaigns

    print("-" * 72)
    print(f"{'TOTAL':<12} {grand_sends:>12,} {grand_with:>14} {grand_without:>14} {grand_total:>16}")
    print(f"\nNote: 'No Analytics' campaigns have total_sends=0 (rate-limited Klaviyo API).")
    print(f"Campaigns with data show actual list sizes.")

    # Show per-month campaigns with data for context
    print("\n--- Monthly campaign breakdown (with analytics only) ---")
    for month_key in sorted(monthly.keys()):
        m = monthly[month_key]
        with_data = [(c.get('name','?'), get_total_sends(c)) for c in m['campaigns'] if get_total_sends(c) > 0]
        if not with_data:
            print(f"\n{month_key}: No campaigns with analytics data")
            continue
        print(f"\n{month_key}:")
        for name, sends in sorted(with_data, key=lambda x: -x[1]):
            is_trade = 'trade' in name.lower()
            tag = ' [TRADE]' if is_trade else ''
            print(f"  {sends:>8,}  {name}{tag}")


def part2_trade_campaigns(campaigns):
    """TE trade campaigns all time."""
    print("\n\n" + "=" * 70)
    print("PART 2: TE Trade Campaigns — All Time")
    print("=" * 70)

    trade = [c for c in campaigns if 'trade' in (c.get('name') or '').lower()]
    trade_with_data = [c for c in trade if get_total_sends(c) > 0]
    trade_no_data = [c for c in trade if get_total_sends(c) == 0]

    print(f"\nTotal trade campaigns found: {len(trade)}")
    print(f"  With analytics data: {len(trade_with_data)}")
    print(f"  No analytics (total_sends=0): {len(trade_no_data)}")

    if not trade:
        print("No trade campaigns found.")
        return

    # Sort by send_date; put None dates at the end
    def sort_key(c):
        sd = get_send_date(c)
        return sd if sd else date(9999, 12, 31)

    trade_sorted = sorted(trade, key=sort_key)

    # First appearance
    first_with_date = next((c for c in trade_sorted if get_send_date(c)), None)
    if first_with_date:
        print(f"  First trade send: {get_send_date(first_with_date)} — {first_with_date.get('name','?')}")

    print(f"\n{'Date':<14} {'Sends':>8}  Campaign Name")
    print("-" * 80)

    # Group by month to detect pruning
    monthly_trade = defaultdict(list)
    for c in trade_sorted:
        sd = get_send_date(c)
        total = get_total_sends(c)
        date_str = str(sd) if sd else 'Unknown'
        month_key = sd.strftime('%Y-%m') if sd else 'Unknown'
        print(f"{date_str:<14} {total:>8,}  {c.get('name','?')}")
        if total > 0 and sd:
            monthly_trade[month_key].append(total)

    # Monthly averages for trade sends with data
    print("\n--- Monthly trade avg send size (campaigns with analytics) ---")
    print(f"\n{'Month':<12} {'Campaigns':>10} {'Avg Sends':>12} {'Min':>10} {'Max':>10}")
    print("-" * 58)

    prev_avg = None
    for month_key in sorted(monthly_trade.keys()):
        vals = monthly_trade[month_key]
        avg = sum(vals) / len(vals)
        flag = ''
        if prev_avg and avg < prev_avg * 0.8:
            flag = ' *** DROP'
        elif prev_avg and avg > prev_avg * 1.2:
            flag = ' *** GROWTH'
        print(f"{month_key:<12} {len(vals):>10} {avg:>12,.0f} {min(vals):>10,} {max(vals):>10,}{flag}")
        prev_avg = avg

    # No-data trade campaigns (listed separately)
    if trade_no_data:
        print(f"\n--- Trade campaigns with no analytics data ({len(trade_no_data)} campaigns) ---")
        for c in sorted(trade_no_data, key=sort_key):
            sd = get_send_date(c)
            print(f"  {str(sd) if sd else 'Unknown':<14}  {c.get('name','?')}")


def main():
    print("Loading TE campaigns from YAML knowledgebase...")
    campaigns = load_te_campaigns()
    print(f"Total TE campaigns loaded: {len(campaigns)}\n")

    part1_monthly_volume(campaigns)
    part2_trade_campaigns(campaigns)


if __name__ == '__main__':
    main()
