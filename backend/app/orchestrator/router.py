# app/orchestrator/router.py
import json
import time
from typing import Any, AsyncGenerator, Literal
import uuid
from fastapi import APIRouter, Depends, Header, HTTPException, Request, status
from fastapi.responses import StreamingResponse
from pydantic import BaseModel, Field
from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession
from ..auth.deps import SessionContext, get_session
from ..db import get_db, set_rls_system
from ..ratelimit import rate_limit
from ..settings import settings
from ..tools.registry import RunContext
from .graph import build_graph
from .guards import scrub_pii

router = APIRouter()
_compiled_graph = None


def get_orchestrator_graph():
    global _compiled_graph
    if _compiled_graph is None:
        _compiled_graph = build_graph()
    return _compiled_graph


class ChatRequest(BaseModel):
    message: str = Field(..., min_length=1, max_length=2000)
    conversation_id: uuid.UUID
    input_mode: Literal["text", "voice"] = "text"


async def persist_run(
    run_ctx: RunContext,
    query: str,
    state: dict[str, Any],
    latency_ms: int,
) -> None:
    try:
        await set_rls_system(run_ctx.db)
        plan = state.get("plan")
        reply = state.get("reply", {})
        final_status = "COMPLETED"
        if state.get("guard", {}).get("route") in ("ESCALATE", "REFUSE", "CLARIFY"):
            final_status = state["guard"]["route"]

        await run_ctx.db.execute(
            text(
                """
                INSERT INTO agent_runs (id, user_id, trace_id, query_redacted, plan, final_status, prompt_versions, model, tokens_in, tokens_out, latency_ms)
                VALUES (:id, :uid, :tid, :q, CAST(:plan AS jsonb), :status, CAST(:pv AS jsonb), :model, :tin, :tout, :lat)
                ON CONFLICT (id) DO NOTHING
                """
            ),
            {
                "id": run_ctx.run_id,
                "uid": uuid.UUID(run_ctx.session.user_id),
                "tid": run_ctx.trace_id,
                "q": scrub_pii(query),
                "plan": json.dumps(plan, default=str) if plan else None,
                "status": final_status,
                "pv": json.dumps({"SUPERVISOR": "1.0.0"}),
                "model": settings.llm_model,
                "tin": run_ctx.tokens_used,
                "tout": 0,
                "lat": latency_ms,
            },
        )
        await run_ctx.db.commit()
    except Exception:
        pass


@router.post("/agent/chat")
async def chat_endpoint(
    req: ChatRequest,
    request: Request,
    s: SessionContext = Depends(get_session),
    db: AsyncSession = Depends(get_db),
    _=Depends(rate_limit("chat", 20, 60)),
):
    accept_header = request.headers.get("accept", "")
    is_stream = "text/event-stream" in accept_header

    run_ctx = RunContext(
        session=s,
        db=db,
        run_id=uuid.uuid4(),
        trace_id=str(uuid.uuid4()),
    )
    graph = get_orchestrator_graph()

    start_t = time.monotonic()

    if is_stream:
        async def event_generator() -> AsyncGenerator[str, None]:
            init_state = {
                "ctx": run_ctx,
                "query": req.message,
                "outputs": {},
                "bundle": None,
                "reply": {},
            }
            yield f"event: start\ndata: {json.dumps({'status': 'processing'})}\n\n"

            final_state = await graph.ainvoke(
                init_state,
                config={"configurable": {"thread_id": f"{s.user_id}:{req.conversation_id}"}},
            )
            lat = int((time.monotonic() - start_t) * 1000)
            await persist_run(run_ctx, req.message, final_state, lat)

            if final_state.get("guard"):
                yield f"event: guard\ndata: {json.dumps(final_state['guard'])}\n\n"
            if final_state.get("plan"):
                yield f"event: plan\ndata: {json.dumps(final_state['plan'])}\n\n"
            if final_state.get("bundle"):
                yield f"event: bundle\ndata: {json.dumps(final_state['bundle'])}\n\n"

            reply_payload = {
                **final_state.get("reply", {}),
                "bundle": final_state.get("bundle"),
            }
            yield f"event: reply\ndata: {json.dumps(reply_payload)}\n\n"
            yield "event: done\ndata: [DONE]\n\n"

        return StreamingResponse(event_generator(), media_type="text/event-stream")

    # Standard JSON response
    final_state = await graph.ainvoke(
        {
            "ctx": run_ctx,
            "query": req.message,
            "outputs": {},
            "bundle": None,
            "reply": {},
        },
        config={"configurable": {"thread_id": f"{s.user_id}:{req.conversation_id}"}},
    )
    lat = int((time.monotonic() - start_t) * 1000)
    await persist_run(run_ctx, req.message, final_state, lat)

    return {
        **final_state.get("reply", {}),
        "bundle": final_state.get("bundle"),
    }
