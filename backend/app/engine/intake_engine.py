from __future__ import annotations

import uuid
from dataclasses import dataclass, field
from typing import Any

from ..config import settings
from ..knowledge import CASE_KNOWLEDGE
from ..knowledge.base import CaseTypeKnowledge
from .llm import chat_json
from .report_generator import generate_report


@dataclass
class SessionState:
    session_id: str = field(default_factory=lambda: str(uuid.uuid4()))
    state: str = "greeting"
    case_type: str | None = None
    case_type_confidence: float = 0.0
    gathered_facts: dict[str, Any] = field(default_factory=dict)
    conversation_history: list[dict] = field(default_factory=list)
    report: dict | None = None


class IntakeEngine:
    def __init__(self) -> None:
        self.sessions: dict[str, SessionState] = {}

    def start_session(self) -> tuple[str, str]:
        session = SessionState()
        session.state = "intake"

        greeting = (
            f"Hey! I'm the intake assistant for {settings.firm_name}. "
            "I'll ask you a few quick questions so our attorneys can review your situation — "
            "totally confidential, no pressure.\n\n"
            "What's going on?"
        )

        session.conversation_history.append(
            {"role": "assistant", "content": greeting}
        )
        self.sessions[session.session_id] = session
        return session.session_id, greeting

    async def process_message(
        self, session_id: str, user_message: str
    ) -> dict:
        session = self.sessions.get(session_id)
        if session is None:
            return {"message": "Session not found. Please start a new conversation.", "ready_for_report": False}

        session.conversation_history.append(
            {"role": "user", "content": user_message}
        )

        if session.state == "complete":
            return {
                "message": "You're all set — an attorney will be in touch soon.",
                "case_type": session.case_type,
                "ready_for_report": True,
            }

        if session.state == "generating_report":
            return await self._finalize(session)

        return await self._handle_intake(session)

    async def get_report(self, session_id: str) -> dict | None:
        session = self.sessions.get(session_id)
        if session is None or session.report is None:
            return None
        return session.report

    # ------------------------------------------------------------------
    # Internal
    # ------------------------------------------------------------------

    async def _handle_intake(self, session: SessionState) -> dict:
        prompt = self._build_prompt(session)
        result = await chat_json(prompt, session.conversation_history)

        if result.get("extracted_facts"):
            for k, v in result["extracted_facts"].items():
                if v is not None:
                    session.gathered_facts[k] = v

        if (
            result.get("case_type")
            and result.get("case_type_confidence", 0) > 0.7
        ):
            session.case_type = result["case_type"]
            session.case_type_confidence = result["case_type_confidence"]

        response_text = result.get(
            "response",
            "Could you tell me a bit more about what happened?",
        )
        session.conversation_history.append(
            {"role": "assistant", "content": response_text}
        )

        if result.get("ready_for_report"):
            session.state = "generating_report"
            return await self._finalize(session)

        return {
            "message": response_text,
            "case_type": session.case_type,
            "ready_for_report": False,
        }

    async def _finalize(self, session: SessionState) -> dict:
        if session.case_type is None:
            session.state = "intake"
            return {
                "message": "Can you tell me a bit more about what happened?",
                "case_type": None,
                "ready_for_report": False,
            }

        knowledge = CASE_KNOWLEDGE.get(session.case_type)
        report = await generate_report(session, knowledge)
        session.report = report
        session.state = "complete"

        return {
                "message": (
                    "Got it — I have everything I need. "
                    "An attorney will review your info and reach out soon. "
                    "Anything else you want to add?"
                ),
            "case_type": session.case_type,
            "ready_for_report": True,
        }

    # ------------------------------------------------------------------
    # Prompt builders
    # ------------------------------------------------------------------

    def _build_prompt(self, session: SessionState) -> str:
        if session.case_type is None:
            return self._classification_prompt()
        return self._fact_gathering_prompt(session)

    def _classification_prompt(self) -> str:
        case_lines = []
        for knowledge in CASE_KNOWLEDGE.values():
            case_lines.append(
                f"  - type key: \"{knowledge.case_type}\"\n"
                f"    name: {knowledge.display_name}\n"
                f"    keywords: {', '.join(knowledge.keywords)}"
            )
        case_block = "\n".join(case_lines)

        return (
            f"You are a friendly, concise legal intake assistant for {settings.firm_name}, "
            "a Texas criminal defense law firm.\n\n"
            "YOUR JOB: Quickly figure out what happened and gather the key facts "
            "so the attorneys can decide whether to take the case.\n\n"
            "RULES:\n"
            "- Sound like a real person — warm, calm, never robotic.\n"
            "- ONE short question at a time. Max 1-2 sentences per response.\n"
            "- Never give legal opinions or predictions. If asked, say: \"The attorney can go over that with you.\"\n"
            "- Don't over-explain. Get to the point.\n\n"
            "CASE TYPES YOU CAN IDENTIFY:\n"
            f"{case_block}\n\n"
            "Identify the case type as fast as possible, then start asking the most important questions.\n\n"
            "RESPOND WITH THIS EXACT JSON FORMAT:\n"
            "{\n"
            '  "extracted_facts": {},\n'
            '  "case_type": "dwi" or "parking_ticket" or null,\n'
            '  "case_type_confidence": 0.0 to 1.0,\n'
            '  "response": "your response — short and conversational",\n'
            '  "ready_for_report": false\n'
            "}\n"
        )

    def _fact_gathering_prompt(self, session: SessionState) -> str:
        knowledge = CASE_KNOWLEDGE[session.case_type]
        gathered = session.gathered_facts

        missing = self._get_missing_facts(knowledge, gathered)

        gathered_lines = (
            "\n".join(f"  {k}: {v}" for k, v in gathered.items())
            or "  (none yet)"
        )
        missing_lines = "\n".join(
            f"  [priority {f.priority}] {f.key}: \"{f.question}\""
            for f in missing[:6]
        )

        readiness = self._assess_readiness(knowledge, gathered)

        return (
            f"You are a friendly, concise legal intake assistant for {settings.firm_name}, "
            "a Texas criminal defense law firm.\n\n"
            f"CASE TYPE: {knowledge.display_name}\n"
            f"JURISDICTION: {knowledge.jurisdiction}\n\n"
            "RULES:\n"
            "- Sound like a real, caring person. Short, natural sentences.\n"
            "- ONE question per response. Max 1-2 sentences.\n"
            "- Briefly acknowledge what they said, then ask the next thing.\n"
            "- Never give legal opinions. If asked: \"The attorney can go over that with you.\"\n"
            "- Don't repeat questions already answered.\n\n"
            "FACTS ALREADY GATHERED:\n"
            f"{gathered_lines}\n\n"
            "FACTS STILL NEEDED (ask highest priority first):\n"
            f"{missing_lines}\n\n"
            f"{readiness}\n\n"
            "EXTRACTION RULES:\n"
            "- Only extract facts the caller explicitly stated or clearly implied.\n"
            "- Use the fact key names listed above.\n"
            "- Set value to null if not mentioned.\n\n"
            "RESPOND WITH THIS EXACT JSON FORMAT:\n"
            "{\n"
            f'  "extracted_facts": {{...new facts from the latest message...}},\n'
            f'  "case_type": "{session.case_type}",\n'
            f'  "case_type_confidence": {session.case_type_confidence},\n'
            '  "response": "your conversational response",\n'
            '  "ready_for_report": true or false\n'
            "}\n"
        )

    # ------------------------------------------------------------------
    # Helpers
    # ------------------------------------------------------------------

    @staticmethod
    def _get_missing_facts(
        knowledge: CaseTypeKnowledge, gathered: dict
    ) -> list:
        missing = []
        for fact in knowledge.facts:
            if fact.key in gathered:
                continue
            if fact.follow_up_condition:
                skip = False
                for cond_key, cond_val in fact.follow_up_condition.items():
                    actual = gathered.get(cond_key)
                    if actual is None or str(actual).lower() != str(cond_val).lower():
                        skip = True
                        break
                if skip:
                    continue
            missing.append(fact)
        missing.sort(key=lambda f: f.priority)
        return missing

    @staticmethod
    def _assess_readiness(
        knowledge: CaseTypeKnowledge, gathered: dict
    ) -> str:
        p1_facts = [
            f for f in knowledge.facts
            if f.priority == 1 and not f.follow_up_condition
        ]
        p2_facts = [
            f for f in knowledge.facts
            if f.priority == 2 and not f.follow_up_condition
        ]

        p1_done = all(f.key in gathered for f in p1_facts)
        p2_done = all(f.key in gathered for f in p2_facts)

        if p1_done and p2_done:
            return (
                "STATUS: All critical and important facts are gathered. "
                "Ask if there's anything else they want to add, then set "
                "ready_for_report to true."
            )
        if p1_done:
            return (
                "STATUS: All critical facts gathered. "
                "Continue with important (priority 2) questions."
            )
        return "STATUS: Still gathering critical facts."


engine = IntakeEngine()
