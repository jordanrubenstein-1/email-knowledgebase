---
name: ngrok + webhook service setup
description: How to start the Asana webhook service (ngrok + uvicorn) when user says "restart ngrok" or "get ngrok running"
type: project
---

When the user says "restart ngrok", "get ngrok running", or similar:

1. Start ngrok on port 8765 in the background:
   `/opt/homebrew/bin/ngrok http 8765 --log=stdout > /tmp/ngrok-webhook.log 2>&1 &`

2. Wait ~4 seconds, then get the public URL:
   `curl -s http://127.0.0.1:4040/api/tunnels`

3. Start the uvicorn webhook server in the background (from project root):
   `uv run uvicorn scripts.braze_automation.webhook_server:app --host 0.0.0.0 --port 8765 > /tmp/webhook-server.log 2>&1 &`

4. Confirm health: `curl -s http://localhost:8765/health`

5. Check the Asana webhook registration still points to the new ngrok URL:
   `uv run python scripts/braze_automation/register_webhook.py list`

6. If the registered URL doesn't match the new ngrok URL, re-register:
   `uv run python scripts/braze_automation/register_webhook.py register --url <new-ngrok-url>/webhook/asana`

Notes:
- ngrok binary is at `/opt/homebrew/bin/ngrok` (not on PATH by default)
- Webhook server listens on port 8765
- Webhook endpoint: `/webhook/asana`
- The ngrok account appears to reuse the same URL (`deafly-nondemocratical-theresa.ngrok-free.dev`), so re-registration is often not needed

## If builds fail with a login/session error
Run the session refresh script (uses .env credentials, no manual login needed):
```
uv run python scripts/braze_automation/refresh_session.py
```
Then retry the builds.
