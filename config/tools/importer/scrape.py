"""
Standalone recipe scraper — called by GitHub Actions import-recipe workflow.
Usage:
  python config/tools/importer/scrape.py \
    --url "https://..." \
    --tags "chicken quick"
Writes _recipes/<slug>.md and recipe_images/<slug>.<ext> relative to the repo root.
"""
import argparse
import json
import re
import sys
from pathlib import Path
from urllib.parse import urlparse, urljoin

import requests
from bs4 import BeautifulSoup

try:
    from recipe_scrapers import scrape_html
except ImportError:
    print("recipe-scrapers not installed", file=sys.stderr)
    sys.exit(1)

REPO_ROOT = Path(__file__).resolve().parent.parent.parent.parent  # config/tools/importer/scrape.py → repo root
sys.path.insert(0, str(REPO_ROOT / "config" / "tools"))
from measurements import normalize_items
from notes import normalize_note_items
from recipe_frontmatter import render_recipe_markdown

# ---------------------------------------------------------------------------
# Helpers (mirror of app/main.py so the Actions workflow needs no FastAPI)
# ---------------------------------------------------------------------------

def slugify(text: str) -> str:
    text = (text or "").lower()
    text = re.sub(r"[^\w\s-]", "", text)
    text = re.sub(r"[-\s]+", "-", text).strip("-")
    return text or "imported-recipe"


def _ensure_str_list(value):
    if value is None:
        return []
    if isinstance(value, str):
        return [value]
    try:
        return [str(v) for v in value]
    except TypeError:
        return [str(value)]


def format_ingredients(ingredients) -> list:
    items = _ensure_str_list(ingredients)
    return normalize_items([str(i).strip() for i in items if str(i).strip()])


def format_instructions(instructions) -> list:
    items = _ensure_str_list(instructions)
    cleaned = []
    for step in items:
        step = str(step).strip()
        if not step:
            continue
        step = re.sub(r"<[^>]+>", "", step)
        step = re.sub(r"^(\d+[\.]\s+|-\s+|\*\s+)", "", step)
        if step:
            cleaned.append(step)
    return normalize_note_items(normalize_items(cleaned))


RECIPE_CARD_RE = re.compile(
    r"(wprm-recipe|tasty-recipes|recipe-card|recipecontainer|recipe-content|"
    r"recipe-instructions|recipe-ingredients|recipe__content|recipe__ingredients|"
    r"recipe__instructions|recipe__summary|recipe-meta|hrecipe|mv-create-card)",
    re.IGNORECASE,
)

AUTHOR_BIO_RE = re.compile(
    r"(author|biography|bio\b|contributor|byline)",
    re.IGNORECASE,
)

BOILERPLATE_RE = re.compile(
    r"^(jump to recipe|skip to recipe|recipe video|print recipe|save recipe|"
    r"pin recipe|this post (may contain|contains) affiliate|advertisement|"
    r"disclaimer|shop the post|read more)",
    re.IGNORECASE,
)


def clean_text(text) -> str:
    if text is None:
        return ""
    text = str(text).replace("\xa0", " ")
    text = re.sub(r"\s+", " ", text)
    return text.strip()


def derive_times(data: dict) -> None:
    """Fill the missing member of prep + cook = total when possible."""
    from time_utils import derive_times as _derive_times

    data.update(_derive_times(data))


def extract_first_paragraph(html: str) -> str:
    """Return the first meaningful intro paragraph of a recipe page (the
    'what/why' blurb that usually appears before the ingredients list)."""
    try:
        soup = BeautifulSoup(html, "html.parser")
    except Exception:
        return ""
    for tag in soup(["script", "style", "noscript", "svg", "iframe", "form"]):
        tag.decompose()
    for p in soup.find_all("p"):
        # Skip paragraphs inside nav/header/footer/aside/form or inside the
        # recipe card (where the ingredients/directions live).
        ancestor = p.parent
        skip = False
        while ancestor is not None and getattr(ancestor, "name", None):
            if ancestor.name.lower() in ("nav", "header", "footer", "aside", "form"):
                skip = True
                break
            cls = " ".join(ancestor.get("class", [])) if hasattr(ancestor, "get") else ""
            ident = ancestor.get("id", "") if hasattr(ancestor, "get") else ""
            if RECIPE_CARD_RE.search(cls) or RECIPE_CARD_RE.search(ident) or ident.lower() == "recipe":
                skip = True
                break
            if AUTHOR_BIO_RE.search(cls) or AUTHOR_BIO_RE.search(ident):
                skip = True
                break
            ancestor = ancestor.parent
        if skip:
            continue
        text = clean_text(p.get_text(" ", strip=True))
        if len(text) < 40:
            continue
        if BOILERPLATE_RE.search(text.lower()):
            continue
        return text
    return ""


def shorten_description(text, limit: int = 400) -> str:
    """Trim an over-long fallback description at a sentence/word boundary."""
    text = clean_text(text or "")
    if len(text) <= limit:
        return text
    head = text[:limit]
    cut = max(head.rfind(". "), head.rfind("! "), head.rfind("? "))
    if cut > limit // 2:
        return head[: cut + 1]
    return head.rsplit(" ", 1)[0] + "\u2026"


def guess_tags(title: str) -> list:
    title_lower = (title or "").lower()
    tag_map = {
        "vegetarian": ["vegetarian"],
        "vegan": ["vegan"],
        "gluten-free": ["gluten-free"],
        "chicken": ["chicken"],
        "beef": ["beef"],
        "pork": ["pork"],
        "fish": ["fish", "seafood"],
        "salmon": ["fish", "seafood"],
        "shrimp": ["seafood"],
        "pasta": ["pasta"],
        "soup": ["soup"],
        "stew": ["stew"],
        "salad": ["salad"],
        "dessert": ["dessert"],
        "cake": ["dessert", "baking"],
        "cookie": ["dessert", "baking"],
        "bread": ["bread", "baking"],
        "pizza": ["pizza"],
        "taco": ["mexican"],
        "curry": ["curry"],
    }
    tags: set = set()
    for keyword, tag_list in tag_map.items():
        if keyword in title_lower:
            tags.update(tag_list)
    return sorted(list(tags))


def download_image(image_url: str, source_url: str, save_path: Path) -> bool:
    if not image_url:
        return False
    if image_url.startswith("/"):
        parsed = urlparse(source_url)
        image_url = f"{parsed.scheme}://{parsed.netloc}{image_url}"
    elif not image_url.startswith("http"):
        image_url = urljoin(source_url, image_url)
    headers = {
        "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
                      "AppleWebKit/537.36 (KHTML, like Gecko) "
                      "Chrome/120.0.0.0 Safari/537.36",
        "Referer": source_url,
    }
    try:
        resp = requests.get(image_url, headers=headers, timeout=30, stream=True)
        resp.raise_for_status()
        save_path.parent.mkdir(parents=True, exist_ok=True)
        with open(save_path, "wb") as f:
            for chunk in resp.iter_content(chunk_size=8192):
                if chunk:
                    f.write(chunk)
        return True
    except Exception as e:
        print(f"Image download failed: {e}", file=sys.stderr)
        return False


def _safe_scraper_call(scraper, method_name):
    """Call a scraper method and return (value, ok)."""
    try:
        val = getattr(scraper, method_name)()
        return val, True
    except Exception:
        return None, False


def _node_text(node) -> str:
    """Return the text content of a rich-text descriptor node."""
    if not isinstance(node, dict):
        return ""
    if node.get("type") == "text":
        return str(node.get("content") or "")
    parts = [_node_text(child) for child in (node.get("children") or [])]
    return " ".join(part for part in parts if part)


def _iter_descriptor_nodes(node, key: str):
    """Yield the descriptor nodes whose key matches (e.g. list items)."""
    if not isinstance(node, dict):
        return
    if node.get("key") == key:
        yield node
        return
    for child in node.get("children") or []:
        yield from _iter_descriptor_nodes(child, key)


def _is_label_node(node) -> bool:
    """A heading/bold-only node such as the \"Moutabal\" section label."""
    if node.get("key") in ("@@standfirst", "h2", "h3", "h4", "h5", "h6"):
        return True
    children = [child for child in (node.get("children") or []) if isinstance(child, dict)]
    return bool(children) and all(child.get("key") == "strong" for child in children)


def _descriptor_lines(descriptor, ordered_items: bool = False) -> list:
    """Flatten a rich-text descriptor tree into recipe lines.

    Section labels (bold-only entries) are prefixed with ``###`` so the recipe
    layout renders them as headings instead of ingredients/steps.
    """
    lines: list = []
    if not isinstance(descriptor, dict):
        return lines
    for child in descriptor.get("children") or []:
        if not isinstance(child, dict):
            continue
        nodes = list(_iter_descriptor_nodes(child, "li")) if ordered_items else []
        if not nodes:
            nodes = [child]
        for node in nodes:
            text = clean_text(_node_text(node))
            if not text:
                continue
            if not ordered_items and _is_label_node(node):
                lines.append(f"### {text}")
            else:
                lines.append(text)
    return lines


def _first_descriptor(value):
    """Find the first ``{\"descriptor\": ...}`` payload in a nested structure."""
    if isinstance(value, dict):
        if isinstance(value.get("descriptor"), dict):
            return value["descriptor"]
        for child in value.values():
            found = _first_descriptor(child)
            if found:
                return found
    elif isinstance(value, list):
        for child in value:
            found = _first_descriptor(child)
            if found:
                return found
    return None


def _find_next_recipe(data):
    """Locate a Next.js recipe loader (``__NEXT_DATA__``) in the page payload."""
    stack = [data]
    while stack:
        node = stack.pop()
        if isinstance(node, dict):
            recipe = node.get("recipe")
            if isinstance(recipe, dict) and any(
                key in recipe
                for key in ("recipeIngredientsPrepared", "recipeInstructionsPrepared")
            ):
                return node, recipe
            stack.extend(node.values())
        elif isinstance(node, list):
            stack.extend(node)
    return None, None


def _next_data_recipe(html: str) -> dict:
    """Extract a recipe from an embedded Next.js page payload (e.g. ABC News).

    Some publishers (ABC News included) render their recipe card from
    ``__NEXT_DATA__`` and ship no schema.org Recipe markup at all, which is
    what makes recipe-scrapers give up on them.
    """
    match = re.search(
        r'<script[^>]+id="__NEXT_DATA__"[^>]*>(.*?)</script>', html, re.S
    )
    if not match:
        return {}
    try:
        payload = json.loads(match.group(1))
    except (TypeError, ValueError):
        return {}

    page, recipe = _find_next_recipe(payload)
    if not recipe:
        return {}

    ingredients = _descriptor_lines(_first_descriptor(recipe.get("recipeIngredientsPrepared")))
    instructions = _descriptor_lines(
        _first_descriptor(recipe.get("recipeInstructionsPrepared")), ordered_items=True
    )
    if not ingredients or not instructions:
        return {}

    data = {
        "title": clean_text(page.get("title") if page else ""),
        "ingredients": ingredients,
        "instructions": instructions,
    }
    for source_key, target_key in [
        ("preparationTime", "prep_time"),
        ("cookingTime", "cook_time"),
        ("totalTime", "total_time"),
        ("recipeYield", "yield"),
    ]:
        value = recipe.get(source_key)
        if value:
            data[target_key] = str(value)
    return data


RECIPE_CONTAINER_RE = re.compile(
    r"(wprm-recipe|tasty-recipes|recipe-?card|recipe-?container|recipe__|hrecipe)", re.IGNORECASE
)


def _find_recipe_container(soup):
    container = soup.find(id=re.compile(r"^recipe$", re.IGNORECASE))
    if container is not None:
        return container
    for candidate in soup.find_all(["article", "section", "div"]):
        classes = " ".join(candidate.get("class") or [])
        ident = candidate.get("id") or ""
        if RECIPE_CONTAINER_RE.search(classes) or RECIPE_CONTAINER_RE.search(ident):
            return candidate
    return None


def _section_matching(container, pattern: str):
    regex = re.compile(pattern, re.IGNORECASE)
    for section in container.find_all(["section", "div"]):
        classes = " ".join(section.get("class") or [])
        ident = section.get("id") or ""
        if regex.search(classes) or regex.search(ident):
            return section
    return None


def _html_recipe(html: str) -> dict:
    """Extract a recipe from a rendered recipe card (no structured data)."""
    soup = BeautifulSoup(html, "html.parser")
    for tag in soup(["script", "style", "noscript", "svg", "iframe", "form"]):
        tag.decompose()

    container = _find_recipe_container(soup)
    if container is None:
        return {}

    heading = container.find(["h1", "h2"])
    title = clean_text(heading.get_text(" ", strip=True)) if heading else ""

    ingredients: list = []
    ingredient_box = _section_matching(container, r"ingredient")
    if ingredient_box is not None:
        entries = ingredient_box.find_all("li") or ingredient_box.find_all("p")
        for entry in entries:
            text = clean_text(entry.get_text(" ", strip=True))
            if not text:
                continue
            strong = entry.find("strong")
            is_label = strong is not None and clean_text(strong.get_text(" ", strip=True)) == text
            ingredients.append(f"### {text}" if is_label else text)

    steps: list = []
    instruction_box = _section_matching(container, r"instruction|method|direction")
    if instruction_box is not None:
        steps = [clean_text(li.get_text(" ", strip=True)) for li in instruction_box.find_all("li")]
    if not steps:
        ordered = container.find("ol")
        if ordered is not None:
            steps = [clean_text(li.get_text(" ", strip=True)) for li in ordered.find_all("li")]
    steps = [step for step in steps if step]

    if not ingredients or not steps:
        return {}
    return {"title": title, "ingredients": ingredients, "instructions": steps}


def extract_fallback_recipe(html: str) -> dict:
    """Extract a recipe from pages recipe-scrapers cannot read (no JSON-LD)."""
    for extractor in (_next_data_recipe, _html_recipe):
        try:
            data = extractor(html)
        except Exception as e:  # a broken page must not abort the import
            print(f"Warning: {extractor.__name__} failed: {e}", file=sys.stderr)
            data = {}
        if data.get("ingredients") and data.get("instructions"):
            return data
    return {}


def meta_image(html: str) -> str:
    """Return the page's social/og image, used when the card has none."""
    soup = BeautifulSoup(html, "html.parser")
    for attrs in (
        {"property": "og:image"},
        {"name": "og:image"},
        {"name": "twitter:image"},
    ):
        tag = soup.find("meta", attrs=attrs)
        if tag and tag.get("content"):
            return tag["content"].strip()
    return ""


def fetch_recipe(url: str) -> dict:
    headers = {
        "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
                      "AppleWebKit/537.36 (KHTML, like Gecko) "
                      "Chrome/120.0.0.0 Safari/537.36"
    }
    response = requests.get(url, headers=headers, timeout=30)
    response.raise_for_status()
    html = response.text

    data: dict = {}
    scraper = None
    try:
        scraper = scrape_html(html, url, supported_only=False)
    except Exception as e:
        print(
            f"recipe-scrapers could not read this page ({e}); "
            "trying page extraction instead",
            file=sys.stderr,
        )

    if scraper is not None:
        title, _ = _safe_scraper_call(scraper, "title")
        ingredients, _ = _safe_scraper_call(scraper, "ingredients")
        instructions, _ = _safe_scraper_call(scraper, "instructions")
        image_url, _ = _safe_scraper_call(scraper, "image")

        data = {
            "title": title or "Untitled Recipe",
            "ingredients": ingredients or [],
            "instructions": instructions or "",
            "image_url": image_url or "",
        }

        for method_name, key_name in [
            ("yields", "yield"),
            ("total_time", "total_time"),
            ("prep_time", "prep_time"),
            ("cook_time", "cook_time"),
        ]:
            val, ok = _safe_scraper_call(scraper, method_name)
            if ok and val:
                data[key_name] = str(val)

    # Pages without schema.org Recipe markup: read the embedded page payload or
    # the rendered recipe card, keeping any values recipe-scrapers did provide.
    if not data.get("ingredients") or not data.get("instructions"):
        fallback = extract_fallback_recipe(html)
        if fallback:
            data = {**fallback, **{key: val for key, val in data.items() if val}}
        if not data.get("ingredients") or not data.get("instructions"):
            raise RuntimeError(
                "no recipe ingredients/directions found — the page has no "
                "schema.org Recipe markup and no recognised recipe card"
            )

    data.setdefault("title", "Untitled Recipe")
    data.setdefault("image_url", "")
    if not data["image_url"]:
        data["image_url"] = meta_image(html)

    # Description: prefer the first intro paragraph (the "what/why" blurb),
    # falling back to the structured description when no paragraph is found.
    description = extract_first_paragraph(html)
    if not description and scraper is not None:
        desc_val, ok = _safe_scraper_call(scraper, "description")
        if ok and desc_val:
            description = shorten_description(str(desc_val))
    data["description"] = description

    derive_times(data)
    return data


def build_markdown(data: dict, image_ref: str, user_tags: list,
                   original_url: str) -> str:
    auto_tags = guess_tags(data.get("title"))
    all_tags = sorted(list(set(auto_tags + (user_tags or []))))
    from datetime import date

    fm = {
        "date_added": date.today(),
        "layout": "recipe",
        "title": data.get("title", "Untitled Recipe"),
        "image": image_ref or "",
        "original_url": original_url,
        "tags": all_tags,
        "ingredients": format_ingredients(data.get("ingredients")),
        "directions": format_instructions(data.get("instructions")),
    }
    for key in ["description", "yield", "prep_time", "cook_time", "total_time"]:
        val = data.get(key)
        if val:
            fm[key] = val
    return render_recipe_markdown(fm)


# ---------------------------------------------------------------------------
# CLI entry point
# ---------------------------------------------------------------------------

def main() -> None:
    parser = argparse.ArgumentParser(description="Scrape a recipe URL and write markdown")
    parser.add_argument("--url", required=True)
    parser.add_argument("--tags", default="")
    args = parser.parse_args()

    user_tags = [t.strip() for t in args.tags.split() if t.strip()]

    print(f"Fetching recipe from {args.url}…")
    try:
        data = fetch_recipe(args.url)
    except Exception as e:
        print(f"ERROR: Failed to fetch recipe: {e}", file=sys.stderr)
        sys.exit(1)

    title = data.get("title")
    if not title:
        title = "Untitled Recipe"
    print(f"Scraped: {title}")
    slug = slugify(title)
    filename = f"{slug}.md"

    images_dir = REPO_ROOT / "recipe_images"
    images_dir.mkdir(parents=True, exist_ok=True)

    image_ref = ""
    image_filename = f"{slug}.jpg"
    image_save_path = images_dir / image_filename

    if data.get("image_url"):
        downloaded = download_image(data["image_url"], args.url, image_save_path)
        if downloaded:
            actual_ext = image_save_path.suffix
            if actual_ext and actual_ext != ".jpg":
                new_name = f"{slug}{actual_ext}"
                image_save_path.rename(images_dir / new_name)
                image_ref = new_name
            else:
                image_ref = image_filename
            print(f"Image saved: {image_ref}")
        else:
            if image_save_path.exists():
                image_save_path.unlink(missing_ok=True)
            print("Image download failed — recipe will have no image")

    md_content = build_markdown(data, image_ref, user_tags, original_url=args.url)
    recipes_dir = REPO_ROOT / "_recipes"
    recipes_dir.mkdir(parents=True, exist_ok=True)
    out_path = recipes_dir / filename
    out_path.write_text(md_content, encoding="utf-8")
    print(f"Written: _recipes/{filename}")


if __name__ == "__main__":
    main()
