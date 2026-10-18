# app/orchestrator/synthesizer.py
import json
from typing import Any
from .. import llm as llm_module
from ..prompts import load_prompt
from ..settings import settings
from ..tools.registry import RunContext


async def synth(
    outputs: dict[str, Any],
    bundle: dict[str, Any] | None,
    ctx: RunContext,
) -> dict[str, Any]:
    # 1. Safety precedence: ESCALATE > REFUSED > CONSTRAINTS
    for e in outputs.values():
        if getattr(e, "status", None) == "ESCALATE":
            msg = e.user_message
            if "I'll be here when you're ready" not in msg:
                msg += " I'll be here when you're ready."
            return {
                "reply": msg,
                "quick_actions": [],
                "conflicts_resolved": [],
                "flags": getattr(getattr(e, "safety", None), "flags", []),
            }

    # If all outputs are REFUSED
    if outputs and all(getattr(e, "status", None) == "REFUSED" for e in outputs.values()):
        refusals = [e.user_message for e in outputs.values() if getattr(e, "user_message", None)]
        first_refusal = refusals[0] if refusals else "I cannot fulfill this request based on safety policy."
        all_flags = []
        for e in outputs.values():
            all_flags.extend(getattr(getattr(e, "safety", None), "flags", []))
        return {
            "reply": first_refusal,
            "quick_actions": [],
            "conflicts_resolved": [],
            "flags": sorted(set(all_flags)),
        }

    # 2. Call LLM Synthesizer
    try:
        prompt = load_prompt("SYNTHESIZER", ctx)
        envelopes_data = [
            e.model_dump() if hasattr(e, "model_dump") else e
            for e in outputs.values()
        ]
        input_payload = {
            "envelopes": envelopes_data,
            "bundle": bundle,
            "session_context": ctx.session.llm_json() if hasattr(ctx.session, "llm_json") else {},
        }
        messages = [
            {"role": "system", "content": prompt.text},
            {"role": "user", "content": json.dumps(input_payload, default=str)},
        ]
        resp = await llm_module.llm.chat.completions.create(
            model=settings.llm_model,
            messages=messages,
            temperature=0.1,
            response_format={"type": "json_object"},
        )
        content = resp.choices[0].message.content or "{}"
        result = json.loads(content)
        # Ensure keys
        if "reply" in result:
            # Word limit check (max 120 words)
            words = result["reply"].split()
            if len(words) > 120:
                result["reply"] = " ".join(words[:120])
            return result
    except Exception:
        pass

    # 3. Deterministic fallback if LLM synthesis fails
    quick_actions = []
    if bundle and bundle.get("bundle_id"):
        step_count = len(bundle.get("steps", []))
        quick_actions.append({
            "type": "CONFIRM_BUNDLE",
            "bundle_id": bundle["bundle_id"],
            "label": f"Confirm all {step_count} steps" if step_count > 1 else "Confirm step",
        })
    elif bundle and bundle.get("action_id"):
        quick_actions.append({
            "type": "CONFIRM",
            "action_id": bundle["action_id"],
            "label": "Confirm action",
        })

    # Combine user messages from envelopes
    msgs = []
    all_flags = []
    for e in outputs.values():
        if getattr(e, "user_message", None):
            msgs.append(e.user_message)
        if getattr(e, "safety", None) and e.safety.flags:
            all_flags.extend(e.safety.flags)

    combined_reply = " ".join(msgs)
    if bundle and bundle.get("questions"):
        for q in bundle["questions"]:
            q_text = q.get("text", "")
            if q_text and q_text not in combined_reply:
                combined_reply += f" {q_text}"

    words = combined_reply.split()
    if len(words) > 120:
        combined_reply = " ".join(words[:120])

    return {
        "reply": combined_reply,
        "quick_actions": quick_actions,
        "conflicts_resolved": [],
        "flags": sorted(set(all_flags)),
    }
