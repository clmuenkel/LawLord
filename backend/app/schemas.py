from pydantic import BaseModel, Field
from typing import Optional


class StartSessionResponse(BaseModel):
    session_id: str
    message: str


class ChatMessageRequest(BaseModel):
    session_id: str
    message: str


class ChatMessageResponse(BaseModel):
    message: str
    case_type: Optional[str] = None
    ready_for_report: bool = False


class IntakeReport(BaseModel):
    session_id: str
    case_type: str
    case_type_display: str
    jurisdiction: str = "Texas"
    client_summary: str
    key_facts: dict
    offense_classification: str
    potential_penalties: str
    identified_defenses: list[str]
    red_flags: list[str]
    green_flags: list[str]
    case_strength: str = Field(description="weak / moderate / strong")
    recommendation: str = Field(description="take / pass / needs_review")
    recommendation_reasoning: str
    next_steps: list[str]


class ReportRequest(BaseModel):
    session_id: str
