"""
Build the TE (The Expert) Lifecycle Canvas Map on FigJam.

Board URL: https://www.figma.com/board/dtgM4oqjnYueUniBESjCHJ/
Page: 0-1 (root page)

Usage:
  python scripts/build_te_figjam.py --upload-only   # crop + upload images, print IH dict
  python scripts/build_te_figjam.py --dry-run        # print the plugin script without running
  python scripts/build_te_figjam.py                  # full build (requires Figma MCP auth)
"""
import argparse, json, os, sys, tempfile, glob
from pathlib import Path
from PIL import Image

BASE       = Path(__file__).parent.parent
SS_DIR     = BASE / "campaigns" / "screenshots"
FILE_KEY   = "dtgM4oqjnYueUniBESjCHJ"
PAGE_ID    = "0:1"   # node-id from URL: 0-1 → "0:1"
CARD_W     = 260

# ─── FH values (measured from autocropped screenshots at 260px width) ─────────
FH = {
    # Welcome Series
    "RexA77": 2390, "VmM9pi": 1987, "U7K4a4": 3247, "YeYBsf": 2372,
    "Yamm6R": 4169, "YjHZ4R": 3361, "VcTHRZ": 256,  "SGJpcT": 3247,
    "S3GkrK": 4147, "Rwv4fe": 3361, "TgTVBc": 2369, "VJX7Vb": 1987,
    "QZBWMT": 1664, "Y4jugu": 1664,
    # Trade Welcome June 2026
    "Tmjisd": 1566, "SDEZuc": 1047, "RW2Gwb": 276,  "RiZDTy": 1870,
    "Renpya": 1645, "VmBWQm": 231,  "Wx2MJd": 1902, "UDXDSk": 2363,
    "XBNngF": 1420,
    # Trade Welcome July 2025
    "W3GLND": 1566, "RKcGPE": 1047, "REzsug": 1870, "S3GJ4H": 1645,
    "Xb6BxY": 1902, "RHbGF9": 2363, "XCR9tP": 1420, "WDijgA": 276,
    "W3ugDD": 231,
    # Trade Post-Purchase
    "Vhpnpq": 1903, "WsNdhg": 950,  "XCd4b8": 2263, "UEyjbw": 1448,
    # Browse Abandonment
    "Tb2443": 920,
    # Create Account
    "QTWspr": 125,  "T9nd5j": 150,  "YwDRAL": 150,
    # Cart Abandonment
    "SQvLwU": 882,  "VbjsiC": 915,
    # Post-Consultation
    "TjbnSg": 2844, "SJLAsw": 2849, "Xf9rja": 2448, "UdgGBM": 2001,
    "Su5ZfP": 2245, "R9HdBK": 1244, "VX4PHP": 790,
}
# Cap very tall cards at 2400px to keep board manageable
FH = {k: min(v, 2400) for k, v in FH.items()}


# ─── Screenshot slug map: msg_id → screenshot filename stem ──────────────────
SLUG = {
    # Welcome Series
    "RexA77": "klv-flow-flow-welcome-series-t01-RexA77",
    "VmM9pi": "klv-flow-flow-welcome-series-t02-VmM9pi",
    "U7K4a4": "klv-flow-flow-welcome-series-t03-U7K4a4",
    "YeYBsf": "klv-flow-flow-welcome-series-t04-YeYBsf",
    "Yamm6R": "klv-flow-flow-welcome-series-t05-Yamm6R",
    "YjHZ4R": "klv-flow-flow-welcome-series-t06-YjHZ4R",
    "VcTHRZ": "klv-flow-flow-welcome-series-t07-VcTHRZ",
    "SGJpcT": "klv-flow-flow-welcome-series-t08-SGJpcT",
    "S3GkrK": "klv-flow-flow-welcome-series-t09-S3GkrK",
    "Rwv4fe": "klv-flow-flow-welcome-series-t10-Rwv4fe",
    "TgTVBc": "klv-flow-flow-welcome-series-t11-TgTVBc",
    "VJX7Vb": "klv-flow-flow-welcome-series-t12-VJX7Vb",
    "QZBWMT": "klv-flow-flow-welcome-series-t13-QZBWMT",
    "Y4jugu": "klv-flow-flow-welcome-series-t14-Y4jugu",
    # Trade Welcome June 2026 (only Variant A for Day 3 A/B: SDEZuc)
    "Tmjisd": "klv-flow-trade_program-welcome-june2026-t01-Tmjisd",
    "SDEZuc": "klv-flow-trade_program-welcome-june2026-t02-SDEZuc",
    "RW2Gwb": "klv-flow-trade_program-welcome-june2026-t05-RW2Gwb",
    "RiZDTy": "klv-flow-trade_program-welcome-june2026-t06-RiZDTy",
    "Renpya": "klv-flow-trade_program-welcome-june2026-t07-Renpya",
    "VmBWQm": "klv-flow-trade_program-welcome-june2026-t08-VmBWQm",
    "Wx2MJd": "klv-flow-trade_program-welcome-june2026-t09-Wx2MJd",
    "UDXDSk": "klv-flow-trade_program-welcome-june2026-t10-UDXDSk",
    "XBNngF": "klv-flow-trade_program-welcome-june2026-t11-XBNngF",
    # Trade Welcome July 2025
    "W3GLND": "klv-flow-trade_program-welcome-july2025-t01-W3GLND",
    "RKcGPE": "klv-flow-trade_program-welcome-july2025-t02-RKcGPE",
    "REzsug": "klv-flow-trade_program-welcome-july2025-t03-REzsug",
    "S3GJ4H": "klv-flow-trade_program-welcome-july2025-t04-S3GJ4H",
    "Xb6BxY": "klv-flow-trade_program-welcome-july2025-t05-Xb6BxY",
    "RHbGF9": "klv-flow-trade_program-welcome-july2025-t06-RHbGF9",
    "XCR9tP": "klv-flow-trade_program-welcome-july2025-t07-XCR9tP",
    "WDijgA": "klv-flow-trade_program-welcome-july2025-t08-WDijgA",
    "W3ugDD": "klv-flow-trade_program-welcome-july2025-t09-W3ugDD",
    # Trade Post-Purchase
    "Vhpnpq": "klv-flow-flow-sr_post-purchase_trade-t01-Vhpnpq",
    "WsNdhg": "klv-flow-flow-sr_post-purchase_trade-t02-WsNdhg",
    "XCd4b8": "klv-flow-flow-sr_post-purchase_trade-t03-XCd4b8",
    "UEyjbw": "klv-flow-flow-sr_post-purchase_trade-t05-UEyjbw",
    # Browse Abandonment
    "Tb2443": "klv-flow-flow-sh_abandoned-browse2-t01-Tb2443",
    # Create Account
    "QTWspr": "klv-flow-flow-co_create-account-t01-QTWspr",
    "T9nd5j": "klv-flow-flow-co_create-account-t02-T9nd5j",
    "YwDRAL": "klv-flow-flow-co_create-account-t03-YwDRAL",
    # Cart Abandonment
    "SQvLwU": "klv-flow-flow-sh_abandoned-cart2-t01-SQvLwU",
    "VbjsiC": "klv-flow-flow-sh_abandoned-cart2-t02-VbjsiC",
    # Post-Consultation
    "TjbnSg": "klv-flow-flow-co_post-consultation_ecom-t01-TjbnSg",
    "SJLAsw": "klv-flow-flow-co_post-consultation_ecom-t02-SJLAsw",
    "Xf9rja": "klv-flow-flow-co_post-consultation_ecom-t03-Xf9rja",
    "UdgGBM": "klv-flow-flow-co_post-consultation_ecom-t04-UdgGBM",
    "Su5ZfP": "klv-flow-flow-co_post-consultation_ecom-t05-Su5ZfP",
    "R9HdBK": "klv-flow-flow-co_post-consultation_ecom-t06-R9HdBK",
    "VX4PHP": "klv-flow-flow-co_post-consultation_ecom-t07-VX4PHP",
}


# ─── Flow definitions ──────────────────────────────────────────────────────────
# Each row: name, trigger, steps[{t, subj, ph, id}]
FLOWS = [
    {
        "name": "Welcome Series",
        "trigger": "New subscriber (Added to List)",
        "steps": [
            {"t": "T1 · Immediately", "subj": "Welcome to The Expert",                             "ph": "Designing your dream home starts here.",          "id": "RexA77"},
            {"t": "T2 · Day 1 · A",   "subj": "Questions about consultations?",                    "ph": "We have the answers.",                           "id": "VmM9pi"},
            {"t": "T2 · Day 1 · B",   "subj": "Our Experts’ shopping secrets, revealed.",     "ph": "Plus, discover our best-sellers.",               "id": "U7K4a4"},
            {"t": "T3 · Day 4",        "subj": "A before & after signed Jake Arnold",               "ph": "Psst: it was all done virtually!",               "id": "YeYBsf"},
            {"t": "T4 · Day 7",        "subj": "Bring Miles Redd’s iconic style home",         "ph": "3 Expert Showrooms you need to see.",            "id": "Yamm6R"},
            {"t": "T5 · Day 10",       "subj": "This tangerine-hued pantry borrows from the Brits", "ph": "Plus, 14 trending paint colors designers love.", "id": "YjHZ4R"},
            {"t": "T6 · Day 11",       "subj": "Join The Expert Trade Program",                     "ph": "",                                               "id": "VcTHRZ"},
            {"t": "T7 · Day 13 · A",   "subj": "Our Experts’ shopping secrets, revealed.",     "ph": "Plus, discover our best-sellers.",               "id": "SGJpcT"},
            {"t": "T7 · Day 13 · B",   "subj": "Bring Miles Redd’s iconic style home",         "ph": "3 Expert Showrooms you need to see.",            "id": "S3GkrK"},
            {"t": "T8 · Day 18",       "subj": "This tangerine-hued pantry borrows from the Brits", "ph": "Plus, 14 trending paint colors designers love.", "id": "Rwv4fe"},
            {"t": "T9 · Day 21 · A",   "subj": "A before & after signed Jake Arnold",               "ph": "Psst: it was all done virtually!",               "id": "TgTVBc"},
            {"t": "T9 · Day 21 · B",   "subj": "Questions about consultations?",                    "ph": "We have the answers.",                           "id": "VJX7Vb"},
            {"t": "T10 · Day 30 · A",  "subj": "Caitlin Flemming’s go-to wallpaper",           "ph": "6 pieces our Experts can’t get enough of.", "id": "QZBWMT"},
            {"t": "T10 · Day 30 · B",  "subj": "Caitlin Flemming’s go-to wallpaper",           "ph": "6 pieces our Experts can’t get enough of.", "id": "Y4jugu"},
        ],
    },
    {
        "name": "Post-Consultation",
        "trigger": "Completed consultation (Added to List)",
        "steps": [
            {"t": "T1 · Day 1 · A",  "subj": "What our Experts are shopping right now", "ph": "15% off for a limited time.",                        "id": "TjbnSg"},
            {"t": "T1 · Day 1 · B",  "subj": "15% off our best-sellers",                "ph": "Exclusive to you, only for a limited time.",          "id": "SJLAsw"},
            {"t": "T2 · Day 4 · A",  "subj": "The last layer your room needs",           "ph": "Under $300 finds to finish off your space in style.", "id": "Xf9rja"},
            {"t": "T2 · Day 4 · B",  "subj": "15% off fabric and wallpaper",             "ph": "Plus, a step-by-step guide.",                        "id": "UdgGBM"},
            {"t": "T3 · Day 13",     "subj": "Just for you: 15% off all month",           "ph": "Now the fun part starts…",                      "id": "Su5ZfP"},
            {"t": "T4 · Day 29",     "subj": "Your 15% off ends tomorrow",                "ph": "Don’t miss your chance to save big.",            "id": "R9HdBK"},
            {"t": "T5 · Day 32",     "subj": "Quick question…",                      "ph": "We’d love your feedback!",                       "id": "VX4PHP"},
        ],
    },
    {
        "name": "Browse Abandonment",
        "trigger": "Viewed product page (Metric)",
        "steps": [
            {"t": "T1 · ~2 hr", "subj": "Did we catch your eye?", "ph": "We can help make it official.", "id": "Tb2443"},
        ],
    },
    {
        "name": "Cart Abandonment",
        "trigger": "Added to cart, no purchase (Metric)",
        "steps": [
            {"t": "T1 · ~1 hr", "subj": "You have great taste!", "ph": "We saved this for you…",  "id": "SQvLwU"},
            {"t": "T2 · Day 3",  "subj": "Remember me?",          "ph": "Where’d you go?",        "id": "VbjsiC"},
        ],
    },
    {
        "name": "Create Account",
        "trigger": "Account created (Added to List)",
        "steps": [
            {"t": "T1 · Day 1 · A", "subj": "Have any questions?",         "ph": "", "id": "QTWspr"},
            {"t": "T1 · Day 1 · B", "subj": "Can I answer any questions?", "ph": "", "id": "T9nd5j"},
            {"t": "T1 · Day 1 · C", "subj": "Can I answer any questions?", "ph": "", "id": "YwDRAL"},
        ],
    },
    {
        "name": "Trade Welcome (June 2026)",
        "trigger": "Trade approval (Added to List)",
        "steps": [
            {"t": "T1 · Day 1",  "subj": "Welcome to The Expert!",                          "ph": "Shop faster. Save more. Stress Less.",           "id": "Tmjisd"},
            {"t": "T2 · Day 3",  "subj": "Better trade discounts are here!",                 "ph": "200+ brands. One unbeatable promise.",           "id": "SDEZuc"},
            {"t": "T3 · Day 5",  "subj": "Excited to work with you!",                        "ph": "",                                               "id": "RW2Gwb"},
            {"t": "T4 · Day 7",  "subj": "Everything you’d travel to find, just a click away", "ph": "A curated world of design at your fingertips.", "id": "RiZDTy"},
            {"t": "T5 · Day 10", "subj": "Ready to declutter your inbox?",                   "ph": "100s of brands, 1 contact.",                    "id": "Renpya"},
            {"t": "T6 · Day 13", "subj": "We rep hundreds of brands. Let us help you source!", "ph": "",                                             "id": "VmBWQm"},
            {"t": "T7 · Day 16", "subj": "You’re in good company",                       "ph": "Join designers who've found their sourcing home.", "id": "Wx2MJd"},
            {"t": "T8 · Day 19", "subj": "Loved by the trade. Exclusively ours.",             "ph": "Stop giving your clients déjà vu…", "id": "UDXDSk"},
            {"t": "T9 · Day 22", "subj": "We want to be your growth partner",                 "ph": "Think of us as an extension of your team.",     "id": "XBNngF"},
        ],
    },
    {
        "name": "Trade Welcome (July 2025)",
        "trigger": "Trade approval (Added to List) — legacy",
        "steps": [
            {"t": "T1 · Day 1",      "subj": "Welcome to The Expert!",                          "ph": "Shop faster. Save more. Stress Less.",           "id": "W3GLND"},
            {"t": "T2 · Day 3",      "subj": "Better trade discounts are here!",                 "ph": "200+ brands. One unbeatable promise.",           "id": "RKcGPE"},
            {"t": "T3 · Day 5",      "subj": "Everything you’d travel to find, just a click away", "ph": "A curated world of design at your fingertips.", "id": "REzsug"},
            {"t": "T4 · Day 8",      "subj": "Ready to declutter your inbox?",                   "ph": "100s of brands, 1 contact.",                    "id": "S3GJ4H"},
            {"t": "T5 · Day 11",     "subj": "You’re in good company",                       "ph": "Join designers who've found their sourcing home.", "id": "Xb6BxY"},
            {"t": "T6 · Day 14",     "subj": "Loved by the trade. Exclusively ours.",             "ph": "Stop giving your clients déjà vu…", "id": "RHbGF9"},
            {"t": "T7 · Day 17 · A", "subj": "We want to be your growth partner",                 "ph": "Think of us as an extension of your team.",     "id": "XCR9tP"},
            {"t": "T7 · Day 17 · B", "subj": "Excited to work with you!",                        "ph": "",                                               "id": "WDijgA"},
            {"t": "T7 · Day 17 · C", "subj": "We rep hundreds of brands. Let us help you source!", "ph": "",                                             "id": "W3ugDD"},
        ],
    },
    {
        "name": "Trade Post-Purchase",
        "trigger": "First trade order placed (Added to List)",
        "steps": [
            {"t": "T1 · Day 5",  "subj": "What else can we help you source?", "ph": "Your first order is just the beginning…",   "id": "Vhpnpq"},
            {"t": "T2 · Day 8",  "subj": "Let us showcase your work",          "ph": "Enjoy perks from your Expert community.",       "id": "WsNdhg"},
            {"t": "T3 · Day 11", "subj": "Unlock up to 25% off",               "ph": "Deeper discounts, only for trade members.",     "id": "XCd4b8"},
            {"t": "T4 · Day 17", "subj": "How to get $350 back, plus more perks", "ph": "Your road to gold starts here…",         "id": "UEyjbw"},
        ],
    },
]


def autocrop(path, pad=2):
    img = Image.open(path).convert("RGBA")
    bg = img.getpixel((0, 0))
    pix = img.load()
    w, h = img.size
    top    = next((y for y in range(h)         for x in range(w) if pix[x, y][:3] != bg[:3]), 0)
    bottom = next((y for y in range(h-1,-1,-1) for x in range(w) if pix[x, y][:3] != bg[:3]), h)
    left   = next((x for x in range(w)         for y in range(h) if pix[x, y][:3] != bg[:3]), 0)
    right  = next((x for x in range(w-1,-1,-1) for y in range(h) if pix[x, y][:3] != bg[:3]), w)
    return img.crop((max(0,left-pad), max(0,top-pad), min(w,right+pad), min(h,bottom+pad)))


def get_all_msg_ids():
    ids = []
    for flow in FLOWS:
        for step in flow["steps"]:
            ids.append(step["id"])
    return ids


def prepare_cropped_images(tmpdir):
    """Autocrop all screenshots and save to tmpdir. Returns {msg_id: path}."""
    out = {}
    for msg_id in get_all_msg_ids():
        slug = SLUG.get(msg_id)
        if not slug:
            print(f"  WARNING: no SLUG for {msg_id}")
            continue
        src = SS_DIR / f"{slug}.png"
        if not src.exists():
            print(f"  WARNING: screenshot missing: {src}")
            continue
        dst = Path(tmpdir) / f"{msg_id}.png"
        cropped = autocrop(src)
        cropped.save(str(dst))
        out[msg_id] = str(dst)
    return out


def generate_plugin_script(IH: dict) -> str:
    """Generate the FigJam plugin JS to build the board."""
    fh_json  = json.dumps(FH)
    ih_json  = json.dumps(IH)
    flows_json = json.dumps(FLOWS, ensure_ascii=False)

    return f"""
// TE Lifecycle Canvas Map — auto-generated by build_te_figjam.py
(async () => {{
await figma.loadFontAsync({{family:"Inter",style:"Regular"}});
await figma.loadFontAsync({{family:"Inter",style:"Semi Bold"}});

const page = figma.currentPage;
for (const n of [...page.children]) n.remove();

const FH = {fh_json};
const IH = {ih_json};
const FLOWS = {flows_json};

const SX=100, LW=140, SW=260, SG=40, LH=120, RG=120;
const DARK  = {{r:0.11,g:0.13,b:0.17}};
const GOLD  = {{r:0.98,g:0.75,b:0.27}};
const WHITE = {{r:1,  g:1,  b:1  }};
const GREY  = {{r:0.6,g:0.6,b:0.6}};
const PGREY = {{r:0.93,g:0.93,b:0.93}};
const BLACK = {{r:0.05,g:0.05,b:0.05}};

function mkR(x,y,w,h,color){{
  const r=figma.createRectangle();r.x=x;r.y=y;r.resize(w,h);
  r.fills=[{{type:'SOLID',color}}];page.appendChild(r);return r;
}}
function mkT(x,y,txt,sz,style,color,maxW){{
  const t=figma.createText();t.fontName={{family:"Inter",style}};
  t.characters=String(txt);t.fontSize=sz;t.fills=[{{type:'SOLID',color}}];
  if(maxW){{t.textAutoResize='HEIGHT';t.resize(maxW,50);}}
  t.x=x;t.y=y;page.appendChild(t);return t;
}}

function buildRow(rowY, flow){{
  const maxFH = Math.max(...flow.steps.map(s => FH[s.id] || 400));
  mkR(SX, rowY-44, 8, 44+LH+maxFH, DARK);
  mkT(SX+20, rowY-40, flow.name,    14, 'Semi Bold', BLACK, 600);
  mkT(SX+20, rowY-22, flow.trigger, 10, 'Regular',   GREY,  600);
  for (let i=0; i<flow.steps.length; i++){{
    const s=flow.steps[i], sx=SX+LW+i*(SW+SG), fh=FH[s.id]||400;
    mkR(sx, rowY,    SW, LH, DARK);
    mkT(sx+10, rowY+ 8, s.t,    11, 'Semi Bold', GOLD,  SW-20);
    mkT(sx+10, rowY+26, s.subj, 10, 'Semi Bold', WHITE, SW-20);
    if(s.ph) mkT(sx+10, rowY+58, s.ph, 9, 'Regular', GREY, SW-20);
    const fr = mkR(sx, rowY+LH, SW, fh, PGREY);
    if(IH[s.id]) fr.fills=[{{type:'IMAGE',scaleMode:'FIT',imageHash:IH[s.id]}}];
  }}
  return rowY + LH + maxFH + RG;
}}

mkT(SX, 20, 'The Expert — Lifecycle Canvas Map', 20, 'Semi Bold', DARK);

let rowY = 100;
for (const flow of FLOWS) {{
  rowY = buildRow(rowY, flow);
}}
figma.notify('TE Lifecycle Canvas Map built! ' + FLOWS.length + ' flows.');
}})();
"""


if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("--dry-run",     action="store_true", help="Print plugin script only")
    parser.add_argument("--upload-only", action="store_true", help="Crop + print image paths (no Figma calls)")
    args = parser.parse_args()

    if args.dry_run:
        IH = {mid: "PLACEHOLDER_HASH" for mid in get_all_msg_ids()}
        print(generate_plugin_script(IH))
        sys.exit(0)

    if args.upload_only:
        tmpdir = tempfile.mkdtemp()
        paths = prepare_cropped_images(tmpdir)
        print(f"\nCropped {len(paths)} images to: {tmpdir}")
        for mid, p in paths.items():
            print(f"  {mid}: {p}")
        print("\nPass these paths to mcp__figma__upload_images to get IH dict.")
        sys.exit(0)

    print("Run with --dry-run or --upload-only. Full build requires Figma MCP from Claude.")
    sys.exit(1)
