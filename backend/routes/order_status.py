from fastapi import APIRouter, HTTPException
from pathlib import Path
import sys

sys.path.append(str(Path(__file__).parent.parent))
import db

router = APIRouter()


@router.get("/order/{token}/status")
async def get_status(token: str):
    order = db.get_order_by_token(token)
    if not order:
        raise HTTPException(404, "Unknown token")
    return {
        "token": order["token"],
        "module": order["module"],
        "status": order["status"],
        "error_message": order["error_message"],
        "created_at": order["created_at"],
    }


@router.post("/order/{token}/mark-printed")
async def mark_printed(token: str):
    """Called by the print-agent script running on the shop PC once
    SumatraPDF confirms the print job was sent."""
    order = db.get_order_by_token(token)
    if not order:
        raise HTTPException(404, "Unknown token")
    db.update_order(order["id"], status="printed")
    return {"ok": True}
