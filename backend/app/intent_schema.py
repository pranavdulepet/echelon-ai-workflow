"""
Pydantic models describing the intermediate intent plan.
"""

from enum import Enum
from typing import Any

from pydantic import BaseModel, Field


class OperationType(str, Enum):
    insert = "insert"
    update = "update"
    delete = "delete"


class EntityType(str, Enum):
    form = "form"
    field = "field"
    option = "option"
    logic_rule = "logic_rule"
    logic_condition = "logic_condition"
    logic_action = "logic_action"


class TargetForm(BaseModel):
    form_id: str | None = None
    form_name: str | None = None
    form_code: str | None = None


class FieldIntent(BaseModel):
    operation: OperationType
    target_form: TargetForm
    field_code: str | None = None
    field_label: str | None = None
    field_type: str | None = None
    page_hint: str | None = None
    properties: dict[str, Any] = Field(default_factory=dict)


class OptionIntent(BaseModel):
    operation: OperationType
    target_form: TargetForm
    field_code: str | None = None
    field_label: str | None = None
    add_values: list[str] = Field(default_factory=list)
    rename_map: dict[str, str] = Field(default_factory=dict)
    remove_values: list[str] = Field(default_factory=list)


class LogicIntent(BaseModel):
    operation: OperationType
    target_form: TargetForm
    description: str
    payload: dict[str, Any] = Field(default_factory=dict)


class IntentPlan(BaseModel):
    fields: list[FieldIntent] = Field(default_factory=list)
    options: list[OptionIntent] = Field(default_factory=list)
    logic_blocks: list[LogicIntent] = Field(default_factory=list)
    notes: str | None = None
    needs_clarification: bool = False
    clarification_question: str | None = None


