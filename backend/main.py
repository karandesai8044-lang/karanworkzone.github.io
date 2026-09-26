import time
from collections import defaultdict
from pathlib import Path
import sys

BACKEND_DIR = Path(__file__).resolve().parent
if str(BACKEND_DIR) not in sys.path:
    sys.path.insert(0, str(BACKEND_DIR))

from fastapi import FastAPI, Request, HTTPException
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import FileResponse
from fastapi.staticfiles import StaticFiles

import db
from routes import upload, order_status
from jobs.cleanup import start_background_cleanup

app = FastAPI(title="Print Kiosk")

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],  # tighten this to your deployed frontend origin in production
    allow_methods=["*"],
    allow_headers=["*"],
)

# ---- basic per-IP rate limiting on uploads (in-memory; fine for single-shop scale) ----
RATE_LIMIT_WINDOW_SECONDS = 60
RATE_LIMIT_MAX_UPLOADS = 10
_upload_log: dict[str, list[float]] = defaultdict(list)


@app.middleware("http")
async def rate_limit_uploads(request: Request, call_next):
    if request.url.path.startswith("/upload/"):
        ip = request.client.host if request.client else "unknown"
        now = time.time()
        recent = [t for t in _upload_log[ip] if now - t < RATE_LIMIT_WINDOW_SECONDS]
        if len(recent) >= RATE_LIMIT_MAX_UPLOADS:
            raise HTTPException(429, "Too many uploads. Please wait a minute and try again.")
        recent.append(now)
        _upload_log[ip] = recent
    return await call_next(request)


app.include_router(upload.router)
app.include_router(order_status.router)


@app.on_event("startup")
def startup():
    db.init_db()
    start_background_cleanup()


@app.get("/health")
def health():
    return {"ok": True}


# Serve the frontend single-page app
FRONTEND_DIR = Path(__file__).parent.parent / "frontend"
if FRONTEND_DIR.exists():
    app.mount("/static", StaticFiles(directory=FRONTEND_DIR), name="static")

    @app.get("/")
    def index():
        return FileResponse(FRONTEND_DIR / "index.html")
