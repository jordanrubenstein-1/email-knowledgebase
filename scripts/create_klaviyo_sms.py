#!/usr/bin/env python3
"""
Create a Klaviyo SMS campaign (Draft, unscheduled) from an Asana task.

Link resolution order:
  1. --link CLI arg (manual override)
  2. Asana "HeroImage/Other CTA Link(s)" custom field (FIELD_HERO_CTA_LINK)
  3. Keyword-based default from TI_DEFAULT_LINKS (matched against campaign name)
  4. If none match: leave placeholder and warn

Usage:
    # Asana-driven (primary):
    uv run python scripts/create_klaviyo_sms.py \\
      --brand TI \\
      --asana-gid 1213758018415441 \\
      --link https://www.theinside.com/collections/new-arrivals

    # Manual override:
    uv run python scripts/create_klaviyo_sms.py \\
      --brand TI \\
      --name "SMS: Spring Arrivals" \\
      --body "The Inside: Spring just dropped..." \\
      --segment "Master SMS Segment"

    # Dry-run:
    uv run python scripts/create_klaviyo_sms.py --brand TI --asana-gid GID --dry-run
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
from utils.campaign_name import generate_campaign_name
from utils.sms_brand_prefix import check_sms_brand_prefix
from utils.sms_grammar import check_copy_grammar, SMS_URL_STRIP_RE
from utils.url_validation import validate_url

PROJECT_ROOT = Path(__file__).parent.parent

# ---------------------------------------------------------------------------
# Constants
# ---------------------------------------------------------------------------

ASANA_BASE_URL          = "https://app.asana.com/api/1.0"
KLAVIYO_EDIT_URL_BASE   = "https://www.klaviyo.com/text-message/campaign"
KLAVIYO_OVERVIEW_URL_BASE = "https://www.klaviyo.com/campaign"
KLAVIYO_BRANDS          = {"TI"}

# Asana custom field GIDs
FIELD_BRAZE_LINK        = "1210710306792280"   # "Braze Campaign Link"
FIELD_HERO_CTA_LINK     = "1209982221146582"   # "HeroImage/Other CTA Link(s)"
FIELD_COPY              = "1209982215611013"   # "Copy" (SMS body text)

# Fallback default campaign name keyword -> URL (first keyword match wins),
# used only if data/ti_links.yaml is missing or fails to load. Normally
# superseded by _ti_default_links_from_yaml() below, which is the real
# source of truth shared with email briefing.
TI_DEFAULT_LINKS: list[tuple[str, str]] = [
    ("new arrivals",        "https://www.theinside.com/collections/new-arrivals"),
    ("outdoor",             "https://www.theinside.com/collections/outdoorliving"),
    ("bed",                 "https://www.theinside.com/c/bedroom-furniture/beds"),
    ("pillow",              "https://www.theinside.com/c/home-decor/throw-pillows"),
    ("curtain",             "https://www.theinside.com/c/home-decor/curtains"),
    ("sofa",                "https://www.theinside.com/c/living-room-furniture/sofas"),
    ("chair",               "https://www.theinside.com/c/living-room-furniture/chairs"),
    ("rug",                 "https://www.theinside.com/collections/rugs"),
    ("",                    "https://www.theinside.com/"),
]


def _ti_default_links_from_yaml() -> list[tuple[str, str]] | None:
    """Build the TI_DEFAULT_LINKS-shaped list from data/ti_links.yaml.

    Only the `categories` + `product_categories` sections are used (stable
    nav-level pages) — `destinations`/`edits`/`prints` are one-off seasonal
    editorial collections with no `keywords` field, matched by label lookup
    elsewhere, not by this keyword scan.

    Returns entries sorted by keyword length descending, since resolve_link()
    does a simple first-substring-match-wins scan (not scored) — without this
    sort, a short generic keyword earlier in the yaml (e.g. "chair") could
    shadow a more specific one added later (e.g. "dining chair"). The
    homepage entry's catch-all keywords are excluded from this list and a
    bare "" is appended last, matching TI_DEFAULT_LINKS' own fallback-to-
    homepage convention (an empty string matches any string, so it must
    always be checked last).
    """
    yaml_path = PROJECT_ROOT / "data" / "ti_links.yaml"
    if not yaml_path.exists():
        return None
    with open(yaml_path) as f:
        data = yaml.safe_load(f)

    homepage_url = "https://www.theinside.com/"
    pairs: list[tuple[str, str]] = []
    for section_name in ("categories", "product_categories"):
        for item in data.get(section_name, []):
            keywords = item.get("keywords")
            if not keywords or item["url"] == homepage_url:
                continue
            for kw in keywords:
                pairs.append((kw, item["url"]))

    pairs.sort(key=lambda pair: len(pair[0]), reverse=True)
    pairs.append(("", homepage_url))
    return pairs

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
    """Fetch a single Asana task with name, notes, due_on, and custom fields."""
    resp = requests.get(
        f"{ASANA_BASE_URL}/tasks/{task_gid}",
        headers=_asana_headers(),
        params={
            "opt_fields": (
                "name,notes,due_on,"
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


def post_asana_campaign_comment(
    task_gid: str,
    klaviyo_url: str,
    edit_url: str,
    assignee: dict | None,
    dry_run: bool = False,
) -> bool:
    """Post an Asana comment tagging the assignee once a Klaviyo SMS campaign is created."""
    campaign_id = klaviyo_url.rstrip("/").split("/")[-2] if "/campaign/" in klaviyo_url else "?"
    mention = ""
    if assignee and assignee.get("gid") and assignee.get("name"):
        mention = (
            f'<li>CC: <a data-asana-type="user" data-asana-gid="{assignee["gid"]}">'
            f'{assignee["name"]}</a></li>'
        )
    html_text = (
        f"<body><ul>"
        f"<li>This SMS campaign has been automatically created in Klaviyo "
        f"and is ready for review and scheduling.</li>"
        f'<li>Overview: <a href="{klaviyo_url}">{klaviyo_url}</a></li>'
        f'<li>Edit: <a href="{edit_url}">{edit_url}</a></li>'
        f"{mention}"
        f"</ul></body>"
    )
    if dry_run:
        print(f"  [DRY RUN] Would post Asana comment:\n{html_text}")
        return True
    resp = requests.post(
        f"{ASANA_BASE_URL}/tasks/{task_gid}/stories",
        headers=_asana_headers(),
        json={"data": {"html_text": html_text, "is_pinned": False}},
        timeout=30,
    )
    if resp.status_code not in (200, 201):
        print(f"  Warning: Asana comment failed: {resp.status_code} {resp.text[:200]}")
        return False
    return True


def update_asana_task_link(task_gid: str, klaviyo_url: str, dry_run: bool = False) -> bool:
    """Write the Klaviyo campaign URL into the Asana 'Braze Campaign Link' field."""
    if dry_run:
        print(f"  [DRY RUN] Would update Asana task {task_gid}: Braze Campaign Link = {klaviyo_url}")
        return True
    payload = {
        "data": {
            "custom_fields": {
                FIELD_BRAZE_LINK: klaviyo_url,
            }
        }
    }
    resp = requests.put(
        f"{ASANA_BASE_URL}/tasks/{task_gid}",
        headers=_asana_headers(),
        json=payload,
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
    """Generate a properly-formatted campaign name from an Asana task.

    Strips the channel prefix (e.g. "SMS: ") from the task name and formats
    using the standard naming convention: P_SMS_YYYY_MM_DD_{BRAND}_{Description}.

    Args:
        asana_task_name: Raw Asana task name, e.g. "SMS: Spring Arrivals".
        due_on: Task due date as "YYYY-MM-DD", or None to use today.
        brand: Brand code, e.g. "TI".

    Returns:
        Formatted name, e.g. "P_SMS_2026_04_04_TI_Spring_Arrivals".
    """
    from datetime import date as _date

    description = re.sub(r"^(SMS|EM|PUSH|Email|Push):\s*", "", asana_task_name, flags=re.IGNORECASE).strip()
    send_date = due_on or _date.today().isoformat()
    try:
        return generate_campaign_name(
            campaign_type="P",
            channel="SMS",
            send_date=send_date,
            brand=brand,
            description=description,
        )
    except ValueError as e:
        # generate_sms_campaign_name() in build_sms_campaign.py (the Braze SMS
        # builder) has always had this fallback; this builder didn't, so a
        # naming edge case (unrecognized brand code, malformed date, etc.)
        # would crash the whole build instead of producing a usable — if
        # imperfect — campaign name.
        print(f"  WARNING: generate_campaign_name failed ({e}), building name manually")
        date_str = send_date.replace("-", "_")
        desc_parts = description.replace(" ", "_").split("_")
        desc_formatted = "_".join(
            w[0].upper() + w[1:] if len(w) > 1 else w.upper()
            for w in desc_parts if w
        )
        return f"P_SMS_{date_str}_{brand}_{desc_formatted}"


# ---------------------------------------------------------------------------
# Copy parsing
# ---------------------------------------------------------------------------

def extract_sms_body(notes: str) -> str:
    """Return the primary SMS copy from Asana task notes.

    Convention: the first non-empty paragraph (everything before the first
    blank line). The creative-direction block below the separator is ignored.
    """
    lines = notes.strip().splitlines()
    body_lines: list[str] = []
    for line in lines:
        if line.strip() == "" and body_lines:
            break
        if line.strip():
            body_lines.append(line.strip())
    return " ".join(body_lines)


_LINK_PLACEHOLDER_RE = re.compile(r"→\s*(\[?link\]?|LINK|<link>)|\[link\]|<link>|\bLINK\b", re.IGNORECASE)


def has_link_placeholder(body: str) -> bool:
    """True if body contains an arrow+placeholder, bare LINK, [link], or <link> token."""
    return bool(_LINK_PLACEHOLDER_RE.search(body))


def apply_link(body: str, link: str) -> str:
    """Replace arrow+placeholder patterns with ': <link>'.

    Rules:
      - No space before the colon (colon attaches directly to the last word)
      - One space between colon and URL

    Handles: '→ LINK', '→ [link]', bare 'LINK', bare '[link]', bare '<link>'
    """
    # Arrow + placeholder (with optional surrounding spaces)
    body = re.sub(
        r"\s*→\s*(\[?link\]?|LINK|<link>)",
        f": {link}",
        body,
        flags=re.IGNORECASE,
    )
    # Bare [link] and <link> (must run before bare LINK to avoid partial match)
    body = re.sub(r"\[link\]", link, body, flags=re.IGNORECASE)
    body = re.sub(r"<link>", link, body, flags=re.IGNORECASE)
    # Bare LINK (word-bounded — runs last so it doesn't eat the inner 'link' of [link])
    body = re.sub(r"\bLINK\b", link, body, flags=re.IGNORECASE)
    return body


def append_link(body: str, link: str) -> str:
    """Append a resolved link to the end of SMS copy that has no link placeholder.

    Follows the SMS link-formatting rule (CLAUDE.md): the sentence immediately
    before the link ends with a colon, not a period — unless the copy already
    contains a colon elsewhere, in which case a period is used to avoid a
    double colon.
    """
    body = body.rstrip()
    if body.endswith(":"):
        return f"{body} {link}"
    if ":" in body:
        return f"{body.rstrip('.')}. {link}"
    return f"{body.rstrip('.')}: {link}"


def resolve_link(
    cli_link: str | None,
    asana_task: dict | None,
    campaign_name: str,
) -> str | None:
    """Resolve the destination URL using the priority chain:
      1. --link CLI arg
      2. Asana HeroImage/Other CTA Link(s) field
      3. Keyword match against campaign name from data/ti_links.yaml
         (falls back to the hardcoded TI_DEFAULT_LINKS if the yaml is
         missing or fails to load)
      4. None (caller warns)
    """
    if cli_link:
        return cli_link

    if asana_task:
        field_link = get_text_field(asana_task, FIELD_HERO_CTA_LINK)
        if field_link and field_link.startswith("http"):
            print(f"  Using link from Asana HeroImage field: {field_link}")
            return field_link

    # Campaign names follow the underscored convention (e.g.
    # "P_SMS_2026_04_04_TI_New_Arrivals") — normalize to spaces so multi-word
    # keywords like "new arrivals" actually match instead of silently never
    # firing (confirmed bug: this previously made "new arrivals" dead).
    name_normalized = campaign_name.lower().replace("_", " ")
    links = _ti_default_links_from_yaml() or TI_DEFAULT_LINKS
    for keyword, url in links:
        if keyword in name_normalized:
            print(f"  Using default link for keyword '{keyword}': {url}")
            return url

    return None


# ---------------------------------------------------------------------------
# Klaviyo client factory
# ---------------------------------------------------------------------------

def init_klaviyo_client(brand: str) -> KlaviyoClient:
    brand = brand.upper()
    if brand not in KLAVIYO_BRANDS:
        print(f"Error: '{brand}' is not a supported Klaviyo SMS brand. Supported: {KLAVIYO_BRANDS}",
              file=sys.stderr)
        sys.exit(1)
    api_key = os.environ.get(f"KLAVIYO_API_KEY_{brand}")
    if not api_key:
        print(f"Error: KLAVIYO_API_KEY_{brand} not set in .env", file=sys.stderr)
        sys.exit(1)
    return KlaviyoClient(api_key=api_key, brand=brand)


# ---------------------------------------------------------------------------
# Core builder — importable for use from webhook server
# ---------------------------------------------------------------------------

def build_klaviyo_sms_campaign(
    brand: str,
    asana_gid: str | None = None,
    link: str | None = None,
    name: str | None = None,
    body: str | None = None,
    segment: str = "Master SMS Segment",
    dry_run: bool = False,
) -> str | None:
    """Create a Draft Klaviyo SMS campaign. Returns the Klaviyo campaign URL or None."""
    asana_task = None

    if asana_gid:
        print(f"Fetching Asana task {asana_gid}...")
        asana_task = fetch_asana_task(asana_gid)
        if not asana_task:
            print("Error: could not fetch Asana task.", file=sys.stderr)
            return None
        if not name:
            name = _generate_campaign_name(
                asana_task["name"], asana_task.get("due_on"), brand
            )
        if not body:
            copy_field = get_text_field(asana_task, FIELD_COPY) or ""
            body = extract_sms_body(copy_field) if copy_field else ""
            if body:
                print("  SMS copy sourced from 'Copy' custom field.")
            else:
                notes = asana_task.get("notes", "")
                body = extract_sms_body(notes)
            if not body:
                print("Error: could not extract SMS body from 'Copy' field or task notes.", file=sys.stderr)
                return None

    if not name or not body:
        print("Error: --name and --body are required when --asana-gid is not provided.",
              file=sys.stderr)
        return None

    # Resolve link
    resolved_link = resolve_link(link, asana_task, name)
    if resolved_link:
        # Live-check the resolved URL before using it (same check the Braze SMS
        # builder has always run via validate_url() in build_sms_campaign.py —
        # this builder trusted the resolved link blindly). Non-blocking: a
        # broken/redirecting URL only gets a printed warning, the link is
        # still used, matching Braze's own behavior.
        validate_url(
            resolved_link,
            on_error=lambda msg: print(f"  ERROR: {msg}"),
            on_warning=lambda msg: print(f"  WARNING: {msg}"),
        )
        if has_link_placeholder(body):
            body = apply_link(body, resolved_link)
        elif re.search(r"https?://", body):
            print("  Body already contains a URL — leaving as-is.")
        else:
            # No placeholder and no existing URL — the brief copy never
            # signaled where a link goes. Rather than silently ship an SMS
            # with no link at all (confirmed bug: 9/8 TI Labor Day Event
            # Last Chance had no LINK/[link]/arrow token anywhere in the
            # brief copy, so the resolved link was previously dropped),
            # append the resolved link to the end of the copy.
            body = append_link(body, resolved_link)
            print(f"  No link placeholder in copy — appended resolved link to end: {resolved_link}")
    elif has_link_placeholder(body):
        print(
            "Warning: body contains a link placeholder but no URL could be resolved.\n"
            "  Add a URL to the Asana 'HeroImage/Other CTA Link(s)' field, pass --link,\n"
            "  or add a keyword entry to TI_DEFAULT_LINKS in create_klaviyo_sms.py."
        )

    # Copy is written by hand into Asana and passed through verbatim, so a
    # copywriter working from a mislabeled task can hand a send another
    # brand's prefix. Only the prefix form is checked — copy that embeds the
    # brand name mid-sentence, or leads with "LAST CHANCE:"/"Reminder:", is
    # valid house style and never flagged.
    prefix_error = check_sms_brand_prefix(body, brand)
    if prefix_error:
        print(f"Error: {prefix_error}", file=sys.stderr)
        return None

    # Grammar/copy-quality check — same mechanical checks as the Braze SMS
    # builder (space before punctuation, double spaces, ":." sequences), via
    # the module the two builders now share (scripts/utils/sms_grammar.py).
    # The link is stripped first so its own formatting can't produce a false
    # positive. Non-blocking, same as Braze: the campaign is still built.
    copy_for_grammar = SMS_URL_STRIP_RE.sub(' ', body).strip()
    grammar_warnings = check_copy_grammar(copy_for_grammar)
    if grammar_warnings:
        print(f"\n  ** GRAMMAR: {len(grammar_warnings)} issue(s) detected in copy:")
        for w in grammar_warnings:
            print(f"     - {w}")

    print(f"\nCampaign name  : {name}")
    print(f"SMS body       : {body}")
    print(f"Char count     : {len(body)}")
    print(f"Segment        : {segment}")

    if dry_run:
        print("\n[DRY RUN] No Klaviyo API calls made.")
        if asana_gid:
            update_asana_task_link(asana_gid, f"{KLAVIYO_OVERVIEW_URL_BASE}/DRY_RUN/overview",
                                   dry_run=True)
        return None

    client = init_klaviyo_client(brand)

    print(f"\nLooking up segment '{segment}'...")
    segment_id = client.find_list_or_segment_by_name(segment)
    if not segment_id:
        print(f"Error: segment '{segment}' not found in Klaviyo for brand {brand}.", file=sys.stderr)
        return None
    print(f"  Found: {segment_id}")

    print("Looking up 'Trade Members (All)' exclusion segment...")
    trade_exclusion_id = client.find_list_or_segment_by_name("Trade Members (All)")
    excluded_ids = [trade_exclusion_id] if trade_exclusion_id else []
    if excluded_ids:
        print(f"  Excluding: Trade Members (All) ({trade_exclusion_id})")
    else:
        print("  Warning: 'Trade Members (All)' segment not found — no exclusion applied.")

    print(f"Creating campaign '{name}'...")
    campaign_id = client.create_campaign(
        name=name,
        channel="sms",
        included_ids=[segment_id],
        excluded_ids=excluded_ids,
        use_smart_sending=False,
    )
    if not campaign_id:
        print("Error: campaign creation failed.", file=sys.stderr)
        return None
    print(f"  Campaign ID: {campaign_id}")

    print("Fetching auto-created campaign message...")
    messages = client.get_campaign_messages(campaign_id)
    if not messages:
        print("Error: could not retrieve campaign messages.", file=sys.stderr)
        return None
    message_id = messages[0]["id"]
    print(f"  Message ID: {message_id}")

    print("Setting SMS body...")
    if not client.update_campaign_message_body(message_id, body):
        print("Error: failed to update message body.", file=sys.stderr)
        return None

    print("Disabling unsubscribe instructions...")
    client.update_campaign_message_options(
        message_id,
        render_options={
            "shorten_links": True,
            "add_org_prefix": False,
            "add_info_link": True,
            "add_opt_out_language": False,
        },
    )

    edit_url     = f"{KLAVIYO_EDIT_URL_BASE}/{campaign_id}/edit"
    overview_url = f"{KLAVIYO_OVERVIEW_URL_BASE}/{campaign_id}/overview"
    print(f"\n✓ Campaign ready (Draft — unscheduled):")
    print(f"  Name : {name}")
    print(f"  Body : {body}")
    print(f"  Edit : {edit_url}")

    if asana_gid:
        print(f"\nUpdating Asana task {asana_gid}...")
        update_asana_task_link(asana_gid, overview_url)
        assignee = asana_task.get("assignee") if asana_task else None
        comment_ok = post_asana_campaign_comment(asana_gid, overview_url, edit_url, assignee,
                                                 dry_run=dry_run)
        if comment_ok:
            print("  Asana comment posted.")
        else:
            print("  WARNING: Failed to post Asana comment.")

        # Separate grammar-warning comment, matching the Braze SMS builder's own
        # follow-up comment wording — non-blocking, campaign already built.
        # (dry_run always returns before this point, so this only runs on a
        # real build, same as the main comment above.)
        if grammar_warnings:
            issues_text = "\n".join(f"<li>{w}</li>" for w in grammar_warnings)
            grammar_html = (
                f"<body><p>⚠️ Grammar check flagged {len(grammar_warnings)} issue(s) "
                f"in the SMS copy — please review before dispatching:</p>"
                f"<ul>{issues_text}</ul>"
                f"<p>The campaign was still built; update the copy in Klaviyo if needed.</p></body>"
            )
            grammar_comment_ok = requests.post(
                f"{ASANA_BASE_URL}/tasks/{asana_gid}/stories",
                headers=_asana_headers(),
                json={"data": {"html_text": grammar_html, "is_pinned": False}},
                timeout=30,
            ).status_code in (200, 201)
            if grammar_comment_ok:
                print(f"  Grammar warning comment posted ({len(grammar_warnings)} issue(s)).")
            else:
                print("  WARNING: Failed to post grammar warning comment.")

    return edit_url


# ---------------------------------------------------------------------------
# CLI entry point
# ---------------------------------------------------------------------------

def main() -> None:
    parser = argparse.ArgumentParser(
        description="Create a Klaviyo SMS campaign (Draft) from an Asana task."
    )
    parser.add_argument("--brand", required=True, help="Brand code (TI)")
    parser.add_argument("--asana-gid", help="Asana task GID to pull name + copy from")
    parser.add_argument("--link", help="Destination URL (overrides Asana field and default map)")
    parser.add_argument("--name", help="Campaign name (overrides Asana task name)")
    parser.add_argument("--body", help="SMS body text (overrides Asana notes)")
    parser.add_argument("--segment", default="Master SMS Segment",
                        help="Klaviyo list/segment name (default: Master SMS Segment)")
    parser.add_argument("--dry-run", action="store_true",
                        help="Print what would be created without making API calls")
    args = parser.parse_args()

    if not args.asana_gid and not (args.name and args.body):
        parser.error("Provide --asana-gid OR both --name and --body")

    build_klaviyo_sms_campaign(
        brand=args.brand,
        asana_gid=args.asana_gid,
        link=args.link,
        name=args.name,
        body=args.body,
        segment=args.segment,
        dry_run=args.dry_run,
    )


if __name__ == "__main__":
    main()
