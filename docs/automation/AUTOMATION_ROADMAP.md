# Automation Roadmap

> Last updated: Feb 10, 2026

Overview of what's been automated, what's in progress, and what's next for the email/SMS campaign workflow.

---

## Already Automated

### Calendar → Asana Tasks
**Script:** `scripts/create_calendar_tasks.py`

Reads the Google Sheets master marketing calendar (5 tabs: HAV, CZ, ID+BUR, TI+SF, TRADE), creates Asana tasks in the Master CRM project with custom fields (Brand, Channel, Type, Status, Category, Subject Line, Preheader), and tracks duplicates via `data/calendar_task_mapping.yaml`.

### AI-Generated Creative Direction + SL/PH
**Integrated into:** `scripts/create_calendar_tasks.py`

Claude generates 2 subject line / preheader options and a full creative brief (hero section, product/offer, supporting content, CTA) per task. Uses past campaign examples from the YAML archive for brand-specific tone matching. Can be skipped with `--skip-ai`.

### Campaign Naming Convention Enforcement
**Utility:** `scripts/utils/campaign_name.py`
**Rule:** `.cursor/rules/campaign-naming-convention.mdc`

`generate_campaign_name()`, `validate_campaign_name()`, and `parse_campaign_name()` functions enforce the `[TYPE]_[CHANNEL]_[YYYY]_[MM]_[DD]_[BRAND]_[DESIGN]_[HAV_AUDIENCE?]_[CONTENT_TYPE?]_Description[_SUFFIX?]` pattern across all scripts and AI-assisted workflows.

### Sale Schedule Auto-Sync
**Script:** `scripts/import_sale_schedules.py --source asana`
**CI:** `.gitlab-ci.yml` (daily scheduled pipeline)

Daily GitLab CI pipeline fetches all tasks from the Asana Promo Tracking Board, parses brand, dates, discount, and sale name from each task, handles Havenly DPS vs Marketplace audience distinction, merges with historical data in `data/sale_schedules.yaml`, and auto-commits changes. Eliminates manual sale schedule imports entirely.

---

## High Impact — Done

### 1. Gap Analysis Script ✅
**Script:** `scripts/gap_analysis.py`

Compares scheduled Asana tasks against `data/lifecycle_guidelines.yaml` targets and flags gaps. Features:
- Per-brand, per-channel, per-week comparison against send cadence targets
- Sale context integration (flags gaps during active sale periods)
- Content-type suggestions based on historical category mix from campaign YAMLs
- Terminal report + markdown output to `reports/gap-analysis.md`

**Usage:**
```bash
uv run python scripts/gap_analysis.py --brand HAV --weeks 4
```

### 2. Braze Campaign Pre-Creation ✅ (All Four Channels)
The most mature area of the project. Four paths depending on campaign type:

#### API Shell Creation
**Script:** `scripts/create_braze_campaigns.py`

Fetches "Ready to Code" tasks from Asana, creates Braze campaign shells (name, subject, preheader) via the Braze Campaigns API, writes the dashboard link back to the Asana task. For designed emails where the coder still needs to drop in the HTML.

#### Full Plain Text Email Builder
**Script:** `scripts/braze_automation/build_pt_campaign.py`

End-to-end Playwright automation for plain text emails:
1. Fetches PT tasks from Asana ("Ready to Code" status, name ends with "PT")
2. Converts plain text body from Asana notes to HTML (600px template)
3. Automates all 4 Braze campaign builder steps:
   - **Content:** subject, preheader, HTML body (clipboard paste into Monaco editor)
   - **Target audience:** segments + filters from `data/brand_braze_config.yaml` (handles HAV PC/CONV variants)
   - **Delivery schedule:** Intelligent Timing, or specific time resolved from Asana fields (sale announcements → 7:15 AM, PM suffix → 4:00 PM)
   - **Conversion events:** 4 per brand, 3-day deadline
4. Applies UTM link templates via Link Management
5. Saves as draft (never auto-launches)
6. Writes Braze campaign link back to Asana

#### Full SMS Builder
**Script:** `scripts/braze_automation/build_sms_campaign.py`

End-to-end Playwright automation for SMS campaigns:
1. Fetches SMS tasks from Asana ("Ready to Code" + Channel = SMS)
2. Extracts copy from task notes (filters out instruction lines)
3. Resolves landing page URLs via keyword-to-path mapping (`sms_config.link_paths` in brand config)
4. Appends brand-specific UTMs to all links (`utm_medium=sms`)
5. Generates campaign name programmatically
6. Automates Braze: SMS body, target audience (SMS opt-in segment), delivery schedule (3 PM local default or Asana send time), conversion events
7. Saves as draft, writes campaign link back to Asana

Smart link resolution handles LINK placeholders and keyword matching (e.g., "outdoor" → `/collections/outdoor-furniture`).

#### Full Push Notification Builder
**Script:** `scripts/braze_automation/build_push_campaign.py`

End-to-end Playwright automation for Havenly push notification campaigns using a **duplicate-based** workflow:
1. Fetches push tasks from Asana ("Ready to Code" + Channel = Push, name starts with "Push:")
2. Detects audience from task name: `DPS` → Pre-Converted (PC), `MP` → Converted (MP)
3. Extracts push copy from task notes (`Title:` and `Description:` fields)
4. Handles combined tasks (no DPS/MP prefix) by building TWO campaigns — one PC, one CONV
5. Navigates to a reference campaign in Braze and duplicates it (audience, conversions, deep links, on-click behavior carry over)
6. Edits only variable fields: campaign name, push title, push message, delivery date
7. Saves as draft, writes Braze campaign link back to Asana (comment with both links for combined tasks)

Uses `push_config` in `data/brand_braze_config.yaml` for reference campaign URLs, segments, deep links, and send time (3:00 PM local).

#### Batch Creation
**Script:** `scripts/create_braze_campaigns_batch.py`

Parallel processing of multiple YAML config files through the API pipeline.

#### Brand Config System
**Config:** `data/brand_braze_config.yaml`

Centralizes all brand-specific Braze settings for email, SMS, and push: audience segments (email variants + SMS opt-in lists + push audiences), conversion events, UTM templates, send time defaults, SMS link paths and base URLs, push reference campaign URLs and deep links. Adding a new brand or channel is a config change, not a code change.

---

## High Impact — Partially Done

### 3. Automated HTML Assembly from Components (~50%)
**Component library:** `components/` (9 Liquid components)
**Assembly script:** `scripts/assemble_email.py`

**What exists:**
- Reusable components: `hero_image`, `product_grid_2col`, `product_grid_4col`, `product_card`, `cta_button`, `headline`, `paragraph`, `spacer`, `divider`
- Component schema definitions in `components/components.yaml`
- Personalization block insertion and A/B split logic
- Personalized brief generator (`scripts/generate_personalized_brief.py`)

**What's missing:**
- Google Drive API integration for fetching sliced images from the design folder
- Mapping from campaign brief / `layout_type` to a specific component arrangement
- Automatic HTML output ready for Braze upload

**Next step:** Build a Drive fetcher that pulls slices from a known folder structure, maps them to components based on `layout_type`, and outputs assembled HTML.

---

## Medium Impact — Partially Done

### 4. Asana Status-Driven Pipeline (~40%)

**What exists:**
- All three builders filter by Asana task status ("Ready to Code") and write results back
- GitLab CI running scheduled jobs (sale schedule sync) that could host additional automation

**What's missing:**
- Asana webhook listener or polling daemon for status transitions
- "Design Complete" → run QA checks automatically
- "Ready for Braze" → trigger the appropriate creation script (PT / SMS / designed)
- "Test Sent" → auto-send test to QA distribution list
- Slack notifications at each stage

**Next step:** Build a lightweight orchestrator on GitLab CI (or Asana webhooks → Lambda) that polls status changes and dispatches the right script. The individual scripts are ready; they need a conductor.

### 5. Automated QA (~60%)
**Script:** `scripts/validate_campaign_config.py`

**What exists:**
- Subject line quality checks (length, ALL CAPS, brand-specific rules)
- Preheader validation (presence, optimal length 60-90 chars)
- Email body structure validation (min length, paragraph count, personalized greeting)
- CTA domain validation (links on correct brand domain)
- Link count warnings
- Subject/preheader/body repetition detection

**What's missing:**
- Link resolution (HTTP HEAD checks to catch 404s)
- Image URL validation (broken images, oversized files)
- UTM parameter enforcement (correct source/medium/campaign values)
- HTML structure validation (email client compatibility, dark mode)
- Audience size sanity check (compare segment size against lifecycle guidelines)

**Next step:** Extend with network-based checks and UTM parsing. Wire into the status-driven pipeline (#4) as a gate before "Ready for Braze."

---

## Lower Priority

### 6. Google Drive → Braze HTML Upload — Not Started
No Drive API integration exists (only Google Sheets for calendar and sale schedule imports). Would require Drive API auth, folder-watching, and mapping from file names to Braze template slots.

### 7. Post-Send Analytics Backfill ✅ (Expanded)
**Scripts:**
- `scripts/backfill_analytics.py` — Braze open/click/unsubscribe rates via Analytics API (parallel processing)
- `scripts/import_ga4_metrics_snowflake.py` — GA4 sessions, purchases, revenue from Snowflake (BUR, CZ, ID)
- `scripts/analysis/analyze_sale_performance.py` — sale vs non-sale performance report

**Supporting:**
- Data freshness Cursor rule (`.cursor/rules/data-freshness-check.mdc`) auto-detects stale data before analysis
- GA4 attribution uses Session Primary Channel Group (matches GA4 UI)
- Configurable attribution windows (7 days default, 14 for canvas steps)

**Remaining gap:** Auto-updating Asana tasks with performance metrics after 24/48hrs. Scripts update YAML files but don't push metrics back to Asana.

---

## Capabilities Beyond the Original Plan

| Capability | Details |
|---|---|
| **Sale schedule auto-sync** | Daily CI pipeline from Promo Calendar Google Sheet; eliminates manual imports |
| **Havenly audience-aware sale matching** | `sale_matcher.py` distinguishes PC (DPS) from CONV (Marketplace) for HAV campaigns |
| **SMS smart link resolution** | SMS builder resolves landing page URLs from keywords in copy via `sms_config.link_paths` |
| **PT email revenue analysis** | `analyze_plain_text_revenue.py` identifies what makes PT emails drive revenue |
| **Personalized brief generator** | `generate_personalized_brief.py` outputs briefs with personalization recs + A/B split config |
| **Brand Braze config** | `data/brand_braze_config.yaml` centralizes email + SMS settings per brand |
| **Data freshness checks** | Cursor rule auto-detects stale Braze analytics, GA4 data, and sale schedules before analysis |

---

## Recommended Next Priorities

1. **Automated QA completion** — extend `validate_campaign_config.py` with link checking, image validation, UTM enforcement. Quick win that catches errors before they ship.
2. **Status-driven orchestrator** — connect existing scripts into an Asana status-change listener. GitLab CI is already running scheduled jobs, so adding a "process Ready to Code tasks" job is a natural extension.
3. **Designed email builder** — either extend Playwright automation to handle designed emails (HTML drop-in + audience/schedule/conversions) or build the Drive → HTML assembly pipeline to close the last manual gap.
