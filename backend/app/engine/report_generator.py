from __future__ import annotations

import json
import logging
from typing import TYPE_CHECKING, Any

from ..config import settings
from ..knowledge.base import CaseTypeKnowledge
from .llm import chat_json

if TYPE_CHECKING:
    from .intake_engine import SessionState

logger = logging.getLogger(__name__)


async def generate_report(
    session: "SessionState",
    knowledge: CaseTypeKnowledge | None,
) -> dict:
    if knowledge is None:
        return _empty_report(session.session_id)

    prompt = _build_report_prompt(session, knowledge)

    messages = [
        {
            "role": "user",
            "content": (
                "Generate the intake report based on the conversation and "
                "facts provided in the system prompt."
            ),
        }
    ]

    result = await chat_json(prompt, messages)
    result["session_id"] = session.session_id
    result.setdefault("case_type", knowledge.case_type)
    result.setdefault("case_type_display", knowledge.display_name)
    result.setdefault("jurisdiction", knowledge.jurisdiction)
    return result


def _build_report_prompt(
    session: "SessionState", knowledge: CaseTypeKnowledge
) -> str:
    facts_block = json.dumps(session.gathered_facts, indent=2)

    offense_block = "\n".join(
        f"  - {ol.name} ({ol.classification}): "
        f"Jail {ol.jail_range}, Fine {ol.fine_range}"
        f"{', Condition: ' + ol.conditions if ol.conditions else ''}"
        for ol in knowledge.offense_levels
    )

    defense_block = "\n".join(
        f"  - {d.name} [{d.strength_indicator}]: {d.description}"
        for d in knowledge.common_defenses
    )

    take_block = "\n".join(f"  - {s}" for s in knowledge.take_signals)
    pass_block = "\n".join(f"  - {s}" for s in knowledge.pass_signals)
    review_block = "\n".join(f"  - {s}" for s in knowledge.review_signals)

    conversation_summary = "\n".join(
        f"  {m['role'].upper()}: {m['content'][:300]}"
        for m in session.conversation_history
    )

    return (
        "You are a legal case evaluation assistant. Generate a structured "
        f"intake report for the attorneys at {settings.firm_name}.\n\n"
        f"CASE TYPE: {knowledge.display_name}\n"
        f"JURISDICTION: {knowledge.jurisdiction}\n\n"
        "CONVERSATION TRANSCRIPT:\n"
        f"{conversation_summary}\n\n"
        "EXTRACTED FACTS:\n"
        f"{facts_block}\n\n"
        "OFFENSE LEVELS FOR THIS CASE TYPE:\n"
        f"{offense_block}\n\n"
        "KNOWN DEFENSES:\n"
        f"{defense_block}\n\n"
        "SIGNALS — TAKE THE CASE:\n"
        f"{take_block}\n\n"
        "SIGNALS — PASS ON THE CASE:\n"
        f"{pass_block}\n\n"
        "SIGNALS — NEEDS FURTHER REVIEW:\n"
        f"{review_block}\n\n"
        "INSTRUCTIONS:\n"
        "Based on ALL the above, produce a JSON report with these fields:\n"
        "{\n"
        '  "client_summary": "2-3 sentence plain-English summary of the situation",\n'
        '  "key_facts": {fact_key: value for the most important facts},\n'
        '  "offense_classification": "The specific offense level that applies",\n'
        '  "potential_penalties": "Penalty range for this classification",\n'
        '  "identified_defenses": ["list of potentially viable defenses based on the facts"],\n'
        '  "red_flags": ["list of concerning factors that weaken the case"],\n'
        '  "green_flags": ["list of positive factors that strengthen the case or defense"],\n'
        '  "case_strength": "weak" or "moderate" or "strong",\n'
        '  "recommendation": "take" or "pass" or "needs_review",\n'
        '  "recommendation_reasoning": "2-3 sentences explaining the recommendation",\n'
        '  "next_steps": ["list of recommended next steps if the firm takes the case"]\n'
        "}\n\n"
        "GUIDELINES:\n"
        "- Base the recommendation on the SIGNALS lists above and the facts gathered.\n"
        "- Be specific — reference actual facts, not generalities.\n"
        "- If critical facts are missing, lean toward needs_review.\n"
        "- For defenses, only list ones supported by the gathered facts.\n"
        "- Be honest and direct. This report is for attorneys, not the client.\n"
    )


def _empty_report(session_id: str) -> dict:
    return {
        "session_id": session_id,
        "case_type": "unknown",
        "case_type_display": "Unclassified",
        "jurisdiction": "Texas",
        "client_summary": "Unable to determine case type from conversation.",
        "key_facts": {},
        "offense_classification": "Unknown",
        "potential_penalties": "Unknown",
        "identified_defenses": [],
        "red_flags": ["Case type could not be determined"],
        "green_flags": [],
        "case_strength": "weak",
        "recommendation": "needs_review",
        "recommendation_reasoning": (
            "Not enough information was gathered to classify the case. "
            "An attorney should follow up directly."
        ),
        "next_steps": ["Schedule a follow-up call with the potential client"],
    }
