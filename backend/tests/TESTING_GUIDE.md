# Testing Guide: Coverage, Strategy, and Improvements

This guide explains the current testing infrastructure, what's covered, what's missing, and how to improve test coverage.

---

## Current Testing Infrastructure

The project has **three complementary testing approaches**:

### 1. **Scenario-Based Testing** (`scenarios.json` + `run_scenarios.py`)

**What it does**: Quick manual testing of natural language queries with real LLM calls.

**How to use**:
- Add scenarios to `backend/tests/scenarios.json`
- Run: `python backend/tests/run_scenarios.py`
- Inspect the printed change-sets

**Example**:
```json
{
    "name": "Update travel destination options",
    "query": "update the dropdown options for the destination field in the travel request form: 1. add a paris option, 2. change tokyo to milan",
    "provider": "openai"
}
```

**When to use**:
- Testing new query patterns
- Validating LLM output quality
- Debugging specific user requests
- Manual inspection of change-sets

**Limitations**:
- No automated assertions
- Results need manual review

---

### 2. **Invariant Testing** (`test_invariants.py`)

**What it does**: Automated validation that change-sets are structurally correct.

**How it works**:
- Uses `@pytest.mark.parametrize` to test multiple queries
- Runs full agent pipeline (LLM calls + resolution)
- Validates:
  - Change-set shape (correct JSON structure)
  - Required fields present in inserts
  - Update/delete IDs exist in database

**Run**: `pytest backend/tests/test_invariants.py -v`

**When to use**:
- Regression testing
- CI/CD validation
- Ensuring no breaking changes
- Validating structural correctness

**Limitations**:
- Requires API keys
- Doesn't validate semantic correctness (just structure)
- Can't test clarification flows easily (tests skip them)

---

### 3. **Resolver Unit Testing** (`test_resolver_examples.py`)

**What it does**: Test resolver logic deterministically without LLM calls.

**How it works**:
- Creates `IntentPlan` objects directly (bypasses LLM)
- Tests resolver conversion to change-sets
- Validates specific behaviors (e.g., field resolution, option updates)

**Run**: `pytest backend/tests/test_resolver_examples.py -v`

**When to use**:
- Fast, deterministic tests
- Testing resolver edge cases
- Validating field reference resolution
- No API costs

**Limitations**:
- Doesn't test LLM understanding
- Requires manual IntentPlan construction
- Can't test natural language parsing

---

## Current Test Coverage

### ✅ What's Well Tested

1. **Basic Insert Operations** (~80% coverage)
   - ✅ Field creation with proper types and properties
   - ✅ Option addition to dropdowns
   - ✅ Logic rule creation with conditions and actions
   - ✅ Form creation with pages

2. **Option Updates** (~70% coverage)
   - ✅ Adding new options
   - ✅ Renaming options (Tokyo → Milan)
   - ⚠️ Option removal/deactivation (tested indirectly)

3. **Structural Validation** (~90% coverage)
   - ✅ Change-set JSON shape validation
   - ✅ Required fields present in inserts
   - ✅ Update/delete IDs exist in database

4. **Field Reference Resolution** (~60% coverage)
   - ✅ Placeholder ID matching for new fields
   - ✅ Field code to field_id conversion
   - ✅ Basic field lookup in database

---

## Critical Gaps in Coverage

### 🔴 Priority 1: Critical Missing Tests

#### 1. **Update/Delete Operations** (0% coverage)
**Status**: We just implemented these features but **NO TESTS EXIST**

**What's missing**:
- ❌ Logic rule updates (changing trigger, priority, enabled status)
- ❌ Logic rule deletes
- ❌ Field updates (changing label, required, placeholder)
- ❌ Field deletes
- ❌ Option removal (explicit deactivation)

**Why this matters**:
- These are **new features** with no validation
- High risk of regressions
- Users will expect these operations to work

**Example test needed**:
```python
async def test_update_logic_rule():
    """Test updating an existing logic rule's priority and trigger"""
    # Create a rule, then update it
    # Verify the change-set contains the update
```

---

#### 2. **Priority Conflict Resolution** (0% coverage)
**Status**: Implemented but **NOT TESTED**

**What's missing**:
- ❌ Test that priority auto-adjusts when conflicts exist
- ❌ Test that priority doesn't conflict with existing rules
- ❌ Test that priority doesn't conflict with rules in same change-set

**Why this matters**:
- Prevents silent bugs where rules have duplicate priorities
- Ensures rules execute in correct order
- Critical for form logic correctness

**Example test needed**:
```python
async def test_priority_conflict_resolution():
    """Test that priority auto-adjusts when conflicts exist"""
    # Create rule with priority 10
    # Try to create another with priority 10
    # Verify second rule gets priority 11
```

---

#### 3. **Clarification Flows** (0% coverage)
**Status**: Tests **SKIP** when clarification is needed

**What's missing**:
- ❌ Test that ambiguous form references trigger clarification
- ❌ Test that ambiguous field references trigger clarification
- ❌ Test that missing information triggers clarification
- ❌ Test that clarification responses work correctly

**Why this matters**:
- Clarification is a **core feature** for handling ambiguous queries
- Users need to know when and why clarifications are asked
- No way to verify the clarification logic works

**Example test needed**:
```python
async def test_ambiguous_form_reference():
    """Test that ambiguous form names trigger clarification"""
    result = await agent.plan_and_resolve("add field to form")
    assert result["type"] == "clarification"
    assert "form" in result["question"].lower()
    assert len(result["form_candidates"]) > 1
```

---

#### 4. **Error Handling** (~20% coverage)
**Status**: **MINIMAL ERROR TESTS**

**What's missing**:
- ❌ Invalid field types
- ❌ Non-existent form references
- ❌ Non-existent field references
- ❌ Malformed JSON in logic references
- ❌ Missing required fields
- ❌ MAX_CHANGED_ROWS limit enforcement

**Why this matters**:
- Prevents crashes from invalid input
- Ensures graceful error messages
- Protects against malicious or malformed requests

---

### 🟡 Priority 2: Important Missing Tests

#### 5. **Edge Cases** (~30% coverage)
**What's missing**:
- ❌ Multiple forms with similar names
- ❌ Multiple fields with similar codes/labels
- ❌ Fields on different pages
- ❌ Forms with no fields
- ❌ Logic rules with complex conditions (multiple AND/OR)

**Why this matters**:
- Real-world scenarios often have edge cases
- Prevents subtle bugs in production

---

#### 6. **Field Reference Resolution Edge Cases** (~40% coverage)
**What's missing**:
- ❌ Invalid placeholder IDs
- ❌ Field code that doesn't exist
- ❌ Field references in update operations
- ❌ Field references across different forms

**Why this matters**:
- Field references are complex and error-prone
- Logic rules depend on correct field resolution

---

### 🟢 Priority 3: Nice-to-Have Tests

#### 7. **Semantic Validation** (0% coverage)
**What's missing**:
- ❌ Verify change-set actually implements the requested behavior
- ❌ Verify "add Paris" actually adds Paris
- ❌ Verify "require when Student" actually creates correct logic
- ❌ Golden output comparison

**Why this matters**:
- Ensures the agent does what the user asked
- Catches semantic errors (correct structure, wrong behavior)

---

#### 8. **API Endpoint Testing** (0% coverage)
**What's missing**:
- ❌ POST /api/query endpoint
- ❌ GET /api/forms endpoint
- ❌ GET /api/forms/{form_id} endpoint
- ❌ POST /api/explain endpoint
- ❌ Error responses (400, 404, 502)

**Why this matters**:
- API is the public interface
- Ensures endpoints work correctly
- Validates error handling

---

#### 9. **Provider Testing** (~50% coverage)
**What's missing**:
- ❌ Claude provider tests
- ❌ Provider switching
- ❌ Provider-specific behavior differences

**Why this matters**:
- Users can choose providers
- Different providers may behave differently
- Need to ensure consistency

---

## Coverage Summary

| Category | Coverage | Status |
|----------|----------|--------|
| Insert operations | ~80% | ✅ Good |
| Update operations | ~10% | ❌ Critical gap |
| Delete operations | ~5% | ❌ Critical gap |
| Error handling | ~20% | ❌ Needs work |
| Edge cases | ~30% | ⚠️ Limited |
| API endpoints | ~0% | ❌ Missing |
| Clarification flows | ~0% | ❌ Missing |
| Semantic validation | ~0% | ⚠️ Nice-to-have |

**Overall Coverage: ~35%**

---

## How to Add New Tests

### Quick Testing (Manual)

1. Edit `backend/tests/scenarios.json`:
```json
[
    {
        "name": "Your scenario name",
        "query": "Your natural language query here",
        "provider": "openai"
    }
]
```

2. Run: `python backend/tests/run_scenarios.py`

3. Review output and manually verify correctness

### Automated Testing (Invariants)

1. Edit `backend/tests/test_invariants.py`:
```python
@pytest.mark.parametrize("query", [
    # ... existing queries ...
    "Your new query here",
])
```

2. Run: `pytest backend/tests/test_invariants.py -v`

### Deterministic Testing (Unit Tests)

1. Create new test in `backend/tests/test_resolver_examples.py`:
```python
@pytest.mark.asyncio
async def test_your_scenario():
    db = Database()
    plan = IntentPlan(
        fields=[...],
        options=[...],
        logic_blocks=[...]
    )
    change_set = await build_change_set(plan, db)
    # Add assertions
```

2. Run: `pytest backend/tests/test_resolver_examples.py::test_your_scenario -v`

---

## Recommended Test Additions

### Immediate Priority (Before Production)

#### 1. Logic Rule Operations Tests
**File**: `backend/tests/test_logic_rule_operations.py`

```python
@pytest.mark.asyncio
async def test_update_logic_rule():
    """Test updating an existing logic rule"""
    # Create rule, then update priority/trigger
    # Verify update in change-set

@pytest.mark.asyncio
async def test_delete_logic_rule():
    """Test deleting a logic rule and its conditions/actions"""
    # Create rule, then delete
    # Verify rule, conditions, and actions in delete arrays

@pytest.mark.asyncio
async def test_priority_conflict_resolution():
    """Test that priority auto-adjusts when conflicts exist"""
    # Create rule with priority 10
    # Create another with priority 10
    # Verify second gets priority 11
```

**Why**: These are new features with zero test coverage. High risk of bugs.

---

#### 2. Field Operations Tests
**File**: `backend/tests/test_field_operations.py`

```python
@pytest.mark.asyncio
async def test_update_field_properties():
    """Test updating field label, required, placeholder"""
    
@pytest.mark.asyncio
async def test_delete_field():
    """Test deleting a field"""
```

**Why**: Field updates/deletes are common operations that need validation.

---

#### 3. Clarification Flow Tests
**File**: `backend/tests/test_clarification_flows.py`

```python
@pytest.mark.asyncio
async def test_ambiguous_form_reference():
    """Test that ambiguous form names trigger clarification"""
    result = await agent.plan_and_resolve("add field to form")
    assert result["type"] == "clarification"
    assert "form" in result["question"].lower()

@pytest.mark.asyncio
async def test_ambiguous_field_reference():
    """Test that ambiguous field names trigger clarification"""
    
@pytest.mark.asyncio
async def test_clarification_response():
    """Test that providing clarification resolves the issue"""
    # First request triggers clarification
    # Second request with answer should succeed
```

**Why**: Clarification is a core UX feature. Users need it to work correctly.

---

#### 4. Error Handling Tests
**File**: `backend/tests/test_error_handling.py`

```python
@pytest.mark.asyncio
async def test_invalid_field_type():
    """Test error when field_type doesn't exist"""
    
@pytest.mark.asyncio
async def test_nonexistent_form():
    """Test error when form doesn't exist"""
    
@pytest.mark.asyncio
async def test_max_changed_rows_limit():
    """Test that MAX_CHANGED_ROWS limit is enforced"""
```

**Why**: Prevents crashes and ensures graceful error handling.

---

### Short-term (Next Sprint)

5. **Edge Case Tests** - Complex scenarios, multiple matches, etc.
6. **Semantic Validation** - Verify change-sets match intent
7. **API Endpoint Tests** - Test FastAPI endpoints

### Long-term (Future)

8. **Golden Output Testing** - Exact-match validation against saved outputs
9. **Performance Testing** - Latency and token usage
10. **Provider Comparison** - OpenAI vs Claude behavior
11. **Integration Tests** - Full request/response cycles

---

## Testing Different Query Types

### Testing Option Updates
```json
{
    "name": "Update dropdown options",
    "query": "update the dropdown options for the destination field in the travel request form: 1. add a paris option, 2. change tokyo to milan"
}
```

**What to check**:
- `option_items.insert` contains new options
- `option_items.update` contains renamed options
- Correct `option_set_id` references
- Proper `position` values

### Testing Field Creation
```json
{
    "name": "Add field to form",
    "query": "add a description field to the travel request form"
}
```

**What to check**:
- `form_fields.insert` contains new field
- Correct `form_id` and `page_id`
- Proper `type_id` mapping
- Required fields populated

### Testing Logic Rules
```json
{
    "name": "Add conditional logic",
    "query": "I want the employment-demo form to require university_name when employment_status is 'Student'"
}
```

**What to check**:
- `logic_rules.insert` contains rule
- `logic_conditions.insert` has correct field references
- `logic_actions.insert` has show/require actions
- Field references use `field_id` (not `field_code`)

### Testing Form Creation
```json
{
    "name": "Create new form",
    "query": "I want to create a new form to allow employees to request a new snack"
}
```

**What to check**:
- `forms.insert` contains new form
- `form_pages.insert` contains at least one page
- All fields are on the form
- Options are linked correctly

### Testing Clarification Flows
```json
{
    "name": "Ambiguous form reference",
    "query": "add a description field to the form"
}
```

**What to check**:
- Returns `{"type": "clarification", ...}`
- `question` field is present
- `form_candidates` or `field_candidates` provided

---

## Running Tests

```bash
# Run all tests
pytest backend/tests/ -v

# Run only invariant tests (requires API keys)
pytest backend/tests/test_invariants.py -v

# Run only resolver tests (no API keys needed)
pytest backend/tests/test_resolver_examples.py -v

# Run scenario harness (manual inspection)
python backend/tests/run_scenarios.py

# Run specific test file
pytest backend/tests/test_logic_rule_operations.py -v

# Run specific test
pytest backend/tests/test_resolver_examples.py::test_update_travel_destination_options_matches_example -v
```

---

## Best Practices

1. **Start with `scenarios.json`** for quick manual testing
2. **Add to invariant tests** once you've validated manually
3. **Create resolver unit tests** for edge cases and deterministic validation
4. **Test both success and failure cases** (clarifications, errors)
5. **Test with both providers** (OpenAI and Claude) if possible
6. **Document expected behavior** in test names and comments
7. **Add tests for new features immediately** (don't let coverage gaps grow)

---

## Test Organization

Recommended structure:

```
backend/tests/
├── test_resolver_examples.py      # Existing: Deterministic resolver tests
├── test_invariants.py              # Existing: Structural validation
├── test_logic_rule_operations.py  # NEW: Update/delete logic rules
├── test_field_operations.py       # NEW: Update/delete fields
├── test_clarification_flows.py    # NEW: Clarification testing
├── test_error_handling.py         # NEW: Error cases
├── test_edge_cases.py              # NEW: Edge cases
├── test_semantic_validation.py     # NEW: Semantic correctness
├── test_api.py                      # NEW: API endpoints
├── test_providers.py                # NEW: Provider comparison
├── scenarios.json                   # Existing: Manual scenarios
└── run_scenarios.py                 # Existing: Scenario runner
```

---

## Conclusion

**Current Status**: Testing infrastructure is solid but coverage is incomplete (~35%).

**Critical Gaps**: Update/delete operations, clarification flows, and error handling have minimal or no test coverage.

**Recommendation**: Add Priority 1 tests (logic rule operations, field operations, clarification flows, error handling) before considering this production-ready. This would bring coverage to ~60-70% and validate all new features.

**Next Steps**:
1. Add tests for update/delete operations (highest priority)
2. Add clarification flow tests
3. Add basic error handling tests
4. Gradually add edge cases and semantic validation
