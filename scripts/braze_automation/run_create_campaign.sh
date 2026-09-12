#!/usr/bin/env bash
# Run Braze Playwright automation: log in and create a draft email campaign.
# Requires: .env with BRAZE_DASHBOARD_URL, BRAZE_DASHBOARD_EMAIL, BRAZE_DASHBOARD_PASSWORD
#           (and BRAZE_TOTP_SECRET if 2FA is enabled). From repo root: uv run playwright install chromium (once).

set -e
cd "$(dirname "$0")/../.."
uv run python scripts/braze_automation/create_campaign.py \
  --name "${1:-Cursor Test Campaign $(date +%s)}" \
  --subject "${2:-Test subject from automation}" \
  --preheader "${3:-Test preheader}" \
  "${@:4}"
