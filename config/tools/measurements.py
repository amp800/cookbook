"""Normalize recipe measurements to the family's UK metric conventions."""
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


def normalize_text(text: str) -> str:
    """Return text using grams, kilograms, millilitres, litres and UK volumes."""
    if not isinstance(text, str):
        return text
    text = _convert_temperature(text)
    # Remove duplicate imperial values when a metric equivalent is already supplied.
    text = re.sub(r"(\d+(?:[.,]\d+)?\s*(?:g|gram(?:s)?|kg|kilogram(?:s)?|ml|millilit(?:re|er)s?|l|lit(?:re|er)s?))\s*/\s*\d+(?:[.,]\d+)?\s*(?:oz|ounce(?:s)?|lb|lbs|pound(?:s)?)\b", r"\1", text, flags=re.I)
    text = re.sub(r"(\d+(?:[.,]\d+)?\s*(?:ml|millilit(?:re|er)s?|l|lit(?:re|er)s?))\s*\([^)]*\b(?:cup|cups|tbsp|tablespoons?|tsp|teaspoons?|oz|ounces?)\b[^)]*\)", r"\1", text, flags=re.I)
    text = re.sub(r"\([^)]*\b(?:oz|ounces?|lb|lbs|pounds?)\b[^)]*\)", "", text, flags=re.I)
    text = re.sub(r"\s{2,}", " ", text).strip()

    # Explicit US volume units. Keep numerals readable rather than forcing decimals.
    def volume(match):
        amount = _fraction(match.group(1))
        unit = match.group(2).lower()
        if amount is None:
            return match.group(0)
        if unit.startswith(("tbsp", "tablespoon")):
            return f"{_fmt(amount * 15)} ml"
        if unit.startswith(("tsp", "teaspoon")):
            return f"{_fmt(amount * 5)} ml"
        if unit.startswith(("cup",)):
            return f"{_fmt(amount * 236.588)} ml"
        return match.group(0)
    text = re.sub(r"(?<![\w.])(\d+(?:\.\d+)?(?:\s+\d+/\d+)?|[½⅓⅔¼¾⅛⅜⅝⅞])\s*(cups?|tablespoons?|tbsp|teaspoons?|tsp)\b", volume, text, flags=re.I)

    def weight(match):
        amount = _fraction(match.group(1))
        unit = match.group(2).lower()
        if amount is None:
            return match.group(0)
        return f"{_fmt(amount * (453.592 if unit.startswith(('lb', 'pound')) else 28.3495))} g"
    text = re.sub(r"(?<![\w.])(\d+(?:\.\d+)?(?:\s+\d+/\d+)?|[½⅓⅔¼¾⅛⅜⅝⅞])\s*(lbs?|pounds?|ounces?|oz)\b", weight, text, flags=re.I)
    return text


def normalize_items(items):
    return [normalize_text(item) for item in (items or [])]
