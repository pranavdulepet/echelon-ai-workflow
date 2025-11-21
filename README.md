## Overview

This project is an AI-powered planning agent for an enterprise form management system backed by a SQLite database. It takes natural-language requests such as:

- update options in an existing dropdown
- add new fields and dynamic logic to a form
- create new forms with specific fields

and returns a structured JSON change-set describing inserts, updates, and deletes for the underlying tables.

The backend is written in Python (FastAPI) with support for both OpenAI and Claude APIs. The frontend is a minimal React app that lets you type a request, answer clarifying questions, and inspect the resulting JSON.

## Project structure

- `backend/`: FastAPI service, agent logic, and SQLite helpers
- `frontend/`: React UI built with Vite
- `data/forms.sqlite`: SQLite database used by the sample app

## Running the backend

1. Create and activate a virtual environment:

```bash
python -m venv .venv
source .venv/bin/activate
```

2. Install backend dependencies:

```bash
cd backend
pip install -r requirements.txt
```

3. Configure environment variables in a `.env` file in the project root or export them (set `DISABLE_DOTENV=1` to skip loading `.env`, which is helpful in sandboxed CI or when file permissions are locked down):

```bash
OPENAI_API_KEY=sk-...
ANTHROPIC_API_KEY=sk-ant-...
LLM_PROVIDER=openai
OPENAI_MODEL=gpt-5.1
ANTHROPIC_MODEL=claude-3-5-sonnet-20241022
SQLITE_PATH=data/forms.sqlite
MAX_CHANGED_ROWS=100
```

4. Start the FastAPI server:

```bash
cd echelon-ai-workflow
uvicorn backend.app.main:app --reload --host 0.0.0.0 --port 8000
```

The API exposes (each response includes an `X-Request-ID` header so you can trace logs end-to-end):

- `POST /api/query` for running the agent
- `GET /health` for a basic health check

## Running the frontend

1. Install frontend dependencies:

```bash
cd echelon-ai-workflow/frontend
npm install
```

2. Start the development server:

```bash
npm run dev
```

3. Open the printed URL (usually `http://localhost:5173`) in a browser.

The frontend calls the backend at `/api/query` via a development proxy defined in `vite.config.ts`, so both should run locally for the UI to work.

## How the agent works

### High-level flow

1. User enters a natural-language request in the React UI.
2. Frontend sends the request to `POST /api/query` with a selected provider (OpenAI or Claude) and any prior clarification history. Before the text reaches any LLM, the backend runs prompt-injection detection, input sanitization, and clarification-history validation.
3. Backend agent:
   - pre-processes and normalizes the text
   - builds a compact prompt including a cached database schema summary, a comprehensive forms/fields inventory, and an explicit JSON schema for the intent plan
   - enforces a “ZERO HALLUCINATIONS” checklist so missing information automatically triggers clarifications instead of guesses
   - calls the chosen LLM in JSON mode to get an initial `IntentPlan`
   - runs a second, critique pass over the plan to check for obvious mismatches (if the critique result fails validation, the original plan is reused and the warning is logged)
   - validates/repairs the plan using Pydantic and a custom `plan_validator` that detects assumptions (e.g., generic field names, missing field types) and generates personalized clarification questions referencing prior answers
   - resolves forms, fields, option sets, and logic rules against SQLite
   - produces a JSON change-set keyed by table name with `insert`/`update`/`delete` arrays and a `before_snapshot` of affected forms
4. The change-set or a clarifying question is returned to the frontend and rendered as formatted JSON (with edit/save controls that validate user tweaks before applying them) plus an enhanced visual preview showing before/after states with detailed change highlighting.

### Intermediate intent representation

The agent uses a Pydantic model `IntentPlan` to represent the user’s request in domain terms instead of raw tables. It includes:

- field intents: add/update/delete fields on a form
- option intents: add/rename/deactivate options for a dropdown
- logic intents: add or adjust logic rules, conditions, and actions
- a clarification flag and question when the model is unsure

This separation makes it easier to keep prompts small and stable while evolving database details.

### LLM pre- and post-processing and reasoning

- Requests are trimmed and normalized, and a short history of prior clarifications is included.
- The prompt is split into clear roles:
  - system: domain rules, constraints, and the exact JSON schema for `IntentPlan`
  - user: current request, with optional history context
- Native structured output modes are used:
  - OpenAI chat completions with `response_format={"type": "json_object"}`
  - Claude messages with `response_format={"type": "json_object"}`
- The JSON is parsed and then validated against the Pydantic schema. On validation errors, the agent builds a conservative fallback plan that marks `needs_clarification=true` so the user can restate their request.
- A second \"critique\" call reviews the intent plan against the original request; it either returns the same plan, a corrected one, or triggers a clarification.

### SQLite resolution and change-set construction

The resolver converts the intent plan into concrete row changes:

- Forms are resolved by `title` or `slug` with ambiguity checks.
- Fields are resolved by `code` or `label`, scoped to the selected form.
- Option sets are discovered via `field_option_binding`. New sets and bindings are created when needed.
- For option updates:
  - new values are appended with appropriate `position`
  - renames update existing `value` and `label`
  - removals deactivate options via `is_active=0` rather than physical deletes
- New fields:
  - are placed on the last page of the form with the next position
  - use field type keys mapped through `field_types`
- Logic rules:
  - are inserted with generated placeholder IDs
  - include conditions and actions described in the intent payload
  - field references in `lhs_ref` and `target_ref` are automatically resolved from `field_code` to `field_id`
  - priority conflicts are automatically resolved by incrementing until a free slot is found
  - update and delete operations are supported for existing rules

The final change-set JSON follows the required format:

```json
{
  "table_name": {
    "insert": [ { ... } ],
    "update": [ { ... } ],
    "delete": [ { ... } ]
  }
}
```

IDs for inserts use placeholder tokens such as `$fld_xxxxxx` that can be referenced by other rows in the same plan.

In addition, the agent returns a `before_snapshot` structure for any affected forms so the UI can render an enhanced visual preview showing:
- Field additions, modifications, and deletions with before/after property changes
- Option changes (additions, renames, removals) displayed as visual pills
- Logic rules with readable condition and action descriptions
- Change summary statistics (counts of new/modified items)
- Field type badges and property indicators (read-only, hidden by default)

## Guardrails, idempotency, and ambiguity handling

- The agent prefers updates over inserts for existing entities when the intent is clearly to modify.
- Deactivation (`is_active=0`) is used for options instead of hard deletes unless a request is explicitly destructive.
- A configurable limit `MAX_CHANGED_ROWS` caps the number of rows that can be modified by a single request.
- Ambiguous matches for forms or fields surface as clarifying questions (e.g., listing multiple matching forms/fields) rather than silent failures.
- Intent validation ensures every `update` and `delete` references real rows where resolvable.
- `plan_validator` enforces the required-information checklist and generates specific clarification questions (including available forms/fields) when details are missing.
- `change_set_validator` runs after resolution to ensure placeholder references, required columns, and foreign keys are all valid before returning a response.
- Clarification questions are deduplicated to avoid loops; if the same wording repeats, the agent escalates with stronger messaging and flags the response with `reason=clarification_loop`.
- Option intents can reference fields inserted earlier in the same request because the resolver now matches against placeholder IDs, normalized codes, and labels (with ambiguity detection).

## Safety, security, and observability

- **Prompt injection defense**: `prompt_injection.py` detects malicious patterns (e.g., “ignore previous instructions”), strips control characters, wraps user text in sentinel markers, and validates clarification history structure before any LLM call.
- **Zero-hallucination policy**: System prompts contain a required-information checklist; missing details force `needs_clarification=true` with empty plan arrays, and the validator double-checks this.
- **Two-stage reasoning with safe fallback**: The critique model can only reduce risk; invalid critique JSON is logged and the previous plan is reused.
- **Structured error handling**: Custom exceptions (`ResolutionClarificationNeeded`, `ChangeSetStructureError`, `LLMOperationError`, etc.) are surfaced to FastAPI, which maps them to precise HTTP codes (400, 422, 502, 503) and user-friendly messages.
- **Request tracing**: Every HTTP request gets a UUID via `request_context`; the middleware adds `X-Request-ID` so logs, frontend, and API clients can align traces.
- **Change-set validation**: Beyond schema checks, the validator enforces row count ceilings (`MAX_CHANGED_ROWS`) and ensures placeholder IDs referenced by logic rules/options resolve correctly.
- **Frontend safeguards**: The JSON editor validates edits before applying and shows inline errors; the visual preview always reflects the parsed structure, not raw text, preventing malformed JSON from propagating.

## Testing and evaluation

There is a scenario example set and a small test suite under `backend/tests`:

- `backend/tests/scenarios.json` contains representative natural-language queries:
  - updating dropdown options on an existing form
  - adding conditional field requirements
  - creating a new form with specific fields
- `backend/tests/run_scenarios.py` runs the agent against these queries and prints the resulting change-sets.
- `backend/tests/test_resolver_examples.py` checks deterministic resolver behavior against the three standard examples (options update, snack form, employment logic).
- `backend/tests/test_invariants.py` runs end-to-end queries through the full agent and asserts invariants on the resulting change-sets (shape, required fields present, update/delete IDs exist), using the cached schema.
- `backend/tests/TESTING_GUIDE.md` documents the full testing strategy, coverage map, and how to extend each layer (scenarios, invariants, resolver unit tests).

Run the tests with:

```bash
cd echelon-ai-workflow/backend
python tests/run_scenarios.py
pytest
```

You can measure quality by checking:

- whether the correct tables are edited
- whether IDs for updates correspond to existing rows
- whether inserts have all required fields populated
- whether options and logic rules match the intended behavior

In a production setting, you could extend this to compute exact- and partial-match metrics against golden JSON outputs.

## Limitations

- The agent relies on LLM understanding of the domain; complex or very ambiguous requests may require multiple clarification questions.
- Only a subset of possible operations is modeled in the current intent schema, though the core patterns are in place.
- Logic rule updates support modifying properties and adding/updating conditions/actions, but complex rule merging (e.g., combining multiple rules) is not yet implemented.
- There is no automatic execution of the generated change-sets against the database; applying them is left to downstream tooling.

## Next steps

- Stronger validation by simulating SQL constraints before returning a change-set.
- One-click test runs for common scenarios directly from the UI.
- More detailed evaluation metrics and automated regression tests comparing outputs against a curated corpus of expected JSON plans.

## Design and implementation decisions

- **Separation of concerns**:
  - The system keeps three layers distinct:
    - `IntentPlan` (domain-level description of what to change).
    - Resolver (`resolver.py`) that maps the plan onto concrete table rows and IDs using SQLite.
    - UI that only ever sees the final JSON change-set and snapshots.
  - This makes it easier to evolve the DB schema or the UI without having to rewrite prompts.
- **Intermediate intent model**:
  - The agent thinks in terms of forms, fields, options, and logic rules, not raw tables.
  - This reduces prompt complexity and allows the planning step to remain relatively stable even if the underlying DB schema is refactored or extended.
- **LLM-assisted but DB-grounded**:
  - The LLM is responsible for understanding the natural-language request and producing a structured `IntentPlan`.
  - All ID resolution and constraint enforcement happens in code against the real SQLite DB; the model never has to guess IDs or refer to unknown tables.
  - **Enhanced context provision**: The agent provides the LLM with a comprehensive view of existing forms and fields, not just table schemas. This includes exact form titles, slugs, field codes, labels, and types, enabling accurate matching of natural language to database entities.
  - **Fuzzy matching fallback**: When exact matching fails, the resolver attempts fuzzy/partial matching on field codes and labels, handling common variations like singular/plural differences.
- **Two-stage reasoning**:
  - The first call generates an `IntentPlan`.
  - A second critique call reviews that plan against the original request and either accepts it, refines it, or triggers a clarification.
  - This is cheaper than always using a very large model and provides some self-checking behavior without a full "tool-loop" framework.
- **Few-shot learning**:
  - The agent includes three concrete examples in every prompt:
    1. Updating dropdown options (the most common use case).
    2. Adding fields with conditional logic.
    3. Handling ambiguous requests that need clarification.
  - These examples teach the LLM the exact structure of `IntentPlan` objects and how to properly identify forms/fields.
- **Explainability and UX**:
  - The visual preview and explanation mode are deliberately kept separate:
    - Visual preview is deterministic, driven by DB snapshots + change-set, showing exact field/option/logic changes with before/after states.
    - Explanations are LLM-generated text and treated as an aid, not a source of truth.
  - The visual preview provides:
    - Side-by-side before/after comparison of forms
    - Visual highlighting of new, modified, and deleted items
    - Detailed property change tracking (shows what changed and how)
    - Logic rule visualization with readable condition/action descriptions
    - Option change visualization with pills showing additions, renames, and removals
  - The JSON change-set viewer supports inline edit/save with validation, so advanced users can tweak the payload, re-parse it safely, and immediately see the visual preview update.
  - This avoids coupling correctness to free-form text while still giving users easily followable summaries and clear visual feedback.

## Assumptions and constraints

- The SQLite schema is the one shipped in `data/forms.sqlite` and does not change frequently.
- The agent is expected to operate in an **admin tooling** context (not directly on end-user data), so:
  - Throughput requirements are moderate.
  - User oversight is expected before applying change-sets.
- API keys for OpenAI and/or Claude are available and the network environment allows outbound calls.
- The number of forms and fields is large enough that you must **not** stream entire tables into the LLM, but not so large that a few targeted lookups per request become a bottleneck.
- The agent only plans; actually executing the change-sets against the DB is intentionally left to other tooling to avoid accidental destructive changes.

## Tech stack

- **Backend**:
  - Python 3.11+
  - FastAPI for HTTP routing and JSON APIs
  - `aiosqlite` for async SQLite access
  - Pydantic + `pydantic-settings` for configuration and schema validation
  - OpenAI and Anthropic Python SDKs for LLM calls
  - Pytest for tests
- **Frontend**:
  - React 18 with TypeScript
  - Vite for bundling and dev server
  - Minimal hand-crafted CSS for a clean, modern UI

## Handling large databases and context size

- **No full-table dumps to LLM**:
  - The LLM never sees raw table contents; it only receives:
    - A compact **schema summary** (table and column names/types).
    - The structured `IntentPlan` and final JSON change-set for explanations.
  - This keeps prompt size bounded even if the DB grows.
- **Targeted lookups, not scans**:
  - For each request, the backend performs a small number of focused queries:
    - Resolve a form by title/slug.
    - Resolve fields on that form by label/code.
    - Fetch options for a specific field’s option set.
    - Fetch logic rules/conditions/actions for a specific form.
  - No code path loads entire tables into memory or into the context window.
- **Schema caching**:
  - Table/column metadata is loaded once at startup and reused:
    - For building schema summaries passed to the LLM.
    - For computing required columns in tests.
  - This avoids repeated `PRAGMA` calls and stabilizes the schema view.

## Metrics, success criteria, and guardrails

- **Structural correctness (hard requirement)**:
  - Change-sets must match the required JSON shape:
    - Top-level keys are table names.
    - Each table has `insert`/`update`/`delete` arrays.
  - Invariants enforced by tests:
    - All `insert` rows have required columns (NOT NULL, no default, non-PK).
    - All `update`/`delete` rows reference existing IDs.
- **Scenario-level correctness**:
  - For representative scenarios (the three canonical examples and more):
    - The right tables are touched (e.g., `option_items` and `form_fields` for option updates).
    - The right rows are updated (based on labels/codes, not guesses).
    - The resulting behavior matches the user’s description (e.g., “Student requires university name”).
- **Ambiguity and clarification metrics**:
  - How often does the agent:
    - Return a clarification instead of a plan?
    - Surface ambiguous matches (multiple forms/fields) clearly?
  - The goal is **fewer incorrect plans** and **more safe clarifications** when information is missing.
- **Cost and latency**:
  - Two-stage reasoning and explanations incur extra LLM calls; you can track:
    - Average tokens per request.
    - Time to first response for `/api/query` and `/api/explain`.
- **Guardrails recap**:
  - Prefer `update` over `insert` when modifying existing entities.
  - Use `is_active=0` instead of hard deletes for options unless explicitly requested.
  - Enforce a configurable `MAX_CHANGED_ROWS` ceiling.
  - Never guess IDs; all IDs come from DB lookups.
  - Treat explanations as advisory; the authoritative definition of changes is always the JSON change-set.

## Detailed end-to-end flow (example: update a dropdown)

1. **User input**:
   - In the Agent tab, user types:
     - “Update the dropdown options for the destination field in the travel request form: add Paris, change Tokyo to Milan.”
2. **Request to backend**:
   - Frontend sends `POST /api/query` with:
     - `query`: the raw text.
     - `provider`: `"openai"` or `"anthropic"`.
     - `history`: any prior clarification Q&A for this request.
3. **Planning (stage 1)**:
   - Agent normalizes the text and retrieves the cached schema summary.
   - It builds a structured prompt (system + user) describing:
     - The form management domain.
     - The `IntentPlan` JSON schema.
     - The database schema (tables + columns).
     - The existing forms and fields summary (crucial: shows exact form titles, slugs, field codes, labels, and types).
     - Three few-shot examples demonstrating correct intent structure.
     - Explicit guidelines about matching field names exactly to what exists.
   - It calls the LLM in JSON mode to get an initial `IntentPlan`.
4. **Validation and repair**:
   - Pydantic validates the initial plan.
   - If there are schema mismatches, the agent:
     - Either repairs simple issues (e.g., missing lists), or
     - Marks `needs_clarification=true` with a generic question.
5. **Planning (stage 2 critique)**:
   - The agent sends the initial plan and original request to a second LLM call.
   - The model can:
     - Accept the plan as-is.
     - Return a refined `IntentPlan`.
     - Implicitly suggest that the plan is unsafe or unclear (in which case the agent turns this into a clarification).
6. **Resolution against SQLite**:
   - Given the final `IntentPlan`, the resolver:
     - Resolves the `travel-complex` form by slug/title (with fuzzy matching if needed).
     - Resolves the `destinations` field by code/label on that form (tries exact match first, then fuzzy match).
     - If field resolution fails, provides a clarification question with all available fields on that form.
     - Fetches the option set and existing options for the field.
     - Computes which options to insert/rename/deactivate.
   - It constructs the final `change_set`:
     - `option_items.insert`: a new `Paris` row with a placeholder ID and next position.
     - `option_items.update`: a row that changes `Tokyo` → `Milan`.
7. **Before snapshot for diff**:
   - The agent collects the IDs of all affected forms from the change-set.
   - For each form ID, it builds a `before_snapshot` using `get_form_structure`:
     - Form metadata, pages, fields, options, logic rules/conditions/actions.
8. **Response to frontend**:
   - If there was ambiguity (multiple matching forms/fields), the agent returns:
     - `{"type": "clarification", "question": "...", "plan": ...}`.
   - Otherwise it returns:
     - `{"type": "change_set", "plan": ..., "change_set": ..., "before_snapshot": ...}`.
9. **Frontend rendering**:
   - The Agent tab shows:
     - The raw change-set JSON (with expand to fullscreen option).
     - An **enhanced visual preview** with side-by-side before/after comparison showing:
       - All fields with proper type rendering (text, dropdown, checkbox, date, etc.)
       - Visual indicators for new/modified/deleted fields and options
       - Property change details (e.g., "label: Old → New")
       - Option changes displayed as colored pills (new options highlighted, renamed options show "was: old_value")
       - Logic rules with human-readable conditions and actions
       - Change summary badges showing counts of additions/modifications
     - An **Explain plan** button that calls `/api/explain/stream` to stream a friendly explanation.
10. **Testing and validation**:
    - Resolver tests confirm that for this query, the change-set:
      - Inserts a `Paris` option.
      - Renames the `Tokyo` option to `Milan`.
    - Invariant tests confirm:
      - IDs used in `update` operations exist.
      - All required columns for inserts are present.

This pattern generalizes to other scenarios (adding fields, creating new forms, adding conditional logic) with the same two-stage reasoning, DB-grounded resolution, diffing, and explanations. 