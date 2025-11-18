"""
Resolver that converts an intent plan into a concrete JSON change-set.
"""

from __future__ import annotations

from typing import Any
from uuid import uuid4

from .config import get_settings
from .db import Database
from .intent_schema import IntentPlan, OptionIntent, FieldIntent, LogicIntent, OperationType


class ResolutionClarificationNeeded(ValueError):
    def __init__(
        self,
        message: str,
        reason: str,
        form_candidates: list[dict[str, Any]] | None = None,
        field_candidates: list[dict[str, Any]] | None = None,
    ) -> None:
        super().__init__(message)
        self.reason = reason
        self.form_candidates = form_candidates or []
        self.field_candidates = field_candidates or []


def _placeholder(prefix: str) -> str:
    return f"${prefix}_{uuid4().hex[:8]}"


def _ensure_table_section(container: dict[str, Any], table: str) -> dict[str, list[dict[str, Any]]]:
    if table not in container:
        container[table] = {"insert": [], "update": [], "delete": []}
    return container[table]


async def build_change_set(plan: IntentPlan, db: Database) -> dict[str, Any]:
    settings = get_settings()
    change_set: dict[str, Any] = {}
    
    new_form_ids: dict[str, str] = {}

    await _create_new_forms(plan, db, change_set, new_form_ids)
    await _apply_field_intents(plan.fields, db, change_set, new_form_ids)
    await _apply_option_intents(plan.options, db, change_set, new_form_ids)
    await _apply_logic_intents(plan.logic_blocks, db, change_set, new_form_ids)

    total_rows = 0
    for table in change_set.values():
        for op in ("insert", "update", "delete"):
            total_rows += len(table[op])
    if total_rows > settings.max_changed_rows:
        raise ValueError(f"Planned {total_rows} row changes which exceeds limit {settings.max_changed_rows}")

    return change_set


async def _create_new_forms(
    plan: IntentPlan, db: Database, change_set: dict[str, Any], new_form_ids: dict[str, str]
) -> None:
    unique_forms: dict[str, dict[str, Any]] = {}
    
    for intent in plan.fields + plan.options + plan.logic_blocks:
        form_key = (
            intent.target_form.form_id
            or intent.target_form.form_name
            or intent.target_form.form_code
        )
        if form_key and form_key not in unique_forms:
            unique_forms[form_key] = intent.target_form.model_dump()
    
    for form_key, target_form in unique_forms.items():
        if target_form.get("form_id"):
            continue
        
        name_or_code = target_form.get("form_name") or target_form.get("form_code")
        if not name_or_code:
            continue
        
        matches = await db.find_form_by_name(name_or_code)
        if matches:
            continue
        
        form_id = _placeholder("form")
        slug = name_or_code.lower().replace(" ", "-")
        title = name_or_code if target_form.get("form_name") else name_or_code.replace("-", " ").title()
        
        forms_table = _ensure_table_section(change_set, "forms")
        forms_table["insert"].append({
            "id": form_id,
            "slug": slug,
            "title": title,
            "description": f"Form for {title.lower()}",
            "status": "draft",
        })
        
        page_id = _placeholder("page")
        pages_table = _ensure_table_section(change_set, "form_pages")
        pages_table["insert"].append({
            "id": page_id,
            "form_id": form_id,
            "page_number": 1,
            "title": "Page 1",
        })
        
        new_form_ids[form_key] = form_id


async def _resolve_form_id(
    db: Database, target_form: dict[str, Any], new_form_ids: dict[str, str] | None = None
) -> str:
    if target_form.get("form_id"):
        return str(target_form["form_id"])
    name_or_code = target_form.get("form_name") or target_form.get("form_code")
    if not name_or_code:
        raise ValueError("Intent is missing form reference")
    
    if new_form_ids and name_or_code in new_form_ids:
        return new_form_ids[name_or_code]
    
    matches = await db.find_form_by_name(name_or_code)
    if not matches:
        all_forms = await db.fetch_all(
            "SELECT id, slug, title FROM forms ORDER BY title"
        )
        if all_forms:
            message = (
                f"I could not find any form matching '{name_or_code}'. "
                "Please choose one of the known forms."
            )
            candidates = [
                {"id": row["id"], "title": row["title"], "slug": row["slug"]}
                for row in all_forms
            ]
        else:
            message = (
                f"I could not find any form matching '{name_or_code}'. "
                "The database currently has no forms."
            )
            candidates = []
        raise ResolutionClarificationNeeded(
            message=message,
            reason="form_not_found",
            form_candidates=candidates,
        )
    if len(matches) > 1:
        message = (
            f"Multiple forms match '{name_or_code}'. "
            "Please choose the correct form."
        )
        candidates = [
            {"id": row["id"], "title": row["title"], "slug": row["slug"]}
            for row in matches
        ]
        raise ResolutionClarificationNeeded(
            message=message,
            reason="form_ambiguous",
            form_candidates=candidates,
        )
    return str(matches[0]["id"])


async def _resolve_field(
    db: Database, form_id: str, intent: FieldIntent, change_set: dict[str, Any] | None = None
) -> dict[str, Any] | None:
    if form_id.startswith("$") and change_set:
        fields_in_changeset = change_set.get("form_fields", {}).get("insert", [])
        if intent.field_code:
            exact_matches = [
                f for f in fields_in_changeset
                if f.get("form_id") == form_id and f.get("code") == intent.field_code
            ]
            if exact_matches:
                return exact_matches[0]
            
            fuzzy_matches = [
                f for f in fields_in_changeset
                if f.get("form_id") == form_id and intent.field_code in f.get("code", "")
            ]
            if len(fuzzy_matches) == 1:
                return fuzzy_matches[0]
        
        if intent.field_label:
            label_matches = [
                f for f in fields_in_changeset
                if f.get("form_id") == form_id and f.get("label") == intent.field_label
            ]
            if label_matches:
                return label_matches[0]
        
        return None
    
    if intent.field_code:
        candidates = await db.fetch_all(
            "SELECT * FROM form_fields WHERE form_id = ? AND code = ?",
            [form_id, intent.field_code],
        )
        if candidates:
            return candidates[0]
        
        fuzzy_candidates = await db.fetch_all(
            "SELECT * FROM form_fields WHERE form_id = ? AND code LIKE ?",
            [form_id, f"%{intent.field_code}%"],
        )
        if len(fuzzy_candidates) == 1:
            return fuzzy_candidates[0]
        if len(fuzzy_candidates) > 1:
            message = (
                f"Multiple fields match code '{intent.field_code}' on this form. "
                "Please choose the correct field."
            )
            field_candidates = [
                {"id": c["id"], "label": c["label"], "code": c["code"]}
                for c in fuzzy_candidates
            ]
            raise ResolutionClarificationNeeded(
                message=message,
                reason="field_ambiguous",
                field_candidates=field_candidates,
            )
    
    if intent.field_label:
        candidates = await db.find_field_by_label(form_id, intent.field_label)
        if len(candidates) == 1:
            return candidates[0]
        if len(candidates) > 1:
            message = (
                f"Multiple fields match '{intent.field_label}' on this form. "
                "Please choose the correct field."
            )
            field_candidates = [
                {"id": c["id"], "label": c["label"], "code": c["code"]}
                for c in candidates
            ]
            raise ResolutionClarificationNeeded(
                message=message,
                reason="field_ambiguous",
                field_candidates=field_candidates,
            )
    return None


async def _apply_field_intents(
    intents: list[FieldIntent], db: Database, change_set: dict[str, Any], new_form_ids: dict[str, str]
) -> None:
    for intent in intents:
        form_id = await _resolve_form_id(db, intent.target_form.model_dump(), new_form_ids)
        existing = await _resolve_field(db, form_id, intent, change_set)
        table = _ensure_table_section(change_set, "form_fields")

        if intent.operation is OperationType.insert:
            if not intent.field_type:
                raise ValueError("Field insert requires field_type")
            field_type = await db.get_field_type_by_key(intent.field_type)
            if not field_type:
                raise ValueError(f"Unknown field type key '{intent.field_type}'")
            
            if form_id.startswith("$"):
                pages_in_changeset = change_set.get("form_pages", {}).get("insert", [])
                matching_pages = [p for p in pages_in_changeset if p["form_id"] == form_id]
                if not matching_pages:
                    raise ValueError(f"New form {form_id} has no pages in change-set")
                target_page = matching_pages[0]
                
                existing_fields_in_changeset = change_set.get("form_fields", {}).get("insert", [])
                fields_on_page = [
                    f for f in existing_fields_in_changeset
                    if f.get("page_id") == target_page["id"]
                ]
                new_position = len(fields_on_page) + 1
            else:
                pages = await db.get_pages_for_form(form_id)
                if not pages:
                    raise ValueError(f"Form {form_id} has no pages")
                target_page = pages[-1]
                new_position = 1
                existing_fields = await db.fetch_all(
                    "SELECT position FROM form_fields WHERE form_id = ? AND page_id = ? ORDER BY position DESC",
                    [form_id, target_page["id"]],
                )
                if existing_fields:
                    new_position = int(existing_fields[0]["position"]) + 1
            code = intent.field_code or intent.field_label or f"field_{uuid4().hex[:6]}"
            label = intent.field_label or code.replace("_", " ").title()
            row = {
                "id": _placeholder("fld"),
                "form_id": form_id,
                "page_id": target_page["id"],
                "type_id": field_type["id"],
                "code": code,
                "label": label,
                "help_text": intent.properties.get("help_text") if intent.properties else None,
                "position": new_position,
                "required": 1 if intent.properties.get("required") else 0 if intent.properties else 0,
                "read_only": 1 if intent.properties.get("read_only") else 0 if intent.properties else 0,
                "placeholder": intent.properties.get("placeholder") if intent.properties else None,
                "default_value": intent.properties.get("default_value") if intent.properties else None,
                "validation_schema": intent.properties.get("validation_schema") if intent.properties else None,
                "visible_by_default": 1 if intent.properties.get("visible_by_default", True) else 0 if intent.properties else 1,
            }
            table["insert"].append(row)

        elif intent.operation is OperationType.update:
            if not existing:
                raise ValueError("Field update could not resolve an existing field")
            update_row = {"id": existing["id"]}
            if intent.field_label:
                update_row["label"] = intent.field_label
            if intent.properties:
                if "required" in intent.properties:
                    update_row["required"] = 1 if intent.properties["required"] else 0
                if "read_only" in intent.properties:
                    update_row["read_only"] = 1 if intent.properties["read_only"] else 0
                if "placeholder" in intent.properties:
                    update_row["placeholder"] = intent.properties["placeholder"]
            table["update"].append(update_row)

        elif intent.operation is OperationType.delete:
            if not existing:
                raise ValueError("Field delete could not resolve an existing field")
            table["delete"].append({"id": existing["id"]})


async def _apply_option_intents(
    intents: list[OptionIntent], db: Database, change_set: dict[str, Any], new_form_ids: dict[str, str]
) -> None:
    for intent in intents:
        form_id = await _resolve_form_id(db, intent.target_form.model_dump(), new_form_ids)
        field_intent = FieldIntent(
            operation=OperationType.update,
            target_form=intent.target_form,
            field_code=intent.field_code,
            field_label=intent.field_label,
            field_type=None,
            page_hint=None,
            properties={},
        )
        field = await _resolve_field(db, form_id, field_intent, change_set)
        if not field:
            form_row = await db.fetch_one(
                "SELECT title, slug FROM forms WHERE id = ?", [form_id]
            )
            form_label = (
                f"{form_row['title']} (slug={form_row['slug']})"
                if form_row
                else f"form id {form_id}"
            )
            fields = await db.fetch_all(
                "SELECT id, label, code FROM form_fields WHERE form_id = ? ORDER BY position",
                [form_id],
            )
            wanted = intent.field_code or intent.field_label or "the dropdown field"
            message = (
                "I could not find a field that looks like "
                f"'{wanted}' on {form_label}. Please choose the correct field."
            )
            field_candidates = [
                {"id": row["id"], "label": row["label"], "code": row["code"]}
                for row in fields
            ]
            raise ResolutionClarificationNeeded(
                message=message,
                reason="field_not_found",
                field_candidates=field_candidates,
            )

        option_set = await db.get_option_set_for_field(field["id"])
        option_sets_table = _ensure_table_section(change_set, "option_sets")
        binding_table = _ensure_table_section(change_set, "field_option_binding")
        option_items_table = _ensure_table_section(change_set, "option_items")

        if not option_set:
            option_set_id = _placeholder("optset")
            option_set = {
                "id": option_set_id,
                "form_id": form_id,
                "name": f"{field['label']} options",
            }
            option_sets_table["insert"].append(option_set)
            binding_table["insert"].append(
                {
                    "field_id": field["id"],
                    "option_set_id": option_set_id,
                    "display_pattern": None,
                }
            )
        option_set_id = option_set["id"]

        existing_items = await db.get_option_items_for_field(field["id"])
        existing_by_value = {item["value"]: item for item in existing_items}
        existing_by_label = {item["label"]: item for item in existing_items}

        if intent.operation is OperationType.insert:
            max_position = max((int(item["position"]) for item in existing_items), default=0)
            for value in intent.add_values:
                if value in existing_by_value:
                    continue
                max_position += 1
                option_items_table["insert"].append(
                    {
                        "id": _placeholder("opt"),
                        "option_set_id": option_set_id,
                        "value": value,
                        "label": value,
                        "position": max_position,
                        "is_active": 1,
                    }
                )

        if intent.rename_map:
            for old_value, new_value in intent.rename_map.items():
                item = existing_by_value.get(old_value) or existing_by_label.get(old_value)
                if not item:
                    continue
                option_items_table["update"].append(
                    {
                        "id": item["id"],
                        "value": new_value,
                        "label": new_value,
                    }
                )

        if intent.remove_values:
            for value in intent.remove_values:
                item = existing_by_value.get(value) or existing_by_label.get(value)
                if not item:
                    continue
                option_items_table["update"].append(
                    {
                        "id": item["id"],
                        "is_active": 0,
                    }
                )


async def _apply_logic_intents(
    intents: list[LogicIntent], db: Database, change_set: dict[str, Any], new_form_ids: dict[str, str]
) -> None:
    for intent in intents:
        form_id = await _resolve_form_id(db, intent.target_form.model_dump(), new_form_ids)
        rules_table = _ensure_table_section(change_set, "logic_rules")
        conditions_table = _ensure_table_section(change_set, "logic_conditions")
        actions_table = _ensure_table_section(change_set, "logic_actions")

        if intent.operation is OperationType.insert:
            rule_id = _placeholder("rule")
            rule = {
                "id": rule_id,
                "form_id": form_id,
                "name": intent.description,
                "trigger": intent.payload.get("trigger", "on_change"),
                "scope": intent.payload.get("scope", "form"),
                "priority": intent.payload.get("priority", 100),
                "enabled": 1,
            }
            rules_table["insert"].append(rule)

            for cond in intent.payload.get("conditions", []):
                conditions_table["insert"].append(
                    {
                        "id": _placeholder("cond"),
                        "rule_id": rule_id,
                        "group_id": None,
                        "lhs_ref": cond.get("lhs_ref"),
                        "operator": cond.get("operator", "="),
                        "rhs": cond.get("rhs"),
                        "bool_join": cond.get("bool_join", "AND"),
                        "position": cond.get("position"),
                    }
                )

            for act in intent.payload.get("actions", []):
                actions_table["insert"].append(
                    {
                        "id": _placeholder("act"),
                        "rule_id": rule_id,
                        "action": act.get("action"),
                        "target_ref": act.get("target_ref"),
                        "params": act.get("params"),
                        "position": act.get("position"),
                    }
                )


