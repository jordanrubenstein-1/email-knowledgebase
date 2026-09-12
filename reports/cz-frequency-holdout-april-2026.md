# CZ Email Frequency Holdout Test — April 2026

**Test Period:** April 1 – April 30, 2026
**Brand:** The Citizenry (CZ)
**Data Sources:** Braze Raw Events Datashare (Snowflake) · GA4 (Snowflake) · Shopify (Snowflake)

> **Methodology note (updated May 7):** The original version of this report calculated unsubscribe rates as *unsub events / total sends per group*, which produced a spurious 5–7× difference because the control group had ~25% more sends (larger denominator). All engagement metrics in this version are **per-user** (unique users who took an action / group size), matching Jordan Rubenstein's independent verification. Results are materially different — see Section 7.

---

## 1. Test Design

The holdout group was defined using Braze random bucket numbers (0–1999 = holdout, 2000–3999 = control), ensuring random assignment with no selection bias. Both groups represent ~20% of the CZ list. Group membership is derived from Braze segment CSV exports matched to datashare events on `EXTERNAL_USER_ID` and `EMAIL_ADDRESS`.

**Group sizes (from Braze segment exports):**

| Group | Users |
|-------|-------|
| Control (full frequency, buckets 2000–3999) | 23,061 |
| Holdout (reduced frequency, buckets 0–1999) | 22,869 |

**Frequency result:**

| Segment | Control emails/month | Holdout emails/month | Reduction |
|---------|---------------------|---------------------|-----------|
| Full File | 15 | 12 | −20% |
| Engaged | 23 | 17 | −26% |

---

## 2. What the Holdout Group Missed

The following 6 campaigns had the holdout exclusion applied. All Sleep Well Sale sends went to the full list.

| Date | Campaign | Type |
|------|----------|------|
| Apr 1 | April Edit | Editorial |
| Apr 10 | Pillow Pairings | Editorial |
| Apr 13 | Back in Stock | Product |
| Apr 17 | Earth Day Sleep Well Sale | Sale (engaged list) |
| Apr 24 | Spa Towel Guide | Editorial |
| Apr 29 | Archive Sale | Sale |

**Sleep Well Sale (sent to everyone, holdout included):** 7 campaigns Apr 15–27.

> **One execution note:** The Apr 28 Spring Collection Launch was accidentally sent with the holdout filter applied. This was a mistake — it was not marked for holdout exclusion in the Asana task.

---

## 3. Per-User Engagement Results

All metrics are unique users / group size. Shopify orders are matched on email address (Braze purchase events for CZ ended Aug 2025).

| Metric | Holdout (n=22,869) | Control (n=23,061) | Delta | p-value | Sig? |
|--------|-------------------|--------------------|-------|---------|------|
| % opened any email | 18.09% | 18.47% | −0.38pp | 0.294 | No |
| % clicked any email | 7.65% | 8.56% | −0.91pp | <0.001 | Yes |
| % unsubscribed | 1.87% | 2.14% | −0.27pp | 0.036 | Yes |
| % made a purchase | 0.68% | 0.71% | −0.02pp | 0.750 | No |
| Rev/user (MWU) | $3.24 | $3.02 | +$0.22 | 0.747 | No |
| AOV (MWU) | $474.61 | $426.87 | +$47.74 | 0.396 | No |

**Total revenue:** Holdout $74,039 · Control $69,579 (not statistically different)

**Key finding:** The control group (more emails) had significantly more unique clickers. There is no significant difference in opens, purchases, or revenue. The holdout unsubscribed at a slightly *lower* rate than the control — the opposite of the original report's conclusion.

---

## 4. Statistical Significance

Z-test for two proportions (two-tailed, α = 0.05). Revenue/user and AOV use Mann-Whitney U (non-normal, zero-inflated distributions).

| Metric | z / U stat | p-value | Significant? | Direction |
|--------|-----------|---------|--------------|-----------|
| Open rate | — | 0.294 | No | — |
| **Click rate** | — | **<0.001** | **Yes** | **Control higher** |
| **Unsub rate** | — | **0.036** | **Yes** | **Holdout higher (fewer unsubs)** |
| Purchase rate | — | 0.750 | No | — |
| Rev/user | MWU | 0.747 | No | — |
| AOV | MWU | 0.396 | No | — |

---

## 5. Revenue & Sessions (GA4)

### Total email channel — April 2026

| Metric | Value |
|--------|-------|
| Total sessions | 22,040 |
| Total purchases | 223 |
| Total revenue | $73,129 |
| Average order value | $328 |

### Top revenue-driving campaigns

| Campaign | Sessions | Revenue | Rev/Session | Holdout received? |
|----------|---------|---------|-------------|-------------------|
| Back in Stock (Apr 26) | 1,599 | $5,643 | $3.53 | ✅ Yes |
| Sleep Well Sale Last Chance (Apr 27) | 598 | $4,435 | $7.42 | ✅ Yes |
| PT Spring Sale Reminder (Apr 25) | 919 | $4,320 | $4.70 | ✅ Yes |
| Archive Sale (Apr 15) | 1,442 | $4,064 | $2.82 | ✅ Yes |
| Sleep Well Sale Reminder (Apr 19) | 572 | $3,851 | $6.73 | ✅ Yes |
| Sleep Well Sale Launch (Apr 16) | 792 | $2,410 | $3.04 | ✅ Yes |
| Back in Stock (Apr 13) | 1,033 | $1,560 | $1.51 | ❌ No (holdout excluded) |
| Archive Sale (Apr 29) | 1,118 | $1,763 | $1.58 | ❌ No (holdout excluded) |

The Sleep Well Sale drove **$23,548 (32% of April email revenue)** — and the holdout group received every email in that series.

### Estimated revenue impact on holdout group

The 6 intentionally withheld campaigns generated a combined **$7,922 in revenue** across **5,172 sessions**. Based on the holdout group's share of each campaign's audience, the estimated direct revenue missed by the holdout group is approximately **~$1,800–$2,000** (~2.5% of total April email revenue).

---

## 6. Does the Test Support the Hypothesis?

**Hypothesis:** Reducing email frequency will increase clicks, sessions, and revenue, and decrease unsubscribes.

| Goal | Result | Verdict |
|------|--------|---------|
| ↑ Clicks | Control (more emails) had significantly more unique clickers (8.56% vs 7.65%, p<0.001) | Contradicted |
| ↑ Sessions & Revenue | No significant difference in purchases or revenue; holdout missed ~$2K in direct revenue | Did not improve |
| ↓ Unsubscribes | Holdout unsubbed at a *lower* rate (1.87% vs 2.14%, p=0.036) — but the difference is small (0.27pp) | Partially supported — marginal |

---

## 7. Conclusion

**The test does not support reducing email frequency for CZ.**

The per-user analysis reverses the original report's headline finding. The holdout group does unsubscribe at a slightly lower rate (1.87% vs 2.14%), but the difference is small in absolute terms — 0.27 percentage points — and is outweighed by a clear, highly significant disadvantage on clicks: the control group had proportionally more unique clickers at every frequency level (8.56% vs 7.65%, p<0.001). There is no meaningful difference in purchases or revenue between the groups.

The data tells a consistent story: more emails reach more people who click, without a purchase or revenue penalty. The unsub advantage of reduced frequency is real but small, and does not translate into better commercial outcomes.

**Recommendation:** Maintain current send frequency for CZ. The test provides no data-backed case for reducing cadence.

---

*Report updated: 2026-05-07 — methodology corrected from per-send to per-user rates, per Jordan Rubenstein's independent analysis (`scripts/analysis/cz_frequency_holdout_april2026.py`, commit af2f8f7).*
*Original report: 2026-05-06. Data: Braze Raw Events Datashare + Shopify (Snowflake) + GA4 (Snowflake) · Test period: Apr 1–30, 2026.*
