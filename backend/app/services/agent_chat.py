"""The backend-side chat over the agent's LangGraph dialogue graph.

The terminal ``aurum-agent`` CLI and the web UI's Assistant page are two
frontends over one brain: this service wraps the same compiled graph
(``aurum_agent.graph``) with its 15 REST tools, duplicate warnings and the
interrupt-based confirmation gate. The REPL reads y/n from a terminal;
here the pending payload travels to the browser, the button decisions
travel back as a list of per-call booleans, and the graph — the gate
itself — cannot tell the difference.

Lifecycle: one service per process, built lazily on first use (an
instance without ``AURUM_AGENT_LLM_API_KEY`` never builds anything and
answers "unconfigured"). The checkpointer is in-memory, so a container
restart forgets every conversation — the same trade-off the terminal
process makes; a persistent checkpointer is a separate follow-up.
"""

from __future__ import annotations

import asyncio
import logging
import os
from dataclasses import dataclass, field
from datetime import date
from functools import partial
from typing import Any
from uuid import uuid4

import httpx
from langchain_core.language_models import BaseChatModel
from langchain_core.messages import HumanMessage
from langchain_openai import ChatOpenAI
from langgraph.checkpoint.memory import InMemorySaver
from langgraph.types import Command

from aurum_agent.api_client import SETTINGS_PATH, AurumApiError, AurumClient
from aurum_agent.config import DEFAULT_LLM_BASE_URL, DEFAULT_LLM_MODEL, AgentConfig
from aurum_agent.dedup import find_duplicates
from aurum_agent.graph import PENDING_KEY, build_agent_graph, final_reply
from aurum_agent.naming import find_names
from aurum_agent.prompts import build_system_prompt
from aurum_agent.tools import build_tools

logger = logging.getLogger(__name__)

# Inside the backend container uvicorn listens on 8000 (the Dockerfile
# CMD), and the graph's tools are just another REST client of this very
# app. Loopback, not nginx: no basic auth in the path, no TLS, no
# published port — the container talks only to itself.
LOOPBACK_API_URL = "http://127.0.0.1:8000/api"

# Machine-readable turn failures. The browser localizes them (the page
# is bilingual); raw exception text stays in the server log, never in
# the API response — a provider error can quote request internals.
ERROR_CONFIRM_REQUIRED = "confirm_required"  # free text while a write awaits its decision
ERROR_STALE_CONFIRM = "confirm_expired"  # decision arrived with nothing pending (restart, stale tab)
ERROR_TURN_FAILED = "turn_failed"  # the graph blew up; the log has the details


@dataclass(frozen=True)
class ChatLlmSettings:
    """The three shared AURUM_AGENT_LLM_* values; the key lives only here."""

    api_key: str
    base_url: str
    model: str


@dataclass
class ChatTurn:
    """One exchange's outcome: an answer, a confirmation, or a failure.

    At most one of the three is meaningful at a time: a pending write
    freezes the thread (no reply), a finished turn clears the pending
    list, and an error carries a code for the browser to localize.
    """

    reply: str = ""
    pending: list[dict[str, Any]] = field(default_factory=list)
    error: str | None = None


def chat_llm_settings() -> ChatLlmSettings | None:
    """LLM settings from the environment, or None when unconfigured.

    Deliberately not ``aurum_agent.config.load_config``: that function is
    the terminal's — it demands the key (a hard exit there, a quiet
    "page shows a setup hint" here), discovers ``.env`` files by walking
    up from cwd, and carries the nginx URL + basic-auth pair the web
    chat never uses. Only the three shared LLM values are read; the
    defaults come from the agent package so both frontends agree.
    """
    # The one hard requirement: without a key there is nothing to talk to.
    api_key = (os.getenv("AURUM_AGENT_LLM_API_KEY") or "").strip()
    if not api_key:
        return None
    # ``os.getenv(name, default)`` returns a blank string when the
    # variable is set but empty (a typical ``VAR=`` line in .env), so
    # defaults are applied with ``or`` instead — same rule as the agent.
    return ChatLlmSettings(
        api_key=api_key,
        base_url=(os.getenv("AURUM_AGENT_LLM_BASE_URL") or DEFAULT_LLM_BASE_URL).strip(),
        model=(os.getenv("AURUM_AGENT_LLM_MODEL") or DEFAULT_LLM_MODEL).strip(),
    )


class AgentChatService:
    """Conversations of one instance: graph wiring plus pending-confirm registry."""

    def __init__(
        self,
        *,
        config: AgentConfig,
        model: BaseChatModel,
        transport: httpx.AsyncBaseTransport | None = None,
    ) -> None:
        # The tools talk to this very app over plain HTTP — deliberately
        # the same AurumClient the terminal agent uses (its GET-only
        # retry rule and its model-facing error formatting included), so
        # agent behaviour does not fork between frontends. In production
        # the transport is None and httpx dials the loopback uvicorn; in
        # tests it is an ASGITransport around the app itself.
        self._client = AurumClient(config, transport=transport)
        self._config = config
        self._model = model
        self._bundle = build_tools(self._client)
        # One checkpointer for every thread: interrupt()/resume() cannot
        # work without one, and a single process-wide instance keeps all
        # conversations alive together (and dies together on restart).
        self._checkpointer = InMemorySaver()
        self._graph: Any = None
        self._graph_day = ""
        # Threads whose confirmation payload was sent to the browser and
        # now wait for decisions — also the guard that keeps free text
        # from sneaking past a pending write.
        self._awaiting: dict[str, list[dict[str, Any]]] = {}
        # One turn at a time: a single user's stray double-click must not
        # race the checkpointer.
        self._turn_lock = asyncio.Lock()

    async def aclose(self) -> None:
        await self._client.aclose()

    @property
    def model_name(self) -> str:
        """The configured model id, shown on the Assistant page's status."""
        return self._config.llm_model

    def new_thread_id(self) -> str:
        """A fresh conversation key; the old thread's checkpoint is left behind.

        The REPL swaps its uuid the same way on /reset — dropping the
        old thread's checkpoint from the in-memory saver would walk
        langgraph internals for a few KB of RAM, which is not worth it.
        """
        return uuid4().hex

    def drop_thread(self, thread_id: str) -> None:
        """Forget a thread's pending confirmation (the old thread of a reset)."""
        self._awaiting.pop(thread_id, None)

    async def _current_graph(self) -> Any:
        """The compiled graph, rebuilt when the calendar day rolls over.

        The system prompt carries today's date (the model resolves words
        like "yesterday" against it) and the display currency; a
        terminal process is short-lived so ``__main__`` builds both once,
        but a backend container lives for weeks — a stale "today" would
        send the user's "вчера" to the wrong date. Rebuilding is object
        wiring only, and the checkpointer is reused, so live
        conversations survive the swap.
        """
        today = date.today().isoformat()
        if self._graph is not None and self._graph_day == today:
            return self._graph
        currency = "USD"
        try:
            payload = await self._client.request("GET", SETTINGS_PATH)
        except AurumApiError:
            # A failed settings read degrades to the backend's default
            # currency — a label for the model, not worth dying for
            # (the same rule as the terminal's startup).
            payload = None
        if isinstance(payload, dict):
            currency = str(payload.get("currency") or "USD")
        self._graph = build_agent_graph(
            self._model,
            self._bundle,
            system_prompt=build_system_prompt(today=today, currency=currency),
            # The duplicate check and the id-to-name resolution ride the
            # same client and inherit its "degrade, never block"
            # failure behavior — a failing lookup only costs the card
            # its friendly labels, never the confirmation itself.
            duplicate_checker=partial(find_duplicates, self._client),
            name_resolver=partial(find_names, self._client),
            checkpointer=self._checkpointer,
        )
        self._graph_day = today
        return self._graph

    async def send_message(self, thread_id: str, text: str) -> ChatTurn:
        if thread_id in self._awaiting:
            # The terminal cannot do this (its prompt is a y/n question
            # at that point); the page must not either — buttons first.
            return ChatTurn(error=ERROR_CONFIRM_REQUIRED)
        return await self._run(
            thread_id, {"messages": [HumanMessage(content=text)]}
        )

    async def confirm(self, thread_id: str, decisions: list[bool]) -> ChatTurn:
        pending = self._awaiting.get(thread_id)
        if pending is None:
            # A restart wipes the checkpointer; a stale tab keeps its
            # cards. Either way there is nothing to resume.
            return ChatTurn(error=ERROR_STALE_CONFIRM)
        # A malformed batch declines every pending call rather than
        # guessing what was approved — the same rule the graph itself
        # applies to a malformed resume payload.
        if not isinstance(decisions, list) or len(decisions) != len(pending):
            decisions = [False] * len(pending)
        return await self._run(thread_id, Command(resume=decisions))

    async def _run(self, thread_id: str, turn_input: Any) -> ChatTurn:
        graph = await self._current_graph()
        config = {"configurable": {"thread_id": thread_id}}
        async with self._turn_lock:
            try:
                result = await graph.ainvoke(turn_input, config)
            except Exception as error:  # noqa: BLE001 — one bad turn must not kill the service
                # Same rule as the REPL: report, keep the service alive,
                # let the user retry or start a new thread. The raw error
                # goes to the log; the browser gets a code it can render
                # in the user's language. The pending registry entry is
                # dropped too — a half-run turn may have left the thread
                # checkpoint in a shape the provider rejects, and the
                # honest way out is a new thread, not a broken gate.
                logger.warning("agent chat turn failed on thread %s: %r", thread_id, error)
                self._awaiting.pop(thread_id, None)
                return ChatTurn(error=ERROR_TURN_FAILED)
        if "__interrupt__" in result:
            # The confirmation gate froze before any write ran: the
            # payload is what the UI renders as cards, and the thread
            # stays frozen until the same number of decisions returns.
            pending = result["__interrupt__"][0].value[PENDING_KEY]
            self._awaiting[thread_id] = pending
            return ChatTurn(pending=pending)
        self._awaiting.pop(thread_id, None)
        return ChatTurn(reply=final_reply(result))


def create_chat_service(
    *,
    settings: ChatLlmSettings | None,
    transport: httpx.AsyncBaseTransport | None = None,
    model: BaseChatModel | None = None,
) -> AgentChatService | None:
    """Assemble the service; None when the instance has no LLM key.

    ``transport`` is the tests' first seam (an ASGITransport around the
    app makes the tools' HTTP calls hit the real API in-process);
    ``model`` is the second (a scripted BaseChatModel replaces
    ChatOpenAI so the whole interrupt/resume path runs without a
    provider).
    """
    if settings is None:
        return None
    config = AgentConfig(
        api_url=LOOPBACK_API_URL,
        # Basic auth is a terminal-agent concern (it enters through
        # nginx); the loopback call never meets it, so the pair is
        # explicitly empty rather than left to whoever reads env later.
        api_user=None,
        api_password=None,
        llm_base_url=settings.base_url,
        llm_model=settings.model,
        llm_api_key=settings.api_key,
    )
    return AgentChatService(
        config=config,
        transport=transport,
        # Any OpenAI-compatible endpoint works (see agent/README.md):
        # base URL and key come from the environment, never from code.
        model=model
        or ChatOpenAI(
            model=settings.model,
            api_key=settings.api_key,
            base_url=settings.base_url,
        ),
    )


# The process-wide singleton. The graph wiring (its HTTP client, its
# checkpointer, its conversations) is process state: a second build would
# orphan every thread, so the factory runs at most once per boot.
_chat_service: AgentChatService | None = None
_chat_service_built = False


def get_chat_service() -> AgentChatService | None:
    """The process-wide service, or None when no LLM key is configured."""
    global _chat_service, _chat_service_built
    if not _chat_service_built:
        _chat_service = create_chat_service(settings=chat_llm_settings())
        _chat_service_built = True
    return _chat_service


async def close_chat_service() -> None:
    """Release the service's HTTP client on app shutdown, if one was built."""
    global _chat_service, _chat_service_built
    if _chat_service is not None:
        await _chat_service.aclose()
    _chat_service = None
    _chat_service_built = False
