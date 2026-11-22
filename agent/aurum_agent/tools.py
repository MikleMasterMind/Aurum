"""LangChain tools over the Aurum REST API: accounts, categories, tags, transactions, budgets, goals, recurring, analytics, financial advice.

Each tool is a thin, typed wrapper around one endpoint: it compacts the
response into model-friendly JSON, or turns an ``AurumApiError`` into a
plain-text error string the model can read and react to. The tools
themselves know nothing about confirmations — that is the graph's job
(see graph.py): any name in ``ToolBundle.write_names`` is routed through
a terminal "yes" before its REST call is allowed to run.

The consultant tools (net worth, budget suggestions, savings forecast)
are read-only like the analytics ones, but two of them compute in
Python over fetched data instead of passing one endpoint through: the
averages and the month arithmetic are exact math the model must never
redo by hand.

Scope notes: transaction splits are deliberately not exposed, and
neither is ``DELETE /tags/{id}`` — tags are only created and listed
here, because the agent helps tag transactions, not manage the tag
dictionary itself.
"""

from __future__ import annotations

import json
from collections.abc import Awaitable, Callable
from dataclasses import dataclass
from datetime import date, timedelta
from decimal import ROUND_CEILING, Decimal
from typing import Any

from langchain_core.tools import BaseTool, StructuredTool

from .api_client import AurumApiError, AurumClient

# REST endpoints in one place, matching DOCS.md. Dynamic segments are
# appended at call sites: f"{PATH_ACCOUNTS}/{account_id}".
PATH_ACCOUNTS = "/accounts"
PATH_CATEGORIES = "/categories"
PATH_TAGS = "/tags"
PATH_TRANSACTIONS = "/transactions"
PATH_BUDGETS = "/budgets"
PATH_GOALS = "/goals"
PATH_RECURRING = "/recurring"
# Read-only aggregations behind the UI's charts.
PATH_DASHBOARD = "/dashboard/summary"
PATH_CASH_FLOW = "/cash-flow"
PATH_CATEGORY_SPENDING = "/reports/category-spending"
PATH_CATEGORY_RANKING = "/reports/category-ranking"
PATH_TAG_RANKING = "/reports/tag-ranking"
PATH_TAG_SPENDING = "/reports/tag-spending"
PATH_INSIGHTS = "/insights/alerts"
PATH_ADVICE = "/advice"
# The consultant's capital view: cash from accounts plus every asset.
PATH_NET_WORTH = "/net-worth/summary"

# --- Financial advisor math (deterministic, never the model's job) ---
# The resolution every money answer is quantized to.
CENT = Decimal("0.01")
# A suggested budget limit is the category's monthly average rounded UP
# to this step — a limit below the average starts life over budget.
LIMIT_STEP = Decimal("10")
# The default history window for suggest_budgets' averaging.
DEFAULT_LOOKBACK_MONTHS = 6
# The hard cap on that window — averaging over years of old habits
# would blur a recent lifestyle change into the suggestion.
MAX_LOOKBACK_MONTHS = 24
# The cash-flow window behind savings_forecast's use_average_net mode.
AVERAGE_NET_WINDOW_MONTHS = 6


@dataclass(frozen=True)
class ToolBundle:
    """The agent's toolset plus the names that mutate data.

    ``write_names`` is the source of truth for the confirmation router —
    filled in right next to each tool definition and pinned by tests,
    so the registry and the router stay in lockstep.
    """

    tools: list[BaseTool]
    write_names: frozenset[str]


def _dumps(value: Any) -> str:
    """JSON for the model's eyes: readable separators, real unicode."""
    return json.dumps(value, ensure_ascii=False)


def _omit_none(**fields: Any) -> dict[str, Any]:
    """Keep only provided fields — ``None`` means "leave unchanged".

    ``False`` is a real value (e.g. ``is_archived=false`` restores an
    archived account), so only ``None`` is dropped.
    """
    return {name: value for name, value in fields.items() if value is not None}


def _params_without_blanks(params: dict[str, Any]) -> dict[str, Any]:
    """Drop blank string filters — the backend would 422 on them.

    A model-issued "" or whitespace-only value (usually a date the
    model left empty) is "not provided", not a filter to send.
    """
    return {
        name: value
        for name, value in params.items()
        if not (isinstance(value, str) and not value.strip())
    }


def _make_caller(client: AurumClient) -> Callable[..., Awaitable[str]]:
    """One HTTP call per tool: errors become text the model can act on."""

    async def call(
        method: str,
        path: str,
        *,
        params: dict[str, Any] | None = None,
        body: dict[str, Any] | None = None,
        compact: Callable[[Any], Any] | None = None,
    ) -> str:
        # Centralized PATCH guard: an empty partial-update body is always
        # a modeling mistake, and the backend would reject it with a less
        # helpful message than this. Lives here so every update tool —
        # including the transaction ones added later — gets it for free.
        if method == "PATCH" and body is not None and not body:
            return "Nothing to update: pass at least one field to change."
        try:
            payload = await client.request(method, path, params=params, json=body)
        except AurumApiError as error:
            # Not re-raised on purpose: as a tool result, the backend's
            # own message (e.g. "Category 'Salary' is a income category…")
            # lets the model correct itself on the next step. English on
            # purpose: this is model-facing text — the system prompt's
            # rule 5 keys on the "API error" prefix.
            return f"API error (HTTP {error.status}): {error.detail}"
        if compact is not None:
            payload = compact(payload)
        if payload is None:
            # Deletes answer 204 with no body — "null" would only confuse.
            return "OK: done (204 No Content)"
        return _dumps(payload)

    return call


def _compact_account(account: dict[str, Any]) -> dict[str, Any]:
    """Fields the model needs to pick an account; balance is derived."""
    return {
        "id": account.get("id"),
        "name": account.get("name"),
        "type": account.get("type"),
        "currency": account.get("currency"),
        "balance": account.get("balance"),
        "is_archived": account.get("is_archived"),
    }


def _compact_category(category: dict[str, Any]) -> dict[str, Any]:
    """Fields the model needs to pick or build a category."""
    return {
        "id": category.get("id"),
        "name": category.get("name"),
        "kind": category.get("kind"),
        "parent_id": category.get("parent_id"),
        "is_default": category.get("is_default"),
    }


def _compact_transaction(transaction: dict[str, Any]) -> dict[str, Any]:
    """Fields the model needs to discuss a transaction in user terms.

    Nested account/category objects are flattened to ``*_name`` so the
    model can speak human language without extra lookups. Splits ride
    along when present (empty list on a normal single-category row).
    transfer_account_name is deliberately NOT resolved here — it would
    cost a second request per row; the model can name the destination
    via list_accounts when the user asks about a transfer.
    """
    account = transaction.get("account") or {}
    category = transaction.get("category") or {}
    splits = transaction.get("splits") or []
    return {
        "id": transaction.get("id"),
        "type": transaction.get("type"),
        "amount": transaction.get("amount"),
        "date": transaction.get("date"),
        "description": transaction.get("description"),
        "merchant": transaction.get("merchant"),
        "notes": transaction.get("notes"),
        "account_id": transaction.get("account_id"),
        "account_name": account.get("name"),
        "category_id": category.get("id"),
        "category_name": category.get("name"),
        "transfer_account_id": transaction.get("transfer_account_id"),
        "tags": [tag.get("name") for tag in transaction.get("tags", [])],
        "splits": [
            {
                "category_name": (split.get("category") or {}).get("name"),
                "amount": split.get("amount"),
                "note": split.get("note"),
            }
            for split in splits
        ],
    }


def _compact_budget(budget: dict[str, Any]) -> dict[str, Any]:
    """Fields the model needs to discuss a budget; color/icon are UI-only."""
    return {
        "id": budget.get("id"),
        "category_id": budget.get("category_id"),
        "category_name": budget.get("category_name"),
        "monthly_limit": budget.get("monthly_limit"),
    }


def _compact_budget_status_item(item: dict[str, Any]) -> dict[str, Any]:
    """One budget-vs-actual row without the UI-only color/icon fields."""
    return {
        "budget_id": item.get("budget_id"),
        "category_id": item.get("category_id"),
        "category_name": item.get("category_name"),
        "monthly_limit": item.get("monthly_limit"),
        "spent": item.get("spent"),
        "remaining": item.get("remaining"),
        "percent": item.get("percent"),
        "is_over_budget": item.get("is_over_budget"),
    }


def _compact_category_slice(item: dict[str, Any]) -> dict[str, Any]:
    """One category's share of a dashboard/ranking payload.

    color/icon are UI-only. children ride along only when the slice's
    spend came from more than one distinct category (subcategory
    rollup) — that is where a parent's number actually comes from.
    """
    compact: dict[str, Any] = {
        "category_id": item.get("category_id"),
        "name": item.get("name"),
        "amount": item.get("amount"),
        "percent": item.get("percent"),
    }
    if "transaction_count" in item:
        # Dashboard slices don't carry it, ranking items do — never
        # invent a null where the source had nothing to say.
        compact["transaction_count"] = item.get("transaction_count")
    children = item.get("children") or []
    if children:
        compact["children"] = [
            {
                "category_id": child.get("category_id"),
                "name": child.get("name"),
                "amount": child.get("amount"),
            }
            for child in children
        ]
    return compact


def _compact_dashboard_summary(payload: dict[str, Any]) -> dict[str, Any]:
    """A month's headline numbers; slices via ``_compact_category_slice``."""
    return {
        "year": payload.get("year"),
        "month": payload.get("month"),
        "real_income": payload.get("real_income"),
        "spent": payload.get("spent"),
        "net": payload.get("net"),
        "transferred_out": payload.get("transferred_out"),
        "spending_by_category": [
            _compact_category_slice(item) for item in payload.get("spending_by_category", [])
        ],
    }


def _compact_category_spending(payload: dict[str, Any]) -> dict[str, Any]:
    """One category's spend-over-time report; color/icon are UI-only."""
    return {
        "category_id": payload.get("category_id"),
        "category_name": payload.get("category_name"),
        "start_date": payload.get("start_date"),
        "end_date": payload.get("end_date"),
        "total_amount": payload.get("total_amount"),
        "transaction_count": payload.get("transaction_count"),
        "average_per_month": payload.get("average_per_month"),
        "series": payload.get("series", []),
    }


def _compact_category_ranking(payload: dict[str, Any]) -> dict[str, Any]:
    """All categories ranked by period spend; items via ``_compact_category_slice``."""
    return {
        "start_date": payload.get("start_date"),
        "end_date": payload.get("end_date"),
        "total_amount": payload.get("total_amount"),
        "items": [_compact_category_slice(item) for item in payload.get("items", [])],
    }


def _compact_tag_ranking_item(item: dict[str, Any]) -> dict[str, Any]:
    """One tag's ranked total with its per-category breakdown."""
    return {
        "tag_id": item.get("tag_id"),
        "name": item.get("name"),
        "amount": item.get("amount"),
        "percent": item.get("percent"),
        "transaction_count": item.get("transaction_count"),
        "categories": [
            {
                "category_id": category.get("category_id"),
                "name": category.get("name"),
                "amount": category.get("amount"),
            }
            for category in item.get("categories", [])
        ],
    }


def _compact_tag_ranking(payload: dict[str, Any]) -> dict[str, Any]:
    """Tags ranked by period spend; ``tagged_amount`` stays — with
    ``total_amount`` it says how much of the period the report covers."""
    return {
        "start_date": payload.get("start_date"),
        "end_date": payload.get("end_date"),
        "total_amount": payload.get("total_amount"),
        "tagged_amount": payload.get("tagged_amount"),
        "items": [_compact_tag_ranking_item(item) for item in payload.get("items", [])],
    }


def _compact_tag_spending(payload: dict[str, Any]) -> dict[str, Any]:
    """One tag's spend-over-time report — the tag-side twin of
    ``_compact_category_spending``, same shape with tag fields."""
    return {
        "tag_id": payload.get("tag_id"),
        "tag_name": payload.get("tag_name"),
        "start_date": payload.get("start_date"),
        "end_date": payload.get("end_date"),
        "total_amount": payload.get("total_amount"),
        "transaction_count": payload.get("transaction_count"),
        "average_per_month": payload.get("average_per_month"),
        "series": payload.get("series", []),
    }


def _compact_recurring(payload: dict[str, Any]) -> dict[str, Any]:
    """Fields the model needs to discuss a recurring template.

    The computed schedule fields (next_due_date, is_due,
    days_until_due) are the point of the listing; color/icon are
    UI-only. Denormalized names ride along so the model can speak
    human language without extra lookups.
    """
    return {
        "id": payload.get("id"),
        "account_id": payload.get("account_id"),
        "account_name": payload.get("account_name"),
        "category_id": payload.get("category_id"),
        "category_name": payload.get("category_name"),
        "transfer_account_id": payload.get("transfer_account_id"),
        "transfer_account_name": payload.get("transfer_account_name"),
        "type": payload.get("type"),
        "amount": payload.get("amount"),
        "description": payload.get("description"),
        "merchant": payload.get("merchant"),
        "notes": payload.get("notes"),
        "frequency": payload.get("frequency"),
        "anchor_date": payload.get("anchor_date"),
        "last_posted_date": payload.get("last_posted_date"),
        "is_active": payload.get("is_active"),
        "next_due_date": payload.get("next_due_date"),
        "is_due": payload.get("is_due"),
        "days_until_due": payload.get("days_until_due"),
    }


def _compact_net_worth(payload: dict[str, Any]) -> dict[str, Any]:
    """Net worth for the model's eyes: headline plus the three
    breakdowns the page renders (asset class, capital role, risk
    level).

    The daily series is dropped on purpose: at "365d"/"all" it is
    hundreds of points the model would never quote — the range's
    change is already in change_amount/change_percent, and month-level
    money trends are get_cash_flow's job, not capital's. color/icon
    are UI-only, same as every other compaction.
    """
    return {
        "range": payload.get("range"),
        "current": payload.get("current"),
        "change_amount": payload.get("change_amount"),
        "change_percent": payload.get("change_percent"),
        "breakdown": [
            {
                "key": item.get("key"),
                "name": item.get("name"),
                "amount": item.get("amount"),
                "percent": item.get("percent"),
            }
            for item in payload.get("breakdown", [])
        ],
        "capital_roles": [
            {
                "role": item.get("role"),
                "label": item.get("label"),
                "total_value": item.get("total_value"),
                "monthly_cash_flow": item.get("monthly_cash_flow"),
                "count": item.get("count"),
            }
            for item in payload.get("capital_roles", [])
        ],
        "risk_levels": [
            {
                "risk_level": item.get("risk_level"),
                "label": item.get("label"),
                "total_value": item.get("total_value"),
                "percent": item.get("percent"),
                "items": [
                    {
                        "key": sub.get("key"),
                        "name": sub.get("name"),
                        "amount": sub.get("amount"),
                        "percent": sub.get("percent"),
                    }
                    for sub in item.get("items", [])
                ],
            }
            for item in payload.get("risk_levels", [])
        ],
    }


def _full_month_range(months: int) -> tuple[date, date]:
    """Inclusive bounds of the last ``months`` FULL calendar months.

    The current month is always half-written (bills still landing, the
    salary maybe not yet in), so the window ends with the previous
    month's last day: a partial month averaged into a suggestion would
    read as a frugality that doesn't exist yet.
    """
    today = date.today()
    year, month = today.year, today.month
    for _ in range(months):
        year, month = (year - 1, 12) if month == 1 else (year, month - 1)
    start = date(year, month, 1)
    end = date(today.year, today.month, 1) - timedelta(days=1)
    return start, end


def _money(value: Decimal) -> str:
    """Two-decimal string — the API's own money wire format."""
    return str(value.quantize(CENT))


def _ceil_to_step(value: Decimal, step: Decimal) -> Decimal:
    """Round ``value`` UP to the next multiple of ``step`` (>= value)."""
    return (value / step).quantize(Decimal("1"), rounding=ROUND_CEILING) * step


def _add_months(year: int, month: int, months: int) -> tuple[int, int]:
    """The calendar month ``months`` after (year, month) — month math only."""
    total = year * 12 + (month - 1) + months
    return total // 12, total % 12 + 1


def _tool(func: Callable[..., Awaitable[str]], description: str) -> BaseTool:
    """Wrap a typed async function into a LangChain tool.

    The async callable must go via ``coroutine=`` — passing it as the
    positional ``func`` makes langchain-core 1.x treat it as sync and
    return an un-awaited coroutine object. The args schema is inferred
    from the signature and annotations, so what the model sees matches
    exactly what the code enforces.
    """
    return StructuredTool.from_function(coroutine=func, description=description)


class _Registry:
    """Tool registration with an explicit read/write class per tool.

    Every tool is declared through ``@registry.add(...)`` — writes
    with ``is_write=True``, reads keeping the decorator's explicit
    ``is_write=False`` default — so the confirmation split is visible
    at each definition instead of being implied by an absent
    ``writes.add`` line somewhere above it.
    """

    def __init__(self) -> None:
        self._tools: list[BaseTool] = []
        self._write_names: set[str] = set()

    def add(
        self,
        description: str,
        *,
        is_write: bool = False,
    ) -> Callable[[Callable[..., Awaitable[str]]], Callable[..., Awaitable[str]]]:
        """Decorator: register the wrapped async function as a tool."""

        def decorator(func: Callable[..., Awaitable[str]]) -> Callable[..., Awaitable[str]]:
            self._tools.append(_tool(func, description))
            if is_write:
                self._write_names.add(func.__name__)
            return func

        return decorator

    def bundle(self) -> ToolBundle:
        return ToolBundle(
            tools=list(self._tools),
            write_names=frozenset(self._write_names),
        )


def build_tools(client: AurumClient) -> ToolBundle:
    """Build the toolset bound to one API client instance."""
    call = _make_caller(client)
    registry = _Registry()

    # --- Accounts ---

    @registry.add(
        "List the user's accounts with live balances, one JSON object per "
        "account (id, name, type, currency, balance, is_archived). Archived "
        "accounts are hidden unless include_archived=true."
    )
    async def list_accounts(include_archived: bool = False) -> str:
        params = {"include_archived": "true"} if include_archived else None
        return await call(
            "GET",
            PATH_ACCOUNTS,
            params=params,
            compact=lambda items: [_compact_account(item) for item in items],
        )

    @registry.add(
        "Create a new account — a bank account, card, or cash wallet. "
        "name is required (1-100 chars). type: checking | debit_card | "
        "savings | credit_card | cash | investment | other (default "
        "checking). currency: 3-letter display code, default USD. "
        "color: 6-digit hex like '#4f46e5'.",
        is_write=True,
    )
    async def create_account(
        name: str,
        type: str | None = None,
        currency: str | None = None,
        color: str | None = None,
    ) -> str:
        body = _omit_none(name=name, type=type, currency=currency, color=color)
        return await call("POST", PATH_ACCOUNTS, body=body, compact=_compact_account)

    @registry.add(
        "Update an account partially — only the fields you pass change, "
        "omitted ones stay as-is. Use is_archived=true to hide an account "
        "without deleting it; is_archived=false restores it.",
        is_write=True,
    )
    async def update_account(
        account_id: int,
        name: str | None = None,
        type: str | None = None,
        currency: str | None = None,
        color: str | None = None,
        is_archived: bool | None = None,
    ) -> str:
        body = _omit_none(
            name=name,
            type=type,
            currency=currency,
            color=color,
            is_archived=is_archived,
        )
        return await call(
            "PATCH",
            f"{PATH_ACCOUNTS}/{account_id}",
            body=body,
            compact=_compact_account,
        )

    @registry.add(
        "PERMANENTLY delete an account and EVERY transaction on it — "
        "irreversible. The most destructive call in this toolset: prefer "
        "update_account with is_archived=true unless the user explicitly "
        "insists on deletion.",
        is_write=True,
    )
    async def delete_account(account_id: int) -> str:
        return await call("DELETE", f"{PATH_ACCOUNTS}/{account_id}")

    # --- Categories ---

    @registry.add(
        "List categories sorted by display order (id, name, kind, "
        "parent_id, is_default). kind: 'expense' or 'income' filters to "
        "one side; omit for both. Subcategories carry the parent_id of a "
        "top-level category of the same kind."
    )
    async def list_categories(kind: str | None = None) -> str:
        params = {"kind": kind} if kind else None
        return await call(
            "GET",
            PATH_CATEGORIES,
            params=params,
            compact=lambda items: [_compact_category(item) for item in items],
        )

    @registry.add(
        "Create a category or subcategory. kind: 'expense' or 'income' — "
        "required and fixed forever. name: 1-100 chars. color: required "
        "6-digit hex like '#22c55e'. parent_id: set only for a "
        "subcategory; the parent must be top-level and share the child's "
        "kind. sort_order controls display order (default 0).",
        is_write=True,
    )
    async def create_category(
        name: str,
        kind: str,
        color: str,
        icon: str | None = None,
        sort_order: int | None = None,
        parent_id: int | None = None,
    ) -> str:
        body = _omit_none(
            name=name,
            kind=kind,
            color=color,
            icon=icon,
            sort_order=sort_order,
            parent_id=parent_id,
        )
        return await call("POST", PATH_CATEGORIES, body=body, compact=_compact_category)

    @registry.add(
        "Update a category partially — omitted fields stay as-is. kind "
        "cannot be changed, ever. parent_id moves the category under a "
        "top-level parent of the same kind; clear_parent=true turns it "
        "back into a top-level category (sends parent_id=null) and wins "
        "if parent_id is also given. A category that has subcategories "
        "cannot become a subcategory.",
        is_write=True,
    )
    async def update_category(
        category_id: int,
        name: str | None = None,
        color: str | None = None,
        icon: str | None = None,
        sort_order: int | None = None,
        parent_id: int | None = None,
        clear_parent: bool = False,
    ) -> str:
        body = _omit_none(
            name=name,
            color=color,
            icon=icon,
            sort_order=sort_order,
            parent_id=parent_id,
        )
        # Omitted parent_id keeps the current parent; explicit null clears
        # it (see DOCS.md "Partial updates") — needs its own flag, since
        # "not provided" and "set to null" are different requests.
        if clear_parent:
            body["parent_id"] = None
        return await call(
            "PATCH",
            f"{PATH_CATEGORIES}/{category_id}",
            body=body,
            compact=_compact_category,
        )

    @registry.add(
        "Delete a category. Seeded defaults (is_default=true) can only be "
        "deleted while nothing references them — the API returns 400 "
        "otherwise, with a message naming what still points at it. "
        "Deleting a custom category that has transactions leaves those "
        "transactions uncategorized (existing ones are not deleted).",
        is_write=True,
    )
    async def delete_category(category_id: int) -> str:
        return await call("DELETE", f"{PATH_CATEGORIES}/{category_id}")

    # --- Tags ---

    @registry.add("List all tags alphabetically (id, name).")
    async def list_tags() -> str:
        return await call("GET", PATH_TAGS)

    @registry.add(
        "Create a tag (1-50 chars), or return the existing one on a "
        "case-insensitive match — safe to call when unsure whether the "
        "tag already exists.",
        is_write=True,
    )
    async def create_tag(name: str) -> str:
        return await call("POST", PATH_TAGS, body={"name": name})

    # --- Transactions ---

    @registry.add(
        "Fetch one transaction by id, compacted (account_name, "
        "category_name, tags, splits included). Use this when the exact "
        "row is needed for an edit."
    )
    async def get_transaction(transaction_id: int) -> str:
        return await call(
            "GET",
            f"{PATH_TRANSACTIONS}/{transaction_id}",
            compact=_compact_transaction,
        )

    @registry.add(
        "Search transactions. All filters are optional: year (2000-2100) "
        "and/or month (1-12), or start_date/end_date ('YYYY-MM-DD', "
        "inclusive, combinable with year/month), account_id, category_id, "
        "tag_id, type ('income' | 'expense' | 'transfer'), search (a "
        "case-insensitive substring over description, merchant and "
        "notes). sort: 'date_desc' (default), 'amount_desc', "
        "'amount_asc'. Returns {items, total, page, page_size} — when "
        "total exceeds page*page_size, call again with a higher page. "
        "page_size: max 200."
    )
    async def search_transactions(
        year: int | None = None,
        month: int | None = None,
        start_date: str | None = None,
        end_date: str | None = None,
        account_id: int | None = None,
        category_id: int | None = None,
        tag_id: int | None = None,
        type: str | None = None,
        search: str | None = None,
        sort: str | None = None,
        page: int = 1,
        page_size: int = 20,
    ) -> str:
        params = _omit_none(
            year=year,
            month=month,
            start_date=start_date,
            end_date=end_date,
            account_id=account_id,
            category_id=category_id,
            tag_id=tag_id,
            type=type,
            search=search,
            sort=sort,
            page=page,
            page_size=page_size,
        )
        # Same blank-filter rule as the analytics tools: an empty
        # string is "not provided", not a doomed 422 round trip.
        params = _params_without_blanks(params)
        return await call(
            "GET",
            PATH_TRANSACTIONS,
            params=params,
            compact=lambda payload: {
                "items": [_compact_transaction(item) for item in payload.get("items", [])],
                "total": payload.get("total"),
                "page": payload.get("page"),
                "page_size": payload.get("page_size"),
            },
        )

    @registry.add(
        "Create one transaction. type: 'income', 'expense' or 'transfer'. "
        "amount is positive (direction comes from type), up to 2 decimal "
        "places. description: 1-255 chars, auto-capitalized server-side. "
        "date: 'YYYY-MM-DD'. For income/expense: category_id is optional "
        "but must match the type's kind (income transaction needs an "
        "income category, expense needs an expense one) and "
        "transfer_account_id must NOT be set. For transfer: "
        "transfer_account_id is required and must differ from account_id, "
        "and category_id must NOT be set. tag_ids: existing tag ids — "
        "create new tags with create_tag first. Transactions split across "
        "multiple categories are NOT supported by these tools — record "
        "a single-category transaction instead.",
        is_write=True,
    )
    async def create_transaction(
        account_id: int,
        type: str,
        amount: float,
        description: str,
        date: str,
        category_id: int | None = None,
        transfer_account_id: int | None = None,
        merchant: str | None = None,
        notes: str | None = None,
        tag_ids: list[int] | None = None,
    ) -> str:
        body = _omit_none(
            account_id=account_id,
            type=type,
            amount=amount,
            description=description,
            date=date,
            category_id=category_id,
            transfer_account_id=transfer_account_id,
            merchant=merchant,
            notes=notes,
            tag_ids=tag_ids,
        )
        return await call(
            "POST",
            PATH_TRANSACTIONS,
            body=body,
            compact=_compact_transaction,
        )

    @registry.add(
        "Update a transaction partially — omitted fields stay as-is. "
        "Checks run against the row as it would look AFTER the patch, so "
        "switching type may force clearing fields: a transfer must not "
        "carry a category (clear_category=true sends category_id=null), "
        "an income/expense must not carry transfer_account_id "
        "(clear_transfer=true sends transfer_account_id=null). The clear "
        "flags win if the matching id field is also given. tag_ids: omit "
        "to keep the tags, send (even an empty list) to replace the "
        "whole tag set. Transactions split across multiple categories "
        "are NOT supported by these tools — edit single-category rows "
        "only.",
        is_write=True,
    )
    async def update_transaction(
        transaction_id: int,
        account_id: int | None = None,
        type: str | None = None,
        amount: float | None = None,
        description: str | None = None,
        date: str | None = None,
        category_id: int | None = None,
        clear_category: bool = False,
        transfer_account_id: int | None = None,
        clear_transfer: bool = False,
        merchant: str | None = None,
        notes: str | None = None,
        tag_ids: list[int] | None = None,
    ) -> str:
        body = _omit_none(
            account_id=account_id,
            type=type,
            amount=amount,
            description=description,
            date=date,
            category_id=category_id,
            transfer_account_id=transfer_account_id,
            merchant=merchant,
            notes=notes,
            tag_ids=tag_ids,
        )
        # The backend treats explicit null as "clear" and an omitted field
        # as "keep" (exclude_unset), so clearing needs its own flags —
        # same pattern as update_category's clear_parent.
        if clear_category:
            body["category_id"] = None
        if clear_transfer:
            body["transfer_account_id"] = None
        return await call(
            "PATCH",
            f"{PATH_TRANSACTIONS}/{transaction_id}",
            body=body,
            compact=_compact_transaction,
        )

    @registry.add(
        "Delete one transaction permanently. Resolve the id first with "
        "search_transactions or get_transaction when uncertain.",
        is_write=True,
    )
    async def delete_transaction(transaction_id: int) -> str:
        return await call("DELETE", f"{PATH_TRANSACTIONS}/{transaction_id}")

    # --- Budgets ---

    @registry.add(
        "List the user's budgets — one monthly spending limit per "
        "expense category (id, category_id, category_name, "
        "monthly_limit)."
    )
    async def list_budgets() -> str:
        return await call(
            "GET",
            PATH_BUDGETS,
            compact=lambda items: [_compact_budget(item) for item in items],
        )

    @registry.add(
        "Budgets vs. actual spend for one month — THE call for 'how "
        "much is left in the X budget'. year (2000-2100) and month "
        "(1-12) default to the current month. Each item: budget_id, "
        "category_id, category_name, monthly_limit, spent (includes "
        "the category's subcategories), remaining, percent (may "
        "exceed 100), is_over_budget. budget_id and category_id are "
        "the handles for a later update_budget or delete_budget."
    )
    async def get_budget_status(year: int | None = None, month: int | None = None) -> str:
        params = _omit_none(year=year, month=month)
        return await call(
            "GET",
            f"{PATH_BUDGETS}/status",
            params=params or None,
            compact=lambda payload: {
                "year": payload.get("year"),
                "month": payload.get("month"),
                "items": [_compact_budget_status_item(item) for item in payload.get("items", [])],
            },
        )

    @registry.add(
        "Create a monthly spending limit for ONE expense category. "
        "Income categories cannot be budgeted, and each category has "
        "at most one budget — the API returns 400 when either rule is "
        "broken. Resolve the category id with list_categories first. "
        "monthly_limit must be positive.",
        is_write=True,
    )
    async def create_budget(category_id: int, monthly_limit: float) -> str:
        return await call(
            "POST",
            PATH_BUDGETS,
            body={"category_id": category_id, "monthly_limit": monthly_limit},
            compact=_compact_budget,
        )

    @registry.add(
        "Change a budget's monthly_limit (positive). The category "
        "binding is fixed — to move a limit to another category, "
        "delete and recreate the budget.",
        is_write=True,
    )
    async def update_budget(budget_id: int, monthly_limit: float) -> str:
        return await call(
            "PATCH",
            f"{PATH_BUDGETS}/{budget_id}",
            body={"monthly_limit": monthly_limit},
            compact=_compact_budget,
        )

    @registry.add(
        "Delete a budget — only the limit goes; the category and its "
        "transactions stay untouched.",
        is_write=True,
    )
    async def delete_budget(budget_id: int) -> str:
        return await call("DELETE", f"{PATH_BUDGETS}/{budget_id}")

    # --- Goals ---

    @registry.add(
        "List savings goals with computed progress: id, name, "
        "target_amount, target_date, current_amount, remaining, "
        "percent, is_reached."
    )
    async def list_goals() -> str:
        return await call("GET", PATH_GOALS)

    @registry.add(
        "Create a savings goal. name: 1-150 chars. target_amount: "
        "positive. target_date: 'YYYY-MM-DD', or omit for an open-ended "
        "goal. Progress starts at zero — money is attached later by "
        "logging contributions.",
        is_write=True,
    )
    async def create_goal(
        name: str,
        target_amount: float,
        target_date: str | None = None,
    ) -> str:
        body = _omit_none(name=name, target_amount=target_amount, target_date=target_date)
        return await call("POST", PATH_GOALS, body=body)

    @registry.add(
        "Update a goal partially — omitted fields stay as-is. "
        "clear_target_date=true removes the deadline (sends "
        "target_date=null) and wins if target_date is also given.",
        is_write=True,
    )
    async def update_goal(
        goal_id: int,
        name: str | None = None,
        target_amount: float | None = None,
        target_date: str | None = None,
        clear_target_date: bool = False,
    ) -> str:
        body = _omit_none(name=name, target_amount=target_amount, target_date=target_date)
        # Same explicit-null pattern as update_category's clear_parent:
        # "not provided" keeps the date, an explicit null clears it.
        if clear_target_date:
            body["target_date"] = None
        return await call("PATCH", f"{PATH_GOALS}/{goal_id}", body=body)

    @registry.add(
        "Log money moved into (positive amount) or out of (negative "
        "amount) a goal. The ONLY way to change a goal's progress: "
        "current_amount is always the sum of every logged "
        "contribution, there is no 'set balance' call. Zero is "
        "rejected. date: 'YYYY-MM-DD'. note: optional, up to 200 "
        "chars.",
        is_write=True,
    )
    async def add_goal_contribution(
        goal_id: int,
        amount: float,
        date: str,
        note: str | None = None,
    ) -> str:
        body = _omit_none(amount=amount, date=date, note=note)
        return await call("POST", f"{PATH_GOALS}/{goal_id}/contributions", body=body)

    @registry.add(
        "PERMANENTLY delete a goal AND its whole contribution log — "
        "the money history goes with it, and there is no softer "
        "archive-like option for goals.",
        is_write=True,
    )
    async def delete_goal(goal_id: int) -> str:
        return await call("DELETE", f"{PATH_GOALS}/{goal_id}")

    # --- Analytics & reports (read-only) ---

    @registry.add(
        "One month's headline numbers: real_income, spent, net, "
        "transferred_out, plus spending broken down by category "
        "(category_id, name, amount, percent, children when a slice's "
        "spend came from more than one distinct category — subcategory "
        "rollup). year (2000-2100) and month "
        "(1-12) default to the current month. THE call for 'how did "
        "this month go' summaries."
    )
    async def get_dashboard_summary(year: int | None = None, month: int | None = None) -> str:
        params = _omit_none(year=year, month=month)
        return await call(
            "GET",
            PATH_DASHBOARD,
            params=params or None,
            compact=_compact_dashboard_summary,
        )

    @registry.add(
        "Income vs. expense month by month: points (year, month, "
        "income, expense, net) plus total_income/total_expense/"
        "total_net. start_date/end_date ('YYYY-MM-DD', inclusive) "
        "bound the series; omit both for all history. THE call for "
        "trend questions like 'is my income covering my spending'."
    )
    async def get_cash_flow(
        start_date: str | None = None,
        end_date: str | None = None,
    ) -> str:
        params = _params_without_blanks(_omit_none(start_date=start_date, end_date=end_date))
        return await call("GET", PATH_CASH_FLOW, params=params or None)

    @registry.add(
        "One category's spend over time: total_amount, "
        "transaction_count, average_per_month, month-by-month series "
        "(year, month, amount). category_id is required — resolve it "
        "with list_categories. start_date/end_date ('YYYY-MM-DD', "
        "inclusive) bound the series; omit both for all history."
    )
    async def get_category_spending(
        category_id: int,
        start_date: str | None = None,
        end_date: str | None = None,
    ) -> str:
        params = _params_without_blanks(
            _omit_none(category_id=category_id, start_date=start_date, end_date=end_date)
        )
        return await call(
            "GET",
            PATH_CATEGORY_SPENDING,
            params=params,
            compact=_compact_category_spending,
        )

    @registry.add(
        "All categories ranked by total spend over a period, richest "
        "first: items (category_id, name, amount, percent, "
        "transaction_count, children when spend came from "
        "subcategories) plus the period's total_amount. kind: "
        "'expense' or 'income'. start_date/end_date ('YYYY-MM-DD', "
        "inclusive) bound the period; omit both for all history. THE "
        "call for 'where does my money go' questions."
    )
    async def get_category_ranking(
        kind: str = "expense",
        start_date: str | None = None,
        end_date: str | None = None,
    ) -> str:
        params = _params_without_blanks(
            _omit_none(kind=kind, start_date=start_date, end_date=end_date)
        )
        return await call(
            "GET",
            PATH_CATEGORY_RANKING,
            params=params,
            compact=_compact_category_ranking,
        )

    @registry.add(
        "All tags ranked by total spend over a period: items (tag_id, "
        "name, amount, percent of the period's TOTAL spending, "
        "transaction_count, per-category breakdown), plus total_amount "
        "and tagged_amount. kind: 'expense' or 'income'. "
        "start_date/end_date ('YYYY-MM-DD', inclusive) bound the "
        "period; omit both for all history. A single tag's trend over "
        "time is get_tag_spending instead."
    )
    async def get_tag_ranking(
        kind: str = "expense",
        start_date: str | None = None,
        end_date: str | None = None,
    ) -> str:
        params = _params_without_blanks(
            _omit_none(kind=kind, start_date=start_date, end_date=end_date)
        )
        return await call(
            "GET",
            PATH_TAG_RANKING,
            params=params,
            compact=_compact_tag_ranking,
        )

    @registry.add(
        "One tag's spend over time: total_amount, transaction_count, "
        "average_per_month, month-by-month series (year, month, "
        "amount). tag_id is required — resolve it with list_tags. "
        "kind: 'expense' or 'income'. start_date/end_date "
        "('YYYY-MM-DD', inclusive) bound the series; omit both for "
        "all history."
    )
    async def get_tag_spending(
        tag_id: int,
        kind: str = "expense",
        start_date: str | None = None,
        end_date: str | None = None,
    ) -> str:
        params = _params_without_blanks(
            _omit_none(tag_id=tag_id, kind=kind, start_date=start_date, end_date=end_date)
        )
        return await call(
            "GET",
            PATH_TAG_SPENDING,
            params=params,
            compact=_compact_tag_spending,
        )

    @registry.add(
        "Active financial alerts: negative cash flow streak, declining "
        "net worth, over-budget category, risky allocation, idle cash. "
        "Each item is {key, severity, params} with NO ready-made "
        "sentence — interpret the key and params yourself and build a "
        "short message in the user's language (e.g. key 'idle_cash' "
        "with params {count: 2, days: 75} means at least 2 accounts "
        "have seen no activity for 75 days or more)."
    )
    async def get_insights() -> str:
        return await call("GET", PATH_INSIGHTS)

    @registry.add(
        "Financial observations: rising spending categories, "
        "unbudgeted top expenses, savings-rate trend. Each item is "
        "{key, tone, params} with NO ready-made sentence — interpret "
        "the key and params yourself and build a short message in the "
        "user's language (e.g. key 'rising_category' with params "
        "{category: 'Dining', percent: 34, current: 850.0, average: "
        "635.0} means this month's Dining spend is 34% above its "
        "usual average)."
    )
    async def get_advice() -> str:
        return await call("GET", PATH_ADVICE)

    # --- Financial advisor (read-only, but two tools compute) ---

    @registry.add(
        "The user's total capital: net worth (cash from every account "
        "plus all assets) with its change over the range, broken down "
        "by asset class (breakdown), by capital role (capital_roles: "
        "income / neutral / drain) and by risk level (risk_levels, "
        "each with its holdings). range: '7d' | '30d' | '90d' | '180d' "
        "| '365d' | 'all', default '30d'. THE call for 'what am I "
        "worth' / 'how is my capital doing' questions; the daily "
        "series is not included — for month-level income/expense "
        "trends use get_cash_flow."
    )
    async def get_net_worth(range: str = "30d") -> str:
        return await call(
            "GET",
            PATH_NET_WORTH,
            params={"range": range},
            compact=_compact_net_worth,
        )

    @registry.add(
        "Budget suggestions from real history: per-category average "
        "monthly spend over the last N FULL months (the current, "
        "still-running month excluded), each with a proposed limit — "
        "the average rounded UP to the nearest 10. items carry "
        "category_id, name, total_amount, average_per_month, "
        "suggested_limit, has_budget and current_limit (for an "
        "update_budget comparison when a limit already exists). "
        "months: 1-24, default 6. THE call for 'help me plan my "
        "budget' / 'suggest limits' questions; applying the picks "
        "afterwards is create_budget / update_budget with the usual "
        "confirmation."
    )
    async def suggest_budgets(months: int = DEFAULT_LOOKBACK_MONTHS) -> str:
        if not 1 <= months <= MAX_LOOKBACK_MONTHS:
            return f"months must be between 1 and {MAX_LOOKBACK_MONTHS}."
        start, end = _full_month_range(months)
        # Two reads, fetched directly rather than via `call` (which
        # would hand back a string to parse right back): the tool needs
        # both payloads in Python to do the averaging itself.
        try:
            budgets = await client.request("GET", PATH_BUDGETS)
            ranking = await client.request(
                "GET",
                PATH_CATEGORY_RANKING,
                params={
                    "kind": "expense",
                    "start_date": start.isoformat(),
                    "end_date": end.isoformat(),
                },
            )
        except AurumApiError as error:
            return f"API error (HTTP {error.status}): {error.detail}"
        existing = {
            item.get("category_id"): item.get("monthly_limit") for item in budgets or []
        }
        items: list[dict[str, Any]] = []
        for rank in (ranking or {}).get("items", []):
            total = Decimal(str(rank.get("amount") or 0))
            # Zero spend has no average worth suggesting a limit from.
            if total <= 0:
                continue
            average = total / months
            category_id = rank.get("category_id")
            items.append(
                {
                    "category_id": category_id,
                    "name": rank.get("name"),
                    "total_amount": _money(total),
                    "average_per_month": _money(average),
                    "suggested_limit": _money(_ceil_to_step(average, LIMIT_STEP)),
                    "has_budget": category_id in existing,
                    "current_limit": existing.get(category_id),
                }
            )
        return _dumps(
            {
                "months": months,
                "start_date": start.isoformat(),
                "end_date": end.isoformat(),
                "items": items,
            }
        )

    @registry.add(
        "Savings math, done exactly — never divide multi-month amounts "
        "yourself. One target plus one contribution mode. Target: "
        "either goal_id (an existing savings goal — its remaining "
        "amount becomes the target) or target_amount (positive), never "
        "both. Contribution: exactly one of monthly_contribution "
        "(positive), target_date ('YYYY-MM-DD', a future month — the "
        "required monthly amount comes back) or use_average_net=true "
        "(the average of the real monthly net over the last 6 full "
        "months, from cash flow). Answers {required_monthly, "
        "months_available} for a target_date question, "
        "{months_needed, reached_on 'YYYY-MM'} for a contribution "
        "question. Simple arithmetic: no investment returns assumed."
    )
    async def savings_forecast(
        target_amount: float | None = None,
        monthly_contribution: float | None = None,
        target_date: str | None = None,
        goal_id: int | None = None,
        use_average_net: bool = False,
    ) -> str:
        # A blank date is "not provided" — the same rule as the list
        # filters; a model leaving the field empty must not hit the
        # future-month guard below.
        target_date = (target_date or "").strip() or None
        # Target: goal_id (remaining of a real goal) XOR target_amount.
        if (goal_id is None) == (target_amount is None):
            return "Pass exactly one of goal_id or target_amount."
        # Contribution mode: exactly one of the three.
        if sum(
            (
                monthly_contribution is not None,
                target_date is not None,
                use_average_net,
            )
        ) != 1:
            return (
                "Pass exactly one of monthly_contribution, target_date "
                "or use_average_net=true."
            )
        target: dict[str, Any]
        if goal_id is not None:
            try:
                goals = await client.request("GET", PATH_GOALS)
            except AurumApiError as error:
                return f"API error (HTTP {error.status}): {error.detail}"
            goal = next(
                (item for item in goals or [] if item.get("id") == goal_id),
                None,
            )
            if goal is None:
                return f"No goal with id {goal_id}."
            remaining = Decimal(str(goal.get("remaining") or 0))
            if remaining <= 0:
                return (
                    f"Goal '{goal.get('name')}' is already reached — "
                    "nothing to save for."
                )
            target = {
                "goal": {
                    "id": goal_id,
                    "name": goal.get("name"),
                    "remaining": _money(remaining),
                }
            }
        else:
            # Narrowed by the XOR guard above: target_amount is set.
            if target_amount <= 0:
                return "target_amount must be positive."
            remaining = Decimal(str(target_amount))
            target = {"target_amount": _money(remaining)}
        today = date.today()
        if target_date is not None:
            try:
                when = date.fromisoformat(target_date)
            except ValueError:
                return "target_date must be 'YYYY-MM-DD'."
            # Calendar months between today and the deadline — a month
            # is the unit the user budgets in, not 30-day chunks.
            months_available = (when.year - today.year) * 12 + (when.month - today.month)
            if months_available <= 0:
                return "target_date must be in a future month."
            # Rounded UP to the cent: a hair short would still miss.
            required = (remaining / months_available).quantize(
                CENT, rounding=ROUND_CEILING
            )
            return _dumps(
                {
                    **target,
                    "target_date": when.isoformat(),
                    "months_available": months_available,
                    "required_monthly": _money(required),
                }
            )
        if monthly_contribution is not None:
            if monthly_contribution <= 0:
                return "monthly_contribution must be positive."
            contribution = Decimal(str(monthly_contribution))
        else:
            # use_average_net: ground the contribution in what the
            # ledger actually clears per month, not a guess.
            start, end = _full_month_range(AVERAGE_NET_WINDOW_MONTHS)
            try:
                flow = await client.request(
                    "GET",
                    PATH_CASH_FLOW,
                    params={
                        "start_date": start.isoformat(),
                        "end_date": end.isoformat(),
                    },
                )
            except AurumApiError as error:
                return f"API error (HTTP {error.status}): {error.detail}"
            points = (flow or {}).get("points", [])
            if not points:
                # Defensive against a backend shape change: today's
                # bounded cash-flow zero-fills every month of the
                # window, so a live instance answers with six points
                # even when the ledger is empty — this branch only
                # fires if that contract ever shifts.
                return (
                    "No transactions in the last "
                    f"{AVERAGE_NET_WINDOW_MONTHS} full months — nothing to average."
                )
            # The window is whole calendar months, zeros included (a
            # month with no activity is a real net of zero), so the
            # point count IS the window length.
            average_net = Decimal(str(flow.get("total_net") or 0)) / len(points)
            if average_net <= 0:
                return (
                    "Average monthly net over the last "
                    f"{len(points)} full months is {_money(average_net)} — "
                    "at this rate nothing can be saved."
                )
            contribution = average_net
            target["average_net_monthly"] = _money(average_net)
            target["window_months"] = len(points)
        # ceil: the last partial month is still a month of waiting.
        months_needed = (remaining / contribution).quantize(
            Decimal("1"), rounding=ROUND_CEILING
        )
        reached_year, reached_month = _add_months(
            today.year, today.month, int(months_needed)
        )
        return _dumps(
            {
                **target,
                "monthly_contribution": _money(contribution),
                "months_needed": int(months_needed),
                "reached_on": f"{reached_year:04d}-{reached_month:02d}",
            }
        )

    # --- Recurring transactions ---

    @registry.add(
        "List recurring templates (bills/income that repeat on a "
        "schedule), each with computed due-date info: next_due_date, "
        "is_due, days_until_due (negative if overdue), is_active, "
        "plus denormalized account/category names. Nothing posts "
        "automatically in the background — posting is an explicit "
        "post_recurring call."
    )
    async def list_recurring() -> str:
        return await call(
            "GET",
            PATH_RECURRING,
            compact=lambda items: [_compact_recurring(item) for item in items],
        )

    @registry.add(
        "Create a recurring template for a bill or income that "
        "repeats on a schedule. type: 'income', 'expense' or "
        "'transfer', following the same consistency rules as "
        "create_transaction: income/expense take an optional "
        "category_id of the matching kind and must NOT set "
        "transfer_account_id; transfer requires transfer_account_id "
        "(different from account_id) and must NOT set category_id. "
        "NOTE: unlike transactions, the API does NOT reject a "
        "template that breaks these rules — a broken template would "
        "post broken transactions, so follow the rules exactly. "
        "amount is positive, description 1-255 chars. frequency: "
        "'weekly' | 'monthly' | 'yearly'. anchor_date ('YYYY-MM-DD') "
        "is the first due date. No date and no tag_ids — the posting "
        "transaction is dated at post time.",
        is_write=True,
    )
    async def create_recurring(
        account_id: int,
        type: str,
        amount: float,
        description: str,
        frequency: str,
        anchor_date: str,
        category_id: int | None = None,
        transfer_account_id: int | None = None,
        merchant: str | None = None,
        notes: str | None = None,
    ) -> str:
        body = _omit_none(
            account_id=account_id,
            type=type,
            amount=amount,
            description=description,
            frequency=frequency,
            anchor_date=anchor_date,
            category_id=category_id,
            transfer_account_id=transfer_account_id,
            merchant=merchant,
            notes=notes,
        )
        return await call("POST", PATH_RECURRING, body=body, compact=_compact_recurring)

    @registry.add(
        "Update a recurring template partially — omitted fields stay "
        "as-is. is_active=false pauses the template without deleting "
        "anything; is_active=true resumes it. Follow the "
        "type-consistency rules of create_recurring when changing "
        "type, account, category or transfer fields — the API does "
        "not reject an inconsistent template, so keeping the row "
        "consistent is on you.",
        is_write=True,
    )
    async def update_recurring(
        recurring_id: int,
        account_id: int | None = None,
        type: str | None = None,
        amount: float | None = None,
        description: str | None = None,
        frequency: str | None = None,
        anchor_date: str | None = None,
        category_id: int | None = None,
        transfer_account_id: int | None = None,
        merchant: str | None = None,
        notes: str | None = None,
        is_active: bool | None = None,
    ) -> str:
        body = _omit_none(
            account_id=account_id,
            type=type,
            amount=amount,
            description=description,
            frequency=frequency,
            anchor_date=anchor_date,
            category_id=category_id,
            transfer_account_id=transfer_account_id,
            merchant=merchant,
            notes=notes,
            is_active=is_active,
        )
        return await call(
            "PATCH",
            f"{PATH_RECURRING}/{recurring_id}",
            body=body,
            compact=_compact_recurring,
        )

    @registry.add(
        "Delete a recurring template. Already-posted transactions stay "
        "untouched — only the future schedule goes away. Prefer "
        "update_recurring with is_active=false when the bill might "
        "come back.",
        is_write=True,
    )
    async def delete_recurring(recurring_id: int) -> str:
        return await call("DELETE", f"{PATH_RECURRING}/{recurring_id}")

    @registry.add(
        "Post a recurring template NOW: creates a real transaction "
        "dated today with the template's fields and advances the "
        "schedule (last_posted_date moves to today, next_due_date is "
        "recomputed). The response describes the TEMPLATE's new "
        "state, not the created transaction. A confirmation preview "
        "may warn about a similar transaction already recorded today "
        "— the user decides whether to still post.",
        is_write=True,
    )
    async def post_recurring(recurring_id: int) -> str:
        return await call(
            "POST",
            f"{PATH_RECURRING}/{recurring_id}/post",
            compact=_compact_recurring,
        )

    return registry.bundle()
