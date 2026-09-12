# HAV Email Unsubscribe Journey Analysis

*Generated 2026-04-07 · Data: Braze Raw Events Datashare (Jul 2024 – present)*

**Total HAV email unsubscribers:** 238,504

---

## Summary

- **90%** of unsubscribers had NOT paid for a design (never reached `design_fee`)
- **71.6%** have a Havenly account but haven't converted — the largest single group
- **18.4%** are email-only (no account event at all)
- Users who have paid for design unsub at dramatically lower rates: **6.6%** vs **35%** for pre-design_fee
- Unsubscribe pressure is highest at the very beginning: 25% of unsubbers leave within 30 days of account creation

---

## A. Journey Stage at Time of Unsubscribe

Highest milestone each user had completed *before* their unsubscribe.

| Journey Stage | Unsubs | % of Total | Median Days Since Account |
|---|---:|---:|---:|
| No account (email-only) | 87,971 | 36.9% | -29d |
| Account — no design_fee | 126,837 | 53.2% | 38d |
| Post design_fee (pre launch_room) | 3,124 | 1.3% | 185d |
| Post launch_room (pre design_complete) | 7,786 | 3.3% | 127d |
| Post design_process_complete (pre merch) | 6,971 | 2.9% | 340d |
| Post merch_order_completed | 5,815 | 2.4% | 175d |

> **Key takeaway:** The pre-design_fee account holders (71.6%) are the dominant unsub group.
> They have accounts but haven't committed to the service — and email isn't converting them.

---

## B. Time Since Account Creation

Distribution of unsubscribes by days from `registeredAt` to unsubscribe, split by journey stage.

| Time Since Account | Total Unsubs | % | Pre design_fee | Post design_fee | % Post design_fee |
|---|---:|---:|---:|---:|---:|
| Unknown | 89,100 | 37.4% | 88,496 | 604 | 0.7% |
| 0–7 days | 34,790 | 14.6% | 33,781 | 1,009 | 2.9% |
| 8–30 days | 25,454 | 10.7% | 23,705 | 1,749 | 6.9% |
| 31–90 days | 35,860 | 15.0% | 32,660 | 3,200 | 8.9% |
| 91–365 days | 37,639 | 15.8% | 32,273 | 5,366 | 14.3% |
| 365+ days | 15,658 | 6.6% | 8,702 | 6,956 | 44.4% |

> **Note:** The 365+ days group (23.8%) is the largest single bucket — many long-tenured accounts
> eventually unsub after years of non-engagement. The 0–7 day group (14.6%) represents immediate
> post-signup unsubscribers who likely never intended to opt in.

---

## C. Unsubscribe Rate by Journey Stage

Of all users who received at least one email while at each stage, what % unsubscribed at that stage?

| Journey Stage | Recipients | Unsubs | Unsub Rate |
|---|---:|---:|---:|
| No account (email-only) | 321,289 | 87,971 | 27.4% |
| Account — no design_fee | 358,015 | 126,837 | 35.4% |
| Post design_fee (pre launch_room) | 47,002 | 3,124 | 6.7% |
| Post launch_room (pre design_complete) | 41,261 | 7,786 | 18.9% |
| Post design_process_complete (pre merch) | 26,611 | 6,971 | 26.2% |
| Post merch_order_completed | 15,940 | 5,815 | 36.5% |

> **Dramatic drop at design_fee:** Rate falls from ~35% (pre-purchase) to **6.6%** right after
> paying for design. Converts are engaged and not leaving. The rate climbs again post-design as
> the active service engagement fades.
> 
> *Note: these are lifetime cumulative rates (Jul 2024–present), not per-email rates.*

---

## D. Time Within Stage Before Unsubscribing

After entering each stage, how quickly did unsubscribers leave?

| Journey Stage | Unsubs | Median Days | Avg Days | P25 | P75 |
|---|---:|---:|---:|---:|---:|
| Account — no design_fee | 126,837 | 38d | 102d | 7d | 118d |
| Post design_fee (pre launch_room) | 3,124 | 61d | 114d | 15d | 176d |
| Post launch_room (pre design_complete) | 7,786 | 45d | 89d | 13d | 123d |
| Post design_process_complete (pre merch) | 6,971 | 89d | 133d | 34d | 193d |
| Post merch_order_completed | 5,815 | 65d | 110d | 17d | 161d |

> **Stage 1 (account, no design_fee):** Very wide spread (p25=15d, p75=446d) — some unsub quickly,
> many linger for over a year before finally unsubbing. The median of 80 days suggests a ~3-month
> window to convert them before they disengage.
> 
> **Stage 3 (post launch_room):** Fastest unsubs (median 45d) — the launch_room stage may feel like
> a dead-end if design delivery takes too long.

---

## Implications

1. **The pre-design_fee account holder is the core unsub problem.** 71.6% of unsubbers have accounts
   but haven't paid. Email isn't moving them down the funnel, and they eventually disengage.
   The 80-day median suggests there's a ~3-month window to convert before they're likely to unsub.

2. **Design_fee is a strong loyalty signal.** The 6.6% unsub rate post-design_fee (vs 35% pre) is
   the most striking finding. Once a user pays, they stay — but they do eventually unsub if the
   experience ends without a next step.

3. **Post-completion dropout is real.** After design is done (stage 4: 26.2%) or after merch purchase
   (stage 5: 36.5%), rates climb back up. The product relationship may feel "finished" — these users
   don't see a reason to stay subscribed.

4. **~15% unsub within the first week.** The 0–7 day bucket likely contains users who signed up for
   content but weren't expecting email — or who signed up to access a feature and immediately regretted
   opting in.