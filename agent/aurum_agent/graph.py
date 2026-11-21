"""The LangGraph dialogue graph with terminal confirmations on writes.

One exchange walks agent -> (prepare -> confirm?) -> tools -> agent,
until the model answers without tool calls::

    START -> agent -> [no tool calls] -> END
                 |-> [read-only calls] -> tools -> agent
                 |-> [any write call]   -> prepare -> confirm -> tools -> agent

Preparation and confirmation are separate nodes on purpose: a resumed
interrupt re-executes its node from the top, so any work placed above
``interrupt()`` would run twice. ``prepare`` builds the preview payload
(enriched with resolved id-to-name labels and likely duplicates for
create_transaction) and COMPLETES — its result is checkpointed once.
``confirm`` does nothing before
``interrupt()`` except read that result, so a resume costs one state
read and zero API calls. The REPL renders the payload, the user
answers, and the decision comes back as a per-call list of booleans.

Declined calls are executed as a refusal ToolMessage instead of their
REST call, so the model cannot smuggle a write past the terminal: the
gate is in the graph, not in the prompt.

Invariant behind the ``[-1]`` reads: the agent node is the graph's
only entry point and always appends exactly one model message, so the
router and the prepare/confirm/tools nodes — all reachable only after
agent has run — always see at least that message, even when the graph
was invoked with an empty history.
"""

from __future__ import annotations

from collections.abc import Awaitable, Callable
from typing import Any

from langchain_core.language_models import BaseChatModel
from langchain_core.messages import AIMessage, SystemMessage, ToolMessage
from langgraph.checkpoint.base import BaseCheckpointSaver
from langgraph.graph import END, START, MessagesState, StateGraph
from langgraph.types import interrupt

from .tools import ToolBundle

# The refusal the model reads when the user declines a write. Worded
# as an instruction: the model must ask, not retry. English on
# purpose — everything the model reads is English (prompt, tool
# descriptions, backend messages); the model answers the user in the
# user's language, and raw tool results never reach the terminal.
DECLINED_TOOL_RESULT = (
    "The user declined this operation. Do not retry it or any variant "
    "without a new explicit request — ask what to change instead."
)

# Key of the pending-calls list inside the interrupt payload.
PENDING_KEY = "calls"


def final_reply(result: dict[str, Any]) -> str:
    """The user-facing text of a finished turn, ``""`` when there is none.

    Shared by both frontends over this graph (the terminal REPL and the
    backend's chat service): a tool-only turn cannot END the graph, but
    an empty answer must surface as an empty string, not as an empty
    markdown block. Some providers send block lists instead of plain
    strings; keep the text parts, drop the rest.
    """
    last = result["messages"][-1]
    if not isinstance(last, AIMessage) or not last.content:
        return ""
    content = last.content
    if not isinstance(content, str):
        content = " ".join(
            str(block.get("text", "")) for block in content if isinstance(block, dict)
        )
    return content.strip()

# Async callable returning likely duplicates for a transaction about
# to be created; bound to the API client by the caller (see main).
DuplicateChecker = Callable[..., Awaitable[list[dict[str, Any]]]]

# Async callable resolving the id arguments of a pending batch into
# display names (see naming.py); bound to the API client by the caller,
# the same injection pattern as DuplicateChecker.
NameResolver = Callable[..., Awaitable[dict[str, dict[str, str]]]]


class AgentState(MessagesState):
    """Dialogue history plus the confirm nodes' working channels.

    ``pending_calls`` is the preview payload built by prepare (write
    calls only, resolved names and duplicates included); ``approvals``
    maps tool_call ids to the user's booleans after confirm. Both are
    cleared by the tools node — reads never appear here, they don't
    need a gate.
    """

    pending_calls: list[dict[str, Any]]
    approvals: dict[str, bool]


def build_agent_graph(
    model: BaseChatModel,
    bundle: ToolBundle,
    *,
    system_prompt: str,
    duplicate_checker: DuplicateChecker,
    name_resolver: NameResolver,
    checkpointer: BaseCheckpointSaver,
) -> Any:
    """Assemble the compiled graph from the injected dependencies.

    ``duplicate_checker`` is ``find_duplicates`` bound to the API client
    (or a stub in tests) — the graph itself stays network-light. The
    same for ``name_resolver``: ``find_names`` bound to the client,
    turning the id arguments of the pending batch into display names
    for the preview (see naming.py). The checkpointer is required, not
    optional: ``interrupt()`` cannot freeze and resume a confirmation
    without one.
    """
    bound_model = model.bind_tools(bundle.tools)
    tools_by_name = {tool.name: tool for tool in bundle.tools}
    write_names = set(bundle.write_names)
    system_message = SystemMessage(content=system_prompt)

    async def agent_node(state: AgentState) -> dict[str, Any]:
        # The system prompt is prepended per invocation instead of
        # living in the history: it stays out of the checkpoints and
        # cannot drift mid-session.
        response = await bound_model.ainvoke([system_message, *state["messages"]])
        return {"messages": [response]}

    async def prepare_node(state: AgentState) -> dict[str, Any]:
        """Build the preview payload; runs exactly once per batch.

        Completing this node checkpoints the pending list, so the
        duplicate check and the id-to-name resolution (API calls) are
        never repeated on resume.
        """
        last = state["messages"][-1]
        write_calls = [call for call in last.tool_calls if call["name"] in write_names]
        resolved_names = await name_resolver(write_calls)
        pending: list[dict[str, Any]] = []
        for call in write_calls:
            entry: dict[str, Any] = {
                "id": call["id"],
                "name": call["name"],
                "args": call["args"],
            }
            # Display names for the id arguments, resolved once above;
            # keys without a name render as raw ids (see naming.py).
            names = resolved_names.get(call["id"])
            if names:
                entry["names"] = names
            if call["name"] == "create_transaction":
                # Advisory only: a failing duplicate check degrades to
                # [] inside find_duplicates, so this can only enrich
                # the preview, never block it.
                entry["duplicates"] = await duplicate_checker(
                    date=call["args"].get("date"),
                    amount=call["args"].get("amount"),
                    description=call["args"].get("description"),
                )
            pending.append(entry)
        return {"pending_calls": pending}

    async def confirm_node(state: AgentState) -> dict[str, Any]:
        # Zero work above the interrupt: a resumed run re-executes this
        # node from the top, and everything expensive lives in
        # prepare_node, whose checkpointed result is only read here.
        pending = state.get("pending_calls", [])

        # Freeze here: the first run raises the interrupt to the REPL;
        # the resumed run gets the user's answer as the return value.
        decisions = interrupt({PENDING_KEY: pending})

        # A malformed resume (not a list, wrong length) declines every
        # pending call rather than guessing what was approved.
        if not isinstance(decisions, list) or len(decisions) != len(pending):
            decisions = [False] * len(pending)

        approvals: dict[str, bool] = {}
        for entry, decision in zip(pending, decisions):
            approvals[entry["id"]] = bool(decision)
        return {"approvals": approvals}

    async def tools_node(state: AgentState) -> dict[str, Any]:
        last = state["messages"][-1]
        approvals = state.get("approvals", {})
        results: list[ToolMessage] = []
        for call in last.tool_calls:
            tool = tools_by_name.get(call["name"])
            if tool is None:
                results.append(
                    ToolMessage(
                        content=f"Unknown tool: {call['name']}",
                        tool_call_id=call["id"],
                    )
                )
                continue
            if call["name"] in write_names and not approvals.get(call["id"], False):
                results.append(
                    ToolMessage(content=DECLINED_TOOL_RESULT, tool_call_id=call["id"])
                )
                continue
            try:
                observation = await tool.ainvoke(call["args"])
            except Exception as error:  # noqa: BLE001 — one tool failing must not kill the dialogue
                results.append(
                    ToolMessage(
                        content=f"Tool execution failed: {error!r}",
                        tool_call_id=call["id"],
                    )
                )
                continue
            results.append(ToolMessage(content=str(observation), tool_call_id=call["id"]))
        # Approvals are single-use: model-issued ids never repeat, but
        # clearing both working channels keeps the state honest for the
        # next turn.
        return {"messages": results, "approvals": {}, "pending_calls": []}

    def route_after_agent(state: AgentState) -> str:
        last = state["messages"][-1]
        if not getattr(last, "tool_calls", None):
            return END
        if any(call["name"] in write_names for call in last.tool_calls):
            return "prepare"
        return "tools"

    graph = StateGraph(AgentState)
    graph.add_node("agent", agent_node)
    graph.add_node("prepare", prepare_node)
    graph.add_node("confirm", confirm_node)
    graph.add_node("tools", tools_node)
    graph.add_edge(START, "agent")
    graph.add_conditional_edges("agent", route_after_agent, ["tools", "prepare", END])
    graph.add_edge("prepare", "confirm")
    graph.add_edge("confirm", "tools")
    graph.add_edge("tools", "agent")
    return graph.compile(checkpointer=checkpointer)
