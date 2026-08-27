"""Normalize recipe measurements to the family's abbreviated UK metric conventions."""
from __future__ import annotations

import re

FRACTIONS = {"½": 0.5, "⅓": 1 / 3, "⅔": 2 / 3, "¼": 0.25, "¾": 0.75, "⅛": 0.125, "⅜": 0.375, "⅝": 0.625, "⅞": 0.875}


def _fmt(value: float) -> str:
    if abs(value - round(value)) < 1e-9:
        return str(int(round(value)))
    return f"{value:.2f}".rstrip("0").rstrip(".")


def _fraction(value: str) -> float | None:
    value = value.strip()
    if value in FRACTIONS:
        return FRACTIONS[value]
    m = re.fullmatch(r"(\d+)\s+(\d+)/(\d+)", value)
    if m:
        return int(m.group(1)) + int(m.group(2)) / int(m.group(3))
    m = re.fullmatch(r"(\d+)/(\d+)", value)
    if m:
        return int(m.group(1)) / int(m.group(2))
    try:
        return float(value)
    except ValueError:
        return None


def _convert_temperature(text: str) -> str:
    def repl(match):
        value = float(match.group(1))
        return f"{_fmt((value - 32) * 5 / 9)}°C"
    return re.sub(r"(?<![\d.])(-?\d+(?:\.\d+)?)\s*°?F\b", repl, text, flags=re.I)


def _abbreviate_units(text: str) -> str:
    replacements = [
        (r"\bkilograms?\b", "kg"), (r"\bgrams?\b", "g"),
        (r"\bmillilit(?:re|er)s?\b", "mL"), (r"\blit(?:re|er)s?\b", "L"),
        (r"\btablespoons?\b", "tbsp"), (r"\bteaspoons?\b", "tsp"),
    ]
    for pattern, replacement in replacements:
        text = re.sub(pattern, replacement, text, flags=re.I)
    return text


def normalize_text(text: str) -> str:
    """Convert imperial values and normalize all supported units to abbreviations."""
    if not isinstance(text, str):
        return text
    text = _convert_temperature(text)
    # If a Celsius equivalent is already supplied, remove the converted Fahrenheit duplicate.
    text = re.sub(r"(\d+(?:\.\d+)?°C)\s*\(\s*\d+(?:\.\d+)?°C\s*\)", r"\1", text)
    # Prefer an explicitly supplied metric value over a duplicate imperial value.
    text = re.sub(r"(\d+(?:[.,]\d+)?\s*(?:g|gram(?:s)?|kg|kilogram(?:s)?|mL|ml|millilit(?:re|er)s?|L|l|lit(?:re|er)s?))\s*/\s*\d+(?:[.,]\d+)?\s*(?:oz|ounce(?:s)?|lb|lbs|pound(?:s)?)\b", r"\1", text, flags=re.I)
    text = re.sub(r"(\d+(?:[.,]\d+)?\s*(?:mL|ml|millilit(?:re|er)s?|L|l|lit(?:re|er)s?))\s*\([^)]*\b(?:cup|cups|tbsp|tablespoons?|tsp|teaspoons?|oz|ounces?)\b[^)]*\)", r"\1", text, flags=re.I)
    text = re.sub(r"\([^)]*\b(?:oz|ounces?|lb|lbs|pounds?)\b[^)]*\)", "", text, flags=re.I)
    text = re.sub(r"\s{2,}", " ", text).strip()

    def volume(match):
        amount = _fraction(match.group(1))
        unit = match.group(2).lower()
        if amount is None:
            return match.group(0)
        if unit.startswith(("tbsp", "tablespoon")):
            return f"{_fmt(amount * 15)} mL"
        if unit.startswith(("tsp", "teaspoon")):
            return f"{_fmt(amount * 5)} mL"
        # A bare cup is retained as requested; this represents the household UK cup.
        return f"{match.group(1).strip()} cup" + ("s" if amount != 1 and unit.startswith("cup") else "")
    text = re.sub(r"(?<![\w.])(\d+(?:\.\d+)?(?:\s+\d+/\d+)?|[½⅓⅔¼¾⅛⅜⅝⅞])\s*(cups?|tablespoons?|tbsp|teaspoons?|tsp)\b", volume, text, flags=re.I)

    def weight(match):
        amount = _fraction(match.group(1))
        unit = match.group(2).lower()
        if amount is None:
            return match.group(0)
        return f"{_fmt(amount * (453.592 if unit.startswith(('lb', 'pound')) else 28.3495))} g"
    text = re.sub(r"(?<![\w.])(\d+(?:\.\d+)?(?:\s+\d+/\d+)?|[½⅓⅔¼¾⅛⅜⅝⅞])\s*(lbs?|pounds?|ounces?|oz)\b", weight, text, flags=re.I)
    return _abbreviate_units(text)


def normalize_items(items):
    return [normalize_text(item) for item in (items or [])]
