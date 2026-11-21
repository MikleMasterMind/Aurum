from typing import Any

from pydantic import BaseModel, Field


class ChatMessageIn(BaseModel):
    """One user message into an existing conversation thread."""

    # uuid4().hex is 32 chars; the bound is hygiene, not a real limit —
    # the id becomes a checkpointer key and a registry key, and an
    # unbounded string would accept either as a DoS-shaped payload.
    thread_id: str = Field(min_length=1, max_length=64)
    text: str = Field(min_length=1, max_length=4000)


class ChatConfirmIn(BaseModel):
    """The user's answer to a pending write: one boolean per previewed call,
    in the order the pending list was returned in."""

    thread_id: str = Field(min_length=1, max_length=64)
    decisions: list[bool]


class ChatResetIn(BaseModel):
    """The old thread id is optional — passing it lets the service forget
    that thread's pending confirmation along with the swap."""

    thread_id: str | None = Field(default=None, max_length=64)


class ChatPendingCallOut(BaseModel):
    """One write the model proposed and the graph froze before running.

    Rendered as a confirmation card: ``name`` plus raw ``args`` (exactly
    what would be sent — deliberately no id-to-name resolution, same
    honesty rule as the terminal preview), with ``duplicates`` advisory
    for create_transaction.
    """

    id: str
    name: str
    args: dict[str, Any]
    duplicates: list[dict[str, Any]] | None = None


class ChatTurnOut(BaseModel):
    """Exactly one of the three is meaningful per turn: an answer, a
    confirmation request, or an error code the page localizes."""

    reply: str = ""
    pending: list[ChatPendingCallOut] = []
    error: str | None = None


class ChatStatusOut(BaseModel):
    """The page's first call: configured=false shows the setup hint instead
    of a chat; ``model`` is display-only, the key never travels."""

    configured: bool
    model: str | None = None


class ChatResetOut(BaseModel):
    thread_id: str
