from fastapi import APIRouter, HTTPException

from ..engine.intake_engine import engine
from ..schemas import (
    ChatMessageRequest,
    ChatMessageResponse,
    ReportRequest,
    StartSessionResponse,
)

router = APIRouter(prefix="/api/chat", tags=["chat"])


@router.post("/start", response_model=StartSessionResponse)
async def start_session():
    session_id, greeting = engine.start_session()
    return StartSessionResponse(session_id=session_id, message=greeting)


@router.post("/message", response_model=ChatMessageResponse)
async def send_message(req: ChatMessageRequest):
    if req.session_id not in engine.sessions:
        raise HTTPException(status_code=404, detail="Session not found")

    result = await engine.process_message(req.session_id, req.message)
    return ChatMessageResponse(
        message=result["message"],
        case_type=result.get("case_type"),
        ready_for_report=result.get("ready_for_report", False),
    )


@router.post("/report")
async def get_report(req: ReportRequest):
    report = await engine.get_report(req.session_id)
    if report is None:
        raise HTTPException(
            status_code=404,
            detail="No report available. Complete the intake first.",
        )
    return report
