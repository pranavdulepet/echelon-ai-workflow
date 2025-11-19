"""
Change-set validation and structure checking.
"""

from typing import Any

from .db import Database
from .exceptions import ChangeSetValidationError, ChangeSetStructureError
from .schema_cache import get_schema_state


async def validate_change_set_structure(change_set: dict[str, Any]) -> None:
    """
    Validate that the change-set structure is correct:
    - All placeholder IDs are properly referenced
    - No orphaned records
    - Foreign key relationships are valid
    """
    errors: list[str] = []
    
    # Collect all placeholder IDs that are created
    created_ids: set[str] = set()
    referenced_ids: set[str] = set()
    
    # Track form IDs
    form_ids: set[str] = set()
    page_ids: set[str] = set()
    field_ids: set[str] = set()
    option_set_ids: set[str] = set()
    option_item_ids: set[str] = set()
    rule_ids: set[str] = set()
    
    # First pass: collect all created IDs
    for table_name, operations in change_set.items():
        if not isinstance(operations, dict):
            continue
            
        for op_type in ("insert", "update", "delete"):
            if op_type not in operations:
                continue
                
            for row in operations[op_type]:
                if not isinstance(row, dict):
                    continue
                    
                # Collect IDs
                if "id" in row:
                    row_id = row["id"]
                    if isinstance(row_id, str):
                        if op_type == "insert" and row_id.startswith("$"):
                            created_ids.add(row_id)
                        elif op_type in ("update", "delete"):
                            referenced_ids.add(row_id)
                        
                        # Track by type
                        if table_name == "forms":
                            form_ids.add(row_id)
                        elif table_name == "form_pages":
                            page_ids.add(row_id)
                        elif table_name == "form_fields":
                            field_ids.add(row_id)
                        elif table_name == "option_sets":
                            option_set_ids.add(row_id)
                        elif table_name == "option_items":
                            option_item_ids.add(row_id)
                        elif table_name == "logic_rules":
                            rule_ids.add(row_id)
    
    # Second pass: validate references
    for table_name, operations in change_set.items():
        if not isinstance(operations, dict):
            continue
            
        for op_type in ("insert", "update", "delete"):
            if op_type not in operations:
                continue
                
            for row in operations[op_type]:
                if not isinstance(row, dict):
                    continue
                
                # Validate form_id references
                if "form_id" in row:
                    form_id = row["form_id"]
                    if isinstance(form_id, str):
                        if form_id.startswith("$"):
                            if form_id not in created_ids and form_id not in form_ids:
                                errors.append(
                                    f"{table_name}.{op_type}: references non-existent form placeholder {form_id}"
                                )
                
                # Validate page_id references
                if "page_id" in row:
                    page_id = row["page_id"]
                    if isinstance(page_id, str):
                        if page_id.startswith("$"):
                            if page_id not in created_ids and page_id not in page_ids:
                                errors.append(
                                    f"{table_name}.{op_type}: references non-existent page placeholder {page_id}"
                                )
                
                # Validate field_id references
                if "field_id" in row:
                    field_id = row["field_id"]
                    if isinstance(field_id, str):
                        if field_id.startswith("$"):
                            if field_id not in created_ids and field_id not in field_ids:
                                errors.append(
                                    f"{table_name}.{op_type}: references non-existent field placeholder {field_id}"
                                )
                
                # Validate option_set_id references
                if "option_set_id" in row:
                    option_set_id = row["option_set_id"]
                    if isinstance(option_set_id, str):
                        if option_set_id.startswith("$"):
                            if option_set_id not in created_ids and option_set_id not in option_set_ids:
                                errors.append(
                                    f"{table_name}.{op_type}: references non-existent option_set placeholder {option_set_id}"
                                )
                
                # Validate rule_id references (for logic_conditions and logic_actions)
                if "rule_id" in row:
                    rule_id = row["rule_id"]
                    if isinstance(rule_id, str):
                        if rule_id.startswith("$"):
                            if rule_id not in created_ids and rule_id not in rule_ids:
                                errors.append(
                                    f"{table_name}.{op_type}: references non-existent rule placeholder {rule_id}"
                                )
    
    if errors:
        error_msg = "Change-set structure validation failed:\n" + "\n".join(f"  - {e}" for e in errors)
        raise ChangeSetStructureError(error_msg)


async def validate_change_set(change_set: dict[str, Any], db: Database) -> None:
    """
    Validate that the change-set is correct:
    - Required fields are present for inserts
    - Update/delete operations reference existing records
    - Foreign key constraints are satisfied
    """
    errors: list[str] = []
    schema_state = await get_schema_state(db)
    
    # Build a map of table name to TableInfo
    tables_by_name = {table.name: table for table in schema_state.tables}
    
    # Collect all IDs that will exist after inserts
    existing_ids: dict[str, set[str]] = {}
    
    # First, get existing IDs from database for tables we're modifying
    for table_name in change_set.keys():
        if table_name not in tables_by_name:
            continue
        
        # Check if table has an 'id' column
        table_info = tables_by_name[table_name]
        has_id_column = any(col.name == "id" for col in table_info.columns)
        if not has_id_column:
            existing_ids[table_name] = set()
            continue
        
        # Get existing IDs for this table
        table_ids: set[str] = set()
        try:
            rows = await db.fetch_all(f"SELECT id FROM {table_name}")
            for row in rows:
                if "id" in row:
                    table_ids.add(str(row["id"]))
            existing_ids[table_name] = table_ids
        except Exception:
            # Table might not exist or query failed, skip
            existing_ids[table_name] = set()
    
    # Track IDs that will be created
    created_ids: dict[str, set[str]] = {table: set() for table in change_set.keys()}
    
    # Validate inserts first
    for table_name, operations in change_set.items():
        if table_name not in tables_by_name:
            continue
        
        table_info = tables_by_name[table_name]
        required_columns = [
            col.name
            for col in table_info.columns
            if col.not_null and not col.primary_key and col.default_value is None
        ]
        
        if "insert" in operations:
            for idx, row in enumerate(operations["insert"]):
                if not isinstance(row, dict):
                    continue
                
                # Check required fields
                for col_name in required_columns:
                    if col_name not in row or row[col_name] is None:
                        errors.append(
                            f"{table_name}.insert[{idx}]: missing required field '{col_name}'"
                        )
                
                # Track created IDs
                if "id" in row and isinstance(row["id"], str):
                    created_ids[table_name].add(row["id"])
    
    # Validate updates and deletes reference existing records
    for table_name, operations in change_set.items():
        if table_name not in tables_by_name:
            continue
        
        all_ids = existing_ids.get(table_name, set()) | created_ids.get(table_name, set())
        
        if "update" in operations:
            for idx, row in enumerate(operations["update"]):
                if not isinstance(row, dict):
                    continue
                
                if "id" not in row:
                    errors.append(f"{table_name}.update[{idx}]: missing 'id' field")
                else:
                    row_id = str(row["id"])
                    if not row_id.startswith("$") and row_id not in all_ids:
                        errors.append(
                            f"{table_name}.update[{idx}]: references non-existent record with id '{row_id}'"
                        )
        
        if "delete" in operations:
            for idx, row in enumerate(operations["delete"]):
                if not isinstance(row, dict):
                    continue
                
                if "id" not in row:
                    errors.append(f"{table_name}.delete[{idx}]: missing 'id' field")
                else:
                    row_id = str(row["id"])
                    if not row_id.startswith("$") and row_id not in all_ids:
                        errors.append(
                            f"{table_name}.delete[{idx}]: references non-existent record with id '{row_id}'"
                        )
    
    if errors:
        error_msg = "Change-set validation failed:\n" + "\n".join(f"  - {e}" for e in errors)
        raise ChangeSetValidationError(error_msg)

