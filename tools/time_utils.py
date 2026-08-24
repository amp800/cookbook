"""Shared helpers for normalising recipe times and deriving cook/total values."""
from __future__ import annotations

import re


def parse_minutes(value):
    if value is None:
        return None
    text = str(value).strip().lower()
    if not text or text in ("none", "n/a", "0", "0 minutes"):
        return None
    if re.fullmatch(r"\d+(?:\.\d+)?", text):
        return int(round(float(text))) or None
    match = re.fullmatch(r"pt(?:(\d+)h)?(?:(\d+)m)?", text)
    if match:
        return int(match.group(1) or 0) * 60 + int(match.group(2) or 0) or None
    total = 0.0
    found = False
    for number, unit in re.findall(r"(\d+(?:\.\d+)?)\s*(hours?|hrs?|minutes?|mins?)", text):
        found = True
        total += float(number) * (60 if unit.startswith(("hour", "hr")) else 1)
    return int(round(total)) if found and total else None


def derive_times(data: dict) -> dict:
    """Return a copy with the missing member of prep + cook = total filled."""
    result = dict(data)
    prep = parse_minutes(result.get("prep_time"))
    cook = parse_minutes(result.get("cook_time"))
    total = parse_minutes(result.get("total_time"))
    if cook is None and prep is not None and total is not None and total >= prep:
        result["cook_time"] = str(total - prep)
    elif total is None and prep is not None and cook is not None:
        result["total_time"] = str(prep + cook)
    return result
