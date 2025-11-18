from typing import Any

from pydantic import BaseModel, Field


class HistoryItem(BaseModel):
    question: str = ""
    answer: str = ""


class QueryRequest(BaseModel):
    query: str = Field(..., description="Natural language user request")
    provider: str | None = Field(
        default=None, description="Optional provider override: 'openai' or 'anthropic'"
    )
    history: list[HistoryItem] = Field(default_factory=list)


class ClarificationResponse(BaseModel):
    type: str = "clarification"
    question: str
    plan: dict[str, Any]
    reason: str | None = None
    form_candidates: list[dict[str, Any]] | None = None
    field_candidates: list[dict[str, Any]] | None = None


class ChangeSetResponse(BaseModel):
    type: str = "change_set"
    plan: dict[str, Any]
    change_set: dict[str, Any]
    before_snapshot: dict[str, Any] | None = None


class ExplainRequest(BaseModel):
    query: str = Field(..., description="Original natural language request")
    plan: dict[str, Any] | None = Field(
        default=None, description="Intent plan that produced the change-set"
    )
    change_set: dict[str, Any] = Field(
        ..., description="Final JSON change-set to be explained"
    )
    provider: str | None = Field(
        default=None, description="Optional provider override: 'openai' or 'anthropic'"
    )


class ExplainResponse(BaseModel):
    explanation: str


class FormSummary(BaseModel):
    id: str
    slug: str
    title: str
    status: str


class FormStructureResponse(BaseModel):
    form: dict[str, Any]
    pages: list[dict[str, Any]]
    fields: list[dict[str, Any]]
    options_by_field: dict[str, list[dict[str, Any]]]
    logic_rules: list[dict[str, Any]]
    logic_conditions: list[dict[str, Any]]
    logic_actions: list[dict[str, Any]]

