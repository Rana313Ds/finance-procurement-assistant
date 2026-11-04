"""The contract between the routing step (LLM or stub) and the pipeline."""
from __future__ import annotations

from typing import Literal

from pydantic import Field

from .tools import Strict, ToolCall

Route = Literal["data", "policy", "both", "none"]


class Plan(Strict):
    route: Route
    reasoning: str
    tool_calls: list[ToolCall] = Field(default_factory=list, max_length=4)
    policy_clauses: list[str] = Field(default_factory=list)


class Composition(Strict):
    answer: str
    cited_clauses: list[str] = Field(default_factory=list)
    cited_results: list[str] = Field(default_factory=list)
