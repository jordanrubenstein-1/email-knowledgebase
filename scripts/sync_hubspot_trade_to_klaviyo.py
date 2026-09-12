#!/usr/bin/env python3
"""
Sync the HubSpot "All Trade Contacts" list (TE) into the Klaviyo list
"All Trade Members [Hubspot via API]".

Source: HubSpot list 449 (dynamic, filtered on contact property company_type
IS_ANY_OF "Trade Program Partner"/"Expert+TPP", excluding do_not_contact).
Confirmed 2026-07-14 that HubSpot stamps company_type onto every contact
associated with a qualifying company, not just the original applicant — so
list 449 membership alone is the full target audience, no company-association
expansion needed. That inheritance is also why contact_brand_origin matters
below: a contact created by the HubSpot-to-HubSpot instance sync inherits
company_type automatically the moment it is associated with a trade-partner
company, with no other signal that it is not a real trade applicant.

Contacts carrying any value in contact_brand_origin are excluded. That property
marks contacts created by the HubSpot-to-HubSpot instance sync, which must never
be auto-subscribed into Klaviyo marketing. List 449's own filter already gates on
contact_brand_origin IS_UNKNOWN, so this is a redundant second check — kept
deliberately so the skip survives an edit to the list filter, the same
belt-and-braces pattern already used for do_not_contact.

Target: Klaviyo list UF8eu9 ("All Trade Members [Hubspot via API]") in the TE account.

Each run does a full pull + diff: profiles present in the HubSpot list but not
yet in the Klaviyo list are added (via bulk import job); profiles in the
Klaviyo list but no longer in the HubSpot list are removed from the list
(profiles themselves are not deleted).

It then subscribes the contacts it *newly added* this run to email marketing.
List membership alone does NOT grant marketing consent, so the welcome flow
would otherwise skip these profiles at the email step. Only NEVER_SUBSCRIBED
(and brand-new) profiles are subscribed; existing subscribers are left as-is
and profiles that explicitly unsubscribed are never re-subscribed.

This is scoped to each run's new adds only — it does NOT mass-subscribe the
historical backlog of never-subscribed members already on the list. Backfilling
that backlog is a separate, deliberate action, not something this sync does.

Usage:
    uv run python scripts/sync_hubspot_trade_to_klaviyo.py --dry-run
    uv run python scripts/sync_hubspot_trade_to_klaviyo.py
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


HUBSPOT_LIST_ID = "449"
KLAVIYO_LIST_ID = "UF8eu9"
CONTACT_PROPERTIES = ["email", "firstname", "lastname", "do_not_contact", "contact_brand_origin"]


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

    print(f"Fetching HubSpot list {HUBSPOT_LIST_ID} membership...")
    contact_ids = hubspot.get_list_membership_ids(HUBSPOT_LIST_ID)
    print(f"  {len(contact_ids)} contact IDs")

    print("Fetching contact properties...")
    contacts = hubspot.get_contacts_batch(contact_ids, CONTACT_PROPERTIES)

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
    print(f"  {len(target)} contacts with a usable email "
          f"(skipped {skipped_no_email} no-email, {skipped_dnc} do-not-contact, "
          f"{skipped_brand_origin} cross-instance brand origin)")

    print(f"Fetching current Klaviyo list {KLAVIYO_LIST_ID} membership...")
    current = klaviyo.get_list_member_emails(KLAVIYO_LIST_ID)
    print(f"  {len(current)} current members")

    to_add_emails = set(target) - set(current)
    to_remove_emails = set(current) - set(target)
    print(f"To add: {len(to_add_emails)} | To remove: {len(to_remove_emails)}")

    # Being a list member is NOT the same as being subscribed to email marketing.
    # A profile merely added to the list has no marketing consent, so the welcome
    # flow skips it at the email step. For each contact newly added to the list
    # THIS RUN, subscribe it unless it previously unsubscribed.
    #
    # We deliberately scope this to this run's new adds (to_add_emails), NOT the
    # whole target list. That keeps the sync self-maintaining for incoming trade
    # contacts without ever mass-subscribing the historical backlog of
    # never-subscribed members already on the list — those are left as-is.
    # (A one-time backfill of that backlog is a separate, deliberate action.)
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
        subscribed = klaviyo.bulk_subscribe_profiles_to_list(KLAVIYO_LIST_ID, to_subscribe)
        print(f"Subscribed {subscribed} profiles to email marketing.")

    print("Sync complete.")


if __name__ == "__main__":
    main()
