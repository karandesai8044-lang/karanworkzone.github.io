"""
Thin wrapper around the Google Drive API for pushing print-ready PDFs into
the shared folder that the shop PC's Google Drive Desktop app syncs.

Setup (see README):
  1. Create a Google Cloud project, enable the Drive API
  2. Create a service account, download its JSON key -> save as
     backend/service-account.json (gitignored, never commit this)
  3. Create a Drive folder, share it with the service account's email
     (Editor access), copy its folder ID into DRIVE_FOLDER_ID below or env var
  4. On the shop PC: install Google Drive for Desktop, sign in as the account
     that owns that folder, so it syncs locally
"""

import os
from pathlib import Path

from google_auth_oauthlib.flow import InstalledAppFlow
from google.oauth2.credentials import Credentials
from google.auth.transport.requests import Request
from googleapiclient.discovery import build
from googleapiclient.http import MediaFileUpload

OAUTH_CLIENT_FILE = Path(__file__).parent / "client_secret.json"
OAUTH_TOKEN_FILE = Path(__file__).parent / "token.json"
DRIVE_FOLDER_ID = os.environ.get("DRIVE_FOLDER_ID", "")  # set this once the folder is created
SCOPES = ["https://www.googleapis.com/auth/drive"]

_service = None


def _get_service():
    global _service
    if _service is None:
        creds = None
        if OAUTH_TOKEN_FILE.exists():
            creds = Credentials.from_authorized_user_file(str(OAUTH_TOKEN_FILE), SCOPES)
        if creds and creds.expired and creds.refresh_token:
            creds.refresh(Request())
            OAUTH_TOKEN_FILE.write_text(creds.to_json(), encoding="utf-8")
        if not creds or not creds.valid:
            if not OAUTH_CLIENT_FILE.exists():
                raise RuntimeError(
                    "client_secret.json not found. Download a Desktop OAuth client "
                    "from Google Cloud and save it as backend/client_secret.json."
                )
            flow = InstalledAppFlow.from_client_secrets_file(str(OAUTH_CLIENT_FILE), SCOPES)
            creds = flow.run_local_server(port=0)
            OAUTH_TOKEN_FILE.write_text(creds.to_json(), encoding="utf-8")
        
        if not creds:
            raise RuntimeError(
                "Google Drive authorization could not be initialized."
            )
        _service = build("drive", "v3", credentials=creds)
    return _service


def upload_pdf(local_path: Path, drive_filename: str) -> str:
    """Uploads local_path into DRIVE_FOLDER_ID, returns the Drive file ID."""
    if not DRIVE_FOLDER_ID:
        raise RuntimeError("DRIVE_FOLDER_ID environment variable is not set")

    service = _get_service()
    file_metadata = {"name": drive_filename, "parents": [DRIVE_FOLDER_ID]}
    media = MediaFileUpload(str(local_path), mimetype="application/pdf", resumable=False)
    created = service.files().create(body=file_metadata, media_body=media, fields="id").execute()
    return created["id"]


def delete_file(drive_file_id: str) -> None:
    service = _get_service()
    try:
        service.files().delete(fileId=drive_file_id).execute()
    except Exception:
        pass  # already gone, or permission race — cleanup job will retry via local watcher side
