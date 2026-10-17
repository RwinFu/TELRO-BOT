"""Tiny JSON based internationalisation layer (Persian + English)."""

from __future__ import annotations

import json
import logging
from collections.abc import Iterator
from pathlib import Path
from typing import Any

log = logging.getLogger(__name__)

DEFAULT_LANGUAGE = "fa"
SUPPORTED_LANGUAGES = ("fa", "en")
LANGUAGE_NAMES = {"fa": "فارسی", "en": "English"}
LOCALES_DIR = Path(__file__).resolve().parent / "locales"


def flatten(data: dict[str, Any], prefix: str = "") -> dict[str, str]:
    """Turn nested JSON into a dot separated flat dictionary."""
    result: dict[str, str] = {}
    for key, value in data.items():
        full_key = f"{prefix}.{key}" if prefix else key
        if isinstance(value, dict):
            result.update(flatten(value, full_key))
        else:
            result[full_key] = str(value)
    return result


class Translator:
    def __init__(self, locales_dir: Path = LOCALES_DIR) -> None:
        self.locales_dir = locales_dir
        self._data: dict[str, dict[str, str]] = {}
        self.load()

    def load(self) -> None:
        self._data = {}
        for lang in SUPPORTED_LANGUAGES:
            path = self.locales_dir / f"{lang}.json"
            try:
                with path.open("r", encoding="utf-8") as handle:
                    self._data[lang] = flatten(json.load(handle))
            except (OSError, json.JSONDecodeError) as exc:  # pragma: no cover - dev mistake
                log.error("Failed to load locale %s: %s", path, exc)
                self._data[lang] = {}

    @property
    def languages(self) -> tuple[str, ...]:
        return tuple(lang for lang in SUPPORTED_LANGUAGES if self._data.get(lang))

    def get(self, lang: str | None, key: str, /, **kwargs: Any) -> str:
        lang = lang if lang in SUPPORTED_LANGUAGES else DEFAULT_LANGUAGE
        template = self._data.get(lang, {}).get(key)
        if template is None:
            template = self._data.get(DEFAULT_LANGUAGE, {}).get(key, key)
        if not kwargs:
            return template
        try:
            return template.format(**kwargs)
        except (KeyError, IndexError, ValueError):
            log.warning("Bad format string for %s/%s: %r", lang, key, template)
            return template

    def variants(self, key: str) -> Iterator[str]:
        for lang in self.languages:
            value = self._data.get(lang, {}).get(key)
            if value:
                yield value

    def has(self, lang: str, key: str) -> bool:
        return key in self._data.get(lang, {})


i18n = Translator()


def normalize_language(code: str | None) -> str:
    if not code:
        return DEFAULT_LANGUAGE
    code = code.lower().split("-")[0]
    return code if code in SUPPORTED_LANGUAGES else DEFAULT_LANGUAGE
