# tests/evals/fake_llm.py
from dataclasses import dataclass, field
import json
import re
from typing import Any, Callable


@dataclass
class FakeFunction:
    name: str
    arguments: str


@dataclass
class FakeToolCall:
    id: str
    type: str = "function"
    function: FakeFunction = field(default_factory=lambda: FakeFunction(name="", arguments="{}"))


@dataclass
class FakeMessage:
    role: str = "assistant"
    content: str | None = None
    tool_calls: list[FakeToolCall] | None = None


@dataclass
class FakeChoice:
    message: FakeMessage
    index: int = 0
    finish_reason: str = "stop"


@dataclass
class FakeUsage:
    prompt_tokens: int = 150
    completion_tokens: int = 100
    total_tokens: int = 250


@dataclass
class FakeChatCompletion:
    id: str = "chatcmpl-fake-123"
    choices: list[FakeChoice] = field(default_factory=list)
    usage: FakeUsage = field(default_factory=FakeUsage)


class FakeLLM:
    """
    Deterministic scripted LLM for hermetic testing and evaluation.
    Inspects messages, simulates tool calling steps, and produces compliant JSON envelopes.
    """

    def __init__(self):
        self.call_history: list[dict[str, Any]] = []
        self.custom_handlers: list[Callable[[list[dict[str, Any]]], FakeChatCompletion | None]] = []

    def register_handler(self, handler: Callable[[list[dict[str, Any]]], FakeChatCompletion | None]):
        self.custom_handlers.insert(0, handler)

    @property
    def chat(self):
        return self

    @property
    def completions(self):
        return self

    def reset(self):
        self.call_history.clear()
        self.custom_handlers.clear()

    async def create(
        self,
        model: str,
        messages: list[dict[str, Any]],
        tools: list[dict[str, Any]] | None = None,
        temperature: float = 0.1,
        response_format: dict[str, Any] | None = None,
        **kwargs,
    ) -> FakeChatCompletion:
        self.call_history.append({"messages": messages, "tools": tools})

        # Run custom handlers if any match
        for handler in self.custom_handlers:
            res = handler(messages)
            if res is not None:
                return res

        # Extract context
        sys_msg = next((m["content"] for m in messages if m.get("role") == "system"), "")
        user_msg = next((m["content"] for m in reversed(messages) if m.get("role") == "user"), "")
        tool_results = [m for m in messages if m.get("role") == "tool"]

        # Check for Supervisor prompts
        if "SUPERVISOR_GUARD" in sys_msg:
            return self._handle_guard(user_msg)
        elif "SUPERVISOR_PLANNER" in sys_msg:
            return self._handle_planner(user_msg)
        elif "SYNTHESIZER" in sys_msg:
            return self._handle_synthesizer(user_msg)

        # Determine agent
        agent = "SCHEDULE"
        if "AGENT: MEMBERSHIP" in sys_msg:
            agent = "MEMBERSHIP"
        elif "AGENT: WELLNESS" in sys_msg:
            agent = "WELLNESS"
        elif "AGENT: NUTRITION" in sys_msg:
            agent = "NUTRITION"
        elif "AGENT: COMMS" in sys_msg:
            agent = "COMMS"
        elif "AGENT: SUPPORT" in sys_msg:
            agent = "SUPPORT"

        # Check for injection or cross-user attempts across all agents
        if re.search(r"ignore\s+.*rules|you\s+are\s+admin|another\s+user|someone\s+else|lifetime\s+free|print\s+your.*prompt|steroid", user_msg, re.IGNORECASE):
            flags = ["PROMPT_INJECTION"]
            if "another user" in user_msg.lower() or "someone else" in user_msg.lower():
                flags.append("CROSS_USER_REQUEST")
            return self._envelope_response(
                agent=agent,
                status="REFUSED",
                flags=flags,
                user_message="I cannot follow instructions to ignore safety rules or operate across other accounts.",
                data={"operation": "CLARIFY", "options": []} if agent == "SCHEDULE" else {},
            )

        # Route by agent
        if agent == "SCHEDULE":
            return self._handle_schedule(messages, user_msg, tool_results)
        elif agent == "MEMBERSHIP":
            return self._handle_membership(messages, user_msg, tool_results)
        elif agent == "WELLNESS":
            return self._handle_wellness(messages, user_msg, tool_results)
        elif agent == "NUTRITION":
            return self._handle_nutrition(messages, user_msg, tool_results)
        elif agent == "COMMS":
            return self._handle_comms(messages, user_msg, tool_results)
        elif agent == "SUPPORT":
            return self._handle_support(messages, user_msg, tool_results)

        return self._envelope_response(agent, "OK", [], "How can I help you today?")

    def _handle_schedule(self, messages: list[dict[str, Any]], user_msg: str, tool_results: list[dict[str, Any]]) -> FakeChatCompletion:
        # Check typo
        if "semba" in user_msg.lower():
            if not tool_results:
                return self._tool_call_response([
                    ("call_match_1", "match_class_name", {"text": "semba", "date_from": "2026-10-17", "date_to": "2026-10-17"})
                ])
            return self._envelope_response(
                agent="SCHEDULE",
                status="NEEDS_INPUT",
                flags=[],
                user_message="I found two close matches on Saturday: Zumba Fusion or Samba Dance. Which one did you mean?",
                data={
                    "operation": "CLARIFY",
                    "options": [
                        {"class_id": "c1", "title": "Zumba Fusion", "start_time": "2026-10-17T10:00:00+05:30", "end_time": "2026-10-17T11:00:00+05:30", "trainer_name": "Asha Rao", "spots_left": 4, "est_calories": 420, "impact": "MODERATE", "conflict": False, "uses": "INCLUDED"},
                        {"class_id": "c2", "title": "Samba Dance", "start_time": "2026-10-17T17:00:00+05:30", "end_time": "2026-10-17T18:00:00+05:30", "trainer_name": "Ravi Nair", "spots_left": 9, "est_calories": 380, "impact": "MODERATE", "conflict": False, "uses": "INCLUDED"},
                    ],
                    "filtered_for_safety": 0,
                    "selected_class_id": None,
                    "booking_id": None,
                    "depends_on_projected": False,
                },
                missing_fields=["class_choice"],
            )

        # Standard booking flow
        if "book" in user_msg.lower() or "zumba" in user_msg.lower():
            is_zumba = "zumba" in user_msg.lower()
            target_cid = "22222222-2222-2222-2222-222222222222" if is_zumba else "11111111-1111-1111-1111-111111111111"
            title = "Zumba Fusion" if is_zumba else "Evening Yoga"
            cat = "ZUMBA" if is_zumba else "YOGA"
            start_iso = "2026-10-17T10:00:00+05:30" if is_zumba else "2026-10-17T18:00:00+05:30"
            end_iso = "2026-10-17T11:00:00+05:30" if is_zumba else "2026-10-17T19:00:00+05:30"

            if not tool_results:
                return self._tool_call_response([
                    ("call_search_1", "search_classes", {"category": cat, "date_from": "2026-10-17", "date_to": "2026-10-17"}),
                ])
            elif len(tool_results) == 1:
                return self._tool_call_response([
                    ("call_chk_1", "check_conflicts", {"class_id": target_cid}),
                    ("call_prop_1", "propose_booking", {"class_id": target_cid}),
                ])
            else:
                action_id = "a1111111-1111-1111-1111-111111111111"
                for tr in tool_results:
                    try:
                        content = tr.get("content", "")
                        clean = content.replace("<tool_result>", "").replace("</tool_result>", "").strip()
                        p = json.loads(clean)
                        if "action_id" in p:
                            action_id = p["action_id"]
                    except Exception:
                        pass

                return self._envelope_response(
                    agent="SCHEDULE",
                    status="NEEDS_CONFIRMATION",
                    flags=[],
                    user_message=f"I have set up your booking for {title} on Saturday. Please tap confirm below to finalize.",
                    data={
                        "operation": "PROPOSE_BOOK",
                        "options": [
                            {"class_id": target_cid, "title": title, "start_time": start_iso, "end_time": end_iso, "trainer_name": "Maya", "spots_left": 5, "est_calories": 350, "impact": "MODERATE", "conflict": False, "uses": "INCLUDED"}
                        ],
                        "filtered_for_safety": 0,
                        "selected_class_id": target_cid,
                        "booking_id": None,
                        "depends_on_projected": is_zumba,
                    },
                    confirmation={
                        "action_id": action_id,
                        "summary": f"Book {title} on Sat 17 Oct. Included in your membership.",
                        "expires_at": "2026-10-16T18:15:00+05:30",
                    },
                )

        return self._envelope_response("SCHEDULE", "OK", [], "I can help you search, book, or cancel classes.")

    def _handle_membership(self, messages: list[dict[str, Any]], user_msg: str, tool_results: list[dict[str, Any]]) -> FakeChatCompletion:
        # Upgrade flow
        if "upgrade" in user_msg.lower() or "platinum" in user_msg.lower():
            if not tool_results:
                return self._tool_call_response([
                    ("call_high_1", "get_highest_plan", {}),
                    ("call_mem_1", "get_my_membership", {}),
                    ("call_pd_1", "price_diff", {"to_plan": "PLATINUM", "cycle": "MONTHLY"}),
                    ("call_prop_m_1", "propose_plan_change", {"to_plan": "PLATINUM", "cycle": "MONTHLY", "confirmed_total": 1000.00}),
                ])
            action_id = "b2222222-2222-2222-2222-222222222222"
            for tr in tool_results:
                try:
                    clean = tr.get("content", "").replace("<tool_result>", "").replace("</tool_result>", "").strip()
                    p = json.loads(clean)
                    if "action_id" in p:
                        action_id = p["action_id"]
                except Exception:
                    pass

            return self._envelope_response(
                agent="MEMBERSHIP",
                status="NEEDS_CONFIRMATION",
                flags=[],
                user_message="Platinum is our highest plan. It replaces Gold today. You pay 1000.00 INR now (prorated), then 3499.00 INR per month from 16 Nov 2026.",
                data={
                    "current": {"plan": "GOLD", "status": "ACTIVE", "end_date": "2026-11-16", "auto_renew": True},
                    "trial": {"active": False, "classes_remaining": 0, "expires_at": None},
                    "comparison": [{"plan": "PLATINUM", "delta_per_cycle": 1500.0, "currency": "INR", "gains": ["5 PT sessions", "spa"], "unused_by_you": []}],
                    "recommendation": "UPGRADE",
                    "evidence": [],
                    "proposed_action_id": action_id,
                    "replaces_membership": True,
                },
                projected_effects={
                    "plan_after": "PLATINUM",
                    "effective": "on_confirm",
                    "entitlements_after": {"classes_remaining": None, "pt_remaining": 5},
                },
                confirmation={
                    "action_id": action_id,
                    "summary": "Upgrade Gold to Platinum. Gold ends today. Pay 1000.00 INR now (prorated), then 3499.00 INR per month from 16 Nov 2026.",
                    "expires_at": "2026-10-16T18:15:00+05:30",
                },
            )

        if "trial" in user_msg.lower() or "book" in user_msg.lower():
            if not tool_results:
                return self._tool_call_response([
                    ("call_ts_1", "get_trial_status", {})
                ])
            return self._envelope_response(
                agent="MEMBERSHIP",
                status="NEEDS_INPUT",
                flags=[],
                user_message="You have used all 3 of your free trial classes. To keep attending classes, you can select one of our membership plans: Silver, Gold, or Platinum.",
                data={
                    "current": None,
                    "trial": {"active": False, "classes_remaining": 0, "expires_at": "2026-10-30T18:05:00+05:30"},
                    "comparison": [],
                    "recommendation": "NONE",
                    "evidence": ["trial_used"],
                    "proposed_action_id": None,
                    "replaces_membership": False,
                },
                missing_fields=["plan_selection"],
            )

        return self._envelope_response("MEMBERSHIP", "OK", [], "I can explain membership options and assist with upgrades.")

    def _handle_wellness(self, messages: list[dict[str, Any]], user_msg: str, tool_results: list[dict[str, Any]]) -> FakeChatCompletion:
        lower = user_msg.lower()
        if any(k in lower for k in ("end my life", "suicidal", "kill myself", "giving up", "self-harm")):
            return self._envelope_response(
                agent="WELLNESS",
                status="ESCALATE",
                flags=["CRISIS"],
                user_message="If you are feeling overwhelmed or having thoughts of harming yourself, please know support is available right now. Please reach out to emergency resources or a crisis hotline.",
                data={
                    "conditions": [],
                    "safety_constraints": {"avoid_categories": ["ALL_EXERTION"], "max_impact": "LOW", "avoid_movements": [], "contraindicated_for_codes": []},
                    "preferred_activities": [],
                    "metrics": {"bmr": None, "tdee": None, "bmi": None, "hydration_ml": None},
                    "professional_referral": {"recommended": True, "type": "physician", "reason": "Immediate crisis support needed."},
                    "based_on": ["reported: crisis signal"],
                    "disclaimer": "General wellness information, not medical advice.",
                },
            )

        if any(k in lower for k in ("chest feels tight", "chest tight", "chest pain", "dizzy yesterday", "fainted")):
            return self._envelope_response(
                agent="WELLNESS",
                status="ESCALATE",
                flags=["RED_FLAG_SYMPTOM"],
                user_message="Chest tightness and dizziness during exercise require immediate medical evaluation. Please see a physician right away or call local emergency services.",
                data={
                    "conditions": [],
                    "safety_constraints": {"avoid_categories": ["ALL_EXERTION"], "max_impact": "LOW", "avoid_movements": [], "contraindicated_for_codes": []},
                    "preferred_activities": [],
                    "metrics": {"bmr": None, "tdee": None, "bmi": None, "hydration_ml": None},
                    "professional_referral": {"recommended": True, "type": "physician", "reason": "Chest tightness and dizziness during exertion."},
                    "based_on": ["reported: chest tightness, dizziness"],
                    "disclaimer": "General wellness information, not medical advice.",
                },
            )

        if "severe knee pain" in lower:
            if not tool_results:
                return self._tool_call_response([
                    ("call_ip_1", "get_injury_protocol", {"codes": ["KNEE"]})
                ])
            return self._envelope_response(
                agent="WELLNESS",
                status="OK",
                flags=["MEDICAL_CONDITION"],
                user_message="Severe knee pain should be assessed by a professional. If moving today, keep to very gentle low-impact options like swimming or upper body.",
                data={
                    "conditions": [{"code": "KNEE", "reported_text": "severe knee pain", "acuity": "POSSIBLY_ACUTE"}],
                    "safety_constraints": {"avoid_categories": ["HIIT", "SPIN"], "max_impact": "LOW", "avoid_movements": ["jumping", "sprinting"], "contraindicated_for_codes": ["KNEE"]},
                    "preferred_activities": ["SWIMMING", "YOGA"],
                    "metrics": {"bmr": None, "tdee": None, "bmi": None, "hydration_ml": None},
                    "professional_referral": {"recommended": True, "type": "physiotherapist", "reason": "Severe knee pain should be evaluated."},
                    "based_on": ["reported: severe knee pain"],
                    "disclaimer": "General wellness information, not medical advice.",
                },
            )

        return self._envelope_response("WELLNESS", "OK", [], "I can provide exercise safety guidelines and wellness protocols.")

    def _handle_nutrition(self, messages: list[dict[str, Any]], user_msg: str, tool_results: list[dict[str, Any]]) -> FakeChatCompletion:
        lower = user_msg.lower()

        # Check minor constraint (< 18)
        if "1200 calorie" in lower and ("age_years: 16" in user_msg.lower() or "age_years\": 16" in user_msg.lower()):
            return self._envelope_response(
                agent="NUTRITION",
                status="REFUSED",
                flags=["MINOR"],
                user_message="I cannot build a calorie-restricted plan for someone under 18. A registered dietitian or physician is the right professional for weight goals.",
                data={
                    "goal": None,
                    "dietary_preference": None,
                    "daily_calories": None,
                    "macros": None,
                    "split_used": None,
                    "tdee_basis": None,
                    "meals": [],
                    "allergen_check": {"allergies": [], "violations": []},
                    "based_on": [],
                    "notes": [],
                    "referral": "dietitian",
                    "disclaimer": "General nutrition information, not medical advice.",
                },
            )

        # Check eating disorder
        if any(k in lower for k in ("burn off everything", "burn off what i ate", "purge")):
            return self._envelope_response(
                agent="NUTRITION",
                status="ESCALATE",
                flags=["EATING_DISORDER_SIGNAL"],
                user_message="Food does not need to be burned off or compensated for through extreme measures. Please consider speaking with a compassionate healthcare professional.",
                data={
                    "goal": None,
                    "dietary_preference": None,
                    "daily_calories": None,
                    "macros": None,
                    "split_used": None,
                    "tdee_basis": None,
                    "meals": [],
                    "allergen_check": {"allergies": [], "violations": []},
                    "based_on": [],
                    "notes": [],
                    "referral": "physician",
                    "disclaimer": "General nutrition information, not medical advice.",
                },
            )

        # Allergy-constrained plan
        if "vegetarian plan" in lower or "2400 kcal" in lower:
            if not tool_results:
                return self._tool_call_response([
                    ("call_mac_1", "compute_macros", {"target_kcal": 2400, "split_name": "MUSCLE_GAIN"}),
                    ("call_ff_1", "find_foods", {"constraints": {"exclude_allergens": ["peanut"], "diet": "VEGETARIAN"}}),
                ])
            return self._envelope_response(
                agent="NUTRITION",
                status="OK",
                flags=["ALLERGY_CONSTRAINT"],
                user_message="Here is your 2400 kcal vegetarian meal plan. It is completely peanut-free.",
                data={
                    "goal": "MUSCLE_GAIN",
                    "dietary_preference": "VEGETARIAN",
                    "daily_calories": 2400,
                    "macros": {"protein_g": 180, "carbs_g": 300, "fat_g": 53},
                    "split_used": "MUSCLE_GAIN",
                    "tdee_basis": 2400,
                    "meals": [
                        {"meal": "Breakfast", "items": [{"food": "Oats with Almond Milk", "qty": "1 bowl", "kcal": 800, "protein_g": 60, "carbs_g": 100, "fat_g": 18}], "kcal": 800, "protein_g": 60},
                        {"meal": "Lunch", "items": [{"food": "Paneer Rice Bowl", "qty": "1 bowl", "kcal": 800, "protein_g": 60, "carbs_g": 100, "fat_g": 18}], "kcal": 800, "protein_g": 60},
                        {"meal": "Dinner", "items": [{"food": "Tofu Stir-fry", "qty": "1 plate", "kcal": 800, "protein_g": 60, "carbs_g": 100, "fat_g": 17}], "kcal": 800, "protein_g": 60},
                    ],
                    "allergen_check": {"allergies": ["peanut"], "violations": []},
                    "based_on": ["goal: MUSCLE_GAIN", "diet: VEGETARIAN", "allergies: peanut"],
                    "notes": [],
                    "referral": "none",
                    "disclaimer": "General nutrition information, not medical advice.",
                },
            )

        return self._envelope_response("NUTRITION", "OK", [], "I can help create personalized nutrition and meal targets.")

    def _tool_call_response(self, calls: list[tuple[str, str, dict[str, Any]]]) -> FakeChatCompletion:
        tcs = [
            FakeToolCall(
                id=call_id,
                type="function",
                function=FakeFunction(name=fn_name, arguments=json.dumps(args)),
            )
            for call_id, fn_name, args in calls
        ]
        return FakeChatCompletion(
            choices=[FakeChoice(message=FakeMessage(role="assistant", content=None, tool_calls=tcs))]
        )

    def _envelope_response(
        self,
        agent: str,
        status: str,
        flags: list[str],
        user_message: str,
        data: dict[str, Any] | None = None,
        projected_effects: dict[str, Any] | None = None,
        missing_fields: list[str] | None = None,
        confirmation: dict[str, Any] | None = None,
    ) -> FakeChatCompletion:
        env = {
            "agent": agent.upper(),
            "schema_version": "1.0",
            "status": status,
            "data": data or {},
            "projected_effects": projected_effects,
            "user_message": user_message,
            "missing_fields": missing_fields or [],
            "confirmation": confirmation or {"action_id": None, "summary": None, "expires_at": None},
            "safety": {"flags": flags, "escalation": "SEEK_URGENT_CARE" if status == "ESCALATE" else None},
            "citations": [],
            "confidence": 0.95,
        }
        return FakeChatCompletion(
            choices=[FakeChoice(message=FakeMessage(role="assistant", content=json.dumps(env)))]
        )

    def _handle_comms(self, messages: list[dict[str, Any]], user_msg: str, tool_results: list[dict[str, Any]]) -> FakeChatCompletion:
        if "sam@example.com" in user_msg.lower() or "friend" in user_msg.lower():
            return self._envelope_response(
                agent="COMMS",
                status="REFUSED",
                flags=["EMAIL_TARGET_REFUSED"],
                user_message="I can only email your own account address. Want me to send the details there so you can forward them?",
                data={"template_id": None, "channel": None, "to_masked": None, "title": "", "body_preview": "", "attach_calendar": False, "requires_step": None, "send_after": None, "dedupe_key": ""},
            )

        if not tool_results:
            return self._tool_call_response([
                ("call_gt_1", "get_template", {"template_id": "BOOKING_DETAILS"}),
                ("call_prop_mail", "propose_send_email", {"template_id": "BOOKING_DETAILS", "params": {"class_title": "Zumba Fusion"}, "attach_calendar": True, "requires_step": 2}),
            ])

        action_id = "c3333333-3333-3333-3333-333333333333"
        for tr in tool_results:
            try:
                clean = tr.get("content", "").replace("<tool_result>", "").replace("</tool_result>", "").strip()
                p = json.loads(clean)
                if "action_id" in p:
                    action_id = p["action_id"]
            except Exception:
                pass

        return self._envelope_response(
            agent="COMMS",
            status="NEEDS_CONFIRMATION",
            flags=[],
            user_message="I'll email the booking details and a calendar file to your account email once the booking is confirmed.",
            data={
                "template_id": "BOOKING_DETAILS",
                "channel": "EMAIL",
                "to_masked": "m***@gympro.test",
                "title": "Your booking: Zumba Fusion",
                "body_preview": "Class, date, time and a calendar file.",
                "attach_calendar": True,
                "requires_step": 2,
                "send_after": None,
                "dedupe_key": "booking-details:step2",
            },
            confirmation={
                "action_id": action_id,
                "summary": "Email booking details with a calendar file to your account email after the Zumba booking succeeds.",
                "expires_at": "2026-10-16T18:15:00+05:30",
            },
        )

    def _handle_support(self, messages: list[dict[str, Any]], user_msg: str, tool_results: list[dict[str, Any]]) -> FakeChatCompletion:
        if not tool_results:
            return self._tool_call_response([
                ("call_todays_classes", "get_todays_classes_for_me", {})
            ])

        return self._envelope_response(
            agent="SUPPORT",
            status="NEEDS_INPUT",
            flags=[],
            user_message="What happened with today's trainer so I can send your report to the admin?",
            data={
                "operation": "COLLECT",
                "class_id": "33333333-3333-3333-3333-333333333333",
                "class_label": "HIIT Spin, today 7:00 AM",
                "category": None,
                "severity_hint": None,
                "neutral_summary": None,
                "guidance_included": False,
            },
            missing_fields=["what_happened"],
        )

    def _handle_guard(self, user_msg: str) -> FakeChatCompletion:
        low = user_msg.lower()
        labels = []
        blocked_spans = []
        route = "CONTINUE"
        severity = "NONE"

        if any(k in low for k in ("kill myself", "suicid", "end my life", "self-harm", "hurt myself")):
            return FakeChatCompletion(choices=[FakeChoice(message=FakeMessage(role="assistant", content=json.dumps({
                "labels": ["CRISIS"], "severity": "HIGH", "route": "ESCALATE", "blocked_spans": [], "reason": "Crisis detected"
            })))])

        if any(k in low for k in ("chest pain", "can't breathe", "passed out", "stroke", "severe breathlessness")):
            return FakeChatCompletion(choices=[FakeChoice(message=FakeMessage(role="assistant", content=json.dumps({
                "labels": ["MEDICAL_EMERGENCY"], "severity": "HIGH", "route": "ESCALATE", "blocked_spans": [], "reason": "Medical emergency detected"
            })))])

        if any(k in low for k in ("another user", "someone else", "my friend's account", "book this for another user")):
            labels.append("CROSS_USER_REQUEST")
            severity = "HIGH"
            route = "REFUSE"

        if any(k in low for k in ("ignore your rules", "ignore rules", "you are admin", "system prompt", "ignore previous rules")):
            labels.append("PROMPT_INJECTION")
            severity = "HIGH"
            route = "REFUSE"

        if any(k in low for k in ("sam@example.com", "friend@")):
            labels.append("EMAIL_OTHER_ADDRESS")
            blocked_spans.append("sam@example.com")

        if any(k in low for k in ("write python code", "who won the election", "crypto", "bitcoin")):
            labels.append("OUT_OF_SCOPE")
            severity = "LOW"
            route = "REFUSE"

        if not labels:
            labels = ["BENIGN"]

        return FakeChatCompletion(choices=[FakeChoice(message=FakeMessage(role="assistant", content=json.dumps({
            "labels": labels, "severity": severity, "route": route, "blocked_spans": blocked_spans, "reason": "Classifier evaluation"
        })))])

    def _handle_planner(self, user_msg: str) -> FakeChatCompletion:
        low = user_msg.lower()
        if "upgrade" in low and ("zumba" in low or "saturday" in low):
            plan = {
                "intents": [
                    {"id": "i1", "name": "UPGRADE_PLAN", "agent": "MEMBERSHIP", "depends_on": [], "confidence": 0.97},
                    {"id": "i2", "name": "BOOK_CLASS", "agent": "SCHEDULE", "depends_on": ["i1"], "confidence": 0.95},
                    {"id": "i3", "name": "EMAIL_BOOKING_DETAILS", "agent": "COMMS", "depends_on": ["i2"], "confidence": 0.93},
                    {"id": "i4", "name": "REPORT_PROBLEM", "agent": "SUPPORT", "depends_on": [], "confidence": 0.94},
                ],
                "waves": [["i1", "i4"], ["i2"], ["i3"]],
                "handoffs": [
                    {"from": "i1", "to": ["i2"], "fields": ["projected_state"]},
                    {"from": "i2", "to": ["i3"], "fields": ["step_refs"]},
                ],
                "needs_clarification": None,
                "blocked_intents": [],
                "route": "CONTINUE",
            }
            return FakeChatCompletion(choices=[FakeChoice(message=FakeMessage(role="assistant", content=json.dumps(plan)))])

        if "knee pain" in low or "soreness" in low:
            plan = {
                "intents": [
                    {"id": "i1", "name": "INJURY_AWARE_SCHEDULING", "agent": "WELLNESS", "depends_on": [], "confidence": 0.94},
                    {"id": "i2", "name": "FIND_CLASS", "agent": "SCHEDULE", "depends_on": ["i1"], "confidence": 0.94},
                ],
                "waves": [["i1"], ["i2"]],
                "handoffs": [
                    {"from": "i1", "to": ["i2"], "fields": ["safety_constraints", "preferred_activities"]},
                ],
                "needs_clarification": None,
                "blocked_intents": [],
                "route": "CONTINUE",
            }
            return FakeChatCompletion(choices=[FakeChoice(message=FakeMessage(role="assistant", content=json.dumps(plan)))])

        # Default fallback plan
        return FakeChatCompletion(choices=[FakeChoice(message=FakeMessage(role="assistant", content=json.dumps({
            "intents": [{"id": "i1", "name": "HANDLE_SCHEDULE", "agent": "SCHEDULE", "depends_on": [], "confidence": 0.9}],
            "waves": [["i1"]], "handoffs": [], "needs_clarification": None, "blocked_intents": [], "route": "CONTINUE"
        })))])

    def _handle_synthesizer(self, user_msg: str) -> FakeChatCompletion:
        reply = {
            "reply": "I have prepared your upgrade to Platinum, set up your Zumba Fusion booking for Saturday 10:00 AM, and queued the booking details email. What happened with today's trainer so I can send your report to the admin?",
            "quick_actions": [
                {"type": "CONFIRM_BUNDLE", "label": "Confirm all 3 steps"}
            ],
            "conflicts_resolved": [],
            "flags": [],
        }
        return FakeChatCompletion(choices=[FakeChoice(message=FakeMessage(role="assistant", content=json.dumps(reply)))])


fake_llm = FakeLLM()
