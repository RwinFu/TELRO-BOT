from __future__ import annotations

import re

from bot.constants import TG_TEXT_LIMIT
from bot.utils.text import chunk_text, esc, md_to_html, split_html, strip_markdown


def test_escaping_blocks_html_injection():
    result = md_to_html("<script>alert(1)</script>")
    assert "<script>" not in result
    assert "&lt;script&gt;" in result


def test_markdown_basics():
    assert md_to_html("**bold**") == "<b>bold</b>"
    assert md_to_html("*italic*") == "<i>italic</i>"
    assert md_to_html("~~gone~~") == "<s>gone</s>"
    assert md_to_html("`x < y`") == "<code>x &lt; y</code>"
    assert md_to_html("[site](https://example.com)") == '<a href="https://example.com">site</a>'


def test_code_block():
    result = md_to_html("```python\nprint('hi')\n```")
    assert "<pre><code" in result
    assert "print('hi')" in result


def test_headings_quotes_bullets():
    result = md_to_html("# Title\n\n> quote\n\n- one\n- two")
    assert "<b>Title</b>" in result
    assert "<blockquote>quote</blockquote>" in result
    assert "• one" in result


def test_split_html_respects_limit_and_balances_tags():
    text = ("**bold** " * 1200).strip()
    chunks = split_html(text)
    assert len(chunks) > 1
    assert all(len(chunk) <= TG_TEXT_LIMIT for chunk in chunks)
    for chunk in chunks:
        assert chunk.count("<b>") == chunk.count("</b>")


def test_chunk_text_and_strip():
    chunks = chunk_text("a\n\n" * 5000, limit=1000)
    assert all(len(chunk) <= 1000 for chunk in chunks)
    plain = strip_markdown("**hello** `world` [x](https://a.b)")
    assert plain == "hello world x"
    assert esc("<b>") == "&lt;b&gt;"
    assert not re.search(r"<[a-z]", md_to_html("a < b > c"))
