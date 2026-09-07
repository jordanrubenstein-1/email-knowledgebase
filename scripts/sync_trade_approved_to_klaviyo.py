#!/usr/bin/env python3
"""
Sync TE's individually-approved trade partners (HubSpot) plus anyone who has
already received the July 2026 relaunch trade welcome email (Klaviyo) into a
single, safer Klaviyo list.

This is narrower than the existing scripts/sync_hubspot_trade_to_klaviyo.py,
which pulls in EVERY contact associated with a trade-partner company via the
company-level company_type field (~10.8k contacts) regardless of individual
vetting.

Source A (HubSpot): contacts where is_trade_partner = true. Confirmed
2026-07-29 by cross-tabbing against company_type that this is the real
per-person approval flag, distinct from the company-level rollup — it
excludes the ~2,910 contacts who are merely employed by a trade-partner
company but were never individually applied/vetted.

Source A also excludes any contact carrying a value in contact_brand_origin,
which marks contacts created by the HubSpot-to-HubSpot instance sync. Note this
check is NOT redundant here the way it is in sync_hubspot_trade_to_klaviyo.py:
that script inherits list 449's own contact_brand_origin IS_UNKNOWN filter,
whereas this one queries is_trade_partner directly and never touches list 449,
so the skip below is the only thing gating cross-instance contacts out of
Source A.

Source B (Klaviyo): profiles who've received the welcome flow's first email
(campaign name "trade-approved_email-01" — reused across every historical
flow revision) on or after the 2026-07-14 relaunch date. Captured via a
small, dedicated Klaviyo segment (bootstrapped by this script if missing)
using an absolute date cutoff, not a lifetime or rolling-window count, since
a raw "ever received" check would wrongly include people welcomed years ago
under an older, now-draft flow version.

Target: Klaviyo list XMEFhV ("Trade Members - Approved Only [Hubspot via
API]"), created directly in the TE Klaviyo account.

Each run does a full pull + diff, same shape as sync_hubspot_trade_to_klaviyo.py:
add newly-qualifying profiles, remove profiles no longer in either source, and
subscribe only this run's NEW adds to email marketing (never mass-resubscribe
the historical backlog). NOTE: list XMEFhV is configured double opt-in, so the
subscribe step sends a confirmation email rather than granting consent
immediately.

Usage:
    uv run python scripts/sync_trade_approved_to_klaviyo.py --dry-run
    uv run python scripts/sync_trade_approved_to_klaviyo.py
"""

from __future__ import annotations

import os
import sys
import argparse
from pathlib import Path

from dotenv import load_dotenv

load_dotenv(Path(__file__).parent.parent / ".env")

sys.path.insert(0, str(Path(__file__).parent))
from utils.hubspot_client import HubSpotClient
from utils.klaviyo_client import KlaviyoClient


KLAVIYO_LIST_ID = "XMEFhV"
CONTACT_PROPERTIES = ["email", "firstname", "lastname", "do_not_contact", "contact_brand_origin"]

RECENTLY_WELCOMED_SEGMENT_NAME = "TE Recently Welcomed (July2026 Relaunch)"
RECEIVED_EMAIL_METRIC_ID = "QYnTG8"  # "Received Email" internal Klaviyo metric
WELCOME_CAMPAIGN_NAME = "trade-approved_email-01"
RELAUNCH_CUTOFF = "2026-07-14T00:00:00+00:00"

RECENTLY_WELCOMED_CONDITION_GROUPS = [
    {
        "conditions": [
            {
                "type": "profile-metric",
                "metric_id": RECEIVED_EMAIL_METRIC_ID,
                "measurement": "count",
                "measurement_filter": {"type": "numeric", "operator": "greater-than", "value": 0},
                "timeframe_filter": {"type": "date", "operator": "after", "date": RELAUNCH_CUTOFF},
                "metric_filters": [
                    {
                        "property": "Campaign Name",
                        "filter": {"type": "string", "operator": "equals", "value": WELCOME_CAMPAIGN_NAME},
                    }
                ],
            }
        ]
    }
]


def fetch_hubspot_approved(hubspot: HubSpotClient) -> dict[str, dict]:
    """Source A: HubSpot contacts individually approved as trade partners."""
    contacts = hubspot.search_contacts(
        filters=[{"propertyName": "is_trade_partner", "operator": "EQ", "value": "true"}],
        properties=CONTACT_PROPERTIES,
    )
    target: dict[str, dict] = {}
    skipped_no_email = 0
    skipped_dnc = 0
    skipped_brand_origin = 0
    for c in contacts:
        props = c.get("properties") or {}
        email = props.get("email")
        if not email:
            skipped_no_email += 1
            continue
        if props.get("do_not_contact"):
            skipped_dnc += 1
            continue
        if props.get("contact_brand_origin"):
            skipped_brand_origin += 1
            continue
        target[email.lower()] = {
            "email": email,
            "first_name": props.get("firstname") or "",
            "last_name": props.get("lastname") or "",
        }
    print(f"  HubSpot is_trade_partner=true: {len(contacts)} contacts -> "
          f"{len(target)} with usable email (skipped {skipped_no_email} no-email, "
          f"{skipped_dnc} do-not-contact, {skipped_brand_origin} cross-instance brand origin)")
    return target


def fetch_recently_welcomed(klaviyo: KlaviyoClient) -> dict[str, str]:
    """Source B: profiles who've received the relaunch welcome email since 2026-07-14."""
    segment_id = klaviyo.find_list_or_segment_by_name(RECENTLY_WELCOMED_SEGMENT_NAME)
    if not segment_id:
        print(f"  Segment '{RECENTLY_WELCOMED_SEGMENT_NAME}' not found — creating it...")
        segment_id = klaviyo.create_segment(RECENTLY_WELCOMED_SEGMENT_NAME, RECENTLY_WELCOMED_CONDITION_GROUPS)
        if not segment_id:
            print("  Failed to create segment — treating Source B as empty this run.")
            return {}
    members = klaviyo.get_segment_member_emails(segment_id)
    print(f"  Klaviyo segment '{RECENTLY_WELCOMED_SEGMENT_NAME}' ({segment_id}): {len(members)} profiles")
    return members


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--dry-run", action="store_true", help="Show what would change without writing")
    args = parser.parse_args()

    hubspot_key = os.environ.get("HUBSPOT_API_KEY_TE")
    klaviyo_key = os.environ.get("KLAVIYO_API_KEY_TE")
    if not hubspot_key or not klaviyo_key:
        print("Missing HUBSPOT_API_KEY_TE or KLAVIYO_API_KEY_TE in .env")
        sys.exit(1)

    hubspot = HubSpotClient(hubspot_key)
    klaviyo = KlaviyoClient(klaviyo_key, brand="TE")

    print("Fetching Source A: HubSpot individually-approved trade partners...")
    source_a = fetch_hubspot_approved(hubspot)

    print("Fetching Source B: Klaviyo recently-welcomed-since-relaunch profiles...")
    source_b_emails = fetch_recently_welcomed(klaviyo)

    # Merge — Source B only contributes an entry for profiles not already in Source A
    target: dict[str, dict] = dict(source_a)
    added_from_b = 0
    for email in source_b_emails:
        if email not in target:
            target[email] = {"email": email, "first_name": "", "last_name": ""}
            added_from_b += 1
    print(f"Merged target: {len(source_a)} from Source A + {added_from_b} additional from Source B "
          f"= {len(target)} total")

    print(f"Fetching current Klaviyo list {KLAVIYO_LIST_ID} membership...")
    current = klaviyo.get_list_member_emails(KLAVIYO_LIST_ID)
    print(f"  {len(current)} current members")

    to_add_emails = set(target) - set(current)
    to_remove_emails = set(current) - set(target)
    print(f"To add: {len(to_add_emails)} | To remove: {len(to_remove_emails)}")

    # Same consent-safety rule as sync_hubspot_trade_to_klaviyo.py: only check/set
    # consent for profiles newly added THIS run — never the historical backlog.
    to_subscribe: list[dict] = []
    if to_add_emails:
        print(f"Checking email marketing consent for {len(to_add_emails)} newly-added contacts...")
        consent = klaviyo.get_email_marketing_consent(list(to_add_emails))
        skipped_unsub = skipped_sub = 0
        for email in to_add_emails:
            status = consent.get(email)  # None => no profile yet => never subscribed
            if status == "UNSUBSCRIBED":
                skipped_unsub += 1  # respect the opt-out — never re-subscribe
            elif status == "SUBSCRIBED":
                skipped_sub += 1    # already subscribed
            else:                   # NEVER_SUBSCRIBED or brand-new
                to_subscribe.append(target[email])
        print(f"  {len(to_subscribe)} to subscribe | {skipped_sub} already subscribed | "
              f"{skipped_unsub} unsubscribed (left alone)")

    if args.dry_run:
        print("\n--dry-run set, no changes made.")
        for email in sorted(to_add_emails)[:10]:
            print(f"  + list  {email}")
        for email in sorted(to_remove_emails)[:10]:
            print(f"  - list  {email}")
        for info in to_subscribe[:10]:
            print(f"  ~ subscribe  {info['email']}")
        return

    if to_add_emails:
        profiles = [target[email] for email in to_add_emails]
        submitted = klaviyo.bulk_import_profiles_to_list(KLAVIYO_LIST_ID, profiles)
        print(f"Submitted {submitted} profiles to Klaviyo bulk import job.")

    if to_remove_emails:
        profile_ids = [current[email] for email in to_remove_emails]
        removed = klaviyo.remove_profiles_from_list(KLAVIYO_LIST_ID, profile_ids)
        print(f"Removed {removed} profiles from the Klaviyo list.")

    if to_subscribe:
        subscribed = klaviyo.bulk_subscribe_profiles_to_list(
            KLAVIYO_LIST_ID, to_subscribe, custom_source="TE Trade Approved sync"
        )
        print(f"Submitted {subscribed} profiles to email marketing subscription job.")

    print("Sync complete.")


if __name__ == "__main__":
    main()
