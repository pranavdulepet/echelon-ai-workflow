"""
Core agent to turn natural language into an intent plan and final change-set.
"""

from typing import Any
import json

from pydantic import ValidationError

from .config import get_settings
from .db import Database, TableInfo
from .schema_cache import get_schema_state
from .intent_schema import IntentPlan
from .llm_client import LlmClient
from .resolver import build_change_set, ResolutionClarificationNeeded


def _schema_summary(tables: list[TableInfo]) -> str:
    lines: list[str] = ["Database Tables:"]
    for table in tables:
        column_parts = [f"{c.name}:{c.type}" for c in table.columns]
        lines.append(f"  {table.name}({', '.join(column_parts)})")
    return "\n".join(lines)


async def _get_forms_and_fields_summary(db: Database) -> str:
    try:
        field_types = await db.fetch_all("SELECT key FROM field_types ORDER BY key")
        available_types = ", ".join([ft["key"] for ft in field_types])
        
        forms = await db.fetch_all(
            "SELECT id, slug, title FROM forms ORDER BY title"
        )
        if not forms:
            return f"Available field types: {available_types}\n\nNo forms exist in the database yet."
        
        lines = [f"Available field types: {available_types}", "", "Existing Forms and Fields:"]
        for form in forms:
            lines.append(f"\n  Form: {form['title']} (slug={form['slug']}, id={form['id']})")
            fields = await db.fetch_all(
                "SELECT code, label, ft.key as field_type "
                "FROM form_fields f "
                "JOIN field_types ft ON ft.id = f.type_id "
                "WHERE f.form_id = ? "
                "ORDER BY f.position",
                [form["id"]],
            )
            if fields:
                for field in fields:
                    lines.append(f"    - {field['label']} (code={field['code']}, type={field['field_type']})")
            else:
                lines.append("    (no fields yet)")
        return "\n".join(lines)
    except Exception as e:
        print(f"Error in _get_forms_and_fields_summary: {e}")
        import traceback
        traceback.print_exc()
        return f"Error loading forms and fields: {e}"


class FormAgent:
    def __init__(self, db: Database | None = None, llm: LlmClient | None = None) -> None:
        self.db = db or Database()
        self.llm = llm or LlmClient()
        self.settings = get_settings()

    async def _get_schema_summary(self) -> str:
        state = await get_schema_state(self.db)
        table_summary = _schema_summary(state.tables)
        forms_summary = await _get_forms_and_fields_summary(self.db)
        return f"{table_summary}\n\n{forms_summary}"

    async def plan_from_query(self, query: str, history: list[dict[str, str]] | None = None) -> IntentPlan:
        normalized = query.strip()
        if not normalized:
            raise ValueError("Query must not be empty.")
        schema_summary = await self._get_schema_summary()

        history_block = ""
        if history:
            pieces = []
            for item in history[-5:]:
                q = item.get("question", "").strip()
                a = item.get("answer", "").strip()
                if q or a:
                    pieces.append(f"Q: {q}\nA: {a}")
            if pieces:
                history_block = (
                    "IMPORTANT: Previous clarification questions and answers:\n"
                    + "\n".join(pieces)
                    + "\n\n"
                    + "You MUST use the answers above to fill in missing information. "
                    + "If a previous question asked about a form or field, and the user provided an answer, "
                    + "use that answer in your plan. Only ask a NEW clarification question if information is STILL missing "
                    + "after considering all previous answers.\n\n"
                    + "INTERPRETING VAGUE ANSWERS:\n"
                    + "- If you suggested options/values and user said 'that's fine', 'okay', 'yes', or similar, "
                    + "interpret this as accepting your suggestions and use them in the plan\n"
                    + "- If user said 'create a new field' or 'add new field', set operation to 'insert' and do NOT look for existing fields\n"
                    + "- If user provides a partial answer, try to infer the complete intent from context\n\n"
                )

        intent_schema_description = """
The JSON object must match this schema:
{
  "fields": [
    {
      "operation": "insert" | "update" | "delete",
      "target_form": { "form_id": string|null, "form_name": string|null, "form_code": string|null },
      "field_code": string|null,
      "field_label": string|null,
      "field_type": string|null,
      "page_hint": string|null,
      "properties": object
    }
  ],
  "options": [
    {
      "operation": "insert" | "update" | "delete",
      "target_form": { "form_id": string|null, "form_name": string|null, "form_code": string|null },
      "field_code": string|null,
      "field_label": string|null,
      "add_values": string[],
      "rename_map": {string:string},
      "remove_values": string[]
    }
  ],
  "logic_blocks": [
    {
      "operation": "insert" | "update" | "delete",
      "target_form": { "form_id": string|null, "form_name": string|null, "form_code": string|null },
      "description": string,
      "payload": object
    }
  ],
  "notes": string|null,
  "needs_clarification": boolean,
  "clarification_question": string|null
}
"""

        examples_block = """
        Examples:

        1. User: "update the dropdown options for the destination field in the travel request form: 1. add a paris option, 2. change tokyo to milan"
        Response:
        {
            "fields": [],
            "options": [{
            "operation": "insert",
            "target_form": {"form_name": "Travel Request", "form_code": "travel-complex"},
            "field_code": "destinations",
            "field_label": "Destinations",
            "add_values": ["Paris"],
            "rename_map": {"Tokyo": "Milan"},
            "remove_values": []
            }],
            "logic_blocks": [],
            "needs_clarification": false,
            "clarification_question": null
        }

        2. User: "I want the employment form to require university_name when employment_status is Student"
        Response:
        {
            "fields": [{
            "operation": "insert",
            "target_form": {"form_name": "Employment Demo"},
            "field_code": "university_name",
            "field_label": "University name",
            "field_type": "short_text",
            "properties": {"required": false, "visible_by_default": false}
            }],
            "options": [],
            "logic_blocks": [{
            "operation": "insert",
            "target_form": {"form_name": "Employment Demo"},
            "description": "Show and require university_name when employment_status is Student",
            "payload": {
                "trigger": "on_change",
                "scope": "form",
                "priority": 100,
                "conditions": [{
                "lhs_ref": "{\"type\":\"field\",\"field_code\":\"employment_status\",\"property\":\"value\"}",
                "operator": "=",
                "rhs": "\"Student\"",
                "bool_join": "AND",
                "position": 1
                }],
                "actions": [{
                "action": "show",
                "target_ref": "{\"type\":\"field\",\"field_code\":\"university_name\"}",
                "params": null,
                "position": 1
                }, {
                "action": "require",
                "target_ref": "{\"type\":\"field\",\"field_code\":\"university_name\"}",
                "params": null,
                "position": 2
                }]
            }
            }],
            "needs_clarification": false,
            "clarification_question": null
        }

        3. User: "add a description field to the form"
        Response (needs clarification):
        {
            "fields": [],
            "options": [],
            "logic_blocks": [],
            "notes": "User did not specify which form",
            "needs_clarification": true,
            "clarification_question": "Which form would you like to add the description field to? Available forms: Travel Request (travel-complex), Employment Demo (employment-demo), Snack Request (snack-request)"
        }

        4. User: "I want to create a new form to allow employees to request a new snack. There should be a category field (ice cream/ beverage/ fruit/ chips/ gum), and name of the item (text)."
        Response:
        {
            "fields": [{
            "operation": "insert",
            "target_form": {"form_name": "Snack Request"},
            "field_code": "category",
            "field_label": "Category",
            "field_type": "dropdown",
            "properties": {"required": true}
            }, {
            "operation": "insert",
            "target_form": {"form_name": "Snack Request"},
            "field_code": "item_name",
            "field_label": "Item name",
            "field_type": "short_text",
            "properties": {"required": true}
            }],
            "options": [{
            "operation": "insert",
            "target_form": {"form_name": "Snack Request"},
            "field_code": "category",
            "field_label": "Category",
            "add_values": ["ice cream", "beverage", "fruit", "chips", "gum"],
            "rename_map": {},
            "remove_values": []
            }],
            "logic_blocks": [],
            "needs_clarification": false,
            "clarification_question": null
        }

        ZERO HALLUCINATIONS POLICY - CRITICAL RULES:
        - NEVER assume, guess, or invent ANY information
        - NEVER use generic names like "field", "input", "text", "name", "form" - these are assumptions
        - NEVER infer field types, option values, or form names from context
        - If ANY information is missing, you MUST set needs_clarification=true
        - When needs_clarification=true, the plan MUST be completely empty: fields=[], options=[], logic_blocks=[]
        - Only populate fields/options/logic_blocks when you have EXPLICIT, SPECIFIC information from the user
        - If the user says "I want a form for X" without specifying fields, you MUST ask what fields they want
        - If the user says "add a field" without specifying type, you MUST ask what type
        - If the user says "add options" without specifying values, you MUST ask for the exact values

        REQUIRED INFORMATION CHECKLIST - Ask clarification if ANY are missing:
        For NEW FORMS:
        - [ ] Form name/title (must be specific, not generic)
        - [ ] ALL field names/labels (must be specific)
        - [ ] ALL field types (must be one of: short_text, long_text, dropdown, radio, checkbox, tags, date, number, file_upload, email)
        - [ ] ALL field properties (required, placeholder, etc.) - if not specified, ask
        - [ ] ALL option values (if any field needs options)

        For EXISTING FORMS:
        - [ ] Exact form identification (form_name or form_code from schema)
        - [ ] Exact field identification (field_code or field_label from schema)
        - [ ] Field type (if adding new field)
        - [ ] Option values (if adding options)

        For LOGIC RULES:
        - [ ] Complete conditions with field references
        - [ ] Complete actions with field references

        Key guidelines:
        - ALWAYS check the database schema summary above to find the exact form and field names
        - For EXISTING forms/fields: Match names/codes EXACTLY to what exists in the schema
        - For NEW forms: ONLY use the EXACT form name the user provides - never infer or assume
        - For option intents: provide both field_code and field_label from the schema if available
        - If user says "destination field" and schema shows "destinations", use "destinations"
        - When updating options, operation should be "insert" (we add/rename within that operation)
        - When creating new forms, include ALL fields and options in one plan ONLY if user specified all of them
        - Be specific with form identification: use form_name or form_code, preferably both
        - For field_type, use ONLY these values: "short_text", "long_text", "dropdown", "radio", "checkbox", "tags", "date", "number", "file_upload", "email"
        - Use "dropdown" for select/dropdown fields, "short_text" for text inputs, "long_text" for textareas
        - For logic blocks: payload must have "conditions" array with lhs_ref/operator/rhs and "actions" array with action/target_ref
        - Use field_code (not field_id) in lhs_ref and target_ref - IDs will be resolved later
        - Conditions: lhs_ref and rhs are JSON strings, operator is "=" or "!=" or "contains", etc.
        - Actions: action is "show", "hide", "require", "optional", etc. (not "show_field" or "require_field")

        Clarification question guidelines:
        - Make questions SPECIFIC and PERSONALIZED to the user's request
        - Include relevant context: list available forms/fields when asking which one to use
        - Reference what the user originally asked for in your question
        - Ask for ONE piece of missing information at a time
        - Example: Instead of "Which form?", ask "Which form would you like to add the description field to? Available forms: Travel Request (travel-complex), Employment Demo (employment-demo)"
        - Example: Instead of "Which field?", ask "Which field should be updated? The form has these fields: Destinations (destinations), Start Date (start_date), End Date (end_date)"
        - If previous clarification answers provide the needed information, DO NOT ask again - use that information instead
        - IMPORTANT: When user says "create a new field" or "add new field", the operation MUST be "insert" and you should NOT look for existing fields
        - If user's answer is vague (e.g., "that's fine", "okay", "yes"), ask for specific details or interpret based on context (e.g., if you suggested options and they said "that's fine", use those suggested options)
        - When asking about field options for a NEW field, make it clear the field will be created and ask for the specific option values
        - CRITICAL: If needs_clarification=true, the plan MUST be empty (fields=[], options=[], logic_blocks=[])
        - Never populate fields/options/logic_blocks if you're also asking for clarification - wait until you have all information
        """

        system_prompt = (
            "You are an assistant that plans edits to a form management database.\n"
            "You never write SQL or concrete IDs. You only produce a structured intent plan.\n"
            "\n"
            "ZERO HALLUCINATIONS POLICY - CRITICAL:\n"
            "You MUST ask clarification questions for ANY missing information. Never assume, guess, or invent:\n"
            "- Form names, titles, slugs, or codes\n"
            "- Field names, labels, codes, or types\n"
            "- Field properties (required, placeholder, etc.)\n"
            "- Option values or labels\n"
            "- Logic rule conditions or actions\n"
            "- Any other details not explicitly provided by the user\n"
            "\n"
            "REQUIRED INFORMATION CHECKLIST:\n"
            "Before setting needs_clarification=false, ensure you have:\n"
            "1. For new forms: form name/title, ALL field details (code, label, type, properties), ALL option values if needed\n"
            "2. For existing forms: exact form identification (name/code), exact field identification if modifying fields\n"
            "3. For field operations: field_code OR field_label, field_type (if insert), all required properties\n"
            "4. For option operations: exact field identification, all option values/labels\n"
            "5. For logic rules: complete conditions and actions with field references\n"
            "\n"
            "CRITICAL RULES:\n"
            "- If ANY information is missing, set needs_clarification=true\n"
            "- If needs_clarification=true, the plan should be EMPTY (no fields, options, or logic_blocks)\n"
            "- Only populate fields/options/logic_blocks when you have ALL required information\n"
            "- Never use generic values like 'field', 'input', 'text' - ask for specific names\n"
            "- Never infer field types - ask the user what type they want\n"
            "- Never assume option values - ask for the exact list\n"
            "\n"
            "CRITICAL: Before asking a clarification question:\n"
            "1. Check if previous clarification answers already provide the missing information\n"
            "2. If yes, use that information and proceed with the plan\n"
            "3. If no, ask ONE specific, personalized question with context\n"
            "4. Include available options (forms/fields) in your question when relevant\n"
            "5. Reference the user's original request in your question\n"
            "\n"
            "When ANY information is missing or ambiguous AFTER considering all previous answers, "
            "you MUST set needs_clarification=true and ask exactly one specific question with context.\n"
            "Never guess form names, field types, option values, or any other details.\n"
            "Always respond with a single JSON object only, no extra text.\n"
            "\n"
            "Database schema summary:\n"
            f"{schema_summary}\n"
            "\n"
            "The database stores enterprise forms with pages, fields, option sets and items, and logic rules.\n"
            "Think in terms of forms, fields, options, and logic, not raw tables.\n"
            "\n"
            + examples_block
            + "\n"
            + intent_schema_description
        )

        user_prompt = (
            history_block
            + "User request:\n"
            + normalized
            + "\n\nPlan the edits as an intent JSON object."
        )

        raw = self.llm.generate_json(system_prompt=system_prompt, user_prompt=user_prompt)
        try:
            plan = IntentPlan.model_validate(raw)
        except ValidationError as exc:
            repaired = self._attempt_plan_repair(raw, exc)
            plan = IntentPlan.model_validate(repaired)
        return plan

    async def critique_intent_plan(self, query: str, plan: IntentPlan, history: list[dict[str, str]] | None = None) -> IntentPlan:
        skeleton = plan.model_copy(deep=True)
        skeleton.notes = None
        skeleton.needs_clarification = False
        skeleton.clarification_question = None

        history_block = ""
        if history:
            pieces = []
            for item in history[-5:]:
                q = item.get("question", "").strip()
                a = item.get("answer", "").strip()
                if q or a:
                    pieces.append(f"Q: {q}\nA: {a}")
            if pieces:
                history_block = (
                    "Previous clarification questions and answers:\n"
                    + "\n".join(pieces)
                    + "\n\n"
                    + "IMPORTANT: If the plan sets needs_clarification=true but a previous answer already provides "
                    + "the missing information, you should set needs_clarification=false and incorporate that answer into the plan.\n\n"
                )

        system_prompt = (
            "You are reviewing a planned set of edits to a form management database.\n"
            "Your primary job is to detect ASSUMPTIONS and HALLUCINATIONS.\n"
            "\n"
            "CRITICAL VALIDATION RULES:\n"
            "1. If needs_clarification=true, the plan MUST be empty (fields=[], options=[], logic_blocks=[])\n"
            "2. Check if the plan contains any generic or assumed values (e.g., 'field', 'input', 'text')\n"
            "3. Verify all required fields are present (form identification, field types, option values, etc.)\n"
            "4. Ensure no information is inferred or guessed - everything must be explicitly provided\n"
            "5. If ANY information is missing, set needs_clarification=true and empty the plan\n"
            "\n"
            "If you detect assumptions or missing information:\n"
            "- Set needs_clarification=true\n"
            "- Clear fields, options, and logic_blocks arrays\n"
            "- Create a specific clarification question asking for the missing information\n"
            "\n"
            "Check if previous clarification answers resolve any ambiguities in the plan.\n"
            "If the plan asks for clarification but previous answers already provide the needed information, "
            "update the plan to use that information and set needs_clarification=false.\n"
            "If it is acceptable, return the same JSON. If you see clear issues, return a corrected JSON plan.\n"
            "Do not add deletes unless clearly requested.\n"
            "Always respond with a single JSON object matching the intent plan schema, and nothing else.\n"
        )

        user_prompt = (
            history_block
            + "User request:\n"
            f"{query.strip()}\n\n"
            "Planned intent JSON (to review):\n"
            f"{skeleton.model_dump_json(indent=2)}\n\n"
            "Return the reviewed intent JSON."
        )

        raw = self.llm.generate_json(system_prompt=system_prompt, user_prompt=user_prompt)
        try:
            reviewed = IntentPlan.model_validate(raw)
        except ValidationError:
            return plan
        return reviewed

    def _attempt_plan_repair(self, raw: dict[str, Any], error: ValidationError) -> dict[str, Any]:
        repaired: dict[str, Any] = {
            "fields": [],
            "options": [],
            "logic_blocks": [],
            "notes": f"Validation error, repaired: {error.errors()}",
            "needs_clarification": True,
            "clarification_question": "I could not understand all details of your request. Can you restate it more concretely?",
        }
        if isinstance(raw, dict):
            if isinstance(raw.get("fields"), list):
                repaired["fields"] = raw["fields"]
            if isinstance(raw.get("options"), list):
                repaired["options"] = raw["options"]
            if isinstance(raw.get("logic_blocks"), list):
                repaired["logic_blocks"] = raw["logic_blocks"]
        return repaired

    async def plan_and_resolve(self, query: str, history: list[dict[str, str]] | None = None) -> dict[str, Any]:
        from .change_set_validator import validate_change_set
        from .exceptions import ChangeSetValidationError, ChangeSetStructureError
        from .plan_validator import detect_assumptions, should_ask_clarification
        
        schema_summary = await self._get_schema_summary()
        
        plan = await self.plan_from_query(query=query, history=history)
        plan = await self.critique_intent_plan(query=query, plan=plan, history=history)
        
        issues = await detect_assumptions(plan, self.db)
        if issues:
            needs_clarification, question = should_ask_clarification(plan, issues, query)
            if needs_clarification:
                plan.needs_clarification = True
                plan.clarification_question = question
                plan.fields = []
                plan.options = []
                plan.logic_blocks = []
        
        if plan.needs_clarification:
            question = (
                plan.clarification_question
                or "I need a bit more detail to plan these changes. Can you clarify what you want to modify?"
            )
            return {
                "type": "clarification",
                "question": question,
                "plan": plan.model_dump(),
            }

        try:
            change_set = await build_change_set(plan=plan, db=self.db)
            await validate_change_set(change_set, self.db)
        except ResolutionClarificationNeeded as exc:
            payload: dict[str, Any] = {
                "type": "clarification",
                "question": str(exc),
                "plan": plan.model_dump(),
            }
            if getattr(exc, "reason", None):
                payload["reason"] = exc.reason
            if getattr(exc, "form_candidates", None):
                payload["form_candidates"] = exc.form_candidates
            if getattr(exc, "field_candidates", None):
                payload["field_candidates"] = exc.field_candidates
            return payload
        except (ChangeSetValidationError, ChangeSetStructureError) as exc:
            return {
                "type": "clarification",
                "question": f"I encountered an issue with the planned changes: {str(exc)}. Could you please restate your request?",
                "plan": plan.model_dump(),
            }

        form_ids: set[str] = set()
        option_set_ids: set[str] = set()
        
        for table_name, ops in change_set.items():
            for op_name in ("insert", "update", "delete"):
                for row in ops.get(op_name, []):
                    if not isinstance(row, dict):
                        continue
                    form_id = row.get("form_id")
                    if isinstance(form_id, str) and not form_id.startswith("$"):
                        form_ids.add(form_id)
                    if table_name == "forms" and op_name in ("update", "delete"):
                        row_id = row.get("id")
                        if isinstance(row_id, str) and not row_id.startswith("$"):
                            form_ids.add(row_id)
                    # For option_items, track option_set_id to find the form later
                    if table_name == "option_items":
                        option_set_id = row.get("option_set_id")
                        if isinstance(option_set_id, str):
                            option_set_ids.add(option_set_id)
        
        # Look up forms for option changes
        # option_sets table has form_id directly, so we can query it
        if option_set_ids:
            for option_set_id in option_set_ids:
                try:
                    option_set_row = await self.db.fetch_one(
                        "SELECT form_id FROM option_sets WHERE id = ?",
                        (option_set_id,)
                    )
                    if option_set_row and option_set_row.get("form_id"):
                        form_ids.add(option_set_row["form_id"])
                except Exception as e:
                    # Log but don't fail if we can't find the form
                    print(f"Warning: Could not find form for option_set_id {option_set_id}: {e}")

        before_snapshot: dict[str, Any] | None = None
        if form_ids:
            before_snapshot = await self.db.get_form_snapshots(sorted(form_ids))

        return {
            "type": "change_set",
            "plan": plan.model_dump(),
            "change_set": change_set,
            "before_snapshot": before_snapshot,
        }

    def explain_change_set(
        self,
        query: str,
        plan: dict[str, Any] | None,
        change_set: dict[str, Any],
    ) -> str:
        system_prompt = (
            "You explain planned edits to a form management database.\n"
            "Describe the impact in clear, concise language.\n"
            "Focus on forms, fields, options, and logic rules, not SQL or table names.\n"
            "Do not invent changes that are not present in the JSON.\n"
        )

        parts: list[str] = [
            "Original request:",
            query.strip(),
            "",
        ]
        if plan is not None:
            parts.append("Intent plan (JSON):")
            parts.append(json.dumps(plan, indent=2))
            parts.append("")
        parts.append("Planned change-set (JSON):")
        parts.append(json.dumps(change_set, indent=2))
        parts.append("")
        parts.append(
            "Explain these changes in 3-7 short bullet points or paragraphs, focusing on what the user will observe."
        )

        user_prompt = "\n".join(parts)
        explanation = self.llm.generate_text(system_prompt=system_prompt, user_prompt=user_prompt)
        return explanation


