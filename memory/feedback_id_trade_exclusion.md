---
name: feedback-id-trade-exclusion
description: Trade campaigns must always be excluded from Interior Define email analytics
metadata: 
  node_type: memory
  type: feedback
  originSessionId: e53b2fbf-5197-4b30-bcd9-c3cd353b134e
---

Always exclude campaigns with "TRADE" in the campaign name (case-insensitive) when analyzing Interior Define (ID) email performance metrics.

Filter: `if 'TRADE' in data.get('name','').upper(): continue`

**Why:** Trade sends go to a separate trade audience and are not representative of consumer program performance. Mixing them in skews engagement metrics.

**How to apply:** Any time querying ID campaign performance — open rates, click rates, send time analysis, subject line analysis, sale vs non-sale comparisons, day-of-week analysis, etc. Apply the filter before any aggregation.
