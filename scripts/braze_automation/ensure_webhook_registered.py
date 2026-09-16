"""
Runs at login (via launchd) to ensure the Asana webhook points at the current ngrok URL.
Waits for ngrok + webhook server to be ready, then checks/re-registers as needed.
"""

import json
import subprocess
import sys
import time
from pathlib import Path

import requests

PROJECT_ROOT = Path(__file__).parent.parent.parent
MAX_WAIT_SECONDS = 60
POLL_INTERVAL = 3


def get_ngrok_url(timeout=MAX_WAIT_SECONDS):
    print(f"Waiting for ngrok (up to {timeout}s)...")
    deadline = time.time() + timeout
    while time.time() < deadline:
        try:
            r = requests.get("http://127.0.0.1:4040/api/tunnels", timeout=2)
            tunnels = r.json().get("tunnels", [])
            if tunnels:
                url = tunnels[0]["public_url"]
                print(f"ngrok URL: {url}")
                return url
        except Exception:
            pass
        time.sleep(POLL_INTERVAL)
    print("ERROR: ngrok did not start in time")
    return None


def wait_for_webhook_server(timeout=MAX_WAIT_SECONDS):
    print(f"Waiting for webhook server (up to {timeout}s)...")
    deadline = time.time() + timeout
    while time.time() < deadline:
        try:
            r = requests.get("http://localhost:8765/health", timeout=2)
            if r.json().get("status") == "ok":
                print("Webhook server is healthy")
                return True
        except Exception:
            pass
        time.sleep(POLL_INTERVAL)
    print("ERROR: webhook server did not start in time")
    return False


UV = "/Users/jordan.rubenstein/.local/bin/uv"


def run_register_script(args):
    result = subprocess.run(
        [UV, "run", "python", "scripts/braze_automation/register_webhook.py"] + args,
        cwd=PROJECT_ROOT,
        capture_output=True,
        text=True,
    )
    return result.stdout + result.stderr


def main():
    ngrok_url = get_ngrok_url()
    if not ngrok_url:
        sys.exit(1)

    if not wait_for_webhook_server():
        sys.exit(1)

    # Check current registration
    print("Checking Asana webhook registration...")
    list_output = run_register_script(["list"])
    print(list_output)

    target_url = f"{ngrok_url}/webhook/asana"

    if target_url in list_output:
        print(f"Webhook already points at {target_url} — nothing to do")
    else:
        print(f"Webhook URL mismatch or not registered — re-registering to {target_url}")
        register_output = run_register_script(["register", "--url", target_url])
        print(register_output)
        if "REGISTERED SUCCESSFULLY" in register_output:
            print("Re-registration succeeded")
        else:
            print("ERROR: re-registration may have failed — check output above")
            sys.exit(1)


if __name__ == "__main__":
    main()
