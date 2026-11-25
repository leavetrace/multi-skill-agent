"""Tool spec shape and tolerant parsing of model replies."""

from __future__ import annotations

import json

import pytest
from pydantic import ValidationError

from skillagent.llm.types import LLMResponse, ToolCall
from skillagent.skills.calculator.tool import (
    EVALUATE_TOOL,
    MAX_CALCULATIONS,
    Calculation,
    CalculationPlan,
    parse_calculations,
    parse_response,
)


def response(text: str = "", calls: list[ToolCall] | None = None) -> LLMResponse:
    return LLMResponse(text=text, tool_calls=calls or [], latency_ms=0, model="m", attempts=1)


def call(arguments: dict | None = None, raw: str | None = None) -> ToolCall:
    raw = raw if raw is not None else json.dumps(arguments or {})
    return ToolCall(id="c", name="evaluate", arguments=arguments or {}, raw_arguments=raw)


def test_tool_spec_matches_the_wp2_schema() -> None:
    assert EVALUATE_TOOL.name == "evaluate"
    calcs = EVALUATE_TOOL.parameters["properties"]["calculations"]
    assert calcs["maxItems"] == MAX_CALCULATIONS == 5
    assert calcs["items"]["required"] == ["expression"]
    assert "never compute results yourself" in EVALUATE_TOOL.description


def test_calculations_list() -> None:
    parsed = parse_response(
        response(calls=[call({"calculations": [{"expression": "1+1", "label": "sum"}]})])
    )
    assert parsed == [Calculation(expression="1+1", label="sum")]


def test_single_expression_variant() -> None:
    parsed = parse_response(response(calls=[call({"expression": "2*3", "label": "product"})]))
    assert parsed == [Calculation(expression="2*3", label="product")]


def test_multiple_tool_calls_are_concatenated() -> None:
    parsed = parse_response(
        response(calls=[call({"expression": "1+1"}), call({"calculations": ["2+2", "3+3"]})])
    )
    assert parsed is not None
    assert [c.expression for c in parsed] == ["1+1", "2+2", "3+3"]


def test_unparsed_arguments_fall_back_to_raw_json() -> None:
    parsed = parse_response(response(calls=[call(raw='```json\n{"expression": "5-1"}\n```')]))
    assert parsed is not None and parsed[0].expression == "5-1"


def test_json_in_text_variant() -> None:
    text = 'Sure! Here you go:\n```json\n{"calculations": [{"expression": "180/2.5"}]}\n```'
    parsed = parse_response(response(text=text))
    assert parsed is not None and parsed[0].expression == "180/2.5"


def test_explicit_empty_list_is_not_none() -> None:
    assert parse_response(response(calls=[call({"calculations": []})])) == []


@pytest.mark.parametrize("text", ["", "The answer is 42.", '{"foo": 1}', "{not json"])
def test_unusable_replies_return_none(text: str) -> None:
    assert parse_response(response(text=text)) is None


def test_garbage_tool_call_with_no_text_returns_none() -> None:
    assert parse_response(response(calls=[call(raw="not json at all")])) is None


def test_calculations_are_capped() -> None:
    parsed = parse_response(response(calls=[call({"calculations": [str(i) for i in range(9)]})]))
    assert parsed is not None and len(parsed) == MAX_CALCULATIONS


def test_label_cleanup_strips_stated_results() -> None:
    calc = Calculation(expression=" 2+3 ", label="  sum\nof  things = 5  ")
    assert calc.expression == "2+3"
    assert calc.label == "sum of things"
    assert len(Calculation(expression="1", label="x" * 500).label) == 80


def test_calculation_plan_variants() -> None:
    plan = CalculationPlan.model_validate({"expressions": ["1", "2"]})
    assert plan.calculations[1].expression == "2"
    assert CalculationPlan.model_validate({"calculations": {"expression": "1"}}).calculations
    with pytest.raises(ValidationError):
        CalculationPlan.model_validate({"answer": 3})
    with pytest.raises(ValueError):
        parse_calculations(["1+1"])
