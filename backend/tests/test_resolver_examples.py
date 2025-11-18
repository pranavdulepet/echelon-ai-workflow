import asyncio
import sys
from pathlib import Path
from typing import Any

import pytest

here = Path(__file__).resolve()
root = here.parent.parent
if str(root) not in sys.path:
  sys.path.insert(0, str(root))

from app.db import Database
from app.intent_schema import (
    IntentPlan,
    OptionIntent,
    FieldIntent,
    LogicIntent,
    OperationType,
    TargetForm,
)
from app.resolver import build_change_set


@pytest.mark.asyncio
async def test_update_travel_destination_options_matches_example() -> None:
    db = Database()
    plan = IntentPlan(
        fields=[],
        options=[
            OptionIntent(
                operation=OperationType.insert,
                target_form=TargetForm(form_name="Travel Request (Complex)", form_code="travel-complex"),
                field_code="destinations",
                field_label="Destinations",
                add_values=["Paris"],
                rename_map={"Tokyo": "Milan"},
                remove_values=[],
            )
        ],
        logic_blocks=[],
    )

    change_set = await build_change_set(plan, db)

    assert "option_items" in change_set
    option_items = change_set["option_items"]
    inserts = option_items["insert"]
    updates = option_items["update"]

    insert_values = {(row["value"], row["label"]) for row in inserts}
    assert ("Paris", "Paris") in insert_values

    tokyo_updates: list[dict[str, Any]] = [
        row for row in updates if row.get("value") == "Milan" and row.get("label") == "Milan"
    ]
    assert tokyo_updates, "Expected Tokyo option to be renamed to Milan"


@pytest.mark.asyncio
async def test_new_snack_form_creates_form_and_fields() -> None:
    db = Database()
    plan = IntentPlan(
        fields=[
            FieldIntent(
                operation=OperationType.insert,
                target_form=TargetForm(form_name="Snack Request"),
                field_code="category",
                field_label="Category",
                field_type="dropdown",
                page_hint=None,
                properties={"required": True},
            ),
            FieldIntent(
                operation=OperationType.insert,
                target_form=TargetForm(form_name="Snack Request"),
                field_code="item_name",
                field_label="Item name",
                field_type="short_text",
                page_hint=None,
                properties={"required": True},
            ),
        ],
        options=[
            OptionIntent(
                operation=OperationType.insert,
                target_form=TargetForm(form_name="Snack Request"),
                field_code="category",
                field_label="Category",
                add_values=["ice cream", "beverage", "fruit", "chips", "gum"],
                rename_map={},
                remove_values=[],
            )
        ],
        logic_blocks=[],
    )

    change_set = await build_change_set(plan, db)

    assert "form_fields" in change_set
    category_fields = [
        row
        for row in change_set["form_fields"]["insert"]
        if row["code"] == "category" and row["label"] == "Category"
    ]
    item_fields = [
        row
        for row in change_set["form_fields"]["insert"]
        if row["code"] == "item_name" and row["label"] == "Item name"
    ]
    assert category_fields and item_fields

    category_field_id = category_fields[0]["id"]
    assert "option_sets" in change_set
    assert "option_items" in change_set

    option_values = {row["value"] for row in change_set["option_items"]["insert"]}
    for expected in ["ice cream", "beverage", "fruit", "chips", "gum"]:
        assert expected in option_values


@pytest.mark.asyncio
async def test_employment_university_logic_structure() -> None:
    db = Database()

    employment_form = await db.fetch_one(
        "SELECT id FROM forms WHERE slug = ?", ["employment-demo"]
    )
    assert employment_form is not None
    employment_form_id = employment_form["id"]

    employment_status_field = await db.fetch_one(
        "SELECT id FROM form_fields WHERE form_id = ? AND code = ?",
        [employment_form_id, "employment_status"],
    )
    assert employment_status_field is not None

    plan = IntentPlan(
        fields=[
            FieldIntent(
                operation=OperationType.insert,
                target_form=TargetForm(form_id=employment_form_id),
                field_code="university_name",
                field_label="University name",
                field_type="short_text",
                page_hint=None,
                properties={"required": False, "placeholder": "Your university"},
            )
        ],
        options=[],
        logic_blocks=[
            LogicIntent(
                operation=OperationType.insert,
                target_form=TargetForm(form_id=employment_form_id),
                description="Student requires university name",
                payload={
                    "trigger": "on_change",
                    "scope": "form",
                    "priority": 10,
                    "conditions": [
                        {
                            "lhs_ref": f'{{"type":"field","field_id":"{employment_status_field["id"]}","property":"value"}}',
                            "operator": "=",
                            "rhs": '"Student"',
                            "bool_join": "AND",
                            "position": 1,
                        }
                    ],
                    "actions": [
                        {
                            "action": "show",
                            "target_ref": '{"type":"field","field_id":"$fld_university_name"}',
                            "params": None,
                            "position": 1,
                        },
                        {
                            "action": "require",
                            "target_ref": '{"type":"field","field_id":"$fld_university_name"}',
                            "params": None,
                            "position": 2,
                        },
                    ],
                },
            )
        ],
    )

    change_set = await build_change_set(plan, db)

    assert "logic_rules" in change_set
    assert "logic_conditions" in change_set
    assert "logic_actions" in change_set

    rules = change_set["logic_rules"]["insert"]
    assert rules, "Expected at least one logic rule"
    rule = rules[0]
    assert rule["form_id"] == employment_form_id
    assert rule["trigger"] == "on_change"
    assert rule["scope"] == "form"

    conditions = change_set["logic_conditions"]["insert"]
    assert conditions
    assert conditions[0]["operator"] == "="

    actions = change_set["logic_actions"]["insert"]
    action_types = {a["action"] for a in actions}
    assert {"show", "require"}.issubset(action_types)


