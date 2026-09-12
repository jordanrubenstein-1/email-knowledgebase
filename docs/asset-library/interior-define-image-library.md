# Interior Define (ID) — Air Image Library

Reference catalog of existing Interior Define photography in Air (`app.air.inc`), built to inform what imagery to pull into auto-briefed ID emails instead of guessing at URLs or requesting new shoots for content that already exists.

**Air root board:** [Interior Define](https://app.air.inc/b/interior-define-3481a4b1-af9c-4801-9fab-978f95efa53a) (`3481a4b1-af9c-4801-9fab-978f95efa53a`)

**Scope:** This library covers the 4 **photo-first** boards under the ID root — the boards most directly useful for email creative. It deliberately excludes 4 sibling boards that are lower-priority for this purpose:

| Excluded board | Assets | Why excluded |
|---|---|---|
| Influencers | 1,520 | Mostly video/social clips, not stills |
| Sit Videos | 132 | Video only |
| Fabrics | 193 | Swatch/material reference, not lifestyle imagery |
| Product Development | 62 | Internal dev/spec shots, not campaign-ready |

If a future brief needs influencer or fabric-swatch content specifically, those boards can be cataloged the same way (board IDs are in the Air API — ask to have them added).

## Boards in This Library

| Board | Assets | Reference file | Notes |
|---|---|---|---|
| [Lifestyle Imagery](https://app.air.inc/b/lifestyle-imagery-d64cf9c2-817b-4b44-833c-5017266a588f) | 1,079 | [id-lifestyle-imagery.md](id-lifestyle-imagery.md) | **Primary/authoritative source** — check this first |
| [Photoshoots (To Be Sorted)](https://app.air.inc/b/photoshoots-to-be-sorted-7190ee48-4d8b-451b-92d1-49cc99443165) | 663 | [id-photoshoots-unsorted.md](id-photoshoots-unsorted.md) | Board's own description: "mainly duplicates from lifestyle imagery board" — secondary/lower-priority source |
| [UGC](https://app.air.inc/b/ugc-0da550f0-99a4-42dd-adc4-517d03a5cf7b) | 152 | [id-ugc.md](id-ugc.md) | Customer/creator content — 51 assets carry an `@handle` (21 distinct creators) |
| [Studios](https://app.air.inc/b/studios-5cdea032-6838-4b70-9880-092444b18f9b) | 132 | [id-studios.md](id-studios.md) | Showroom/event photography — Dallas Event, Williamsburg, CTZ x ID Denver crossover |

**Total: 2,026 assets catalogued.**

## Combined Category Snapshot

Categories are non-exclusive (an asset can appear in more than one bucket) and are now assigned by a **deterministic keyword ruleset** (`CATEGORY_KEYWORDS` in `scripts/sync_air_image_library.py`), not LLM judgment — see each file's own Category Breakdown for exact per-board counts. At a glance, across all 4 boards:

- **Living Room** is the dominant content type everywhere (890 in Lifestyle Imagery, 252 in Photoshoots, 113 in UGC, 25 in Studios)
- **Detail/Product Vignette** shots (fabric, materials, styling close-ups) are the single largest bucket in Photoshoots (280) and meaningfully present in Lifestyle Imagery (72) and Studios (36)
- **Lifestyle-with-People** content is a strong secondary bucket board-wide, and is actually the *largest* bucket in Studios (65) given its event/showroom focus
- **Bedroom** (115), **Dining/Kitchen** (105), and **Outdoor** (22) exist in Lifestyle Imagery but are comparatively thin — worth checking the per-board files before assuming coverage for those room types
- **Bathroom and Office/Study content is essentially absent** — 1 asset each in Lifestyle Imagery, the board most likely to carry it. Treat any brief needing these room types as a real gap, not just an under-search.
- **Studios** is the only board with location-specific event/showroom photography (Dallas, Williamsburg)

## Do-Not-Use Flags

113 assets across the library are explicitly flagged as unusable via Air's `Section: UNEDITED - DO NOT USE` custom field (or an equivalent "duplicate" marker) — **exclude these from any brief:**

| Board | Flagged count |
|---|---|
| Lifestyle Imagery | 77 |
| Photoshoots (To Be Sorted) | 25 |
| UGC | 11 |
| Studios | 0 |

Flagged assets are marked inline in each board's Full Asset Index (⚠️ DO NOT USE). Note: the UGC count (11) was missed by the original hand-cataloging pass on 2026-07-15, which had concluded those legacy custom fields were null across the board — the automated re-sync (below) caught the discrepancy.

## Keeping This Current

This library is no longer a one-off snapshot — `scripts/sync_air_image_library.py` re-syncs it incrementally:

```bash
uv run python scripts/sync_air_image_library.py              # incremental — only new/changed assets since last run
uv run python scripts/sync_air_image_library.py --board id-studios   # single board
uv run python scripts/sync_air_image_library.py --full        # force a full re-fetch of every board
uv run python scripts/sync_air_image_library.py --dry-run      # preview without writing
```

How it works: Air's asset list API paginates newest-`updatedAt`-first (confirmed empirically, undocumented). Each board's state lives in `data/air_image_library/<slug>.json` (asset ID → full record); the script computes a watermark from the newest `updatedAt` already stored and stops paging as soon as it reaches an asset at or before that point — no full re-fetch needed. Re-tagging/editing an existing asset also bumps its `updatedAt`, so edits get picked up too, not just new imports. It does **not** detect assets removed from a board — run `--full` periodically if that matters.

Board registry (which boards get synced) lives in `data/air_image_library_boards.yaml` — add a board there (with its `board_id`) to bring it into scope, including the excluded boards listed above if a future brief needs them.

For anything time-sensitive between syncs, or if a search here comes up empty, query Air live instead of trusting the doc:
```
mcp__air__list_assets (or list_nested_assets) with parentBoardId=<board id above>, search="<keyword>", or tag=<tag name>
```
