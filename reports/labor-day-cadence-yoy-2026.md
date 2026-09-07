# Labor Day Email Cadence — YoY, All Brands (2026 vs. 2025)

**Prepared:** 2026-08-28 · **Owner:** Julie Calnero · **Status:** confirmed metric, manual name-review in progress

## Origin

Stang asked for ID's next-week email schedule comped to last year's flighting
("what's our cadence + frequency look like YoY"). That grew into a
distance-from-sale comp (Stang: "Labor day is a week later this year"), then
into the same comp across all six brands.

## Read this before using any number from this analysis

Four ways of scoping "Labor Day cadence" were tried. Three of them produce
numbers that look plausible in isolation but don't hold up:

1. **Calendar week comp** (`next week` vs. `same week last year`) — breaks
   because Labor Day is the first Monday of September and drifts year to
   year. 2025's Labor Day was 9/1; 2026's is 9/7 — 6 days later. A fixed
   calendar week silently compares two different points in the sale.

2. **Whole Aug 1–Sep 30 window** — wide enough to catch the full sale, but
   also wide enough to catch several *other* sales with nothing to do with
   Labor Day (Rug Event, Flash Sale, Bedroom Refresh Sale, Weekender Sale,
   Subscriber Flash Sale, Holiday-Ready Sale, standalone Warehouse Sale
   weeks). Declines measured on this window reflect general email volume,
   not Labor Day cadence specifically. Shown in the script's output for
   reference only — **do not cite these numbers as "the Labor Day comp."**

3. **Category-tag isolation** — filtering to rows tagged `Labor Day Event`
   in the knowledgebase looks like the fix, but the tag is applied by
   **date overlap** against `data/sale_schedules.yaml`, not by content. When
   a second sale is active on the same date (e.g. Interior Define's
   Warehouse Sale ran the *entire* Labor Day period in 2026), unrelated
   content picks up the "Labor Day" tag too. This produced impossible swings
   — ID appeared to jump +32%, Burrow flipped from a decline to +24% — driven
   by tagging overlap, not real cadence change.

4. **Name-based content matching** — tried filtering on whether the
   campaign/task name mentions "Labor Day" directly. Fails even harder:
   2025 rows are the actual Braze/Klaviyo **campaign name**, which spells
   out the sale name by this repo's naming convention. 2026 rows are Asana
   **task names**, which this team's own task-naming standard deliberately
   shortens (e.g. "AM Reminder," not "Labor Day AM Reminder"). The two years
   are labeled by non-comparable conventions — text matching produced
   nonsense (an apparent 1167% "change" for HAV).

5. **Date-window distance-from-anchor (the metric actually used below)** —
   count sends by calendar distance from Labor Day itself, independent of
   category tags or naming conventions. This is the only method where every
   brand moved the same direction and the magnitude was plausible across
   all six.

## The trusted metric: ±1 week around Labor Day

Window = day −7 through day +6 relative to that year's Labor Day (the week
immediately before Labor Day, plus Labor Day's own week — 14 days total, not
a symmetric before/after split).

| Brand | 2025 | 2026 | % Change |
|---|---|---|---|
| CZ | 24 | 10 | −58% |
| STF | 12 | 5 | −58% |
| HAV | 36 | 24 | −33% |
| TI | 15 | 11 | −27% |
| BUR | 28 | 21 | −25% |
| ID | 26 | 21 | −19% |
| **Total** | **141** | **92** | **−35%** |

Every brand is down, no sign flips, no impossible swings — the first version
of this analysis where the numbers hold together across all six brands.

**ID specifically (the original question):** Labor Day week alone (day 0
through +6) is 14 (2025) vs. 11 (2026), a 21% decline — consistent with the
±1-week figure above.

## Important nuance: this is a rate change, not necessarily a total-volume change

The ±1-week window intentionally holds window length constant so the
comparison is fair — but that also means it doesn't capture the full sale.
Checking each brand's actual real promotional span this year (EA launch
through Extension end, per `data/sale_schedules.yaml`, using each brand's
own dates rather than a fixed window) shows a very different total-volume
picture:

| Brand | 2025 span | n | 2026 span | n | % |
|---|---|---|---|---|---|
| HAV | 2025-08-07 to 2025-09-03 | 57 | 2026-08-06 to 2026-09-15 | 60 | +5% |
| CZ | 2025-08-19 to 2025-09-08 | 33 | 2026-08-18 to 2026-09-15 | 21 | −36% |
| ID | 2025-08-19 to 2025-09-08 | 38 | 2026-08-13 to 2026-09-15 | 50 | +32% |
| BUR | 2025-08-19 to 2025-09-09 | 38 | 2026-08-18 to 2026-09-20 | 42 | +11% |
| STF | 2025-08-21 to 2025-09-08 | 18 | 2026-08-20 to 2026-09-08 | 9 | −50% |
| TI | 2025-08-21 to 2025-09-08 | 21 | 2026-08-18 to 2026-09-15 | 24 | +14% |
| **Total** | | **205** | | **206** | **0%** |

This isn't a contradiction of the headline table — it's a different question
with unequal window widths. This year's real promotional calendar runs
longer for most brands (BUR's Extension now runs to 9/20 instead of 9/9;
ID/CZ/TI/HAV extend to 9/15 instead of 9/8; ID also picked up an earlier
"DE Backpocket Preview" phase that didn't exist in 2025). A wider window
naturally catches more total sends, independent of any real change in
daily sending rate — which is exactly the flaw that sank method #2 above,
just approached from the other direction (unequal widths instead of a
single too-wide window).

**Both facts are true and answer different questions:** daily sending pace
(cadence) dropped for every brand in the fixed-width comparison above.
Total volume across the full, now-longer event is roughly flat overall,
and up for HAV/ID/BUR/TI specifically. The fixed-width ±1-week comparison
remains the correct answer to "cadence," which is what was originally
asked — but don't cite the headline decline as "we're sending less overall
this Labor Day" without this context, because for most brands that's not
what the full-span numbers show.

## QA pass with Jordan Rubenstein (2026-08-28)

**Fixed:** HAV counted some combined sends as one instead of two. In 2025,
HAV always split Pre-Converted (DPS) and Converted (MP) audiences into
separate Asana tickets, so each showed up as its own row. In 2026, some
tickets are titled "DPS and MP: ..." (or, in one case, have a blank
Audience field) and represent a single ticket covering both audiences —
still 2 actual sends, not 1. `split_hav_combined_tickets()` in
`scripts/analysis/analyze_labor_day_cadence_yoy.py` splits each of these 12
combined tickets into 2 rows to match how 2025 was counted. This moved
HAV's ±1-week window total from 21 to 24, and its whole-window total
(method #2 above, reference only) from 55 to 67.

**Confirmed already handled, no change needed:** the 3 ID segment-variant
PT sends (Cart Abandoners/Engaged/Swatchees, 9/1/25) and the 2 Extension
retargeting variants (365Day/90Day, 9/5/25) are genuinely distinct sends to
distinct audiences — already counted as separate rows. The 2 BUR
`[delete]`-prefixed duplicate/test rows are excluded by `JUNK_NAME_PATTERN`
(see below, a previously-found and already-corrected issue).

**Still open, not yet resolved in this script:**

- **At least one Asana ticket for an email banner (not an actual email
  send) was found tagged Channel = Email.** It falls outside the ±1-week
  window used for the headline numbers above, so it doesn't affect them —
  but it's evidence that similar mistagging may exist elsewhere in the wider
  Aug 1–Sep 30 pull. **Not yet swept for systematically.**
- **A separate STF ticket's Channel field was being confirmed with Mina**
  at analysis time — if it's a real email, it needs including in whichever
  window it falls into.
- Neither issue has been resolved in `reports/labor_day_cadence_2026_asana_snapshot.json`.
  Treat the whole-window totals (method #2 above) as directionally
  informative only, not as a number to cite.
- A previously-found and already-corrected issue: BUR's 2025 actual-send
  data (`campaigns/*.yaml`) included 2 `[delete]`-prefixed duplicate
  campaigns and 1 test send. `scripts/analysis/analyze_labor_day_cadence_yoy.py`
  filters these out (`JUNK_NAME_PATTERN`); the same pattern was checked
  against the other 5 brands' 2025 data and came back clean.

## Manual verification (in progress, owner: Julie)

Given the small size of the ±1-week window (230 rows total, ~40 per brand),
a full manual name-by-name read is the right final check rather than a
fifth automated classification attempt. The Google Sheet's
`Labor Day Window - Review` tab lists every send in this window, both
years, with a blank column for marking relevance:
<https://docs.google.com/spreadsheets/d/19UnsaFZ9Hv22H2u6KV_o7y_6ONlUTM_n1-2w1V89-Ls/edit>

2025 names are the real sent Braze/Klaviyo campaign names. 2026 names are
Asana task titles.

## Reproducing / updating this analysis

```bash
uv run python scripts/analysis/analyze_labor_day_cadence_yoy.py
```

- The 2025 side re-pulls live from `campaigns/*.yaml` every run — no
  refresh needed.
- The 2026 side reads a point-in-time snapshot,
  `reports/labor_day_cadence_2026_asana_snapshot.json`, pulled via the
  Asana MCP on 2026-08-28 (Brand + Channel=Email custom fields; Lacy
  copy-request subtasks, blank-Type rows, and `[delete]`/`Test_Send` rows
  excluded — see CLAUDE.md's Asana Integration section for field GIDs).
  Asana access wasn't available to this script directly in a plain
  `uv run` context — regenerate the snapshot via a fresh Asana pull if a
  later comparison needs current data, especially once the two open
  data-quality tickets above are resolved.

## Related documents

- Full findings + verification plan (Google Doc): <https://docs.google.com/document/d/1ebbVK4MFBua9jbpbB4LZ-enEPA6SBdVtongnCUvzGK4/edit>
- Business-review version (Google Doc): <https://docs.google.com/document/d/14GxH_SDe2Mr6vm1vl0P4yPwxCL95Ar4DnKmIz33e3sY/edit>
- Raw data spreadsheet (whole Aug 1–Sep 30 window, all brands, tagged): <https://docs.google.com/spreadsheets/d/19UnsaFZ9Hv22H2u6KV_o7y_6ONlUTM_n1-2w1V89-Ls/edit>
