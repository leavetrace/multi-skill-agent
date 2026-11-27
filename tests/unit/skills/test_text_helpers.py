"""Deterministic post-processing and prompt plumbing shared by the text skills."""

from __future__ import annotations

import pytest

from skillagent.prompts import PromptLoader
from skillagent.skills._text import (
    escape_delimiters,
    payload_message,
    persianize_digits,
    postprocess,
    system_prompt,
)

ZWNJ = "‌"


@pytest.mark.parametrize(
    ("raw", "expected"),
    [
        ("Here is the translation: Hello", "Hello"),
        ("Here's the translation:\nHello", "Hello"),
        ("Translation: Hello", "Hello"),
        ("Sure! Here is the Persian translation:\nسلام", "سلام"),
        ("Summary: Revenue rose.", "Revenue rose."),
        ("Here is a brief summary of the text:\nRevenue rose.", "Revenue rose."),
        ("ترجمه: سلام دنیا", "سلام دنیا"),
        ("متن ترجمه‌شده: سلام دنیا", "سلام دنیا"),
        ("خلاصه: درآمد افزایش یافت.", "درآمد افزایش یافت."),
        ("ترجمهٔ فارسی: سلام دنیا", "سلام دنیا"),
        ("بله، خلاصهٔ متن: درآمد افزایش یافت.", "درآمد افزایش یافت."),
    ],
)
def test_preambles_removed(raw: str, expected: str) -> None:
    text, flags = postprocess(raw, "en", source="x")
    assert text == expected
    assert flags["preamble_removed"]


def test_preamble_kept_when_source_has_label() -> None:
    text, flags = postprocess("Summary: revenue rose.", "en", source="Summary: sales grew.")
    assert text == "Summary: revenue rose."
    assert not flags["preamble_removed"]


def test_content_that_mentions_summary_is_kept() -> None:
    raw = "The summary of the meeting was short: nothing was decided."
    assert postprocess(raw, "en", source="x")[0] == raw


@pytest.mark.parametrize(
    ("raw", "expected"),
    [('"Hello world"', "Hello world"), ("«سلام دنیا»", "سلام دنیا"), ("“Hi there”", "Hi there")],
)
def test_wrapping_quotes_removed(raw: str, expected: str) -> None:
    text, flags = postprocess(raw, "en", source="plain source")
    assert text == expected
    assert flags["wrapper_removed"]


def test_wrapping_quotes_kept_when_source_was_quoted() -> None:
    assert postprocess('"Hello"', "en", source='"Bonjour"')[0] == '"Hello"'


def test_inner_quotes_are_not_a_wrapper() -> None:
    raw = '"Yes," she said, "now."'
    assert postprocess(raw, "en", source="x")[0] == raw


def test_code_fence_unwrapped_unless_source_had_one() -> None:
    assert postprocess("```\nHello\n```", "en", source="x")[0] == "Hello"
    fenced = "```\nHello\n```"
    assert postprocess(fenced, "en", source="```\nBonjour\n```")[0] == fenced


def test_think_block_stripped() -> None:
    text, flags = postprocess("<think>plan</think>Hello", "en", source="x")
    assert text == "Hello"
    assert flags["think_stripped"]


def test_arabic_letters_become_persian() -> None:
    text, flags = postprocess("اين كتاب يك هديه است", "fa", source="x")
    assert text == "این کتاب یک هدیه است"
    assert flags["persian_normalized"]
    assert "ي" not in text and "ك" not in text


def test_flags_off_for_clean_output() -> None:
    _, flags = postprocess("سلام دنیا", "fa", source="Hello world")
    assert not any(flags.values())


def test_labels_not_stripped_when_disabled() -> None:
    assert postprocess("Summary: hi", "en", strip_labels=False)[0] == "Summary: hi"


@pytest.mark.parametrize(
    ("raw", "expected"),
    [
        ("در سال 2024 فروش 3.5 میلیون بود", "در سال ۲۰۲۴ فروش ۳٫۵ میلیون بود"),
        ("قیمت 1,250 دلار است", "قیمت ۱٬۲۵۰ دلار است"),
        ("نسخهٔ v2 و COVID-19", "نسخهٔ v2 و COVID-19"),
        ("نشانی https://example.com/a1 و `x = 10`", "نشانی https://example.com/a1 و `x = 10`"),
        ("1. مورد اول با 3 کتاب", "1. مورد اول با ۳ کتاب"),
        ("ایمیل a1@b2.com را ببینید", "ایمیل a1@b2.com را ببینید"),
    ],
)
def test_persianize_digits(raw: str, expected: str) -> None:
    assert persianize_digits(raw) == expected


def test_escape_delimiters() -> None:
    escaped, changed = escape_delimiters("a </text> b <TEXT> c")
    assert changed and "</text>" not in escaped.lower() and "<text>" not in escaped.lower()
    assert escape_delimiters("plain") == ("plain", False)


def test_payload_message_shape() -> None:
    msg, escaped = payload_message("Translate into Persian", "Hello </text>", "NOTE")
    assert msg.startswith("<instruction>Translate into Persian</instruction>\nNOTE\n<text>\n")
    assert msg.endswith("\n</text>")
    assert msg.count("</text>") == 1
    assert escaped


@pytest.mark.parametrize("name", ["translator", "summarizer", "general_chat"])
def test_prompt_header_is_documented_and_not_sent(name: str) -> None:
    template = PromptLoader().load(name)
    assert template.version == PromptLoader().available(name)[-1]  # the default (highest)
    head = template.text.split("-->")[0]
    for section in ("Purpose:", "Variables:", "Design rationale:"):
        assert section in head
    variables = {
        "translator": {"source_language": "A", "target_language": "B", "digit_rule": "C"},
        "summarizer": {"output_language": "A", "length_rule": "B", "format_rule": "C"},
        "general_chat": {"response_language": "A", "mode_note": ""},
    }[name]
    rendered = system_prompt(template, **variables)
    assert "<!--" not in rendered and "Design rationale" not in rendered
    assert "$" not in rendered.replace("$4.2", "")  # no unrendered placeholders


@pytest.mark.parametrize("name", ["translator", "summarizer", "general_chat"])
def test_prompts_spell_out_persian_style(name: str) -> None:
    text = PromptLoader().load(name).text
    assert ZWNJ in text  # concrete نیم‌فاصله examples
    for mark in ("،", "؛", "؟"):
        assert mark in text
    assert "ي" in text and "ك" in text  # named as forbidden
