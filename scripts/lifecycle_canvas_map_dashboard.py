"""
Lifecycle Canvas Map Dashboard
================================
Generates a self-contained HTML file showing email creative thumbnails
alongside 12-week rolling performance metrics for every active lifecycle
canvas — for Burrow, Interior Define, Havenly, The Citizenry, St. Frank,
and The Inside (Klaviyo; GA4 stats only — no Braze datashare).

Output: reports/lifecycle-canvas-map.html

Usage:
    uv run python scripts/lifecycle_canvas_map_dashboard.py
    uv run python scripts/lifecycle_canvas_map_dashboard.py --brand bur
    uv run python scripts/lifecycle_canvas_map_dashboard.py --brand id
    uv run python scripts/lifecycle_canvas_map_dashboard.py --brand hav
    uv run python scripts/lifecycle_canvas_map_dashboard.py --brand cz
    uv run python scripts/lifecycle_canvas_map_dashboard.py --brand stf
    uv run python scripts/lifecycle_canvas_map_dashboard.py --brand ti
    uv run python scripts/lifecycle_canvas_map_dashboard.py --no-stats
"""

import argparse
import base64
import datetime
from pathlib import Path

# ── Paths ─────────────────────────────────────────────────────────────────────

RENDERED = Path("campaigns/screenshots/rendered")
OUT_FILE = Path("reports/lifecycle-canvas-map.html")

# ── Canvas definitions ────────────────────────────────────────────────────────
# Each canvas: name, entry trigger, list of steps.
# Each step: timing label, subject, rendered PNG filename (no path), channel.

CANVASES = {
    "bur": {
        "label": "Burrow",
        "color": "#032033",
        "rows": [
            {
                "name": "Welcome Flow — General",
                "entry": "New subscriber",
                "stats_node": "lifecycle-stats::bur::welcome-general",
                "canvas_ids": ["67227526a4311300737cee81"],
                "ga4_pattern": "TRG_EM%Welcome%",
                "ga4_channel": "EMAIL",
                "steps": [
                    {"t": "T1 · Day 0",  "s": "You're In! Free shipping awaits", "f": "canvas-welcome-flow-general-t1-1a98b9d8.png"},
                    {"t": "T2 · Day 2",  "s": "Find your perfect couch",           "f": "canvas-welcome-flow-general-t2-3413f732.png"},
                    {"t": "T3 · Day 4",  "s": "Get with the best",                 "f": "canvas-welcome-flow-general-t3-3fb8053f.png"},
                    {"t": "T4 · Day 6",  "s": "Furniture in a flash.",             "f": "canvas-welcome-flow-general-t4-0b6810e4.png"},
                ],
            },
            {
                "name": "Post-Order Welcome",
                "entry": "First order placed",
                "stats_node": "lifecycle-stats::bur::post-order-welcome",
                "canvas_ids": ["6941ce9f44fe4b00643a081c"],
                "ga4_pattern": "TRG_EM%Welcome_New_Purchaser%",
                "ga4_channel": "EMAIL",
                "steps": [
                    {"t": "T1 · Day 1",  "s": "You're In! Free shipping awaits", "f": "canvas-post-order-welcome-to-new-subscribers-t1-eb805a94.png"},
                    {"t": "T2 · Day 3",  "s": "Find your perfect couch",           "f": "canvas-post-order-welcome-to-new-subscribers-t2-5a5b4f43.png"},
                    {"t": "T3 · Day 5",  "s": "Get with the best",                 "f": "canvas-post-order-welcome-to-new-subscribers-t3-2cf0cab1.png"},
                    {"t": "T4 · Day 7",  "s": "Furniture in a flash.",             "f": "canvas-post-order-welcome-to-new-subscribers-t4-2a5dde7f.png"},
                ],
            },
            {
                "name": "SMS Welcome",
                "entry": "New subscriber (SMS opt-in)",
                "stats_node": "lifecycle-stats::bur::sms-welcome",
                "canvas_ids": ["673649e7f9dee40073052292"],
                "ga4_pattern": "TRG_SMS%Welcome%",
                "ga4_channel": "SMS",
                "steps": [
                    {"t": "T1 · Day 0",       "s": "Welcome to Burrow!", "body": "👋 Welcome to Burrow — where we make furniture that just makes sense. Clever, modular, easy to assemble, and designed to grow with you.", "f": None, "channel": "sms"},
                    {"t": "T2 · Day 0 · 2hr", "s": "Save our contact",   "body": "Make sure to save us to your contacts to be notified about product launches, special events, and more! [+ contact card]", "f": None, "channel": "sms"},
                    {"t": "T3 · Day 1",       "s": "Modular life",       "body": "Burrow: Moving? Growing? Redecorating? We've got you covered. Modular designs + smart details (like hidden USB ports) make home life stress-free.", "f": None, "channel": "sms"},
                    {"t": "T4 · Day 3",       "s": "Fits your life",     "body": "Burrow: Furniture that fits your life — not the other way around. Easy to move, expand, and love. Because normal was never good enough.", "f": None, "channel": "sms"},
                ],
            },
            {
                "name": "Abandon Browse",
                "entry": "1+ products browsed",
                "stats_node": "lifecycle-stats::bur::abandon-browse-multi",
                "canvas_ids": ["69fd3b44bafe140081cff59e", "6917427b99358600634fe4e5"],
                "ga4_pattern": "TRG_EM%Abandon_Browse_T%",
                "ga4_channel": "EMAIL",
                "steps": [
                    {"t": "T1 · Day 0 · 1hr",    "s": "Still thinking it over?",      "f": "canvas-abandon-browse-multi-product-t1-2e9b7807.png"},
                    {"t": "T2 · Day 0 · ~2hr",  "s": "Cart reminder",    "body": "Burrow: Still thinking it over? Our modular furniture is designed to fit your life—and many pieces ship in days. burrow.com", "f": None, "channel": "sms"},
                    {"t": "T3 · Day 1",          "s": "We Like Your Style",           "f": "canvas-abandon-browse-multi-product-t3-87c4dd97.png"},
                    {"t": "T4 · Day 2",          "s": "Choosing furniture takes time", "f": "canvas-abandon-browse-multi-product-t4-9c36bc73.png"},
                    {"t": "T5 · Day 3",          "s": "Final nudge",      "body": "Burrow: Smart design, easy setup, fast delivery. Take another look at furniture that actually works for you. burrow.com", "f": None, "channel": "sms"},
                ],
            },
            {
                "name": "Abandon Cart",
                "entry": "Cart updated, no purchase",
                "stats_node": "lifecycle-stats::bur::abandon-cart",
                "canvas_ids": ["6969482705594d00645ea309"],
                "ga4_pattern": "TRG_EM%Cart_Abandon%",
                "ga4_channel": "EMAIL",
                "steps": [
                    {"t": "T1 · Day 0 · 30 min", "s": "Just circling back",    "f": "canvas-abandon-cart-cart-updated-t1-7a696095.png"},
                    {"t": "T2 · Day 0 · 90 min", "s": "Cart reminder",   "body": "Burrow: Your cart's ready when you are. Thoughtfully made furniture that sets up easily and ships fast. burrow.com", "f": None, "channel": "sms"},
                    {"t": "T3 · Day 1",           "s": "Your cart is waiting",      "f": "canvas-abandon-cart-cart-updated-t3-0f358f66.png"},
                    {"t": "T4 · Day 2",           "s": "Let's Wrap This Up",         "f": "canvas-abandon-cart-cart-updated-t4-476ef1ef.png"},
                    {"t": "T5 · Day 2 · +1hr",   "s": "Final nudge",     "body": "Burrow: Don't leave good design behind. Your Burrow pieces are still waiting—and many can ship in days. burrow.com", "f": None, "channel": "sms"},
                    {"t": "T6 · Day 3",           "s": "One Last Nudge",             "f": "canvas-abandon-cart-cart-updated-t6-f5afc812.png"},
                ],
            },
            {
                "name": "Swatch Post-Purchase",
                "entry": "Swatch order placed",
                "stats_node": "lifecycle-stats::bur::swatch-post-purchase",
                "canvas_ids": ["69715b92b5e08d0065edaf50"],
                "ga4_pattern": "TRG_EM%Swatch%",
                "ga4_channel": "EMAIL",
                "steps": [
                    {"t": "T1 · Day 5",  "s": "Re: Your Recent Swatch Order", "f": "canvas-swatch-post-purchase-t1-31f11c68.png"},
                    {"t": "T2 · Day 8",  "s": "Meet The Fabrics",             "f": "canvas-swatch-post-purchase-t2-2baac239.png"},
                    {"t": "T3 · Day 11", "s": "Last chance",                  "f": "canvas-swatch-post-purchase-t3-8407a055.png"},
                ],
            },
            {
                "name": "Post-Order Cross-Sell",
                "entry": "Order delivered",
                "stats_node": "lifecycle-stats::bur::post-order-cross-sell",
                "canvas_ids": ["69f8a9b37836af007fe3b29f"],
                "ga4_pattern": None,
                "ga4_channel": "EMAIL",
                "steps": [
                    {"t": "T1 · Day 4", "s": "Complete your space", "f": "canvas-post-order-cross-sell-t1-abfae1b7.png"},
                ],
            },
            {
                "name": "Post-Purchase Dining Chair Rec",
                "entry": "Dining table purchased, no chairs",
                "stats_node": "lifecycle-stats::bur::post-purchase-dining-chair-rec",
                "canvas_ids": ["6a53fa7e65d83c008637d6fb"],
                "ga4_pattern": "TRG_EM%Dining_Chair_Rec%",
                "ga4_channel": "EMAIL",
                "steps": [
                    {"t": "T1 · Day 7", "s": "Your new table is missing something", "f": "canvas-post-purchase-table-buyer-no-dining-chairs-t1-6e38605c.png"},
                ],
            },
            {
                "name": "Post-Purchase Dining Table Rec",
                "entry": "Dining chair purchased, no table",
                "stats_node": "lifecycle-stats::bur::post-purchase-dining-table-rec",
                "canvas_ids": ["6a56c266353e380086fb4c3e"],
                "ga4_pattern": "TRG_EM%Dining_Table_Rec%",
                "ga4_channel": "EMAIL",
                "steps": [
                    {"t": "T1 · Day 7", "s": "Your chairs are ready. Is your table?", "f": "canvas-post-purchase-dining-chair-buyer-no-table-t1-e11fb751.png"},
                ],
            },
        ],
    },
    "id": {
        "label": "Interior Define",
        "color": "#1a1a2e",
        "rows": [
            {
                "name": "Welcome Series",
                "entry": "New subscriber",
                "stats_node": "lifecycle-stats::id::welcome-series",
                "canvas_ids": ["66cfcbced4b53b0065d07435"],
                "ga4_pattern": "TRG_EM%Welcome%",
                "ga4_channel": "EMAIL",
                "steps": [
                    {"t": "T1 · Day 0",   "s": "Hi there, we're Interior Define.", "f": "canvas-welcome-series-august-2024-t1-b0ed6760.png"},
                    {"t": "T2 · ~Day 3",  "s": "Red wine on a white sofa?",        "f": "canvas-welcome-series-august-2024-t2-30154a73.png"},
                    {"t": "T3 · ~Day 7",  "s": "Sofa spotlight: Our 3 best sellers","f": "canvas-welcome-series-august-2024-t3-51d4b271.png"},
                    {"t": "T4 · ~Day 10", "s": "What's your pick?",               "f": "canvas-welcome-series-august-2024-t4-a033340d.png"},
                    {"t": "T5 · ~Day 14", "s": "Reserve FREE design services",    "f": "canvas-welcome-series-august-2024-t5-31f97dfa.png"},
                ],
            },
            {
                "name": "SMS Welcome",
                "entry": "New subscriber (SMS opt-in)",
                "stats_node": "lifecycle-stats::id::sms-welcome",
                "canvas_ids": ["67c1d8240164820062088bbb"],
                "ga4_pattern": "TRG_SMS%Welcome%",
                "ga4_channel": "SMS",
                "steps": [
                    {"t": "T1 · Day 0",   "s": "Welcome + 15% off",           "body": "Interior Define: Welcome to Interior Define! Use code WELCOME15-A6J8D3 for 15% off your next order. Happy Customizing! interiordefine.com", "f": None, "channel": "sms"},
                    {"t": "T2 · Day 3",   "s": "Save our contact",             "body": "Interior Define: Save our contact so you never miss a new collection or exclusive offer! interiordefine.com", "f": None, "channel": "sms"},
                    {"t": "T3 · Day 7",   "s": "Fan favorites",                "body": "Interior Define: Fan favorites are waiting for you. Browse our most-loved custom pieces. interiordefine.com", "f": None, "channel": "sms"},
                    {"t": "T4 · Day 10",  "s": "Discount reminder (15% off)",  "body": "Interior Define: Ready to transform your space? Your 15% off code WELCOME15-A6J8D3 is waiting. Start customizing: interiordefine.com", "f": None, "channel": "sms"},
                    {"t": "T5 · Day 14",  "s": "Order free swatches",          "body": "Interior Define: Order up to 5 free swatches and feel the quality before you buy. swatches.interiordefine.com", "f": None, "channel": "sms"},
                    {"t": "T6 · Day 20",  "s": "Quick ship",                   "body": "Interior Define: Need it fast? Shop our Quick Ship styles — ready in as little as 2 weeks. interiordefine.com/quick-ship", "f": None, "channel": "sms"},
                    {"t": "T7 · Day 28",  "s": "Store invite (zip-based)",     "body": "Interior Define: Come visit us! Meet with design experts, test out our furniture in person, and grab free fabric swatches at your local Interior Define studio. [Links to nearest location based on billing zip]", "f": None, "channel": "sms"},
                    {"t": "T8 · Day 35",  "s": "Pet-friendly fabrics", "body": "Interior Define: Built for real life — including pets. Our performance fabrics stand up to anything. interiordefine.com", "f": None, "channel": "sms"},
                ],
            },
            {
                "name": "Cart Abandon",
                "entry": "Cart viewed, no purchase",
                "stats_node": "lifecycle-stats::id::cart-abandon",
                "canvas_ids": ["6938e165e6ccb600638bd400"],
                "ga4_pattern": "TRG_EM%Cart_Abandon%",
                "ga4_channel": "EMAIL",
                "steps": [
                    {"t": "T1 · Day 0 · ~1hr", "s": "We saved your cart",              "f": "canvas-cart-abandon-cart-viewed-t1-692b18af.png"},
                    {"t": "T1 SMS · ~2hrs",     "s": "Cart reminder",   "body": "Interior Define: Hey there! We noticed you eyeing something on our site...come back and shop now:\nhttps://interiordefine.com/cart", "f": None, "channel": "sms"},
                    {"t": "T2 · Day 2",         "s": "Great choice - you'll love this!", "f": "canvas-cart-abandon-cart-viewed-t2-8fb1a917.png"},
                    {"t": "T3 · Day 7",         "s": "Leave something behind?",          "f": "canvas-cart-abandon-cart-viewed-t3-2037984c.png"},
                    {"t": "T5 · Day 12",        "s": "Don't let your cart expire",       "f": "canvas-cart-abandon-cart-viewed-t4-92faf972.png"},
                ],
            },
            {
                "name": "Browse Abandon — Multi Product",
                "entry": "Browsed ≥1 product",
                "stats_node": "lifecycle-stats::id::browse-abandon-multi",
                "canvas_ids": ["699a006c97ee4600633a266d"],
                "ga4_pattern": "TRG_EM%Browse_Abandon%",
                "ga4_channel": "EMAIL",
                "steps": [
                    {"t": "T1 · Day 0 · ~2hr", "s": "Ready to make it yours?",                          "f": "canvas-browse-abandon-multi-product-t1-57e9f33d.png"},
                    {"t": "T2 · Day 3",         "s": "Your next move?",                                  "f": "canvas-browse-abandon-multi-product-t2-15b3485f.png"},
                    {"t": "T3 · Day 6",         "s": "From browsing to building: let's go",              "f": "canvas-browse-abandon-multi-product-t3-c600fa83.png"},
                    {"t": "T4 · Day 9",         "s": "Every fabric, every detail - exactly how you want it","f": "canvas-browse-abandon-multi-product-t4-79be4f71.png"},
                ],
            },
            {
                "name": "Collection Abandon",
                "entry": "Collection page viewed, no cart",
                "stats_node": "lifecycle-stats::id::collection-abandon",
                "canvas_ids": ["69165689e57910006306426e"],
                "ga4_pattern": "TRG_EM%Collection%Abandon%",
                "ga4_channel": "EMAIL",
                "steps": [
                    {"t": "T1 · Day 1 · 11am", "s": "It's waiting — and it's built to order", "f": "canvas-collection-abandon-t1-ca366e7c.png"},
                    {"t": "T2 · Day 8",         "s": "Still on your mind?",                    "f": "canvas-collection-abandon-t2-c2bce246.png"},
                ],
            },
            {
                "name": "Category Abandon",
                "entry": "Category page viewed, no cart",
                "stats_node": "lifecycle-stats::id::category-abandon",
                "canvas_ids": ["69e7bd9e0606b500c4e2cc59"],
                "ga4_pattern": "TRG_EM%Category%Abandon%",
                "ga4_channel": "EMAIL",
                "steps": [
                    {"t": "T1 · Day 1 · 11:10am", "s": "Find your perfect piece — we'll help", "f": "canvas-category-abandon-t1-7eb1c43d.png"},
                    {"t": "T2 · Day 8",            "s": "Your options, narrowed down",           "f": "canvas-category-abandon-t2-b3f419a6.png"},
                ],
            },
            {
                "name": "Swatch Post Purchase",
                "entry": "Swatch order placed",
                "stats_node": "lifecycle-stats::id::swatch-post-purchase",
                "canvas_ids": ["69ea5da43ffb4800c3029b14", "66be3a290645240075070a3d"],
                "ga4_pattern": "TRG_EM%Swatch%",
                "ga4_channel": "EMAIL",
                "steps": [
                    {"t": "T1 · Day 6",   "s": "Found your fabric match?",                         "f": "canvas-swatch-post-purchase-t1-44f2df61.png"},
                    {"t": "T2 · Day 9",   "s": "[Personalized: shopping_for]",                     "f": "canvas-swatch-post-purchase-t2-a6dddefd.png"},
                    {"t": "T3 · Day 13",  "s": "Best sellers that pair perfectly with your swatches","f": "canvas-swatch-post-purchase-t3-5fd16036.png"},
                    {"t": "T4 · Day 17",  "s": "Your free design consultation",                    "f": "canvas-swatch-post-purchase-t4-c936cf03.png"},
                    {"t": "T5 · Day 20",  "s": "Just ask. A designer is ready to chat right now.", "f": "canvas-swatch-post-purchase-t5-eedbcb63.png"},
                    {"t": "T6 · Day 24",  "s": "Swatches in hand?",                                "f": "canvas-swatch-post-purchase-t6-6bc5103a.png"},
                    {"t": "T7 · Day 28",  "s": "[Personalized: design_style]",                     "f": "canvas-swatch-post-purchase-t7-7bce1cec.png"},
                    {"t": "T8 · Day 32",  "s": "FABRIC TEST: Wine & muddy paws",                   "f": "canvas-swatch-post-purchase-t8-103134e0.png"},
                    {"t": "T9 · Day 37",  "s": "3 homes that started with swatches, just like yours","f": "canvas-swatch-post-purchase-t9-bb39daf7.png"},
                    {"t": "T10 · Day 40", "s": "[Personalized: shopping_for]",                     "f": "canvas-swatch-post-purchase-t10-7a643db6.png"},
                    {"t": "T11 · Day 46", "s": "Order now. Finalize your fabric on your own time.", "f": "canvas-swatch-post-purchase-t11-29c75b9f.png"},
                    {"t": "T12 · Day 60", "s": "[Personalized: shopping_for]",                     "f": "canvas-swatch-post-purchase-t12-11e18a90.png"},
                ],
            },
            {
                "name": "Swatch Cart Abandon",
                "entry": "Swatch cart updated, no order",
                "stats_node": "lifecycle-stats::id::swatch-cart-abandon",
                "canvas_ids": ["6974a5ce1e4d7c0065a37547"],
                "ga4_pattern": "TRG_EM%Swatch_Cart%",
                "ga4_channel": "EMAIL",
                "steps": [
                    {"t": "T1 · ~1 hr", "s": "Your free swatches are waiting",              "f": "canvas-swatch-cart-abandon-t1-07b33cb7.png"},
                    {"t": "T2 · Day 2", "s": "Design confidence starts with your swatches", "f": "canvas-swatch-cart-abandon-t2-d04605bb.png"},
                ],
            },
            {
                "name": "Post Purchase",
                "entry": "Order delivered",
                "stats_node": "lifecycle-stats::id::post-purchase",
                "canvas_ids": ["69d28b4766794500632e0822"],
                "ga4_pattern": "TRG_EM%Post_Purchase%",
                "ga4_channel": "EMAIL",
                "steps": [
                    {"t": "T1 · Day 5 · 3pm local", "s": "It's All in the Details", "f": "canvas-post-purchase-t1-65d89ca3.png"},
                ],
            },
            {
                "name": "Post Purchase — Cross-Sell",
                "entry": "Order placed (bed / sofa / sectional) · ~8 weeks post order",
                "stats_node": "lifecycle-stats::id::post-purchase-cross-sell",
                "canvas_ids": ["6a26f120ec1c4b0083aedea9"],
                "ga4_pattern": "TRG_EM%Cross%CZ%",
                "ga4_channel": "EMAIL",
                "steps": [
                    {"t": "T1 · ~8 wks post order (beds)",            "s": "The rug your feet will thank you for",      "f": "canvas-post-purchase-crossbrand-t1-e1dd177f.png"},
                    {"t": "T1 · ~8 wks post order (sofas/sectionals)", "s": "Finishing touches for your new living room", "f": "canvas-post-purchase-crossbrand-t1-7772ce22.png"},
                ],
            },
        ],
    },
    "hav": {
        "label": "Havenly",
        "color": "#2d5016",
        "rows": [
            {
                "name": "Welcome Stream / Onboarding",
                "entry": "New registered user",
                "stats_node": "lifecycle-stats::hav::welcome-stream",
                "canvas_ids": ["66a54e9ac62044005d7badb4"],
                "ga4_pattern": "TRG_EM%Onboarding%",
                "ga4_channel": "EMAIL",
                "steps": [
                    {"t": "T1 · Day 0 · ~10 min", "s": "We are glad you are here",                      "f": "canvas-welcome-stream-onboarding-series-t1-678b13b7.png"},
                    {"t": "T2 · Day 1",            "s": "Your dream home is waiting",                    "f": "canvas-welcome-stream-onboarding-series-t2-585e49cf.png"},
                    {"t": "T3 · Day 4",            "s": "Design inspo this way ➡️",           "f": "canvas-welcome-stream-onboarding-series-t3-2019bd22.png"},
                    {"t": "T4 · Day 7",            "s": "Our favorite design style of the moment? \U0001f941", "f": "canvas-welcome-stream-onboarding-series-t4-4d878a84.png"},
                ],
            },
            {
                "name": "Design Fee Abandon",
                "entry": "Started checkout, no design fee paid",
                "stats_node": "lifecycle-stats::hav::design-fee-abandon",
                "canvas_ids": ["66be37f34b1d520071aff5b9"],
                "ga4_pattern": "TRG_EM%Design_Fee_Abandon%",
                "ga4_channel": "EMAIL",
                "steps": [
                    {"t": "T1 · Day 0 · ~2hr (no designer)", "s": "We can't wait to get started!",     "f": "canvas-design-fee-abandon-t1-6d9f2428.png"},
                    {"t": "T2 · Day 0 · ~2hr (has designer)", "s": "I can't wait to get started!",    "f": "canvas-design-fee-abandon-t2-529574b0.png"},
                    {"t": "T3 · ~Day 3 (no designer)",        "s": "Don't forget your design package!", "f": "canvas-design-fee-abandon-t3-12596680.png"},
                    {"t": "T4 · ~Day 4 (has designer)",       "s": "Don't forget your design package!", "f": "canvas-design-fee-abandon-t4-b1872cdc.png"},
                ],
            },
            {
                "name": "Room Profile Complete",
                "entry": "Room profile completed",
                "stats_node": "lifecycle-stats::hav::room-profile",
                "canvas_ids": ["66fbef2a117d650064972e73"],
                "ga4_pattern": "TRG_EM%Complete_Profile%",
                "ga4_channel": "EMAIL",
                "steps": [
                    {"t": "T1 · Day 0 · ~15 min", "s": "Let's kick things off!",                        "f": "canvas-room-profile-complete-t1-99b55ff0.png"},
                    {"t": "T2 · Day 1",            "s": "Design your home from your phone \U0001f4f1",   "f": "canvas-room-profile-complete-t2-29eed3ba.png"},
                    {"t": "T3 · Day 2",            "s": "Let's get started on your Havenly design!",    "f": "canvas-room-profile-complete-t3-8c2a8d80.png"},
                    {"t": "T4 · Day 3",            "s": "It's a Great Day to Start Your Room Makeover", "f": "canvas-room-profile-complete-t4-1eeb1520.png"},
                    {"t": "T5 · Day 4 · Living Room", "s": "Your after is waiting...", "f": "canvas-room-profile-complete-t5-67ae2b06.png"},
                    {"t": "T5 · Day 4 · Bedroom",    "s": "Your after is waiting...", "f": "canvas-room-profile-complete-t5-44fc628f.png"},
                    {"t": "T5 · Day 4 · Kitchen",    "s": "Your after is waiting...", "f": "canvas-room-profile-complete-t5-104d387f.png"},
                    {"t": "T5 · Day 4 · Dining Room","s": "Your after is waiting...", "f": "canvas-room-profile-complete-t5-27c9b8c1.png"},
                    {"t": "T5 · Day 4 · Office",     "s": "Your after is waiting...", "f": "canvas-room-profile-complete-t5-34168430.png"},
                    {"t": "T5 · Day 4 · General",    "s": "Your after is waiting...", "f": "canvas-room-profile-complete-t5-bfc60fc4.png"},
                    {"t": "T6 · Day 5",            "s": "Ready to start your design?",                  "f": "canvas-room-profile-complete-t6-b1f7e341.png"},
                    {"t": "T7 · Day 6",            "s": "Always get the best prices, only at Havenly",  "f": "canvas-room-profile-complete-t7-f80804f5.png"},
                ],
            },
            {
                "name": "Shopping Prompts",
                "entry": "Design delivered, no purchase",
                "stats_node": "lifecycle-stats::hav::shopping-prompts",
                "canvas_ids": ["66cb75535b01e700656ca645"],
                "ga4_patterns": ["TRG_EM%Shopping_Prompt%", "TRG_EM%Finished_Design%"],
                "ga4_channel": "Organic Shopping",
                "steps": [
                    {"t": "T1 · Day 0 · ~2hr", "s": "Your design is ready! \U0001f389", "channel": "push", "f": None, "body": "Transform your space with your designer's handpicked pieces. Shop now for the best prices."},
                    {"t": "T2 · Day 2",        "s": "Congrats on your finished design! \U0001f389", "f": "canvas-shopping-prompts-t2-712cad53.png"},
                    {"t": "T3 · Day 4",        "s": "Your design is ready to become reality",   "f": "canvas-shopping-prompts-t3-8d4463f0.png"},
                    {"t": "T4 · Day 6",        "s": "A room made just for you",   "channel": "push", "f": None, "body": "Your personal design is one-of-a-kind. Shop your designer's picks and start enjoying your room ASAP."},
                    {"t": "T5 · Day 7",        "s": "Don't forget to complete your design!",    "f": "canvas-shopping-prompts-t5-b843dfdf.png"},
                    {"t": "T6 · Day 11",       "s": "Pieces go fast \U0001f3c3‍♀️", "channel": "push", "f": None, "body": "Lock in your favorites today before they sell out."},
                    {"t": "T7 · Day 13",       "s": "We handle the hard part",                  "f": "canvas-shopping-prompts-t7-15ab43e7.png"},
                ],
            },
            {
                "name": "Abandon Merch Cart",
                "entry": "Marketplace cart updated, no purchase",
                "stats_node": "lifecycle-stats::hav::abandon-merch-cart",
                "canvas_ids": ["69cf197beb5a4100a7754f09"],
                "ga4_pattern": "TRG_EM%Merch_Abandon_Cart%",
                "ga4_channel": "EMAIL",
                "steps": [
                    {"t": "T1 · Day 0 · ~2hr", "s": "One Click Away From The Best Prices…", "f": "canvas-abandon-merch-cart-t1-661d3a9e.png"},
                    {"t": "T2 · ~Day 2",       "s": "Still thinking it over?",              "f": "canvas-abandon-merch-cart-t2-619e6f06.png"},
                ],
            },

            {
                "name": "AI Session Welcome",
                "entry": "AI design session started (power users)",
                "stats_node": "lifecycle-stats::hav::ai-session-welcome",
                "canvas_ids": ["69a602540b68cb0063c0dfe2"],
                "ga4_pattern": "TRG_EM%AI_Session_Welcome_T%",
                "ga4_channel": "EMAIL",
                "steps": [
                    {"t": "T1 · Day 1", "s": "Still thinking about that room you started?", "f": "canvas-ai-session-welcome-t1-12f1c941.png"},
                ],
            },
            {
                "name": "AI Session Welcome — Power Users v2",
                "entry": "AI session (power user cohort v2)",
                "stats_node": "lifecycle-stats::hav::ai-session-welcome-v2",
                "canvas_ids": ["69a8abffe0662d0063f02b07"],
                "ga4_pattern": "TRG_EM%AI_Session_Welcome_Power_User%",
                "ga4_channel": "EMAIL",
                "steps": [
                    {"t": "T1 · Day 1", "s": "An exclusive discount to take your design further", "f": "canvas-ai-session-welcome-power-users-t1-87434d51.png"},
                ],
            },
            {
                "name": "HIP Profile Complete Series",
                "entry": "Havenly In-Person room profile created",
                "stats_node": "lifecycle-stats::hav::hip-profile-complete",
                "canvas_ids": ["67c895a3359ff60075c8ae7a"],
                "ga4_pattern": "TRG_EM%HIP_Profile_Complete%",
                "ga4_channel": "EMAIL",
                "steps": [
                    {"t": "T1 · Day 0 · Immediate", "s": "Welcome to Havenly! Next steps for getting started", "f": "canvas-hip-profile-complete-series-t1-adacc9df.png"},
                    {"t": "T2 · Day 3",             "s": "Reminder from Havenly: Complete your room profile to get started", "f": "canvas-hip-profile-complete-series-t2-ee7f313d.png"},
                    {"t": "T3 · Day 8",             "s": "Last Call! Complete Your Room Profile", "f": "canvas-hip-profile-complete-series-t3-d4190bc9.png"},
                ],
            },
            {
                "name": "HIP In-Person — Now in Your Market",
                "entry": "HIP-eligible zip provided in onboarding",
                "steps": [
                    {"t": "T1 · Day 1", "s": "In-Person Interior Design Is Now In Your City", "f": "canvas-hip-in-person-eligible-t1-figjam.png"},
                ],
            },
            {
                "name": "AI Session Free Design Package Offer",
                "entry": "AI session — free design package trigger",
                "stats_node": "lifecycle-stats::hav::ai-session-design-package",
                "canvas_ids": ["69dfb82822c2f300aaa3cc20"],
                "ga4_pattern": "TRG_EM%AI_Session_Design_Package%",
                "ga4_channel": "EMAIL",
                "steps": [
                    {"t": "T1 · Day 0 · ~1hr", "s": "[Personalized subject line]",    "f": "canvas-ai-session-free-design-package-offer-t1-0238867a.png"},
                    {"t": "T2 · Day 3",         "s": "Unlock Your Free Design Package", "f": "canvas-ai-session-free-design-package-offer-t2-figjam.png"},
                ],
            },
            {
                "name": "Studio 6 Follow Up — 3D Room Generated",
                "entry": "Studio 6 3D room generated",
                "stats_node": "lifecycle-stats::hav::studio6-followup",
                "canvas_ids": ["6a204d159fcb1e00848e47c1"],
                "ga4_pattern": "OT_EM%Studio6_Follow_Up_3D_Room_Generated%",
                "ga4_channel": "EMAIL",
                "steps": [
                    {"t": "T1 · Day 0 · ~1hr", "s": "Your room, ready to make it real?", "f": "canvas-studio-6-follow-up-3d-room-generated-t1-17f36cd5.png"},
                ],
            },
            {
                "name": "Studio 6 Follow Up — Canvas Generated Abandoned",
                "entry": "Studio 6 Canvas Generated (abandoned — no follow-through)",
                "stats_node": "lifecycle-stats::hav::studio6-canvas-abandoned",
                "canvas_ids": ["6a314e873face40086a931c0"],
                "ga4_pattern": "OT_EM%Studio6_Follow_Up_3D_Room_Abandoned%",
                "ga4_channel": "EMAIL",
                "steps": [
                    {"t": "T1 · Timing TBD", "s": "We made something for your room", "f": "canvas-studio-6-follow-up-canvas-generated-abandoned-t1-a7a0474d.png"},
                ],
            },
            {
                "name": "Studio 6 Recap",
                "entry": "Studio 6 Call Recap Submitted",
                "stats_node": "lifecycle-stats::hav::studio6-recap",
                # No canvas_ids yet — this canvas has never sent, so it has no CANVAS_ID
                # row in the datashare to look up. Add it once the first send lands.
                # Renamed 2026-07-24 to OT_EM_2026_07_HAV_CONV_H_Studio6_Follow_Up_Call_Recap_Submitted
                # (previously collided with "3D Room Generated"'s campaign name), so
                # GA4 sessions/revenue can now be attributed to this canvas specifically.
                "ga4_pattern": "OT_EM%Studio6_Follow_Up_Call_Recap_Submitted%",
                "ga4_channel": "EMAIL",
                "canvas_ids": [],
                "steps": [
                    {"t": "T1 · Not yet sent", "s": "Your room, ready to make it real?", "f": "canvas-studio-6-recap-t1-658fbfe6.png"},
                ],
            },
            {
                "name": "$79 Second Room — Post-Purchase Follow-Up",
                "entry": "design_process_complete + $2k+ merch purchase",
                "steps": [
                    {"t": "T1 · Day 14", "s": "A thank you gift from us to you", "f": "canvas-second-room-bonus-t1-8115bba2.png"},
                    {"t": "T2 · Day 17", "s": "Your home is calling", "channel": "push", "f": None, "body": "Don’t forget — use code ENCORE79 to book your second room design for just $79. This one’s just for you."},
                ],
            },
        ],
    },
    "cz": {
        "label": "The Citizenry",
        "color": "#3d2b1f",
        "rows": [
            {
                "name": "Welcome Flow",
                "entry": "New subscriber — T2 personalizes to browsed category",
                "stats_node": "lifecycle-stats::cz::welcome-flow",
                "canvas_ids": ["66ca34a1e52370006541b78f"],
                "ga4_pattern": "TRG_EM%Welcome%",
                "ga4_channel": "EMAIL",
                "steps": [
                    {"t": "T1 · Day 0",           "s": "Welcome to The Citizenry",           "f": "canvas-welcome-flow-august-2024-t1-0d3798e0.png"},
                    {"t": "T2 · Day 2 · Pillows",  "s": "Handcrafted pillows, made to layer", "f": "canvas-welcome-flow-august-2024-t4-92460444.png"},
                    {"t": "T2 · Day 2 · Bedding",  "s": "Your best rest begins here",         "f": "canvas-welcome-flow-august-2024-t4-fab27f03.png"},
                    {"t": "T2 · Day 2 · Rugs",     "s": "Start from the ground up",           "f": "canvas-welcome-flow-august-2024-t5-7eea57f4.png"},
                    {"t": "T2 · Day 2 · Furniture","s": "American-made, artisan-crafted",     "f": "canvas-welcome-flow-august-2024-t7-c8093871.png"},
                    {"t": "T2 · Day 2 · Baskets",  "s": "Our secret bestseller: baskets",     "f": "canvas-welcome-flow-august-2024-t8-860c0b4a.png"},
                    {"t": "T3 · Day 4",            "s": "The Well-Traveled Home",              "f": "canvas-welcome-flow-august-2024-t1-7a079616.png"},
                    {"t": "T4 · Day 7",            "s": "Iconic For A Reason",                 "f": "canvas-welcome-flow-august-2024-t3-57413916.png"},
                ],
            },
            {
                "name": "Product Browse",
                "entry": "Product viewed, no cart",
                "stats_node": "lifecycle-stats::cz::product-browse",
                "canvas_ids": ["6810bed7cc60ca006684c867"],
                "ga4_pattern": "TRG_EM%Product_Browse%",
                "ga4_channel": "EMAIL",
                "steps": [
                    {"t": "T1 · Day 0 · ~1hr",  "s": "Don't Miss Out: A style you loved is going quick!", "f": "canvas-product-browse-t1-007550a4.png"},
                    {"t": "T2 · Day 0 · ~2hr",  "s": "Browsing reminder", "body": "The Citizenry: Still thinking it over? The style you love is ready to make its way home. Don't miss the chance to make it yours:", "f": None, "channel": "sms"},
                    {"t": "T3 · Day 2",          "s": "A handcrafted favorite—still waiting for you",      "f": "canvas-product-browse-t2-96fbe017.png"},
                    {"t": "T4 · Day 3",          "s": "Back in mind?", "body": "The Citizenry: Handcrafted in small batches, the style you love is still here—but won't be for long. Want in on this round?", "f": None, "channel": "sms"},
                    {"t": "T5 · Day 4",          "s": "Last call: This piece may be gone soon",             "f": "canvas-product-browse-t3-be6602aa.png"},
                ],
            },
            {
                "name": "Cart Abandon",
                "entry": "Cart updated, no purchase",
                "stats_node": "lifecycle-stats::cz::cart-abandon",
                "canvas_ids": ["691f1f8b6eaf61006383dfe0"],
                "ga4_pattern": "TRG_EM%Cart_Abandon%",
                "ga4_channel": "EMAIL",
                "steps": [
                    {"t": "T1 · Day 0 · ~20 min", "s": "Going, going...", "channel": "sms", "body": "The Citizenry: Going, going... Handcrafted in small batches, don't miss out on the styles you were eyeing. Check your cart now: [cart URL]"},
                    {"t": "T2 · Day 0 · ~1hr",    "s": "We saved your cart",      "f": "canvas-cart-abandon-new-event-t2-04543554.png"},
                    {"t": "T3 · Day 1",            "s": "Your cart is waiting...", "f": "canvas-cart-abandon-new-event-t3-4fcbe898.png"},
                    {"t": "T4 · Day 2",            "s": "Your Cart is Ready",      "f": "canvas-cart-abandon-new-event-t4-ea428e8b.png"},
                ],
            },
            {
                "name": "Post Purchase",
                "entry": "Order placed",
                "stats_node": "lifecycle-stats::cz::post-purchase",
                "canvas_ids": ["6813b5ec94c2030065148108"],
                "ga4_pattern": "TRG_EM%Post_Purchase%",
                "ga4_channel": "EMAIL",
                "steps": [
                    {"t": "T1 · Day 1 (rug orders)",    "s": "The right way to care for your rug",        "f": "canvas-post-purchase-t6-80c51839.png"},
                    {"t": "T1 · Day 1 (linen/bedding)", "s": "The right way to care for your new linen",  "f": "canvas-post-purchase-t5-ed56c60e.png"},
                    {"t": "T1 · Day 1",                 "s": "Complete the Look: The Well-Traveled Home", "f": "canvas-post-purchase-t1-4c596723.png"},
                    {"t": "T2 · ~Day 2",                "s": "See the impact of your purchase...",        "f": "canvas-post-purchase-t2-8795654c.png"},
                    {"t": "T3 · ~Day 9", "s": "Want to finish your space?", "channel": "sms", "body": "Want to finish your space? Bring home our in-stock, ready-to-ship designs: https://www.the-citizenry.com/collections/ready-to-ship"},
                ],
            },
            {
                "name": "Swatch Post Purchase",
                "entry": "Swatch order placed",
                "stats_node": "lifecycle-stats::cz::swatch-post-purchase",
                "canvas_ids": ["68b0be5faaca2100660bdb91"],
                "ga4_pattern": "TRG_EM%Swatch%",
                "ga4_channel": "EMAIL",
                "steps": [
                    {"t": "T1 · Day 2",  "s": "Re: Your Swatch Order",     "f": "canvas-swatch-post-purchase-t1-b17b4b2b.png"},
                    {"t": "T2 · Day 4",  "s": "So, What Happens Next?",    "f": "canvas-swatch-post-purchase-t4-67ddf029.png"},
                    {"t": "T3 · Day 10", "s": "Thoughts on your swatches?", "f": "canvas-swatch-post-purchase-t3-70e1710c.png"},
                    {"t": "T5 · Day 15", "s": "How can I help?",            "f": "canvas-swatch-post-purchase-t2-1d01f3bf.png"},
                ],
            },
            {
                "name": "Waitlist Confirmation",
                "entry": "Joined waitlist",
                "stats_node": "lifecycle-stats::cz::waitlist-confirm",
                "canvas_ids": ["66bf64931adad20066ee2990"],
                "ga4_pattern": "TRG_EM%Waitlist_Confirm%",
                "ga4_channel": "EMAIL",
                "t1_step_filter": "%Waitlist_Confirmation%",
                "steps": [
                    {"t": "T1 · Immediate", "s": "You're on the list!", "f": "canvas-waitlist-confirmation-t1-559e3ee8.png"},
                ],
            },
            {
                "name": "Waitlist Release",
                "entry": "Waitlisted item back in stock",
                "stats_node": "lifecycle-stats::cz::waitlist-release",
                "canvas_ids": ["66b8b607a8d25f0075f8a23e"],
                "ga4_pattern": "TRG_EM%Waitlist_Release%",
                "ga4_channel": "EMAIL",
                "steps": [
                    {"t": "T1 · Immediate", "s": "Waitlist Update: [product]",        "f": "canvas-waitlist-release-campaign-t1-1c7564a8.png"},
                    {"t": "T2 · Day 2",     "s": "Still available—for now: [product]", "f": "canvas-waitlist-release-campaign-t2-caa7cc01.png"},
                    {"t": "T3 · Day 3",     "s": "Inventory's moving fast: [product]", "body": "The Citizenry: Inventory's moving fast—{{ items[0].product_title }} is still in stock, but not for long. Grab yours:", "f": None, "channel": "sms"},
                ],
            },
            {
                "name": "SMS Welcome",
                "entry": "New subscriber (SMS opt-in)",
                "stats_node": "lifecycle-stats::cz::sms-welcome",
                "canvas_ids": ["67e55d67c465400076dd3dab"],
                "ga4_pattern": "TRG_SMS%CZ%Welcome%",
                "ga4_channel": "SMS",
                "steps": [
                    {"t": "T1 · Day 0", "s": "You're on the list!", "body": "The Citizenry: You're on the list! You now have access to new collections, insider perks, & more. Discover our best sellers: https://www.the-citizenry.com/collections/all-best-sellers", "f": None, "channel": "sms"},
                    {"t": "T2 · Day 1", "s": "Save our contact",    "body": "The Citizenry: Want to make it official? Add us to your contacts so you never miss a notification.\n\nExplore our collections: https://www.the-citizenry.com/", "f": None, "channel": "sms"},
                    {"t": "T3 · Day 3", "s": "From master artisans","body": "The Citizenry: From master artisans to your home. We travel the globe to bring the best craftsmanship home to you. Explore our collections of sustainable, fair trade home goods.\n\nStart your journey: https://www.the-citizenry.com/", "f": None, "channel": "sms"},
                ],
            },
        ],
    },
    "stf": {
        "label": "St. Frank",
        "color": "#1a1a1a",
        "rows": [
            {
                "name": "Welcome Flow",
                "entry": "New subscriber",
                "stats_node": "lifecycle-stats::stf::welcome-flow",
                "canvas_ids": ["66a42ad0782fdb005de94911"],
                "ga4_pattern": "TRG_EM%Welcome%",
                "ga4_channel": "EMAIL",
                "steps": [
                    {"t": "T1 · Day 0",   "s": "Welcome to the Inner Circle",               "f": "canvas-welcome-flow-t1-66bbb46e.png"},
                    {"t": "T2 · ~Day 2",  "s": "Step Into the World of Cosmo Bohème",  "f": "canvas-welcome-flow-t2-c19793a5.png"},
                    {"t": "T3 · ~Day 5",  "s": "New Arrivals. Cult Favorites. All St. Frank.", "f": "canvas-welcome-flow-t3-58abf299.png"},
                    {"t": "T4 · ~Day 9",  "s": "We ❤️ Your Style",                 "f": "canvas-welcome-flow-t4-50ad0563.png"},
                    {"t": "T5 · ~Day 14", "s": "As Seen Chez-Vous",                          "f": "canvas-welcome-flow-t5-d9659ecf.png"},
                ],
            },
            {
                "name": "Product Browse Abandon",
                "entry": "Product viewed, no cart",
                "stats_node": "lifecycle-stats::stf::product-browse",
                "canvas_ids": ["669c506624b6c0005a2df506"],
                "ga4_pattern": "TRG_EM%PBA%",
                "ga4_channel": "EMAIL",
                "steps": [
                    {"t": "T1 · ~1hr",   "s": "You left something behind…",  "f": "canvas-product-browse-t1-b7022f47.png"},
                    {"t": "T2 · ~Day 1", "s": "Still thinking it over?",           "f": "canvas-product-browse-t2-0e9fb250.png"},
                ],
            },
            {
                "name": "Cart Abandon",
                "entry": "Cart updated, no purchase",
                "stats_node": "lifecycle-stats::stf::cart-abandon",
                "canvas_ids": ["669518d9d1bb250059882b87"],
                "ga4_pattern": "TRG_EM%Cart_Abandon%",
                "ga4_channel": "EMAIL",
                "steps": [
                    {"t": "T1 · ~1hr",   "s": "You have exceptional taste",  "f": "canvas-cart-abandon-t1-7991fc84.png"},
                    {"t": "T2 · ~Day 1", "s": "Your cart is waiting…",  "f": "canvas-cart-abandon-t2-749f70ad.png"},
                ],
            },
            {
                "name": "SMS Welcome",
                "entry": "New subscriber (SMS opt-in)",
                "stats_node": "lifecycle-stats::stf::sms-welcome",
                "canvas_ids": ["6888b4ccc0dcb8006789a9b1"],
                "ga4_pattern": "TRG_SMS%SF%Welcome%",
                "ga4_channel": "SMS",
                "steps": [
                    {"t": "T1 · Day 0", "s": "Welcome!",          "body": "St. Frank: Welcome! You can use the code FIRSTTIME20 at checkout for 20% off your first order (exclusions apply). Shop now: https://www.stfrank.com/", "f": None, "channel": "sms"},
                    {"t": "T2 · Day 1", "s": "Save our contact",  "body": "St. Frank: Don't forget to save our contact so you never miss out on exclusive updates!", "f": None, "channel": "sms"},
                    {"t": "T3 · Day 3", "s": "Still deciding?",   "body": "St. Frank: Still deciding? In case you missed it, use offer FIRSTTIME20 at checkout for 20% off your order (exclusions apply). Shop now: https://www.stfrank.com/", "f": None, "channel": "sms"},
                ],
            },
        ],
    },
    "ti": {
        "label": "The Inside",
        "color": "#1a1a1a",
        "rows": [
            {
                "name": "Welcome Series",
                "entry": "New subscriber",
                "stats_node": "lifecycle-stats::ti::welcome-series",
                "canvas_ids": ["SmPgUp"],
                "ga4_pattern": "TRG_EM%TI%Welcome%",
                "ga4_channel": "EMAIL",
                "steps": [
                    {"t": "T1", "s": "Welcome to your design era 💫",           "f": "klv-flow-welcome-series-new-t27-V885ai.png"},
                    {"t": "T2", "s": "Let's have a little fun",                  "f": "klv-flow-welcome-series-new-t28-Sh4mfk.png"},
                    {"t": "T3", "s": "Design it your way (because why settle?)", "f": "klv-flow-welcome-series-new-t29-WvLaRG.png"},
                    {"t": "T4", "s": "The best part? Making it yours.",          "f": "klv-flow-welcome-series-new-t30-Wmkqcc.png"},
                    {"t": "T5", "s": "Final Call on 15% Off",                   "f": "klv-flow-welcome-series-new-t31-VQnBYB.png"},
                ],
            },
            {
                "name": "SMS Welcome Series",
                "entry": "New SMS subscriber",
                "stats_node": "lifecycle-stats::ti::sms-welcome",
                "canvas_ids": ["TudnCd"],
                "ga4_pattern": "TRG_EM_2024_01_TI_D_Welcome_SMS_Welcome_Journey%",
                "ga4_channel": "SMS",
                "steps": [
                    {"t": "T1 · Day 0", "s": "SMS Welcome", "channel": "sms", "f": None,
                     "body": "Welcome to The Inside! Use code WELCOME15-BOLD26 for 15% off your first order. theinside.com"},
                ],
            },
            {
                "name": "Abandon Cart",
                "entry": "Cart updated, no purchase",
                "stats_node": "lifecycle-stats::ti::abandon-cart",
                "canvas_ids": ["NQMyBY", "REanGd"],
                "ga4_pattern": "TRG%TI%Cart_Abandon%",
                "ga4_channel": "EMAIL",
                "steps": [
                    {"t": "T1 · 30m",  "s": "You left something behind…",                                          "f": "klv-flow-abandon-cart-abandon-nonswatch-t01-RNrZz8.png"},
                    {"t": "T2 · 1h",   "s": "Cart abandon SMS", "channel": "sms",                                  "f": None, "body": "Still thinking it over? We saved the items in your cart for you here: https://www.theinside.com/cart"},
                    {"t": "T3 · Day 4","s": "Did you forget something?",                                            "f": "klv-flow-abandon-cart-abandon-nonswatch-t02-VRTBkb.png"},
                ],
            },
            {
                "name": "Abandon Browse",
                "entry": "Product viewed, no cart, no purchase",
                "stats_node": "lifecycle-stats::ti::abandon-browse",
                "canvas_ids": ["VMTjse"],
                "ga4_pattern": "TRG%TI%Browse_Abandon%",
                "ga4_channel": "EMAIL",
                "steps": [
                    {"t": "T1 · 1h",    "s": "Still thinking about it?", "f": "klv-flow-abandon-browse-abandon-new-drip-nonswatch-t01-Tnspj8.png"},
                    {"t": "T2 · Day 4", "s": "Your next move?",         "f": "klv-flow-abandon-browse-abandon-new-drip-nonswatch-t02-YebFkR.png"},
                ],
            },
            {
                "name": "Order Confirmation",
                "entry": "Order placed (non-swatch)",
                "stats_node": "lifecycle-stats::ti::order-confirmation",
                "canvas_ids": ["XyDtUU"],
                "ga4_pattern": "TRG_EM%TI%Order_Confirmation_Non_Swatch%",
                "ga4_channel": "EMAIL",
                "steps": [
                    {"t": "T1 · Day 0", "s": "Your order is confirmed!",  "f": "klv-flow-new-order-placed-nonswatch-ord-t01-UyMKn4.png"},
                ],
            },
            {
                "name": "Order Shipped — Non-Swatch",
                "entry": "Shipment dispatched",
                "stats_node": "lifecycle-stats::ti::order-shipped-nonswatch",
                "canvas_ids": ["TsqSNL"],
                "ga4_pattern": "TRG_EM%TI%Shipping_Confirmation_Non_Swatch%",
                "ga4_channel": "EMAIL",
                "steps": [
                    {"t": "T1",         "s": "Great news! Your order shipped.",  "f": "klv-flow-new-shipped-nonswatch-order-sh-t01-UBPHGC.png"},
                    {"t": "T1 · Sofas", "s": "Great news! Your order shipped.",  "f": "klv-flow-new-shipped-nonswatch-order-sh-t02-TzrDey.png"},
                ],
            },
            {
                "name": "Post-Delivery — Non-Swatch",
                "entry": "Order delivered (AfterShip)",
                "stats_node": "lifecycle-stats::ti::post-delivery-nonswatch",
                "canvas_ids": ["RYqsRt"],
                "ga4_pattern": "TRG_EM%TI%Delivery_Confirmation%NonSwatch%",
                "ga4_channel": "EMAIL",
                "steps": [
                    {"t": "T1 · Day 0",  "s": "Your order from The Inside has arrived!", "f": "klv-flow-new-order-delivered-nonswatch--t01-SRFgxb.png"},
                    {"t": "T2 · Day 20", "s": "Complete your look.",                      "f": "klv-flow-new-order-delivered-nonswatch--t03-VNVeN8.png"},
                ],
            },
            {
                "name": "Swatch Order Confirmed",
                "entry": "Swatch order placed",
                "stats_node": "lifecycle-stats::ti::swatch-order-confirmed",
                "canvas_ids": ["LsWEmF"],
                "ga4_pattern": "TRG_EM%TI%Order_Confirmation_Swatch%",
                "ga4_channel": "EMAIL",
                "steps": [
                    {"t": "T1 · Day 0", "s": "Your swatch order is confirmed", "f": "klv-flow-confirmation-swatch-order-plac-t01-NH95MZ.png"},
                ],
            },
            {
                "name": "Order Shipped — Swatch",
                "entry": "Swatch order shipped",
                "stats_node": "lifecycle-stats::ti::order-shipped-swatch",
                "canvas_ids": ["Neexkg"],
                "ga4_pattern": "TRG_EM%TI_D%Shipping_Confirmation_Swatch%",
                "ga4_channel": "EMAIL",
                "steps": [
                    {"t": "T1 · Day 0",  "s": "Your next step ✨",          "f": "klv-flow-shipped-order-shipped-swatch-t01-XT9zCb.png"},
                    {"t": "T2 · Day 0",  "s": "Great news! Items shipped.", "f": "klv-flow-shipped-order-shipped-swatch-t02-YfhAvK.png"},
                    {"t": "T4 · Day 8",  "s": "Best for a reason",          "f": "klv-flow-shipped-order-shipped-swatch-t04-RUmmW8.png"},
                    {"t": "T6 · Day 10", "s": "The reviews are in",         "f": "klv-flow-shipped-order-shipped-swatch-t06-WnyYhx.png"},
                ],
            },
            {
                "name": "Trade Swatch Shipped",
                "entry": "Trade swatch order shipped",
                "stats_node": "lifecycle-stats::ti::trade-swatch-shipped",
                "canvas_ids": ["QyPJqw"],
                "ga4_pattern": "TRG_EM%TI_Trade%Shipping_Confirmation_Swatch%",
                "ga4_channel": "EMAIL",
                "steps": [
                    {"t": "T1", "s": "Your free swatches have shipped!", "f": "klv-flow-trade-swatch-order-shipped-t05-WCfdCZ.png"},
                    {"t": "T2", "s": "Your free swatches have arrived.", "f": "klv-flow-trade-swatch-order-shipped-t01-H9erkq.png"},
                    {"t": "T3", "s": "The reviews are in.",              "f": "klv-flow-trade-swatch-order-shipped-t02-YqFv7g.png"},
                    {"t": "T4", "s": "Best for a reason",                "f": "klv-flow-trade-swatch-order-shipped-t03-XmFUDm.png"},
                    {"t": "T5", "s": "Need More Swatches?",              "f": "klv-flow-trade-swatch-order-shipped-t04-YwCfuj.png"},
                ],
            },
            {
                "name": "Waitlist — Added",
                "entry": "Customer joins waitlist",
                "stats_node": "lifecycle-stats::ti::waitlist-added",
                "canvas_ids": ["QZpZKU"],
                "ga4_pattern": "TRG_EM%TI%Waitlist_T%",
                "ga4_channel": "EMAIL",
                "steps": [
                    {"t": "T1", "s": "Thanks for joining the waitlist.", "f": "klv-flow-waitlist-added-to-waitlist-t01-VS5C9c.png"},
                ],
            },
            {
                "name": "Back in Stock",
                "entry": "Waitlisted product back in stock",
                "stats_node": "lifecycle-stats::ti::back-in-stock",
                "canvas_ids": ["QZHdRC"],
                "ga4_pattern": "TRG_EM%TI%Waitlist%Item%Back%",
                "ga4_channel": "EMAIL",
                "steps": [
                    {"t": "T1", "s": "Great news! Your waitlisted product is back in stock.", "f": "klv-flow-waitlist-your-item-is-back-in--t01-YrTLY6.png"},
                ],
            },
            {
                "name": "Delayed Order",
                "entry": "Order delayed notification",
                "stats_node": "lifecycle-stats::ti::delayed-order",
                "canvas_ids": ["RpkW38"],
                "ga4_pattern": "TRG_EM%TI%Delayed_Order%",
                "ga4_channel": "EMAIL",
                "steps": [
                    {"t": "T1", "s": "We are still working on your order.", "f": "klv-flow-delayed-order-t01-Ygma3w.png"},
                ],
            },
        ],
    },
    "te": {
        "label": "The Expert",
        "color": "#0a0a0a",
        "rows": [
            {
                "name": "Welcome — Shopping for Clients",
                "entry": "New subscriber · shopping_for = clients",
                "canvas_ids": [],
                "ga4_pattern": None,
                "steps": [
                    {"t": "T1 · Immediately", "s": "Welcome to The Expert",        "f": "klv-flow-flow-welcome-series-t01-RexA77.png",    "f_dir": "ss"},
                    {"t": "T2 · Day 1",       "s": "Join The Expert Trade Program", "f": "klv-flow-flow-welcome-series-t07-VcTHRZ.png",    "f_dir": "ss"},
                ],
            },
            {
                "name": "Welcome — Shopping for Consultation",
                "entry": "New subscriber · shopping_for = consultation",
                "canvas_ids": [],
                "ga4_pattern": None,
                "steps": [
                    {"t": "T1 · Immediately", "s": "Welcome to The Expert",                               "f": "klv-flow-flow-welcome-series-t01-RexA77.png",    "f_dir": "ss"},
                    {"t": "T2 · Day 1",       "s": "Questions about consultations?",                      "f": "klv-flow-flow-welcome-series-t02-VmM9pi.png",    "f_dir": "ss"},
                    {"t": "T3 · Day 1",       "s": "Our Experts' shopping secrets, revealed.",            "f": "klv-flow-flow-welcome-series-t03-U7K4a4.png",    "f_dir": "ss"},
                    {"t": "T4 · Day 4",       "s": "A before & after signed Jake Arnold",                 "f": "klv-flow-flow-welcome-series-t04-YeYBsf.png",    "f_dir": "ss"},
                    {"t": "T5 · Day 7",       "s": "Bring Miles Redd's iconic style home",               "f": "klv-flow-flow-welcome-series-t05-Yamm6R.png",    "f_dir": "ss"},
                    {"t": "T6 · Day 10",      "s": "This tangerine-hued pantry borrows from the Brits",  "f": "klv-flow-flow-welcome-series-t06-YjHZ4R.png",    "f_dir": "ss"},
                    {"t": "T7 · Day 13",      "s": "Caitlin Flemming's go-to wallpaper",                 "f": "klv-flow-flow-welcome-series-t13-QZBWMT.png",    "f_dir": "ss"},
                ],
            },
            {
                "name": "Welcome — Shopping for Myself",
                "entry": "New subscriber · shopping_for = myself (or other)",
                "canvas_ids": [],
                "ga4_pattern": None,
                "steps": [
                    {"t": "T1 · Immediately", "s": "Welcome to The Expert",                               "f": "klv-flow-flow-welcome-series-t01-RexA77.png",    "f_dir": "ss"},
                    {"t": "T2 · Day 2",       "s": "Our Experts' shopping secrets, revealed.",            "f": "klv-flow-flow-welcome-series-t08-SGJpcT.png",    "f_dir": "ss"},
                    {"t": "T3 · Day 2",       "s": "Bring Miles Redd's iconic style home",               "f": "klv-flow-flow-welcome-series-t09-S3GkrK.png",    "f_dir": "ss"},
                    {"t": "T4 · Day 7",       "s": "This tangerine-hued pantry borrows from the Brits",  "f": "klv-flow-flow-welcome-series-t10-Rwv4fe.png",    "f_dir": "ss"},
                    {"t": "T5 · Day 10",      "s": "A before & after signed Jake Arnold",                "f": "klv-flow-flow-welcome-series-t11-TgTVBc.png",    "f_dir": "ss"},
                    {"t": "T6 · Day 10",      "s": "Questions about consultations?",                     "f": "klv-flow-flow-welcome-series-t12-VJX7Vb.png",    "f_dir": "ss"},
                    {"t": "T7 · Day 13",      "s": "Caitlin Flemming's go-to wallpaper",                 "f": "klv-flow-flow-welcome-series-t14-Y4jugu.png",    "f_dir": "ss"},
                ],
            },
            {
                "name": "Post-Consultation",
                "entry": "Completed consultation (Added to List)",
                "canvas_ids": [],
                "ga4_pattern": None,
                "steps": [
                    {"t": "T1 · Day 1 · A", "s": "What our Experts are shopping right now", "f": "klv-flow-flow-co_post-consultation_ecom-t01-TjbnSg.png", "f_dir": "ss"},
                    {"t": "T1 · Day 1 · B", "s": "15% off our best-sellers",                "f": "klv-flow-flow-co_post-consultation_ecom-t02-SJLAsw.png", "f_dir": "ss"},
                    {"t": "T2 · Day 4 · A", "s": "The last layer your room needs",          "f": "klv-flow-flow-co_post-consultation_ecom-t03-Xf9rja.png", "f_dir": "ss"},
                    {"t": "T2 · Day 4 · B", "s": "15% off fabric and wallpaper",            "f": "klv-flow-flow-co_post-consultation_ecom-t04-UdgGBM.png", "f_dir": "ss"},
                    {"t": "T3 · Day 13",    "s": "Just for you: 15% off all month",         "f": "klv-flow-flow-co_post-consultation_ecom-t05-Su5ZfP.png", "f_dir": "ss"},
                    {"t": "T4 · Day 29",    "s": "Your 15% off ends tomorrow",              "f": "klv-flow-flow-co_post-consultation_ecom-t06-R9HdBK.png", "f_dir": "ss"},
                    {"t": "T5 · Day 32",    "s": "Quick question…",                         "f": "klv-flow-flow-co_post-consultation_ecom-t07-VX4PHP.png", "f_dir": "ss"},
                ],
            },
            {
                "name": "Browse Abandonment",
                "entry": "Viewed product page (Metric)",
                "canvas_ids": [],
                "ga4_pattern": None,
                "steps": [
                    {"t": "T1 · ~2 hr", "s": "Did we catch your eye?", "f": "klv-flow-flow-sh_abandoned-browse2-t01-Tb2443.png", "f_dir": "ss"},
                ],
            },
            {
                "name": "Cart Abandonment",
                "entry": "Added to cart, no purchase (Metric)",
                "canvas_ids": [],
                "ga4_pattern": None,
                "steps": [
                    {"t": "T1 · ~1 hr", "s": "You have great taste!",  "f": "klv-flow-flow-sh_abandoned-cart2-t01-SQvLwU.png", "f_dir": "ss"},
                    {"t": "T2 · Day 3", "s": "Remember me?",           "f": "klv-flow-flow-sh_abandoned-cart2-t02-VbjsiC.png", "f_dir": "ss"},
                ],
            },
            {
                "name": "Create Account",
                "entry": "Account created (Added to List)",
                "canvas_ids": [],
                "ga4_pattern": None,
                "steps": [
                    {"t": "T1 · Day 1", "s": "Have any questions?", "f": "klv-flow-flow-co_create-account-t01-QTWspr.png", "f_dir": "ss"},
                ],
            },
            {
                "name": "Trade Welcome (June 2026)",
                "entry": "Trade approval (Added to List)",
                "canvas_ids": [],
                "ga4_pattern": None,
                "steps": [
                    {"t": "T1 · Day 1",  "s": "Welcome to The Expert!",                            "f": "klv-flow-trade_program-welcome-june2026-t01-Tmjisd.png", "f_dir": "ss"},
                    {"t": "T2 · Day 3",  "s": "Better trade discounts are here!",                  "f": "klv-flow-trade_program-welcome-june2026-t02-SDEZuc.png", "f_dir": "ss"},
                    {"t": "T3 · Day 5",  "s": "Excited to work with you!",                         "f": "klv-flow-trade_program-welcome-june2026-t05-RW2Gwb.png", "f_dir": "ss"},
                    {"t": "T4 · Day 7",  "s": "Everything you'd travel to find, just a click away","f": "klv-flow-trade_program-welcome-june2026-t06-RiZDTy.png", "f_dir": "ss"},
                    {"t": "T5 · Day 10", "s": "Ready to declutter your inbox?",                    "f": "klv-flow-trade_program-welcome-june2026-t07-Renpya.png", "f_dir": "ss"},
                    {"t": "T6 · Day 13", "s": "We rep hundreds of brands. Let us help you source!","f": "klv-flow-trade_program-welcome-june2026-t08-VmBWQm.png", "f_dir": "ss"},
                    {"t": "T7 · Day 16", "s": "You're in good company",                            "f": "klv-flow-trade_program-welcome-june2026-t09-Wx2MJd.png", "f_dir": "ss"},
                    {"t": "T8 · Day 19", "s": "Loved by the trade. Exclusively ours.",             "f": "klv-flow-trade_program-welcome-june2026-t10-UDXDSk.png", "f_dir": "ss"},
                    {"t": "T9 · Day 22", "s": "We want to be your growth partner",                 "f": "klv-flow-trade_program-welcome-june2026-t11-XBNngF.png", "f_dir": "ss"},
                ],
            },
            {
                "name": "Trade Post-Purchase",
                "entry": "First trade order placed (Added to List)",
                "canvas_ids": [],
                "ga4_pattern": None,
                "steps": [
                    {"t": "T1 · Day 5",  "s": "What else can we help you source?",    "f": "klv-flow-flow-sr_post-purchase_trade-t01-Vhpnpq.png", "f_dir": "ss"},
                    {"t": "T2 · Day 8",  "s": "Let us showcase your work",             "f": "klv-flow-flow-sr_post-purchase_trade-t02-WsNdhg.png", "f_dir": "ss"},
                    {"t": "T3 · Day 11", "s": "Unlock up to 25% off",                  "f": "klv-flow-flow-sr_post-purchase_trade-t03-XCd4b8.png", "f_dir": "ss"},
                    {"t": "T4 · Day 17", "s": "How to get $350 back, plus more perks", "f": "klv-flow-flow-sr_post-purchase_trade-t05-UEyjbw.png", "f_dir": "ss"},
                ],
            },
        ],
    },
}


# ── Snowflake data ────────────────────────────────────────────────────────────

DB_PRIMARY = "BRAZE_BRAZEWEST_BRAZE_RAW_EVENTS_AWS_US_EAST_1_XJ24206"
DB_TIER3   = "BRAZE_BRAZEWEST_BRAZE_RAW_EVENTS_AWS_US_EAST_1_XJ24206_TIER3_ID_AND_SF"

BRAND_SNOWFLAKE = {
    "bur": {"app_group_id": "67093a1f24ebbe0065cb9c77", "db": DB_PRIMARY,
            "schema": "DATALAKE_SHARING", "ga4": "LANDING_BURROW_GA4"},
    "id":  {"app_group_id": "6666726b459b5e0059d7d687", "db": DB_TIER3,
            "schema": "DATALAKE_SHARING_TIERED", "ga4": "LANDING_INTERIORDEFINE_GA4"},
    "hav": {"app_group_id": "664223fb71bcf3005760dfc2", "db": DB_PRIMARY,
            "schema": "DATALAKE_SHARING", "ga4": "LANDING_HAVENLY_GA4"},
    "cz":  {"app_group_id": "666672a4d8965b005ac6c1bd", "db": DB_PRIMARY,
            "schema": "DATALAKE_SHARING", "ga4": "LANDING_CITIZENRY_GA4"},
    "stf": {"app_group_id": "666716b3858150005b566956", "db": DB_TIER3,
            "schema": "DATALAKE_SHARING_TIERED", "ga4": "LANDING_ST_FRANK_GA4"},
    # TI is on Klaviyo — no Braze datashare. app_group_id=None skips send/open queries.
    "ti":  {"app_group_id": None, "db": None,
            "schema": None, "ga4": "LANDING_THE_INSIDE_GA4"},
    # TE is on Klaviyo and uses Stripe/HubSpot (not GA4). No stats available.
    "te":  {"app_group_id": None, "db": None,
            "schema": None, "ga4": None},
}


def fetch_klaviyo_stats_batch(brand: str, rows: list, client) -> dict:
    """Fetch all GA4 stats for a Klaviyo brand in ONE query, distribute to rows.

    Replaces N per-row ILIKE queries with a single GROUP BY that scans the
    table once, then matches patterns in Python via fnmatch. Much faster
    because it avoids N Snowflake round-trips.
    """
    import fnmatch as _fnmatch
    cfg = BRAND_SNOWFLAKE[brand]
    ga4 = cfg["ga4"]
    campaign_data: dict = {}
    if ga4:
        try:
            results = client.execute_query(f"""
                SELECT UPPER(SESSIONCAMPAIGNNAME) AS n,
                       SUM(SESSIONS)      AS s,
                       SUM(TOTALREVENUE)  AS r
                FROM AIRBYTE_DATABASE.{ga4}.TRAFFIC_SESSION_PERFORMANCE_DAILY
                WHERE UPPER(SESSIONPRIMARYCHANNELGROUP) IN ('EMAIL', 'SMS')
                  AND DATE >= TO_CHAR(DATEADD('week', -12, CURRENT_DATE()), 'YYYYMMDD')
                GROUP BY 1
            """)
            for row in results:
                campaign_data[row.get("N") or ""] = (row.get("S") or 0, row.get("R") or 0)
        except Exception as e:
            print(f"  ⚠ batch GA4 query failed for {brand}: {e}")

    out = {}
    for row in rows:
        is_sms = all(s.get("channel") == "sms" for s in row["steps"])
        raw_patterns = row.get("ga4_patterns") or ([row.get("ga4_pattern")] if row.get("ga4_pattern") else [])
        sess, rev = 0, 0.0
        for raw_p in raw_patterns:
            fnpatt = raw_p.upper().replace("%", "*").replace("_", "?")
            for name, (s, r) in campaign_data.items():
                if _fnmatch.fnmatchcase(name, fnpatt):
                    sess += s; rev += r
        out[row["name"]] = {
            "sess_wk": round(sess / 12) if sess else None,
            "rev_wk":  round(rev / 12) if rev else None,
            "is_sms":  is_sms,
            "klaviyo": True,
        }
    return out


def fetch_stats(brand: str, row: dict, client) -> dict:
    """Query Snowflake for 12-week rolling averages for one canvas row."""
    cfg = BRAND_SNOWFLAKE[brand]

    # Klaviyo brands: use fetch_klaviyo_stats_batch() instead (batch = 1 query).
    # This single-row path is kept for completeness but normally not reached.
    if cfg["app_group_id"] is None:
        batch = fetch_klaviyo_stats_batch(brand, [row], client)
        return batch.get(row["name"], {"klaviyo": True})

    ids  = row["canvas_ids"]
    ids_sql = ", ".join(f"'{i}'" for i in ids)
    db, schema, app = cfg["db"], cfg["schema"], cfg["app_group_id"]
    is_sms = all(s.get("channel") == "sms" for s in row["steps"])
    ch = "SMS" if is_sms else "EMAIL"
    send_tbl = f"{db}.{schema}.USERS_MESSAGES_{ch}_SEND_SHARED"
    open_tbl = f"{db}.{schema}.USERS_MESSAGES_EMAIL_OPEN_SHARED"

    try:
        # Total sends + unique recipients
        r = client.execute_query(f"""
            SELECT COUNT(DISTINCT ID) AS s, COUNT(DISTINCT USER_ID) AS u
            FROM {send_tbl}
            WHERE APP_GROUP_ID='{app}' AND CANVAS_ID IN ({ids_sql})
              AND TO_TIMESTAMP(TIME) >= DATEADD('week',-12,CURRENT_TIMESTAMP())
        """)[0]
        sends, recip = r.get("S") or 0, r.get("U") or 0

        # T1 sends — use the channel of the T1 step, which may differ from the
        # overall flow channel (e.g. Shopping Prompts T1 is push, rest are email;
        # Cart Abandon T1 is SMS in a mixed email/SMS flow).
        t1_step = next(
            (s for s in row["steps"] if s.get("t", "").lstrip().startswith("T1")),
            row["steps"][0] if row["steps"] else {},
        )
        t1_ch = t1_step.get("channel", "email").lower()
        if t1_ch == "push":
            t1_tbl = f"{db}.{schema}.USERS_MESSAGES_PUSHNOTIFICATION_SEND_SHARED"
        elif t1_ch == "sms":
            t1_tbl = f"{db}.{schema}.USERS_MESSAGES_SMS_SEND_SHARED"
        else:
            t1_tbl = send_tbl

        t1_name_filter = row.get("t1_step_filter", "%_T1%")
        r2 = client.execute_query(f"""
            SELECT COUNT(DISTINCT ID) AS t
            FROM {t1_tbl}
            WHERE APP_GROUP_ID='{app}' AND CANVAS_ID IN ({ids_sql})
              AND CANVAS_STEP_NAME ILIKE '{t1_name_filter}'
              AND TO_TIMESTAMP(TIME) >= DATEADD('week',-12,CURRENT_TIMESTAMP())
        """)[0]
        t1 = r2.get("T") or 0

        opens, uor = 0, None
        if not is_sms:
            r3 = client.execute_query(f"""
                SELECT COUNT(DISTINCT USER_ID) AS o
                FROM {open_tbl}
                WHERE APP_GROUP_ID='{app}' AND CANVAS_ID IN ({ids_sql})
                  AND TO_TIMESTAMP(TIME) >= DATEADD('week',-12,CURRENT_TIMESTAMP())
            """)[0]
            opens = r3.get("O") or 0
            uor = round(opens * 100.0 / recip, 1) if recip else None

        # GA4
        sess, rev = 0, 0
        ga4_patterns = row.get("ga4_patterns") or ([row.get("ga4_pattern")] if row.get("ga4_pattern") else [])
        if ga4_patterns:
            ga4_ch = f"'{row.get('ga4_channel', 'EMAIL')}'"
            ga4_cond = " OR ".join(f"SESSIONCAMPAIGNNAME ILIKE '{p}'" for p in ga4_patterns)
            r4 = client.execute_query(f"""
                SELECT SUM(SESSIONS) AS s, SUM(TOTALREVENUE) AS r
                FROM AIRBYTE_DATABASE.{cfg['ga4']}.TRAFFIC_SESSION_PERFORMANCE_DAILY
                WHERE UPPER(SESSIONPRIMARYCHANNELGROUP)={ga4_ch}
                  AND DATE >= TO_CHAR(DATEADD('week',-12,CURRENT_DATE()),'YYYYMMDD')
                  AND ({ga4_cond})
            """)[0]
            sess = r4.get("S") or 0
            rev  = r4.get("R") or 0

        return {
            "sends_wk":  round(sends / 12),
            "t1_wk":     round(t1 / 12),
            "opens_wk":  round(opens / 12),
            "uor":       uor,
            "sess_wk":   round(sess / 12),
            "rev_wk":    round(rev / 12),
            "rev_m":     round(rev / 12 * 1000 / (sends / 12)) if sends else None,
            "is_sms":    is_sms,
        }
    except Exception as e:
        print(f"  ⚠ stats unavailable for {row['name']}: {e}")
        return {}


# ── Image helpers ─────────────────────────────────────────────────────────────

THUMB_W = 160  # px wide in the dashboard


def img_to_b64(path: Path) -> str | None:
    """Load a PNG, resize to THUMB_W, return as base64 data URI."""
    if not path.exists():
        return None
    try:
        from PIL import Image
        import io
        img = Image.open(path).convert("RGB")
        scale = THUMB_W / img.width
        new_h = min(int(img.height * scale), 400)  # cap preview height
        img = img.resize((THUMB_W, int(img.height * scale)), Image.LANCZOS)
        img = img.crop((0, 0, THUMB_W, new_h))
        buf = io.BytesIO()
        img.save(buf, format="JPEG", quality=80)
        return "data:image/jpeg;base64," + base64.b64encode(buf.getvalue()).decode()
    except Exception:
        return None


# ── HTML generation ───────────────────────────────────────────────────────────

def fmt_n(n, prefix="", suffix="", dash_zero=True):
    if n is None or (dash_zero and n == 0):
        return "—"
    return f"{prefix}{int(round(n)):,}{suffix}"


def fmt_pct(n):
    return f"{n:.1f}%" if n is not None else "—"


def stat_chip(label, value):
    return f'<span class="chip"><span class="chip-label">{label}</span><span class="chip-value">{value}</span></span>'


def render_step(step: dict) -> str:
    is_sms = step.get("channel") == "sms"
    img_src = img_to_b64(RENDERED / step["f"]) if step.get("f") else None
    timing = step["t"]
    subject = step["s"]

    if is_sms or img_src is None:
        body = step.get("body", "")
        inner = f'''
        <div class="step-thumb sms-thumb">
            <div class="step-badge sms-badge">{timing}</div>
            <div class="step-subject">{subject}</div>
            <div class="sms-body">{body}</div>
        </div>'''
    else:
        inner = f'''
        <div class="step-thumb">
            <div class="step-badge">{timing}</div>
            <div class="step-subject">{subject}</div>
            <img src="{img_src}" alt="{subject}" loading="lazy">
        </div>'''
    return inner


def render_row(row: dict, stats: dict, brand_color: str) -> str:
    steps_html = "\n".join(render_step(s) for s in row["steps"])
    n_email = sum(1 for s in row["steps"] if s.get("channel") != "sms" and s.get("f"))
    n_sms   = sum(1 for s in row["steps"] if s.get("channel") == "sms")
    step_label = " + ".join(filter(None, [
        f"{n_email} email{'s' if n_email != 1 else ''}" if n_email else None,
        f"{n_sms} SMS" if n_sms else None,
    ]))

    # Stats row
    if stats:
        is_klaviyo = stats.get("klaviyo", False)
        chips = []
        if not is_klaviyo:
            chips += [stat_chip("T1/wk", fmt_n(stats.get("t1_wk"))),
                      stat_chip("Sends/wk", fmt_n(stats.get("sends_wk")))]
            if not stats.get("is_sms"):
                chips += [stat_chip("Uniq Opens/wk", fmt_n(stats.get("opens_wk"))),
                          stat_chip("UOR", fmt_pct(stats.get("uor")))]
        chips += [stat_chip("Sessions/wk", fmt_n(stats.get("sess_wk"))),
                  stat_chip("Rev/wk", fmt_n(stats.get("rev_wk"), "$")),]
        if not is_klaviyo and not stats.get("is_sms"):
            chips.append(stat_chip("Rev/M", fmt_n(stats.get("rev_m"), "$")))
        stats_html = '<div class="stats-row">' + "".join(chips) + '</div>'
    else:
        stats_html = '<div class="stats-row"><span class="chip"><span class="chip-value">Stats unavailable</span></span></div>'

    return f'''
<div class="canvas-row">
  <div class="row-header">
    <div class="row-title">{row["name"]}</div>
    <div class="row-meta">
      <span class="entry-trigger">↳ {row["entry"]}</span>
      <span class="step-count">{step_label}</span>
    </div>
    {stats_html}
  </div>
  <div class="steps-scroll">
    <div class="steps-inner">{steps_html}</div>
  </div>
</div>'''


def render_brand_section(brand: str, cfg: dict, stats_map: dict) -> str:
    rows_html = "\n".join(
        render_row(row, stats_map.get(row["name"], {}), cfg["color"])
        for row in cfg["rows"]
    )
    return f'''
<section class="brand-section">
  <div class="brand-header" style="background:{cfg["color"]}">
    <h2>{cfg["label"]}</h2>
  </div>
  {rows_html}
</section>'''


CSS = """
* { box-sizing: border-box; margin: 0; padding: 0; }
body { font-family: -apple-system, BlinkMacSystemFont, 'Segoe UI', sans-serif;
       background: #f5f5f5; color: #1a1a1a; font-size: 13px; }
header { background: #1a1a1a; color: #fff; padding: 20px 32px;
         display: flex; align-items: baseline; gap: 16px; }
header h1 { font-size: 20px; font-weight: 600; }
header .subtitle { font-size: 12px; color: #888; }
.brand-section { margin: 24px 24px 0; }
.brand-header { color: #fff; padding: 12px 20px; border-radius: 8px 8px 0 0; }
.brand-header h2 { font-size: 15px; font-weight: 600; letter-spacing: 0.3px; }
.canvas-row { background: #fff; border: 1px solid #e5e5e5; border-top: none;
              padding: 16px 20px; display: flex; gap: 20px; align-items: flex-start; }
.canvas-row:last-child { border-radius: 0 0 8px 8px; margin-bottom: 24px; }
.row-header { min-width: 220px; max-width: 220px; flex-shrink: 0; }
.row-title { font-weight: 600; font-size: 13px; margin-bottom: 4px; }
.row-meta { margin-bottom: 10px; }
.entry-trigger { display: block; color: #666; font-size: 11px; margin-bottom: 2px; }
.step-count { font-size: 11px; color: #999; }
.stats-row { display: flex; flex-wrap: wrap; gap: 6px; margin-top: 8px; }
.chip { display: inline-flex; flex-direction: column; background: #f8f8f8;
        border: 1px solid #e8e8e8; border-radius: 6px; padding: 4px 8px;
        min-width: 64px; }
.chip-label { font-size: 9px; color: #999; text-transform: uppercase;
              letter-spacing: 0.4px; line-height: 1.2; }
.chip-value { font-size: 12px; font-weight: 600; color: #1a1a1a; line-height: 1.4; }
.steps-scroll { flex: 1; overflow-x: auto; }
.steps-inner { display: flex; gap: 10px; min-width: min-content; padding-bottom: 4px; }
.step-thumb { width: 160px; flex-shrink: 0; border-radius: 6px; overflow: hidden;
              border: 1px solid #e5e5e5; background: #fafafa; position: relative; }
.step-badge { font-size: 10px; font-weight: 600; color: #fff;
              background: #1a1a1a; padding: 4px 8px; line-height: 1.3; }
.step-thumb img { width: 160px; display: block; height: auto; max-height: 400px;
                  object-fit: cover; object-position: top; }
.step-subject { font-size: 10px; padding: 6px 8px; color: #555;
                border-bottom: 1px solid #e5e5e5; background: #fff;
                line-height: 1.4; }
.sms-thumb { background: #ede9fb; border-color: #c9c0f0; }
.sms-badge { background: #6b4fcf; }
.sms-subject { font-size: 10px; font-weight: 600; padding: 6px 8px 4px;
               color: #4a3a80; border-bottom: 1px solid #c9c0f0; }
.sms-body { font-size: 10px; padding: 6px 8px 10px; color: #4a3a80;
            line-height: 1.5; }
"""

HTML_TEMPLATE = """<!DOCTYPE html>
<html lang="en">
<head>
<meta charset="UTF-8">
<meta name="viewport" content="width=device-width, initial-scale=1">
<title>Lifecycle Canvas Map</title>
<style>{css}</style>
</head>
<body>
<header>
  <h1>Lifecycle Canvas Map</h1>
  <span class="subtitle">Rolling 12-week weekly averages &nbsp;·&nbsp; Generated {date}</span>
</header>
{body}
</body>
</html>"""


# ── Main ──────────────────────────────────────────────────────────────────────

def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--brand", choices=["bur", "id", "hav", "cz", "stf", "ti", "all"], default="all")
    parser.add_argument("--no-stats", action="store_true",
                        help="Skip Snowflake — render creative only (fast)")
    args = parser.parse_args()

    brands = ["bur", "id", "hav", "cz", "stf", "ti"] if args.brand == "all" else [args.brand]
    today = datetime.date.today().strftime("%-d %b %Y")

    # Fetch stats from Snowflake
    stats_map: dict[str, dict[str, dict]] = {b: {} for b in brands}

    if not args.no_stats:
        try:
            import sys
            sys.path.insert(0, str(Path(__file__).parent))
            from snowflake_client import get_snowflake_client

            for brand in brands:
                cfg_sf = BRAND_SNOWFLAKE[brand]
                # Klaviyo brands have no Braze datashare — use AIRBYTE_DATABASE for GA4
                sf_db = cfg_sf["db"] or "AIRBYTE_DATABASE"
                sf_schema = cfg_sf["schema"] or (cfg_sf.get("ga4") or "PUBLIC")
                client = get_snowflake_client(schema=sf_schema, database=sf_db)
                print(f"Fetching stats for {brand.upper()}...")
                cfg_sf = BRAND_SNOWFLAKE[brand]
                if cfg_sf["app_group_id"] is None:
                    # Klaviyo brand — one batch query instead of N per-row queries
                    stats_map[brand] = fetch_klaviyo_stats_batch(
                        brand, CANVASES[brand]["rows"], client
                    )
                else:
                    for row in CANVASES[brand]["rows"]:
                        print(f"  {row['name']}...")
                        stats_map[brand][row["name"]] = fetch_stats(brand, row, client)
        except Exception as e:
            print(f"⚠ Snowflake unavailable — rendering creative only: {e}")

    # Build HTML
    sections = "\n".join(
        render_brand_section(b, CANVASES[b], stats_map[b])
        for b in brands
    )

    html = HTML_TEMPLATE.format(css=CSS, date=today, body=sections)

    OUT_FILE.parent.mkdir(exist_ok=True)
    OUT_FILE.write_text(html, encoding="utf-8")
    size_kb = OUT_FILE.stat().st_size // 1024
    print(f"\n✓ {OUT_FILE}  ({size_kb} KB)")


if __name__ == "__main__":
    main()
