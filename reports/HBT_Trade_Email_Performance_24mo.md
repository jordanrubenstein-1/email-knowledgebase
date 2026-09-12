# Havenly Brands Trade (HBT) — Email Performance, Trailing 24 Months

**Window:** 2024-07-16 → 2026-07-16 (trailing 24 months) · **Generated:** 2026-07-16
**Per-campaign detail:** [`exports/hbt_trade_email_performance_24mo.csv`](../exports/hbt_trade_email_performance_24mo.csv)

## Sources & method (all data refreshed live from source — not the YAML knowledgebase)
- **Engagement (sends/opens/clicks/unsubs):** Braze Raw Events datashare (Snowflake), deduplicated to unique users at the message level. Trade blasts sent from **three Braze workspaces** — Interior Define, The Citizenry, St. Frank (we consolidated to the ID workspace recently; CZ/SF are historical). Trigger = ID **Trade Welcome Series** canvas. TI trade lives only as transactional swatch flows in Klaviyo (pulled from the Klaviyo API).
- **Orders & revenue:** GA4 last-click (Snowflake), Email channel, matched by campaign name and **summed across all four storefronts (CZ + ID + STF + TI)** — a trade email drives cross-brand shopping, so revenue is attributed wherever the order landed.
- **Open rate includes machine opens** (team-standard unique open rate / matches Braze + Klaviyo UI). Apple MPP inflates opens ~4–5×, so **clicks and CTOR are the truer engagement read.** Clicks exclude suspected bots.

> ⚠️ **Revenue is understated and should be read as a floor.** GA4 last-click only captures self-serve online orders attributable to an email session. Trade orders placed through a sales rep, by phone, or on net terms never touch GA4 — so the true trade revenue driven by this program is materially higher than the $489K below. Use these figures for *relative* comparison (trigger vs blast, brand vs brand), not as total program value.

## Headline: trigger vs. blast

Rates are **message-level** (per send) so blast and trigger are apples-to-apples.

| | Sends | Open | Click | CTOR | Unsubs | Orders | Revenue (GA4 x-brand) | Rev / 1k sends |
|---|--:|--:|--:|--:|--:|--:|--:|--:|
| **Blast** (226 campaigns) | 3,659,297 | 44.4% | 0.93% | 2.1% | 15,869 | 271 | $452,127 | $124 |
| **Trigger** (Trade Welcome Series) | 29,529 | 57.3% | **5.26%** | **9.2%** | 0 | 41 | $94,280 | **$3,193** |

At the **per-entrant** level (how the Braze canvas summary reports it — % of the 8,428 people who entered that opened/clicked *any* step), the Trade Welcome runs **65.8% open / 15.6% click**.

**The triggered welcome earns ~26× the revenue per send and ~5–6× the click rate of blast.** It's a tiny fraction of volume but by far the most efficient trade email we send.

> **Trigger revenue spans multiple utm names.** The Trade Welcome's emails have been re-created/renamed over the program's life, so their revenue sits under several `utm_campaign` values in GA4 — the current `TRG_EM_2025_07_Trade_D_Welcome_T1_V2` ($32,192) **and** the earlier `TRG_2024_09_ID_Trade_Welcome_Email` ($44,852), `campaign_ID_Email - Trade_Welcome - Email #1` ($11,638), etc. All are the same canvas and are summed here. (A null `CANVAS_STEP_NAME` in the datashare does **not** block revenue — revenue is keyed on the GA4 utm, not the Braze step name.)

## Blast volume by workspace (24mo)

| Workspace | Campaigns | Sends |
|---|--:|--:|
| Interior Define | 164 | 3,011,447 |
| The Citizenry | 35 | 609,351 |
| St. Frank | 27 | 38,499 |

## Trade Welcome Series — step by step (ID workspace)

Five steps, keyed by their stable Braze step ID (each step's full 24‑month history, combining sends before and after the 2025‑10‑09 rename). Revenue is the sum of every `utm_campaign` version that maps to the step (see CSV `utm_names_matched`):

| Step | Sends | Open | Click | Orders | Revenue | Rev/1k | Live since |
|---|--:|--:|--:|--:|--:|--:|--|
| **T1 — Welcome (entry)** | 8,416 | 60.7% | **12.21%** | 39 | $89,885 | $10,680 | 2024‑09‑05 |
| T2 — ID Spotlight | 5,595 | 58.2% | 3.31% | 1 | $1,907 | $341 | 2025‑07‑17 |
| T3 — CZ Spotlight | 5,369 | 56.3% | 2.72% | 0 | $0 | $0 | 2025‑07‑20 |
| T4 — TI Spotlight | 5,135 | 55.0% | 1.64% | 1 | $2,488 | $484 | 2025‑07‑23 |
| T5 — SF Spotlight | 5,014 | 54.3% | 2.21% | 0 | $0 | $0 | 2025‑07‑26 |
| **Total** | **29,529** | **57.3%** | **5.26%** | **41** | **$94,280** | **$3,193** | |

*Engagement (sends/opens/clicks) is tracked in Braze per step; revenue is tracked in GA4 per `utm_campaign`. The two are bridged by mapping each utm to its step — which is why the utm-revenue breakdown in the CSV carries no per-row send counts (there is no per-utm send data).*

**T1 (the entry email) does virtually all the work** — 12.2% click, and ~$77K of the $94K trigger revenue ($44,852 under its old utm + $32,192 under its current utm). It has run since the program launched (Sept 2024). The brand-spotlight steps **T2–T5 were added in July 2025** and drop off a cliff on clicks with near-zero attributable revenue — the clearest redesign opportunity.

> **Data / versioning note:** there are **only 5 canvas steps** (same step IDs throughout) — not multiple versions in the send data. Braze/the datashare only began populating `CANVAS_STEP_NAME` on send rows on **2025‑10‑09**; sends before that carry a null name but the same step ID, so they're recombined here by ID. Steps' `utm_campaign` values *did* change across creative refreshes (which is why the revenue spans several utm names). All rates are computed by independent aggregation per step ID, **not** a name join — a name join drops null-named rows (`NULL = NULL` is false in SQL) and understates the canvas (this was a bug in the first draft of this report).

## Where the revenue landed (cross-brand split of the $546K)

| Storefront | Orders | Revenue | Share |
|---|--:|--:|--:|
| Interior Define | 151 | $463,328 | 85% |
| The Citizenry | 109 | $58,662 | 11% |
| St. Frank | 39 | $15,720 | 3% |
| The Inside | 13 | $8,697 | 2% |

Even though the emails are cross-brand, **trade purchasing concentrates on Interior Define** (85% of attributable revenue).

## TI (Klaviyo) — transactional trade flows (last 12mo)
`[TRADE] Swatch Order Placed – Confirmation` and `[TRADE] Swatch Order – Shipped`: ~3,456 sends, ~48% open, ~3.6% click. Transactional order confirmations — no marketing revenue. TI's trade *marketing* went through the ID Braze workspace, not TI Klaviyo.

## Top 20 blast campaigns by attributable revenue

| Send date | Campaign | Sends | Open | Click | Orders | Revenue |
|---|---|--:|--:|--:|--:|--:|
| 2025-07-11 | ID_Trade_PT_Geotargeted_Private_Sale | 20,188 | 55.1% | 2.15% | 3 | $54,638 |
| 2025-01-03 | ID_TRADE_Login_Update | 16,408 | 33.8% | 5.67% | 17 | $45,680 |
| 2026-05-04 | ID_PC_PT_Trade_ID_Preview_35%_First_Time_Ever | 22,115 | 45.4% | 1.86% | 8 | $23,210 |
| 2025-02-07 | TRADE_ID_PDW_EA | 17,101 | 15.6% | 1.02% | 6 | $17,973 |
| 2024-11-19 | CZ_BFCM_Sale_Reminder_Trade | 14,494 | 51.8% | 3.22% | 12 | $10,812 |
| 2025-06-23 | ID_Trade_July_4th_Combined_Sale_Announcement | 20,258 | 51.7% | 0.89% | 3 | $9,887 |
| 2025-12-26 | TRADE_ALL_D_PR_EOY_Sale_Reminder | 19,848 | 46.6% | 0.43% | 2 | $8,870 |
| 2026-06-17 | TRADE_PT_ID_Warehouse_Sale | 22,045 | 46.0% | 3.47% | 5 | $8,826 |
| 2025-07-29 | TRADE_ID_D_Contract_Grade_Launch | 9,950 | 12.2% | 1.07% | 2 | $8,737 |
| 2026-04-03 | TRADE_All_D_PR_Perks_Reminder | 20,565 | 45.2% | 0.85% | 4 | $8,623 |
| 2026-05-19 | D_TRADE_TI_STF_Now_Live_Memorial_Day_Sale | 22,132 | 44.7% | 1.00% | 4 | $8,268 |
| 2025-01-28 | D_TRADE_ID_Combined_Trade_Last_Chance | 16,860 | 30.0% | 1.32% | 4 | $8,127 |
| 2026-02-02 | TRADE_ALL_D_PR_Appreciation_Launch | 19,717 | 44.1% | 0.69% | 4 | $8,027 |
| 2025-10-07 | ALL_TRADE_PT_Appreciation_Week_Reminder | 19,914 | 48.4% | 0.76% | 2 | $7,795 |
| 2025-07-23 | TI_TRADE_PT_Summer_Sale | 19,985 | 52.9% | 1.19% | 2 | $7,554 |
| 2025-03-31 | TRADE_ID_March_Sales_Last_Chance | 18,013 | 27.8% | 0.61% | 2 | $7,218 |
| 2026-06-30 | D_TRADE_ID_Warehouse_Sale_Reminder | 22,079 | 43.5% | 1.11% | 2 | $6,678 |
| 2024-12-02 | ID_TRADE_Cyber_Monday_Reminder | 16,210 | 28.8% | 0.90% | 4 | $6,370 |
| 2026-03-24 | TRADE_All_D_PR_Spring_Sale | 20,493 | 43.6% | 0.63% | 2 | $6,058 |
| 2024-12-06 | CZ_Furniture_By_Room_Trade | 14,643 | 51.0% | 1.97% | 5 | $5,984 |

## Takeaways for the combined-trade-list strategy
1. **Lean into triggered.** The welcome trigger earns ~26× the revenue per send of blast ($3,193 vs $124 per 1k) and opens/clicks far better (57.3% / 5.26% vs 44.4% / 0.93%); scaling triggered/behavioral trade journeys is the single clearest lever. (Program total attributable revenue: ~$546K — blast $452K + trigger $94K.)
2. **Fix the welcome after T1.** T1 is excellent; the brand-spotlight steps T2–T5 lose engagement and convert near zero — reorder/consolidate or replace with a stronger offer/CTA.
3. **Blast click rate is very low (0.93%).** Even accounting for machine-open inflation, trade blasts get opened but not clicked — content/offer relevance, not deliverability, is the gap.
4. **Purchasing concentrates on ID (83%).** Cross-brand sends are worth continuing, but ID is where trade converts; CZ is a distant second.
5. **Attribution is the real blocker.** Reported revenue is a floor — rep/offline/net-terms trade orders aren't in GA4. A trade-specific attribution approach (order tags, rep-code matching) would change the picture more than any creative change.
