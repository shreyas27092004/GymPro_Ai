# app/orchestrator/graph.py
from typing import Annotated, Any, TypedDict
from langgraph.graph import END, START, StateGraph
from ..agents.runner import run_agent
from ..agents.schemas import Confirmation, Envelope, Safety
from .bundle import build_bundle
from .guards import (
    clarify_node,
    escalate_node,
    input_guard as guard_input,
    output_guard as guard_output,
    refuse_node,
    remove_blocked_spans,
)
from .planner import llm_plan, rules_fast_path, validate_plan
from .synthesizer import synth


def merge(a: dict, b: dict) -> dict:
    return {**a, **b}


class State(TypedDict):
    ctx: Any
    query: str
    guard: dict[str, Any]
    plan: dict[str, Any]
    outputs: Annotated[dict[str, Any], merge]
    bundle: dict[str, Any] | None
    reply: dict[str, Any]


def skipped_envelope(intent: dict[str, Any]) -> Envelope:
    return Envelope(
        agent=intent.get("agent", "UNKNOWN"),
        schema_version="1.0",
        status="OK",
        data={"skipped": True, "reason": "DEPENDENCY_FAILED"},
        projected_effects=None,
        user_message="This step was skipped because an earlier dependent action failed.",
        missing_fields=[],
        confirmation=Confirmation(),
        safety=Safety(),
        citations=[],
        confidence=1.0,
    )


def build_handoff(
    plan: dict[str, Any],
    outputs: dict[str, Any],
    current_intent: dict[str, Any],
) -> dict[str, Any]:
    handoff: dict[str, Any] = {}
    current_id = current_intent["id"]

    # 1. Step numbers for dependencies
    step_no_map: dict[str, int] = {}
    step_counter = 1
    for i in plan.get("intents", []):
        env = outputs.get(i["id"])
        if env and getattr(env, "confirmation", None) and env.confirmation.action_id:
            step_no_map[i["id"]] = step_counter
            step_counter += 1

    deps = current_intent.get("depends_on", [])
    if deps:
        handoff["depends_on_steps"] = [
            step_no_map[d] for d in deps if d in step_no_map
        ]

    # 2. Extract whitelisted fields from declared handoffs
    for h in plan.get("handoffs", []):
        from_id = h.get("from")
        to_ids = h.get("to", [])
        if current_id in to_ids and from_id in outputs:
            src_env = outputs[from_id]
            src_data = (
                src_env.data
                if isinstance(src_env.data, dict)
                else src_env.data.model_dump()
                if hasattr(src_env.data, "model_dump")
                else {}
            )
            for f in h.get("fields", []):
                if f == "projected_state" and getattr(src_env, "projected_effects", None):
                    handoff["projected_state"] = src_env.projected_effects
                elif f == "safety_constraints" and "safety_constraints" in src_data:
                    handoff["safety_constraints"] = src_data["safety_constraints"]
                elif f == "preferred_activities" and "preferred_activities" in src_data:
                    handoff["preferred_activities"] = src_data["preferred_activities"]
                elif f == "selected_class" and "selected_class_id" in src_data:
                    handoff["selected_class"] = src_data["selected_class_id"]
                elif f == "step_refs":
                    if from_id in step_no_map:
                        handoff["step_refs"] = {
                            "booking": {"from_step": step_no_map[from_id]}
                        }

    return handoff


async def input_guard_node(st: State) -> dict[str, Any]:
    guard_res = await guard_input(st["query"], st["ctx"].session)
    return {"guard": guard_res}


def after_guard(st: State) -> str:
    route = st["guard"].get("route", "CONTINUE")
    if route == "CONTINUE":
        return "planner"
    elif route == "ESCALATE":
        return "escalate"
    elif route == "REFUSE":
        return "refuse"
    else:
        return "clarify"


async def planner_node(st: State) -> dict[str, Any]:
    q = remove_blocked_spans(st["query"], st["guard"].get("blocked_spans", []))
    role = getattr(st["ctx"].session, "role", "USER")
    plan = rules_fast_path(q, role)
    if not plan:
        plan = await llm_plan(q, st["ctx"])
    plan = validate_plan(plan, role=role)
    return {"plan": plan}


async def run_waves_node(st: State) -> dict[str, Any]:
    ctx = st["ctx"]
    plan = st["plan"]
    outputs: dict[str, Any] = {}
    by_id = {i["id"]: i for i in plan.get("intents", [])}

    for wave in plan.get("waves", []):
        for iid in wave:
            if iid not in by_id:
                continue
            intent = by_id[iid]
            deps = intent.get("depends_on", [])

            # Check if any dependency failed or was not confirmed
            if any(
                outputs.get(d) and getattr(outputs[d], "status", None) not in ("OK", "NEEDS_CONFIRMATION")
                for d in deps
            ):
                outputs[iid] = skipped_envelope(intent)
                continue

            handoff = build_handoff(plan, outputs, intent)
            agent_output = await run_agent(intent["agent"], ctx, st["query"], handoff)
            outputs[iid] = agent_output

            if getattr(agent_output, "status", None) == "ESCALATE":
                # Short-circuit immediately on acute safety escalation
                return {"outputs": outputs}

    return {"outputs": outputs}


async def make_bundle_node(st: State) -> dict[str, Any]:
    bundle_card = await build_bundle(
        st["ctx"].db, st["ctx"], st["plan"], st["outputs"]
    )
    return {"bundle": bundle_card}


async def synthesize_node(st: State) -> dict[str, Any]:
    reply_dict = await synth(st["outputs"], st["bundle"], st["ctx"])
    return {"reply": reply_dict}


async def output_guard_node(st: State) -> dict[str, Any]:
    guarded_reply = guard_output(
        st["reply"], st["outputs"], st["bundle"], st["ctx"].session
    )
    return {"reply": guarded_reply}


def build_graph(checkpointer: Any = None):
    g = StateGraph(State)

    g.add_node("input_guard", input_guard_node)
    g.add_node("planner", planner_node)
    g.add_node("run_waves", run_waves_node)
    g.add_node("make_bundle", make_bundle_node)
    g.add_node("synthesize", synthesize_node)
    g.add_node("output_guard", output_guard_node)
    g.add_node("escalate", escalate_node)
    g.add_node("refuse", refuse_node)
    g.add_node("clarify", clarify_node)

    g.add_edge(START, "input_guard")
    g.add_conditional_edges("input_guard", after_guard)

    g.add_edge("planner", "run_waves")
    g.add_edge("run_waves", "make_bundle")
    g.add_edge("make_bundle", "synthesize")
    g.add_edge("synthesize", "output_guard")
    g.add_edge("output_guard", END)

    for n in ("escalate", "refuse", "clarify"):
        g.add_edge(n, END)

    return g.compile(checkpointer=checkpointer)
