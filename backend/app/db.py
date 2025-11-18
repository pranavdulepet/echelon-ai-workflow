"""
SQLite access helpers and schema discovery.
"""

from collections.abc import Iterable
from dataclasses import dataclass
from pathlib import Path
from typing import Any

import aiosqlite

from .config import get_settings


@dataclass
class TableColumn:
    name: str
    type: str
    not_null: bool
    default_value: Any
    primary_key: bool


@dataclass
class TableInfo:
    name: str
    columns: list[TableColumn]


class Database:
    def __init__(self, path: Path | None = None) -> None:
        settings = get_settings()
        self.path = path or settings.sqlite_path

    async def get_tables(self) -> list[TableInfo]:
        async with aiosqlite.connect(self.path) as db:
            db.row_factory = aiosqlite.Row
            cursor = await db.execute(
                "SELECT name FROM sqlite_master WHERE type='table' ORDER BY name"
            )
            rows = await cursor.fetchall()
            tables: list[TableInfo] = []
            for row in rows:
                name = row["name"]
                columns = await self._get_table_columns(db, name)
                tables.append(TableInfo(name=name, columns=columns))
            return tables

    async def _get_table_columns(
        self, db: aiosqlite.Connection, table_name: str
    ) -> list[TableColumn]:
        cursor = await db.execute(f"PRAGMA table_info('{table_name}')")
        rows = await cursor.fetchall()
        columns: list[TableColumn] = []
        for row in rows:
            columns.append(
                TableColumn(
                    name=row["name"],
                    type=row["type"],
                    not_null=bool(row["notnull"]),
                    default_value=row["dflt_value"],
                    primary_key=bool(row["pk"]),
                )
            )
        return columns

    async def fetch_one(
        self, query: str, params: Iterable[Any] | None = None
    ) -> dict[str, Any] | None:
        async with aiosqlite.connect(self.path) as db:
            db.row_factory = aiosqlite.Row
            cursor = await db.execute(query, tuple(params or []))
            row = await cursor.fetchone()
            if row is None:
                return None
            return dict(row)

    async def fetch_all(
        self, query: str, params: Iterable[Any] | None = None
    ) -> list[dict[str, Any]]:
        async with aiosqlite.connect(self.path) as db:
            db.row_factory = aiosqlite.Row
            cursor = await db.execute(query, tuple(params or []))
            rows = await cursor.fetchall()
            return [dict(row) for row in rows]

    async def find_form_by_name(self, name: str) -> list[dict[str, Any]]:
        pattern = f"%{name}%"
        query = "SELECT * FROM forms WHERE title LIKE ? OR slug LIKE ?"
        return await self.fetch_all(query, [pattern, pattern])

    async def find_field_by_label(
        self, form_id: str, label_or_code: str
    ) -> list[dict[str, Any]]:
        pattern = f"%{label_or_code}%"
        query = (
            "SELECT * FROM form_fields "
            "WHERE form_id = ? AND (label LIKE ? OR code LIKE ?)"
        )
        return await self.fetch_all(query, [form_id, pattern, pattern])

    async def get_option_items_for_field(self, field_id: str) -> list[dict[str, Any]]:
        query = (
            "SELECT oi.* FROM option_items oi "
            "JOIN field_option_binding b ON b.option_set_id = oi.option_set_id "
            "WHERE b.field_id = ? ORDER BY oi.position"
        )
        return await self.fetch_all(query, [field_id])

    async def get_pages_for_form(self, form_id: str) -> list[dict[str, Any]]:
        query = (
            "SELECT * FROM form_pages WHERE form_id = ? "
            "ORDER BY position"
        )
        return await self.fetch_all(query, [form_id])

    async def get_field_type_by_key(self, key: str) -> dict[str, Any] | None:
        query = "SELECT * FROM field_types WHERE key = ?"
        return await self.fetch_one(query, [key])

    async def get_option_set_for_field(self, field_id: str) -> dict[str, Any] | None:
        query = (
            "SELECT os.* FROM option_sets os "
            "JOIN field_option_binding b ON b.option_set_id = os.id "
            "WHERE b.field_id = ?"
        )
        return await self.fetch_one(query, [field_id])

    async def get_logic_rules_for_form(self, form_id: str) -> list[dict[str, Any]]:
        query = "SELECT * FROM logic_rules WHERE form_id = ? ORDER BY priority"
        return await self.fetch_all(query, [form_id])

    async def get_form_structure(self, form_id: str) -> dict[str, Any] | None:
        form = await self.fetch_one(
            "SELECT id, slug, title, description, status FROM forms WHERE id = ?",
            [form_id],
        )
        if not form:
            return None

        pages = await self.get_pages_for_form(form_id)
        fields = await self.fetch_all(
            "SELECT f.*, ft.key AS field_type_key "
            "FROM form_fields f "
            "JOIN field_types ft ON ft.id = f.type_id "
            "WHERE f.form_id = ? "
            "ORDER BY f.page_id, f.position",
            [form_id],
        )

        options_by_field: dict[str, list[dict[str, Any]]] = {}
        for field in fields:
            fid = str(field["id"])
            items = await self.get_option_items_for_field(fid)
            options_by_field[fid] = items

        logic_rules = await self.get_logic_rules_for_form(form_id)
        logic_rule_ids = [row["id"] for row in logic_rules]
        logic_conditions: list[dict[str, Any]] = []
        logic_actions: list[dict[str, Any]] = []
        if logic_rule_ids:
            placeholders = ",".join("?" for _ in logic_rule_ids)
            logic_conditions = await self.fetch_all(
                f"SELECT * FROM logic_conditions WHERE rule_id IN ({placeholders})",
                logic_rule_ids,
            )
            logic_actions = await self.fetch_all(
                f"SELECT * FROM logic_actions WHERE rule_id IN ({placeholders})",
                logic_rule_ids,
            )

        return {
            "form": form,
            "pages": pages,
            "fields": fields,
            "options_by_field": options_by_field,
            "logic_rules": logic_rules,
            "logic_conditions": logic_conditions,
            "logic_actions": logic_actions,
        }

    async def get_form_snapshots(self, form_ids: Iterable[str]) -> dict[str, Any]:
        snapshots: dict[str, Any] = {}
        for form_id in form_ids:
            structure = await self.get_form_structure(form_id)
            if structure is not None:
                snapshots[form_id] = structure
        return snapshots



