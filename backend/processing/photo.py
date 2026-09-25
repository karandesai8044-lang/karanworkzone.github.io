"""
Module 3: passport-size photo. Pipeline:
  1. rembg removes the background
  2. composite onto a solid color (white / light blue)
  3. mediapipe finds the face and we crop/center to the target ratio
  4. resize to the preset mm dimensions
  5. tile N copies onto one print sheet with cut-guide lines
"""

import io
import uuid
from pathlib import Path

from PIL import Image, ImageDraw, ImageFilter, ImageOps
from rembg import remove
import mediapipe as mp

TEMP_DIR = Path(__file__).parent.parent / "temp"
TEMP_DIR.mkdir(exist_ok=True)

DPI = 300
MM_TO_PX = DPI / 25.4

# name -> (width_mm, height_mm). Add more presets here as needed.
# PAN/Voter ID dimensions are marked for verification against current specs.
SIZE_PRESETS = {
    "indian_passport": (35, 45),
    "pan_card": (25, 35),          # verify against current UTIITSL/NSDL spec
    "voter_id": (25, 35),          # placeholder — verify against current ECI spec
    "us_visa": (51, 51),           # 2in x 2in
}

SHEET_SIZES_MM = {
    "4x6_landscape": (162, 114),
}

BACKGROUND_COLORS = {
    "white": (255, 255, 255),
    "light_blue": (200, 220, 240),
}


def mm_to_px(mm: float) -> int:
    return round(mm * MM_TO_PX)


def remove_background(img_bytes: bytes, bg_color_name: str = "white") -> Image.Image:
    cutout_bytes = remove(img_bytes)
    cutout = Image.open(io.BytesIO(cutout_bytes)).convert("RGBA")
    bg_color = BACKGROUND_COLORS.get(bg_color_name, BACKGROUND_COLORS["white"])
    background = Image.new("RGBA", cutout.size, bg_color + (255,))
    composed = Image.alpha_composite(background, cutout)
    return composed.convert("RGB")


def _detect_face_box(img: Image.Image) -> tuple[int, int, int, int] | None:
    """Returns (x, y, w, h) of the primary face in pixel coords, or None if
    no face was found."""
    mp_face = mp.solutions.face_detection
    with mp_face.FaceDetection(model_selection=1, min_detection_confidence=0.5) as detector:
        import numpy as np
        results = detector.process(np.array(img))
        if not results.detections:
            return None
        det = results.detections[0]
        box = det.location_data.relative_bounding_box
        w, h = img.size
        return (
            max(0, round(box.xmin * w)),
            max(0, round(box.ymin * h)),
            round(box.width * w),
            round(box.height * h),
        )


def crop_to_passport_ratio(img: Image.Image, target_w_mm: float, target_h_mm: float) -> Image.Image:
    """Crop around the detected face while keeping both sides of the head visible.
    Falls back to a plain center crop if no face is detected."""
    target_ratio = target_w_mm / target_h_mm
    face_box = _detect_face_box(img)
    w, h = img.size

    if face_box is None:
        crop_h = h
        crop_w = round(crop_h * target_ratio)
        if crop_w > w:
            crop_w = w
            crop_h = round(crop_w / target_ratio)
        x0 = (w - crop_w) // 2
        y0 = (h - crop_h) // 2
        resized = img.crop((x0, y0, x0 + crop_w, y0 + crop_h)).resize(
            (mm_to_px(target_w_mm), mm_to_px(target_h_mm)), Image.Resampling.LANCZOS
        )
        return resized.filter(ImageFilter.UnsharpMask(radius=1.0, percent=110, threshold=3))

    fx, fy, fw, fh = face_box
    face_cx, face_cy = fx + fw / 2, fy + fh / 2

    # Leave enough head and shoulder context for a natural ID-photo crop.
    crop_h = fh / 0.48
    crop_w = crop_h * target_ratio

    # Constrain the crop to include the full detected face plus a small side margin.
    side_margin = crop_w * 0.06
    x_min = max(0, fx + fw + side_margin - crop_w)
    x_max = min(w - crop_w, fx - side_margin)
    if x_min > x_max:
        x0 = max(0, min(w - crop_w, face_cx - crop_w / 2))
    else:
        x0 = max(x_min, min(x_max, face_cx - crop_w / 2))

    # Place the face lower in the crop so hair and the full head remain visible.
    top_margin = crop_h * 0.05
    y_min = max(0, fy + fh + top_margin - crop_h)
    y_max = min(h - crop_h, fy - top_margin)
    if y_min > y_max:
        y0 = max(0, min(h - crop_h, face_cy - crop_h * 0.44))
    else:
        y0 = max(y_min, min(y_max, face_cy - crop_h * 0.44))

    crop_w, crop_h = min(crop_w, w - x0), min(crop_h, h - y0)
    cropped = img.crop((round(x0), round(y0), round(x0 + crop_w), round(y0 + crop_h)))
    resized = cropped.resize(
        (mm_to_px(target_w_mm), mm_to_px(target_h_mm)), Image.Resampling.LANCZOS
    )
    return resized.filter(ImageFilter.UnsharpMask(radius=1.0, percent=110, threshold=3))


def tile_on_sheet(photo: Image.Image, sheet_name: str = "4x6", copies: int = 8) -> Path:
    sheet_w_mm, sheet_h_mm = SHEET_SIZES_MM[sheet_name]
    sheet_w_px, sheet_h_px = mm_to_px(sheet_w_mm), mm_to_px(sheet_h_mm)
    photo_w, photo_h = photo.size

    margin = mm_to_px(3)
    # There is no trailing margin after the last photo in a row or column.
    cols = max(1, (sheet_w_px + margin) // (photo_w + margin))
    rows = max(1, (sheet_h_px + margin) // (photo_h + margin))
    max_fit = cols * rows
    n = min(copies, max_fit)
    used_rows = max(1, (n + cols - 1) // cols)

    sheet = Image.new("RGB", (sheet_w_px, sheet_h_px), "white")
    draw = ImageDraw.Draw(sheet)

    grid_width = cols * photo_w + (cols - 1) * margin
    grid_height = used_rows * photo_h + (used_rows - 1) * margin
    start_x = max(margin, (sheet_w_px - grid_width) // 2)
    start_y = max(margin, (sheet_h_px - grid_height) // 2)

    placed = 0
    for r in range(rows):
        for c in range(cols):
            if placed >= n:
                break
            x = start_x + c * (photo_w + margin)
            y = start_y + r * (photo_h + margin)
            sheet.paste(photo, (x, y))
            draw.rectangle([x, y, x + photo_w, y + photo_h], outline="lightgray", width=1)
            placed += 1

    out_path = TEMP_DIR / f"{uuid.uuid4()}_photosheet.pdf"
    sheet.save(out_path, "PDF", resolution=DPI)
    return out_path


def process_passport_photo(
    img_bytes: bytes,
    preset: str,
    bg_color: str = "white",
    copies: int = 8,
    custom_mm: tuple[float, float] | None = None,
) -> Path:
    if preset == "custom":
        if not custom_mm:
            raise ValueError("custom_mm required when preset='custom'")
        target_w_mm, target_h_mm = custom_mm
    elif preset in SIZE_PRESETS:
        target_w_mm, target_h_mm = SIZE_PRESETS[preset]
    else:
        raise ValueError(f"Unknown preset: {preset}")

    source = ImageOps.exif_transpose(Image.open(io.BytesIO(img_bytes))).convert("RGB")
    composed = remove_background(img_bytes, bg_color)
    if source.width < mm_to_px(target_w_mm) or source.height < mm_to_px(target_h_mm):
        raise ValueError(
            f"Image resolution is too low for a sharp {target_w_mm:g}x{target_h_mm:g}mm print"
        )
    cropped = crop_to_passport_ratio(composed, target_w_mm, target_h_mm)
    return tile_on_sheet(cropped, "4x6_landscape", copies)
