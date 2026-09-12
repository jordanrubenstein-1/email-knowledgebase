#!/usr/bin/env python3
"""
Analyze email addresses of BUR users who triggered Checkout Started in the past year
but haven't received any Braze emails in the past week.

Goal: Identify bot/bad-address patterns before considering adding them to the email list.
"""

import re
import sys
from collections import Counter
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.parent.parent))

from scripts.snowflake_client import get_snowflake_client

DB = "BRAZE_BRAZEWEST_BRAZE_RAW_EVENTS_AWS_US_EAST_1_XJ24206"
SCHEMA = "DATALAKE_SHARING"
BUR_APP_GROUP_ID = "67093a1f24ebbe0065cb9c77"

# --- Known disposable / suspicious email providers ---
DISPOSABLE_DOMAINS = {
    "mailinator.com", "guerrillamail.com", "guerrillamail.net", "guerrillamail.org",
    "guerrillamail.de", "guerrillamail.info", "guerrillamail.biz", "sharklasers.com",
    "guerrillamailblock.com", "grr.la", "spam4.me", "yopmail.com", "yopmail.fr",
    "cool.fr.nf", "jetable.fr.nf", "nospam.ze.tc", "nomail.xl.cx",
    "mega.zik.dj", "speed.1s.fr", "courriel.fr.nf", "moncourrier.fr.nf",
    "monemail.fr.nf", "monmail.fr.nf", "trashmail.com", "trashmail.me",
    "trashmail.net", "trashmail.at", "trashmail.io", "trashmail.org",
    "trashmail.xyz", "spamgourmet.com", "spamgourmet.net", "spamgourmet.org",
    "mailnull.com", "spamfree24.org", "maildrop.cc", "throwam.com",
    "throwaway.email", "dispostable.com", "fakeinbox.com", "filzmail.com",
    "getonemail.com", "mailexpire.com", "mailnew.com", "discard.email",
    "binkmail.com", "bob.email", "clrmail.com", "despam.it",
    "dodgit.com", "emailondeck.com", "jetable.com", "jetable.net",
    "jetable.org", "nomail.xl.cx", "pookmail.com", "safetymail.info",
    "spamdecoy.net", "tempail.com", "tempemail.com", "tempinbox.com",
    "throwam.com", "zoemail.net", "temp-mail.org", "10minutemail.com",
    "10minutemail.net", "20minutemail.com", "tempr.email", "discard.email",
}

ROLE_PREFIXES = {
    "admin", "info", "noreply", "no-reply", "support", "help", "contact",
    "sales", "marketing", "team", "hello", "mail", "postmaster", "abuse",
    "webmaster", "hostmaster", "root", "security", "privacy", "legal",
    "billing", "orders", "shop", "store", "service", "test", "demo",
    "newsletter", "news", "donotreply", "do-not-reply", "unsubscribe",
    "bounce", "spam", "feedback", "careers", "jobs", "press", "media",
    "notifications", "alerts", "system", "bot", "robot",
}


def fetch_emails():
    """Pull emails of Checkout Started users not emailed in past week."""
    print("Connecting to Snowflake Braze datashare...")
    client = get_snowflake_client(schema=SCHEMA, database=DB)

    query = f"""
WITH checkout_users AS (
    -- Users who triggered Checkout Started in the past year
    SELECT DISTINCT USER_ID
    FROM {DB}.{SCHEMA}.USERS_BEHAVIORS_CUSTOMEVENT_SHARED
    WHERE APP_GROUP_ID = '{BUR_APP_GROUP_ID}'
      AND NAME = 'Checkout Started'
      AND TO_TIMESTAMP(TIME) >= DATEADD('day', -365, CURRENT_TIMESTAMP())
),
recent_email_recipients AS (
    -- Users who received at least one email in the past 7 days
    SELECT DISTINCT USER_ID
    FROM {DB}.{SCHEMA}.USERS_MESSAGES_EMAIL_SEND_SHARED
    WHERE APP_GROUP_ID = '{BUR_APP_GROUP_ID}'
      AND TO_TIMESTAMP(TIME) >= DATEADD('day', -7, CURRENT_TIMESTAMP())
),
candidates AS (
    -- Checkout Started users who are NOT recent email recipients
    SELECT cu.USER_ID
    FROM checkout_users cu
    LEFT JOIN recent_email_recipients rer ON cu.USER_ID = rer.USER_ID
    WHERE rer.USER_ID IS NULL
),
user_emails AS (
    -- Get latest email address for each candidate user
    SELECT
        u.USER_ID,
        COALESCE(u.EMAIL, u.EMAIL_ADDRESS) AS email,
        ROW_NUMBER() OVER (PARTITION BY u.USER_ID ORDER BY u.TIME DESC) AS rn
    FROM {DB}.{SCHEMA}.USER_DEFAULT_ATTRIBUTES_VIEW_SHARED u
    INNER JOIN candidates c ON u.USER_ID = c.USER_ID
    WHERE u.APP_GROUP_ID = '{BUR_APP_GROUP_ID}'
      AND COALESCE(u.EMAIL, u.EMAIL_ADDRESS) IS NOT NULL
      AND COALESCE(u.EMAIL, u.EMAIL_ADDRESS) != ''
)
SELECT USER_ID, email
FROM user_emails
WHERE rn = 1
"""

    print("Running query (may take 30-60s)...")
    rows = client.execute_query(query)
    print(f"Fetched {len(rows):,} candidate users with emails")
    return rows


def classify_email(email: str) -> dict:
    """Return a dict of flags for a single email address."""
    email = email.strip().lower()
    flags = {
        "raw": email,
        "valid_format": bool(re.match(r"^[^@\s]+@[^@\s]+\.[^@\s]+$", email)),
        "is_disposable": False,
        "is_role_based": False,
        "has_random_local": False,
        "has_many_numbers": False,
        "suspicious_domain": False,
        "domain": None,
        "local": None,
    }

    if "@" not in email:
        return flags

    local, _, domain = email.partition("@")
    flags["local"] = local
    flags["domain"] = domain

    # Disposable domain check
    if domain in DISPOSABLE_DOMAINS:
        flags["is_disposable"] = True

    # Role-based prefix check
    if local.split("+")[0].split(".")[0] in ROLE_PREFIXES:
        flags["is_role_based"] = True

    # Random-looking local: high entropy, lots of mixed chars, long random strings
    # Heuristic: 8+ consecutive random alphanumeric chars with no vowels or patterns
    if re.search(r"[bcdfghjklmnpqrstvwxyz]{5,}", local):
        flags["has_random_local"] = True

    # Many numbers in local part (> 4 consecutive digits or > 50% digits)
    digits_in_local = sum(c.isdigit() for c in local)
    if len(local) > 0 and (digits_in_local / len(local) > 0.5 or re.search(r"\d{5,}", local)):
        flags["has_many_numbers"] = True

    # Suspicious domain: short TLD unusual patterns, or non-standard TLDs
    tld = domain.split(".")[-1] if "." in domain else ""
    suspicious_tlds = {"xyz", "top", "loan", "click", "download", "gq", "ml", "cf", "tk", "ga"}
    if tld in suspicious_tlds:
        flags["suspicious_domain"] = True

    return flags


def analyze(rows: list[dict]) -> None:
    emails = [r.get("EMAIL") or r.get("email") or "" for r in rows]
    emails = [e for e in emails if e]
    total = len(emails)

    if total == 0:
        print("No emails to analyze.")
        return

    print(f"\n{'='*60}")
    print(f"BW CHECKOUT STARTED — EMAIL BOT PATTERN ANALYSIS")
    print(f"{'='*60}")
    print(f"Total candidate email addresses: {total:,}")

    classified = [classify_email(e) for e in emails]

    # --- Basic validity ---
    invalid_format = [c for c in classified if not c["valid_format"]]
    print(f"\n--- Format Issues ---")
    print(f"  Invalid format: {len(invalid_format):,} ({len(invalid_format)/total:.1%})")
    if invalid_format[:5]:
        for c in invalid_format[:5]:
            print(f"    {c['raw']}")

    # --- Risk buckets ---
    disposable = [c for c in classified if c["is_disposable"]]
    role_based = [c for c in classified if c["is_role_based"]]
    random_local = [c for c in classified if c["has_random_local"]]
    many_numbers = [c for c in classified if c["has_many_numbers"]]
    suspicious_domain = [c for c in classified if c["suspicious_domain"]]

    print(f"\n--- Risk Flags ---")
    print(f"  Disposable domains:    {len(disposable):,} ({len(disposable)/total:.2%})")
    print(f"  Role-based prefixes:   {len(role_based):,} ({len(role_based)/total:.2%})")
    print(f"  Random-looking local:  {len(random_local):,} ({len(random_local)/total:.2%})")
    print(f"  High digit density:    {len(many_numbers):,} ({len(many_numbers)/total:.2%})")
    print(f"  Suspicious TLD:        {len(suspicious_domain):,} ({len(suspicious_domain)/total:.2%})")

    # --- Any-flag summary ---
    any_flag = [
        c for c in classified
        if c["is_disposable"] or c["is_role_based"] or c["has_random_local"]
        or c["has_many_numbers"] or c["suspicious_domain"] or not c["valid_format"]
    ]
    print(f"\n  Total flagged (any risk): {len(any_flag):,} ({len(any_flag)/total:.2%})")
    clean = total - len(any_flag)
    print(f"  Estimated clean:          {clean:,} ({clean/total:.2%})")

    # --- Domain distribution ---
    domains = [c["domain"] for c in classified if c["domain"]]
    domain_counts = Counter(domains)
    print(f"\n--- Top 20 Domains ---")
    for domain, count in domain_counts.most_common(20):
        pct = count / total
        flag = " ⚠" if domain in DISPOSABLE_DOMAINS else ""
        print(f"  {domain:<35} {count:>6,}  ({pct:.1%}){flag}")

    # --- Legit provider breakdown ---
    legit_domains = {"gmail.com", "yahoo.com", "hotmail.com", "outlook.com",
                     "icloud.com", "aol.com", "me.com", "mac.com", "live.com",
                     "msn.com", "comcast.net", "att.net", "verizon.net",
                     "sbcglobal.net", "cox.net", "charter.net", "earthlink.net"}
    legit_count = sum(1 for c in classified if c["domain"] in legit_domains)
    corporate_count = sum(1 for c in classified if c["domain"] and c["domain"] not in legit_domains and "." in c["domain"])
    print(f"\n--- Domain Type Breakdown ---")
    print(f"  Consumer providers (gmail/yahoo/etc): {legit_count:,} ({legit_count/total:.1%})")
    print(f"  Corporate / other domains:            {corporate_count:,} ({corporate_count/total:.1%})")

    # --- Sample disposable ---
    if disposable:
        print(f"\n--- Sample Disposable Addresses (first 10) ---")
        for c in disposable[:10]:
            print(f"  {c['raw']}")

    # --- Sample role-based ---
    if role_based:
        print(f"\n--- Sample Role-Based Addresses (first 10) ---")
        for c in role_based[:10]:
            print(f"  {c['raw']}")

    # --- High-volume single domains (bot indicator) ---
    print(f"\n--- High-Volume Single Domains (>1% of total) ---")
    suspicious_high_vol = [(d, n) for d, n in domain_counts.most_common() if n / total > 0.01]
    if suspicious_high_vol:
        for d, n in suspicious_high_vol:
            print(f"  {d}: {n:,} ({n/total:.1%})")
    else:
        print("  None — good domain distribution")

    # --- Final recommendation ---
    pct_flagged = len(any_flag) / total
    print(f"\n{'='*60}")
    print("SUMMARY & RECOMMENDATION")
    print(f"{'='*60}")
    print(f"  Candidates:    {total:,}")
    print(f"  Flagged:       {len(any_flag):,} ({pct_flagged:.1%})")
    print(f"  Clean:         {clean:,} ({clean/total:.1%})")

    if pct_flagged < 0.05:
        print("\n  ✓ LOW RISK — flag rate under 5%. Safe to proceed with clean segment.")
    elif pct_flagged < 0.15:
        print("\n  ⚠ MODERATE RISK — recommend filtering flagged addresses before sending.")
    else:
        print("\n  ✗ HIGH RISK — >15% flagged. Investigate before any list expansion.")


if __name__ == "__main__":
    rows = fetch_emails()
    analyze(rows)
