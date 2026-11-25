"""The `evaluate` tool the model must call, and tolerant parsing of what it sends back.

Small free-tier models vary a lot in how they "call" a tool: proper tool calls with a
`calculations` list, a single `{"expression": ...}`, several tool calls, or the JSON
pasted into plain text. All of these are accepted, so a formatting quirk never costs an
extra LLM call. The JSON-mode fallback (`CalculationPlan`) uses the same normalization.
"""

from __future__ import annotations

import json
from typing import Any

from pydantic import BaseModel, ConfigDict, Field, model_validator

from skillagent.core.language import extract_json_object
from skillagent.llm.types import LLMResponse, ToolSpec

__all__ = [
    "EVALUATE_TOOL",
    "MAX_CALCULATIONS",
    "Calculation",
    "CalculationPlan",
    "parse_calculations",
    "parse_response",
]

MAX_CALCULATIONS = 5
MAX_LABEL_CHARS = 80

EVALUATE_TOOL = ToolSpec(
    name="evaluate",
    description=(
        "Exactly evaluate one or more arithmetic expressions. "
        "You must call this; never compute results yourself."
    ),
    parameters={
        "type": "object",
        "properties": {
            "calculations": {
                "type": "array",
                "minItems": 0,
                "maxItems": MAX_CALCULATIONS,
                "items": {
                    "type": "object",
                    "properties": {
                        "expression": {
                            "type": "string",
                            "description": (
                                "Python-style arithmetic using + - * / ** % ( ) "
                                "and the allowed functions"
                            ),
                        },
                        "label": {
                            "type": "string",
                            "description": (
                                "short description in the user's language, "
                                "e.g. 'average speed (km/h)'"
                            ),
                        },
                    },
                    "required": ["expression"],
                },
            }
        },
        "required": ["calculations"],
    },
)


class Calculation(BaseModel):
    model_config = ConfigDict(extra="ignore")

    expression: str = Field(min_length=1)
    label: str = ""

    @model_validator(mode="before")
    @classmethod
    def _from_string(cls, data: Any) -> Any:
        return {"expression": data} if isinstance(data, str) else data

    @model_validator(mode="after")
    def _clean_label(self) -> Calculation:
        # A label is display text only; keep it short and on one line. Anything after an
        # "=" would be the model stating a result, which is never its job.
        label = " ".join(self.label.split()).split("=")[0].strip(" :")
        self.label = label[:MAX_LABEL_CHARS].rstrip()
        self.expression = self.expression.strip()
        return self


class CalculationPlan(BaseModel):
    """JSON-mode schema; also accepts the single-expression shape."""

    model_config = ConfigDict(extra="ignore")

    calculations: list[Calculation] = Field(default_factory=list)

    @model_validator(mode="before")
    @classmethod
    def _accept_variants(cls, data: Any) -> Any:
        return {"calculations": _items_from(data)} if isinstance(data, dict) else data

    @model_validator(mode="after")
    def _cap(self) -> CalculationPlan:
        del self.calculations[MAX_CALCULATIONS:]
        return self


def _items_from(data: dict[str, Any]) -> list[Any]:
    """Collect calculation items from any of the shapes models produce."""
    if isinstance(data.get("calculations"), list):
        return list(data["calculations"])
    if isinstance(data.get("expressions"), list):
        return list(data["expressions"])
    if isinstance(data.get("expression"), str):
        return [{"expression": data["expression"], "label": data.get("label", "")}]
    if "calculations" in data:  # e.g. a single object instead of a list
        return [data["calculations"]]
    raise ValueError("expected 'calculations' (a list) or 'expression'")


def parse_calculations(data: Any) -> list[Calculation]:
    """Arguments dict → calculations; raises ValueError for unusable shapes."""
    if not isinstance(data, dict):
        raise ValueError("arguments must be a JSON object")
    return CalculationPlan.model_validate(data).calculations


def parse_response(response: LLMResponse) -> list[Calculation] | None:
    """Calculations from tool calls (all of them) or from JSON in the text.

    Returns None when the reply contains nothing usable, which tells the skill to try the
    JSON fallback; `[]` means the model explicitly said "no calculation here".
    """
    found: list[Calculation] = []
    usable = False
    for call in response.tool_calls:
        arguments = call.arguments or _loads_or_empty(call.raw_arguments)
        try:
            found += parse_calculations(arguments)
            usable = True
        except ValueError:
            continue
    if not usable and response.text.strip():
        try:
            found = parse_calculations(json.loads(extract_json_object(response.text)))
            usable = True
        except ValueError:  # includes JSONDecodeError and pydantic ValidationError
            pass
    return found[:MAX_CALCULATIONS] if usable else None


def _loads_or_empty(raw: str) -> dict[str, Any]:
    try:
        value = json.loads(extract_json_object(raw))
    except ValueError:
        return {}
    return value if isinstance(value, dict) else {}
