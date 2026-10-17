from __future__ import annotations

import json
import re
from pathlib import Path

from bot.i18n import LOCALES_DIR, Translator, flatten

PLACEHOLDER_RE = re.compile(r"{(\w+)}")


def load(lang: str) -> dict[str, str]:
    with (Path(LOCALES_DIR) / f"{lang}.json").open(encoding="utf-8") as handle:
        return flatten(json.load(handle))


def test_locale_files_have_identical_keys():
    fa = load("fa")
    en = load("en")
    assert set(fa) == set(en)
    assert len(fa) > 200


def test_placeholders_match_between_languages():
    fa = load("fa")
    en = load("en")
    mismatched = []
    for key in fa:
        if set(PLACEHOLDER_RE.findall(fa[key])) != set(PLACEHOLDER_RE.findall(en[key])):
            mismatched.append(key)
    assert not mismatched, mismatched


def test_no_empty_strings():
    for lang in ("fa", "en"):
        assert all(value.strip() for value in load(lang).values())


def test_translator_fallback_and_formatting():
    translator = Translator()
    assert "TELRO" in translator.get("fa", "welcome.title")
    assert translator.get("en", "welcome.title").startswith("🎬")
    text = translator.get("fa", "welcome.stats", downloads=5, limit=10)
    assert "5" in text and "10" in text
    # Unknown language falls back to Persian
    assert translator.get("de", "welcome.title") == translator.get("fa", "welcome.title")
    # Unknown key returns the key itself
    assert translator.get("fa", "no.such.key") == "no.such.key"
