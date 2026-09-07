// TE Lifecycle Canvas Map — Figma Development Plugin
// Fetches autocropped email screenshots from the local server (python serve_te_screenshots.py)
// and builds all flow rows on the current FigJam page.
//
// Before running: start the screenshot server:
//   python scripts/serve_te_screenshots.py
//   (serves on http://localhost:8899)

const SERVER = "http://localhost:8899";

// ─── Display heights (cropped at 260px width, capped at 2400) ─────────────────
const FH = {
  // Welcome Series
  "RexA77": 2390, "VmM9pi": 1987, "U7K4a4": 2400, "YeYBsf": 2372,
  "Yamm6R": 2400, "YjHZ4R": 2400, "VcTHRZ": 256,  "SGJpcT": 2400,
  "S3GkrK": 2400, "Rwv4fe": 2400, "TgTVBc": 2369, "VJX7Vb": 1987,
  "QZBWMT": 1664, "Y4jugu": 1664,
  // Trade Welcome June 2026
  "Tmjisd": 1566, "SDEZuc": 1047, "RW2Gwb": 276,  "RiZDTy": 1870,
  "Renpya": 1645, "VmBWQm": 231,  "Wx2MJd": 1902, "UDXDSk": 2363,
  "XBNngF": 1420,
  // Trade Welcome July 2025
  "W3GLND": 1566, "RKcGPE": 1047, "REzsug": 1870, "S3GJ4H": 1645,
  "Xb6BxY": 1902, "RHbGF9": 2363, "XCR9tP": 1420, "WDijgA": 276,
  "W3ugDD": 231,
  // Trade Post-Purchase
  "Vhpnpq": 1903, "WsNdhg": 950,  "XCd4b8": 2263, "UEyjbw": 1448,
  // Browse Abandonment
  "Tb2443": 920,
  // Create Account
  "QTWspr": 125,  "T9nd5j": 150,  "YwDRAL": 150,
  // Cart Abandonment
  "SQvLwU": 882,  "VbjsiC": 915,
  // Post-Consultation
  "TjbnSg": 2400, "SJLAsw": 2400, "Xf9rja": 2400, "UdgGBM": 2001,
  "Su5ZfP": 2245, "R9HdBK": 1244, "VX4PHP": 790,
};

// ─── Flow definitions ──────────────────────────────────────────────────────────
const FLOWS = [
  {
    name: "Welcome Series",
    trigger: "New subscriber (Added to List)",
    steps: [
      {t:"T1 · Immediately",  subj:"Welcome to The Expert",                              ph:"Designing your dream home starts here.",           id:"RexA77"},
      {t:"T2 · Day 1 · A",    subj:"Questions about consultations?",                     ph:"We have the answers.",                            id:"VmM9pi"},
      {t:"T2 · Day 1 · B",    subj:"Our Experts' shopping secrets, revealed.",           ph:"Plus, discover our best-sellers.",                id:"U7K4a4"},
      {t:"T3 · Day 4",        subj:"A before & after signed Jake Arnold",                ph:"Psst: it was all done virtually!",                id:"YeYBsf"},
      {t:"T4 · Day 7",        subj:"Bring Miles Redd's iconic style home",               ph:"3 Expert Showrooms you need to see.",             id:"Yamm6R"},
      {t:"T5 · Day 10",       subj:"This tangerine-hued pantry borrows from the Brits",  ph:"Plus, 14 trending paint colors designers love.",  id:"YjHZ4R"},
      {t:"T6 · Day 11",       subj:"Join The Expert Trade Program",                      ph:"",                                                id:"VcTHRZ"},
      {t:"T7 · Day 13 · A",   subj:"Our Experts' shopping secrets, revealed.",           ph:"Plus, discover our best-sellers.",                id:"SGJpcT"},
      {t:"T7 · Day 13 · B",   subj:"Bring Miles Redd's iconic style home",               ph:"3 Expert Showrooms you need to see.",             id:"S3GkrK"},
      {t:"T8 · Day 18",       subj:"This tangerine-hued pantry borrows from the Brits",  ph:"Plus, 14 trending paint colors designers love.",  id:"Rwv4fe"},
      {t:"T9 · Day 21 · A",   subj:"A before & after signed Jake Arnold",                ph:"Psst: it was all done virtually!",                id:"TgTVBc"},
      {t:"T9 · Day 21 · B",   subj:"Questions about consultations?",                     ph:"We have the answers.",                            id:"VJX7Vb"},
      {t:"T10 · Day 30 · A",  subj:"Caitlin Flemming's go-to wallpaper",                 ph:"6 pieces our Experts can't get enough of.",       id:"QZBWMT"},
      {t:"T10 · Day 30 · B",  subj:"Caitlin Flemming's go-to wallpaper",                 ph:"6 pieces our Experts can't get enough of.",       id:"Y4jugu"},
    ],
  },
  {
    name: "Post-Consultation",
    trigger: "Completed consultation (Added to List)",
    steps: [
      {t:"T1 · Day 1 · A",  subj:"What our Experts are shopping right now",  ph:"15% off for a limited time.",                         id:"TjbnSg"},
      {t:"T1 · Day 1 · B",  subj:"15% off our best-sellers",                 ph:"Exclusive to you, only for a limited time.",          id:"SJLAsw"},
      {t:"T2 · Day 4 · A",  subj:"The last layer your room needs",           ph:"Under $300 finds to finish off your space in style.", id:"Xf9rja"},
      {t:"T2 · Day 4 · B",  subj:"15% off fabric and wallpaper",             ph:"Plus, a step-by-step guide.",                        id:"UdgGBM"},
      {t:"T3 · Day 13",     subj:"Just for you: 15% off all month",          ph:"Now the fun part starts…",                           id:"Su5ZfP"},
      {t:"T4 · Day 29",     subj:"Your 15% off ends tomorrow",               ph:"Don't miss your chance to save big.",                 id:"R9HdBK"},
      {t:"T5 · Day 32",     subj:"Quick question…",                          ph:"We'd love your feedback!",                           id:"VX4PHP"},
    ],
  },
  {
    name: "Browse Abandonment",
    trigger: "Viewed product page (Metric)",
    steps: [
      {t:"T1 · ~2 hr", subj:"Did we catch your eye?", ph:"We can help make it official.", id:"Tb2443"},
    ],
  },
  {
    name: "Cart Abandonment",
    trigger: "Added to cart, no purchase (Metric)",
    steps: [
      {t:"T1 · ~1 hr", subj:"You have great taste!", ph:"We saved this for you…",  id:"SQvLwU"},
      {t:"T2 · Day 3", subj:"Remember me?",          ph:"Where'd you go?",          id:"VbjsiC"},
    ],
  },
  {
    name: "Create Account",
    trigger: "Account created (Added to List)",
    steps: [
      {t:"T1 · Day 1 · A", subj:"Have any questions?",         ph:"", id:"QTWspr"},
      {t:"T1 · Day 1 · B", subj:"Can I answer any questions?", ph:"", id:"T9nd5j"},
      {t:"T1 · Day 1 · C", subj:"Can I answer any questions?", ph:"", id:"YwDRAL"},
    ],
  },
  {
    name: "Trade Welcome (June 2026)",
    trigger: "Trade approval (Added to List)",
    steps: [
      {t:"T1 · Day 1",  subj:"Welcome to The Expert!",                            ph:"Shop faster. Save more. Stress Less.",           id:"Tmjisd"},
      {t:"T2 · Day 3",  subj:"Better trade discounts are here!",                  ph:"200+ brands. One unbeatable promise.",           id:"SDEZuc"},
      {t:"T3 · Day 5",  subj:"Excited to work with you!",                         ph:"",                                               id:"RW2Gwb"},
      {t:"T4 · Day 7",  subj:"Everything you'd travel to find, just a click away",ph:"A curated world of design at your fingertips.", id:"RiZDTy"},
      {t:"T5 · Day 10", subj:"Ready to declutter your inbox?",                    ph:"100s of brands, 1 contact.",                    id:"Renpya"},
      {t:"T6 · Day 13", subj:"We rep hundreds of brands. Let us help you source!",ph:"",                                               id:"VmBWQm"},
      {t:"T7 · Day 16", subj:"You're in good company",                            ph:"Join designers who've found their sourcing home.",id:"Wx2MJd"},
      {t:"T8 · Day 19", subj:"Loved by the trade. Exclusively ours.",             ph:"Stop giving your clients déjà vu…",              id:"UDXDSk"},
      {t:"T9 · Day 22", subj:"We want to be your growth partner",                 ph:"Think of us as an extension of your team.",     id:"XBNngF"},
    ],
  },
  {
    name: "Trade Welcome (July 2025)",
    trigger: "Trade approval (Added to List) — legacy",
    steps: [
      {t:"T1 · Day 1",      subj:"Welcome to The Expert!",                            ph:"Shop faster. Save more. Stress Less.",           id:"W3GLND"},
      {t:"T2 · Day 3",      subj:"Better trade discounts are here!",                  ph:"200+ brands. One unbeatable promise.",           id:"RKcGPE"},
      {t:"T3 · Day 5",      subj:"Everything you'd travel to find, just a click away",ph:"A curated world of design at your fingertips.", id:"REzsug"},
      {t:"T4 · Day 8",      subj:"Ready to declutter your inbox?",                    ph:"100s of brands, 1 contact.",                    id:"S3GJ4H"},
      {t:"T5 · Day 11",     subj:"You're in good company",                            ph:"Join designers who've found their sourcing home.",id:"Xb6BxY"},
      {t:"T6 · Day 14",     subj:"Loved by the trade. Exclusively ours.",             ph:"Stop giving your clients déjà vu…",              id:"RHbGF9"},
      {t:"T7 · Day 17 · A", subj:"We want to be your growth partner",                 ph:"Think of us as an extension of your team.",     id:"XCR9tP"},
      {t:"T7 · Day 17 · B", subj:"Excited to work with you!",                         ph:"",                                               id:"WDijgA"},
      {t:"T7 · Day 17 · C", subj:"We rep hundreds of brands. Let us help you source!",ph:"",                                               id:"W3ugDD"},
    ],
  },
  {
    name: "Trade Post-Purchase",
    trigger: "First trade order placed (Added to List)",
    steps: [
      {t:"T1 · Day 5",  subj:"What else can we help you source?",      ph:"Your first order is just the beginning…",  id:"Vhpnpq"},
      {t:"T2 · Day 8",  subj:"Let us showcase your work",               ph:"Enjoy perks from your Expert community.",  id:"WsNdhg"},
      {t:"T3 · Day 11", subj:"Unlock up to 25% off",                    ph:"Deeper discounts, only for trade members.",id:"XCd4b8"},
      {t:"T4 · Day 17", subj:"How to get $350 back, plus more perks",   ph:"Your road to gold starts here…",           id:"UEyjbw"},
    ],
  },
];

// ─── Layout constants ──────────────────────────────────────────────────────────
const SX = 100;   // page left margin
const LW = 140;   // width of the left label column (flow name / trigger)
const SW = 260;   // email card width
const SG = 40;    // gap between email cards
const LH = 120;   // header row height (timing + subject + preheader)
const RG = 120;   // row gap (between bottom of one row and top of next)

const DARK  = {r:0.11, g:0.13, b:0.17};
const GOLD  = {r:0.98, g:0.75, b:0.27};
const WHITE = {r:1,    g:1,    b:1   };
const GREY  = {r:0.6,  g:0.6,  b:0.6 };
const PGREY = {r:0.93, g:0.93, b:0.93};
const BLACK = {r:0.05, g:0.05, b:0.05};

// ─── Helpers ──────────────────────────────────────────────────────────────────
function mkRect(x, y, w, h, color) {
  const r = figma.createRectangle();
  r.x = x; r.y = y;
  r.resize(w, h);
  r.fills = [{type: 'SOLID', color}];
  figma.currentPage.appendChild(r);
  return r;
}

function mkText(x, y, txt, sz, style, color, maxW) {
  if (!txt) return null;
  const t = figma.createText();
  t.fontName = {family: "Inter", style};
  t.characters = String(txt);
  t.fontSize = sz;
  t.fills = [{type: 'SOLID', color}];
  if (maxW) {
    t.textAutoResize = 'HEIGHT';
    t.resize(maxW, 50);
  }
  t.x = x; t.y = y;
  figma.currentPage.appendChild(t);
  return t;
}

async function fetchImageHash(msgId) {
  try {
    const resp = await fetch(`${SERVER}/${msgId}.png`);
    if (!resp.ok) {
      console.warn(`Image not found for ${msgId}: ${resp.status}`);
      return null;
    }
    const buf = await resp.arrayBuffer();
    const img = figma.createImage(new Uint8Array(buf));
    return img.hash;
  } catch (e) {
    console.warn(`Failed to load image for ${msgId}: ${e}`);
    return null;
  }
}

function buildRow(rowY, flow, IH) {
  const maxFH = Math.max(...flow.steps.map(s => FH[s.id] || 400));

  // Left sidebar: dark stripe + flow name/trigger
  mkRect(SX, rowY - 44, 8, 44 + LH + maxFH, DARK);
  mkText(SX + 20, rowY - 40, flow.name,    14, 'Semi Bold', BLACK, 600);
  mkText(SX + 20, rowY - 22, flow.trigger, 10, 'Regular',   GREY,  600);

  for (let i = 0; i < flow.steps.length; i++) {
    const s = flow.steps[i];
    const sx = SX + LW + i * (SW + SG);
    const fh = FH[s.id] || 400;

    // Header card (dark)
    mkRect(sx, rowY, SW, LH, DARK);
    mkText(sx + 10, rowY + 8,  s.t,    11, 'Semi Bold', GOLD,  SW - 20);
    mkText(sx + 10, rowY + 26, s.subj, 10, 'Semi Bold', WHITE, SW - 20);
    if (s.ph) mkText(sx + 10, rowY + 58, s.ph, 9, 'Regular', GREY, SW - 20);

    // Email thumbnail
    const fr = mkRect(sx, rowY + LH, SW, fh, PGREY);
    if (IH[s.id]) {
      fr.fills = [{type: 'IMAGE', scaleMode: 'FIT', imageHash: IH[s.id]}];
    }
  }

  return rowY + LH + maxFH + RG;
}

// ─── Main ─────────────────────────────────────────────────────────────────────
(async () => {
  await figma.loadFontAsync({family: "Inter", style: "Regular"});
  await figma.loadFontAsync({family: "Inter", style: "Semi Bold"});

  figma.notify("Loading images from localhost:8899…", {timeout: 60000});

  // Collect all unique msg_ids
  const allIds = [...new Set(FLOWS.flatMap(f => f.steps.map(s => s.id)))];

  // Fetch all images (sequentially to avoid overwhelming the server)
  const IH = {};
  let loaded = 0;
  for (const id of allIds) {
    const hash = await fetchImageHash(id);
    if (hash) {
      IH[id] = hash;
      loaded++;
    }
  }
  figma.notify(`Loaded ${loaded}/${allIds.length} images. Building board…`);

  // Clear existing page content
  for (const n of [...figma.currentPage.children]) n.remove();

  // Title
  mkText(SX, 20, 'The Expert — Lifecycle Canvas Map', 20, 'Semi Bold', DARK);

  // Build all flow rows
  let rowY = 100;
  for (const flow of FLOWS) {
    rowY = buildRow(rowY, flow, IH);
  }

  figma.notify(`✓ TE Lifecycle Canvas Map built! ${FLOWS.length} flows, ${loaded} email thumbnails.`);
  figma.closePlugin();
})();
