"""
Resolver that converts an intent plan into a concrete JSON change-set.
"""

from __future__ import annotations

import json
from typing import Any
from uuid import uuid4

from .config import get_settings
from .db import Database
from .intent_schema import IntentPlan, OptionIntent, FieldIntent, LogicIntent, OperationType, TargetForm


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
    from .change_set_validator import validate_change_set_structure
    
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

    await validate_change_set_structure(change_set)

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
            "position": 1,
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
            form_list = ", ".join([f"{row['title']} ({row['slug']})" for row in all_forms])
            message = (
                f"I could not find any form matching '{name_or_code}'. "
                f"Please choose one of the available forms: {form_list}"
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
        form_list = ", ".join([f"{row['title']} ({row['slug']})" for row in matches])
        message = (
            f"Multiple forms match '{name_or_code}'. "
            f"Please choose the correct form: {form_list}"
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
            field_list = ", ".join([f"{c['label']} ({c['code']})" for c in fuzzy_candidates])
            message = (
                f"Multiple fields match code '{intent.field_code}' on this form. "
                f"Please choose the correct field: {field_list}"
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
            field_list = ", ".join([f"{c['label']} ({c['code']})" for c in candidates])
            message = (
                f"Multiple fields match '{intent.field_label}' on this form. "
                f"Please choose the correct field: {field_list}"
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
        table = _ensure_table_section(change_set, "form_fields")

        if intent.operation is OperationType.insert:
   
            existing = await _resolve_field(db, form_id, intent, change_set)
            if existing:
            
                continue
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
                "field_type_key": field_type["key"],  
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
            existing = await _resolve_field(db, form_id, intent, change_set)
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
            existing = await _resolve_field(db, form_id, intent, change_set)
            if not existing:
                raise ValueError("Field delete could not resolve an existing field")
            table["delete"].append({"id": existing["id"]})


async def _apply_option_intents(
    intents: list[OptionIntent], db: Database, change_set: dict[str, Any], new_form_ids: dict[str, str]
) -> None:
    for intent in intents:
        form_id = await _resolve_form_id(db, intent.target_form.model_dump(), new_form_ids)
        
        field = None
        if change_set:
            fields_in_changeset = change_set.get("form_fields", {}).get("insert", [])
            if intent.field_code:
                field = next(
                    (f for f in fields_in_changeset
                     if f.get("form_id") == form_id and f.get("code") == intent.field_code),
                    None
                )
            if not field and intent.field_label:
                field = next(
                    (f for f in fields_in_changeset
                     if f.get("form_id") == form_id and f.get("label") == intent.field_label),
                    None
                )
        
        if not field:
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
            field_list = ", ".join([f"{row['label']} ({row['code']})" for row in fields]) if fields else "no fields"
            message = (
                f"I could not find a field that looks like '{wanted}' on {form_label}. "
                f"Existing fields: {field_list}. "
                f"If you want to CREATE a new field, please say 'create a new field' or 'add new field' explicitly."
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


async def _resolve_field_reference(
    ref_json_str: str | None,
    form_id: str,
    db: Database,
    change_set: dict[str, Any],
) -> str | None:
    if not ref_json_str:
        return None
    
    try:
        ref_obj = json.loads(ref_json_str)
    except (json.JSONDecodeError, TypeError):
        return ref_json_str
    
    if not isinstance(ref_obj, dict):
        return ref_json_str
    
    if ref_obj.get("type") != "field":
        return ref_json_str
    
    if "field_id" in ref_obj:
        field_id = ref_obj["field_id"]
        if field_id.startswith("$"):
            fields_in_changeset = change_set.get("form_fields", {}).get("insert", [])
            matching_field = next(
                (f for f in fields_in_changeset if f.get("id") == field_id),
                None
            )
            
            if not matching_field:
                
                placeholder_parts = field_id.split("_", 1)
                if len(placeholder_parts) == 2 and placeholder_parts[0] == "$fld":
                    potential_code = placeholder_parts[1]
                   
                    if len(potential_code) > 8 or not all(c in '0123456789abcdef' for c in potential_code.lower()):
                        matching_field = next(
                            (f for f in fields_in_changeset
                             if f.get("form_id") == form_id and f.get("code") == potential_code),
                            None
                        )
            
            if not matching_field and "field_code" in ref_obj:
                field_code = ref_obj["field_code"]
                matching_field = next(
                    (f for f in fields_in_changeset
                     if f.get("form_id") == form_id and f.get("code") == field_code),
                    None
                )
            
            if not matching_field:
                raise ValueError(
                    f"Logic rule references field placeholder {field_id} that doesn't exist in change-set"
                )
            ref_obj["field_id"] = matching_field["id"]
            return json.dumps(ref_obj)
        return ref_json_str
    
    field_code = ref_obj.get("field_code")
    if not field_code:
        return ref_json_str
    
    fields_in_changeset = change_set.get("form_fields", {}).get("insert", [])
    matching_field = None
    
    if form_id.startswith("$"):
        matching_field = next(
            (f for f in fields_in_changeset
             if f.get("form_id") == form_id and f.get("code") == field_code),
            None
        )
    else:
        matching_field = next(
            (f for f in fields_in_changeset
             if f.get("form_id") == form_id and f.get("code") == field_code),
            None
        )
        
        if not matching_field:
            field_intent = FieldIntent(
                operation=OperationType.update,
                target_form=TargetForm(form_id=form_id),
                field_code=field_code,
                field_label=None,
                field_type=None,
                page_hint=None,
                properties={},
            )
            matching_field = await _resolve_field(db, form_id, field_intent, change_set)
    
    if not matching_field:
        raise ValueError(
            f"Logic rule references field '{field_code}' that doesn't exist on form {form_id}"
        )
    
    ref_obj["field_id"] = matching_field["id"]
    if "field_code" in ref_obj:
        del ref_obj["field_code"]
    
    return json.dumps(ref_obj)


async def _apply_logic_intents(
    intents: list[LogicIntent], db: Database, change_set: dict[str, Any], new_form_ids: dict[str, str]
) -> None:
    for intent in intents:
        form_id = await _resolve_form_id(db, intent.target_form.model_dump(), new_form_ids)
        rules_table = _ensure_table_section(change_set, "logic_rules")
        conditions_table = _ensure_table_section(change_set, "logic_conditions")
        actions_table = _ensure_table_section(change_set, "logic_actions")

        if intent.operation is OperationType.insert:
            requested_priority = intent.payload.get("priority", 100)
            existing_rules = await db.get_logic_rules_for_form(form_id)
            existing_priorities = {r["priority"] for r in existing_rules}
            
            rules_in_changeset = change_set.get("logic_rules", {}).get("insert", [])
            existing_priorities.update(r["priority"] for r in rules_in_changeset if r.get("form_id") == form_id)
            
            final_priority = requested_priority
            while final_priority in existing_priorities:
                final_priority += 1
            
            rule_id = _placeholder("rule")
            rule = {
                "id": rule_id,
                "form_id": form_id,
                "name": intent.description,
                "trigger": intent.payload.get("trigger", "on_change"),
                "scope": intent.payload.get("scope", "form"),
                "priority": final_priority,
                "enabled": 1,
            }
            rules_table["insert"].append(rule)

            for cond in intent.payload.get("conditions", []):
                lhs_ref = cond.get("lhs_ref")
                resolved_lhs_ref = await _resolve_field_reference(lhs_ref, form_id, db, change_set)
                
                conditions_table["insert"].append(
                    {
                        "id": _placeholder("cond"),
                        "rule_id": rule_id,
                        "group_id": None,
                        "lhs_ref": resolved_lhs_ref,
                        "operator": cond.get("operator", "="),
                        "rhs": cond.get("rhs"),
                        "bool_join": cond.get("bool_join", "AND"),
                        "position": cond.get("position"),
                    }
                )

            for act in intent.payload.get("actions", []):
                target_ref = act.get("target_ref")
                resolved_target_ref = await _resolve_field_reference(target_ref, form_id, db, change_set)
                
                actions_table["insert"].append(
                    {
                        "id": _placeholder("act"),
                        "rule_id": rule_id,
                        "action": act.get("action"),
                        "target_ref": resolved_target_ref,
                        "params": act.get("params"),
                        "position": act.get("position"),
                    }
                )
        
        elif intent.operation is OperationType.update:
            rule_identifier = intent.payload.get("rule_id") or intent.description
            existing_rules = await db.get_logic_rules_for_form(form_id)
            
            matching_rule = None
            if rule_identifier and not rule_identifier.startswith("$"):
                matching_rule = next(
                    (r for r in existing_rules if r["id"] == rule_identifier),
                    None
                )
            
            if not matching_rule and intent.description:
                matching_rule = next(
                    (r for r in existing_rules if r["name"] == intent.description),
                    None
                )
            
            if not matching_rule:
                raise ValueError(
                    f"Could not find existing logic rule to update: {rule_identifier or intent.description}"
                )
            
            rule_id = matching_rule["id"]
            
            update_rule = {"id": rule_id}
            if "trigger" in intent.payload:
                update_rule["trigger"] = intent.payload["trigger"]
            if "scope" in intent.payload:
                update_rule["scope"] = intent.payload["scope"]
            if "priority" in intent.payload:
                update_rule["priority"] = intent.payload["priority"]
            if "enabled" in intent.payload:
                update_rule["enabled"] = 1 if intent.payload["enabled"] else 0
            if intent.description:
                update_rule["name"] = intent.description
            
            if len(update_rule) > 1:
                rules_table["update"].append(update_rule)
            
            if "conditions" in intent.payload:
                existing_conditions = await db.fetch_all(
                    "SELECT * FROM logic_conditions WHERE rule_id = ?",
                    [rule_id]
                )
                existing_condition_ids = {c["id"] for c in existing_conditions}
                
                for cond in intent.payload["conditions"]:
                    cond_id = cond.get("id")
                    if cond_id and cond_id in existing_condition_ids:
                        update_cond = {"id": cond_id}
                        if "lhs_ref" in cond:
                            resolved = await _resolve_field_reference(cond["lhs_ref"], form_id, db, change_set)
                            update_cond["lhs_ref"] = resolved
                        if "operator" in cond:
                            update_cond["operator"] = cond["operator"]
                        if "rhs" in cond:
                            update_cond["rhs"] = cond["rhs"]
                        if "bool_join" in cond:
                            update_cond["bool_join"] = cond["bool_join"]
                        if "position" in cond:
                            update_cond["position"] = cond["position"]
                        conditions_table["update"].append(update_cond)
                    else:
                        resolved_lhs_ref = await _resolve_field_reference(
                            cond.get("lhs_ref"), form_id, db, change_set
                        )
                        conditions_table["insert"].append({
                            "id": _placeholder("cond"),
                            "rule_id": rule_id,
                            "group_id": None,
                            "lhs_ref": resolved_lhs_ref,
                            "operator": cond.get("operator", "="),
                            "rhs": cond.get("rhs"),
                            "bool_join": cond.get("bool_join", "AND"),
                            "position": cond.get("position"),
                        })
            
            if "actions" in intent.payload:
                existing_actions = await db.fetch_all(
                    "SELECT * FROM logic_actions WHERE rule_id = ?",
                    [rule_id]
                )
                existing_action_ids = {a["id"] for a in existing_actions}
                
                for act in intent.payload["actions"]:
                    act_id = act.get("id")
                    if act_id and act_id in existing_action_ids:
                        update_act = {"id": act_id}
                        if "action" in act:
                            update_act["action"] = act["action"]
                        if "target_ref" in act:
                            resolved = await _resolve_field_reference(act["target_ref"], form_id, db, change_set)
                            update_act["target_ref"] = resolved
                        if "params" in act:
                            update_act["params"] = act["params"]
                        if "position" in act:
                            update_act["position"] = act["position"]
                        actions_table["update"].append(update_act)
                    else:
                        resolved_target_ref = await _resolve_field_reference(
                            act.get("target_ref"), form_id, db, change_set
                        )
                        actions_table["insert"].append({
                            "id": _placeholder("act"),
                            "rule_id": rule_id,
                            "action": act.get("action"),
                            "target_ref": resolved_target_ref,
                            "params": act.get("params"),
                            "position": act.get("position"),
                        })
        
        elif intent.operation is OperationType.delete:
            rule_identifier = intent.payload.get("rule_id") or intent.description
            existing_rules = await db.get_logic_rules_for_form(form_id)
            
            matching_rule = None
            if rule_identifier and not rule_identifier.startswith("$"):
                matching_rule = next(
                    (r for r in existing_rules if r["id"] == rule_identifier),
                    None
                )
            
            if not matching_rule and intent.description:
                matching_rule = next(
                    (r for r in existing_rules if r["name"] == intent.description),
                    None
                )
            
            if not matching_rule:
                raise ValueError(
                    f"Could not find existing logic rule to delete: {rule_identifier or intent.description}"
                )
            
            rule_id = matching_rule["id"]
            
            rules_table["delete"].append({"id": rule_id})
            
            existing_conditions = await db.fetch_all(
                "SELECT id FROM logic_conditions WHERE rule_id = ?",
                [rule_id]
            )
            for cond in existing_conditions:
                conditions_table["delete"].append({"id": cond["id"]})
            
            existing_actions = await db.fetch_all(
                "SELECT id FROM logic_actions WHERE rule_id = ?",
                [rule_id]
            )
            for act in existing_actions:
                actions_table["delete"].append({"id": act["id"]})


