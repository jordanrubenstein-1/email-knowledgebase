#!/usr/bin/env python3
"""
Create a Klaviyo email campaign (Draft, unscheduled) from an Asana task.

Subject extraction order:
  1. Lines before the greeting (Hi/Hey/Hello/Dear) in Asana notes
  2. Asana "Subject Line" custom field
  3. Missing: campaign created, Asana comment flags the gap

Link resolution order:
  1. --link CLI arg
  2. Asana "HeroImage/Other CTA Link(s)" custom field
  3. TI_DEFAULT_LINKS keyword match against campaign name
  4. Homepage fallback: https://www.theinside.com/

Link injection: bold text in html_notes (<strong>/<b> tags) → hyperlinks
Formatting: italic text (<em>/<i> tags) is preserved in the HTML output

Usage:
    # Asana-driven (primary):
    uv run python scripts/create_klaviyo_email.py \\
      --brand TI \\
      --asana-gid 1212913401777448

    # With explicit link override:
    uv run python scripts/create_klaviyo_email.py \\
      --brand TI \\
      --asana-gid 1212913401777448 \\
      --link https://www.theinside.com/collections/sale

    # Dry-run:
    uv run python scripts/create_klaviyo_email.py --brand TI --asana-gid GID --dry-run
"""

from __future__ import annotations

import argparse
import os
import re
import sys
from pathlib import Path

import requests
import yaml
from dotenv import load_dotenv

load_dotenv(Path(__file__).parent.parent / ".env")

sys.path.insert(0, str(Path(__file__).parent))
from utils.klaviyo_client import KlaviyoClient
from utils.pt_text import strip_markdown_emphasis
from utils.campaign_name import (
    clean_task_name_for_description,
    generate_campaign_name,
    validate_campaign_name,
)
from utils.segment_text import resolve_ti_segment_key, resolve_audience_names

# ---------------------------------------------------------------------------
# Constants
# ---------------------------------------------------------------------------

ASANA_BASE_URL           = "https://app.asana.com/api/1.0"
KLAVIYO_EDIT_URL_BASE    = "https://www.klaviyo.com/campaign"
KLAVIYO_OVERVIEW_URL_BASE = "https://www.klaviyo.com/campaign"
KLAVIYO_EMAIL_BRANDS     = {"TI"}

# Asana custom field GIDs
FIELD_BRAZE_LINK         = "1210710306792280"   # "Braze Campaign Link"
FIELD_HERO_CTA_LINK      = "1209982221146582"   # "HeroImage/Other CTA Link(s)"
FIELD_SUBJECT_LINE       = "1207522425689914"   # "Subject Line"
FIELD_PRE_HEADER         = "1207522425689916"   # "Pre-Header"
FIELD_SEGMENT            = "1211927654349290"   # "Segment" (enum) — legacy fallback
FIELD_SEGMENT_TEXT       = "1216855544683297"   # "Segment (Text)" — see CLAUDE.md

# Brand config path
BRAND_CONFIG_PATH = Path(__file__).parent.parent / "data" / "brand_config.yaml"

# TI keyword → URL (first match wins). Homepage is the sale/fallback default.
TI_DEFAULT_LINKS: list[tuple[str, str]] = [
    ("new arrivals", "https://www.theinside.com/collections/new-arrivals"),
    ("sale",         "https://www.theinside.com/"),
    ("outdoor",      "https://www.theinside.com/collections/outdoor-furniture"),
    ("bed",          "https://www.theinside.com/collections/bedding"),
    ("pillow",       "https://www.theinside.com/collections/pillows"),
    ("curtain",      "https://www.theinside.com/collections/window-treatments"),
    ("sofa",         "https://www.theinside.com/collections/sofas"),
    ("chair",        "https://www.theinside.com/c/living-room-furniture/chairs"),
    ("rug",          "https://www.theinside.com/collections/rugs"),
]
TI_HOMEPAGE = "https://www.theinside.com/"


# ---------------------------------------------------------------------------
# Brand config helpers
# ---------------------------------------------------------------------------

def _load_brand_config(brand: str) -> dict:
    with open(BRAND_CONFIG_PATH) as f:
        cfg = yaml.safe_load(f)
    return cfg.get("brands", {}).get(brand) or cfg.get(brand, {})


def _get_sender_info(brand: str) -> dict:
    cfg = _load_brand_config(brand)
    return cfg.get("sender_info", {}).get("pt", {})


def _get_klaviyo_audiences(brand: str, segment_key: str) -> tuple[list[str], list[str]]:
    cfg = _load_brand_config(brand)
    return resolve_audience_names(cfg, segment_key)


# ---------------------------------------------------------------------------
# Asana helpers
# ---------------------------------------------------------------------------

def _asana_headers() -> dict[str, str]:
    token = os.environ.get("ASANA_ACCESS_TOKEN")
    if not token:
        print("Error: ASANA_ACCESS_TOKEN not set in .env", file=sys.stderr)
        sys.exit(1)
    return {
        "Authorization": f"Bearer {token}",
        "Accept": "application/json",
        "Content-Type": "application/json",
    }


def fetch_asana_task(task_gid: str) -> dict | None:
    """Fetch a single Asana task including html_notes and custom fields."""
    resp = requests.get(
        f"{ASANA_BASE_URL}/tasks/{task_gid}",
        headers=_asana_headers(),
        params={
            "opt_fields": (
                "name,notes,html_notes,due_on,"
                "assignee,assignee.gid,assignee.name,"
                "custom_fields,custom_fields.gid,custom_fields.name,"
                "custom_fields.display_value,custom_fields.text_value,"
                "custom_fields.enum_value,custom_fields.enum_value.name,"
                "custom_fields.type"
            )
        },
        timeout=30,
    )
    if resp.status_code != 200:
        print(f"Error fetching Asana task {task_gid}: {resp.status_code} {resp.text[:200]}",
              file=sys.stderr)
        return None
    return resp.json().get("data")


def get_text_field(task: dict, field_gid: str) -> str | None:
    """Extract a text custom field value from a task by field GID."""
    for cf in task.get("custom_fields", []):
        if cf.get("gid") == field_gid:
            return cf.get("text_value") or cf.get("display_value") or None
    return None


def get_enum_field_name(task: dict, field_gid: str) -> str | None:
    """Extract an enum custom field's selected option name from a task by field GID."""
    for cf in task.get("custom_fields", []):
        if cf.get("gid") == field_gid and cf.get("enum_value"):
            return cf["enum_value"].get("name")
    return None


def resolve_segment_key(task: dict | None) -> str:
    """Resolve a TI task's audience key: Segment (Text) first, falling back to
    the legacy enum Segment field, defaulting to "engaged" (TI's baseline list).

    Send date (Asana due_on) gates the two swatch keys — see resolve_ti_segment_key()."""
    if not task:
        return resolve_ti_segment_key("")
    segment_text = get_text_field(task, FIELD_SEGMENT_TEXT) or ""
    raw = segment_text.strip() or get_enum_field_name(task, FIELD_SEGMENT) or ""
    send_date = task.get("due_on")
    return resolve_ti_segment_key(raw, send_date=send_date)


def post_asana_comment(
    task_gid: str,
    html_text: str,
    dry_run: bool = False,
) -> bool:
    """Post an HTML comment on an Asana task."""
    if dry_run:
        print(f"  [DRY RUN] Would post Asana comment:\n{html_text}")
        return True
    resp = requests.post(
        f"{ASANA_BASE_URL}/tasks/{task_gid}/stories",
        headers=_asana_headers(),
        json={"data": {"html_text": f"<body>{html_text}</body>", "is_pinned": False}},
        timeout=30,
    )
    if resp.status_code not in (200, 201):
        print(f"  Warning: Asana comment failed: {resp.status_code} {resp.text[:200]}")
        return False
    return True


def update_asana_task_link(task_gid: str, klaviyo_url: str, dry_run: bool = False) -> bool:
    """Write the Klaviyo campaign URL into the Asana 'Braze Campaign Link' field."""
    if dry_run:
        print(f"  [DRY RUN] Would set Asana 'Braze Campaign Link' = {klaviyo_url}")
        return True
    resp = requests.put(
        f"{ASANA_BASE_URL}/tasks/{task_gid}",
        headers=_asana_headers(),
        json={"data": {"custom_fields": {FIELD_BRAZE_LINK: klaviyo_url}}},
        timeout=30,
    )
    if resp.status_code != 200:
        print(f"  Warning: Asana update failed: {resp.status_code} {resp.text[:200]}")
        return False
    return True


# ---------------------------------------------------------------------------
# Campaign naming
# ---------------------------------------------------------------------------

def _generate_campaign_name(asana_task_name: str, due_on: str | None, brand: str) -> str:
    from datetime import date as _date

    # Shared with the Braze PT builder (_derive_campaign_name) so the two
    # can't drift again — this used to strip only a leading "PT:", leaving an
    # inner "PT" and literal hyphens in the generated name.
    description = clean_task_name_for_description(asana_task_name) or "Campaign"
    send_date = due_on or _date.today().isoformat()
    try:
        name = generate_campaign_name(
            campaign_type="P",
            channel="EM",
            send_date=send_date,
            brand=brand,
            description=description,
            design_type="PT",
        )
    except ValueError as e:
        # _derive_campaign_name() in build_pt_campaign.py (the Braze PT
        # builder) has always caught this and fallen back to the raw task
        # name; this builder had no such guard and would crash the whole
        # build on the same class of edge case (unrecognized brand code,
        # malformed date).
        print(f"  WARNING: campaign name generation failed ({e}), using raw task name: {asana_task_name}")
        return asana_task_name
    # Surface convention violations instead of shipping them silently —
    # validate_campaign_name() was previously called by neither builder.
    valid, issues = validate_campaign_name(name)
    if not valid:
        for issue in issues:
            print(f"  WARNING: campaign name issue ({name}): {issue}")
    return name


# ---------------------------------------------------------------------------
# Subject + body parsing
# ---------------------------------------------------------------------------

_GREETING_RE = re.compile(r"^(Hi|Hey|Hello|Dear)\b", re.IGNORECASE)
_AI_BRIEF_RE = re.compile(r"^\[AI Brief\]", re.IGNORECASE)
_SIGNOFF_RE = re.compile(
    r"^-?.{0,60}(?:Team|Lisa|Rachel)\b|"
    r"^(?:Best|Thanks|Warmly|Cheers|Happy Shopping|Happy Decorating|Happy designing|"
    r"With gratitude|See you soon|Thank you|Talk soon|Xo|Regards)[,!]?\s*$",
    re.IGNORECASE,
)


# Headers that open the AI-generated briefing section of an Asana description.
# Everything at or below one of these is briefing metadata and must never reach
# the email.  "[AI Brief]" is the documented separator, but plenty of briefs
# don't carry it and go straight into "Creative Direction:".
_BRIEF_SECTION_RE = re.compile(
    r"^\s*(?:"
    r"\[AI Brief\]"
    r"|Creative Direction\s*:"
    r"|Direction\s*:"
    r"|Proposed Body Copy\s*\(AI generated\)"
    r"|Proposed Copy\s*\(AI generated\)"
    r"|SL\s*(?:/\s*PH)?\s*\(AI generated\)"
    r"|PH\s*\(AI generated\)"
    r"|SL/PH Suggestions\s*\(AI generated\)"
    r"|Format\s*:"
    r")",
    re.IGNORECASE,
)

# Bare section words that open an internal-notes block.  Whole-line matches
# only — "Notes" alone is a header, "Notes on sizing below" is copy.  Ported
# from _NOTES_SECTION_HEADERS in build_pt_campaign.py, which the Braze builder
# has always cut at and this one did not.
_NOTES_SECTION_HEADERS = re.compile(
    r"^\s*(?:Overview|Notes|Details|Brief|Context|Instructions|Background|"
    r"Email Template Inspo|Template Inspo|Reference|Inspiration|"
    r"Copy Notes|Copywriter Notes|Internal Notes|Briefing|"
    r"\[AI Generated\]|\[AI Generated Instructions\])\s*:?\s*$",
    re.IGNORECASE,
)

# Horizontal rules ("---", "===", "***") used as section dividers.
_HORIZONTAL_RULE = re.compile(r"^\s*[-=*_]{3,}\s*$")

# A run of this many consecutive blank lines ends the email body.  Copywriters
# separate the copy from the briefing notes with a big gap; nothing inside real
# body copy has this much air.
_MAX_BLANK_RUN = 3


def _truncate_at_ai_brief(lines: list[str]) -> list[str]:
    """Trim briefing metadata off the end of the body copy.

    Cuts at whichever comes first:
      1. a briefing-section header (``_BRIEF_SECTION_RE``), or
      2. a run of ``_MAX_BLANK_RUN`` or more blank lines after real content.

    Rule 2 used to require the blank run to *immediately follow a recognised
    sign-off line*, which meant it could only fire on a one-line sign-off.  The
    house standard is two lines (phrase then name), so the blank run always sat
    under the *name* line — and ``_SIGNOFF_RE`` only matches a name containing
    "Team", "Lisa" or "Rachel".  The TI 8/27 "Labor Day Event Reminder PT
    Resend" brief closed "Happy Shopping!" / "Harper at The Inside": the phrase
    matched but wasn't followed by blanks, the name was followed by six blanks
    but didn't match, so nothing truncated and the whole briefing section plus
    the AI draft (its own greeting, body, URL and sign-off) was built into the
    email.  It only ever worked before by accident, whenever the name line
    happened to contain "Lisa".
    """
    cut: int | None = None

    for i, line in enumerate(lines):
        if (
            _BRIEF_SECTION_RE.match(line)
            or _NOTES_SECTION_HEADERS.match(line)
            or _HORIZONTAL_RULE.match(line)
        ):
            cut = i
            break

    seen_content = False
    blanks = 0
    for i, line in enumerate(lines):
        if line.strip():
            seen_content = True
            blanks = 0
            continue
        if not seen_content:
            continue
        blanks += 1
        if blanks >= _MAX_BLANK_RUN:
            start = i - blanks + 1
            if cut is None or start < cut:
                cut = start
            break

    return lines if cut is None else lines[:cut]


def extract_subject_and_body(notes: str) -> tuple[str | None, str]:
    """Split Asana notes into (subject, body).

    Subject: lines before the greeting (Hi/Hey/Hello/Dear).
    Body: from the greeting line onward, truncated at [AI Brief] marker or
    a signoff line followed by 3+ blank lines (whichever comes first).
    Returns (None, full_notes) if no greeting is found.
    """
    lines = notes.strip().splitlines()
    greeting_idx: int | None = None
    for i, line in enumerate(lines):
        if _GREETING_RE.match(line.strip()):
            greeting_idx = i
            break

    if greeting_idx is None:
        return None, notes.strip()

    pre = [l.strip() for l in lines[:greeting_idx] if l.strip()]
    body_lines = _truncate_at_ai_brief(lines[greeting_idx:])

    subject = _subject_from_pre_lines(pre)
    body = "\n".join(body_lines).strip()
    return subject, body


def _subject_from_pre_lines(pre: list[str]) -> str | None:
    """Pick the subject line out of the lines above the greeting.

    Previously every pre-greeting line was space-joined into one string.  That
    works when the copy is at the top of the description (a lone "SL: ..."
    line), but when the description is briefing-only the AI draft's greeting is
    the first greeting in the task — so the entire briefing preamble
    ("Creative Direction: … SL (AI generated): … Proposed Body Copy …") became
    the subject.  Worse, that string is truthy, so the caller never fell back
    to the Asana "Subject Line" field.

    Prefers the first explicitly labelled ``SL:`` / ``Subject Line:`` line,
    scanning top-down so a copywriter's own SL wins over the AI suggestion
    below it.  Returns ``None`` when nothing usable is found, letting the
    caller consult the custom field.
    """
    # Matches the same prefixes as the Braze builder's _SUBJECT_PREFIXES,
    # including markdown-bolded labels.  Note "Subject\s*Line?" (the earlier
    # form) requires a literal "Lin", so a plain "Subject:" never matched.
    label_re = re.compile(
        r"^(?:\*{0,2})(?:SL|Subject(?:\s*Line)?)(?:\*{0,2})\s*:\s*(?P<value>.+)$",
        re.IGNORECASE,
    )
    for line in pre:
        m = label_re.match(line)
        if m:
            # A bolded label ("**SL:**") leaves its closing marker behind — the
            # prefix pattern only consumes up to the colon.
            value = strip_markdown_emphasis(m.group("value"))
            if value:
                return value

    # No labelled SL — fall back to a single bare line, ignoring briefing
    # headers.  Anything longer is prose, not a subject.
    candidates = [l for l in pre if not _BRIEF_SECTION_RE.match(l)]
    if len(candidates) == 1 and len(candidates[0]) <= 120:
        return candidates[0]
    return None


# ---------------------------------------------------------------------------
# Formatting extraction from html_notes
# ---------------------------------------------------------------------------

def extract_bold_phrases(html_notes: str) -> list[str]:
    """Return plain-text content of <strong> and <b> tags in Asana html_notes."""
    raw = re.findall(r"<(?:strong|b)>(.*?)</(?:strong|b)>", html_notes, re.IGNORECASE | re.DOTALL)
    return [re.sub(r"<[^>]+>", "", phrase).strip() for phrase in raw if phrase.strip()]


def extract_anchors(html_notes: str) -> list[tuple[str, str]]:
    """Return (text, href) for each <a> tag in the copywriter's half of html_notes.

    Asana's plain-text ``notes`` projection of an anchor keeps only the href and
    throws the anchor text away, so a CTA written as
    ``<a href="https://www.theinside.com/">Shop the Last Day →</a>`` arrives in
    ``notes`` as a bare URL on its own line.  This builder assembles the body
    from ``notes``, and read ``html_notes`` only for <strong>/<em>, so the link
    text was never in the data at all — the URL shipped as literal text.
    (The Braze builder already handles this: an explicit <a href> in html_notes
    is rule 1 of its ``_apply_link_rules()``.)

    Anchors at or below a briefing-section header are the AI draft's, which the
    copywriter's version above supersedes — those are ignored.
    """
    lines = html_notes.splitlines()
    for i, line in enumerate(lines):
        if _BRIEF_SECTION_RE.match(re.sub(r"<[^>]+>", "", line)):
            lines = lines[:i]
            break
    copy_half = "\n".join(lines)

    anchors: list[tuple[str, str]] = []
    for href, inner in re.findall(
        r'<a\s[^>]*href="([^"]+)"[^>]*>(.*?)</a>', copy_half, re.IGNORECASE | re.DOTALL
    ):
        text = re.sub(r"<[^>]+>", "", inner).strip()
        href = href.replace("&amp;", "&").strip()
        if text and href and (text, href) not in anchors:
            anchors.append((text, href))
    return anchors


_BARE_URL_RE = re.compile(r"(?<!\")(?<!=)(https?://[^\s<>\"]+)")

# "[https://…]" / "[link: …]" / "[link to …]" — a bracketed inline link hint.
_BRACKET_URL_RE = re.compile(
    r"\[\s*(?:link(?:ed)?(?:\s+to)?\s*:?\s*)?"
    r"(?P<url>https?://[^\]\s]+|www\.[^\]\s]+)\s*\]",
    re.IGNORECASE,
)

# "anchor text: LINK" — the copywriter marks where a link goes without a URL.
_LINK_PLACEHOLDER_RE = re.compile(r"(?P<anchor>[^.!?:\n]{1,120}?)\s*:\s*LINK\b")
_BARE_LINK_PLACEHOLDER_RE = re.compile(r"\bLINK\b")

# "…here." / "…here:" — "here" language signals a link on the surrounding phrase.
_HERE_PHRASE_RE = re.compile(r"(?P<phrase>[^.!?\n]*\bhere\b)(?P<tail>[.!:]?)", re.IGNORECASE)


def _link_from_placeholder(paragraph: str, url: str) -> str | None:
    """Apply the "anchor text: LINK" rule, with CLAUDE.md's word-count formatting.

    - <= 3 words: drop the colon, append an arrow, link the phrase + arrow
    - 4-6 words: drop the colon, add a period, link the full phrase
    - > 6 words:  keep the sentence, swap ": LINK" for the URL (auto-linked later)

    The Braze builder has had this since the link-placement rules landed; this
    one had nothing, so a brief written "Shop early access: LINK" shipped with
    the literal word LINK visible in the email.
    """
    m = _LINK_PLACEHOLDER_RE.search(paragraph)
    if m:
        phrase = m.group("anchor").strip()
        words = phrase.split()
        if len(words) <= 3:
            replacement = f'<a href="{url}">{phrase} \u2192</a>'
        elif len(words) <= 6:
            replacement = f'<a href="{url}">{phrase}.</a>'
        else:
            replacement = f'{phrase} <a href="{url}">{url}</a>'
        return paragraph[: m.start()] + replacement + paragraph[m.end():]
    if _BARE_LINK_PLACEHOLDER_RE.search(paragraph):
        return _BARE_LINK_PLACEHOLDER_RE.sub(f'<a href="{url}">{url}</a>', paragraph, count=1)
    return None


def _apply_link_rules_paragraph(
    paragraph: str,
    anchors: list[tuple[str, str]],
    url: str | None,
) -> tuple[str, bool]:
    """Link one paragraph, in the same priority order as the Braze builder.

    Returns ``(paragraph, linked)``.  Priority: explicit <a href> from
    html_notes, bracketed URL hint, "anchor: LINK" placeholder, "here"
    language, then a bare URL (auto-linked so it is at least clickable).
    """
    # Rule 1: explicit anchor from html_notes
    if anchors:
        after = _apply_anchors(paragraph, anchors)
        if after != paragraph:
            return after, True

    # Rule 1.5: bracketed URL hint
    m = _BRACKET_URL_RE.search(paragraph)
    if m:
        href = m.group("url")
        if not href.startswith("http"):
            href = "https://" + href
        before = paragraph[: m.start()].rstrip()
        anchor_text = before.split(".")[-1].strip() or href
        if anchor_text and anchor_text != href:
            linked = f'<a href="{href}">{anchor_text}</a>'
            return (paragraph[: m.start()].rstrip()[: -len(anchor_text)] + linked
                    + paragraph[m.end():]), True
        return paragraph[: m.start()] + f'<a href="{href}">{href}</a>' + paragraph[m.end():], True

    # Rule 2: "anchor text: LINK" / bare LINK placeholder
    if url:
        placed = _link_from_placeholder(paragraph, url)
        if placed is not None:
            return placed, True

        # Rule 3: "here" language — link the surrounding phrase, not just "here"
        if re.search(r"\bhere\b", paragraph, re.IGNORECASE) and "<a href" not in paragraph:
            m3 = _HERE_PHRASE_RE.search(paragraph)
            if m3:
                phrase = m3.group("phrase").strip()
                tail = m3.group("tail") or "."
                if phrase:
                    return (paragraph[: m3.start()]
                            + f'<a href="{url}">{phrase}{tail}</a>'
                            + paragraph[m3.end():]), True

    # Rule 4 (fallback): a bare URL should at least be clickable rather than
    # shipping as plain text, which is what this builder used to do.
    if _BARE_URL_RE.search(paragraph) and "<a href" not in paragraph:
        return _BARE_URL_RE.sub(lambda mm: f'<a href="{mm.group(1)}">{mm.group(1)}</a>',
                                paragraph, count=1), True

    return paragraph, False


def _apply_anchors(paragraph: str, anchors: list[tuple[str, str]]) -> str:
    """Restore anchor text onto a paragraph the plain-text notes flattened.

    Two shapes, since Asana's flattening isn't consistent: the paragraph is the
    bare href (replace it wholesale with the anchor), or it still carries the
    anchor text (wrap that text in place).
    """
    for text, href in anchors:
        if paragraph.strip() == href:
            return f'<a href="{href}">{text}</a>'
        if text in paragraph:
            return paragraph.replace(text, f'<a href="{href}">{text}</a>', 1)
        if href in paragraph:
            return paragraph.replace(href, f'<a href="{href}">{text}</a>', 1)
    return paragraph


def extract_italic_phrases(html_notes: str) -> list[str]:
    """Return plain-text content of <em> and <i> tags in Asana html_notes."""
    raw = re.findall(r"<(?:em|i)>(.*?)</(?:em|i)>", html_notes, re.IGNORECASE | re.DOTALL)
    return [re.sub(r"<[^>]+>", "", phrase).strip() for phrase in raw if phrase.strip()]


# ---------------------------------------------------------------------------
# Body → minimal PT HTML
# ---------------------------------------------------------------------------

TI_PT_FOOTER = (
    '<p style="font-size: 11px; color: #888888; '
    "margin-top: 32px; line-height: 1.6; font-family: 'Helvetica Neue', Arial, sans-serif;\">\n"
    "  3200 Cherry Creek South Drive, Suite 210, Denver, CO 80209<br>\n"
    "  © {year} The Inside<br><br>\n"
    "  If you no longer wish to receive emails from us, you can "
    '<a href="{{% unsubscribe_link %}}" style="color: #888888; text-decoration: underline;">Unsubscribe</a>\n'
    "</p>"
)


def _build_footer(brand: str) -> str:
    from datetime import date
    year = date.today().year
    if brand.upper() == "TI":
        return TI_PT_FOOTER.format(year=year)
    return ""


# Klaviyo personalization tag for the recipient's first name, with fallback.
# Klaviyo uses Django-style templating — NOT Braze Liquid.  The Braze form
# ("{{${first_name} | default: 'there'}}") does not render here and ships as
# literal text.  This exact string is already in use across 18 sent TI/TE
# Klaviyo emails, so it is the established house form.
KLAVIYO_FIRST_NAME_TAG = "{{ first_name|default:'there' }}"

# Braze Liquid personalization, e.g. "{{${first_name} | default: 'there'}}" or
# "{{${first_name}}}".  Briefs are written from a shared PT prompt that has
# historically emitted the Braze form for every brand, so this syntax reaches
# Klaviyo builds regularly — and Klaviyo does not render it, it ships as
# literal text in front of the customer.
_BRAZE_LIQUID_RE = re.compile(
    r"\{\{\s*\$\{(?P<attr>[A-Za-z0-9_]+)\}\s*"
    r"(?:\|\s*default\s*:\s*(?P<q>['\"])(?P<fallback>.*?)(?P=q)\s*)?"
    r"\}\}"
)


def convert_braze_liquid(text: str) -> str:
    """Rewrite any Braze Liquid personalization tag into Klaviyo syntax.

    Braze: ``{{${first_name} | default: 'there'}}``  (``${...}`` attribute form)
    Klaviyo: ``{{ first_name|default:'there' }}``    (Django-style)

    Klaviyo silently ships the Braze form as literal text — confirmed on the TI
    "Labor Day Event Last Chance PT" brief, whose body opened with the Braze
    tag verbatim.  Applied to the whole body rather than just the greeting line,
    so a mid-copy personalization tag is converted too.
    """
    def _sub(m: re.Match) -> str:
        attr = m.group("attr")
        fallback = m.group("fallback")
        if fallback is None:
            return "{{ %s }}" % attr
        return "{{ %s|default:'%s' }}" % (attr, fallback)

    return _BRAZE_LIQUID_RE.sub(_sub, text)


# A greeting line: salutation word, an optional object (a plain word, or an
# existing personalization tag in either Klaviyo or Braze syntax), then
# terminal punctuation.
_GREETING_LINE_RE = re.compile(
    r"^(?P<salutation>Hi|Hey|Hello|Dear)"
    r"(?P<object>(?:\s+(?:\{\{.*?\}\}|[\w'\u2019-]+)){0,4})"
    r"\s*(?P<punct>[,!.:]?)\s*$",
    re.IGNORECASE,
)


def _normalize_greeting(body: str) -> str:
    """Rewrite the opening greeting to use Klaviyo first-name personalization.

    Unlike the Braze builder — where the greeting lives in the PT template and
    is *stripped* from the body (see ``build_pt_campaign.py``) — the Klaviyo
    path keeps the greeting inside the body and has no template supplying one.
    So a brief written per the copywriter skills ("Hi there,") shipped verbatim
    with no personalization at all; a bare "{{ first_name }}" with no fallback
    is equally bad, rendering "Hi ," for any profile missing a first name.

    Only the first greeting line is touched.  The salutation word and its
    terminal punctuation are preserved; an existing tag that already carries a
    ``default:`` fallback is left alone.
    """
    lines = body.splitlines()
    for i, line in enumerate(lines):
        stripped = line.strip()
        if not stripped:
            continue
        m = _GREETING_LINE_RE.match(stripped)
        if not m:
            break  # first real line isn't a greeting — nothing to normalize
        obj = m.group("object").strip()
        # Already personalized *with* a fallback (Klaviyo syntax) — leave as-is.
        if "first_name" in obj and "default" in obj and "${" not in obj:
            break
        punct = m.group("punct") or ","
        indent = line[: len(line) - len(line.lstrip())]
        lines[i] = f"{indent}{m.group('salutation')} {KLAVIYO_FIRST_NAME_TAG}{punct}"
        break
    return "\n".join(lines)


# A closing phrase line: short, and ends the way a sign-off does.  Deliberately
# looser than _SIGNOFF_RE's fixed vocabulary — the point is to catch whatever
# the copywriter improvised ("xx,", "Until soon,") and swap in the brand's
# standard, not to enumerate every phrase anyone might write.
_CLOSING_PHRASE_RE = re.compile(r"^.{1,30}[,!.]$")

# A name/attribution line: the brand default, an alias, "<Person> at <Brand>",
# or anything with "Team" in it.
def _looks_like_name_line(line: str, default_name: str, aliases: list[str]) -> bool:
    low = line.strip().lower()
    if not low:
        return False
    if low == default_name.strip().lower() or low in [a.strip().lower() for a in aliases]:
        return True
    if re.search(r"\b(?:at|from)\s+(?:The\s+)?[A-Z]", line):
        return True
    if re.search(r"\bTeam\b", line, re.IGNORECASE) and len(line) < 60:
        return True
    return False


def _normalize_signoff_block(body: str, brand: str) -> str:
    """Rewrite the trailing sign-off block to the brand's standard, phrase included.

    Only runs for brands flagged ``signoff_name_locked``.  Klaviyo's counterpart
    to ``build_pt_campaign._extract_locked_signoff()``: the Braze path rebuilds
    the sign-off from config at render time, but the Klaviyo path had no
    equivalent, and ``_normalize_signoff_name()`` below only ever replaced the
    *name* line — so a wrong closing phrase sailed through untouched.

    Confirmed on the TI "Labor Day Event Last Chance PT" brief, which closed
    "xx," / "Lisa at The Inside": the name was right, the phrase was not, and
    nothing corrected it.  ("xx," doesn't match ``_SIGNOFF_RE``, so the name
    normalizer never even fired.)

    Leaves the body untouched if no name/attribution line can be identified —
    better a missing correction than eating a line of real copy.
    """
    with open(BRAND_CONFIG_PATH) as f:
        styles = yaml.safe_load(f).get("pt_email_styles", {}).get(brand, {})
    if not styles.get("signoff_name_locked"):
        return body
    default_name = styles.get("default_signoff_name", "")
    default_phrase = styles.get("default_signoff", "")
    if not default_name:
        return body
    aliases = styles.get("signoff_name_aliases", []) or []

    lines = body.rstrip().splitlines()
    end = len(lines) - 1
    while end >= 0 and not lines[end].strip():
        end -= 1
    if end < 0 or not _looks_like_name_line(lines[end], default_name, aliases):
        return body

    # Walk up past blanks to find the closing phrase, if the brief wrote one.
    phrase_idx = None
    j = end - 1
    while j >= 0 and not lines[j].strip():
        j -= 1
    if j >= 0 and _CLOSING_PHRASE_RE.match(lines[j].strip()) and not _looks_like_name_line(
        lines[j], default_name, aliases
    ):
        phrase_idx = j

    lines[end] = default_name
    if default_phrase:
        if phrase_idx is not None:
            lines[phrase_idx] = default_phrase
        else:
            lines.insert(end, default_phrase)
    return "\n".join(lines)


def _normalize_signoff_name(body: str, brand: str) -> str:
    """Replace the signoff name line with the canonical default_signoff_name from brand_config.

    The signoff name is the first non-empty line immediately following a signoff phrase
    (e.g. "Happy Shopping!"). Any name there — alias or copywriter's placeholder — is
    replaced with default_signoff_name so the brand voice stays consistent.
    """
    with open(BRAND_CONFIG_PATH) as f:
        full_cfg = yaml.safe_load(f)
    styles = full_cfg.get("pt_email_styles", {}).get(brand, {})
    default_name = styles.get("default_signoff_name", "")
    if not default_name:
        return body
    lines = body.splitlines()
    result = []
    after_signoff = False
    for line in lines:
        stripped = line.strip()
        if after_signoff:
            if stripped:
                # This is the signoff name line — replace unless already correct
                result.append(default_name if stripped != default_name else line)
                after_signoff = False
            else:
                result.append(line)
        else:
            if stripped and _SIGNOFF_RE.match(stripped):
                after_signoff = True
            result.append(line)
    return "\n".join(result)


def body_to_html(
    body: str,
    bold_phrases: list[str],
    italic_phrases: list[str],
    link: str | None,
    brand: str = "TI",
    anchors: list[tuple[str, str]] | None = None,
) -> str:
    """Convert plain-text body to minimal PT email HTML.

    - Bold phrases (from html_notes) → hyperlinks wrapped in <strong>
    - Italic phrases (from html_notes) → preserved as <em>
    - Footer with unsubscribe appended after body
    """
    # Braze Liquid → Klaviyo syntax first, so the greeting normalizer below
    # sees an already-converted tag and leaves it alone.
    body = convert_braze_liquid(body)
    body = _normalize_greeting(body)
    # Locked brands get the whole block (phrase + name) rebuilt from config;
    # everyone else keeps the name-only correction.
    body = _normalize_signoff_block(body, brand)
    body = _normalize_signoff_name(body, brand)
    lines = body.strip().splitlines()

    # Collapse consecutive non-empty lines into paragraphs.
    # Exception: a signoff line (e.g. "Happy Shopping!") always starts a new paragraph
    # so it and the name below it don't merge into one line.
    paras: list[str] = []
    current: list[str] = []
    for line in lines:
        stripped = line.strip()
        if not stripped:
            if current:
                paras.append(" ".join(current))
                current = []
        elif _SIGNOFF_RE.match(stripped):
            # Flush whatever came before, then start a fresh paragraph for the signoff line
            if current:
                paras.append(" ".join(current))
                current = []
            paras.append(stripped)
        else:
            current.append(stripped)
    if current:
        paras.append(" ".join(current))

    # --- Link pass, in the Braze builder's priority order ---
    processed_paras: list[str] = []
    any_linked = False
    for para in paras:
        processed, linked = _apply_link_rules_paragraph(para, anchors or [], link)
        any_linked = any_linked or linked
        processed_paras.append(processed)

    # Rule 4: bold text as the link anchor — only when nothing else produced a
    # link.  Bold is otherwise just bold: this builder used to turn *every*
    # bold phrase into a link, and drop bold entirely when no link resolved.
    if bold_phrases and link and not any_linked:
        for idx, para in enumerate(processed_paras):
            if "<a href" in para:
                continue
            replaced = para
            for phrase in bold_phrases:
                if phrase in replaced:
                    replaced = replaced.replace(
                        phrase, f'<strong><a href="{link}">{phrase}</a></strong>', 1
                    )
                    break
            if replaced != para:
                processed_paras[idx] = replaced
                any_linked = True
                break

    # Rule 5 (fallback): nothing in the brief signaled a link at all — anchor,
    # bracket hint, LINK placeholder, "here" language, bare URL, and bold text
    # all came up empty. Rather than silently dropping the resolved link
    # (confirmed bug — mirrors the same class of bug fixed in the TI SMS
    # builder), append it as its own paragraph, matching the Braze PT
    # builder's own Rule 5 fallback (`_apply_link_rules()` in
    # build_pt_campaign.py: "body_copy.rstrip() + f'\n\n{homepage}'").
    if link and not any_linked:
        processed_paras.append(f'<a href="{link}">{link}</a>')
        any_linked = True

    html_paras: list[str] = []
    for processed in processed_paras:
        # Remaining bold phrases stay plain <strong> — preserved, not linked.
        if bold_phrases:
            for phrase in bold_phrases:
                if phrase and phrase in processed and f">{phrase}<" not in processed:
                    processed = processed.replace(phrase, f"<strong>{phrase}</strong>", 1)
        # Apply italic
        if italic_phrases:
            for phrase in italic_phrases:
                escaped = re.escape(phrase)
                processed = re.sub(
                    escaped,
                    f"<em>{phrase}</em>",
                    processed,
                    flags=re.IGNORECASE,
                )
        html_paras.append(f"<p>{processed}</p>")

    footer = _build_footer(brand)
    if footer:
        html_paras.append(footer)

    return "\n".join(html_paras)


# ---------------------------------------------------------------------------
# Link resolution
# ---------------------------------------------------------------------------

def resolve_link(
    cli_link: str | None,
    asana_task: dict | None,
    campaign_name: str,
) -> tuple[str, str]:
    """Resolve the destination URL. Returns (url, source_description)."""
    if cli_link:
        return cli_link, "--link argument"

    if asana_task:
        field_link = get_text_field(asana_task, FIELD_HERO_CTA_LINK)
        if field_link and field_link.startswith("http"):
            return field_link, "Asana HeroImage field"

    name_lower = campaign_name.lower()
    for keyword, url in TI_DEFAULT_LINKS:
        if keyword in name_lower:
            return url, f"TI_DEFAULT_LINKS keyword '{keyword}'"

    return TI_HOMEPAGE, "homepage fallback (no keyword match)"


# ---------------------------------------------------------------------------
# Klaviyo client factory
# ---------------------------------------------------------------------------

def init_klaviyo_client(brand: str) -> KlaviyoClient:
    brand = brand.upper()
    if brand not in KLAVIYO_EMAIL_BRANDS:
        print(f"Error: '{brand}' is not a supported Klaviyo email brand. Supported: {KLAVIYO_EMAIL_BRANDS}",
              file=sys.stderr)
        sys.exit(1)
    api_key = os.environ.get(f"KLAVIYO_API_KEY_{brand}")
    if not api_key:
        print(f"Error: KLAVIYO_API_KEY_{brand} not set in .env", file=sys.stderr)
        sys.exit(1)
    return KlaviyoClient(api_key=api_key, brand=brand)


# ---------------------------------------------------------------------------
# Core builder
# ---------------------------------------------------------------------------

def build_klaviyo_email_campaign(
    brand: str,
    asana_gid: str | None = None,
    link: str | None = None,
    name: str | None = None,
    subject: str | None = None,
    preheader: str = "",
    body: str | None = None,
    dry_run: bool = False,
) -> str | None:
    """Create a Draft Klaviyo email campaign. Returns the Klaviyo edit URL or None."""
    asana_task: dict | None = None
    html_notes: str = ""
    missing_subject = False

    if asana_gid:
        print(f"Fetching Asana task {asana_gid}...")
        asana_task = fetch_asana_task(asana_gid)
        if not asana_task:
            print("Error: could not fetch Asana task.", file=sys.stderr)
            return None

        html_notes = asana_task.get("html_notes", "")

        if not name:
            name = _generate_campaign_name(
                asana_task["name"], asana_task.get("due_on"), brand
            )

        if not subject:
            # 1. Lines before greeting in notes
            parsed_subject, notes_body = extract_subject_and_body(asana_task.get("notes", ""))
            if parsed_subject:
                subject = parsed_subject
                print(f"  Subject sourced from notes (pre-greeting).")
            else:
                # 2. Subject Line custom field
                subject = get_text_field(asana_task, FIELD_SUBJECT_LINE)
                if subject:
                    print(f"  Subject sourced from Asana 'Subject Line' field.")
                else:
                    print("  Warning: no subject line found — will flag in Asana comment.")
                    missing_subject = True
                    subject = ""
                # Body from notes if we didn't get it via pre-greeting split
                raw_notes = asana_task.get("notes", "")
                notes_body = "\n".join(
                    _truncate_at_ai_brief(raw_notes.splitlines())
                ).strip()

            if not body:
                body = notes_body

        if not preheader:
            preheader = get_text_field(asana_task, FIELD_PRE_HEADER) or ""

    if not name or body is None:
        print("Error: --name and --body are required when --asana-gid is not provided.",
              file=sys.stderr)
        return None

    # Resolve link
    resolved_link, link_source = resolve_link(link, asana_task, name)
    print(f"  Link: {resolved_link}  (source: {link_source})")

    # Extract bold + italic phrases from html_notes
    bold_phrases = extract_bold_phrases(html_notes) if html_notes else []
    italic_phrases = extract_italic_phrases(html_notes) if html_notes else []
    if bold_phrases:
        print(f"  Bold phrases (→ links)  : {bold_phrases}")
    if italic_phrases:
        print(f"  Italic phrases (→ <em>) : {italic_phrases}")
    if not bold_phrases and not italic_phrases:
        print("  No bold/italic phrases found in html_notes.")

    # Build HTML body (includes footer)
    anchors = extract_anchors(html_notes) if html_notes else []
    if anchors:
        print(f"  Found {len(anchors)} explicit link(s) in html_notes: "
              + ", ".join(f"{t!r} -> {h}" for t, h in anchors))
    body_html = body_to_html(
        body, bold_phrases, italic_phrases, resolved_link, brand=brand, anchors=anchors
    )

    # Load sender info from brand_config.yaml
    sender = _get_sender_info(brand)
    from_name  = sender.get("from_name", "")
    from_email = sender.get("from_email", "")
    reply_to   = sender.get("reply_to", from_email)

    segment_key = resolve_segment_key(asana_task)
    included_names, excluded_names = _get_klaviyo_audiences(brand, segment_key)

    print(f"\nCampaign name : {name}")
    print(f"Subject       : {subject or '(empty — needs manual entry)'}")
    print(f"Preheader     : {preheader or '(none)'}")
    print(f"From          : {from_name} <{from_email}>  (account default — not overridden)")
    print(f"Segment       : {segment_key}  (include={included_names} exclude={excluded_names})")
    print(f"Body HTML:\n{body_html}\n")

    # Resolve audience IDs now (before the dry-run check) — a real, read-only
    # Klaviyo lookup, so --dry-run actually exercises segment resolution and a
    # broken/nonexistent segment name surfaces before anyone tries to send.
    client = init_klaviyo_client(brand)
    included_ids: list[str] = []
    excluded_ids: list[str] = []

    for seg_name in included_names:
        print(f"Looking up included segment '{seg_name}'...")
        seg_id = client.find_list_or_segment_by_name(seg_name)
        if seg_id:
            included_ids.append(seg_id)
            print(f"  Found: {seg_id}")
        else:
            print(f"  Warning: '{seg_name}' not found in Klaviyo.")

    for seg_name in excluded_names:
        print(f"Looking up excluded segment '{seg_name}'...")
        seg_id = client.find_list_or_segment_by_name(seg_name)
        if seg_id:
            excluded_ids.append(seg_id)
            print(f"  Found: {seg_id}")
        else:
            print(f"  Warning: '{seg_name}' not found — no exclusion applied.")

    if not included_ids:
        print("Error: no included segments resolved. Aborting.", file=sys.stderr)
        return None

    if dry_run:
        print("[DRY RUN] No Klaviyo campaign created and no Asana updates made "
              "(segment/list lookups above were live, read-only API calls).")
        if asana_gid:
            update_asana_task_link(asana_gid, f"{KLAVIYO_EDIT_URL_BASE}/DRY_RUN/wizard/2",
                                   dry_run=True)
        return None

    # Create campaign (Smart Sending off — PT emails target by segment, not per-profile)
    print(f"\nCreating campaign '{name}'...")
    campaign_id = client.create_campaign(
        name=name,
        channel="email",
        included_ids=included_ids,
        excluded_ids=excluded_ids,
        use_smart_sending=False,
    )
    if not campaign_id:
        print("Error: campaign creation failed.", file=sys.stderr)
        return None
    print(f"  Campaign ID: {campaign_id}")

    # Fetch auto-created message
    print("Fetching auto-created campaign message...")
    messages = client.get_campaign_messages(campaign_id)
    if not messages:
        print("Error: could not retrieve campaign messages.", file=sys.stderr)
        return None
    message_id = messages[0]["id"]
    print(f"  Message ID: {message_id}")

    # Set subject / preview_text / from_label
    print("Setting subject / preheader / from_label...")
    meta: dict = {}
    if subject:
        meta["subject"] = subject
    if preheader:
        meta["preview_text"] = preheader
    if from_name:
        meta["from_label"] = from_name
    if from_email:
        meta["from_email"] = from_email
    if reply_to:
        meta["reply_to_email"] = reply_to
    if meta:
        if not client.update_campaign_message_content(message_id, meta):
            print("Error: failed to update campaign message content.", file=sys.stderr)
            return None

    # Create a CODE template and assign it to carry the HTML body
    print("Creating email template with HTML body...")
    template_id = client.create_email_template(name=name, html=body_html)
    if not template_id:
        print("Error: template creation failed.", file=sys.stderr)
        return None
    print(f"  Template ID: {template_id}")

    print("Assigning template to campaign message...")
    if not client.assign_template_to_campaign_message(message_id, template_id):
        print("Error: template assignment failed.", file=sys.stderr)
        return None

    edit_url = f"{KLAVIYO_EDIT_URL_BASE}/{campaign_id}/wizard/2"
    overview_url = f"{KLAVIYO_OVERVIEW_URL_BASE}/{campaign_id}/overview"

    print(f"\n✓ Campaign ready (Draft — unscheduled):")
    print(f"  Name     : {name}")
    print(f"  Subject  : {subject or '(missing — see Asana comment)'}")
    print(f"  Edit URL : {edit_url}")

    # Update Asana and post comment
    if asana_gid:
        print(f"\nUpdating Asana task {asana_gid}...")
        update_asana_task_link(asana_gid, edit_url)

        # Build comment
        comment_lines = [
            f"<ul>"
            f"<li>This email campaign has been automatically created in Klaviyo "
            f"and is ready for review and scheduling.</li>"
            f'<li>Overview: <a href="{overview_url}">{overview_url}</a></li>'
            f'<li>Edit: <a href="{edit_url}">{edit_url}</a></li>'
        ]
        if missing_subject:
            comment_lines.append(
                "<li>⚠️ Auto-built — subject line is missing, please add it before scheduling.</li>"
            )
        if link_source not in ("--link argument", "Asana HeroImage field"):
            comment_lines.append(
                f"<li>Note: the email link was inferred ({link_source}: {resolved_link}). "
                f"Please verify it is correct before scheduling.</li>"
            )

        assignee = asana_task.get("assignee") if asana_task else None
        if assignee and assignee.get("gid") and assignee.get("name"):
            comment_lines.append(
                f'<li>CC: <a data-asana-type="user" data-asana-gid="{assignee["gid"]}">'
                f'{assignee["name"]}</a></li>'
            )

        comment_lines.append("</ul>")
        post_asana_comment(asana_gid, "".join(comment_lines))
        print("  Asana comment posted.")

    return edit_url


# ---------------------------------------------------------------------------
# CLI entry point
# ---------------------------------------------------------------------------

def main() -> None:
    parser = argparse.ArgumentParser(
        description="Create a Klaviyo email campaign (Draft) from an Asana task."
    )
    parser.add_argument("--brand", required=True, help="Brand code (TI)")
    parser.add_argument("--asana-gid", help="Asana task GID to pull name + copy from")
    parser.add_argument("--link", help="Destination URL (overrides Asana field and default map)")
    parser.add_argument("--name", help="Campaign name (overrides Asana task name)")
    parser.add_argument("--subject", help="Email subject line (overrides Asana field)")
    parser.add_argument("--preheader", default="", help="Email preheader / preview text")
    parser.add_argument("--body", help="Email body plain text (overrides Asana notes)")
    parser.add_argument("--dry-run", action="store_true",
                        help="Print what would be created without making API calls")
    args = parser.parse_args()

    if not args.asana_gid and not (args.name and args.body):
        parser.error("Provide --asana-gid OR both --name and --body")

    build_klaviyo_email_campaign(
        brand=args.brand,
        asana_gid=args.asana_gid,
        link=args.link,
        name=args.name,
        subject=args.subject,
        preheader=args.preheader,
        body=args.body,
        dry_run=args.dry_run,
    )


if __name__ == "__main__":
    main()
