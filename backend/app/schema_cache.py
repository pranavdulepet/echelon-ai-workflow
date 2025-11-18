from dataclasses import dataclass
from typing import Any

from .db import Database, TableInfo, TableColumn


@dataclass
class SchemaState:
    tables: list[TableInfo]


_schema_state: SchemaState | None = None


async def get_schema_state(db: Database) -> SchemaState:
    global _schema_state
    if _schema_state is None:
        tables = await db.get_tables()
        _schema_state = SchemaState(tables=tables)
    return _schema_state


def clear_schema_state() -> None:
    global _schema_state
    _schema_state = None


def required_columns_for_table(table: TableInfo) -> list[str]:
    required: list[str] = []
    for column in table.columns:
        if column.primary_key:
            continue
        if column.not_null and column.default_value is None:
            required.append(column.name)
    return required


