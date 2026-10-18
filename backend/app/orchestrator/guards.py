# app/orchestrator/guards.py
import json
import re
from typing import Any
from ..auth.deps import SessionContext
from .. import llm as llm_module
from ..prompts import load_prompt
from ..settings import settings

INJECTION_HINTS = re.compile(
    r"(ignore\s+((all|any|previous|prior|your)\s+)*(instructions|rules)|"
    r"you\s+are\s+now|system\s+prompt|developer\s+message|prompt\s+template|"
    r"act\s+as\s+(admin|root)|reveal\s+your\s+(prompt|instructions)|disregard)",
    re.I,
)
EMERGENCY_TERMS = re.compile(
    r"(chest\s+(pain|tight)|can'?t\s+breathe|severe\s+breathless|passed\s+out|fainted|stroke|numb(ness)?\s+(in|on)\s+(face|arm))",
    re.I,
)
CRISIS_TERMS = re.compile(
    r"(kill\s+myself|suicid|end\s+my\s+life|self[- ]harm|hurt\s+myself)",
    re.I,
)
OTHER_EMAIL = re.compile(
    r"(send|email|mail|forward)[^.\n]{0,60}\b([a-zA-Z0-9_.+-]+@[a-zA-Z0-9-]+\.[a-zA-Z0-9-.]+)",
    re.I,
)
CROSS_USER_TERMS = re.compile(
    r"(book\s+(this\s+)?for\s+(another|someone|my\s+friend)|on\s+behalf\s+of|another\s+user('s)?|someone\s+else's)",
    re.I,
)
PRIVILEGE_TERMS = re.compile(
    r"(make\s+me\s+admin|grant\s+me\s+admin|approve\s+admin\s+request|give\s+me\s+trainer\s+role|become\s+admin|grant\s+me\s+lifetime)",
    re.I,
)
EATING_DISORDER_TERMS = re.compile(
    r"(burn\s+off\s+(food|calories|dinner)|purge|throw\s+up\s+after\s+eating|starve\s+myself|500\s+calories\s+a\s+day)",
    re.I,
)
OUT_OF_SCOPE_TERMS = re.compile(
    r"\b(write\s+python\s+code|debug\s+my\s+code|who\s+won\s+the\s+election|write\s+an\s+essay\s+on|crypto\s+price|bitcoin)\b",
    re.I,
)
COMPLETED_CLAIM = re.compile(
    r"\b(you\s+are\s+booked|i\s+have\s+booked\s+you|booking\s+is\s+confirmed|successfully\s+booked)\b",
    re.I,
)


def remove_blocked_spans(query: str, blocked_spans: list[str]) -> str:
    cleaned = query
    for span in blocked_spans:
        cleaned = cleaned.replace(span, " ")
    return re.sub(r"\s+", " ", cleaned).strip()


def scrub_pii(text_str: str) -> str:
    # Mask emails: keep first char, mask name, keep domain
    def _mask_email(match: re.Match) -> str:
        addr = match.group(0)
        parts = addr.split("@")
        if len(parts) == 2:
            name, dom = parts
            masked = (name[0] if name else "") + "***@" + dom
            return masked
        return addr

    # Replace emails
    scrubbed = re.sub(r"\b[A-Za-z0-9._%+-]+@[A-Za-z0-9.-]+\.[A-Z|a-z]{2,7}\b", _mask_email, text_str)
    # Mask Indian phone numbers (10 digits starting with 6-9)
    scrubbed = re.sub(r"\b[6-9]\d{9}\b", "**********", scrubbed)
    return scrubbed


def soften_completed_claims(text_str: str) -> str:
    return COMPLETED_CLAIM.sub("I have set up your booking request. Tap confirm below to finalize.", text_str)


async def input_guard(query: str, session: SessionContext) -> dict[str, Any]:
    if len(query) > 2000:
        return {
            "route": "CLARIFY",
            "labels": ["BENIGN"],
            "severity": "LOW",
            "blocked_spans": [],
            "reason": "query exceeds 2000 character limit",
        }

    # 1. Deterministic regex pass (works without LLM)
    if CRISIS_TERMS.search(query) or EMERGENCY_TERMS.search(query):
        is_crisis = bool(CRISIS_TERMS.search(query))
        label = "CRISIS" if is_crisis else "MEDICAL_EMERGENCY"
        return {
            "route": "ESCALATE",
            "labels": [label],
            "severity": "HIGH",
            "blocked_spans": [],
            "reason": "Emergency or crisis terms detected",
        }

    labels: list[str] = []
    blocked_spans: list[str] = []

    if INJECTION_HINTS.search(query):
        labels.append("PROMPT_INJECTION")

    if CROSS_USER_TERMS.search(query):
        labels.append("CROSS_USER_REQUEST")

    if PRIVILEGE_TERMS.search(query):
        labels.append("PRIVILEGE_ESCALATION")

    if EATING_DISORDER_TERMS.search(query):
        labels.append("EATING_DISORDER")

    if OUT_OF_SCOPE_TERMS.search(query):
        labels.append("OUT_OF_SCOPE")

    # Check other email
    m = OTHER_EMAIL.search(query)
    if m:
        target_email = m.group(2)
        user_email = getattr(session, "account_email", "") or ""
        if target_email.lower() != user_email.lower():
            labels.append("EMAIL_OTHER_ADDRESS")
            blocked_spans.append(m.group(0))

    # Check minor sensitive
    is_minor = getattr(session, "is_minor", False)
    age_years = getattr(session, "age_years", None)
    if is_minor or (age_years is not None and age_years < 18):
        if re.search(r"\b(diet|weight\s+loss|fat\s+loss|cut\s+calories|supplements?)\b", query, re.I):
            labels.append("MINOR_SENSITIVE")

    # 2. Classifier pass (via LLM / FakeLLM)
    try:
        classifier_res = await run_classifier("SUPERVISOR_GUARD", query, session)
        if classifier_res.get("labels"):
            labels = sorted(set(labels) | set(classifier_res["labels"]))
        if classifier_res.get("blocked_spans"):
            blocked_spans = list(set(blocked_spans) | set(classifier_res["blocked_spans"]))
    except Exception:
        # Fallback to regex pass only
        pass

    if not labels:
        labels = ["BENIGN"]

    labels_set = set(labels)
    # Apply routing rules from Section 7.14
    if {"MEDICAL_EMERGENCY", "CRISIS", "EATING_DISORDER"} & labels_set:
        route = "ESCALATE"
        severity = "HIGH"
    elif {"PRIVILEGE_ESCALATION", "CROSS_USER_REQUEST"} & labels_set:
        # If the entire message is about another user or privilege escalation, REFUSE
        # Otherwise, CONTINUE with blocked spans
        rem = remove_blocked_spans(query, blocked_spans)
        has_other_intent = bool(re.search(r"\b(book|upgrade|cancel|class|schedule|help|diet)\b", rem, re.I))
        if has_other_intent and blocked_spans:
            route = "CONTINUE"
            severity = "LOW"
        else:
            route = "REFUSE"
            severity = "HIGH"
    elif "OUT_OF_SCOPE" in labels_set:
        route = "REFUSE"
        severity = "LOW"
    elif "PROMPT_INJECTION" in labels_set:
        route = "REFUSE"
        severity = "HIGH"
    else:
        route = "CONTINUE"
        severity = "NONE"

    return {
        "route": route,
        "labels": labels,
        "severity": severity,
        "blocked_spans": blocked_spans,
        "reason": f"Classified with route {route}",
    }


async def run_classifier(agent_name: str, query: str, session: SessionContext) -> dict[str, Any]:
    prompt = load_prompt(agent_name)
    session_json = session.llm_json() if hasattr(session, "llm_json") else "{}"
    messages = [
        {"role": "system", "content": prompt.text},
        {"role": "user", "content": f"<session_context>{session_json}</session_context>\n<user_message>{query}</user_message>"},
    ]
    resp = await llm_module.llm.chat.completions.create(
        model=settings.llm_model,
        messages=messages,
        temperature=0,
        response_format={"type": "json_object"},
    )
    content = resp.choices[0].message.content or "{}"
    return json.loads(content)


def output_guard(reply: dict[str, Any], outputs: dict[str, Any], bundle: dict[str, Any] | None, session: SessionContext) -> dict[str, Any]:
    valid_actions = set()
    for e in outputs.values():
        if hasattr(e, "confirmation") and e.confirmation and e.confirmation.action_id:
            valid_actions.add(str(e.confirmation.action_id))

    valid_bundle = bundle.get("bundle_id") if bundle else None

    # 1. Quick actions verification
    cleaned_actions = []
    for a in reply.get("quick_actions", []):
        act_type = a.get("type")
        if act_type == "PROMPT":
            cleaned_actions.append(a)
        elif act_type == "CONFIRM" and a.get("action_id") in valid_actions:
            cleaned_actions.append(a)
        elif act_type == "CONFIRM_BUNDLE" and valid_bundle and a.get("bundle_id") == valid_bundle:
            cleaned_actions.append(a)

    reply["quick_actions"] = cleaned_actions

    # 2. PII Scrubbing
    reply_text = reply.get("reply", "")
    reply_text = scrub_pii(reply_text)

    # 3. Soften claims of completed booking if no action was executed
    reply_text = soften_completed_claims(reply_text)

    # 4. Check for safety flags in outputs (CRISIS, RED_FLAG_SYMPTOM)
    for e in outputs.values():
        flags = getattr(getattr(e, "safety", None), "flags", [])
        if "CRISIS" in flags or "RED_FLAG_SYMPTOM" in flags:
            if "emergency" not in reply_text.lower() and "112" not in reply_text:
                reply_text = "Please seek immediate medical assistance or call emergency services (112 / 911). I'll be here when you're ready."
            break

    reply["reply"] = reply_text
    return reply


# Node functions for StateGraph
async def escalate_node(state: dict[str, Any]) -> dict[str, Any]:
    guard = state.get("guard", {})
    labels = guard.get("labels", [])
    if "CRISIS" in labels:
        msg = "If you or someone you know is in crisis or distress, please call 988 or your local emergency line immediately. Help is available 24/7. I'll be here when you're ready."
    else:
        msg = "If you are experiencing acute pain, shortness of breath, dizziness or severe symptoms, please stop all activity and call emergency services (112 / 911) or proceed to the nearest emergency room. I'll be here when you're ready."

    return {
        "reply": {
            "reply": msg,
            "quick_actions": [],
            "conflicts_resolved": [],
            "flags": labels,
        },
        "bundle": None,
    }


async def refuse_node(state: dict[str, Any]) -> dict[str, Any]:
    guard = state.get("guard", {})
    labels = guard.get("labels", [])
    if "CROSS_USER_REQUEST" in labels:
        msg = "I can only search, book, or manage memberships for your own account. I cannot perform actions for another user."
    elif "PRIVILEGE_ESCALATION" in labels:
        msg = "I cannot grant administrator or trainer privileges. Role requests must follow standard gym verification procedures."
    elif "PROMPT_INJECTION" in labels:
        msg = "I cannot follow instructions that attempt to ignore or bypass safety guidelines."
    elif "OUT_OF_SCOPE" in labels:
        msg = "I am the GymPro AI assistant, here to assist with workout scheduling, gym memberships, wellness, and fitness nutrition. How can I help with your fitness journey?"
    else:
        msg = "I cannot fulfill this request based on safety policy."

    return {
        "reply": {
            "reply": msg,
            "quick_actions": [],
            "conflicts_resolved": [],
            "flags": labels,
        },
        "bundle": None,
    }


async def clarify_node(state: dict[str, Any]) -> dict[str, Any]:
    guard = state.get("guard", {})
    reason = guard.get("reason", "Please clarify your request.")
    return {
        "reply": {
            "reply": f"Could you please clarify your request? ({reason})",
            "quick_actions": [],
            "conflicts_resolved": [],
            "flags": guard.get("labels", []),
        },
        "bundle": None,
    }
