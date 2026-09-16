# Lifecycle Analysis Roadmap
> Moving from single-email optimization to lifecycle-level performance

---

## Current State Assessment

### What We Have
- **3,221 campaign-level records** with performance data
- **Campaign metadata**: timing, subject, structure, visual analysis
- **Some flow indicators**: ~135 triggered campaigns identified by name patterns
- **Cadence data**: Brand-level send frequency (7-17 campaigns/week)
- **Canvas import capability**: Can now pull triggered journeys from Braze (see below)

### What We're Missing
- **Subscriber-level data**: No individual engagement history
- **Sequence tracking**: Can't see what emails came before/after
- ~~**Flow vs Campaign distinction**: Only ~2 marked as "Triggered Journey"~~ **RESOLVED** - see Canvas Data section
- **Cohort data**: No signup dates, first purchase dates, customer lifetime value
- **Revenue attribution**: No per-email revenue data
- **Unsubscribe/complaint data**: Only aggregate rates

---

## Canvas Data Gap - RESOLVED

**Issue identified**: The original import only pulled Braze "campaigns" - not "canvases" (multi-step triggered journeys).

**Fix implemented**: Updated `scripts/import_braze.py` to support canvas import:
```bash
# Import canvases alongside campaigns
uv run python scripts/import_braze.py --brand HAV --include-canvases

# Import only canvases
uv run python scripts/import_braze.py --brand HAV --canvases-only
```

### Canvas Inventory by Brand

| Brand | Total Canvases | With Email | Key Flows |
|-------|---------------|------------|-----------|
| HAV | 15 | 9 | Welcome, Cross-brand promo |
| CZ | 38 | **25** | Cart abandon, Browse abandon |
| BUR | 19 | 15 | Abandoned browse, Post-order welcome |
| STF | 14 | 8 | Swatch post-purchase |
| ID | 22 | 8 | Cart abandon |
| **Total** | **108** | **65** | |

**Key insight**: Cart abandonment, welcome series, and browse abandonment flows are implemented as Braze Canvases, not regular campaigns. This data was previously missing from our analysis.

### Canvas vs Campaign Structure

Canvases are multi-step journeys with:
- **Entry triggers**: User events (cart abandon, signup, etc.)
- **Steps**: Sequence of message, delay, decision_split, user_update
- **Multi-email sequences**: E.g., 3-email cart abandon series

The import now captures:
- `braze_type: canvas` - Distinguishes from regular campaigns
- `campaign_type: Triggered Journey` - Marks as automated flow
- `canvas_steps` - Full step sequence for flow analysis
- `sends` - Individual email steps with subjects

---

## Key Finding: Flows Outperform Batches

| Type | Open Rate | Click Rate | Sample |
|------|-----------|------------|--------|
| Flow/Triggered | 49.3% | **1.56%** | 135 |
| Batch | 44.6% | 1.00% | 3,086 |
| **Lift** | +4.7pt | **+56%** | |

This aligns with industry data showing automated flows generate **20x more revenue per recipient** than one-off campaigns ([Klaviyo benchmarks](https://www.klaviyo.com/)).

---

## Brand Cadence Analysis

| Brand | Campaigns/Week | Avg Gap | Assessment |
|-------|----------------|---------|------------|
| HAV | 17.4 | 0.4 days | High frequency - fatigue risk |
| BUR | 11.0 | 0.6 days | High frequency |
| ID | 11.4 | 0.6 days | High frequency |
| CZ | 10.4 | 0.7 days | Moderate |
| STF | 7.2 | 1.0 days | Healthier cadence |

**Industry benchmark**: 5-6 emails/week is typical tolerance threshold before fatigue sets in ([Return Path study](https://www.omnisend.com/blog/email-marketing-frequency/)).

**Hypothesis**: HAV's high frequency (17/week) may explain why individual campaign performance varies - subscribers are fatigued.

---

## Recommended Analysis (with current data)

### 1. Flow Type Performance
Analyze the ~135 flow-like campaigns we can identify:

```
Questions:
- Which flow types perform best? (cart abandon vs welcome vs birthday)
- How do flow performance patterns differ by brand?
- What subject line patterns work in flows vs batches?
```

### 2. Send Sequence Analysis
Using send dates, we can approximate sequence effects:

```
Questions:
- Does campaign N performance depend on days since campaign N-1?
- Is there a "rest period" that improves next-send performance?
- Do back-to-back promos underperform vs promo-content-promo sequences?
```

### 3. Fatigue Indicators
Look for fatigue patterns in the data:

```
Questions:
- Do brands with higher cadence have lower average performance?
- Has performance declined over time as cadence increased?
- Do campaigns perform worse during high-volume periods (BFCM)?
```

### 4. Content Mix Analysis
Analyze the balance of content types:

```
Questions:
- What's the ratio of sale vs content vs product emails by brand?
- Do brands with more content variety perform better?
- Is there an optimal content rotation pattern?
```

---

## Analysis Requiring New Data

### 1. Customer Lifecycle Segmentation
**Data needed**: Subscriber signup date, first purchase date, purchase history

```
Questions:
- How do new subscribers (0-30 days) respond vs mature (180+ days)?
- What content works for different lifecycle stages?
- When do subscribers typically churn?
```

### 2. Individual Engagement History
**Data needed**: Per-subscriber open/click history

```
Questions:
- What's the optimal re-engagement timing for inactive subscribers?
- How many non-opens before a subscriber is "lost"?
- Does engagement pattern predict purchase behavior?
```

### 3. Revenue Attribution
**Data needed**: Per-campaign or per-email revenue

```
Questions:
- Which campaigns drive actual purchases vs just clicks?
- What's the revenue per recipient by flow type?
- Does click rate correlate with revenue?
```

### 4. Cross-Channel Effects
**Data needed**: SMS, push notification data alongside email

```
Questions:
- Does SMS + email together outperform email alone?
- What's the optimal channel sequence?
- Do SMS subscribers have different email engagement?
```

---

## Industry Best Practices to Test

### Welcome Series
- **Benchmark**: 54% open, 5.8% click, 2-3% conversion ([Klaviyo](https://www.bluedropstudio.com/blog/10-essential-email-flows-for-dtc-brands))
- **Best practice**: 5-10 emails over 2-4 weeks
- **Goal**: Should drive ~80% of flow revenue

**Test**: Compare current welcome performance vs benchmark

### Abandoned Cart
- **Benchmark**: $7-14 revenue per recipient depending on AOV
- **Best practice**: 3-email sequence (1hr, 24hr, 72hr)
- **Current data shows**: Cart campaigns average 3.00% click (our best performer)

**Test**: Analyze cart abandonment timing and sequence

### Winback
- **Benchmark**: 45% of winback recipients will open subsequent emails
- **Best practice**: Trigger at 60-90 days of inactivity
- **Industry insight**: "Winback flows suck in DTC" - often the last resort after damage is done ([Magnet Monster](https://magnetmonster.com/blog/why-winback-flows-suck-in-dtc-and-what-to-do-about-it))

**Test**: Identify winback campaigns and analyze performance vs timing

### Post-Purchase
- **Benchmark**: Cross-sell emails 3-7 days post-purchase
- **Best practice**: Review request at 14-21 days
- **Goal**: Turn one-time buyers into repeat customers (30-40% repurchase rate is excellent)

**Test**: Analyze review request and thank you campaign performance

---

## Proposed New Analysis Scripts

### 1. `scripts/analyze_flow_performance.py`
```
- Categorize campaigns into flow types (welcome, cart, browse, winback, etc.)
- Calculate performance by flow type and brand
- Compare flow vs campaign metrics
```

### 2. `scripts/analyze_send_cadence.py`
```
- Calculate per-brand weekly/monthly send volume over time
- Correlate cadence with performance trends
- Identify fatigue patterns
```

### 3. `scripts/analyze_content_mix.py`
```
- Calculate ratio of sale vs content vs product emails
- Analyze content sequencing patterns
- Identify optimal mix by brand
```

### 4. `scripts/analyze_sequence_effects.py`
```
- For each campaign, calculate days since previous campaign
- Analyze performance by gap duration
- Identify optimal "rest" periods
```

---

## Data Acquisition Priorities

### High Priority (would unlock major insights)
1. ~~**Flow/Journey data from Braze** - Distinguish automated flows from manual campaigns~~ **DONE** - Canvas import implemented
2. **Campaign sequence within journeys** - Which email in the sequence (now available via `canvas_steps`)
3. **Segment data** - Which subscriber segments received each campaign

### Medium Priority (would enable lifecycle analysis)
4. **Aggregate cohort performance** - New vs returning subscriber performance
5. **Unsubscribe/complaint rates** - Per-campaign fatigue indicators
6. **Revenue per campaign** - Connect clicks to purchases

### Lower Priority (nice to have)
7. **Individual subscriber data** - Full engagement history
8. **A/B test results** - Controlled experiment data
9. **Cross-channel data** - SMS performance alongside email

---

## Immediate Action Items

1. ~~**Pull Braze flow/journey data** if available via API~~ **DONE**
2. **Import canvas data for all brands** - Run `--include-canvases` for each brand
3. **Re-analyze flow performance** with complete canvas data
4. **Categorize existing campaigns** into flow types using name patterns
5. **Analyze cadence vs performance** correlation by brand
6. **Build sequence analysis** using send dates and canvas_steps
7. **Compare content mix** across brands

---

## Sources
- [Lifecycle Email Marketing Guide - CleverTap](https://clevertap.com/blog/customer-lifecycle-email-marketing-campaigns/)
- [Email Frequency Best Practices - Omnisend](https://www.omnisend.com/blog/email-marketing-frequency/)
- [DTC Email Flow Benchmarks - Blue Drop Studio](https://www.bluedropstudio.com/blog/10-essential-email-flows-for-dtc-brands)
- [Winback Flows in DTC - Magnet Monster](https://magnetmonster.com/blog/why-winback-flows-suck-in-dtc-and-what-to-do-about-it)
- [Email Marketing Cadence - Mailjet](https://www.mailjet.com/blog/email-best-practices/how-many-marketing-emails-is-too-many/)
- [State of Email in Lifecycle Marketing - Litmus](https://www.litmus.com/resources/state-of-email-lifecycle-marketing)
