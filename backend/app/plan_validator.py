"""
Validation logic to detect assumptions and hallucinations in intent plans.
"""

from typing import Any

from .intent_schema import IntentPlan
from .db import Database


async def detect_assumptions(plan: IntentPlan, db: Database) -> list[str]:
    """
    Detect if the plan contains assumptions or hallucinations.
    Returns a list of issues found.
    """
    issues: list[str] = []
    
    if plan.needs_clarification:
        if plan.fields:
            issues.append("Plan has needs_clarification=true but contains fields - should be empty")
        if plan.options:
            issues.append("Plan has needs_clarification=true but contains options - should be empty")
        if plan.logic_blocks:
            issues.append("Plan has needs_clarification=true but contains logic_blocks - should be empty")
        return issues
    
    generic_names = {"field", "input", "text", "name", "value", "item", "data", "form", "description", "title", "label"}
    generic_form_names = {"form", "new form", "my form", "the form", "a form", "form for", "form to"}
    
    for field in plan.fields:
        if field.field_code:
            code_lower = field.field_code.lower().strip()
            if code_lower in generic_names:
                issues.append(f"Field code '{field.field_code}' appears to be generic or assumed")
            elif len(code_lower) < 3:
                issues.append(f"Field code '{field.field_code}' is too short and may be generic")
        
        if field.field_label:
            label_lower = field.field_label.lower().strip()
            if label_lower in generic_names:
                issues.append(f"Field label '{field.field_label}' appears to be generic or assumed")
        
        if not field.target_form.form_id and field.target_form.form_name:
            form_name_lower = field.target_form.form_name.lower().strip()
            if any(generic in form_name_lower for generic in generic_form_names):
                issues.append(f"Form name '{field.target_form.form_name}' appears to be generic or assumed")
        
        if field.operation.value == "insert" and not field.field_type:
            issues.append(f"New field '{field.field_code or field.field_label}' missing required field_type")
        
        if not field.field_code and not field.field_label:
            issues.append("Field missing both field_code and field_label")
    
    new_form_fields = [f for f in plan.fields if f.operation.value == "insert" and not f.target_form.form_id]
    if new_form_fields:
        form_names = {f.target_form.form_name for f in new_form_fields if f.target_form.form_name}
        form_codes = {f.target_form.form_code for f in new_form_fields if f.target_form.form_code}
        
        if not form_names and not form_codes:
            issues.append("Creating new form but no form name or code specified")
        elif len(form_names) > 1:
            issues.append(f"Multiple form names specified for new form: {form_names}")
    
    for option in plan.options:
        if option.operation.value == "insert":
            if not option.add_values and not option.rename_map:
                issues.append(f"Option intent for field '{option.field_code or option.field_label}' has no values to add")
            elif option.add_values:
                for value in option.add_values:
                    value_lower = value.lower().strip()
                    if value_lower in generic_names or len(value_lower) < 2:
                        issues.append(f"Option value '{value}' appears to be generic or assumed")
    
    for logic in plan.logic_blocks:
        if not logic.description:
            issues.append("Logic block missing description")
        
        payload = logic.payload or {}
        conditions = payload.get("conditions", [])
        actions = payload.get("actions", [])
        
        if not conditions:
            issues.append("Logic block missing conditions")
        else:
            for cond in conditions:
                if not cond.get("lhs_ref"):
                    issues.append("Logic condition missing lhs_ref")
                if not cond.get("operator"):
                    issues.append("Logic condition missing operator")
        
        if not actions:
            issues.append("Logic block missing actions")
        else:
            for action in actions:
                if not action.get("action"):
                    issues.append("Logic action missing action type")
                if not action.get("target_ref"):
                    issues.append("Logic action missing target_ref")
    
    return issues


def should_ask_clarification(plan: IntentPlan, issues: list[str], query: str) -> tuple[bool, str]:
    """
    Determine if clarification is needed based on detected issues.
    Returns (needs_clarification, question).
    """
    if not issues:
        return (False, "")
    
    if plan.needs_clarification and plan.clarification_question:
        return (True, plan.clarification_question)
    
    issues_text = " ".join(issues).lower()
    
    if "new form" in issues_text or "creating new form" in issues_text:
        missing_parts = []
        if "form name" in issues_text or "no form name" in issues_text:
            missing_parts.append("What should the form be called? (Please provide a specific name or title)")
        if "field" in issues_text and ("missing" in issues_text or "generic" in issues_text):
            missing_parts.append("What fields should be on the form? (Please specify: field names, types, and which are required)")
        if "field_type" in issues_text:
            missing_parts.append("What types should the fields be? (e.g., text, dropdown, number, etc.)")
        if missing_parts:
            return (True, "To create this form, I need: " + " ".join(f"{i+1}) {part}" for i, part in enumerate(missing_parts)))
    
    if "generic" in issues_text or "assumed" in issues_text:
        if "field" in issues_text:
            return (True, "I noticed some field names appear to be generic. Please provide specific, descriptive names for each field.")
        if "form" in issues_text:
            return (True, "I need a specific name for the form. Please provide a descriptive title.")
    
    missing_info = []
    if any("field_type" in issue.lower() for issue in issues):
        missing_info.append("field types")
    if any("field_code" in issue.lower() or "field_label" in issue.lower() for issue in issues):
        missing_info.append("field names/labels")
    if any("option" in issue.lower() and "value" in issue.lower() for issue in issues):
        missing_info.append("option values")
    if any("logic" in issue.lower() and ("condition" in issue.lower() or "action" in issue.lower()) for issue in issues):
        missing_info.append("logic rule details")
    
    if missing_info:
        return (True, f"I need more information to complete your request. Please specify: {', '.join(missing_info)}.")
    
    return (True, "I need more details to understand your request. Could you please provide more specific information?")
