"""Google Drive download utility.

Supports two download modes, tried in order:

1. **Authenticated** (preferred): Uses OAuth2 credentials stored in .env
   (GOOGLE_OAUTH_CLIENT_ID, GOOGLE_OAUTH_CLIENT_SECRET, GOOGLE_DRIVE_REFRESH_TOKEN).
   Works for any file the authorized user can access, including files shared only
   within Havenly — no "Anyone with the link" setting required.
   Run scripts/setup_google_drive_auth.py once to set up credentials.

2. **Public link fallback**: Unauthenticated download for files shared as
   "Anyone with the link can view". Used when credentials are absent.

Handles URLs of the form:
  https://drive.google.com/file/d/{FILE_ID}/view?usp=sharing
  https://drive.google.com/open?id={FILE_ID}
"""

import io
import os
import re
import tempfile
from pathlib import Path
from typing import Optional

import requests


def extract_drive_file_id(url: str) -> Optional[str]:
    """Parse the Google Drive file ID from a share URL."""
    m = re.search(r'/file/d/([^/\?&]+)', url)
    if m:
        return m.group(1)
    m = re.search(r'[?&]id=([^&]+)', url)
    if m:
        return m.group(1)
    return None


def extract_drive_folder_id(url: str) -> Optional[str]:
    """Parse the Google Drive folder ID from a folder share URL."""
    m = re.search(r'/drive/folders/([^/?&#]+)', url)
    return m.group(1) if m else None


def list_folder_images(folder_url: str) -> list:
    """List image files in a Google Drive folder.

    Requires OAuth credentials (GOOGLE_DRIVE_REFRESH_TOKEN in .env).
    Returns a list of dicts with 'id', 'name', 'mimeType' for each image.
    Raises RuntimeError if credentials are not configured.
    """
    folder_id = extract_drive_folder_id(folder_url)
    if not folder_id:
        return []

    service = _get_drive_service()
    if service is None:
        raise RuntimeError(
            "Google Drive credentials not configured — set GOOGLE_DRIVE_REFRESH_TOKEN in .env"
        )

    results = service.files().list(
        q=f"'{folder_id}' in parents and mimeType contains 'image/' and trashed=false",
        fields="files(id,name,mimeType)",
    ).execute()
    return results.get("files", [])


def _get_drive_service():
    """Build an authenticated Drive API client from .env credentials.

    Returns None if credentials are not configured.
    """
    client_id = os.getenv("GOOGLE_OAUTH_CLIENT_ID")
    client_secret = os.getenv("GOOGLE_OAUTH_CLIENT_SECRET")
    refresh_token = os.getenv("GOOGLE_DRIVE_REFRESH_TOKEN")

    if not all([client_id, client_secret, refresh_token]):
        return None

    try:
        from google.oauth2.credentials import Credentials
        from googleapiclient.discovery import build

        creds = Credentials(
            token=None,
            refresh_token=refresh_token,
            client_id=client_id,
            client_secret=client_secret,
            token_uri="https://oauth2.googleapis.com/token",
        )
        return build("drive", "v3", credentials=creds, cache_discovery=False)
    except Exception:
        return None


def _mime_to_ext(mime_type: str) -> str:
    return {
        "image/jpeg": ".jpg",
        "image/png": ".png",
        "image/gif": ".gif",
        "image/webp": ".webp",
    }.get(mime_type, ".jpg")


def _download_authenticated(service, file_id: str, dest_path: Optional[str]) -> str:
    """Download a Drive file using an authenticated Drive API service."""
    from googleapiclient.http import MediaIoBaseDownload

    meta = service.files().get(fileId=file_id, fields="name,mimeType").execute()
    fname = meta.get("name", "")
    ext = Path(fname).suffix or _mime_to_ext(meta.get("mimeType", ""))

    if dest_path is None:
        tmp = tempfile.NamedTemporaryFile(suffix=ext, delete=False)
        dest_path = tmp.name
        tmp.close()

    request = service.files().get_media(fileId=file_id)
    buf = io.FileIO(dest_path, mode="wb")
    downloader = MediaIoBaseDownload(buf, request)
    done = False
    while not done:
        _, done = downloader.next_chunk()
    buf.close()

    return dest_path


def download_image(url: str, dest_path: Optional[str] = None) -> str:
    """Download a Google Drive image to a local file.

    Tries authenticated download first (if GOOGLE_DRIVE_REFRESH_TOKEN is in .env),
    then falls back to public-link download for files shared as "Anyone with the link."

    Returns the path to the downloaded file (temp file if dest_path not given).
    Raises ValueError if the file ID cannot be extracted.
    """
    file_id = extract_drive_file_id(url)
    if not file_id:
        raise ValueError(f"Could not extract file ID from Drive URL: {url}")

    service = _get_drive_service()
    if service is not None:
        return _download_authenticated(service, file_id, dest_path)

    return _download_public(file_id, dest_path)


def _download_public(file_id: str, dest_path: Optional[str]) -> str:
    """Download a publicly shared Drive file (no credentials required)."""
    session = requests.Session()
    download_url = f"https://drive.google.com/uc?export=download&id={file_id}"

    response = session.get(download_url, stream=True, timeout=60)
    response.raise_for_status()

    # Google serves a virus-scan confirmation page for larger files.
    # Detect it by Content-Type and re-request with the confirm token.
    content_type = response.headers.get("Content-Type", "")
    if "text/html" in content_type:
        page_text = response.text
        m = re.search(r'confirm=([0-9A-Za-z_\-]+)', page_text)
        if m:
            confirm_token = m.group(1)
        else:
            # Newer Google Drive uses a uuid confirm token in a form action
            m = re.search(r'name="confirm"\s+value="([^"]+)"', page_text)
            confirm_token = m.group(1) if m else "t"

        response = session.get(
            f"https://drive.google.com/uc?export=download&id={file_id}&confirm={confirm_token}",
            stream=True,
            timeout=60,
        )
        response.raise_for_status()

    ext = _guess_extension(response)

    if dest_path is None:
        tmp = tempfile.NamedTemporaryFile(suffix=ext, delete=False)
        dest_path = tmp.name
        tmp.close()

    with open(dest_path, "wb") as f:
        for chunk in response.iter_content(chunk_size=8192):
            if chunk:
                f.write(chunk)

    return dest_path


def _guess_extension(response: requests.Response) -> str:
    """Determine file extension from Content-Disposition or Content-Type."""
    cd = response.headers.get("Content-Disposition", "")
    m = re.search(r'filename[^;=\n]*=[\"\']?([^\"\';]+)', cd)
    if m:
        fname = m.group(1).strip()
        suffix = Path(fname).suffix
        if suffix:
            return suffix

    ct = response.headers.get("Content-Type", "").lower()
    if "jpeg" in ct or "jpg" in ct:
        return ".jpg"
    if "png" in ct:
        return ".png"
    if "gif" in ct:
        return ".gif"
    if "webp" in ct:
        return ".webp"
    return ".jpg"
