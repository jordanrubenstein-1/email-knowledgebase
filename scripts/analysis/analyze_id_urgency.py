"""
Analyze urgency language in Interior Define email subject lines and preheaders.

Compares open rate and click rate for:
1. All ID emails: urgency vs no urgency
2. Non-sale emails: urgency vs no urgency
3. Mid-sale emails (not final day): urgency vs no urgency
4. End-of-sale emails (final 1-2 days): urgency vs no urgency
"""

import glob
import re
import sys
from datetime import datetime, timedelta
from pathlib import Path

import yaml

sys.path.insert(0, str(Path(__file__).parents[2]))
from scripts.utils.sale_matcher import get_sale_context, load_sale_schedules

# ── Urgency keyword patterns ──────────────────────────────────────────────────
URGENCY_PATTERNS = [
    # Time countdowns
    r"\btoday\s+only\b",
    r"\blast\s+(day|chance|call)\b",
    r"\bend(s|ing)?\s+(today|tonight|soon|now)\b",
    r"\b(only\s+)?\d+\s+days?\s+(left|remaining|only)\b",
    r"\bthree\s+days?\s+(left|remaining|only)\b",
    r"\btwo\s+days?\s+(left|remaining|only)\b",
    r"\bone\s+day\s+(left|remaining|only)\b",
    r"\b(final|last)\s+(day|hours?|chance|call)\b",
    r"\bhours?\s+(left|remaining|only)\b",
    r"\bexpires?\b",
    r"\bcountdown\b",
    r"\bdon'?t\s+(miss|wait)\b",
    r"\bmissed?\s+out\b",
    r"\btime('s| is)?\s+running\s+out\b",
    r"\bwhile\s+(it\s+lasts|supplies\s+last)\b",
    r"\blimited\s+time\b",
    r"\blimited\s+availability\b",
    # Flash / urgent sale terms
    r"\bflash\s+sale\b",
    r"\bflash\s+(deal|offer)\b",
    r"\burgen(t|cy)\b",
    r"\bhurry\b",
    r"\bact\s+(fast|now|quickly)\b",
    r"\bquick(ly)?\b",
    r"\bnow\s+or\s+never\b",
    r"\bdon'?t\s+delay\b",
    r"\bimmediately\b",
    # Scarcity
    r"\bselling\s+(fast|out)\b",
    r"\bgoing\s+fast\b",
    r"\balmostgone?\b",
    r"\b(almost\s+)?sold\s+out\b",
    r"\bfew\s+(left|remaining)\b",
    r"\bonly\s+a\s+few\b",
    r"\blast\s+(few|items?|pieces?|units?)\b",
    r"\bback\s+in\s+stock\b",
]

URGENCY_RE = re.compile("|".join(URGENCY_PATTERNS), re.IGNORECASE)


def has_urgency(subject: str, preheader: str) -> bool:
    text = f"{subject or ''} {preheader or ''}"
    return bool(URGENCY_RE.search(text))


def matched_urgency_terms(subject: str, preheader: str) -> list[str]:
    text = f"{subject or ''} {preheader or ''}"
    return list({m.group(0).lower() for m in URGENCY_RE.finditer(text)})


def parse_date(campaign: dict) -> datetime | None:
    raw = campaign.get("dates", {}).get("first_sent")
    if not raw:
        return None
    try:
        return datetime.fromisoformat(str(raw).replace("Z", "+00:00")).replace(tzinfo=None)
    except Exception:
        return None


def days_before_sale_end(campaign_date: datetime, sale: dict) -> int | None:
    """Return how many days before the sale end the campaign was sent (0 = same day as end)."""
    try:
        end = datetime.strptime(sale["end_date"], "%Y-%m-%d")
    except Exception:
        return None
    delta = (end - campaign_date.replace(hour=0, minute=0, second=0, microsecond=0)).days
    return delta  # 0 = final day, 1 = penultimate day, negative = sent after sale


def load_id_emails() -> list[dict]:
    base = Path(__file__).parents[2] / "campaigns"
    campaigns = []
    for path in sorted(glob.glob(str(base / "*.yaml"))):
        with open(path) as f:
            c = yaml.safe_load(f)
        if not c:
            continue
        if c.get("brand") != "ID":
            continue
        if c.get("channel") != "email":
            continue
        if c.get("braze_type") == "canvas_step":
            continue
        perf = c.get("performance_summary", {})
        sends = perf.get("total_sends", 0) or 0
        if sends < 5000:  # exclude tiny sends (tests / near-zero)
            continue
        campaigns.append(c)
    return campaigns


def stats(group: list[dict]) -> dict:
    if not group:
        return {"n": 0, "open_rate": None, "click_rate": None}
    open_rates = [c["performance_summary"]["open_rate"] for c in group
                  if c.get("performance_summary", {}).get("open_rate") is not None]
    click_rates = [c["performance_summary"]["click_rate"] for c in group
                   if c.get("performance_summary", {}).get("click_rate") is not None]
    return {
        "n": len(group),
        "open_rate": sum(open_rates) / len(open_rates) if open_rates else None,
        "click_rate": sum(click_rates) / len(click_rates) if click_rates else None,
    }


def fmt(s: dict, label: str) -> str:
    if s["n"] == 0:
        return f"  {label}: n=0"
    or_ = f"{s['open_rate']:.1%}" if s["open_rate"] is not None else "n/a"
    cr_ = f"{s['click_rate']:.2%}" if s["click_rate"] is not None else "n/a"
    return f"  {label}: n={s['n']:>3}  opens={or_}  clicks={cr_}"


def delta_label(a: dict, b: dict, metric: str) -> str:
    """Show lift of a over b for a given metric key."""
    va, vb = a.get(metric), b.get(metric)
    if va is None or vb is None or vb == 0:
        return ""
    pct = (va - vb) / vb * 100
    sign = "+" if pct >= 0 else ""
    return f"  ({sign}{pct:.1f}% vs no-urgency)"


def print_comparison(label: str, urgency: list, no_urgency: list) -> None:
    su = stats(urgency)
    sn = stats(no_urgency)
    print(f"\n{'─'*60}")
    print(f"  {label}")
    print(f"{'─'*60}")
    print(fmt(su, "  Urgency   ") + delta_label(su, sn, "open_rate"))
    print(fmt(sn, "  No urgency"))
    cr_delta = delta_label(su, sn, "click_rate")
    print(fmt(su, "  Urgency   ") + delta_label(su, sn, "click_rate"))
    print(fmt(sn, "  No urgency"))


def main():
    print("Loading campaigns and sale schedules…")
    campaigns = load_id_emails()
    sale_schedules = load_sale_schedules()
    print(f"  {len(campaigns)} ID batch emails (≥5K sends)")

    # Tag each campaign
    for c in campaigns:
        sends_list = c.get("sends", [])
        subject = sends_list[0].get("subject", "") if sends_list else ""
        preheader = sends_list[0].get("preheader", "") if sends_list else ""
        c["_urgency"] = has_urgency(subject, preheader)
        c["_urgency_terms"] = matched_urgency_terms(subject, preheader)
        c["_date"] = parse_date(c)
        ctx = get_sale_context(c, sale_schedules)
        c["_sale_ctx"] = ctx

    # ── Segment campaigns ────────────────────────────────────────────────────
    non_sale, mid_sale, end_sale = [], [], []

    for c in campaigns:
        ctx = c["_sale_ctx"]
        date = c["_date"]
        if not ctx["during_sale"]:
            non_sale.append(c)
        else:
            # Check if this is an end-of-sale send (final 2 days)
            primary = ctx.get("primary_sale")
            if primary and date:
                days_left = days_before_sale_end(date, primary)
                if days_left is not None and 0 <= days_left <= 1:
                    end_sale.append(c)
                else:
                    mid_sale.append(c)
            else:
                mid_sale.append(c)

    # ── Print results ─────────────────────────────────────────────────────────
    print("\n" + "=" * 60)
    print("  INTERIOR DEFINE: URGENCY LANGUAGE ANALYSIS")
    print("=" * 60)
    print("\n  Urgency keywords detected in subject line or preheader.")
    print("  Metrics: mean open rate and click rate per group.")

    for label, group in [
        ("ALL ID EMAILS", campaigns),
        ("NON-SALE EMAILS", non_sale),
        ("MID-SALE EMAILS (not final 2 days)", mid_sale),
        ("END-OF-SALE EMAILS (final 1–2 days of sale)", end_sale),
    ]:
        urg = [c for c in group if c["_urgency"]]
        no_urg = [c for c in group if not c["_urgency"]]

        su, sn = stats(urg), stats(no_urg)
        print(f"\n{'═'*60}")
        print(f"  {label}  (total n={len(group)})")
        print(f"{'═'*60}")

        # Open rate row
        or_delta = ""
        if su["open_rate"] and sn["open_rate"]:
            pct = (su["open_rate"] - sn["open_rate"]) / sn["open_rate"] * 100
            or_delta = f"  (urgency {'+' if pct>=0 else ''}{pct:.1f}% vs no-urgency)"
        cr_delta = ""
        if su["click_rate"] and sn["click_rate"]:
            pct = (su["click_rate"] - sn["click_rate"]) / sn["click_rate"] * 100
            cr_delta = f"  (urgency {'+' if pct>=0 else ''}{pct:.1f}% vs no-urgency)"

        print(f"\n  {'Group':<30}  {'n':>4}  {'Open Rate':>10}  {'Click Rate':>10}")
        print(f"  {'-'*30}  {'----':>4}  {'----------':>10}  {'----------':>10}")
        or_u = f"{su['open_rate']:.1%}" if su.get('open_rate') else "—"
        cr_u = f"{su['click_rate']:.2%}" if su.get('click_rate') else "—"
        or_n = f"{sn['open_rate']:.1%}" if sn.get('open_rate') else "—"
        cr_n = f"{sn['click_rate']:.2%}" if sn.get('click_rate') else "—"
        print(f"  {'Urgency language':<30}  {su['n']:>4}  {or_u:>10}  {cr_u:>10}")
        print(f"  {'No urgency language':<30}  {sn['n']:>4}  {or_n:>10}  {cr_n:>10}")
        if or_delta:
            print(f"\n  Open rate delta: {or_delta.strip()}")
        if cr_delta:
            print(f"  Click rate delta: {cr_delta.strip()}")

    # ── Granular end-of-sale breakdown ────────────────────────────────────────
    print(f"\n{'═'*60}")
    print("  END-OF-SALE: FINAL DAY vs PENULTIMATE DAY")
    print(f"{'═'*60}")

    for days_left, day_label in [(0, "Final day of sale"), (1, "Penultimate day (D-1)")]:
        group = []
        for c in campaigns:
            ctx = c["_sale_ctx"]
            date = c["_date"]
            if not ctx["during_sale"]:
                continue
            primary = ctx.get("primary_sale")
            if primary and date:
                dl = days_before_sale_end(date, primary)
                if dl == days_left:
                    group.append(c)

        urg = [c for c in group if c["_urgency"]]
        no_urg = [c for c in group if not c["_urgency"]]
        su, sn = stats(urg), stats(no_urg)

        print(f"\n  {day_label}  (total n={len(group)})")
        print(f"  {'Group':<30}  {'n':>4}  {'Open Rate':>10}  {'Click Rate':>10}")
        print(f"  {'-'*30}  {'----':>4}  {'----------':>10}  {'----------':>10}")
        or_u = f"{su['open_rate']:.1%}" if su.get('open_rate') else "—"
        cr_u = f"{su['click_rate']:.2%}" if su.get('click_rate') else "—"
        or_n = f"{sn['open_rate']:.1%}" if sn.get('open_rate') else "—"
        cr_n = f"{sn['click_rate']:.2%}" if sn.get('click_rate') else "—"
        print(f"  {'Urgency language':<30}  {su['n']:>4}  {or_u:>10}  {cr_u:>10}")
        print(f"  {'No urgency language':<30}  {sn['n']:>4}  {or_n:>10}  {cr_n:>10}")

    # ── Urgency terms frequency ───────────────────────────────────────────────
    print(f"\n{'═'*60}")
    print("  MOST COMMON URGENCY TERMS (ID emails with urgency language)")
    print(f"{'═'*60}")
    term_counts: dict[str, int] = {}
    for c in campaigns:
        for t in c["_urgency_terms"]:
            term_counts[t] = term_counts.get(t, 0) + 1
    for term, count in sorted(term_counts.items(), key=lambda x: -x[1])[:20]:
        print(f"  {count:>3}x  {term}")

    # ── Example campaigns ─────────────────────────────────────────────────────
    print(f"\n{'═'*60}")
    print("  SAMPLE URGENCY SUBJECT LINES (end-of-sale only, sorted by open rate desc)")
    print(f"{'═'*60}")
    eos_urgency = [c for c in end_sale if c["_urgency"]]
    eos_urgency.sort(key=lambda c: c.get("performance_summary", {}).get("open_rate", 0) or 0, reverse=True)
    for c in eos_urgency[:10]:
        sends_list = c.get("sends", [])
        subject = sends_list[0].get("subject", "") if sends_list else ""
        preheader = sends_list[0].get("preheader", "") if sends_list else ""
        perf = c.get("performance_summary", {})
        or_ = perf.get("open_rate", 0) or 0
        cr_ = perf.get("click_rate", 0) or 0
        date = c.get("dates", {}).get("first_sent", "")[:10]
        terms = ", ".join(c["_urgency_terms"][:3])
        print(f"\n  [{date}] opens={or_:.1%}  clicks={cr_:.2%}  [{terms}]")
        print(f"  SL: {subject}")
        print(f"  PH: {preheader}")

    print(f"\n{'═'*60}")
    print("  SAMPLE NON-URGENCY SUBJECT LINES (end-of-sale only, sorted by open rate desc)")
    print(f"{'═'*60}")
    eos_no_urgency = [c for c in end_sale if not c["_urgency"]]
    eos_no_urgency.sort(key=lambda c: c.get("performance_summary", {}).get("open_rate", 0) or 0, reverse=True)
    for c in eos_no_urgency[:10]:
        sends_list = c.get("sends", [])
        subject = sends_list[0].get("subject", "") if sends_list else ""
        preheader = sends_list[0].get("preheader", "") if sends_list else ""
        perf = c.get("performance_summary", {})
        or_ = perf.get("open_rate", 0) or 0
        cr_ = perf.get("click_rate", 0) or 0
        date = c.get("dates", {}).get("first_sent", "")[:10]
        print(f"\n  [{date}] opens={or_:.1%}  clicks={cr_:.2%}")
        print(f"  SL: {subject}")
        print(f"  PH: {preheader}")


if __name__ == "__main__":
    main()
