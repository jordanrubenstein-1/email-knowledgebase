# Braze MAU Billing — Business Case for Contract Renegotiation

**Prepared for:** Braze Contract Negotiation
**Date:** May 2026
**Brand Focus:** Interior Define (ID)

---

## The Billing Reality

Under the proposed contract, Havenly is paying **$170,000/year** for **4.25M Monthly Active Users** across its brand portfolio. Interior Define alone accounted for **1,920,197 MAUs in the last 30 days** — nearly **45% of the total bill**.

ID's email list is **225,000 contacts**. That is the universe of people we can actually market to via Braze. The Braze MAU count is **8.5x larger** than our reachable audience.

---

## What a Braze "MAU" Actually Represents for Interior Define

The gap between 1.92M MAUs and 225K email contacts is not a measurement error — it reflects how Braze defines an active user. Braze's web SDK fires on every page load, creating or updating a profile for every site visitor regardless of whether we have any contact information for that person. A visitor who arrives from a Google ad, browses one page for seven seconds, and leaves is recorded as a Monthly Active User in the same way as a loyal customer who opens every email.

GA4 data for Interior Define's website over the same 30-day period confirms this directly. Total site sessions were approximately **2.0 million** — almost exactly matching the Braze MAU count. The breakdown by channel tells the real story:

| Channel | Sessions | Bounce Rate | Engaged Sessions |
|---|---|---|---|
| Direct | 840,548 | 22% | 663,819 |
| Paid Social | 324,572 | **47%** | 237,078 |
| Unassigned | 286,264 | **48%** | 4,524 |
| Cross-network | 204,240 | 23% | 154,015 |
| Paid Shopping | 95,599 | **45%** | 59,207 |
| Organic Search | 49,413 | 32% | 29,823 |
| Paid Search | 44,076 | 33% | 32,794 |
| (other) | 43,519 | **100%** | 0 |
| Referral | 31,070 | **57%** | 14,658 |
| Organic Social | 25,612 | 29% | 21,601 |
| Email | 23,842 | 38% | 15,493 |
| Affiliates | 16,995 | 41% | 11,034 |
| SMS | 6,132 | 47% | 3,701 |
| *Other channels* | *~12,834* | *varies* | — |
| **Total** | **~2,004,716** | | |

*GA4 bounce = session under 10 seconds with no meaningful interaction.*

A few figures stand out:

**Across all channels, an estimated 684,000 sessions — roughly 34% of the total — bounced within 10 seconds.** These are people who barely registered a visit to the site. Under the current pricing model, Havenly pays the same per-MAU rate for a seven-second bounce from a paid social ad as it does for a loyal customer who places an order.

**Email and SMS together drove only 29,974 sessions — 1.5% of the total MAU count.** Braze's core value proposition is email and SMS marketing, yet the channel group it enables represents a rounding error in its own MAU calculation.

**329,783 sessions came from "Unassigned" and "(other)" sources** — traffic whose origin GA4 could not attribute to a known channel. The "Unassigned" group was 1.6% engaged, and "(other)" recorded a 100% bounce rate with zero engaged sessions. These are visitors who arrived and left almost immediately, with no channel context and no path to identification. Every one of them registers as a Braze MAU.

---

## The Ask

Braze's MAU definition was designed for mobile apps, where an "active user" genuinely indicates intent and engagement. Applied to a web SDK that fires on every page load, it becomes a count of site traffic — not customers.

We are asking Braze to restructure ID's billing around **identified, reachable contacts**: users for whom Havenly holds a verified email address or phone number and to whom a message has been sent within the billing period. By this definition, ID's billable MAU count would align with its 225,000-contact email list — an **88% reduction** from the current 1.92M figure — and would reflect the audience Braze actually helps us reach.

We are prepared to discuss alternative approaches, including tiered pricing that distinguishes anonymous SDK-tracked profiles from identified messaging contacts, or a dedicated lower rate for web-SDK-only profiles. What we are not in a position to accept is continued billing at customer-tier rates for anonymous visitors who will never receive a single message from us.

---

*Data sources: Braze dashboard (MAU, 30-day window); GA4 via Snowflake (AIRBYTE_DATABASE.LANDING_INTERIORDEFINE_GA4, last 30 days); internal lifecycle guidelines (email list size).*
