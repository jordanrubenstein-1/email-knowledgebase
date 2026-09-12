# Email Holdout Test Analysis

**Test Period:** January 14, 2026 – 2026-04-01
**Brands:** Burrow (BW), Havenly Pre-Converted (HAV PC)
**Data Sources:** Burrow & HAV — Braze Raw Events Datashare (Snowflake)

> **Note on HAV PC:** Starting March 11, the holdout group's frequency was reduced further (from ~15% below control to ~22% below control). Section 4 breaks performance into two periods to isolate the effect of this change.

---

## 1. Test Design

The holdout frequency test splits each brand's email list into two groups. The **control group** receives the full email cadence. The **holdout group** is excluded from certain sends, resulting in a lower frequency. Cohort membership is defined by two Braze campaign API IDs per brand: one sent to the entire test universe and one sent exclusively to the control group. The cohort is fixed — users who joined the list after January 14 are not included.

Split sizes: HAV PC — 80% control / 20% holdout; Burrow — 79% control / 21% holdout.

---

## 2. Send Frequency (cumulative to Apr 1)

| Brand | Period | Control Sends/User | Holdout Sends/User | Reduction |
|-------|--------|-------------------|-------------------|-----------|
| HAV PC | Full test (Jan 14–Apr 1) | 49.6 | 41.2 | −17.0% |
| HAV PC | P1: Jan 14–Mar 10 (55 days) | 36.3 | 30.7 | −15.4% |
| HAV PC | P2: Mar 11–Apr 1 (22 days) | 13.3 | 10.4 | −21.8% |
| Burrow | Full test (Jan 14–Apr 1) | 58.6 | 44.3 | −24.4% |

**Weekly send rates (normalized):**

| Brand / Period | Control/week | Holdout/week |
|----------------|-------------|-------------|
| HAV PC P1 | 4.6 | 3.9 |
| HAV PC P2 | 4.2 | 3.3 |
| Burrow (full) | 5.4 | 4.1 |

---

## 3. Overall Performance Results

### 3a. Havenly Pre-Converted (HAV PC) — Cumulative

| Metric | Control | Holdout | Delta |
|--------|---------|---------|-------|
| Users | 202,041 | 52,616 | — |
| Converters | 465 | 216 | — |
| Conversion Rate | 0.230% | 0.411% | **+78.3%** |
| Clickers | 13,066 | 3,641 | — |
| Clicker Rate | 6.47% | 6.92% | **+7.0%** |

### 3b. Burrow (BW) — Cumulative

| Metric | Control | Holdout | Delta |
|--------|---------|---------|-------|
| Users | 187,362 | 50,111 | — |
| Purchasers | 483 | 119 | — |
| Purchase Rate | 0.258% | 0.237% | −8.1% |
| Total Revenue | $715,877 | $174,866 | — |
| Revenue/User | $3.82 | $3.49 | −8.6% |
| AOV | $687.68 | $560.47 | −18.5% |

---

## 4. HAV PC: Period-Split Analysis

### Did the further frequency reduction (Mar 11+) help or hurt?

**Period 1: Jan 14 – Mar 10** (55 days, holdout ~3.9 emails/week vs control ~4.6/week)

| Metric | Control | Holdout | Delta | Significance |
|--------|---------|---------|-------|--------------|
| Conversion Rate | 0.180% | 0.369% | **+104.5%** | Significant (>99.9%) |
| Clicker Rate | 5.34% | 6.04% | **+13.2%** | Significant (>99.9%) |

**Period 2: Mar 11 – Apr 1** (22 days, holdout ~3.3 emails/week vs control ~4.2/week)

| Metric | Control | Holdout | Delta | Significance |
|--------|---------|---------|-------|--------------|
| Conversion Rate | 0.054% | 0.048% | −11.9% | Not significant (p=0.57) |
| Clicker Rate | 1.81% | 1.60% | **−12.0%** | Significant (>99.9%) — wrong direction |

### Interpretation

In Period 1, the holdout had a clear, highly significant advantage on both metrics — users receiving fewer emails converted and clicked at higher rates, consistent with the core hypothesis that over-sending suppresses engagement.

In Period 2, that advantage disappeared and reversed:
- Clicker rate flipped significantly in favor of the control (z = 3.38, p < 0.001). Users receiving *more* emails were more likely to click at least once in the period.
- Conversion rate also flipped directionally but the difference is not statistically significant (too few conversions over 22 days to conclude).

**The most likely explanation:** the initial reduction (~3.9/week holdout vs ~4.6/week control) hit the sweet spot — enough reduction to relieve fatigue and improve per-email engagement, but frequent enough to maintain conversion momentum. The further cut to ~3.3/week appears to have crossed a threshold where reduced send volume outweighs the per-email engagement lift, causing holdout users to miss out on enough touchpoints to suppress conversions and clicks.

The initial, less drastic reduction was better.

---

## 5. Statistical Significance (cumulative)

Z-test for two proportions (two-tailed, α = 0.05). Revenue/User uses Welch's t-test.

| Brand | Metric | Stat | p-value | Confidence | Direction |
|-------|--------|------|---------|------------|-----------|
| HAV PC | Conversion Rate | z = −7.13 | ~0.000 | **>99.9%** | Holdout higher ✓ |
| HAV PC | Clicker Rate | z = −3.74 | ~0.000 | **>99.9%** | Holdout higher ✓ |
| HAV PC P1 | Conversion Rate | z = −8.24 | ~0.000 | **>99.9%** | Holdout higher ✓ |
| HAV PC P1 | Clicker Rate | z = −6.32 | ~0.000 | **>99.9%** | Holdout higher ✓ |
| HAV PC P2 | Conversion Rate | z = 0.57 | 0.57 | ~43% | Control higher (n.s.) |
| HAV PC P2 | Clicker Rate | z = 3.38 | 0.001 | **>99.9%** | Control higher ✗ |
| BW | Purchase Rate | z = 0.80 | 0.42 | ~58% | Control higher (n.s.) |
| BW | Revenue/User | t = 0.61 | 0.54 | ~46% | Control higher (n.s.) |

---

## 6. Incremental Impact Analysis

### Havenly Pre-Converted (HAV PC)

The holdout group converts at 1.79× the control rate (0.411% vs 0.230%).

- Holdout advantage per user: +0.181 percentage points
- If the entire HAV PC population (254,657 users) converted at the holdout rate instead of the control rate: **+461 additional conversions** over the test window.

### Burrow (BW)

No statistically significant difference in purchase rate or revenue/user. Control has a small numeric advantage ($3.82 vs $3.49/user) but this is well within noise (p=0.54). Email is not clearly driving incremental purchases — nor is reducing frequency clearly hurting them.

---

## 7. Changes from Last Report (Mar 6 → Apr 1)

| Brand | Metric | Mar 6 | Apr 1 | Trend |
|-------|--------|-------|-------|-------|
| HAV PC | Conversion rate delta | +106.2% | +78.3% | Narrowing |
| HAV PC | Clicker rate delta | +13.9% | +7.0% | Narrowing |
| HAV PC | Ctrl sends/user | 34.98 | 49.6 | More sends (longer window) |
| HAV PC | Holdout sends/user | 29.44 | 41.2 | More sends (longer window) |
| HAV PC | p-value (conversion) | ~0.000 | ~0.000 | Still highly significant |
| BW | Purchase rate delta | −19.4% | −8.1% | Narrowing toward parity |
| BW | Revenue/user delta | −24.5% | −8.6% | Narrowing toward parity |
| BW | p-value (purchase rate) | 0.080 | 0.42 | Well above 0.05 |

---

## 8. Key Takeaways

### Havenly Pre-Converted (HAV PC)

The holdout continues to outperform the control over the full test window — conversion rate is +78% higher (vs +106% in March), and clicker rate is +7% higher. Both remain highly statistically significant. **The overall direction of the test is clear: current email frequency is suppressing conversions for this segment.**

However, the period-split analysis reveals an important nuance: the *further* frequency reduction introduced March 11 appears to have crossed a threshold. In the first 55 days (holdout ~3.9/week), the holdout advantage was strong (+104% conversion, +13% clicks). In the subsequent 22 days (holdout ~3.3/week), the advantage not only disappeared but reversed on clicker rate significantly.

**Recommendation:** The optimal frequency for HAV PC appears to be closer to the Period 1 holdout level (~3.9 emails/week), not the further-reduced Period 2 level (~3.3/week). Consider pulling back to the P1 cadence for the holdout group.

### Burrow (BW)

Neither purchase rate nor revenue/user shows a statistically significant difference as of April 1. The control's numeric advantage has collapsed from −19% to −8% on purchase rate and −24% to −9% on revenue/user — essentially noise. Email frequency does not appear to be incrementally driving purchases for BW at current cadence levels.

---

*Report generated: 2026-04-01. Test window: January 14, 2026 – 2026-04-01.*
