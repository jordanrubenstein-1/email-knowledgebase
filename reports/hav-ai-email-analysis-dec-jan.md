# Havenly AI Email Performance Analysis
## December 2025 vs January 2026 Comparison

**Generated:** February 4, 2026  
**Status:** December 2025 data available | January 2026 data pending import

---

## Executive Summary

This analysis compares Havenly AI email campaign performance between December 2025 and January 2026 to assess the impact of increasing cadence to weekly sends.

---

## December 2025 Performance

### Campaigns (3 total)

1. **December 13, 2025** — "Meet your new design BFF (and she's fast)"
   - **PC Segment:**
     - Open Rate: 38.6%
     - Click Rate: 0.18%
     - Sends: 250,910
     - Subject: "Meet your new design BFF (and she's fast)"
   
   - **Conversion Segment:**
     - Open Rate: 51.0%
     - Click Rate: 0.50%
     - Sends: 43,594
     - Subject: "Meet your new design BFF (and she's fast)"

2. **December 20, 2025** — "A little design time for you"
   - Open Rate: 32.7%
   - Click Rate: 0.15%
   - Sends: 297,401
   - Subject: "A little design time for you"
   - Note: Holiday-themed campaign

### December 2025 Summary Metrics

| Metric | Value |
|--------|-------|
| **Campaigns** | 3 |
| **Average Open Rate** | 40.7% |
| **Average Click Rate** | 0.28% |
| **Aggregate Open Rate** | 35.0% |
| **Aggregate Click Rate** | 0.19% |
| **Total Sends** | 591,905 |
| **Total Opens** | 207,297 |
| **Total Clicks** | 1,108 |

### Key Insights (December)

- **Conversion segment outperforms:** 51.0% open rate vs 38.6% for PC segment
- **Strong click performance:** Conversion segment achieved 0.50% click rate (2.8x higher than PC)
- **Holiday campaign impact:** Dec 20 campaign had lower engagement (32.7% open), likely due to holiday inbox competition

---

## January 2026 Performance

**Status:** ⚠️ Data not yet imported

To import January 2026 campaigns:
```bash
cd /Users/mina.cohen/AI\ Email/email-knowledgebase
uv run python scripts/import_braze.py --brand HAV --skip-existing
```

Once imported, run the analysis script:
```bash
uv run python scripts/analysis/analyze_hav_ai_dec_jan_comparison.py
```

---

## Weekly Cadence Analysis

### Expected Impact

With cadence increased to **weekly** in January 2026 (vs monthly/less frequent in December):

**Potential Positive Impacts:**
- Increased brand awareness and top-of-funnel engagement
- More opportunities for conversion
- Better alignment with product usage patterns

**Potential Risks:**
- **Engagement fatigue:** Declining open rates due to frequency
- **Click rate dilution:** Lower click rates as subscribers become accustomed to weekly sends
- **Unsubscribe risk:** Higher unsubscribe rates from increased frequency

### Monitoring Metrics

When January 2026 data is available, compare:

1. **Open Rate Trend:**
   - Target: Maintain ≥35% aggregate open rate
   - Warning: If drops below 30%, consider reducing frequency

2. **Click Rate Trend:**
   - Target: Maintain ≥0.15% aggregate click rate
   - Warning: If drops below 0.10%, engagement may be declining

3. **Campaign Count:**
   - Expected: 4-5 campaigns in January (weekly cadence)
   - Compare to: 3 campaigns in December

4. **Unsubscribe Rate:**
   - Monitor for increases vs December baseline

---

## Historical Context

### Previous Months (for reference)

**October 2025** (Launch campaigns):
- Average Open Rate: 24.1%
- Average Click Rate: 0.33%
- Note: Lower open rate due to one campaign at 7.3% (likely test/control variant)

**November 2025:**
- Average Open Rate: 46.2%
- Average Click Rate: 0.17%

**Trend:** Open rates improved from October to November, then stabilized in December.

---

## Recommendations

### Immediate Actions

1. **Import January 2026 data** using the import script
2. **Run comparison analysis** using `analyze_hav_ai_dec_jan_comparison.py`
3. **Review weekly cadence impact** on engagement metrics

### If Performance Maintains (Jan 2026)

✅ **Continue weekly cadence** - engagement is stable  
✅ **Optimize subject lines** - test variations to improve open rates  
✅ **Segment strategy** - leverage conversion segment's strong performance (51% open, 0.50% click)

### If Performance Declines (Jan 2026)

⚠️ **Consider cadence adjustment:**
- Test bi-weekly frequency
- A/B test send times
- Review content variety to maintain interest

⚠️ **Content optimization:**
- Ensure each weekly send provides unique value
- Avoid repetitive messaging
- Test different angles/benefits

---

## Analysis Script

A comprehensive analysis script has been created at:
`scripts/analysis/analyze_hav_ai_dec_jan_comparison.py`

This script will:
- Load all Havenly AI campaigns
- Compare December 2025 vs January 2026 performance
- Calculate weekly cadence impact
- Provide trend analysis across all months

---

## Next Steps

1. ✅ Analysis script created
2. ⏳ Import January 2026 campaigns from Braze
3. ⏳ Run analysis script
4. ⏳ Review results and make cadence/content recommendations

---

## Questions to Answer Once Data Available

1. **Did weekly cadence maintain engagement?**
   - Compare Jan 2026 open/click rates to Dec 2025

2. **How many campaigns were sent in January?**
   - Expected: 4-5 (weekly cadence)
   - Compare to: 3 in December

3. **Is there engagement fatigue?**
   - Look for declining trends across January campaigns
   - Compare first vs last campaign in January

4. **Which segments performed best?**
   - Compare PC vs Conversion segment performance
   - Identify optimal targeting strategy

5. **Subject line performance?**
   - Analyze which subjects drove highest engagement
   - Identify patterns for future campaigns
