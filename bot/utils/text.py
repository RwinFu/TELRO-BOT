"""Safe text helpers: escaping, Markdown-ish -> Telegram HTML, chunking."""

from __future__ import annotations

import html
import re
from collections.abc import Iterable

from bot.constants import TG_CAPTION_LIMIT, TG_TEXT_LIMIT

_CODE_BLOCK_RE = re.compile(r"```([a-zA-Z0-9+#._-]*)\n?(.*?)```", re.DOTALL)
_INLINE_CODE_RE = re.compile(r"`([^`\n]+)`")
_BOLD_RE = re.compile(r"\*\*(.+?)\*\*|__(.+?)__", re.DOTALL)
_ITALIC_RE = re.compile(r"(?<![\w*])\*([^*\n]+)\*(?![\w*])|(?<![\w_])_([^_\n]+)_(?![\w_])")
_STRIKE_RE = re.compile(r"~~(.+?)~~", re.DOTALL)
_LINK_RE = re.compile(r"\[([^\]\n]+)\]\((https?://[^\s)]+|tg://[^\s)]+)\)")
_HEADING_RE = re.compile(r"^(#{1,6})\s+(.+)$", re.MULTILINE)
_QUOTE_RE = re.compile(r"^&gt;\s?(.*)$", re.MULTILINE)
_BULLET_RE = re.compile(r"^\s*[-*•]\s+", re.MULTILINE)
_HR_RE = re.compile(r"^\s*-{3,}\s*$", re.MULTILINE)
_MULTI_NEWLINE_RE = re.compile(r"\n{3,}")


def esc(value: object) -> str:
    """Escape a value for Telegram HTML."""
    return html.escape(str(value), quote=False)


def _escape_outside_tags(text: str) -> str:
    """Escape HTML but keep our generated tags.

    Used by :func:`md_to_html` because the source text is escaped first and then
    decorated, so this helper is only kept for safety when callers pass HTML.
    """
    return html.escape(text, quote=False)


def md_to_html(text: str) -> str:
    """Convert a small, safe subset of Markdown into Telegram HTML.

    The input is HTML-escaped first, so model output can never inject tags.
    Supported: fenced code, inline code, bold, italic, strike, links, headings,
    block quotes, bullets and horizontal rules.
    """
    if not text:
        return ""
    text = _escape_outside_tags(text)

    placeholders: list[str] = []

    def stash(value: str) -> str:
        placeholders.append(value)
        return f"\x00{len(placeholders) - 1}\x00"

    def code_block(match: re.Match[str]) -> str:
        language, code = match.group(1), match.group(2)
        code = code.rstrip("\n")
        if not code.strip():
            return ""
        lang_attr = f' class="language-{esc(language)}"' if language else ""
        return stash(f"<pre><code{lang_attr}>{code}</code></pre>")

    text = _CODE_BLOCK_RE.sub(code_block, text)
    text = _INLINE_CODE_RE.sub(lambda m: stash(f"<code>{m.group(1)}</code>"), text)
    text = _LINK_RE.sub(lambda m: stash(f'<a href="{m.group(2)}">{m.group(1)}</a>'), text)
    text = _BOLD_RE.sub(lambda m: f"<b>{m.group(1) or m.group(2)}</b>", text)
    text = _ITALIC_RE.sub(lambda m: f"<i>{m.group(1) or m.group(2)}</i>", text)
    text = _STRIKE_RE.sub(lambda m: f"<s>{m.group(1)}</s>", text)
    text = _HEADING_RE.sub(lambda m: f"<b>{m.group(2)}</b>", text)
    text = _QUOTE_RE.sub(lambda m: f"<blockquote>{m.group(1)}</blockquote>", text)
    text = _HR_RE.sub("──────────", text)
    text = _BULLET_RE.sub("• ", text)
    text = _MULTI_NEWLINE_RE.sub("\n\n", text)

    # Restore placeholders (they may contain other placeholders in theory).
    for index, value in enumerate(placeholders):
        text = text.replace(f"\x00{index}\x00", value)
    return text.strip()


def strip_markdown(text: str) -> str:
    """Remove the most common markdown markers for plain notifications."""
    text = re.sub(r"```[a-zA-Z0-9]*\n?(.*?)```", r"\1", text, flags=re.DOTALL)
    text = re.sub(r"`([^`]*)`", r"\1", text)
    text = re.sub(r"\*\*(.*?)\*\*", r"\1", text)
    text = re.sub(r"__(.*?)__", r"\1", text)
    text = re.sub(r"~~(.*?)~~", r"\1", text)
    text = re.sub(r"\[([^\]]+)\]\((https?://[^)]+)\)", r"\1", text)
    return text


def chunk_text(text: str, limit: int = TG_TEXT_LIMIT) -> list[str]:
    """Split text on paragraph boundaries so every chunk fits Telegram."""
    if len(text) <= limit:
        return [text]
    chunks: list[str] = []
    remaining = text
    while remaining:
        if len(remaining) <= limit:
            chunks.append(remaining)
            break
        cut = remaining.rfind("\n\n", 0, limit)
        if cut < limit // 2:
            cut = remaining.rfind("\n", 0, limit)
        if cut < limit // 2:
            cut = remaining.rfind(" ", 0, limit)
        if cut < limit // 2:
            cut = limit
        chunks.append(remaining[:cut].rstrip())
        remaining = remaining[cut:].lstrip("\n")
    return [chunk for chunk in chunks if chunk]


def split_html(text: str, limit: int = TG_TEXT_LIMIT) -> list[str]:
    """Convert markdown to HTML and split it safely per chunk.

    Markdown decoration adds tags, so a plain 4000-character chunk can grow past
    Telegram's limit. Chunks that overflow are split recursively; every piece is
    converted independently, keeping tag pairs balanced.
    """
    if not text:
        return []
    if len(text) <= limit:
        converted = md_to_html(text)
        if len(converted) <= limit:
            return [converted]
    result: list[str] = []
    for part in chunk_text(text, max(400, limit // 2)):
        result.extend(_convert_part(part, limit))
    return [chunk for chunk in result if chunk]


def _convert_part(part: str, limit: int) -> list[str]:
    converted = md_to_html(part)
    if len(converted) <= limit:
        return [converted]
    if len(part) < 2:
        return [converted[:limit]]
    cut = part.rfind("\n", 0, len(part) // 2)
    if cut < len(part) // 4:
        cut = part.rfind(" ", 0, len(part) // 2)
    if cut < len(part) // 4:
        cut = len(part) // 2
    return _convert_part(part[:cut], limit) + _convert_part(part[cut:], limit)


def caption_text(text: str, limit: int = TG_CAPTION_LIMIT) -> str:
    return truncate_html(md_to_html(text), limit)


def truncate_html(value: str, limit: int) -> str:
    """Trim plain lenght; safe because callers only pass generated HTML."""
    if len(value) <= limit:
        return value
    return value[: max(0, limit - 1)].rstrip() + "…"


def join_nonempty(parts: Iterable[str | None], separator: str = " · ") -> str:
    return separator.join(part for part in parts if part)


def mention(user_id: int, name: str) -> str:
    return f'<a href="tg://user?id={int(user_id)}">{esc(name)}</a>'


def code(value: object) -> str:
    return f"<code>{esc(value)}</code>"


def b(value: object) -> str:
    return f"<b>{esc(value)}</b>"


def i(value: object) -> str:
    return f"<i>{esc(value)}</i>"
