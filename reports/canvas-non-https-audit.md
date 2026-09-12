# Canvas Non-HTTPS Link Audit Report

**Date:** 2026-02-10 20:34
**Canvases checked:** 116
**Email steps checked:** 272
**Canvases with issues:** 4
**Total problematic links:** 46

## Summary by Brand/Workspace

| Workspace | Canvases | Steps | Links |
|-----------|----------|-------|-------|
| CZ | 2 | 4 | 22 |
| ID | 1 | 4 | 22 |
| STF | 1 | 1 | 2 |

## Affected Domains

| Domain | Occurrences |
|--------|-------------|
| `example.com` | 21 |
| `the-citizenry.com` | 6 |
| `theinside.com` | 6 |
| `stfrank.com` | 5 |
| `trade.interiordefine.com` | 4 |
| `interiordefine.com` | 4 |

## Detailed Findings

These are **active triggered flows** — every new user/event hits these emails.
Fixing these has immediate and ongoing impact on tracking.

### Braze Template For Back In Stock
- **Workspace:** CZ
- **Canvas ID:** `e2317c1c-435a-4abb-9f74-b2dd8b4e3b7c`
- **Steps affected:** 3
- **Total bad links:** 21

  **Email** (Subject: _Refreshed stock! Act fast before it's too late!_)
  - [`http://`] `http://www.example.com/?lid=0c97vgaqy8ba`
  - [`http://`] `http://www.example.com/?lid=tsxedzhhc0w4`
  - [`http://`] `http://www.example.com/?lid=garu9xw8za9w`
  - [`http://`] `http://www.example.com/?lid=n30yhpq0idwg`
  - [`http://`] `http://www.example.com/?lid=lxip14aqe20m`
  - [`http://`] `http://www.example.com/?lid=lxip14aqe20m`
  - [`http://`] `http://www.example.com?lid=njegwwlpzaid`

  **Push+Email Alert** (Subject: _Back-in-stock reminder for {{${first_name} | default: 'you'}_)
  - [`http://`] `http://www.example.com/?lid=0vi2lzsdegwt`
  - [`http://`] `http://www.example.com/?lid=d6c0pbaltx3m`
  - [`http://`] `http://www.example.com/?lid=rcgeid45mz90`
  - [`http://`] `http://www.example.com/?lid=6fmvemvwlnob`
  - [`http://`] `http://www.example.com/?lid=q97rsz04pf63`
  - [`http://`] `http://www.example.com/?lid=q97rsz04pf63`
  - [`http://`] `http://www.example.com?lid=sigx5z5uxb43`

  **In-Product Msg & Email** (Subject: _Don't forget about these new arrivals!_)
  - [`http://`] `http://www.example.com/?lid=xp86m8nni8f1`
  - [`http://`] `http://www.example.com/?lid=71l6k8zxntoq`
  - [`http://`] `http://www.example.com/?lid=lmclw7xnpnwq`
  - [`http://`] `http://www.example.com/?lid=vid5cs3qpq1l`
  - [`http://`] `http://www.example.com/?lid=8mw5c2umrz58`
  - [`http://`] `http://www.example.com/?lid=8mw5c2umrz58`
  - [`http://`] `http://www.example.com?lid=3bllj16ij26e`

### Soho Workshop RSVP Confirmation - November, 2025
- **Workspace:** CZ
- **Canvas ID:** `21b1375c-431e-4d79-84f4-bd8e2c26f163`
- **Steps affected:** 1
- **Total bad links:** 1

  **Step 1** (Subject: _You’re on the List_)
  - [no protocol (bare domain)] `the-citizenry.com?lid=cc49toefrpgh`

### Trade Welcome Series
- **Workspace:** ID
- **Canvas ID:** `e1412565-1cc2-4ca6-b5f0-37fbba278520`
- **Steps affected:** 4
- **Total bad links:** 22

  **TRG_EM_2025_07_Trade_D_Welcome_IDSpotlight_T2_V1** (Subject: _Personalize Every Project with Interior Define_)
  - [no protocol (bare domain)] `trade.interiordefine.com?lid=f3vhn0bfa4ze`
  - [no protocol (bare domain)] `interiordefine.com?lid=9o9vpik053el`
  - [no protocol (bare domain)] `the-citizenry.com?lid=0lh7w6pg031m`
  - [no protocol (bare domain)] `theinside.com?lid=l6ix6rg85697`

  **TRG_EM_2025_07_Trade_D_Welcome_SFSpotlight_T5_V1** (Subject: _Design Boldly with St. Frank_)
  - [no protocol (bare domain)] `trade.interiordefine.com?lid=2nug5j66t1uf`
  - [no protocol (bare domain)] `stfrank.com?lid=awvalowarb0u`
  - [no protocol (bare domain)] `stfrank.com?lid=fxb06donvfio`
  - [no protocol (bare domain)] `stfrank.com?lid=6ebbwf0kqxqn`
  - [no protocol (bare domain)] `interiordefine.com?lid=0hmn9ddjaijf`
  - [no protocol (bare domain)] `theinside.com?lid=dbqz1ovifw83`
  - [no protocol (bare domain)] `the-citizenry.com?lid=jl5yxvthe6ce`

  **TRG_EM_2025_07_Trade_D_Welcome_TISpotlight_T4_V1** (Subject: _Make Every Space More Joyful with The Inside_)
  - [no protocol (bare domain)] `trade.interiordefine.com?lid=im3fvjb97n6i`
  - [no protocol (bare domain)] `theinside.com?lid=nm9fj3oikrta`
  - [no protocol (bare domain)] `theinside.com?lid=qj9zwk6m7t63`
  - [no protocol (bare domain)] `theinside.com?lid=lukfh0f1sao8`
  - [no protocol (bare domain)] `interiordefine.com?lid=mvcxb2gz7jmu`
  - [no protocol (bare domain)] `the-citizenry.com?lid=i63s7a5yc3vu`

  **TRG_EM_2025_07_Trade_D_Welcome_CZSpotlight_T3_V1** (Subject: _Layer in Story and Soul with The Citizenry_)
  - [no protocol (bare domain)] `trade.interiordefine.com?lid=nhicdhtmv433`
  - [no protocol (bare domain)] `the-citizenry.com?lid=6eluoiufq06n`
  - [no protocol (bare domain)] `the-citizenry.com?lid=cd40ko5l2nj9`
  - [no protocol (bare domain)] `interiordefine.com?lid=uznt4915svw2`
  - [no protocol (bare domain)] `theinside.com?lid=7pf6m5cgnvly`

### Order Confirmation - Swatch Post Purchase 2025
- **Workspace:** STF
- **Canvas ID:** `14dfd1d5-9584-4632-9b68-4a1f2b777355`
- **Steps affected:** 1
- **Total bad links:** 2

  **TRG_EM_2025_08_SF_D_Order_Confirmation_Post_Purchase_Swatch_T1_V1** (Subject: _Order Confirmed. Style Incoming._)
  - [no protocol (bare domain)] `stfrank.com?lid=hhvvn43rtlg0`
  - [no protocol (bare domain)] `stfrank.com?lid=kdefm70nozcn`
