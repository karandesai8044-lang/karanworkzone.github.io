"""
Module 1: plain document print. The heavy lifting (any-format -> PDF) is
shared code in convert.py; this module just validates/normalizes the
print settings that get attached to the order and later handed to the
print agent.
"""

import re


def parse_page_range(page_range: str, total_pages: int) -> list[int]:
    """Parse strings like '1-3, 5, 8-9' into a sorted list of 1-indexed pages.
    Empty string means "all pages"."""
    page_range = (page_range or "").strip()
    if not page_range:
        return list(range(1, total_pages + 1))

    if not re.fullmatch(r"[\d,\-\s]+", page_range):
        raise ValueError("Page range may only contain digits, commas, hyphens and spaces")

    pages: set[int] = set()
    for part in page_range.split(","):
        part = part.strip()
        if not part:
            continue
        if "-" in part:
            start_s, end_s = part.split("-", 1)
            start, end = int(start_s), int(end_s)
            if start < 1 or end > total_pages or start > end:
                raise ValueError(f"Invalid page range segment: {part}")
            pages.update(range(start, end + 1))
        else:
            p = int(part)
            if p < 1 or p > total_pages:
                raise ValueError(f"Page {p} is out of range (1-{total_pages})")
            pages.add(p)
    return sorted(pages)


def build_print_settings(copies: int, color: bool, page_range: str, orientation: str) -> dict:
    """Normalize UI settings into the dict stored in orders.settings_json and
    later translated into a SumatraPDF -print-settings string by the print agent.
    NOTE: confirm exact SumatraPDF CLI flag syntax for color/orientation against
    current docs before wiring this into a real print call — flags have changed
    across SumatraPDF versions."""
    if copies < 1 or copies > 100:
        raise ValueError("Copies must be between 1 and 100")
    if orientation not in ("portrait", "landscape"):
        raise ValueError("Orientation must be 'portrait' or 'landscape'")
    return {
        "copies": copies,
        "color": bool(color),
        "page_range": page_range or "",
        "orientation": orientation,
    }
