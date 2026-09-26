"""Calculate statistical significance for STO/IT test results."""
import math

def two_prop_z_test(n1, p1, n2, p2):
    """Two-proportion z-test. Returns z-score and two-tailed p-value."""
    if n1 == 0 or n2 == 0:
        return 0, 1.0
    p_pool = (n1 * p1 + n2 * p2) / (n1 + n2)
    if p_pool == 0 or p_pool == 1:
        return 0, 1.0
    se = math.sqrt(p_pool * (1 - p_pool) * (1/n1 + 1/n2))
    if se == 0:
        return 0, 1.0
    z = (p1 - p2) / se
    # Approximate two-tailed p-value using normal CDF
    p_value = 2 * (1 - normal_cdf(abs(z)))
    return z, p_value

def normal_cdf(x):
    """Approximate standard normal CDF."""
    return 0.5 * (1 + math.erf(x / math.sqrt(2)))

def sig_label(p):
    if p < 0.01:
        return "***"
    elif p < 0.05:
        return "**"
    elif p < 0.10:
        return "*"
    else:
        return ""

def format_pct(val):
    return f"{val*100:.2f}%"

# All test data: (label, control_sends, control_metric, sto_sends, sto_metric)
# For rate metrics we pass (sends, rate)
# For count metrics we pass (sends, count/sends) to get a rate

tests = [
    {
        "name": "BUR Collection Spotlight (2/4)",
        "metrics": {
            "Open Rate":    (118227, 0.5293, 117294, 0.5361),
            "Click Rate":   (118227, 221/118227, 117294, 262/117294),
            "Unsub Rate":   (118227, 137/118227, 117294, 129/117294),
        }
    },
    {
        "name": "BUR Loving Leather (2/22)",
        "metrics": {
            "Open Rate":    (118022, 0.5208, 116751, 0.5236),
            "Click Rate":   (118022, 203/118022, 116751, 235/116751),
            "Unsub Rate":   (118022, 87/118022, 116751, 90/116751),
        }
    },
    {
        "name": "HAV Why Havenly PT (2/12)",
        "metrics": {
            "Open Rate":    (130552, 0.3958, 130750, 0.3928),
            "Click Rate":   (130552, 276/130552, 130750, 273/130750),
            "Unsub Rate":   (130552, 216/130552, 130750, 195/130750),
        }
    },
    {
        "name": "HAV Social Proof (2/22)",
        "metrics": {
            "Open Rate":    (132423, 0.3725, 132729, 0.3694),
            "Click Rate":   (132423, 204/132423, 132729, 185/132729),
            "Unsub Rate":   (132423, 188/132423, 132729, 164/132729),
        }
    },
    {
        "name": "HAV CONV Items in Design (2/22)",
        "metrics": {
            "Open Rate":    (4112, 0.5409, 4152, 0.5539),
            "Click Rate":   (4112, 46/4112, 4152, 41/4152),
            "Unsub Rate":   (4112, 5/4112, 4152, 11/4152),
        }
    },
    {
        "name": "CZ Catalog (2/12)",
        "metrics": {
            "Open Rate":    (57380, 0.5030, 57274, 0.4934),
            "Click Rate":   (57380, 418/57380, 57274, 449/57274),
            "Unsub Rate":   (57380, 77/57380, 57274, 56/57274),
        }
    },
    {
        "name": "CZ Entryway (2/21)",
        "metrics": {
            "Open Rate":    (28874, 0.4858, 29091, 0.4902),
            "Click Rate":   (28874, 343/28874, 29091, 375/29091),
            "Unsub Rate":   (28874, 51/28874, 29091, 47/29091),
        }
    },
    {
        "name": "CZ Spring Preview (2/26)",
        "metrics": {
            "Open Rate":    (56749, 0.4512, 56746, 0.4461),
            "Click Rate":   (56749, 463/56749, 56746, 470/56746),
            "Unsub Rate":   (56749, 109/56749, 56746, 84/56746),
        }
    },
    {
        "name": "HAV Color Trends (2/20)",
        "metrics": {
            "Open Rate":    (131583, 0.3855, 130951, 0.3917),
            "Click Rate":   (131583, 220/131583, 130951, 240/130951),
            "Unsub Rate":   (131583, 184/131583, 130951, 165/130951),
        }
    },
    {
        "name": "HAV CONV Color Trends (2/20)",
        "metrics": {
            "Open Rate":    (21553, 0.5164, 21613, 0.5111),
            "Click Rate":   (21553, 60/21553, 21613, 65/21613),
            "Unsub Rate":   (21553, 32/21553, 21613, 25/21613),
        }
    },
]

# GA4 metrics (sessions-based rates)
ga4_tests = [
    {
        "name": "BUR Spotlight (2/4) — GA4",
        "metrics": {
            "ATC Rate (of sessions)": (116, 1/116, 202, 7/202),
        }
    },
    {
        "name": "BUR Leather (2/22) — GA4",
        "metrics": {
            "ATC Rate (of sessions)": (110, 4/110, 175, 18/175),
        }
    },
    {
        "name": "CZ Catalog (2/12) — GA4",
        "metrics": {
            "ATC Rate (of sessions)": (424, 61/424, 452, 100/452),
        }
    },
    {
        "name": "CZ Spring (2/26) — GA4",
        "metrics": {
            "ATC Rate (of sessions)": (401, 19/401, 462, 42/462),
        }
    },
]

# Design fee / launch room (QB data — use sends as denominator for rate test)
hav_qb_tests = [
    {
        "name": "HAV Why Hav (2/12) — QB",
        "metrics": {
            "Design Fee Rate": (130552, 16/130552, 130750, 24/130750),
            "Launch Room Rate": (130552, 9/130552, 130750, 11/130750),
        }
    },
    {
        "name": "HAV Social Proof (2/22) — QB",
        "metrics": {
            "Design Fee Rate": (132423, 25/132423, 132729, 24/132729),
            "Launch Room Rate": (132423, 20/132423, 132729, 11/132729),
        }
    },
    {
        "name": "HAV CONV Items (2/22) — QB",
        "metrics": {
            "Design Fee Rate": (4112, 3/4112, 4152, 6/4152),
            "Launch Room Rate": (4112, 10/4112, 4152, 12/4152),
        }
    },
    {
        "name": "HAV Color Trends (2/20) — QB",
        "metrics": {
            "Design Fee Rate": (131583, 22/131583, 130951, 29/130951),
            "Launch Room Rate": (131583, 16/131583, 130951, 23/130951),
        }
    },
    {
        "name": "HAV CONV Color (2/20) — QB",
        "metrics": {
            "Design Fee Rate": (21553, 19/21553, 21613, 21/21613),
            "Launch Room Rate": (21553, 43/21553, 21613, 52/21613),
        }
    },
]

print("=" * 90)
print("BRAZE METRICS — Statistical Significance")
print("=" * 90)
print(f"{'Test':<35} {'Metric':<15} {'Control':>10} {'STO':>10} {'Diff':>10} {'p-value':>10} {'Sig':>5}")
print("-" * 90)

for test in tests:
    for metric_name, (n1, p1, n2, p2) in test["metrics"].items():
        z, p = two_prop_z_test(n1, p1, n2, p2)
        diff = p2 - p1
        sig = sig_label(p)
        print(f"{test['name']:<35} {metric_name:<15} {format_pct(p1):>10} {format_pct(p2):>10} {diff*100:>+9.3f}pp {p:>9.4f} {sig:>5}")
    print()

print("\n" + "=" * 90)
print("GA4 METRICS — Statistical Significance")
print("=" * 90)
print(f"{'Test':<35} {'Metric':<22} {'Control':>10} {'STO':>10} {'p-value':>10} {'Sig':>5}")
print("-" * 90)

for test in ga4_tests:
    for metric_name, (n1, p1, n2, p2) in test["metrics"].items():
        z, p = two_prop_z_test(n1, p1, n2, p2)
        sig = sig_label(p)
        print(f"{test['name']:<35} {metric_name:<22} {format_pct(p1):>10} {format_pct(p2):>10} {p:>9.4f} {sig:>5}")

print("\n" + "=" * 90)
print("HAV QUERY BUILDER — Statistical Significance")
print("=" * 90)
print(f"{'Test':<35} {'Metric':<22} {'Ctrl #':>8} {'STO #':>8} {'p-value':>10} {'Sig':>5}")
print("-" * 90)

for test in hav_qb_tests:
    for metric_name, (n1, p1, n2, p2) in test["metrics"].items():
        z, p = two_prop_z_test(n1, p1, n2, p2)
        count1 = round(n1 * p1)
        count2 = round(n2 * p2)
        sig = sig_label(p)
        print(f"{test['name']:<35} {metric_name:<22} {count1:>8} {count2:>8} {p:>9.4f} {sig:>5}")

# ============================================================
# POOLED AGGREGATE ANALYSIS — All sends combined
# ============================================================

print("\n\n" + "=" * 90)
print("POOLED AGGREGATE — All STO vs All Control (Braze Metrics)")
print("=" * 90)
print(f"{'Metric':<20} {'Ctrl Sends':>12} {'Ctrl Count':>12} {'Ctrl Rate':>10} {'STO Sends':>12} {'STO Count':>12} {'STO Rate':>10} {'Diff':>10} {'p-value':>10} {'Sig':>5}")
print("-" * 120)

# Collect raw counts for pooling
# We need actual counts, not just rates, so compute count = n * rate
braze_metrics = ["Open Rate", "Click Rate", "Unsub Rate"]
for metric in braze_metrics:
    ctrl_sends_total = 0
    ctrl_count_total = 0
    sto_sends_total = 0
    sto_count_total = 0
    for test in tests:
        n1, p1, n2, p2 = test["metrics"][metric]
        ctrl_sends_total += n1
        ctrl_count_total += round(n1 * p1)
        sto_sends_total += n2
        sto_count_total += round(n2 * p2)
    ctrl_rate = ctrl_count_total / ctrl_sends_total
    sto_rate = sto_count_total / sto_sends_total
    z, p = two_prop_z_test(ctrl_sends_total, ctrl_rate, sto_sends_total, sto_rate)
    diff = sto_rate - ctrl_rate
    sig = sig_label(p)
    print(f"{metric:<20} {ctrl_sends_total:>12,} {ctrl_count_total:>12,} {format_pct(ctrl_rate):>10} {sto_sends_total:>12,} {sto_count_total:>12,} {format_pct(sto_rate):>10} {diff*100:>+9.3f}pp {p:>9.4f} {sig:>5}")

# Pooled by brand
print("\n\n" + "=" * 90)
print("POOLED BY BRAND — STO vs Control (Braze Metrics)")
print("=" * 90)

brand_groups = {
    "BUR (2 tests)": [t for t in tests if t["name"].startswith("BUR")],
    "HAV DPS (3 tests)": [t for t in tests if t["name"].startswith("HAV") and "CONV" not in t["name"]],
    "HAV CONV (2 tests)": [t for t in tests if "CONV" in t["name"]],
    "CZ (3 tests)": [t for t in tests if t["name"].startswith("CZ")],
}

print(f"{'Brand':<22} {'Metric':<15} {'Ctrl Rate':>10} {'STO Rate':>10} {'Diff':>10} {'p-value':>10} {'Sig':>5}")
print("-" * 90)

for brand_label, brand_tests in brand_groups.items():
    for metric in braze_metrics:
        ctrl_n = 0
        ctrl_count = 0
        sto_n = 0
        sto_count = 0
        for test in brand_tests:
            n1, p1, n2, p2 = test["metrics"][metric]
            ctrl_n += n1
            ctrl_count += round(n1 * p1)
            sto_n += n2
            sto_count += round(n2 * p2)
        ctrl_rate = ctrl_count / ctrl_n if ctrl_n else 0
        sto_rate = sto_count / sto_n if sto_n else 0
        z, p = two_prop_z_test(ctrl_n, ctrl_rate, sto_n, sto_rate)
        diff = sto_rate - ctrl_rate
        sig = sig_label(p)
        print(f"{brand_label:<22} {metric:<15} {format_pct(ctrl_rate):>10} {format_pct(sto_rate):>10} {diff*100:>+9.3f}pp {p:>9.4f} {sig:>5}")
    print()

# Pooled GA4 ATC
print("\n" + "=" * 90)
print("POOLED AGGREGATE — All STO vs All Control (GA4 ATC)")
print("=" * 90)
print(f"{'Scope':<25} {'Ctrl Sess':>10} {'Ctrl ATC':>10} {'Ctrl Rate':>10} {'STO Sess':>10} {'STO ATC':>10} {'STO Rate':>10} {'Diff':>10} {'p-value':>10} {'Sig':>5}")
print("-" * 120)

ctrl_sess = 0
ctrl_atc = 0
sto_sess = 0
sto_atc = 0
for test in ga4_tests:
    n1, p1, n2, p2 = test["metrics"]["ATC Rate (of sessions)"]
    ctrl_sess += n1
    ctrl_atc += round(n1 * p1)
    sto_sess += n2
    sto_atc += round(n2 * p2)

ctrl_rate = ctrl_atc / ctrl_sess
sto_rate = sto_atc / sto_sess
z, p = two_prop_z_test(ctrl_sess, ctrl_rate, sto_sess, sto_rate)
diff = sto_rate - ctrl_rate
sig = sig_label(p)
print(f"{'All brands (4 tests)':<25} {ctrl_sess:>10,} {ctrl_atc:>10,} {format_pct(ctrl_rate):>10} {sto_sess:>10,} {sto_atc:>10,} {format_pct(sto_rate):>10} {diff*100:>+9.3f}pp {p:>9.4f} {sig:>5}")

# Pooled HAV QB
print("\n" + "=" * 90)
print("POOLED AGGREGATE — All STO vs All Control (HAV QB Metrics)")
print("=" * 90)
print(f"{'Scope':<30} {'Metric':<20} {'Ctrl #':>8} {'STO #':>8} {'p-value':>10} {'Sig':>5}")
print("-" * 90)

for metric in ["Design Fee Rate", "Launch Room Rate"]:
    ctrl_n = 0
    ctrl_count = 0
    sto_n = 0
    sto_count = 0
    for test in hav_qb_tests:
        n1, p1, n2, p2 = test["metrics"][metric]
        ctrl_n += n1
        ctrl_count += round(n1 * p1)
        sto_n += n2
        sto_count += round(n2 * p2)
    ctrl_rate = ctrl_count / ctrl_n if ctrl_n else 0
    sto_rate = sto_count / sto_n if sto_n else 0
    z, p = two_prop_z_test(ctrl_n, ctrl_rate, sto_n, sto_rate)
    sig = sig_label(p)
    print(f"{'All HAV (5 tests)':<30} {metric:<20} {ctrl_count:>8} {sto_count:>8} {p:>9.4f} {sig:>5}")
