# BUR Lifecycle Decisioning Engine

**Date:** 2026-06-26
**Status:** Architecture finalized, not yet built
**Context doc:** Burrow Lifecycle Strategy Rebuild (Nicole Poulson, June 2026) — see the "External Decisioning Architecture" addendum

---

## What This Is

An external decisioning engine that determines which lifecycle email each Burrow subscriber should receive on a given day, and calls Braze to deliver it. Braze becomes the template library and delivery layer; all arc logic (HOT/WARM/COOLING/BURST/RE-OPEN) lives in Python, not in Braze canvases.

This is needed because Braze canvases cannot pause mid-flow, resume at a specific step, or transfer a user between canvases at an arbitrary position — all of which the lifecycle arc model requires for BURST (behavioral interrupt) and RE-OPEN (re-entry after dormancy).

---

## Architecture

### Daily job flow

```
5:30am ET — GitLab scheduled job runs scripts/lifecycle_decisioning_bur.py
  1. Read data/lifecycle_active_users_bur.json → list of enrolled user IDs
  2. POST /users/export/ids → read current lifecycle state attributes from Braze
  3. Query Snowflake datashare → new events in the last 24h (clicks, purchases, cart adds, swatch orders, PDP views, welcome canvas sends)
  4. Compute state transitions (HOT→WARM at Day 15, click→BURST, purchase→exit, etc.)
  5. POST /users/track → write updated state attributes back to Braze (batches of 75)
  6. POST /campaigns/trigger/schedule/create → pre-schedule sends for 7am ET
  7. Add newly detected subscribers; remove converted/exited users from active list
  8. Commit updated data/lifecycle_active_users_bur.json to git

7:00am ET — Braze delivers the pre-scheduled sends
```

Sends are pre-scheduled (not immediate) so the job can run at 5:30am and emails go out at 7am. If the job fails, nothing sends — a missed send is the failure mode, not a double send.

### State storage

**Braze custom attributes** are the state store — no new Snowflake table, no new permissions needed. Attributes written per user via `/users/track`:

```python
{
    "external_id": "user_123",
    "lifecycle_state": "WARM",           # HOT / WARM / COOLING / BURST / RE-OPEN
    "lifecycle_arc_day": 22,             # days since entering current arc
    "lifecycle_send_index": 5,           # which send in the arc they receive next
    "lifecycle_sends_completed": "hot_t1,hot_t2,hot_t3",  # comma-separated log
    "lifecycle_burst_active": False,
    "lifecycle_entered_at": "2026-06-01"
}
```

**`data/lifecycle_active_users_bur.json`** tracks who is currently enrolled (HOT through RE-OPEN). DORMANT users are not stored here — see enrollment detection below. Format:

```json
{
  "enrolled": ["external_user_id_a", "external_user_id_b", ...],
  "updated_at": "2026-06-26"
}
```

### Enrollment and signal detection

The daily job queries the Braze datashare for multiple signals, not just welcome canvas entries:

```sql
-- New subscribers (welcome canvas entry)
SELECT USER_ID, EXTERNAL_USER_ID, 'new_subscriber' AS signal, MAX(TIME) AS ts
FROM USERS_MESSAGES_EMAIL_SEND_SHARED
WHERE APP_GROUP_ID = '67093a1f24ebbe0065cb9c77'  -- BUR
  AND CANVAS_NAME ILIKE '%welcome%'
  AND TO_TIMESTAMP(TIME) >= DATEADD('hour', -48, CURRENT_TIMESTAMP())
GROUP BY 1, 2, 3

UNION ALL

-- Email clicks (BURST trigger)
SELECT USER_ID, EXTERNAL_USER_ID, 'click' AS signal, MAX(TIME) AS ts
FROM USERS_MESSAGES_EMAIL_CLICK_SHARED
WHERE APP_GROUP_ID = '67093a1f24ebbe0065cb9c77'
  AND TO_TIMESTAMP(TIME) >= DATEADD('hour', -24, CURRENT_TIMESTAMP())
  AND (IS_SUSPECTED_BOT_CLICK IS NULL OR IS_SUSPECTED_BOT_CLICK = 'false')
GROUP BY 1, 2, 3

UNION ALL

-- Cart adds (BURST trigger)
SELECT USER_ID, EXTERNAL_USER_ID, 'cart_add' AS signal, MAX(TIME) AS ts
FROM USERS_BEHAVIORS_CUSTOMEVENT_SHARED
WHERE APP_GROUP_ID = '67093a1f24ebbe0065cb9c77'
  AND EVENT_NAME = 'Product Added'
  AND TO_TIMESTAMP(TIME) >= DATEADD('hour', -24, CURRENT_TIMESTAMP())
GROUP BY 1, 2, 3

UNION ALL

-- 3+ PDP views of same product in 24h (RE-OPEN trigger)
SELECT USER_ID, EXTERNAL_USER_ID, 'pdp_3x' AS signal, MAX(TIME) AS ts
FROM USERS_BEHAVIORS_CUSTOMEVENT_SHARED
WHERE APP_GROUP_ID = '67093a1f24ebbe0065cb9c77'
  AND EVENT_NAME = 'Product Viewed'
  AND TO_TIMESTAMP(TIME) >= DATEADD('hour', -24, CURRENT_TIMESTAMP())
GROUP BY USER_ID, EXTERNAL_USER_ID, 'pdp_3x', PRODUCT_ID
HAVING COUNT(*) >= 3
```

Swatch orders come from a separate Shopify Fivetran query joined on email/external_id.

**Classification logic per signal:**

| Signal | User in active list? | Action |
|--------|---------------------|--------|
| new_subscriber | No | Add as HOT, arc_day=0 |
| click or cart_add | Yes (HOT/WARM/COOLING) | Trigger BURST |
| click or cart_add | No | Check prior lifecycle history → if yes: RE-OPEN; if no: HOT |
| pdp_3x or swatch | Yes (COOLING) | Trigger RE-OPEN |
| pdp_3x or swatch | No | Check prior lifecycle history → if yes: RE-OPEN |
| any | Yes (already BURST) | No-op (BURST already active) |

**DORMANT users are not tracked explicitly.** A user not in the active list who signals intent and has prior lifecycle send history is DORMANT by definition. No separate DORMANT file needed. Prior history check: query `USERS_MESSAGES_EMAIL_SEND_SHARED` for any prior send of a lifecycle campaign API ID.

### Braze delivery

Each lifecycle message is a **Braze API-triggered campaign** — no audience, no schedule, only fires when called by this job. The job maintains a catalog:

```yaml
# data/lifecycle_campaign_catalog.yaml
hot_t1: "campaign_api_id_here"
hot_t2: "campaign_api_id_here"
hot_t3: "campaign_api_id_here"
warm_wk1_s1: "campaign_api_id_here"
burst_t1: "campaign_api_id_here"
reopen_t1: "campaign_api_id_here"
# etc.
```

One `POST /campaigns/trigger/schedule/create` call per campaign per day, passing the list of `external_ids` who should receive it and the scheduled send time (7am ET).

---

## Why Not Other Approaches

**Braze-native canvases:** Can't pause mid-flow, resume at step N, or transfer between canvases. BURST and RE-OPEN require these capabilities. HOT arc alone could be a canvas; WARM onward cannot.

**Attribute + scheduled Braze campaign (audience filter on lifecycle_today_send):** Dangerous failure mode — if attributes don't update one morning, the Braze campaign fires on yesterday's stale value → wrong sends or double sends. API-triggered sends fail safe (missed send vs double send).

**CDI (Cloud Data Ingestion):** CDI is just a scheduled `/users/track` run by Braze instead of by us. Requires Snowflake role provisioning for Braze's IPs + Braze dashboard setup. Not worth the engineering dependency at current volume (~12–15K active users). Worth revisiting at 100K+ active enrolled users.

**Simon Data / Lexer:** Both provide this architecture out of the box. Simon Data is $50K–$150K+/yr. Worth evaluating in parallel with Phase 1 build once HOT arc is live and generating conversion data. See strategy doc for full vendor comparison.

---

## Infrastructure Already in Place

| Component | Status | Location |
|-----------|--------|---------|
| BUR Braze API key | ✅ | `BRAZE_API_KEY_BUR` in `.env` and GitLab CI vars |
| Braze base URL | ✅ | `BRAZE_BASE_URL` in `.env` |
| `/users/track` wrapper (BUR) | ✅ | `scripts/set_june2026_second_room_cohort.py` — exact pattern to follow |
| `/campaigns/trigger/send` wrapper | ✅ | `scripts/braze_campaign_api.py` — `trigger_campaign()` |
| Snowflake client | ✅ | `scripts/snowflake_client.py` — `get_snowflake_client()` |
| Braze datashare (read-only) | ✅ | `BRAZE_BRAZEWEST_BRAZE_RAW_EVENTS_AWS_US_EAST_1_XJ24206.DATALAKE_SHARING` |
| GitLab scheduled jobs | ✅ | `.gitlab-ci.yml` — follow `sync-sale-schedules` pattern |
| Snowflake env vars in CI | ✅ | Used by `update-lifecycle-canvas-map` job |

BUR app group ID: `67093a1f24ebbe0065cb9c77`

---

## Files to Create

| File | Purpose |
|------|---------|
| `scripts/lifecycle_decisioning_bur.py` | Main daily decisioning script |
| `scripts/utils/lifecycle_state.py` | Helpers: read/write Braze state attributes, active-list management |
| `data/lifecycle_campaign_catalog.yaml` | Arc position → Braze campaign API ID mapping |
| `data/lifecycle_active_users_bur.json` | Active enrolled user IDs (committed and updated by the job) |
| `.gitlab-ci.yml` | Add `lifecycle-decisioning-bur` scheduled job |

---

## Phased Build

| Phase | Scope | Notes |
|-------|-------|-------|
| 1 | HOT arc (T1–T9), exit on purchase | Stateless — compute from datashare each run; no persistent arc_day tracking needed |
| 2 | BURST detection | Click/cart → pause HOT/WARM, fire T1–T3, resume; first real state-machine behavior |
| 3 | WARM arc | Weekly cadence; needs `lifecycle_arc_day` + `lifecycle_send_index` attributes |
| 4 | COOLING suppression, DORMANT signal detection, RE-OPEN | Lower frequency; RE-OPEN uses prior-history check |
| 5 | POST PURCHASE parallel track | Coordinate suppression with existing cart/browse abandon canvases |

---

## Volume and Scalability

At current enrollment (~3K new subscribers/month):
- HOT + WARM + COOLING active at any time: ~12–15K users
- Estimated daily job runtime: ~15 minutes
- API calls: ~300 `/users/export/ids` reads + ~200 `/users/track` writes + ~20 campaign trigger calls

At 3–5× growth (Part 1 identification improvements from the strategy doc): ~45–75K active users, ~45 min runtime — still within GitLab job timeout. CDI becomes relevant at ~100K+.

---

## Testing Approach

- `--dry-run` flag: print who would get what, no API calls made
- `--limit N` flag: process only N users for live testing
- Idempotency guard at job start: query datashare to confirm no lifecycle sends already went out today before scheduling anything (prevents double-send if job is manually re-triggered)
