# app/agents/runner.py
import asyncio
import json
import time
from typing import Any
from pydantic import ValidationError
from .. import llm as llm_module
from ..prompts import load_prompt
from ..settings import settings
from ..tools.registry import dispatch, openai_tool_specs, RunContext
from .schemas import Confirmation, DATA_MODELS, Envelope, Safety, Status


def wrap(tag: str, payload: str) -> str:
    """Untrusted data is fenced and labeled; angle brackets neutralized to stop tag spoofing."""
    return f"<{tag}>\n{payload.replace('<', '&lt;')}\n</{tag}>"


def safe_fallback(agent: str) -> Envelope:
    """Safe fallback response returned on unrecoverable tool errors or budget exhaustion."""
    return Envelope(
        agent=agent.upper(),
        schema_version="1.0",
        status="ERROR",
        data={},
        projected_effects=None,
        user_message="I ran into an issue while processing your request. Please try again or ask for assistance.",
        missing_fields=[],
        confirmation=Confirmation(action_id=None, summary=None, expires_at=None),
        safety=Safety(flags=[], escalation=None),
        citations=[],
        confidence=0.0,
    )


async def run_agent(
    agent: str,
    ctx: RunContext,
    user_message: str,
    handoff: dict[str, Any] | None = None,
) -> Envelope:
    """
    Executes an agent run through prompt assembly, tool execution loop,
    validation, 1-attempt retry on failure, token metering, and safe fallback.
    """
    prompt = load_prompt(agent, ctx)
    ctx.set_handoff(agent, handoff or {})

    # Check if upstream step failed
    if handoff and handoff.get("upstream_failed"):
        return Envelope(
            agent=agent.upper(),
            schema_version="1.0",
            status="OK",
            data={},
            projected_effects=None,
            user_message="This step was skipped because an earlier dependent action failed.",
            missing_fields=[],
            confirmation=Confirmation(action_id=None, summary=None, expires_at=None),
            safety=Safety(flags=[], escalation=None),
            citations=[],
            confidence=1.0,
        )

    session_llm = ctx.session.llm_json() if hasattr(ctx.session, "llm_json") else "{}"
    messages: list[dict[str, Any]] = [
        {"role": "system", "content": prompt.text},
        {
            "role": "user",
            "content": (
                f"<session_context>{session_llm}</session_context>\n"
                + wrap("agent_handoff", json.dumps(handoff or {}))
                + "\n"
                + wrap("user_message", user_message)
            ),
        },
    ]

    tools = openai_tool_specs(ctx.allowed_tools_for(agent))
    deadline = time.monotonic() + settings.agent_timeout_s

    try:
        for _ in range(settings.agent_max_tool_steps):
            remaining = max(1.0, deadline - time.monotonic())
            kwargs: dict[str, Any] = {
                "model": settings.llm_model,
                "messages": messages,
                "temperature": 0.1,
                "response_format": {"type": "json_object"},
            }
            if tools:
                kwargs["tools"] = tools

            resp = await asyncio.wait_for(
                llm_module.llm.chat.completions.create(**kwargs),
                timeout=remaining,
            )
            ctx.meter(resp.usage)
            msg = resp.choices[0].message

            if getattr(msg, "tool_calls", None):
                # Append assistant tool call request
                assistant_dict: dict[str, Any] = {"role": "assistant"}
                if msg.content:
                    assistant_dict["content"] = msg.content
                assistant_dict["tool_calls"] = [
                    {
                        "id": tc.id,
                        "type": "function",
                        "function": {
                            "name": tc.function.name,
                            "arguments": tc.function.arguments,
                        },
                    }
                    for tc in msg.tool_calls
                ]
                messages.append(assistant_dict)

                # Execute tools sequentially
                results = []
                for tc in msg.tool_calls:
                    fn_name = tc.function.name
                    try:
                        args = json.loads(tc.function.arguments) if tc.function.arguments else {}
                    except Exception:
                        args = {}
                    res = await dispatch(fn_name, args, ctx)
                    results.append(res)

                for tc, r in zip(msg.tool_calls, results):
                    messages.append(
                        {
                            "role": "tool",
                            "tool_call_id": tc.id,
                            "content": wrap("tool_result", json.dumps(r, default=str)),
                        }
                    )
                continue

            # Final answer reached: validate with 1 retry on failure
            for attempt in (1, 2):
                try:
                    content_str = msg.content or "{}"
                    env = Envelope.model_validate_json(content_str)
                    if env.agent in DATA_MODELS:
                        DATA_MODELS[env.agent].model_validate(env.data)
                    ctx.post_validate(agent, env)
                    return env
                except (ValidationError, ValueError) as e:
                    if attempt == 2:
                        break
                    messages.extend([
                        {"role": "assistant", "content": msg.content or "{}"},
                        {
                            "role": "user",
                            "content": f"Your JSON failed validation: {str(e)[:600]}. Return corrected JSON only.",
                        },
                    ])
                    remaining = max(1.0, deadline - time.monotonic())
                    resp = await asyncio.wait_for(
                        llm_module.llm.chat.completions.create(
                            model=settings.llm_model,
                            messages=messages,
                            temperature=0,
                            response_format={"type": "json_object"},
                        ),
                        timeout=remaining,
                    )
                    ctx.meter(resp.usage)
                    msg = resp.choices[0].message
            break
    except Exception:
        # On timeout, budget error, or unexpected exception -> safe fallback
        return safe_fallback(agent)

    return safe_fallback(agent)
