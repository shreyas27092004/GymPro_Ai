# app/agents/schemas.py
from typing import Any, Literal
from pydantic import BaseModel, Field, field_validator

Status = Literal["OK", "NEEDS_INPUT", "NEEDS_CONFIRMATION", "REFUSED", "ESCALATE", "ERROR"]
Flag = Literal[
    "PROMPT_INJECTION",
    "RED_FLAG_SYMPTOM",
    "CRISIS",
    "MINOR",
    "PREGNANCY",
    "ALLERGY_CONSTRAINT",
    "EATING_DISORDER_SIGNAL",
    "MEDICAL_CONDITION",
    "CROSS_USER_REQUEST",
    "OUT_OF_SCOPE",
    "PRIVILEGE_ESCALATION",
    "EMAIL_TARGET_REFUSED",
]


class Confirmation(BaseModel):
    action_id: str | None = None
    summary: str | None = None
    expires_at: str | None = None


class Safety(BaseModel):
    flags: list[Flag] = []
    escalation: str | None = None


class Envelope(BaseModel):
    agent: str
    schema_version: Literal["1.0", "2.0", "3.0"] = "1.0"
    status: Status
    data: dict[str, Any] = {}
    projected_effects: dict[str, Any] | None = None
    user_message: str = Field(max_length=700)
    missing_fields: list[str] = []
    confirmation: Confirmation = Confirmation()
    safety: Safety = Safety()
    citations: list[dict[str, Any]] = []
    confidence: float = Field(default=1.0, ge=0, le=1)

    @field_validator("user_message")
    @classmethod
    def word_limit(cls, v: str) -> str:
        if len(v.split()) > 90:  # 80 in the prompt + tolerance
            raise ValueError("user_message too long")
        return v


class MacroSet(BaseModel):
    protein_g: int
    carbs_g: int
    fats_g: int | None = None
    fat_g: int | None = None

    def model_post_init(self, __context: Any) -> None:
        if self.fats_g is None and self.fat_g is not None:
            self.fats_g = self.fat_g
        elif self.fat_g is None and self.fats_g is not None:
            self.fat_g = self.fats_g
        if self.fats_g is None:
            self.fats_g = 0
            self.fat_g = 0


class NutritionData(BaseModel):
    daily_calories: int | None = None
    macros: MacroSet | None = None
    meals: list[dict[str, Any]] = []


class CommsData(BaseModel):
    template_id: str | None = None
    channel: str | None = None
    to_masked: str | None = None
    attach_calendar: bool = False
    requires_step: int | None = None


class SupportData(BaseModel):
    operation: Literal["COLLECT", "PROPOSE_REPORT", "REFUSE"] = "COLLECT"
    class_id: str | None = None
    category: str | None = None
    severity_hint: Literal["LOW", "MEDIUM", "HIGH", "URGENT"] | None = None
    neutral_summary: str | None = Field(default=None, max_length=300)


class FitnessData(BaseModel):
    weekly_frequency: int | None = None
    recommended_classes: list[dict[str, Any]] = []
    roadmap: list[dict[str, Any]] = []
    rest_days_per_week: int | None = None
    excluded_for_safety: list[str] = []
    based_on: list[str] = []
    rationale: str | None = None
    reassess_after_days: int | None = None
    disclaimer: str | None = None


class TrainerInfoData(BaseModel):
    match_count: int = 0
    trainers: list[dict[str, Any]] = []
    relaxed_filter: str | None = None
    handoff_to: Literal["SCHEDULE", "MEMBERSHIP"] | None = None


DATA_MODELS = {
    "NUTRITION": NutritionData,
    "COMMS": CommsData,
    "SUPPORT": SupportData,
    "FITNESS": FitnessData,
    "TRAINER_INFO": TrainerInfoData,
}
