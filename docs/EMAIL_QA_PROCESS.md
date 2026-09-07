# Email QA Process

A step-by-step guide for producers on how to QA, proof, and get approval on email campaigns before sending.

---

## Overview

Every email goes through three stages before it ships:

1. **Build** — Producer builds the email in Braze
2. **Self-QA** — Producer reviews the email in Braze, sends themselves a test, and works through the QA checklist in Asana
3. **Proof & Approval** — Producer sends a proof to relevant stakeholders and posts in the #email-qa Slack channel for sign-off

---

## Stage 1: Build

Set up the campaign in Braze following the brief:

- Campaign named per the [naming convention](https://docs.google.com/spreadsheets/d/10GQdM8YUfQQuCOvgk7fvzHvyswdrxM5e6j0Qii8g4Lk) (`TYPE_CHANNEL_YYYY_MM_DD_BRAND_DESIGN_Description`)
- Subject line and preheader match the brief
- Sender name and reply-to address are correct for the brand
- HTML/copy is built and images are uploaded
- Audience segment is applied
- Send date and time are configured

---

## Stage 2: Self-QA

Work through **both** QA tasks in Asana before requesting approval. Each task has a checklist of sub-items — check them off as you go.

### QA (Email) — Content & Rendering

Do this in two passes: first in the **Braze preview**, then by **sending yourself a test email** and checking on desktop and mobile.

| # | Check | Notes |
|---|-------|-------|
| 1 | Campaign name follows naming conventions | Compare to the [naming convention sheet](https://docs.google.com/spreadsheets/d/10GQdM8YUfQQuCOvgk7fvzHvyswdrxM5e6j0Qii8g4Lk) |
| 2 | Subject line matches brief | |
| 3 | Preheader matches brief | |
| 4 | Sender name & email address | Correct brand sender, not a test/default |
| 5 | Copy matches brief & no typos | Read every word — don't skim |
| 6 | Images match brief | Correct assets, correct order |
| 7 | All images have alt tags | Required for accessibility |
| 8 | All links work and point to correct pages | Click every link in your test email |
| 9 | Link template applied & UTMs appended | Verify in at least one link's URL |
| 10 | Unsubscribe link is present and works | (Skip for transactional messages) |
| 11 | Dynamic tags / personalization renders correctly | Preview with both a populated value and a null value |
| 12 | Font is consistent throughout | Watch for fallback font bleed-through |
| 13 | Desktop readability | Check in your inbox on desktop |
| 14 | Mobile readability | Check on a real device or Braze's mobile preview |
| 15 | Email renders correctly in dark mode | Use your email client's dark mode or Braze preview |
| 16 | Terms and conditions are correct | Verify promo-specific T&Cs match the brief |

### QA Campaign Settings & Audience — Configuration

Do this in **Braze's campaign settings panel** before calculating audience size.

| # | Check | Notes |
|---|-------|-------|
| 1 | Send date matches brief | |
| 2 | Send time matches the [Lifecycle Common Data Set](https://docs.google.com/spreadsheets/...) | Check brand's standard AM or PM send time |
| 3 | Audience segment matches the Asana "Segment" column | **ID and TI:** read the **Segment (Text)** field, not the enum Segment column |
| 4 | Audience segment matches the lists in the Lifecycle Common Data Set | |
| 5 | Old / irrelevant filters have been removed | No leftover filters from a duplicated campaign |
| 6 | Save, calculate exact statistics, and compare audience size to Lifecycle Common Data Set | Flag significant deviations to your manager |

**ID and TI audience lists changed in the segmentation redos** (ID: 7 Braze segments — Full File, Engaged, Highly Engaged, Swatch Purchasers, Swatch Non-Purchasers, Geo Segment - Engaged, Geo Segment - Unengaged; TI: 4 Klaviyo segments — Full File, Engaged, Swatch Purchasers, Swatch Non-Purchasers). For these two brands the campaign's audience is chosen per-task from the **Segment (Text)** Asana field, so check the campaign against that field's value — the old standing lists (ID "Main Email Send List" / "AM VIP B2C Segment", TI "May 2024 Full List" / "AM List VIP") apply only to sends dated before 2026-08-18. Live segment names are in `data/brand_config.yaml`.

---

## Stage 3: Proof & Approval

Once both QA checklists in Asana are complete:

1. **Send a proof** to relevant internal stakeholders (creative lead, brand manager, or whoever is specified in the brief)
2. **Post in #email-qa** with:
   - Brand and campaign name
   - Send date/time
   - A screenshot or Litmus/inbox preview link if available
   - Any callouts (new template, dynamic logic, promo terms, etc.)
3. **Get explicit approval** before scheduling — a thumbs up or written "approved" from the required approver

> **Do not schedule the campaign as "Active" until approval is received.**

---

## Checklist Summary (Quick Reference)

```
Stage 1 — Build
  ☐ Campaign built in Braze per brief

Stage 2 — Self-QA
  Email Content (QA in Braze preview + test email)
  ☐ Campaign name follows convention
  ☐ SL matches brief
  ☐ PH matches brief
  ☐ Sender name & email address
  ☐ Copy matches & no typos
  ☐ Images match
  ☐ Images have alt tags
  ☐ Links work & point to correct pages
  ☐ Link template applied & UTMs appended
  ☐ Unsubscribe link present & works
  ☐ Dynamic tags render correctly
  ☐ Font consistent
  ☐ Desktop readability
  ☐ Mobile readability
  ☐ Dark mode rendering
  ☐ T&Cs correct

  Campaign Settings & Audience (QA in Braze settings)
  ☐ Send date matches brief
  ☐ Send time matches Lifecycle Common Data Set
  ☐ Audience segment matches Asana + Lifecycle Common Data Set
  ☐ No old/irrelevant filters
  ☐ Audience size calculated & verified

Stage 3 — Proof & Approval
  ☐ Proof sent to stakeholders
  ☐ Posted in #email-qa
  ☐ Approval received before scheduling
```

---

## Notes

- **Asana is the source of truth** — the QA checklist sub-tasks in Asana must be marked complete. This is how we track QA status across the team, not just your personal memory.
- **Test emails are not optional** — the Braze preview can miss rendering issues. Always send to a real inbox (or at minimum Litmus) before proofing.
- **Duplicate campaigns carry risk** — always check for leftover audience filters, old subject lines, or incorrect sender settings when duplicating a previous campaign.
- **SMS and push channels** have their own QA tasks in Asana (separate from email). See those checklists for the channel-specific items.
