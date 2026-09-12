# Braze SDK Re-Subscribe Audit — All Brands, Email + SMS

**Date:** 2026-08-28 · **Window:** trailing 90 days (2026-05-22 → 2026-08-20) unless noted
**Trigger:** an SDK-sourced subscription write re-subscribing users who had already opted out, found in ID and checked across HAV, CZ, BUR, STF.

---

## 1. Method (reusable)

Source: Braze raw events datashares.

| Datashare | Database | Schema | Brands |
|---|---|---|---|
| Primary | `BRAZE_BRAZEWEST_BRAZE_RAW_EVENTS_AWS_US_EAST_1_XJ24206` | `DATALAKE_SHARING` | BUR, HAV, CZ |
| TIER3 | `..._XJ24206_TIER3_ID_AND_SF` | `DATALAKE_SHARING_TIERED` | ID, STF |

Key views:
- `USERS_BEHAVIORS_SUBSCRIPTION_GLOBALSTATECHANGE_SHARED` — global email/push subscription state.
- `USERS_BEHAVIORS_SUBSCRIPTIONGROUP_STATECHANGE_SHARED` — per-group (SMS + email) state. Column is `SUBSCRIPTION_GROUP_API_ID`, **not** `SUBSCRIPTION_GROUP_ID`.

Both carry `STATE_CHANGE_SOURCE` (`SDK`, `REST API`, `Shopify`, `List-Unsubscribe`, `Subscription Page`, `Inbound Message` = carrier STOP, `User Merge`, `Canvas User Update Step`, `Dashboard`, `CSV Import`) and `SUBSCRIPTION_STATUS`.

### Rules learned the hard way

1. **Raw SDK volume is not the harm metric.** The metric is a `LAG()` over **full history** (partition by app_group + user; add `SUBSCRIPTION_GROUP_API_ID` for groups) finding SDK `Subscribed`/`Opted In` where `prev_status = 'Unsubscribed'`. Windowing the LAG to 90 days undercounts badly — CZ reads 242 users windowed vs **877** with full history.
2. **Use signed time deltas, not event ordering.** `event.TIME - flip_time` over a symmetric window. A causal event's timestamp can land *at or after* the flip due to ingestion skew. CZ's `waitlist_form_submit` peaks at delta **0s (49)** and **+1s (44)** with neighbours at 3–11 — requiring event-before-flip discards the strongest signal in the dataset.
3. **Read the shape, not just the count.** A true trigger = sub-second spike. Background activity = flat or bimodal smear with mass at the window edges. Elevated *coverage* without tight timing means "user was active on site" (a precondition for the SDK to run), not causation.
4. **Separate real opt-ins before counting.** Exclude users who fired a genuine opt-in event between the unsubscribe and the flip.
5. **For SMS, analyse the subscription group, not the consent event.** Sending depends on group membership; the `Phone Subscribed` event is largely decorative (see §5).

---

## 2. Email — cross-brand

SDK subscribe landing on a previously-`Unsubscribed` profile:

| Brand | app_group_id | SDK subscribe events (90d) | Users re-subscribed | After explicit opt-out | Emails sent to them after |
|---|---|---|---|---|---|
| **ID** | `6666726b459b5e0059d7d687` | 583,471 Opted In + 95,817 Subscribed | **2,558** | 1,410 | 37,292 |
| **CZ** | `666672a4d8965b005ac6c1bd` | 28,737 Subscribed | **877** | 659 | 16,360 |
| **BUR** | `67093a1f24ebbe0065cb9c77` | 9,214 Opted In + 2,343 Subscribed | 219 | 195 | 7,455 |
| **HAV** | `664223fb71bcf3005760dfc2` | 22,860 Subscribed | 12 | 12 | 213 |
| **STF** | `666716b3858150005b566956` | 2,095 Subscribed | 1 | 1 | 0 |

"Explicit opt-out" = prior state change came from `List-Unsubscribe` or `Subscription Page`.

**After excluding genuine opt-in events** (`Newsletter Subscribed` for ID, `waitlist_form_submit` for CZ):

| Brand | Unexplained users | After explicit opt-out | Users emailed after | Emails sent |
|---|---|---|---|---|
| ID | 1,680 | 674 | 389 | 11,774 |
| CZ | 594 | 420 | 530 | 10,806 |

**BUR** is largely a false positive on email — 163 of 219 flips coincide with a real `Subscribed to Promotions` event; only ~15 users lack any opt-in signal. **HAV**'s 12 are mobile app-session events. **STF** email is effectively clean.

### Browsing does not cause re-subscription

Cohort: unsubscribed 5/1–7/20, then viewed a product afterwards.

| Brand | Flipped | Stayed unsubscribed | Flip rate | Excl. genuine opt-in |
|---|---|---|---|---|
| ID | 419 | 2,185 | 16% | **75 / 2,256 = 3.3%** |
| CZ | 214 | 1,198 | 15% | **102 / 1,270 = 8.0%** |

`Product Viewed` coverage is *lower* among ID's flipped users (76%) than among those who stayed (100%). 2,185 ID users viewed 48,354 products after unsubscribing and were never re-subscribed.

---

## 3. SMS — subscription groups (separate, compliance-relevant)

SDK re-subscribing users to an SMS group after they had opted out:

| Brand | After any SMS opt-out | **After a texted STOP** (`Inbound Message`) |
|---|---|---|
| ID | 284 | **166** |
| BUR | 123 | **98** |
| CZ | 61 | 27 |
| STF | 17 | 10 |

BUR is second-worst here despite being nearly clean on email. Overriding a STOP is TCPA territory — treat as its own ticket. **Not caused by ID checkout** (only 5 users re-subscribed to SMS at checkout in 60 days, 2 after a STOP), so the vector is still unidentified.

---

## 4. CZ root cause — `waitlist_form_submit`

Only event with a sub-second lock to the flip:

| Event | % within ±2s of flip | Coverage: flipped vs control |
|---|---|---|
| `waitlist_form_submit` | **29.9%** | 38.6% vs 9.6% |
| `shopify_account_login` | 2.7% | 21.5% vs 6.7% |
| `custom_product_view` | 1.9% | 60.5% vs 29.1% |
| `ecommerce.product_viewed` | 1.2% | 64.4% vs 34.5% |
| `ecommerce.checkout_started` | 0.0% | 23.4% vs 12.4% |

Product view is **not** causal — elevated coverage but diffuse timing (11 of 949 events within ±2s; mass at −300..−61s and +61..+300s).

### Downstream harm

Of 286 waitlist-caused flips:

| What they received after the flip | Sends | Users | % |
|---|---|---|---|
| Waitlist Confirmation canvas | 513 | 285 | 99.7% |
| **General batch & blast** | **4,697** | **267** | **93.4%** |
| Other marketing canvases (Product Browse, Cart Abandon) | 881 | 209 | 73.1% |

Median **13** promo emails per person, max 67 — Labor Day Event, Flash Sale, Archive Sale, Rugs, Pillow Pairings, etc. A single-product waitlist signup silently converts into a full marketing re-subscribe.

**Expected behaviour (team view, 2026-08-28):** joining a waitlist should sign the user up for that product's notifications only; it should **not** re-subscribe them to batch & blast. Complication: in Braze a globally-unsubscribed profile is suppressed for all marketing email, so subscription-group targeting alone can't deliver the back-in-stock alert. Options: (a) treat the alert as transactional outside the marketing subscription state; (b) make the re-subscribe explicit on the form ("You're currently unsubscribed — joining will resubscribe you"); (c) flip global state but exclude via segment filter (maintenance burden, not recommended).

---

## 5. ID root cause — two separate mechanisms

### 5a. Checkout email auto-subscribe with no prior-state check (~30%)

ID **intentionally** auto-subscribes email at checkout; SMS is an optional checkbox ("Sign up SMS for news & special offers"). The intended exception — don't auto-subscribe people who previously unsubscribed — **is not implemented**.

Among 10,128 `Checkout Step Completed` users (60 days), whether an email subscribe was written at checkout, by prior state:

| Email state before checkout | Users | Subscribe written | Rate |
|---|---|---|---|
| No prior state change | 4,067 | 4,042 | 99.4% |
| Subscribed | 1,562 | 1,553 | 99.4% |
| Opted In | 1,328 | 1,323 | 99.6% |
| **Unsubscribed** | **441** | **438** | **99.3%** |

Identical rate across every prior state. **Fix = one conditional: skip the write when current state is `Unsubscribed`.**

Supporting detail:
- Event split: 7,942 fired both `Phone Subscribed` + `Newsletter Subscribed`; 0 SMS-only; 3 email-only; 2,183 neither. Zero SMS-only is expected by construction (email always written), **not** evidence about the checkbox.
- The 2,183 "neither" are **not** previously-unsubscribed (1,875 no prior state change · 216 Opted In · 88 Subscribed · only 49 Unsubscribed) and mostly get no email write either (~15%) — consistent with skipping the contact-info step (returning customer with saved details, or express checkout).
- `Order Completed` sits entirely *after* the flip — the write happens mid-checkout.

**SMS checkbox appears to work correctly.** Of 7,402 who fired `Phone Subscribed`, only **558 (7.5%)** got an actual SMS group write at checkout and 4,826 (65%) were never in an SMS group at all. ~7.5% is a plausible unchecked-box opt-in rate. `Phone Subscribed` fires on contact-step submission, not consent — **do not use it as an SMS consent proxy.**

### 5b. Backend batch job (~70% — the larger, still-unexplained half)

1,463 flip events have **no custom event and no session** between the unsubscribe and the flip.

- **86.3%** land in minutes containing 5+ flips
- only **200 distinct minutes** across 90 days; up to **74 users flipped in a single minute**
- episodic dates: 6/18 (130), 6/19 (176), then nothing until 7/30 (53), 7/31 (278), 8/2 (83), 8/3 (167), 8/5 (229), 8/6 (203), 8/8 (23)

Human browsing does not produce 74 subscription writes in one minute and then go quiet for six weeks. This is a bulk write hitting Braze under an SDK-keyed credential. **Next step: pull the deploy / ETL run history for 6/18–19 and 7/30–8/8.**

---

## 6. Open items

1. **ID §5b** — identify what ran on those nine dates. Largest affected population; invisible to any front-end audit.
2. **ID §5a** — add the prior-state check to the checkout email subscribe.
3. **CZ §4** — waitlist form handler; decide between the three design options above.
4. **SMS STOP overrides (§3)** — vector unidentified for all four brands; not checkout.
5. **BUR/HAV/STF email** — no action needed on current evidence; re-check after the ID/CZ fixes ship.
6. **Remediation question not yet answered** — should the affected profiles (ID 1,680, CZ 594) be force-unsubscribed back to their pre-flip state? Not actioned.

## 7. Corrections made during this audit

Recorded so they aren't re-derived:
- CZ was initially reported as matching ID's "browse fingerprint". Timing analysis disproved it — product view is background activity in both brands.
- ID's `Newsletter`/`Phone Subscribed` co-firing was initially read as forced consent. It is not: email auto-subscribe is by design, and the SMS group data shows the checkbox works.
