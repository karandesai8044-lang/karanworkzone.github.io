"""
Module 2: ID card print. Takes front + back photos of a card (Aadhar, PAN,
etc.), crops both to standard CR80 card ratio, and composes them onto a
single A4 page (front on top, back on bottom) with a dashed cut line.
"""

import uuid
from pathlib import Path

import cv2
import numpy as np
from PIL import Image, ImageDraw

TEMP_DIR = Path(__file__).parent.parent / "temp"
TEMP_DIR.mkdir(exist_ok=True)

# CR80 card size in mm
CARD_WIDTH_MM = 85.6
CARD_HEIGHT_MM = 53.98

# A4 in mm
A4_WIDTH_MM = 210
A4_HEIGHT_MM = 297

DPI = 300
MM_TO_PX = DPI / 25.4


def mm_to_px(mm: float) -> int:
    return round(mm * MM_TO_PX)


def _fit_crop_to_ratio(img: Image.Image, target_ratio: float) -> Image.Image:
    """Center-crop an image to match target_ratio (width/height) without distorting it."""
    w, h = img.size
    current_ratio = w / h
    if current_ratio > target_ratio:
        # too wide -> crop width
        new_w = round(h * target_ratio)
        x0 = (w - new_w) // 2
        img = img.crop((x0, 0, x0 + new_w, h))
    else:
        # too tall -> crop height
        new_h = round(w / target_ratio)
        y0 = (h - new_h) // 2
        img = img.crop((0, y0, w, y0 + new_h))
    return img


def _order_points(points: np.ndarray) -> np.ndarray:
    ordered = np.zeros((4, 2), dtype=np.float32)
    sums = points.sum(axis=1)
    differences = np.diff(points, axis=1).ravel()
    ordered[0] = points[np.argmin(sums)]
    ordered[2] = points[np.argmax(sums)]
    ordered[1] = points[np.argmin(differences)]
    ordered[3] = points[np.argmax(differences)]
    return ordered


def _extract_card(img: Image.Image) -> Image.Image:
    """Detect the card boundary and flatten a tilted phone photo."""
    source = cv2.cvtColor(np.array(img), cv2.COLOR_RGB2BGR)
    height, width = source.shape[:2]
    gray = cv2.cvtColor(source, cv2.COLOR_BGR2GRAY)
    edges = cv2.Canny(cv2.GaussianBlur(gray, (5, 5), 0), 50, 150)
    contours, _ = cv2.findContours(edges, cv2.RETR_EXTERNAL, cv2.CHAIN_APPROX_SIMPLE)

    image_area = width * height
    best = None
    best_area = 0
    for contour in sorted(contours, key=cv2.contourArea, reverse=True)[:30]:
        area = cv2.contourArea(contour)
        if area < image_area * 0.20:
            continue
        perimeter = cv2.arcLength(contour, True)
        polygon = cv2.approxPolyDP(contour, 0.02 * perimeter, True)
        if len(polygon) != 4 or not cv2.isContourConvex(polygon):
            continue
        points = polygon.reshape(4, 2).astype(np.float32)
        ordered = _order_points(points)
        top_left, top_right, bottom_right, bottom_left = ordered
        target_width = int(max(np.linalg.norm(bottom_right - bottom_left), np.linalg.norm(top_right - top_left)))
        target_height = int(max(np.linalg.norm(top_right - bottom_right), np.linalg.norm(top_left - bottom_left)))
        if target_width <= 0 or target_height <= 0:
            continue
        ratio = target_width / target_height
        if 1.2 <= ratio <= 2.2 and area > best_area:
            best = ordered
            best_area = area

    if best is None:
        return img

    target_width = max(1, int(max(np.linalg.norm(best[2] - best[3]), np.linalg.norm(best[1] - best[0]))))
    target_height = max(1, int(max(np.linalg.norm(best[1] - best[2]), np.linalg.norm(best[0] - best[3]))))
    destination = np.array(
        [[0, 0], [target_width - 1, 0], [target_width - 1, target_height - 1], [0, target_height - 1]],
        dtype=np.float32,
    )
    transform = cv2.getPerspectiveTransform(best, destination)
    warped = cv2.warpPerspective(source, transform, (target_width, target_height))
    return Image.fromarray(cv2.cvtColor(warped, cv2.COLOR_BGR2RGB))


def compose_id_card_sheet(front_path: Path, back_path: Path) -> Path:
    card_ratio = CARD_WIDTH_MM / CARD_HEIGHT_MM
    card_w_px = mm_to_px(CARD_WIDTH_MM)
    card_h_px = mm_to_px(CARD_HEIGHT_MM)

    a4_w_px = mm_to_px(A4_WIDTH_MM)
    a4_h_px = mm_to_px(A4_HEIGHT_MM)

    front = _fit_crop_to_ratio(_extract_card(Image.open(front_path).convert("RGB")), card_ratio)
    back = _fit_crop_to_ratio(_extract_card(Image.open(back_path).convert("RGB")), card_ratio)
    front = front.resize((card_w_px, card_h_px), Image.LANCZOS)
    back = back.resize((card_w_px, card_h_px), Image.LANCZOS)

    canvas = Image.new("RGB", (a4_w_px, a4_h_px), "white")
    x_offset = (a4_w_px - card_w_px) // 2

    top_y = round(a4_h_px * 0.20)
    bottom_y = round(a4_h_px * 0.55)

    canvas.paste(front, (x_offset, top_y))
    canvas.paste(back, (x_offset, bottom_y))

    draw = ImageDraw.Draw(canvas)
    cut_line_y = (top_y + card_h_px + bottom_y) // 2
    dash_len, gap_len = 15, 10
    x = 0
    while x < a4_w_px:
        draw.line([(x, cut_line_y), (min(x + dash_len, a4_w_px), cut_line_y)], fill="gray", width=2)
        x += dash_len + gap_len

    out_path = TEMP_DIR / f"{uuid.uuid4()}_idcard.pdf"
    canvas.save(out_path, "PDF", resolution=DPI)
    return out_path
