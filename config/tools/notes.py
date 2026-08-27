"""Helpers for rendering and normalising recipe note references."""
from __future__ import annotations

import re


def normalize_note_references(text: str) -> str:
    """Convert bracketed note references such as ``(note 1)`` to superscript HTML."""
    if not isinstance(text, str):
        return text
    pattern = re.compile(r"\(\s*(?:note|notes)\s+(\d+)\s*\)", re.IGNORECASE)
    return pattern.sub(r"<sup>\1</sup>", text)


def normalize_note_items(items):
    return [normalize_note_references(item) for item in (items or [])]
