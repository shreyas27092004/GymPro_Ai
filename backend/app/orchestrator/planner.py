# app/orchestrator/planner.py
from collections import defaultdict, deque
import json
import re
from typing import Any
from .. import llm as llm_module
from ..prompts import load_prompt
from ..settings import settings

ROLE_AGENTS = {
    "USER": {
        "SCHEDULE",
        "MEMBERSHIP",
        "FITNESS",
        "WELLNESS",
        "NUTRITION",
        "TRAINER_INFO",
        "SUPPORT",
        "COMMS",
    },
    "TRAINER": {"TRAINER_OPS"},
    "ADMIN": {"ADMIN_INSIGHTS"},
}

ROLE_AGENT_DEFAULT = {"TRAINER": "TRAINER_OPS", "ADMIN": "ADMIN_INSIGHTS"}

RULES = {
    "SCHEDULE": re.compile(
        r"\b(book|cancel|waitlist|reschedule|my\s+(bookings|classes)|class(es)?\s+(at|on|tomorrow|today))\b",
        re.I,
    ),
    "MEMBERSHIP": re.compile(
        r"\b(membership|renew(al)?|upgrade|downgrade|(gold|silver|platinum)\s+plan|free\s+trial|trial)\b",
        re.I,
    ),
    "NUTRITION": re.compile(
        r"\b(diet|meal\s+plan|macros?|calories?\s+target|protein\s+intake)\b",
        re.I,
    ),
    "WELLNESS": re.compile(
        r"\b(soreness|recovery|stretching|sleep|hydrate|hydration|mobility)\b",
        re.I,
    ),
}

MULTI_INTENT_HINT = re.compile(
    r"\b(and\s+also|and\s+then|and\s+send|and\s+report|as\s+well\s+as|,(\s+\w+)+,\s+and)\b",
    re.I,
)

SAFETY_TERMS = re.compile(
    r"\b(pain|injury|hurt|ache|sprain|doctor|swollen|bleed)\b",
    re.I,
)

WHITELISTED_HANDOFF_FIELDS = {
    "safety_constraints",
    "preferred_activities",
    "projected_state",
    "step_refs",
    "selected_class",
}


def single_agent_plan(agent: str) -> dict[str, Any]:
    return {
        "intents": [
            {
                "id": "i1",
                "name": f"HANDLE_{agent}",
                "agent": agent,
                "depends_on": [],
                "confidence": 1.0,
            }
        ],
        "waves": [["i1"]],
        "handoffs": [],
        "needs_clarification": None,
        "blocked_intents": [],
        "route": "CONTINUE",
    }


def rules_fast_path(q: str, role: str) -> dict[str, Any] | None:
    if role in ROLE_AGENT_DEFAULT:
        return single_agent_plan(ROLE_AGENT_DEFAULT[role])

    hits = [a for a, rx in RULES.items() if rx.search(q)]
    if len(hits) == 1 and not MULTI_INTENT_HINT.search(q) and not SAFETY_TERMS.search(q):
        return single_agent_plan(hits[0])
    return None


async def llm_plan(q: str, ctx: Any) -> dict[str, Any]:
    prompt = load_prompt("SUPERVISOR_PLANNER", ctx)
    session_json = ctx.session.llm_json() if hasattr(ctx.session, "llm_json") else "{}"
    messages = [
        {"role": "system", "content": prompt.text},
        {"role": "user", "content": f"<session_context>{session_json}</session_context>\n<user_message>{q}</user_message>"},
    ]
    resp = await llm_module.llm.chat.completions.create(
        model=settings.llm_model,
        messages=messages,
        temperature=0,
        response_format={"type": "json_object"},
    )
    content = resp.choices[0].message.content or "{}"
    try:
        return json.loads(content)
    except Exception:
        return single_agent_plan("SCHEDULE")


def validate_plan(plan: dict[str, Any], role: str = "USER") -> dict[str, Any]:
    allowed_agents = ROLE_AGENTS.get(role, ROLE_AGENTS["USER"])
    raw_intents = plan.get("intents", [])

    valid_intents: list[dict[str, Any]] = []
    blocked_intents = list(plan.get("blocked_intents", []))

    # 1. Role allowlist check
    for intent in raw_intents:
        agent_name = (intent.get("agent") or "").upper()
        if agent_name in allowed_agents:
            intent["agent"] = agent_name
            valid_intents.append(intent)
        else:
            blocked_intents.append(f"{intent.get('name', 'INTENT')}:{agent_name}")

    if not valid_intents:
        return {
            "intents": [],
            "waves": [],
            "handoffs": [],
            "needs_clarification": "No actions available for your role.",
            "blocked_intents": blocked_intents,
            "route": "CLARIFY",
        }

    # 2. Enforce max 6 agents by confidence
    if len(valid_intents) > 6:
        valid_intents.sort(key=lambda x: x.get("confidence", 0.0), reverse=True)
        dropped = valid_intents[6:]
        valid_intents = valid_intents[:6]
        for d in dropped:
            blocked_intents.append(f"{d.get('name')}:OVER_LIMIT")

    valid_ids = {i["id"] for i in valid_intents}

    # Clean depends_on
    for i in valid_intents:
        i["depends_on"] = [d for d in i.get("depends_on", []) if d in valid_ids and d != i["id"]]

    # 3. Cycle check & Topological sorting (Kahn's algorithm)
    in_degree: dict[str, int] = {i["id"]: 0 for i in valid_intents}
    adj: dict[str, list[str]] = defaultdict(list)

    for i in valid_intents:
        for dep in i["depends_on"]:
            adj[dep].append(i["id"])
            in_degree[i["id"]] += 1

    queue = deque([node for node, deg in in_degree.items() if deg == 0])
    ordered_ids: list[str] = []
    wave_map: dict[str, int] = {}
    for node in queue:
        wave_map[node] = 0

    while queue:
        curr = queue.popleft()
        ordered_ids.append(curr)
        curr_wave = wave_map[curr]

        for neighbor in adj[curr]:
            in_degree[neighbor] -= 1
            wave_map[neighbor] = max(wave_map.get(neighbor, 0), curr_wave + 1)
            if in_degree[neighbor] == 0:
                queue.append(neighbor)

    # If cycle detected (not all nodes ordered), break back edges
    if len(ordered_ids) < len(valid_intents):
        remaining = [i["id"] for i in valid_intents if i["id"] not in ordered_ids]
        for node in remaining:
            wave_map[node] = 0
            ordered_ids.append(node)
        # Clear cyclic dependencies
        for i in valid_intents:
            if i["id"] in remaining:
                i["depends_on"] = []

    # Reorder valid_intents in topological order
    by_id = {i["id"]: i for i in valid_intents}
    sorted_intents = [by_id[nid] for nid in ordered_ids]

    # Group into waves
    max_wave = max(wave_map.values()) if wave_map else 0
    waves: list[list[str]] = [[] for _ in range(max_wave + 1)]
    for nid, w in wave_map.items():
        waves[w].append(nid)

    # Filter out empty waves
    waves = [w for w in waves if w]

    # Cap waves at 4: collapse any waves >= 4 into wave 3 if needed
    if len(waves) > 4:
        collapsed = []
        for w in waves[3:]:
            collapsed.extend(w)
        waves = waves[:3] + [collapsed]

    # 4. Filter handoffs to whitelisted fields
    clean_handoffs = []
    for h in plan.get("handoffs", []):
        fields = [f for f in h.get("fields", []) if f in WHITELISTED_HANDOFF_FIELDS]
        if fields and h.get("from") in valid_ids:
            clean_targets = [t for t in h.get("to", []) if t in valid_ids]
            if clean_targets:
                clean_handoffs.append({
                    "from": h["from"],
                    "to": clean_targets,
                    "fields": fields,
                })

    return {
        "intents": sorted_intents,
        "waves": waves,
        "handoffs": clean_handoffs,
        "needs_clarification": plan.get("needs_clarification"),
        "blocked_intents": blocked_intents,
        "route": plan.get("route", "CONTINUE"),
    }
