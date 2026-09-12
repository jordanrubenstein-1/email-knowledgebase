#!/usr/bin/env python3
"""
UI build spec for BUR Flow 1A: Dining Set Completers (Table buyers -> chair recs).

Canvas name: TRG_EM_2026_06_BW_D_Dining_Chair_Rec_1A
Braze canvas creation is NOT supported via the REST API -- build manually in the UI.
This script documents the complete canvas structure and can be run to print a build guide.

Flow 1A -- 4 touches over 50 days:
  T1 (Day  7): Email -- chair recs, no offer
  T2 (Day 21): Email -- chair recs + free shipping
  T3 (Day 35): Email -- Interior Define cross-brand (ID dining chairs)
  T4 (Day 50): SMS   -- free shipping

Entry: post_purchase_1a_enrolled_at changed (set by daily sync job)
Exit:  customer purchases any dining chair while in the canvas
"""

CANVAS_NAME = "TRG_EM_2026_06_BW_D_Dining_Chair_Rec_1A"
CANVAS_STEP_PREFIX = "TRG_EM_2026_06_BW_D_Dining_Chair_Rec_1A"

# Dining CHAIR product_id substrings -- any purchase of these exits the canvas
CHAIR_KEYWORDS = [
    "Alto Dining Chair",
    "Haiku Dining Chair",
    "Sonnet Dining Chair",
]

T1_TEMPLATE_ID = "57fb19b9-8900-4a13-a292-35c4b1bb2a6f"
T3_TEMPLATE_ID = "cfd54939-8e46-4344-923a-c5e1348b1a38"  # ID cross-brand (built by build_bur_dining_chair_rec_t3_template.py)


def print_build_guide():
    print("=" * 70)
    print(f"BRAZE CANVAS BUILD GUIDE: {CANVAS_NAME}")
    print("=" * 70)

    print(f"""
1. CANVAS SETTINGS
------------------
Name:      TRG_EM_2026_06_BW_D_Dining_Chair_Rec_1A
Type:      Action-Based
Re-entry:  Do not allow re-entry
Workspace: Burrow


2. ENTRY TRIGGER
----------------
Trigger:   Custom attribute change
Attribute: post_purchase_1a_enrolled_at
Condition: is less than 1 day ago

The daily sync job (sync_bur_post_purchase_attributes.py, 2:15am UTC) writes
post_purchase_1a_enrolled_at to qualifying table buyers (no chair purchase
within +-14 days of the table buy). Setting that attribute fires canvas entry.
The "less than 1 day ago" condition ensures only freshly-enrolled users enter,
not historical attribute holders if the canvas is ever paused/restarted.


3. EXCEPTION ENTRY CRITERIA
----------------------------
Add ALL of the following with OR logic (any one true = no entry):

  A. Custom attribute: post_purchase_1b_enrolled_at  less than 60 days ago
     -> user is in the Flow 1B (chair buyer) window; don't double-send

  B. Custom attribute: post_purchase_2_enrolled_at   less than 60 days ago
     -> user is in the Flow 2 (sofa) window; don't double-send

  C. Custom attribute: post_purchase_3_enrolled_at   less than 60 days ago
     -> user is in the Flow 3 (sleeper) window; don't double-send

Note: No "1a_enrolled_at IS SET" exception needed -- the entry trigger
("less than 1 day ago") + "Do not allow re-entry" prevent re-enrollment.

Pre-existing chair owners and same-order chair buyers are excluded upstream
by the sync job. Post-enrollment chair purchases are handled by Exit Criteria.


4. EXIT CRITERIA (canvas-level)
--------------------------------
Trigger: Made a Purchase
Filter:  Product ID contains any of (OR logic):
           "Alto Dining Chair"
           "Haiku Dining Chair"
           "Sonnet Dining Chair"

If the user buys dining chairs at any point while in the canvas, they exit
immediately and receive no further emails or SMS.


5. CANVAS FLOW (2 steps per touch, 4 touches)
----------------------------------------------

TOUCH 1 (Day 7)
  Step A: Delay -- 7 days after canvas entry
  Step B: Email -- T1_V1 (Chair Recs, no offer)
    Template:  {T1_TEMPLATE_ID}
    Step name: {CANVAS_STEP_PREFIX}_T1_V1
    From:      Burrow <friends@em.burrow.com>
    Reply-to:  friends@burrow.com
    Subject/preheader set in the template

TOUCH 2 (Day 21)
  Step C: Delay -- 14 days after T1
  Step D: Email -- T2_V1 (Chair Recs + Free Shipping offer)
    Template:  (create TRG_EM_2026_06_BW_D_Dining_Chair_Rec_T2_V1)
    Subject:   Free shipping on dining chairs today
    Body:      Same rec grid as T1, free-shipping badge/banner added at top
    Note:      Confirm offer mechanism with Burrow team (promo code vs.
               auto-apply Shopify discount) before building template

TOUCH 3 (Day 35)
  Step E: Delay -- 14 days after T2
  Step F: Email -- T3_V1 (Interior Define cross-brand)
    Template:  {T3_TEMPLATE_ID}  (TRG_EM_2026_06_BW_D_Dining_Chair_Rec_T3_V1)
    Step name: {CANVAS_STEP_PREFIX}_T3_V1
    From:      Burrow <friends@em.burrow.com>
    Reply-to:  friends@burrow.com
    Subject:   Sometimes you need more options
    Preheader: Meet Interior Define. Custom dining chairs made to order.
    Static 4-slice designed email (no personalization); all slices link to
    interiordefine.com custom dining chairs. Built by
    scripts/build_bur_dining_chair_rec_t3_template.py.

TOUCH 4 (Day 50)
  Step G: Delay -- 15 days after T3
  Step H: SMS -- T4 (Free shipping)
    Step name: {CANVAS_STEP_PREFIX}_T4_SMS
    Copy:
      Burrow: Still need dining chairs? Free shipping -- shop now:
      https://burrow.com/dining
    Note: Replace link with active sale URL if a sale is running on send date.


6. POST-BUILD QA
----------------
  a. Preview T1 with test user jordan.rubenstein+20251014v9@havenly.com --
     Serif + Walnut sample attributes already set; verify all 4 recs populate
  b. Exit criteria: add an Alto/Haiku/Sonnet purchase event to a test user
     mid-canvas and confirm they exit before the next step fires
  c. Entry trigger: manually set post_purchase_1a_enrolled_at to now on a
     test user and confirm canvas entry fires


7. NOTES
--------
  - Canvas can be launched with T1 only. T2/T3/T4 steps can be added later
    in a new canvas version (Braze supports this without stopping the canvas).
  - Flow 1B (chair buyers -> table recs), Flow 2 (sofa/sectional), and
    Flow 3 (sleeper) are separate canvases, mutually exclusive by entry
    trigger (different enrolled_at attributes; no cross-canvas routing needed).
""")


if __name__ == "__main__":
    print_build_guide()
