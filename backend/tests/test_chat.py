"""Integration tests for the Assistant chat endpoints.

The whole chain runs for real — HTTP endpoint -> AgentChatService ->
the compiled LangGraph -> the agent's tools -> a second HTTP hop through
ASGITransport back into this very app -> the seeded test database. The
only double is the model: a scripted BaseChatModel replaying queued
AIMessages through the real graph (the same pattern as agent/tests), so
the interrupt/resume confirmation path is exercised exactly as in
production, provider aside.
"""

from __future__ import annotations

from collections.abc import AsyncIterator, Callable
from datetime import date
from typing import Any
from uuid import uuid4

import pytest
from httpx import ASGITransport, AsyncClient
from langchain_core.language_models import BaseChatModel
from langchain_core.messages import AIMessage, HumanMessage
from langchain_core.outputs import ChatGeneration, ChatResult
from pydantic import PrivateAttr

from app.main import app
from app.services.agent_chat import (
    AgentChatService,
    ChatLlmSettings,
    create_chat_service,
    get_chat_service,
)

# A fabricated provider config — the scripted model ignores it; what
# matters is that the service considers itself "configured".
TEST_LLM = ChatLlmSettings(api_key="test-key", base_url="https://llm.local/v1", model="test-model")


class ScriptedModel(BaseChatModel):
    """Test double: pops queued AIMessages, one per agent-node run.

    bind_tools is a no-op — the graph only needs the model to replay
    whatever tool_calls the test scripted. Every invocation is recorded
    so a test can assert on the conversation state the model received
    (the port of the double from agent/tests/conftest.py, invocations
    log included).
    """

    _responses: list[AIMessage] = PrivateAttr(default_factory=list)
    _invocations: list[list[Any]] = PrivateAttr(default_factory=list)

    def queue(self, message: AIMessage) -> None:
        self._responses.append(message)

    def bind_tools(self, tools: Any, **kwargs: Any) -> "ScriptedModel":
        return self

    @property
    def _llm_type(self) -> str:
        return "scripted-test-model"

    @property
    def invocations(self) -> list[list[Any]]:
        """What the graph sent the model on each agent-node run."""
        return self._invocations

    def _generate(
        self,
        messages: list[Any],
        stop: Any = None,
        run_manager: Any = None,
        **kwargs: Any,
    ) -> ChatResult:
        self._invocations.append(list(messages))
        response = self._responses.pop(0) if self._responses else AIMessage(content="(конец)")
        return ChatResult(generations=[ChatGeneration(message=response)])

    async def _agenerate(
        self,
        messages: list[Any],
        stop: Any = None,
        run_manager: Any = None,
        **kwargs: Any,
    ) -> ChatResult:
        return self._generate(messages, stop, run_manager, **kwargs)


def tool_call(name: str, args: dict[str, Any]) -> AIMessage:
    """One scripted write proposal with a stable tool-call id."""
    return AIMessage(
        content="",
        tool_calls=[{"name": name, "args": args, "id": f"call_{uuid4().hex[:8]}", "type": "tool_call"}],
    )


@pytest.fixture
def chat_service(client: AsyncClient) -> AsyncIterator[Callable[..., tuple[AgentChatService, ScriptedModel]]]:
    """Factory: queue the scripted answers, swap in a fresh service.

    A fresh service per call means a fresh in-memory checkpointer and a
    fresh pending-confirmation registry — tests never share conversation
    state. Returns the scripted model alongside the service so a test
    can assert on the conversation the model actually received. The
    tools' transport re-enters the same ASGI app the client fixture
    drives, so the seeded database and its dependency overrides are
    live for their calls too.
    """

    def make(*script: AIMessage) -> tuple[AgentChatService, ScriptedModel]:
        model = ScriptedModel()
        for message in script:
            model.queue(message)
        service = create_chat_service(
            settings=TEST_LLM,
            transport=ASGITransport(app=app),
            model=model,
        )
        assert service is not None  # settings are non-None by construction
        app.dependency_overrides[get_chat_service] = lambda: service
        return service, model

    yield make
    # The client fixture clears all overrides too; popping keeps the
    # intent explicit even if that ever changes.
    app.dependency_overrides.pop(get_chat_service, None)


@pytest.fixture
def unconfigured(client: AsyncClient) -> None:
    """The dependency answers None: no LLM key on this instance."""
    app.dependency_overrides[get_chat_service] = lambda: None


async def _new_thread(client: AsyncClient) -> str:
    resp = await client.post("/chat/reset", json={})
    assert resp.status_code == 200
    return resp.json()["thread_id"]


async def _posted_transactions(client: AsyncClient, description: str) -> list[dict[str, Any]]:
    """Rows the chain created, by the unique-ish description of the test."""
    resp = await client.get("/transactions", params={"search": description})
    assert resp.status_code == 200
    return resp.json()["items"]


async def test_status_unconfigured(client: AsyncClient, unconfigured: None) -> None:
    resp = await client.get("/chat/status")
    assert resp.status_code == 200
    assert resp.json() == {"configured": False, "model": None}


async def test_status_configured_shows_model(client: AsyncClient, chat_service: Any) -> None:
    # Installing the factory's service is all this needs — the scripted
    # answers never run.
    chat_service()
    resp = await client.get("/chat/status")
    assert resp.json() == {"configured": True, "model": "test-model"}


async def test_confirm_rejected_when_unconfigured(client: AsyncClient, unconfigured: None) -> None:
    resp = await client.post("/chat/confirm", json={"thread_id": uuid4().hex, "decisions": [True]})
    assert resp.status_code == 400
    assert "AURUM_AGENT_LLM_API_KEY" in resp.json()["detail"]


async def test_messages_rejected_when_unconfigured(client: AsyncClient, unconfigured: None) -> None:
    resp = await client.post("/chat/messages", json={"thread_id": uuid4().hex, "text": "привет"})
    assert resp.status_code == 400
    assert "AURUM_AGENT_LLM_API_KEY" in resp.json()["detail"]


async def test_plain_answer_roundtrip(client: AsyncClient, chat_service: Any) -> None:
    chat_service(AIMessage(content="Привет! Это тестовый ответ."))
    thread = await _new_thread(client)
    resp = await client.post("/chat/messages", json={"thread_id": thread, "text": "привет"})
    assert resp.status_code == 200
    assert resp.json() == {"reply": "Привет! Это тестовый ответ.", "pending": [], "error": None}


async def test_thread_remembers_previous_turns(client: AsyncClient, chat_service: Any) -> None:
    # Two HTTP turns on one thread: the in-memory checkpointer carries
    # the conversation across them, so the model must see turn one's
    # message (and only it — the system prompt rides per-invocation)
    # when turn two runs.
    _, model = chat_service(AIMessage(content="Первый ответ."), AIMessage(content="Второй ответ."))
    thread = await _new_thread(client)
    first = await client.post("/chat/messages", json={"thread_id": thread, "text": "первое сообщение"})
    assert first.json()["reply"] == "Первый ответ."
    second = await client.post(
        "/chat/messages", json={"thread_id": thread, "text": "второе сообщение"}
    )
    assert second.json()["reply"] == "Второй ответ."
    assert len(model.invocations) == 2
    seen = [m.content for m in model.invocations[1] if isinstance(m, HumanMessage)]
    assert seen == ["первое сообщение", "второе сообщение"]


async def test_write_proposal_returns_pending_card(
    client: AsyncClient, chat_service: Any, account_id: int
) -> None:
    description = "Кофе с круассаном"
    chat_service(
        tool_call(
            "create_transaction",
            {
                "account_id": account_id,
                "type": "expense",
                "amount": 340.0,
                "description": description,
                "date": date.today().isoformat(),
            },
        ),
        AIMessage(content="Записал."),
    )
    thread = await _new_thread(client)
    resp = await client.post("/chat/messages", json={"thread_id": thread, "text": "запиши"})
    body = resp.json()
    # The turn froze at the confirmation gate: no reply, one preview
    # card carrying exactly what the model wanted to send.
    assert body["reply"] == ""
    assert body["error"] is None
    assert len(body["pending"]) == 1
    card = body["pending"][0]
    assert card["name"] == "create_transaction"
    assert card["args"]["amount"] == 340.0
    assert card["args"]["description"] == description
    # The card names the account instead of its id: the graph's
    # prepare node resolved it through this same app.
    accounts = await client.get("/accounts")
    assert card["names"]["account_id"] == accounts.json()[0]["name"]
    # Nothing similar exists yet — no duplicate warning on the card.
    assert card["duplicates"] == []
    # ...and nothing in the database either: the gate held the write.
    assert await _posted_transactions(client, description) == []


async def test_pending_card_names_categories_and_tags(
    client: AsyncClient, chat_service: Any, account_id: int, categories: dict[str, dict[str, Any]]
) -> None:
    # A tag to reference in the proposal — tags are user-created, so
    # the test makes its own before the model can name it.
    tag_resp = await client.post("/tags", json={"name": "кофе"})
    assert tag_resp.status_code == 201
    tag_id = tag_resp.json()["id"]
    groceries = categories["Groceries"]
    description = "Кофе с книгой"
    chat_service(
        tool_call(
            "create_transaction",
            {
                "account_id": account_id,
                "type": "expense",
                "amount": 340.0,
                "description": description,
                "date": date.today().isoformat(),
                "category_id": groceries["id"],
                "tag_ids": [tag_id],
            },
        ),
        AIMessage(content="Записал."),
    )
    thread = await _new_thread(client)
    resp = await client.post("/chat/messages", json={"thread_id": thread, "text": "запиши"})
    card = resp.json()["pending"][0]
    # Every id argument the card can name, it names: the category by
    # its list entry, the tags as one joined label.
    assert card["names"]["category_id"] == "Groceries"
    assert card["names"]["tag_ids"] == "кофе"
    # Raw args are untouched — the write will still run on the ids.
    assert card["args"]["category_id"] == groceries["id"]
    assert card["args"]["tag_ids"] == [tag_id]
    assert await _posted_transactions(client, description) == []


async def test_approved_write_creates_transaction(
    client: AsyncClient, chat_service: Any, account_id: int
) -> None:
    description = "Продукты на неделю"
    chat_service(
        tool_call(
            "create_transaction",
            {
                "account_id": account_id,
                "type": "expense",
                "amount": 1500.0,
                "description": description,
                "date": date.today().isoformat(),
            },
        ),
        AIMessage(content="Записал: расход 1500.00, Продукты на неделю."),
    )
    thread = await _new_thread(client)
    await client.post("/chat/messages", json={"thread_id": thread, "text": "запиши"})
    resp = await client.post("/chat/confirm", json={"thread_id": thread, "decisions": [True]})
    body = resp.json()
    assert body["reply"] == "Записал: расход 1500.00, Продукты на неделю."
    assert body["pending"] == []
    assert body["error"] is None
    # The tool call went through the real app — the row is in the DB.
    rows = await _posted_transactions(client, description)
    assert len(rows) == 1
    assert float(rows[0]["amount"]) == 1500.0
    assert rows[0]["account_id"] == account_id


async def test_declined_write_creates_nothing(
    client: AsyncClient, chat_service: Any, account_id: int
) -> None:
    description = "Отменяемая покупка"
    chat_service(
        tool_call(
            "create_transaction",
            {
                "account_id": account_id,
                "type": "expense",
                "amount": 99.0,
                "description": description,
                "date": date.today().isoformat(),
            },
        ),
        AIMessage(content="Хорошо, не записываю. Что изменить?"),
    )
    thread = await _new_thread(client)
    await client.post("/chat/messages", json={"thread_id": thread, "text": "запиши"})
    resp = await client.post("/chat/confirm", json={"thread_id": thread, "decisions": [False]})
    assert resp.json()["reply"] == "Хорошо, не записываю. Что изменить?"
    assert await _posted_transactions(client, description) == []


async def test_malformed_decisions_decline_every_pending_call(
    client: AsyncClient, chat_service: Any, account_id: int
) -> None:
    # Two decisions for one previewed call: the service declines rather
    # than guessing which call the extra boolean belonged to — the same
    # safe default the graph applies to a malformed resume.
    description = "Несовпадающая пачка"
    chat_service(
        tool_call(
            "create_transaction",
            {
                "account_id": account_id,
                "type": "expense",
                "amount": 42.0,
                "description": description,
                "date": date.today().isoformat(),
            },
        ),
        AIMessage(content="Не записал — ответ был непонятен."),
    )
    thread = await _new_thread(client)
    await client.post("/chat/messages", json={"thread_id": thread, "text": "запиши"})
    resp = await client.post("/chat/confirm", json={"thread_id": thread, "decisions": [True, True]})
    assert resp.json()["error"] is None
    assert await _posted_transactions(client, description) == []


async def test_duplicate_warning_rides_the_pending_card(
    client: AsyncClient, chat_service: Any, account_id: int
) -> None:
    description = "Повторяющийся кофе"
    # The earlier row: same date, amount and description as the proposal.
    created = await client.post(
        "/transactions",
        json={
            "account_id": account_id,
            "type": "expense",
            "amount": 340.0,
            "description": description,
            "date": date.today().isoformat(),
        },
    )
    assert created.status_code == 201
    chat_service(
        tool_call(
            "create_transaction",
            {
                "account_id": account_id,
                "type": "expense",
                "amount": 340.0,
                "description": description,
                "date": date.today().isoformat(),
            },
        ),
        AIMessage(content="Подожди — похожая уже есть."),
    )
    thread = await _new_thread(client)
    resp = await client.post("/chat/messages", json={"thread_id": thread, "text": "запиши"})
    card = resp.json()["pending"][0]
    assert len(card["duplicates"]) == 1
    assert card["duplicates"][0]["id"] == created.json()["id"]
    assert card["duplicates"][0]["amount"] == "340.00"


async def test_free_text_blocked_while_confirmation_pending(
    client: AsyncClient, chat_service: Any, account_id: int
) -> None:
    chat_service(
        tool_call(
            "create_transaction",
            {
                "account_id": account_id,
                "type": "expense",
                "amount": 10.0,
                "description": "Зависшее подтверждение",
                "date": date.today().isoformat(),
            },
        ),
        AIMessage(content="Записал."),
    )
    thread = await _new_thread(client)
    await client.post("/chat/messages", json={"thread_id": thread, "text": "запиши"})
    # The user ignores the cards and types instead: the gate must not
    # let free text slip past an unanswered write.
    resp = await client.post("/chat/messages", json={"thread_id": thread, "text": "ещё вопрос"})
    body = resp.json()
    assert body["error"] == "confirm_required"
    assert body["pending"] == []
    assert body["reply"] == ""


async def test_confirm_without_pending_is_expired(client: AsyncClient, chat_service: Any) -> None:
    # Installing the configured service is the point of the factory call
    # here: without it the dependency stays the real unconfigured one.
    chat_service()
    # A restart wipes the checkpointer; a stale tab keeps its cards. Either
    # way there is nothing to resume — a code, not a stack trace.
    thread = await _new_thread(client)
    resp = await client.post("/chat/confirm", json={"thread_id": thread, "decisions": [True]})
    assert resp.json()["error"] == "confirm_expired"


async def test_reset_forgets_old_thread_pending(
    client: AsyncClient, chat_service: Any, account_id: int
) -> None:
    chat_service(
        tool_call(
            "create_transaction",
            {
                "account_id": account_id,
                "type": "expense",
                "amount": 20.0,
                "description": "Сброс перед подтверждением",
                "date": date.today().isoformat(),
            },
        ),
        AIMessage(content="Записал."),
    )
    thread = await _new_thread(client)
    await client.post("/chat/messages", json={"thread_id": thread, "text": "запиши"})
    resp = await client.post("/chat/reset", json={"thread_id": thread})
    new_thread = resp.json()["thread_id"]
    assert isinstance(new_thread, str) and new_thread != thread
    # The old thread's pending confirmation was dropped with the swap.
    resp = await client.post("/chat/confirm", json={"thread_id": thread, "decisions": [True]})
    assert resp.json()["error"] == "confirm_expired"
    # The new thread starts clean: a plain answer flows through it.
    chat_service(AIMessage(content="Начинаем с чистого листа."))
    resp = await client.post("/chat/messages", json={"thread_id": new_thread, "text": "привет"})
    assert resp.json()["reply"] == "Начинаем с чистого листа."


async def test_provider_failure_is_an_error_code_not_a_500(
    client: AsyncClient,
) -> None:
    class ExplodingModel(ScriptedModel):
        # The provider dying mid-turn must surface as a localized code,
        # with the service alive for the next turn.
        async def _agenerate(self, messages: Any, **kwargs: Any) -> Any:
            raise RuntimeError("provider exploded")

    service = create_chat_service(
        settings=TEST_LLM,
        transport=ASGITransport(app=app),
        model=ExplodingModel(),
    )
    assert service is not None
    app.dependency_overrides[get_chat_service] = lambda: service
    thread = await _new_thread(client)
    resp = await client.post("/chat/messages", json={"thread_id": thread, "text": "привет"})
    assert resp.status_code == 200
    body = resp.json()
    assert body["error"] == "turn_failed"
    assert body["reply"] == ""
    assert body["pending"] == []
    # The service survived: the next message is a fresh turn (it fails
    # the same scripted way, but as a turn — not a crashed endpoint).
    resp = await client.post("/chat/messages", json={"thread_id": thread, "text": "ещё раз"})
    assert resp.json()["error"] == "turn_failed"
