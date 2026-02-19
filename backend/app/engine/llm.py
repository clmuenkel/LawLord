import json
import logging

from openai import AsyncOpenAI

from ..config import settings

logger = logging.getLogger(__name__)

_client: AsyncOpenAI | None = None


def _get_client() -> AsyncOpenAI:
    global _client
    if _client is None:
        _client = AsyncOpenAI(api_key=settings.openai_api_key)
    return _client


async def chat_json(system_prompt: str, messages: list[dict]) -> dict:
    """Single LLM call that returns parsed JSON."""
    client = _get_client()
    response = await client.chat.completions.create(
        model=settings.openai_model,
        response_format={"type": "json_object"},
        messages=[
            {"role": "system", "content": system_prompt},
            *messages,
        ],
        temperature=0.3,
        max_tokens=1024,
    )
    raw = response.choices[0].message.content
    try:
        return json.loads(raw)
    except json.JSONDecodeError:
        logger.error("LLM returned invalid JSON: %s", raw[:500])
        return {
            "extracted_facts": {},
            "case_type": None,
            "case_type_confidence": 0.0,
            "response": "I'm sorry, I had trouble processing that. Could you repeat what you said?",
            "ready_for_report": False,
        }


async def chat_text(system_prompt: str, messages: list[dict]) -> str:
    """Single LLM call that returns plain text."""
    client = _get_client()
    response = await client.chat.completions.create(
        model=settings.openai_model,
        messages=[
            {"role": "system", "content": system_prompt},
            *messages,
        ],
        temperature=0.3,
        max_tokens=2048,
    )
    return response.choices[0].message.content
