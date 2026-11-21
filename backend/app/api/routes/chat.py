"""The Assistant page's endpoints: thin transport over the chat service.

Everything heavy — the dialogue graph, its tools, the confirmation
gate, the LLM wiring — lives in app/services/agent_chat.py; these
routes only translate between HTTP and per-thread conversations. A
request carries the thread id (an opaque key the browser keeps in
localStorage); a turn's answer is either text, or a pending-write
payload the page renders as confirmation cards, or an error code the
page localizes.
"""

from uuid import uuid4

from fastapi import APIRouter, Depends, HTTPException

from app.schemas.chat import (
    ChatConfirmIn,
    ChatMessageIn,
    ChatResetIn,
    ChatResetOut,
    ChatStatusOut,
    ChatTurnOut,
)
from app.services.agent_chat import AgentChatService, get_chat_service

router = APIRouter(prefix="/chat", tags=["chat"])

# English like the rest of the backend's HTTP errors. The page normally
# shows its own localized hint based on GET /chat/status, so this text is
# the fallback for non-UI clients (curl, scripts).
UNCONFIGURED_DETAIL = (
    "Assistant chat is not configured — set AURUM_AGENT_LLM_API_KEY in .env "
    "and restart the backend container"
)


async def require_chat_service(
    service: AgentChatService | None = Depends(get_chat_service),
) -> AgentChatService:
    """Turn "no LLM key on this instance" into a 400, not a stack trace.

    A configuration choice, not an outage — the crypto service 400s a
    missing CoinGecko key the same way.
    """
    if service is None:
        raise HTTPException(status_code=400, detail=UNCONFIGURED_DETAIL)
    return service


@router.get("/status", response_model=ChatStatusOut)
async def chat_status(
    service: AgentChatService | None = Depends(get_chat_service),
) -> ChatStatusOut:
    """The page's first call: it decides between the chat UI and the setup
    hint without a request that would 400. The model id is display-only —
    the key never travels."""
    if service is None:
        return ChatStatusOut(configured=False, model=None)
    return ChatStatusOut(configured=True, model=service.model_name)


@router.post("/messages", response_model=ChatTurnOut)
async def send_message(
    payload: ChatMessageIn,
    service: AgentChatService = Depends(require_chat_service),
) -> ChatTurnOut:
    turn = await service.send_message(payload.thread_id, payload.text)
    return ChatTurnOut(reply=turn.reply, pending=turn.pending, error=turn.error)


@router.post("/confirm", response_model=ChatTurnOut)
async def confirm_pending(
    payload: ChatConfirmIn,
    service: AgentChatService = Depends(require_chat_service),
) -> ChatTurnOut:
    turn = await service.confirm(payload.thread_id, payload.decisions)
    return ChatTurnOut(reply=turn.reply, pending=turn.pending, error=turn.error)


@router.post("/reset", response_model=ChatResetOut)
async def reset_thread(
    payload: ChatResetIn,
    service: AgentChatService | None = Depends(get_chat_service),
) -> ChatResetOut:
    """A fresh thread id — works even unconfigured, so the page can hand
    one out before any key exists. The old thread's pending confirmation
    (if any) is dropped, so a late "confirm" click cannot land on it.
    """
    if service is not None:
        if payload.thread_id:
            service.drop_thread(payload.thread_id)
        return ChatResetOut(thread_id=service.new_thread_id())
    # Unconfigured: nothing to drop (no service ever confirmed anything),
    # a fresh opaque key is all the caller needs.
    return ChatResetOut(thread_id=uuid4().hex)
