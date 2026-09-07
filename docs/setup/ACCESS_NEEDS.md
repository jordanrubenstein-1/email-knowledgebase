# GA4 Data Requirements


## Data Needed

I need to join GA4 metrics with email campaign data at the **campaign level**. Core conversion metrics (most important):

1. **Sessions** - Total sessions attributed to the campaign
2. **Purchases** - Total purchases attributed to the campaign  
3. **Revenue** - Total revenue attributed to the campaign
4. **Attribution window** - The window used (e.g., 7, 14, or 30 days) - this would be helpful to know if it's configurable

**Additional conversion events**:
- Add to cart events
- Swatch purchases
- Design fee purchases

**Additional engagement metrics** (nice to have, if available):
- Active users
- Engaged sessions / Engagement rate
- Bounce rate
- Average session duration / time on page
- Pages per session
- Event count (total events)
- Checkout starts / Checkout progress
- Product views
- Item list views / Item list clicks

## Join Requirements

On the Braze side, we already have campaign names that include the brand in the naming convention, and these are used as UTM campaign parameters. So I'll be able to join the GA4 data with our campaign data using the UTM campaign parameter. I know there will be separate tables per brand.

## Format Questions

1. **How is attribution handled?** - Is there a default attribution window, or can I query different windows?
2. **Time granularity** - Is the data at the day level, or more granular?
3. **Table naming convention** - What's the naming pattern for the brand-specific tables? (e.g., `ga4_hav`, `ga4_cz`, etc.)

## Brands Needed

All 6 brands: HAV, CZ, ID, BUR, STF, TI

