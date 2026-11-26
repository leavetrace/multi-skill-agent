from __future__ import annotations

import json

import pytest

from skillagent.core.language import (
    detect_lang_hint,
    estimate_tokens,
    extract_json_object,
    normalize_lang_code,
    normalize_persian,
    strip_think,
    to_ascii_digits,
    to_persian_digits,
    truncate_to_tokens,
)

ZWNJ = "‌"


class TestNormalizePersian:
    def test_arabic_letters_become_persian(self) -> None:
        assert normalize_persian("علي كتاب مى") == "علی کتاب می"

    def test_tatweel_removed(self) -> None:
        assert normalize_persian("سـلـام") == "سلام"

    def test_repeated_zwnj_collapsed(self) -> None:
        assert normalize_persian(f"می{ZWNJ}{ZWNJ}{ZWNJ}خواهم") == f"می{ZWNJ}خواهم"

    def test_zwnj_next_to_space_removed(self) -> None:
        assert normalize_persian(f"کتاب{ZWNJ} ها و {ZWNJ}دفتر") == "کتاب ها و دفتر"

    def test_zwnj_exposed_by_tatweel_removal_is_collapsed(self) -> None:
        assert normalize_persian(f"می{ZWNJ}ـ{ZWNJ}روم") == f"می{ZWNJ}روم"

    def test_digits_and_other_text_unchanged(self) -> None:
        text = "قیمت ۱۲۳ و ٤٥٦ تومان, price 789!"
        assert normalize_persian(text) == text

    @pytest.mark.parametrize(
        "text", ["علي  كـتاب", f"a{ZWNJ}{ZWNJ} b", "plain English", f"{ZWNJ}ـ{ZWNJ}ي"]
    )
    def test_idempotent(self, text: str) -> None:
        once = normalize_persian(text)
        assert normalize_persian(once) == once


class TestDigits:
    def test_persian_and_arabic_indic_to_ascii(self) -> None:
        assert to_ascii_digits("۰۱۲۳۴۵۶۷۸۹ ٠١٢٣٤٥٦٧٨٩") == "0123456789 0123456789"

    def test_persian_decimal_separator(self) -> None:
        assert to_ascii_digits("۳٫۵") == "3.5"

    def test_thousands_separator_between_digits_removed(self) -> None:
        assert to_ascii_digits("۱٬۲۰۰ × ۳٫۵") == "1200 × 3.5"

    def test_thousands_separator_elsewhere_kept(self) -> None:
        assert to_ascii_digits("الف٬ ب") == "الف٬ ب"

    def test_to_persian_digits(self) -> None:
        assert to_persian_digits("1200 and 3.5.") == "۱۲۰۰ and ۳٫۵."

    def test_to_persian_leaves_text_alone(self) -> None:
        assert to_persian_digits("end. Next") == "end. Next"

    def test_round_trip(self) -> None:
        assert to_ascii_digits(to_persian_digits("12.75")) == "12.75"


class TestDetectLangHint:
    @pytest.mark.parametrize(
        ("text", "expected"),
        [
            ("سلام، حالت چطوره؟", "fa"),
            ("Hello, how are you?", "en"),
            ("salam, chetori? khoobi?", "en"),  # Finglish is Latin script → en
            ("این متن را translate کن please", "mixed"),
            ("😀🎉 123 !!!", "unknown"),
            ("", "unknown"),
            ("۱۲۳ + ۴۵۶", "unknown"),  # digits are not letters
            ("مرحبا بالعالم", "fa"),  # Arabic script counts as fa-side (router decides)
        ],
    )
    def test_hints(self, text: str, expected: str) -> None:
        assert detect_lang_hint(text) == expected

    def test_mostly_persian_with_one_word_english_is_fa(self) -> None:
        assert detect_lang_hint("لطفا این متن طولانی فارسی را خلاصه کن ok") == "fa"


class TestEstimateTokens:
    def test_empty_is_zero(self) -> None:
        assert estimate_tokens("") == 0

    def test_non_empty_minimum_one(self) -> None:
        assert estimate_tokens("a") == 1
        assert estimate_tokens("   ") == 1

    def test_english_rate(self) -> None:
        assert estimate_tokens("abcdefgh") == 2  # 8 / 4

    def test_persian_costs_more_per_char(self) -> None:
        assert estimate_tokens("سلامسلام") == 4  # ceil(8 / 2.5)
        assert estimate_tokens("سلامسلام") > estimate_tokens("abcdefgh")

    def test_other_scripts_and_emoji(self) -> None:
        assert estimate_tokens("😀😀😀") == 2  # 3 / 1.5

    def test_whitespace_not_counted(self) -> None:
        assert estimate_tokens("ab cd") == estimate_tokens("abcd")


class TestTruncate:
    def test_within_budget_unchanged(self) -> None:
        assert truncate_to_tokens("short text", 100) == ("short text", False)

    def test_cuts_at_sentence_boundary(self) -> None:
        text = "First sentence here. Second sentence is much longer than the first one."
        out, truncated = truncate_to_tokens(text, 10)
        assert truncated
        assert out == "First sentence here."

    def test_persian_question_mark_is_boundary(self) -> None:
        text = "این یک پرسش است؟ و این جملهٔ دوم بسیار بسیار طولانی‌تر از اولی است."
        out, truncated = truncate_to_tokens(text, 10)
        assert truncated
        assert out == "این یک پرسش است؟"

    def test_falls_back_to_whitespace_never_mid_word(self) -> None:
        text = "alpha beta gamma delta epsilon zeta eta theta iota kappa"
        out, truncated = truncate_to_tokens(text, 5)
        assert truncated
        assert estimate_tokens(out) <= 5
        assert text.startswith(out)
        assert text[len(out)] == " "  # the next char is a space → no word was split

    def test_decimal_point_is_not_a_sentence_end(self) -> None:
        # The 2-token prefix is "Pi is 3.14"; a naive "." cut would return "Pi is 3."
        assert truncate_to_tokens("Pi is 3.14159 roughly", 2) == ("Pi is", True)

    def test_single_long_word_yields_empty(self) -> None:
        assert truncate_to_tokens("x" * 100, 3) == ("", True)

    def test_zero_budget(self) -> None:
        assert truncate_to_tokens("anything", 0) == ("", True)

    @pytest.mark.parametrize("budget", [1, 2, 3, 5, 8, 13])
    def test_result_always_fits(self, budget: int) -> None:
        text = "یک دو سه. چهار پنج شش! seven eight nine? ده یازده دوازده"
        out, _ = truncate_to_tokens(text, budget)
        assert estimate_tokens(out) <= budget
        assert text.startswith(out)


class TestNormalizeLangCode:
    @pytest.mark.parametrize(
        ("value", "expected"),
        [
            ("fa", "fa"),
            ("EN", "en"),
            ("fr-FR", "fr"),
            ("pt_BR", "pt"),
            ("Persian", "fa"),
            ("Farsi", "fa"),
            ("english", "en"),
            ("German", "de"),
            ("French", "fr"),
            ("Arabic", "ar"),
            ("Spanish", "es"),
            ("Turkish", "tr"),
            ("Chinese", "zh"),
            ("Russian", "ru"),
            ("Italian", "it"),
            ("Japanese", "ja"),
            ("فارسی", "fa"),
            ("انگلیسی", "en"),
            ("آلمانی", "de"),
            ("فرانسوی", "fr"),
            ("عربی", "ar"),
            ("ترکی", "tr"),
            ("اسپانیایی", "es"),
            ("روسی", "ru"),
            ("چینی", "zh"),
            ("زبان فارسی", "fa"),
            ("فارسي", "fa"),  # Arabic yeh is normalized first
            ("the English language", "en"),
            ("fas", "fa"),
            ("eng", "en"),
            ("  de  ", "de"),
        ],
    )
    def test_known(self, value: str, expected: str) -> None:
        assert normalize_lang_code(value) == expected

    @pytest.mark.parametrize("value", ["Klingon", "xx", "", "abcd", "زبان خیالی"])
    def test_unknown_raises(self, value: str) -> None:
        with pytest.raises(ValueError, match="unknown language"):
            normalize_lang_code(value)

    def test_non_string_raises_value_error(self) -> None:
        with pytest.raises(ValueError, match="must be a string"):
            normalize_lang_code(3)


class TestStripThink:
    def test_removes_block(self) -> None:
        assert strip_think("<think>reasoning\nmore</think>\nAnswer") == "Answer"

    def test_case_insensitive_and_multiple(self) -> None:
        assert strip_think("<THINK>a</THINK>x <think>b</think>y") == "x y"

    def test_unterminated_leading_block(self) -> None:
        assert strip_think("  <think>still thinking when tokens ran out") == ""

    def test_orphan_closing_tag(self) -> None:
        assert strip_think("template-injected reasoning</think>\n\nFinal") == "Final"

    def test_no_think_unchanged_but_stripped(self) -> None:
        assert strip_think("  plain answer \n") == "plain answer"

    def test_gemma_thought_blocks(self) -> None:
        # Observed in WP0/WP3 on gemma-4-31b-it via the Gemini OpenAI endpoint.
        assert strip_think("<thought>plan the reply</thought>Paris") == "Paris"
        assert strip_think('<thought>x</thought>{"city": "Paris"}') == '{"city": "Paris"}'
        assert strip_think("<thought>ran out of tokens") == ""
        reply = "<thought>be warm</thought>\n<message>سلام! خوبم، ممنون.</message>"
        assert strip_think(reply) == "سلام! خوبم، ممنون."

    def test_message_tag_kept_when_not_a_lone_wrapper(self) -> None:
        text = "Use <message> tags like <message>this</message> in your template."
        assert strip_think(text) == text


class TestExtractJsonObject:
    def test_plain(self) -> None:
        assert extract_json_object('{"a": 1}') == '{"a": 1}'

    def test_fenced(self) -> None:
        text = 'Sure! Here you go:\n```json\n{"a": {"b": [1, 2]}}\n```\nAnything else?'
        assert json.loads(extract_json_object(text)) == {"a": {"b": [1, 2]}}

    def test_fence_preferred_over_stray_braces_in_prose(self) -> None:
        text = 'Use {placeholders} like this:\n```\n{"ok": true}\n```'
        assert json.loads(extract_json_object(text)) == {"ok": True}

    def test_braces_and_escaped_quotes_inside_strings(self) -> None:
        text = 'noise {"text": "a } b \\" { c", "n": 2} trailing }'
        assert json.loads(extract_json_object(text)) == {"text": 'a } b " { c', "n": 2}

    def test_first_of_several_objects(self) -> None:
        assert extract_json_object('{"first": 1} {"second": 2}') == '{"first": 1}'

    def test_skips_unbalanced_prefix(self) -> None:
        assert json.loads(extract_json_object('broken { here\n{"ok": 1}')) == {"ok": 1}

    def test_persian_content(self) -> None:
        text = '{"response_language": "fa", "q": "متن را بفرست؟"}'
        assert json.loads(extract_json_object(text))["q"] == "متن را بفرست؟"

    @pytest.mark.parametrize("text", ["", "no json here", "{ unbalanced", "[1, 2]"])
    def test_none_raises(self, text: str) -> None:
        with pytest.raises(ValueError, match="no JSON object"):
            extract_json_object(text)
