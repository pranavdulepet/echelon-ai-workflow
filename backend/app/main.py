from fastapi import FastAPI, HTTPException
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import StreamingResponse
import json

from .agent import FormAgent
from .api_models import (
    ChangeSetResponse,
    ClarificationResponse,
    ExplainRequest,
    ExplainResponse,
    FormStructureResponse,
    FormSummary,
    QueryRequest,
)
from .config import Settings, get_settings
from .llm_client import LlmClient
from .db import Database


def create_app() -> FastAPI:
    settings: Settings = get_settings()
    app = FastAPI(title="Form Agent API", version="0.1.0")

    app.add_middleware(
        CORSMiddleware,
        allow_origins=["*"],
        allow_credentials=True,
        allow_methods=["*"],
        allow_headers=["*"],
    )

    db = Database()
    llm = LlmClient()
    agent = FormAgent(db=db, llm=llm)

    @app.post("/api/query", response_model=ChangeSetResponse | ClarificationResponse)
    async def handle_query(body: QueryRequest):
        settings.llm_provider = body.provider or settings.llm_provider
        try:
            result = await agent.plan_and_resolve(
                query=body.query,
                history=[item.model_dump() for item in body.history],
            )
        except ValueError as exc:
            raise HTTPException(status_code=400, detail=str(exc)) from exc
        except Exception as exc:  # noqa: BLE001
            import traceback
            error_details = f"Failed to plan changes: {type(exc).__name__}: {str(exc)}"
            print(f"Error in handle_query: {error_details}")
            traceback.print_exc()
            raise HTTPException(status_code=502, detail=error_details) from exc

        if result["type"] == "clarification":
            return ClarificationResponse(
                type="clarification",
                question=result["question"],
                plan=result["plan"],
                reason=result.get("reason"),
                form_candidates=result.get("form_candidates"),
                field_candidates=result.get("field_candidates"),
            )
        return ChangeSetResponse(
            type="change_set",
            plan=result["plan"],
            change_set=result["change_set"],
            before_snapshot=result.get("before_snapshot"),
        )

    @app.get("/api/forms", response_model=list[FormSummary])
    async def list_forms():
        rows = await db.fetch_all(
            "SELECT id, slug, title, status FROM forms ORDER BY title"
        )
        return [FormSummary(**row) for row in rows]

    @app.get("/api/forms/{form_id}", response_model=FormStructureResponse)
    async def get_form_structure(form_id: str):
        structure = await db.get_form_structure(form_id)
        if not structure:
            raise HTTPException(status_code=404, detail="Form not found")
        return FormStructureResponse(**structure)

    @app.get("/health")
    async def health():
        return {"status": "ok"}

    @app.post("/api/explain", response_model=ExplainResponse)
    async def explain(body: ExplainRequest):
        settings.llm_provider = body.provider or settings.llm_provider
        try:
            explanation = agent.explain_change_set(
                query=body.query,
                plan=body.plan,
                change_set=body.change_set,
            )
        except Exception as exc:  # noqa: BLE001
            message = "Failed to generate explanation."
            raise HTTPException(status_code=502, detail=message) from exc
        return ExplainResponse(explanation=explanation)

    @app.post("/api/explain/stream")
    async def explain_stream(body: ExplainRequest):
        settings.llm_provider = body.provider or settings.llm_provider

        system_prompt = (
            "You explain planned edits to a form management database.\n"
            "Describe the impact in clear, concise language.\n"
            "Focus on forms, fields, options, and logic rules, not SQL or table names.\n"
            "Do not invent changes that are not present in the JSON.\n"
        )

        parts: list[str] = [
            "Original request:",
            body.query.strip(),
            "",
        ]
        if body.plan is not None:
            parts.append("Intent plan (JSON):")
            parts.append(json.dumps(body.plan, indent=2))
            parts.append("")
        parts.append("Planned change-set (JSON):")
        parts.append(json.dumps(body.change_set, indent=2))
        parts.append("")
        parts.append(
            "Explain these changes in clear, concise language, focusing on what the user will observe."
        )
        user_prompt = "\n".join(parts)

        async def streamer():
            try:
                async for chunk in llm.stream_text(system_prompt=system_prompt, user_prompt=user_prompt):
                    yield chunk
            except Exception:
                return

        return StreamingResponse(streamer(), media_type="text/plain")

    return app


app = create_app()


