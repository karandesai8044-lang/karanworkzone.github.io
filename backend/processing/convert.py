"""
Universal upload handling: detect real file type (magic bytes, not just
extension) and convert anything supported into a single print-ready PDF.
"""

import subprocess
import uuid
from pathlib import Path

import img2pdf

TEMP_DIR = Path(__file__).parent.parent / "temp"
TEMP_DIR.mkdir(exist_ok=True)

MAX_FILE_SIZE_BYTES = 20 * 1024 * 1024  # 20MB

# Magic-byte signatures for the file types we accept. Extensions are only used
# as a hint; this is the actual allowlist check.
SIGNATURES = {
    b"%PDF-": "pdf",
    b"\xff\xd8\xff": "jpg",
    b"\x89PNG\r\n\x1a\n": "png",
    b"PK\x03\x04": "zip_based",  # docx/pptx/xlsx are zip containers; disambiguate below
}

OFFICE_EXTENSIONS = {".docx", ".pptx", ".xlsx"}


class UnsupportedFileError(Exception):
    pass


def sniff_type(file_bytes: bytes, filename: str) -> str:
    """Return one of: pdf, jpg, png, docx, pptx, xlsx. Raises UnsupportedFileError."""
    if len(file_bytes) > MAX_FILE_SIZE_BYTES:
        raise UnsupportedFileError(f"File exceeds {MAX_FILE_SIZE_BYTES // (1024*1024)}MB limit")

    for sig, kind in SIGNATURES.items():
        if file_bytes.startswith(sig):
            if kind != "zip_based":
                return kind
            # zip-based office format: extension is the only reliable signal
            # (a full check would open the zip and inspect [Content_Types].xml;
            # left as a documented simplification for the MVP)
            ext = Path(filename).suffix.lower()
            if ext in OFFICE_EXTENSIONS:
                return ext.lstrip(".")
            raise UnsupportedFileError(f"Unrecognized zip-based file: {filename}")

    raise UnsupportedFileError(
        "File type not recognized. Supported: PDF, JPG, PNG, DOCX, PPTX, XLSX"
    )


def image_to_pdf(image_path: Path) -> Path:
    out_path = TEMP_DIR / f"{uuid.uuid4()}.pdf"
    with open(out_path, "wb") as f:
        f.write(img2pdf.convert(str(image_path)))
    return out_path


def office_to_pdf(office_path: Path) -> Path:
    """Requires LibreOffice installed with `soffice` on PATH."""
    out_dir = TEMP_DIR
    result = subprocess.run(
        [
            "soffice", "--headless", "--norestore",
            "--convert-to", "pdf", "--outdir", str(out_dir), str(office_path),
        ],
        capture_output=True, text=True, timeout=120,
    )
    if result.returncode != 0:
        raise RuntimeError(f"LibreOffice conversion failed: {result.stderr}")
    produced = out_dir / f"{office_path.stem}.pdf"
    if not produced.exists():
        raise RuntimeError("LibreOffice did not produce an output PDF")
    return produced


def to_print_ready_pdf(file_bytes: bytes, filename: str) -> Path:
    """Entry point: given raw upload bytes, return a Path to a print-ready PDF."""
    kind = sniff_type(file_bytes, filename)

    raw_path = TEMP_DIR / f"{uuid.uuid4()}_{filename}"
    raw_path.write_bytes(file_bytes)

    if kind == "pdf":
        return raw_path
    if kind in ("jpg", "png"):
        return image_to_pdf(raw_path)
    if kind in ("docx", "pptx", "xlsx"):
        return office_to_pdf(raw_path)

    raise UnsupportedFileError(f"No converter for {kind}")
