from fastapi import APIRouter, UploadFile, File, Form, HTTPException
from pathlib import Path
import sys

sys.path.append(str(Path(__file__).parent.parent))

import db
import drive_bridge
from processing.convert import to_print_ready_pdf, UnsupportedFileError
from processing.document import build_print_settings
from processing.id_card import compose_id_card_sheet
from processing.photo import process_passport_photo

router = APIRouter()


@router.post("/upload/document")
async def upload_document(
    file: UploadFile = File(...),
    copies: int = Form(1),
    color: bool = Form(False),
    page_range: str = Form(""),
    orientation: str = Form("portrait"),
):
    try:
        settings = build_print_settings(copies, color, page_range, orientation)
    except ValueError as e:
        raise HTTPException(400, str(e))

    order = db.create_order("document", copies=copies, settings=settings)
    try:
        raw = await file.read()
        pdf_path = to_print_ready_pdf(raw, file.filename)
        db.update_order(order["id"], status="converting", file_path=str(pdf_path))
        drive_id = drive_bridge.upload_pdf(pdf_path, f"{order['token']}.pdf")
        db.update_order(order["id"], status="queued", drive_file_id=drive_id)
    except UnsupportedFileError as e:
        db.update_order(order["id"], status="error", error_message=str(e))
        raise HTTPException(400, str(e))
    except Exception as e:
        db.update_order(order["id"], status="error", error_message=str(e))
        raise HTTPException(500, "Processing failed. See order status for details.")

    return {"token": order["token"], "status": "queued"}


@router.post("/upload/id_card")
async def upload_id_card(front: UploadFile = File(...), back: UploadFile = File(...)):
    order = db.create_order("id_card", copies=1, settings={})
    try:
        front_bytes, back_bytes = await front.read(), await back.read()
        from processing.id_card import TEMP_DIR
        import uuid
        f_path = TEMP_DIR / f"{uuid.uuid4()}_front"
        b_path = TEMP_DIR / f"{uuid.uuid4()}_back"
        f_path.write_bytes(front_bytes)
        b_path.write_bytes(back_bytes)

        pdf_path = compose_id_card_sheet(f_path, b_path)
        db.update_order(order["id"], status="converting", file_path=str(pdf_path))
        drive_id = drive_bridge.upload_pdf(pdf_path, f"{order['token']}.pdf")
        db.update_order(order["id"], status="queued", drive_file_id=drive_id)
    except Exception as e:
        db.update_order(order["id"], status="error", error_message=str(e))
        raise HTTPException(500, "Processing failed. See order status for details.")

    return {"token": order["token"], "status": "queued"}


@router.post("/upload/photo")
async def upload_photo(
    file: UploadFile = File(...),
    preset: str = Form("indian_passport"),
    bg_color: str = Form("white"),
    copies: int = Form(8),
    custom_width_mm: str | None = Form(None),
    custom_height_mm: str | None = Form(None),
):
    custom_mm = None
    if preset == "custom":
        if not custom_width_mm or not custom_height_mm:
            raise HTTPException(400, "Custom width and height are required")
        try:
            custom_mm = (float(custom_width_mm), float(custom_height_mm))
        except ValueError:
            raise HTTPException(400, "Custom width and height must be valid numbers")
    order = db.create_order("photo", copies=copies, settings={"preset": preset, "bg_color": bg_color})
    try:
        raw = await file.read()
        pdf_path = process_passport_photo(raw, preset, bg_color, copies, custom_mm)
        db.update_order(order["id"], status="converting", file_path=str(pdf_path))
        drive_id = drive_bridge.upload_pdf(pdf_path, f"{order['token']}.pdf")
        db.update_order(order["id"], status="queued", drive_file_id=drive_id)
    except ValueError as e:
        db.update_order(order["id"], status="error", error_message=str(e))
        raise HTTPException(400, str(e))
    except Exception as e:
        db.update_order(order["id"], status="error", error_message=str(e))
        raise HTTPException(500, "Processing failed. See order status for details.")

    return {"token": order["token"], "status": "queued"}
