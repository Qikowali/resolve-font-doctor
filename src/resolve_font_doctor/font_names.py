from __future__ import annotations

import re
import unicodedata
from difflib import SequenceMatcher


STYLE_WORDS = {
    "thin",
    "extralight",
    "ultralight",
    "semilight",
    "demilight",
    "light",
    "book",
    "regular",
    "roman",
    "normal",
    "medium",
    "semibold",
    "demibold",
    "bold",
    "extrabold",
    "ultrabold",
    "black",
    "heavy",
    "extrablack",
    "ultrablack",
    "italic",
    "oblique",
    "ital",
    "slanted",
}

NOISE_WORDS = {
    "demo",
    "trial",
    "free",
    "personal",
    "use",
    "for",
    "version",
    "ver",
    "web",
    "webfont",
}

WIDTH_WORDS = {"condensed", "narrow", "compressed", "extended", "expanded", "wide"}

# Values that are not real font families, or are internal Resolve constructs.
SKIP_NAMES = {
    "default",
    "default font",
    "none",
    "null",
    "system",
    "system font",
    "fusion shapes",
    "fusion shape",
    "fusion icons",
    "fusion icons 2",
    "resolve",
    "blackmagic design",
}

PLACEHOLDER_VALUES = {
    "",
    "-",
    "--",
    "n/a",
    "na",
    "unknown",
    "undefined",
}

_FONT_EXTENSIONS = {".ttf", ".otf", ".ttc", ".otc", ".woff", ".woff2", ".dfont"}


def nfkc(text: str) -> str:
    return unicodedata.normalize("NFKC", text or "")


def normalize_name(text: str) -> str:
    """Aggressive comparison key; keeps letters/digits from any script."""
    text = nfkc(text).casefold().replace("&", "and")
    # Keep alphanumerics only. This makes "Open Sans" == "OpenSans" and
    # ignores hyphens, spaces and punctuation used inconsistently by vendors.
    return "".join(ch for ch in text if ch.isalnum())


def normalize_words(text: str) -> list[str]:
    text = nfkc(text).casefold().replace("&", " and ")
    text = re.sub(r"[^\w]+", " ", text, flags=re.UNICODE)
    return [w for w in text.split() if w]


def strip_style(text: str) -> str:
    words = normalize_words(text)
    while words and words[-1] in STYLE_WORDS:
        words.pop()
    return "".join(words)


def strip_style_and_noise(text: str) -> str:
    words = normalize_words(text)
    changed = True
    while changed and words:
        changed = False
        if words and words[-1] in STYLE_WORDS | NOISE_WORDS | {"caps"}:
            words.pop()
            changed = True
    return "".join(words)


def strip_width(text: str) -> str:
    words = [w for w in normalize_words(text) if w not in WIDTH_WORDS]
    return "".join(words)


def candidate_variants(name: str, include_width: bool = True) -> list[str]:
    """Ordered keys, strongest first."""
    variants: list[str] = []
    for value in (normalize_name(name), strip_style(name), strip_style_and_noise(name)):
        if value and value not in variants:
            variants.append(value)
    if include_width:
        for base in (strip_style(name), strip_style_and_noise(name)):
            widthless = strip_width(base)
            if widthless and widthless not in variants:
                variants.append(widthless)
    return variants


def is_plausible_font_name(value: str) -> bool:
    if not isinstance(value, str):
        return False
    value = value.strip().strip("\x00")
    if not value or value.casefold() in PLACEHOLDER_VALUES:
        return False
    if len(value) > 96:
        return False
    if "\n" in value or "\r" in value or "\t" in value:
        return False
    if value.startswith(("$", "{", "}", "<", "//")):
        return False
    if re.search(r"[\\/:*?<>|]", value):
        return False
    if value.startswith("."):
        return False
    lower = value.casefold()
    if lower in SKIP_NAMES:
        return False
    if re.fullmatch(r"[\d\W_]+", value):
        return False
    if re.fullmatch(r"[\d.]+(?:pt|px|em|rem)?", lower):
        return False
    ext = "." + lower.rsplit(".", 1)[-1] if "." in lower else ""
    if ext in _FONT_EXTENSIONS:
        return False
    return True


def is_skip_name(value: str) -> bool:
    return (value or "").strip().casefold() in SKIP_NAMES


def slug_for_google(name: str) -> str:
    text = nfkc(name).casefold().replace("&", "and")
    return re.sub(r"[^a-z0-9]", "", text)


def similarity(a: str, b: str) -> float:
    return SequenceMatcher(None, a, b).ratio()


def pretty_family(name: str) -> str:
    return re.sub(r"\s+", " ", nfkc(name)).strip()


def style_from_name(name: str) -> str:
    words = normalize_words(name)
    styles: list[str] = []
    for word in words:
        if word in STYLE_WORDS:
            styles.append(word)
    return " ".join(styles)
