"""Application translations; English source strings and ASCII JSON catalogs."""
from functools import lru_cache
import json
import os
from pathlib import Path

CATALOG_DIR = Path(__file__).with_name("locales")
LANGUAGES = (("system", "System default"), ("en", "English"), ("de", "German"),
             ("es", "Spanish"), ("fr", "French"), ("it", "Italian"),
             ("pt_BR", "Portuguese (Brazil)"), ("ru", "Russian"))
_language = "system"


def resolve_language(code):
    """Resolve POSIX/BCP-47 locale identifiers with a safe English fallback."""
    code = code.split(".", 1)[0].split("@", 1)[0].replace("-", "_")
    if code in ("C", "POSIX", ""):
        return "en"
    codes = {code for code, _label in LANGUAGES if code != "system"}
    if code in codes:
        return code
    base = code.split("_", 1)[0].lower()
    if base == "pt":
        return "pt_BR"
    return base if base in codes else "en"


def system_language():
    locale = os.environ.get("LC_ALL") or os.environ.get("LC_MESSAGES") or os.environ.get("LANG", "en")
    if resolve_language(locale) == "en" and locale.split(".")[0] in ("C", "POSIX"):
        return "en"
    preferred = os.environ.get("LANGUAGE", "")
    for code in preferred.split(":"):
        language = resolve_language(code)
        if language != "en" or code.lower().startswith("en"):
            return language
    return resolve_language(locale)


def set_language(code):
    global _language
    if code not in dict(LANGUAGES):
        raise ValueError("Unsupported application language")
    _language = code


def get_language():
    return _language


@lru_cache(maxsize=None)
def catalog(code):
    try:
        return json.loads((CATALOG_DIR / f"{code}.json").read_text(encoding="ascii"))
    except FileNotFoundError:
        return {}


def _(text):
    code = system_language() if _language == "system" else _language
    return catalog(code).get(text, text)
