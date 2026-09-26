# Design: TI SMS Campaign Builder

**Date:** 2026-04-01
**Status:** Approved

## Goal

Reusable infrastructure for building The Inside (TI) SMS campaigns in Klaviyo from Asana tasks.
When a TI Asana task is marked "Ready to Code" with Channel = SMS, run this script to create a
Draft campaign + message in Klaviyo. A human schedules and sends manually.

## Scope

- Extend `scripts/utils/klaviyo_client.py` with write methods (campaign + message creation)
- New script `scripts/create_klaviyo_sms.py` — Asana-driven or fully manual CLI

## 1. `klaviyo_client.py` — new write methods

Four new methods on `KlaviyoClient`:

| Method | Endpoint | Notes |
|--------|----------|-------|
| `find_list_or_segment_by_name(name)` | `GET /api/lists/` + `GET /api/segments/` | Searches both; returns `(id, kind)` tuple; result cached in instance dict |
| `create_campaign(name, channel, included_ids)` | `POST /api/campaigns/` | `channel: sms`, audience `included`, no send_strategy → Draft |
| `create_campaign_message(campaign_id, body)` | `POST /api/campaign-messages/` | SMS body text only |
| `assign_campaign_message(campaign_id, message_id)` | `POST /api/campaigns/{id}/campaign-message-assign/` | Required by Klaviyo to link message to campaign |

Auth, rate-limiting, and retry logic reuse existing `_post()` and `_get()` infrastructure.

## 2. `scripts/create_klaviyo_sms.py`

### CLI

**Asana-driven (primary workflow):**
```bash
uv run python scripts/create_klaviyo_sms.py \
  --brand TI \
  --asana-gid 1213758018415441 \
  --link https://www.theinside.com/collections/new-arrivals
```

**Manual override:**
```bash
uv run python scripts/create_klaviyo_sms.py \
  --brand TI \
  --name "SMS: Spring Arrivals" \
  --body "The Inside: Spring just dropped 🌷 New beds, new curtains + new outdoor in all the patterns you love. Shop the new arrivals: https://www.theinside.com/collections/new-arrivals" \
  --segment "Master SMS Segment"
```

**Dry-run (prints what would be created, no API calls):**
```bash
uv run python scripts/create_klaviyo_sms.py --brand TI --asana-gid 1213758018415441 --link ... --dry-run
```

### Execution steps

1. **Fetch Asana task** (if `--asana-gid`) — pulls `name`, primary copy (first non-empty paragraph
   of the task notes, before the blank-line separator), and audience name from the notes block.
2. **Format body** — replaces `→ LINK`, `→ [link]`, or bare `LINK`/`[link]` placeholder with
   `--link` value. Formatting rule: no space before colon, one space after:
   `Shop the new arrivals: https://...`
3. **Resolve segment** — calls `find_list_or_segment_by_name("Master SMS Segment")` (or the
   segment name parsed from Asana / passed via `--segment`).
4. **Create campaign** — Draft, `channel: sms`, audience = resolved segment ID.
5. **Create + assign message** — SMS body attached to campaign.
6. **Print summary** — campaign name, Klaviyo campaign URL, final SMS body (for human review).
7. **Update Asana task** — writes Klaviyo campaign URL into the `Braze Campaign Link` custom field.

### Copy parsing rule

Primary copy = first non-empty paragraph of the Asana task notes (everything before the first
blank line). The creative-direction line below the separator is ignored — it is a brief for humans,
not the send copy.

## 3. Formatting rules (SMS body)

- Arrow `→` before a link → replace with `: ` (colon + space)
- `LINK` or `[link]` placeholder → replace with the actual URL (from `--link`)
- Combined pattern `→ LINK` / `→ [link]` → replace with `: <url>`
- No space between last word and colon; one space between colon and URL

## 4. Out of scope

- Scheduling (human does this in Klaviyo UI after reviewing)
- Email campaigns (separate flow; email already handled by `import_klaviyo.py`)
- Other brands (only TI uses Klaviyo SMS today; extend later if needed)
- Automatic Asana status transition (can be added later)
