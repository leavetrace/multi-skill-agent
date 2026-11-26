"""General chat: greetings, small talk, general knowledge, and the no-match fallback.

Unlike the payload skills, the user's message here *is* the request, so it goes in
`<message>` (to answer) instead of `<text>` (to process as data). A chained input — a
previous step's output — is still data and goes in `<text>`. The router's restatement in
`<task>` tells the model which part of a multi-task message is its own.
"""

from __future__ import annotations

from typing import Any

from skillagent.core.language import estimate_tokens
from skillagent.core.types import SkillInput, SkillOutput
from skillagent.skills._text import (
    UiLang,
    build_messages,
    escape_delimiters,
    language_name,
    localized,
    postprocess,
    prompt_meta,
    require_text,
    system_prompt,
    truncation_note,
    ui_lang,
    was_truncated,
)
from skillagent.skills.base import RouterExample, SkillBudget, SkillContext, SkillSpec

__all__ = ["BUDGET", "PROMPT_NAME", "PURPOSE", "SPEC", "run"]

BUDGET = SkillBudget(max_input_tokens=1500, max_output_tokens=600, timeout_s=25, temperature=0.7)
PROMPT_NAME = "general_chat"
PURPOSE = "skill:general_chat"

_DEGRADED_NOTE = (
    "\n# This request\nThe request could not be classified precisely. Reply to the message "
    "as helpfully as you can within the rules above. Never mention routing, errors, "
    "components or any internal detail."
)
_TOO_LONG: dict[UiLang, str] = {
    "en": "Your message is too long for me to answer in one go (about {tokens} tokens; the "
    "limit is {limit}). If you'd like, ask me to summarize the text first.",
    "fa": "پیام شما برای پاسخ در یک مرحله بیش از حد طولانی است (حدود {tokens} توکن؛ سقف "
    "{limit} توکن است). اگر بخواهید، می‌توانم اول متن را خلاصه کنم.",
}


def _user_message(inp: SkillInput) -> tuple[str, bool]:
    task, esc_a = escape_delimiters(inp.instruction)
    text, esc_b = escape_delimiters(inp.text.strip())
    if inp.is_chained:
        body = f"<task>{task}</task>\n<text>\n{text}\n</text>"
    else:
        body = f"<task>{task}</task>\n<message>\n{text}\n</message>"
    return body, esc_a or esc_b


async def run(inp: SkillInput, ctx: SkillContext) -> SkillOutput:
    lang = ui_lang(inp.response_language)
    degraded = bool(inp.params.get("degraded"))
    tokens = estimate_tokens(inp.text)
    meta: dict[str, Any] = {
        "degraded": degraded,
        "input_tokens": tokens,
        "response_language": inp.response_language,
        "llm_calls": 0,
    }
    if tokens > BUDGET.max_input_tokens:
        return SkillOutput(
            status="rejected",
            output=localized(_TOO_LONG[lang], lang, tokens=tokens, limit=BUDGET.max_input_tokens),
            meta=meta | {"reason": "too_long"},
        )

    prompt = ctx.prompts.load(PROMPT_NAME)
    system = system_prompt(
        prompt,
        response_language=language_name(inp.response_language),
        mode_note=_DEGRADED_NOTE if degraded else "",
    )
    user, escaped = _user_message(inp)
    response = await ctx.llm.complete(
        build_messages(system, user),
        temperature=BUDGET.temperature,
        max_tokens=BUDGET.max_output_tokens,
        purpose=PURPOSE,
    )
    text, flags = postprocess(
        require_text(response, "general_chat"), inp.response_language, strip_labels=False
    )
    truncated = was_truncated(response)
    if truncated:
        text = f"{text}\n\n{truncation_note(lang)}"
    meta |= prompt_meta(prompt) | {
        "llm_calls": 1,
        "postprocess": flags,
        "delimiters_escaped": escaped,
        "truncated_output": truncated,
    }
    return SkillOutput(status="ok", output=text, meta=meta)


SPEC = SkillSpec(
    name="general_chat",
    description=(
        "Conversational replies: greetings, small talk, general-knowledge questions and "
        "explanations from the model's own knowledge; also the fallback for requests no "
        "other skill covers (it explains honestly what the assistant can and cannot do)."
    ),
    when_to_use=(
        "Greetings, thanks and small talk: 'hi, how are you?', 'thanks!', 'salam chetori?' "
        "(Finglish: reply in Persian script).",
        "سلام و احوال‌پرسی، تشکر و گفت‌وگوی دوستانه: «سلام، خوبی؟»، «مرسی»، «حالم خوب نیست».",
        "General-knowledge questions and explanations: 'what is photosynthesis?', 'explain "
        "how a derivative works', «پایتخت ژاپن کجاست؟»، «تورم یعنی چه؟».",
        "Requests the assistant cannot perform (book a flight, set an alarm, browse the web, "
        "today's weather or prices): it says so and offers what it can do.",
        "پرسش‌هایی که به زبان فارسی پرسیده شده‌اند و پاسخ می‌خواهند، نه ترجمه؛ و هر درخواستی "
        "که هیچ مهارت دیگری پوشش نمی‌دهد.",
    ),
    when_not_to_use=(
        "Any numeric computation, including word problems and Persian number words → "
        "calculator (explaining a math concept without computing stays here).",
        "Translating a given text, even a short phrase → translator. But answering a question "
        "*in* Persian ('answer in Persian: …') is general_chat with response_language=fa.",
        "Condensing a given text → summarizer.",
    ),
    examples=(
        RouterExample(prompt="Hi! How are you today?", plan="general_chat(user)"),
        RouterExample(prompt="salam, chetori? khubi?", plan="general_chat(user)"),
        RouterExample(
            prompt="«یک بلیت هواپیما برای فردا به مشهد رزرو کن»", plan="general_chat(user)"
        ),
        RouterExample(
            prompt="Explain what inflation is, in Persian please.",
            plan="general_chat(user)",
        ),
        RouterExample(
            prompt="What is 25% of 360, and what is the capital of Japan?",
            plan="calculator(user) + general_chat(user)",
        ),
        RouterExample(
            prompt="Calculate 1200 * 1.15 and explain what this kind of increase is called.",
            plan="calculator(user) -> general_chat(s1)",
        ),
    ),
    params_model=None,
    accepts=frozenset({"text", "number"}),
    output_kind="text",
    requires_payload=False,
    budget=BUDGET,
    run=run,
    order=90,
)
