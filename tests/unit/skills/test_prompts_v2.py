"""Text-skill prompt v2 (WP7a): same variables as v1, documented changes, Persian rules,
v1 frozen as the measured baseline, and pinning selects either version end to end."""

from __future__ import annotations

import re
from string import Template

import pytest

from skillagent.config import Settings
from skillagent.prompts import PromptLoader
from skillagent.skills import general_chat, summarizer, translator
from skillagent.skills._text import system_prompt
from skillagent.skills.base import SkillContext

# Only translator v2 shipped: the owner's blind A/B preferred v1 for summarizer and general_chat
# (ADR-032). Their v2 drafts stay in git history (commit 80d9c31 / cc1d955 / 42f668a).
NAMES = ("translator",)
# v1 is the measured baseline (WP3 samples, dev baseline, test run 1): its text must not move.
V1_SHA = {
    "summarizer": "987b3e151b77",
    "translator": "0b4f7564d8aa",
    "general_chat": "e24622e64c50",
}
VARIABLES = {
    "translator": {
        "source_language": "English",
        "target_language": "Persian (Farsi)",
        "digit_rule": "D",
    },
    "summarizer": {"output_language": "Persian (Farsi)", "length_rule": "L", "format_rule": "F"},
    "general_chat": {"response_language": "Persian (Farsi)", "mode_note": ""},
}
# One marker per v2 change that must reach the model (the header comment is stripped).
V2_MARKERS = {
    "summarizer": ("به رهبری", "«اعلام کرد»", "Advice, requests and warnings", "Restructure"),
    "translator": (
        "«رایانش ابری»",
        "درصدی",
        "what the speaker means",
        "«این آخر هفته»",
        "All members",
    ),
    "general_chat": ("می‌تونی", "clichés", "concrete things you can do", "This request"),
}
# Rendered text for a request of the matching skill → (runner, params) for the pinning test.
RUNNERS = {
    "summarizer": (summarizer.run, {"output_language": "fa"}),
    "translator": (translator.run, {"target_language": "fa"}),
    "general_chat": (general_chat.run, {}),
}
_SAMPLE_TEXT = " ".join(["The council approved the new budget for public transport."] * 6)


def _identifiers(text: str) -> set[str]:
    return set(Template(text).get_identifiers())


@pytest.mark.parametrize("name", NAMES)
def test_v1_and_v2_both_ship_and_v2_is_default(name: str) -> None:
    loader = PromptLoader()
    assert loader.available(name) == [1, 2]
    assert loader.load(name).version == 2


@pytest.mark.parametrize("name", NAMES)
def test_v1_is_unchanged(name: str) -> None:
    assert PromptLoader().load(name, 1).sha == V1_SHA[name]


@pytest.mark.parametrize("name", NAMES)
def test_v2_uses_exactly_the_v1_variables(name: str) -> None:
    loader = PromptLoader()
    v1, v2 = loader.load(name, 1), loader.load(name, 2)
    assert _identifiers(v2.text) == _identifiers(v1.text) == set(VARIABLES[name])
    rendered = system_prompt(v2, **VARIABLES[name])
    assert "<!--" not in rendered and "Changes from v1" not in rendered
    assert not re.search(r"\$[A-Za-z_{]", rendered)  # no unrendered placeholder


@pytest.mark.parametrize("name", NAMES)
def test_v2_header_documents_each_change_with_a_reason(name: str) -> None:
    head = PromptLoader().load(name, 2).text.split("-->")[0]
    for section in ("Purpose:", "Variables:", "Design rationale:", "Changes from v1"):
        assert section in head
    changes = re.findall(r"^\s+\d\. (.+?)(?=^\s+\d\. |\Z)", head, flags=re.M | re.S)
    assert len(changes) >= 4
    for change in changes:
        assert "→" in change, change
        assert re.search(r"\b[stc]\d\b|WP0 item \d", change), change  # tied to a sample id


@pytest.mark.parametrize("name", NAMES)
def test_v2_keeps_the_persian_rules_and_adds_the_targeted_ones(name: str) -> None:
    rendered = system_prompt(PromptLoader().load(name, 2), **VARIABLES[name])
    assert "نیم‌فاصله" in rendered and "«،»" in rendered
    assert "never the Arabic ي and ك" in rendered or "never ي and ك" in rendered
    for marker in V2_MARKERS[name]:
        assert marker in rendered, marker
    for line in rendered.splitlines():  # Arabic ي/ك appear only inside the rule forbidding them
        if "ي" in line or "ك" in line:
            assert "never" in line, line


@pytest.mark.parametrize("version", [1, 2])
@pytest.mark.parametrize("name", NAMES)
async def test_pinning_selects_the_version_end_to_end(
    name: str, version: int, fake, make_input, sent
) -> None:
    pins = ",".join(f"{n}={version}" for n in NAMES)  # what SKILLAGENT_PROMPT_VERSIONS holds
    settings = Settings(
        llm_provider="google", google_api_key="AIza-test-0000", llm_rpm=0, prompt_versions=pins
    )
    llm = fake("خلاصه")
    ctx = SkillContext(llm=llm, settings=settings, prompts=PromptLoader.from_settings(settings))
    runner, params = RUNNERS[name]
    out = await runner(make_input(_SAMPLE_TEXT, params=params, lang="fa"), ctx)
    assert out.status == "ok"
    assert out.meta["prompt_version"] == version
    assert out.meta["prompt_sha"] == PromptLoader().load(name, version).sha
    system, _ = sent(llm)
    assert (V2_MARKERS[name][0] in system) is (version == 2)
