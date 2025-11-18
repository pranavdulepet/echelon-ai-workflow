from typing import Any

import pytest

from app.agent import FormAgent
from app.db import Database, TableInfo
from app.schema_cache import get_schema_state, required_columns_for_table


def _load_tables_sync() -> list[TableInfo]:
    db = Database()

    async def inner() -> list[TableInfo]:
        state = await get_schema_state(db)
        return state.tables

    import asyncio

    return asyncio.run(inner())


SCHEMA_TABLES = {table.name: table for table in _load_tables_sync()}


def _validate_change_set_shape(change_set: dict[str, Any]) -> None:
    for table_name, ops in change_set.items():
        assert isinstance(ops, dict), f"{table_name} value must be an object"
        for key in ("insert", "update", "delete"):
            assert key in ops, f"{table_name} is missing '{key}' array"
            assert isinstance(ops[key], list), f"{table_name}.{key} must be a list"


async def _validate_ids_exist(change_set: dict[str, Any], db: Database) -> None:
    for table_name, ops in change_set.items():
        if "id" not in {c.name for c in SCHEMA_TABLES[table_name].columns}:
            continue
        for op in ("update", "delete"):
            for row in ops[op]:
                row_id = row.get("id")
                assert row_id, f"{table_name} {op} row is missing id"
                existing = await db.fetch_one(
                    f"SELECT id FROM {table_name} WHERE id = ?", [row_id]
                )
                assert existing is not None, f"{table_name} {op} id {row_id} does not exist"


def _validate_required_fields(change_set: dict[str, Any]) -> None:
    for table_name, ops in change_set.items():
        table = SCHEMA_TABLES[table_name]
        required_cols = required_columns_for_table(table)
        for row in ops["insert"]:
            for col in required_cols:
                assert col in row, f"{table_name} insert row missing required field {col}"


@pytest.mark.asyncio
@pytest.mark.parametrize(
    "query",
    [
        "update the dropdown options for the destination field in the travel request form: 1. add a paris option, 2. change tokyo to milan",
        'I want the employment-demo form to require university_name when employment_status is "Student". University name should be a text field.',
        "I want to create a new form to allow employees to request a new snack. There should be a category field (ice cream/ beverage/ fruit/ chips/ gum), and name of the item (text).",
    ],
)
async def test_end_to_end_invariants_hold(query: str) -> None:
    db = Database()
    agent = FormAgent(db=db)

    result = await agent.plan_and_resolve(query=query, history=[])

    if result["type"] == "clarification":
        pytest.skip("Agent requested clarification; invariants not applicable.")

    change_set = result["change_set"]

    _validate_change_set_shape(change_set)
    _validate_required_fields(change_set)
    await _validate_ids_exist(change_set, db)


