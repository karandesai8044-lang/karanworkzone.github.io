# Print Kiosk — QR-based auto-print for local Xerox/print shops

Customer scans a QR code at the counter → uploads a document / ID card / photo
from their phone → it auto-prints on the shop's printer. No USB, no manual
file handling.

## How it's wired together

```
Customer's phone (frontend)
      │  upload
      ▼
Backend (FastAPI, hosted on Render/Railway)
      │  converts file → print-ready PDF, saves order in SQLite
      │  uploads PDF to a shared Google Drive folder (service account)
      ▼
Google Drive
      │  synced locally by Google Drive for Desktop on the shop PC
      ▼
print-agent/watcher.py (runs on the shop PC)
      │  detects new file → sends to printer via SumatraPDF -silent
      │  calls backend to mark the order "printed" → deletes local + Drive copy
      ▼
Customer's status page updates to "printed" automatically (polling)
```

## Project layout

```
backend/          FastAPI app, SQLite DB, file processing, Drive bridge, cleanup job
frontend/         Single-page mobile-first web app (plain HTML/JS)
print-agent/      Script that runs on the shop's Windows PC only
```

## 1. First-time setup

### Backend
```bash
cd backend
python -m venv venv && source venv/bin/activate   # Windows: venv\Scripts\activate
pip install -r requirements.txt
```
You also need **LibreOffice** installed with `soffice` on PATH, for DOCX/PPTX/XLSX → PDF conversion.

### Google Drive bridge (do this before testing uploads)
1. Create a Google Cloud project → enable the **Drive API**.
2. Create a **service account** → generate a JSON key → save it as `backend/service-account.json` (never commit this file).
3. In Google Drive, create one folder, e.g. "PrintKioskQueue" → share it with the service account's email address (found inside the JSON key) with **Editor** access.
4. Copy that folder's ID (from its URL) into an environment variable:
   ```bash
   export DRIVE_FOLDER_ID="your_folder_id_here"
   ```
5. On the **shop PC**: install Google Drive for Desktop, sign in with a Google account that has access to that same folder, so it syncs locally. Note the local synced path — you'll need it in `print-agent/config.py`.

### Run the backend locally
```bash
cd backend
uvicorn main:app --reload --port 8000
```
Open `http://localhost:8000` — the frontend is served automatically.

### Print agent (on the shop PC only)
```bash
cd print-agent
python -m venv venv && venv\Scripts\activate
pip install -r requirements.txt
```
1. Install [SumatraPDF](https://www.sumatrapdfreader.org/) (portable exe is fine).
2. Edit `config.py`: set `PRINTER_NAME` exactly as it appears in Windows "Devices and Printers", `SYNCED_FOLDER_PATH` to the Google Drive synced folder, `SUMATRA_PATH`, and `BACKEND_URL` (your deployed backend URL once hosted).
3. Run: `python watcher.py`
4. Once confirmed working, register it to run on Windows startup via **Task Scheduler** (Trigger: "At log on", Action: run `pythonw.exe path\to\watcher.py`) so it survives reboots.

## 2. Test the pipeline before building on top of it

This is the highest-risk part of the whole system — test it in isolation first:
1. Start the backend locally.
2. Manually `POST` a dummy PDF to `/upload/document` (e.g. with `curl` or the frontend).
3. Confirm the file lands in the shared Drive folder from the Drive web UI.
4. Confirm Google Drive for Desktop syncs it down to the shop PC.
5. Confirm `watcher.py` picks it up and sends it to the printer.
6. Confirm the order status flips to `printed` at `/order/{token}/status`.
7. Confirm the local file and Drive file are both deleted afterward.

Only once this loop works end-to-end should you rely on the three module UIs.

## 3. Deploying

- **Backend + frontend**: push `backend/` and `frontend/` to Render or Railway free tier. Set the `DRIVE_FOLDER_ID` env var and upload `service-account.json` as a secret file there — do not commit it to git.
- Update `print-agent/config.py`'s `BACKEND_URL` to the deployed URL.
- Print a QR code pointing at your deployed URL and stick it at the shop counter.

## 4. Known things to verify before going live

- **SumatraPDF CLI flags** for copies / page-range / color (`-print-settings`) — confirm the exact current syntax against SumatraPDF's own docs; flag names have shifted across versions. `document.py`'s `build_print_settings()` stores the intent; `watcher.py` is where you wire it into the actual command.
- **PAN card / Voter ID photo dimensions** in `backend/processing/photo.py`'s `SIZE_PRESETS` are marked as placeholders — verify against current UTIITSL/NSDL and ECI specs before shipping.
- The DOCX/PPTX/XLSX detection in `convert.py` currently disambiguates zip-based Office files by file extension (a full check would inspect the zip's internal `[Content_Types].xml`) — documented simplification, fine for MVP but spoofable by a malicious extension rename combined with a valid zip signature.
- WhatsApp notifications (Twilio) were intentionally left out — the polling status page is the free MVP notification method, per the brief.

## 5. Security already built in

- File type allowlist by magic bytes, not extension (`convert.py`)
- 20MB upload cap
- Per-IP rate limiting on uploads (`main.py`)
- Random, non-sequential order tokens (`db.py`)
- Auto-delete of files (local temp, Drive) after 2 hours, background job (`jobs/cleanup.py`)
