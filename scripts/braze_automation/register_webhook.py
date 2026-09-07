#!/usr/bin/env python3
"""
Asana Webhook Manager — register, list, and delete Asana webhooks.

IMPORTANT: The webhook server must be running (and ngrok must be active) before
you register. Asana immediately sends a handshake POST to the target URL, and
registration fails if the server doesn't respond within a few seconds.

Usage:
    # Register a new webhook for the Master CRM project
    uv run python scripts/braze_automation/register_webhook.py register \\
        --url https://<your-id>.ngrok-free.dev/webhook/asana

    # List all active webhooks in the workspace
    uv run python scripts/braze_automation/register_webhook.py list

    # Delete a webhook by its GID
    uv run python scripts/braze_automation/register_webhook.py delete --id <webhook_gid>

Workflow:
    1. Start ngrok + server:   bash scripts/braze_automation/start_webhook_service.sh
    2. Register:               uv run python scripts/braze_automation/register_webhook.py register --url <ngrok-url>/webhook/asana
    3. The handshake fires automatically — the server saves the secret to .webhook_secret
    4. Done. The server will now receive Asana task events in real time.
"""

import argparse
import os
import sys
from pathlib import Path

import requests
from dotenv import load_dotenv

PROJECT_ROOT = Path(__file__).parent.parent.parent
load_dotenv(PROJECT_ROOT / ".env")

ASANA_BASE_URL = "https://app.asana.com/api/1.0"
ASANA_PROJECT_GID = "1207522423363072"   # Master CRM (Email & SMS)
ASANA_WORKSPACE_GID = "5257710284167"    # havenly.com workspace


def _headers() -> dict:
    token = os.environ.get("ASANA_ACCESS_TOKEN", "").strip()
    if not token:
        print("ERROR: ASANA_ACCESS_TOKEN not set in .env", file=sys.stderr)
        sys.exit(1)
    return {
        "Authorization": f"Bearer {token}",
        "Content-Type": "application/json",
        "Accept": "application/json",
    }


def cmd_register(url: str) -> None:
    """Register a new webhook on the Master CRM project."""
    print(f"Registering Asana webhook...")
    print(f"  Resource (project): {ASANA_PROJECT_GID}")
    print(f"  Target URL:         {url}")
    print()
    print("NOTE: Your webhook server must be running at that URL right now.")
    print("      Asana will send a handshake request immediately after registration.")
    print()

    payload = {
        "data": {
            "resource": ASANA_PROJECT_GID,
            "target": url,
            "filters": [
                {
                    "resource_type": "task",
                    "action": "changed",
                    "fields": ["custom_fields"],
                },
                {
                    # Capture story (comment) additions for AI feedback loop.
                    # The webhook server checks for "AI feedback:" prefix before logging.
                    "resource_type": "story",
                    "action": "added",
                },
            ],
        }
    }

    resp = requests.post(
        f"{ASANA_BASE_URL}/webhooks",
        headers=_headers(),
        json=payload,
        timeout=30,
    )

    if resp.status_code not in (200, 201):
        print(f"ERROR: Registration failed ({resp.status_code})")
        print(resp.text)
        sys.exit(1)

    data = resp.json().get("data", {})
    webhook_gid = data.get("gid", "")
    active = data.get("active", False)

    print("=" * 60)
    print("WEBHOOK REGISTERED SUCCESSFULLY")
    print("=" * 60)
    print(f"  GID:    {webhook_gid}")
    print(f"  Active: {active}")
    print(f"  Target: {data.get('target', url)}")
    print()

    if not active:
        print("WARNING: Webhook is not yet active — this usually means the handshake")
        print("         failed. Check that your server is running and reachable at:")
        print(f"         {url}")
        print()
        print("         The server saves the secret automatically when the handshake")
        print("         succeeds. Re-register after confirming the server is reachable.")
    else:
        print("The handshake succeeded! Your server has captured and saved the secret.")
        print("Check the server logs — it should show 'WEBHOOK SECRET RECEIVED AND SAVED'.")
        print()
        print("To make the secret permanent (survives server restarts), add to .env:")
        print(f"  ASANA_WEBHOOK_SECRET=<value from server logs or .webhook_secret file>")

    print("=" * 60)


def cmd_list() -> None:
    """List all active webhooks in the workspace."""
    resp = requests.get(
        f"{ASANA_BASE_URL}/webhooks",
        headers=_headers(),
        params={"workspace": ASANA_WORKSPACE_GID},
        timeout=30,
    )

    if resp.status_code != 200:
        print(f"ERROR: Failed to list webhooks ({resp.status_code})")
        print(resp.text)
        sys.exit(1)

    webhooks = resp.json().get("data", [])

    if not webhooks:
        print("No webhooks found in this workspace.")
        return

    print(f"Found {len(webhooks)} webhook(s):\n")
    for wh in webhooks:
        gid = wh.get("gid", "")
        target = wh.get("target", "")
        active = wh.get("active", False)
        resource = wh.get("resource", {})
        resource_gid = resource.get("gid", "")
        resource_name = resource.get("name", "")
        status = "ACTIVE" if active else "INACTIVE"
        print(f"  [{status}] {gid}")
        print(f"    Target:   {target}")
        print(f"    Resource: {resource_name} ({resource_gid})")
        print()


def cmd_delete(webhook_gid: str) -> None:
    """Delete a webhook by GID."""
    print(f"Deleting webhook {webhook_gid}...")

    resp = requests.delete(
        f"{ASANA_BASE_URL}/webhooks/{webhook_gid}",
        headers=_headers(),
        timeout=30,
    )

    if resp.status_code == 200:
        print(f"Webhook {webhook_gid} deleted successfully.")
    elif resp.status_code == 404:
        print(f"Webhook {webhook_gid} not found (already deleted?).")
        sys.exit(1)
    else:
        print(f"ERROR: Delete failed ({resp.status_code})")
        print(resp.text)
        sys.exit(1)


def main() -> None:
    parser = argparse.ArgumentParser(
        description="Manage Asana webhooks for the Master CRM project.",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog=__doc__,
    )
    subparsers = parser.add_subparsers(dest="command", required=True)

    # register
    reg_parser = subparsers.add_parser(
        "register",
        help="Register a new webhook (server must be running first)",
    )
    reg_parser.add_argument(
        "--url",
        required=True,
        help="Public ngrok URL for your webhook server, e.g. https://abc123.ngrok-free.dev/webhook/asana",
    )

    # list
    subparsers.add_parser("list", help="List all webhooks in the workspace")

    # delete
    del_parser = subparsers.add_parser("delete", help="Delete a webhook by GID")
    del_parser.add_argument("--id", required=True, dest="webhook_gid", help="Webhook GID to delete")

    args = parser.parse_args()

    if args.command == "register":
        cmd_register(args.url)
    elif args.command == "list":
        cmd_list()
    elif args.command == "delete":
        cmd_delete(args.webhook_gid)


if __name__ == "__main__":
    main()
