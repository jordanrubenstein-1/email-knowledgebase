#!/usr/bin/env bash
# =============================================================================
# start_webhook_service.sh — Start ngrok + Asana webhook server together
#
# Usage:
#   bash scripts/braze_automation/start_webhook_service.sh
#
# What this does:
#   1. Starts ngrok tunnel on port 8765 in the background
#   2. Waits for ngrok to be ready, reads the public URL
#   3. Prints the webhook URL and registration command
#   4. Starts the FastAPI webhook server in the foreground
#      (Ctrl-C stops both ngrok and the server)
#
# Prerequisites:
#   brew install ngrok/ngrok/ngrok
#   ngrok config add-authtoken <YOUR_TOKEN>   # one-time, from https://dashboard.ngrok.com
#   uv add fastapi "uvicorn[standard]"
# =============================================================================

set -euo pipefail

# Ensure homebrew binaries are on PATH
export PATH="/opt/homebrew/bin:/usr/local/bin:$PATH"

PORT=8765
SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
PROJECT_ROOT="$(cd "$SCRIPT_DIR/../.." && pwd)"

# ---------------------------------------------------------------------------
# Kill ngrok on exit (Ctrl-C or error)
# ---------------------------------------------------------------------------
NGROK_PID=""
cleanup() {
    if [ -n "$NGROK_PID" ]; then
        echo ""
        echo "Stopping ngrok (pid $NGROK_PID)..."
        kill "$NGROK_PID" 2>/dev/null || true
    fi
}
trap cleanup EXIT

# ---------------------------------------------------------------------------
# 1. Start ngrok
# ---------------------------------------------------------------------------
echo "Starting ngrok tunnel on port $PORT..."
ngrok http "$PORT" --log=stdout > /tmp/ngrok-webhook.log 2>&1 &
NGROK_PID=$!

# ---------------------------------------------------------------------------
# 2. Wait for ngrok to report its public URL (via local API on port 4040)
# ---------------------------------------------------------------------------
PUBLIC_URL=""
for i in $(seq 1 15); do
    PUBLIC_URL=$(
        curl -s http://127.0.0.1:4040/api/tunnels 2>/dev/null \
        | python3 -c "
import sys, json
try:
    d = json.load(sys.stdin)
    tunnels = d.get('tunnels', [])
    https = [t for t in tunnels if t.get('proto') == 'https']
    print((https or tunnels)[0]['public_url'])
except Exception:
    pass
" 2>/dev/null || true
    )
    if [ -n "$PUBLIC_URL" ]; then
        break
    fi
    sleep 1
done

if [ -z "$PUBLIC_URL" ]; then
    echo ""
    echo "ERROR: ngrok did not start within 15 seconds."
    echo "       Check /tmp/ngrok-webhook.log for details."
    exit 1
fi

# ---------------------------------------------------------------------------
# 3. Print instructions
# ---------------------------------------------------------------------------
WEBHOOK_URL="$PUBLIC_URL/webhook/asana"

echo ""
echo "============================================================"
echo " ngrok is running!"
echo ""
echo " Webhook URL:"
echo "   $WEBHOOK_URL"
echo ""
echo " If this is a new ngrok URL (or first time), register it:"
echo "   uv run python scripts/braze_automation/register_webhook.py register \\"
echo "     --url $WEBHOOK_URL"
echo ""
echo " To list existing webhooks:"
echo "   uv run python scripts/braze_automation/register_webhook.py list"
echo ""
echo " Health check (confirms server is reachable):"
echo "   curl $PUBLIC_URL/health"
echo "============================================================"
echo ""

# ---------------------------------------------------------------------------
# 4. Start the FastAPI webhook server (foreground — Ctrl-C to stop)
# ---------------------------------------------------------------------------
echo "Starting webhook server on port $PORT..."
echo "(Ctrl-C to stop both server and ngrok)"
echo ""

cd "$PROJECT_ROOT"
uv run uvicorn scripts.braze_automation.webhook_server:app \
    --host 0.0.0.0 \
    --port "$PORT"
