"""
Runs every CLEANUP_INTERVAL_SECONDS in a background thread started from
main.py. Deletes any order's local temp file + its Drive copy once it's
older than RETENTION_SECONDS, and marks the DB row 'expired'.

Sensitive documents (ID cards, photos) must never persist longer than this
window on the backend, in Drive, or (by extension, once the local watcher
deletes its copy after printing) on the shop PC.
"""

import logging
import threading
import time
from pathlib import Path

import sys
sys.path.append(str(Path(__file__).parent.parent))

import db
import drive_bridge

RETENTION_SECONDS = 2 * 60 * 60      # 2 hours
CLEANUP_INTERVAL_SECONDS = 20 * 60   # run every 20 minutes

logger = logging.getLogger("cleanup")


def run_cleanup_once():
    candidates = db.get_expired_candidates(RETENTION_SECONDS)
    for order in candidates:
        file_path = order.get("file_path")
        if file_path:
            p = Path(file_path)
            if p.exists():
                try:
                    p.unlink()
                except OSError as e:
                    logger.warning("Could not delete local file %s: %s", p, e)

        drive_id = order.get("drive_file_id")
        if drive_id:
            try:
                drive_bridge.delete_file(drive_id)
            except Exception as e:
                logger.warning("Could not delete Drive file %s: %s", drive_id, e)

        db.update_order(order["id"], status="expired")
        logger.info("Expired order %s (token %s)", order["id"], order["token"])


def _loop():
    while True:
        try:
            run_cleanup_once()
        except Exception:
            logger.exception("Cleanup pass failed")
        time.sleep(CLEANUP_INTERVAL_SECONDS)


def start_background_cleanup():
    thread = threading.Thread(target=_loop, daemon=True)
    thread.start()
    return thread
