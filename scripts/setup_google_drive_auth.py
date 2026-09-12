"""One-time script to authorize Google Drive access and store credentials in .env.

Run this once after setting up a Google Cloud OAuth 2.0 Desktop App credential:

    uv run python scripts/setup_google_drive_auth.py ~/Downloads/client_secret_xxx.json

This opens a browser where you log in with your Havenly Google account and grant
Drive read access. The refresh token is written to .env and persists indefinitely
(as long as the OAuth consent screen is set to Internal in Google Cloud Console).

After running this, drive_client.py will automatically use your credentials to
download any Drive file you have access to — including files shared only within
Havenly, with no "Anyone with link" requirement.
"""

import sys
from pathlib import Path

from dotenv import find_dotenv, set_key
from google_auth_oauthlib.flow import InstalledAppFlow

SCOPES = ["https://www.googleapis.com/auth/drive.readonly"]


def main():
    secrets_path = sys.argv[1] if len(sys.argv) > 1 else "client_secrets.json"

    if not Path(secrets_path).exists():
        print(f"Error: client secrets file not found: {secrets_path}")
        print()
        print("To get this file:")
        print("  1. Go to console.cloud.google.com")
        print("  2. Enable the Google Drive API for your project")
        print("  3. Go to Credentials → Create OAuth 2.0 Client ID → Desktop app")
        print("  4. Download the JSON file and pass its path to this script")
        print()
        print("Important: set OAuth consent screen to 'Internal' so tokens don't expire.")
        sys.exit(1)

    print("Opening browser for Google authorization...")
    print("Log in with your Havenly Google account and click Allow.")
    print()

    flow = InstalledAppFlow.from_client_secrets_file(secrets_path, SCOPES)
    creds = flow.run_local_server(port=0)

    env_path = find_dotenv()
    if not env_path:
        env_path = ".env"

    set_key(env_path, "GOOGLE_OAUTH_CLIENT_ID", creds.client_id)
    set_key(env_path, "GOOGLE_OAUTH_CLIENT_SECRET", creds.client_secret)
    set_key(env_path, "GOOGLE_DRIVE_REFRESH_TOKEN", creds.refresh_token)

    print()
    print("Credentials written to .env:")
    print(f"  GOOGLE_OAUTH_CLIENT_ID = {creds.client_id[:20]}...")
    print(f"  GOOGLE_OAUTH_CLIENT_SECRET = {creds.client_secret[:8]}...")
    print(f"  GOOGLE_DRIVE_REFRESH_TOKEN = {creds.refresh_token[:20]}...")
    print()
    print("Done. drive_client.py will now use these credentials automatically.")
    print("You can delete the client secrets JSON file — it's no longer needed.")


if __name__ == "__main__":
    main()
