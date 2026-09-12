# Plain Text Email Revenue Automation System

This document describes the revenue-focused plain text email automation system that incorporates GA4 revenue data to optimize campaigns for purchases and revenue.

## Overview

The system has been enhanced to:
1. **Analyze** historical plain text campaigns by revenue performance
2. **Recommend** optimizations based on high-revenue campaign patterns
3. **Validate** campaigns with revenue-focused best practices
4. **Learn** from top-performing campaigns to improve future emails

## Components

### 1. Revenue Analysis Script (`analyze_plain_text_revenue.py`)

Analyzes plain text campaigns to identify patterns in high-revenue emails.

**Usage:**
```bash
# Analyze all brands
uv run python scripts/analyze_plain_text_revenue.py --all

# Analyze specific brand
uv run python scripts/analyze_plain_text_revenue.py --brand HAV

# Analyze with minimum revenue threshold
uv run python scripts/analyze_plain_text_revenue.py --brand CZ --min-revenue 1000

# Show top 50 campaigns
uv run python scripts/analyze_plain_text_revenue.py --brand HAV --top-n 50
```

**Output:**
- Top revenue-generating plain text campaigns
- Average revenue metrics (revenue per send, purchase rate, etc.)
- Brand and category distribution of top performers
- Subject line and body features from high-revenue campaigns

### 2. Revenue Recommender (`plain_text_revenue_recommender.py`)

Provides real-time recommendations during campaign creation based on historical revenue data.

**Key Features:**
- Analyzes top 20% of revenue-generating campaigns for patterns
- Provides brand-specific recommendations
- Suggests optimizations for subject lines, body content, and timing
- Integrates seamlessly with validation system

**Usage (as a module):**
```python
from scripts.plain_text_revenue_recommender import get_revenue_recommendations

recommendations = get_revenue_recommendations(
    brand="HAV",
    subject="Your discount is now up to 70% off",
    preheader="Shop our best deals before they're gone",
    body="Hi {{${first_name} | default: 'there'}},\n\n...",
    category="sale_promo"
)

for severity, message in recommendations:
    print(f"{severity}: {message}")
```

### 3. Enhanced Validation System

The `validate_campaign_config.py` script now includes revenue-focused recommendations automatically.

**What's New:**
- Revenue recommendations are included in validation warnings
- Recommendations are based on actual high-revenue campaign patterns
- Brand-specific insights (e.g., CZ benefits more from "You/Your" in subjects)
- Category-specific patterns (e.g., which categories generate most revenue)

**Example Output:**
```
⚠ [Revenue] Consider using 'You/Your' in subject line. 75% of high-revenue campaigns use it (+2.2pt open rate).
⚠ [Revenue] Percent signs in subject correlate with -3.4pt open rate. Only 20% of high-revenue campaigns use them.
ℹ [Revenue Optimization] Most high-revenue plain text campaigns are 'sale_promo' category. Your campaign is 'reminder'.
```

## How It Works

### 1. Data Collection
- System loads all plain text campaigns from `campaigns/*.yaml`
- Filters campaigns with GA4 revenue data (`performance_summary.ga4.revenue`)
- Identifies plain text campaigns by `_PT` in name or `layout_type: text_only`

### 2. Pattern Extraction
- Sorts campaigns by revenue performance score (revenue per send + purchase rate)
- Analyzes top 20% of performers for patterns:
  - Subject line features (You/Your, percent signs, questions, ALL CAPS)
  - Body features (paragraph count, link count, personalization)
  - Brand and category distribution
  - Timing patterns (day of week, hour)

### 3. Recommendation Generation
- Compares new campaign against high-revenue patterns
- Provides specific, actionable recommendations
- Prioritizes recommendations by severity (error > warning > info)

### 4. Integration with Automation
- Recommendations appear automatically during campaign validation
- No additional steps required - just use existing `create_braze_campaign_v2.py`
- Recommendations are non-blocking (warnings, not errors)

## Best Practices Identified

Based on analysis of high-revenue plain text campaigns:

### Subject Lines
- ✅ **Use "You/Your"** - Especially important for CZ (+6.8pt open rate)
- ❌ **Avoid percent signs** - Correlates with -3.4pt open rate
- ❌ **Avoid questions** - Correlates with -2.7pt open rate
- ❌ **Avoid ALL CAPS** (except BUR) - Correlates with -4.4pt open rate

### Body Content
- ✅ **Personalize greeting** - Must start with `Hi {{${first_name} | default: 'there'}}`
- ✅ **Limit links to 0-2** - Campaigns with 0-2 links perform 92% better
- ✅ **Use 2+ paragraphs** - Better engagement and readability

### Campaign Structure
- ✅ **Preheader required** - Correlates with +8.7pt open rate
- ✅ **Optimal preheader length** - 60-90 characters (47.6% open rate)

## Example Workflow

1. **Create campaign config:**
   ```yaml
   campaign:
     name: "P_2025_01_26_PT_HAV_Sale_Reminder"
     brand: "HAV"
     category: "sale_promo"
     email:
       subject: "Your discount is now up to 70% off"
       preheader: "Shop our best deals before they're gone"
       body: |
         Hi {{${first_name} | default: 'there'}},
         
         This is your first paragraph...
         
         This is your second paragraph...
   ```

2. **Validate campaign:**
   ```bash
   uv run python scripts/create_braze_campaign_v2.py \
     --config campaigns/my-campaign.yaml \
     --brand HAV \
     --api-campaign-id YOUR_ID \
     --dry-run
   ```

3. **Review revenue recommendations:**
   The validation output will include revenue-focused recommendations based on historical high-revenue campaigns.

4. **Create and send:**
   ```bash
   uv run python scripts/create_braze_campaign_v2.py \
     --config campaigns/my-campaign.yaml \
     --brand HAV \
     --api-campaign-id YOUR_ID
   ```

## Analyzing Revenue Performance

To understand what makes plain text emails successful for revenue:

```bash
# See top revenue-generating campaigns
uv run python scripts/analyze_plain_text_revenue.py --brand HAV --top-n 20

# Compare across brands
uv run python scripts/analyze_plain_text_revenue.py --all --min-revenue 500
```

This will show:
- Which campaigns generate the most revenue
- Revenue per send metrics
- Purchase rates
- Patterns in subject lines and body content
- Brand and category insights

## Future Enhancements

Potential improvements:
1. **A/B testing recommendations** - Suggest test variants based on high-revenue patterns
2. **Timing optimization** - Recommend send times based on revenue performance
3. **Audience segmentation** - Identify which audiences respond best to plain text
4. **Content templates** - Generate email content based on top revenue patterns
5. **Real-time learning** - Update recommendations as new campaign data comes in

## Notes

- Revenue data comes from GA4 integration (`import_ga4_metrics.py`)
- Recommendations are based on correlations, not causation
- Always test recommendations before implementing broadly
- Brand-specific patterns may vary - recommendations are tailored per brand
- System gracefully handles missing GA4 data (falls back to general best practices)

## Troubleshooting

**No revenue recommendations appearing:**
- Check that GA4 data has been imported: `uv run python scripts/import_ga4_metrics.py --brand HAV`
- Verify campaigns have `performance_summary.ga4.revenue` data
- Ensure minimum revenue threshold isn't too high

**Recommendations seem generic:**
- More historical data needed - run GA4 import for more campaigns
- Lower the `min_revenue` threshold in recommender to include more campaigns
- Check that brand has sufficient plain text campaign history

**Import errors:**
- Revenue recommender is optional - validation will still work without it
- Check that `plain_text_revenue_recommender.py` is in the `scripts/` directory
- Verify all dependencies are installed
