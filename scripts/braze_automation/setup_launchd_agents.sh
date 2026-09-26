#!/usr/bin/env bash
# =============================================================================
# setup_launchd_agents.sh — install the 6 com.havenly.* launchd services on
# THIS machine, for THIS user.
#
# Jordan's original plists hardcode /Users/jordan.rubenstein/... paths, so
# they can't be copied to another machine as-is. This script regenerates all
# six from templates, filling in:
#   - $HOME              (this user's home directory)
#   - the repo root       (resolved from this script's own location)
#   - the absolute path to `uv`  (resolved via `command -v uv`, since it
#                                  varies by machine — Homebrew, .local/bin,
#                                  pyenv, etc.)
#
# Usage:
#   bash scripts/braze_automation/setup_launchd_agents.sh
#
# Safe to re-run any time (e.g. after moving the repo to a new path, or after
# switching `uv` installs) — it overwrites the plists and reloads them.
#
# See docs/automation/MOVING_LOCAL_PIPELINE.md for the full handoff runbook
# this script is one step of.
# =============================================================================

set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
REPO_ROOT="$(cd "$SCRIPT_DIR/../.." && pwd)"
AGENTS_DIR="$HOME/Library/LaunchAgents"

UV_PATH="$(command -v uv || true)"
if [ -z "$UV_PATH" ]; then
    echo "ERROR: 'uv' not found on PATH. Install it first (see README) then re-run." >&2
    exit 1
fi

NGROK_PATH="$(command -v ngrok || true)"
if [ -z "$NGROK_PATH" ]; then
    echo "WARNING: 'ngrok' not found on PATH — com.havenly.ngrok-webhook will fail to start."
    echo "         Install with: brew install ngrok/ngrok/ngrok"
    NGROK_PATH="/opt/homebrew/bin/ngrok"  # written anyway; fix path once installed
fi

mkdir -p "$AGENTS_DIR"

echo "Repo root:  $REPO_ROOT"
echo "uv path:    $UV_PATH"
echo "ngrok path: $NGROK_PATH"
echo "Agents dir: $AGENTS_DIR"
echo ""

write_plist() {
    local label="$1"
    local body="$2"
    local path="$AGENTS_DIR/${label}.plist"
    cat > "$path" <<PLIST
<?xml version="1.0" encoding="UTF-8"?>
<!DOCTYPE plist PUBLIC "-//Apple//DTD PLIST 1.0//EN" "http://www.apple.com/DTDs/PropertyList-1.0.dtd">
<plist version="1.0">
<dict>
    <key>Label</key>
    <string>${label}</string>
${body}
</dict>
</plist>
PLIST
    echo "  wrote $path"
}

# ---------------------------------------------------------------------------
# 1. webhook-server — FastAPI server, always-on, restarted by launchd if it dies
# ---------------------------------------------------------------------------
write_plist "com.havenly.webhook-server" "$(cat <<BODY
    <key>ProgramArguments</key>
    <array>
        <string>${UV_PATH}</string>
        <string>run</string>
        <string>uvicorn</string>
        <string>scripts.braze_automation.webhook_server:app</string>
        <string>--host</string>
        <string>0.0.0.0</string>
        <string>--port</string>
        <string>8765</string>
    </array>
    <key>WorkingDirectory</key>
    <string>${REPO_ROOT}</string>
    <key>RunAtLoad</key>
    <true/>
    <key>KeepAlive</key>
    <true/>
    <key>StandardOutPath</key>
    <string>/tmp/webhook-server.log</string>
    <key>StandardErrorPath</key>
    <string>/tmp/webhook-server.log</string>
BODY
)"

# ---------------------------------------------------------------------------
# 2. ngrok-webhook — tunnel port 8765 to the public internet (free tier, no
#    reserved domain; ensure-registered handles URL changes)
# ---------------------------------------------------------------------------
write_plist "com.havenly.ngrok-webhook" "$(cat <<BODY
    <key>ProgramArguments</key>
    <array>
        <string>${NGROK_PATH}</string>
        <string>http</string>
        <string>8765</string>
        <string>--log=stdout</string>
    </array>
    <key>RunAtLoad</key>
    <true/>
    <key>KeepAlive</key>
    <true/>
    <key>StandardOutPath</key>
    <string>/tmp/ngrok-webhook.log</string>
    <key>StandardErrorPath</key>
    <string>/tmp/ngrok-webhook.log</string>
BODY
)"

# ---------------------------------------------------------------------------
# 3. webhook-ensure-registered — re-point the Asana webhook at ngrok's
#    current URL; at login + hourly, since the free ngrok URL isn't static
# ---------------------------------------------------------------------------
write_plist "com.havenly.webhook-ensure-registered" "$(cat <<BODY
    <key>ProgramArguments</key>
    <array>
        <string>${UV_PATH}</string>
        <string>run</string>
        <string>python</string>
        <string>scripts/braze_automation/ensure_webhook_registered.py</string>
    </array>
    <key>WorkingDirectory</key>
    <string>${REPO_ROOT}</string>
    <key>RunAtLoad</key>
    <true/>
    <key>StartInterval</key>
    <integer>3600</integer>
    <key>StandardOutPath</key>
    <string>/tmp/webhook-ensure-registered.log</string>
    <key>StandardErrorPath</key>
    <string>/tmp/webhook-ensure-registered.log</string>
BODY
)"

# ---------------------------------------------------------------------------
# 4. poll-ready-tasks — 15-min safety-net poller
# ---------------------------------------------------------------------------
write_plist "com.havenly.poll-ready-tasks" "$(cat <<BODY
    <key>ProgramArguments</key>
    <array>
        <string>${UV_PATH}</string>
        <string>run</string>
        <string>python</string>
        <string>scripts/braze_automation/poll_ready_tasks.py</string>
    </array>
    <key>WorkingDirectory</key>
    <string>${REPO_ROOT}</string>
    <key>RunAtLoad</key>
    <false/>
    <key>StartInterval</key>
    <integer>900</integer>
    <key>StandardOutPath</key>
    <string>/tmp/poll-ready-tasks.log</string>
    <key>StandardErrorPath</key>
    <string>/tmp/poll-ready-tasks.log</string>
BODY
)"

# ---------------------------------------------------------------------------
# 5. braze-session-refresh — daily 8am, re-logs the Braze bot account in
# ---------------------------------------------------------------------------
write_plist "com.havenly.braze-session-refresh" "$(cat <<BODY
    <key>ProgramArguments</key>
    <array>
        <string>${UV_PATH}</string>
        <string>run</string>
        <string>python</string>
        <string>scripts/braze_automation/refresh_session.py</string>
    </array>
    <key>WorkingDirectory</key>
    <string>${REPO_ROOT}</string>
    <key>StartCalendarInterval</key>
    <dict>
        <key>Hour</key>
        <integer>8</integer>
        <key>Minute</key>
        <integer>0</integer>
    </dict>
    <key>StandardOutPath</key>
    <string>/tmp/braze-session-refresh.log</string>
    <key>StandardErrorPath</key>
    <string>/tmp/braze-session-refresh.log</string>
BODY
)"

# ---------------------------------------------------------------------------
# 6. notify-lee-completions — Slack alert, unrelated to Braze login,
#    brand-agnostic; every 10 min
# ---------------------------------------------------------------------------
write_plist "com.havenly.notify-lee-completions" "$(cat <<BODY
    <key>ProgramArguments</key>
    <array>
        <string>${UV_PATH}</string>
        <string>run</string>
        <string>python</string>
        <string>scripts/braze_automation/notify_lee_task_completions.py</string>
    </array>
    <key>WorkingDirectory</key>
    <string>${REPO_ROOT}</string>
    <key>RunAtLoad</key>
    <false/>
    <key>StartInterval</key>
    <integer>600</integer>
    <key>StandardOutPath</key>
    <string>/tmp/notify-lee-completions.log</string>
    <key>StandardErrorPath</key>
    <string>/tmp/notify-lee-completions.log</string>
BODY
)"

echo ""
echo "Loading services via launchctl..."
for label in webhook-server ngrok-webhook webhook-ensure-registered poll-ready-tasks braze-session-refresh notify-lee-completions; do
    plist="$AGENTS_DIR/com.havenly.${label}.plist"
    launchctl bootout "gui/$(id -u)/com.havenly.${label}" 2>/dev/null || true
    launchctl bootstrap "gui/$(id -u)" "$plist"
    echo "  loaded com.havenly.${label}"
done

echo ""
echo "Done. Verify with:"
echo "  launchctl list | grep havenly"
echo "  curl -sf http://localhost:8765/health"
