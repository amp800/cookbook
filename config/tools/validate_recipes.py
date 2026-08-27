"""Validate recipe file structure without requiring the Jekyll toolchain."""
from __future__ import annotations

import re
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
RECIPES = ROOT / "_recipes"
IMAGES = ROOT / "recipe_images"


def main() -> int:
    errors = []
    files = sorted(RECIPES.glob("*.md"))
    if not files:
        errors.append("no recipe files found")
    for path in files:
        text = path.read_text(encoding="utf-8")
        parts = re.split(r"(?m)^---[ \t]*$", text, maxsplit=2)
        if len(parts) < 2:
            errors.append(f"{path}: missing front matter")
            continue
        front = parts[1]
        for required in ("layout:", "title:", "ingredients:", "directions:"):
            if required not in front:
                errors.append(f"{path}: missing {required[:-1]} field")
        image = re.search(r"^image:\s*['\"]?([^'\"\s]+)", front, re.MULTILINE)
        if image and not (IMAGES / image.group(1)).is_file():
            errors.append(f"{path}: missing image {image.group(1)}")
    if errors:
        print("\n".join(errors))
        return 1
    print(f"Validated {len(files)} recipes")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
