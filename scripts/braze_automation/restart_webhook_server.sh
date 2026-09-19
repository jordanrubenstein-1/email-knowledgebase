#!/usr/bin/env bash
# Restart uvicorn webhook server after commits that touch braze_automation code.
# Called by .git/hooks/post-commit — safe to run manually too.
#
# Usage: ./scripts/braze_automation/restart_webhook_server.sh

set -euo pipefail

REPO_ROOT="$(git -C "$(dirname "$0")" rev-parse --show-toplevel)"
LOG=/tmp/webhook-server.log
HEALTH_URL="http://localhost:8765/health"
WAIT_SECS=600  # max seconds to wait for queue to drain (~10 min)

# Only restart if the last commit touched braze_automation files.
CHANGED=$(git diff-tree --no-commit-id -r --name-only HEAD 2>/dev/null || true)
if ! echo "$CHANGED" | grep -q "scripts/braze_automation/"; then
  exit 0
fi

# Detect how the server is deployed. Under launchd the plist sets KeepAlive=true,
# so pkill'ing the process makes launchd respawn it immediately — starting a second
# uvicorn by hand then races it for port 8765 and one of them dies on "address
# already in use". Use launchctl kickstart for that deployment instead.
LAUNCHD_LABEL="com.havenly.webhook-server"
if launchctl list "$LAUNCHD_LABEL" > /dev/null 2>&1; then
  DEPLOY=launchd
elif pgrep -f "uvicorn scripts.braze_automation.webhook_server" > /dev/null 2>&1; then
  DEPLOY=manual
else
  echo "[restart_webhook] server not running — skipping"
  exit 0
fi
echo "[restart_webhook] deployment: $DEPLOY"

echo "[restart_webhook] braze_automation files changed — waiting for queue to drain..."

# Wait for in-flight builds to finish.
ELAPSED=0
while true; do
  DEPTH=$(curl -sf "$HEALTH_URL" 2>/dev/null \
    | python3 -c "import sys,json; print(json.load(sys.stdin).get('queue_depth',0))" 2>/dev/null \
    || echo "0")
  if [ "$DEPTH" = "0" ]; then
    break
  fi
  if [ "$ELAPSED" -ge "$WAIT_SECS" ]; then
    echo "[restart_webhook] WARNING: queue still has $DEPTH job(s) after ${WAIT_SECS}s — restarting anyway"
    break
  fi
  echo "[restart_webhook] queue_depth=$DEPTH — waiting..."
  sleep 5
  ELAPSED=$((ELAPSED + 5))
done

if [ "$DEPLOY" = "launchd" ]; then
  echo "[restart_webhook] kickstarting $LAUNCHD_LABEL..."
  launchctl kickstart -k "gui/$(id -u)/$LAUNCHD_LABEL"
else
  echo "[restart_webhook] stopping uvicorn..."
  pkill -f "uvicorn scripts.braze_automation.webhook_server" || true
  sleep 2

  echo "[restart_webhook] starting uvicorn..."
  cd "$REPO_ROOT"
  nohup uv run uvicorn scripts.braze_automation.webhook_server:app \
    --host 0.0.0.0 --port 8765 >> "$LOG" 2>&1 &
fi

# Wait for the server to come back up.
for i in $(seq 1 15); do
  if curl -sf "$HEALTH_URL" > /dev/null 2>&1; then
    echo "[restart_webhook] server back up (${i}s)"
    exit 0
  fi
  sleep 1
done

echo "[restart_webhook] WARNING: server did not respond after 15s — check $LOG and /tmp/restart-webhook-server.log"
exit 1
