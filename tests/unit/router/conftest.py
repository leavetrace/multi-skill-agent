"""Router test fixtures: real catalog, synthetic bilingual skills, a router factory."""

from __future__ import annotations

import dataclasses
import json
from collections.abc import Callable
from typing import Any

import pytest

from skillagent.config import Settings
from skillagent.core.registry import SkillRegistry
from skillagent.prompts import PromptLoader
from skillagent.router import Router
from skillagent.router.candidates import CandidateSelector
from skillagent.skills.base import RouterExample, SkillSpec
from skillagent.skills.catalog import build_default_registry
from skillagent.testing import make_skill_spec

# name, description, EN cues, FA cues, example prompt, (EN query, FA query)
SYNTHETIC_DOMAINS: tuple[tuple[str, str, str, str, str, tuple[str, str]], ...] = (
    ("weather_forecast", "Weather forecast, temperature, rain and wind for a city.",
     "weather forecast temperature rain snow wind humidity tomorrow",
     "آب و هوا پیش‌بینی هوا دما باران برف باد", "Will it rain in Tehran tomorrow?",
     ("what's the temperature and wind in Paris", "فردا در شیراز باران می‌آید؟")),
    ("currency_exchange", "Converts money between currencies at exchange rates.",
     "currency exchange rate dollar euro convert money",
     "نرخ ارز دلار یورو تبدیل پول", "How many euros is 100 dollars?",
     ("dollar to euro exchange rate today", "قیمت دلار به یورو چند است؟")),
    ("recipe_finder", "Finds cooking recipes and ingredients for dishes.",
     "recipe cook cooking ingredients dish bake meal",
     "دستور پخت آشپزی مواد لازم غذا پختن", "Give me a recipe for lasagna",
     ("ingredients to bake a chocolate cake", "دستور پخت قورمه سبزی را بگو")),
    ("flight_search", "Searches airline flights, tickets and departure times.",
     "flight airline ticket airport departure plane",
     "پرواز بلیط هواپیما فرودگاه ایرلاین", "Find a flight from Tehran to Istanbul",
     ("cheap plane ticket to London airport", "بلیط هواپیما به مشهد برای فردا")),
    ("hotel_booking", "Books hotel rooms and accommodation.",
     "hotel room booking reservation accommodation stay night",
     "هتل اتاق رزرو اقامت شب", "Reserve a hotel room in Isfahan",
     ("book a hotel room for two nights", "یک اتاق هتل در کیش رزرو کن")),
    ("music_player", "Plays songs, albums and playlists.",
     "play music song album playlist artist singer",
     "پخش موسیقی آهنگ آلبوم خواننده", "Play a song by Queen",
     ("play my workout playlist", "یک آهنگ از خواننده محبوبم پخش کن")),
    ("movie_guide", "Recommends films and shows cinema showtimes.",
     "movie film cinema showtime actor director",
     "فیلم سینما بازیگر کارگردان سانس", "Recommend a good sci-fi movie",
     ("cinema showtimes for the new film", "یک فیلم خوب با بازیگر معروف پیشنهاد بده")),
    ("stock_market", "Reports stock prices, shares and market indexes.",
     "stock share price market index nasdaq invest",
     "سهام بورس قیمت سهم شاخص سرمایه‌گذاری", "What is Apple's stock price?",
     ("nasdaq index and share price today", "شاخص بورس امروز چقدر است؟")),
    ("fitness_coach", "Creates workout plans and exercise routines.",
     "workout exercise gym training fitness muscle",
     "ورزش تمرین باشگاه بدنسازی عضله", "Give me a 20 minute workout",
     ("gym training plan for muscle", "یک برنامه تمرین بدنسازی بده")),
    ("email_writer", "Drafts emails and formal letters.",
     "email draft letter write reply inbox",
     "ایمیل نامه پیش‌نویس نوشتن پاسخ", "Draft an email to my manager",
     ("write a reply email to my client", "یک ایمیل رسمی به استادم بنویس")),
    ("calendar_manager", "Schedules meetings and calendar events.",
     "calendar meeting schedule event appointment",
     "تقویم جلسه قرار ملاقات رویداد", "Schedule a meeting on Monday",
     ("add an appointment to my calendar", "برای شنبه یک جلسه در تقویم بگذار")),
    ("news_digest", "Gives latest news headlines.",
     "news headlines latest breaking report",
     "اخبار خبر تیتر تازه‌ترین گزارش", "What are today's news headlines?",
     ("latest breaking news report", "تازه‌ترین اخبار امروز را بگو")),
    ("dictionary_lookup", "Defines words and gives synonyms.",
     "define definition word meaning synonym dictionary",
     "معنی کلمه واژه مترادف فرهنگ لغت", "Define the word serendipity",
     ("meaning and synonym of the word brave", "معنی کلمه «سرنوشت» چیست؟")),
    ("unit_converter", "Converts units of length, weight and volume.",
     "unit convert kilometers miles kilograms pounds liters",
     "واحد تبدیل کیلومتر مایل کیلوگرم پوند لیتر", "Convert 5 miles to kilometers",
     ("how many pounds in 3 kilograms", "۱۰ مایل چند کیلومتر است؟")),
    ("sports_scores", "Shows match results and league tables.",
     "football match score league goal team",
     "فوتبال مسابقه نتیجه لیگ گل تیم", "Who won the football match last night?",
     ("league table and team scores", "نتیجه بازی تیم فوتبال دیشب چه شد؟")),
    ("code_reviewer", "Reviews source code for bugs.",
     "code review bug python function programming",
     "کد برنامه‌نویسی باگ تابع بررسی", "Review this Python function for bugs",
     ("find the bug in my python code", "این کد برنامه‌نویسی را برای باگ بررسی کن")),
    ("grammar_checker", "Fixes grammar and spelling mistakes.",
     "grammar spelling mistake proofread correct sentence",
     "دستور زبان املا غلط ویرایش جمله", "Proofread my sentence for grammar",
     ("correct the spelling mistakes", "غلط‌های املایی این جمله را درست کن")),
    ("poem_writer", "Writes poems and verses.",
     "poem poetry verse rhyme haiku",
     "شعر غزل بیت قافیه شاعر", "Write a haiku about autumn",
     ("a short poem with rhyme about the sea", "یک شعر کوتاه درباره بهار بگو")),
    ("visa_advisor", "Explains visa and passport requirements.",
     "visa passport embassy immigration requirements",
     "ویزا گذرنامه پاسپورت سفارت مهاجرت", "Do I need a visa for Japan?",
     ("passport and embassy requirements for Canada", "برای ویزای آلمان چه مدارکی لازم است؟")),
    ("taxi_ride", "Orders a taxi or ride to a destination.",
     "taxi ride driver car pickup destination",
     "تاکسی اسنپ راننده ماشین مقصد", "Call a taxi to the airport",
     ("order a ride with a driver to downtown", "یک تاکسی برای رفتن به مقصد بگیر")),
)  # fmt: skip


def synthetic_spec(i: int) -> SkillSpec:
    name, description, en, fa, example, _ = SYNTHETIC_DOMAINS[i]
    base = make_skill_spec(name, description=description, order=200 + i)
    return dataclasses.replace(
        base,
        when_to_use=(f"The user asks about: {en}.", f"کاربر درباره {fa} می‌پرسد."),
        when_not_to_use=("Anything unrelated to this domain.",),
        examples=(RouterExample(prompt=example, plan=f"{name}(user)"),),
    )


def synthetic_queries() -> list[tuple[str, str]]:
    """(query, gold skill): 2 per domain (EN + FA) → 40 queries."""
    return [(q, d[0]) for d in SYNTHETIC_DOMAINS for q in d[5]]


@pytest.fixture
def registry() -> SkillRegistry:
    return build_default_registry()


@pytest.fixture
def settings(make_settings: Callable[..., Settings]) -> Settings:
    return make_settings()


@pytest.fixture
def make_router(registry: SkillRegistry, settings: Settings) -> Callable[..., Router]:
    def factory(
        reg: SkillRegistry | None = None,
        selector: CandidateSelector | None = None,
        **overrides: Any,
    ) -> Router:
        s = settings.model_copy(update=overrides) if overrides else settings
        return Router(reg or registry, s, PromptLoader(), selector)

    return factory


def plan_json(**overrides: Any) -> str:
    """A valid single-step router reply, with overrides."""
    data: dict[str, Any] = {
        "response_language": "en",
        "steps": [
            {"id": "s1", "skill": "general_chat", "instruction": "Reply.", "input_from": "user"}
        ],
        "needs_clarification": False,
        "clarification_question": None,
        "confidence": 0.9,
        "rationale": "test",
    }
    data.update(overrides)
    return json.dumps(data, ensure_ascii=False)


@pytest.fixture
def plan() -> Callable[..., str]:
    return plan_json


@pytest.fixture
def synthetic_specs() -> list[SkillSpec]:
    return [synthetic_spec(i) for i in range(len(SYNTHETIC_DOMAINS))]


@pytest.fixture
def queries() -> list[tuple[str, str]]:
    return synthetic_queries()
