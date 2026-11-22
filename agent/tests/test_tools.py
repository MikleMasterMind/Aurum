"""Tool behavior tests: request shapes, response compaction, write registry."""

from __future__ import annotations

import json
from datetime import date, timedelta
from typing import Any

import httpx
import pytest

from aurum_agent.tools import build_tools

# Every tool that mutates data — the confirmation router's source of truth.
EXPECTED_WRITE_NAMES = {
    "create_account",
    "update_account",
    "delete_account",
    "create_category",
    "update_category",
    "delete_category",
    "create_tag",
    "create_transaction",
    "update_transaction",
    "delete_transaction",
    "create_budget",
    "update_budget",
    "delete_budget",
    "create_goal",
    "update_goal",
    "delete_goal",
    "add_goal_contribution",
    "create_recurring",
    "update_recurring",
    "delete_recurring",
    "post_recurring",
}


def bundle_by_name(bundle: Any) -> dict[str, Any]:
    return {tool.name: tool for tool in bundle.tools}


def body_of(request: httpx.Request) -> dict[str, Any]:
    return json.loads(request.content)


def account_payload() -> list[dict[str, Any]]:
    # Extra fields on purpose: compaction must drop them.
    return [
        {
            "id": 1,
            "name": "Checking",
            "type": "checking",
            "currency": "USD",
            "color": "#4f46e5",
            "is_archived": False,
            "balance": "1523.40",
        }
    ]


def transaction_payload() -> dict[str, Any]:
    # Nested account/category/tags on purpose: compaction must flatten
    # them to the *_name fields the model speaks in.
    return {
        "id": 7,
        "account_id": 1,
        "account": {"id": 1, "name": "Cash", "type": "cash", "currency": "USD", "color": None},
        "category_id": 4,
        "category": {"id": 4, "name": "Groceries", "kind": "expense", "color": "#22c55e"},
        "transfer_account_id": None,
        "type": "expense",
        "amount": "42.50",
        "description": "Groceries",
        "merchant": "Whole Foods",
        "notes": None,
        "date": "2026-11-21",
        "tags": [{"id": 3, "name": "weekend"}],
        "splits": [],
    }


def budget_payload() -> list[dict[str, Any]]:
    # Extra fields on purpose: compaction must drop them.
    return [
        {
            "id": 1,
            "category_id": 4,
            "category_name": "Groceries",
            "category_color": "#22c55e",
            "category_icon": "shopping-cart",
            "monthly_limit": "500.00",
        }
    ]


def budget_status_payload() -> dict[str, Any]:
    return {
        "year": 2026,
        "month": 11,
        "items": [
            {
                "budget_id": 1,
                "category_id": 4,
                "category_name": "Groceries",
                "category_color": "#22c55e",
                "category_icon": "shopping-cart",
                "monthly_limit": "500.00",
                "spent": "612.30",
                "remaining": "-112.30",
                "percent": 122.46,
                "is_over_budget": True,
            }
        ],
    }


def goal_payload() -> list[dict[str, Any]]:
    # Already compact server-side (GoalRead) — the tool passes it through.
    return [
        {
            "id": 1,
            "name": "Emergency fund",
            "target_amount": "10000.00",
            "target_date": "2027-01-01",
            "current_amount": "3250.00",
            "remaining": "6750.00",
            "percent": 32.5,
            "is_reached": False,
        }
    ]


def dashboard_payload() -> dict[str, Any]:
    # color/icon on both levels on purpose: compaction must drop
    # them, the children (subcategory rollup) must survive.
    return {
        "year": 2026,
        "month": 11,
        "real_income": "5200.00",
        "spent": "3120.45",
        "net": "2079.55",
        "transferred_out": "500.00",
        "spending_by_category": [
            {
                "category_id": 4,
                "name": "Groceries",
                "color": "#22c55e",
                "icon": "shopping-cart",
                "amount": "612.30",
                "percent": 19.6,
                "children": [
                    {
                        "category_id": 5,
                        "name": "Snacks",
                        "color": "#a3e635",
                        "icon": "cookie",
                        "amount": "112.30",
                    }
                ],
            }
        ],
    }


def cash_flow_payload() -> dict[str, Any]:
    return {
        "start_date": None,
        "end_date": None,
        "points": [
            {"year": 2026, "month": 10, "income": "5200.00", "expense": "3400.00", "net": "1800.00"}
        ],
        "total_income": "62400.00",
        "total_expense": "40800.00",
        "total_net": "21600.00",
    }


def category_spending_payload() -> dict[str, Any]:
    # Extra color/icon on purpose: compaction must drop them.
    return {
        "category_id": 4,
        "category_name": "Groceries",
        "category_color": "#22c55e",
        "category_icon": "shopping-cart",
        "start_date": None,
        "end_date": None,
        "total_amount": "612.30",
        "transaction_count": 14,
        "average_per_month": "306.15",
        "series": [
            {"year": 2026, "month": 10, "amount": "306.15"},
            {"year": 2026, "month": 11, "amount": "306.15"},
        ],
    }


def category_ranking_payload() -> dict[str, Any]:
    return {
        "start_date": None,
        "end_date": None,
        "total_amount": "3120.45",
        "items": [
            {
                "category_id": 4,
                "name": "Groceries",
                "color": "#22c55e",
                "icon": "shopping-cart",
                "amount": "612.30",
                "percent": 19.6,
                "transaction_count": 14,
                "children": [],
            }
        ],
    }


def tag_ranking_payload() -> dict[str, Any]:
    return {
        "start_date": None,
        "end_date": None,
        "total_amount": "3120.45",
        "tagged_amount": "1200.00",
        "items": [
            {
                "tag_id": 3,
                "name": "weekend",
                "color": "#38bdf8",
                "amount": "800.00",
                "percent": 25.6,
                "transaction_count": 5,
                "categories": [
                    {
                        "category_id": 4,
                        "name": "Groceries",
                        "color": "#22c55e",
                        "icon": "shopping-cart",
                        "amount": "500.00",
                    },
                    {
                        "category_id": None,
                        "name": "",
                        "color": "#9ca3af",
                        "icon": None,
                        "amount": "300.00",
                    },
                ],
            }
        ],
    }


def tag_spending_payload() -> dict[str, Any]:
    return {
        "tag_id": 3,
        "tag_name": "weekend",
        "start_date": None,
        "end_date": None,
        "total_amount": "800.00",
        "transaction_count": 5,
        "average_per_month": "400.00",
        "series": [{"year": 2026, "month": 11, "amount": "400.00"}],
    }


def insights_payload() -> dict[str, Any]:
    # The API's own compact shape: key + machine params, no text.
    # params mirrors insights_service exactly: count of idle accounts
    # and the threshold days from settings — never an account id.
    return {
        "alerts": [
            {"key": "idle_cash", "severity": "warning", "params": {"count": 2, "days": 75}}
        ]
    }


def advice_payload() -> dict[str, Any]:
    return {
        "items": [
            {
                "key": "rising_category",
                "tone": "warning",
                "params": {"category": "Dining", "percent": 34.2},
            }
        ]
    }


def net_worth_payload() -> dict[str, Any]:
    # series/colors/icons on purpose: compaction must drop the daily
    # series and every UI-only field, keeping the three breakdowns.
    return {
        "range": "30d",
        "current": "48250.00",
        "change_amount": "1200.00",
        "change_percent": 2.55,
        "series": [{"date": "2026-10-24", "value": "47050.00"}],
        "breakdown": [
            {
                "key": "cash",
                "name": "Cash",
                "color": "#38bdf8",
                "icon": "wallet",
                "amount": "5250.00",
                "percent": 10.88,
            }
        ],
        "capital_roles": [
            {
                "role": "income",
                "label": "Income",
                "color": "#22c55e",
                "total_value": "25000.00",
                "monthly_cash_flow": "0.00",
                "count": 1,
            }
        ],
        "risk_levels": [
            {
                "risk_level": "low",
                "label": "Low",
                "color": "#94a3b8",
                "total_value": "5250.00",
                "percent": 10.88,
                "items": [
                    {"key": "cash", "name": "Cash", "amount": "5250.00", "percent": 100.0}
                ],
            }
        ],
    }


def expected_full_month_window(months: int) -> tuple[str, str]:
    """The bounds suggest_budgets must average over, recomputed here on
    purpose: the test states the calendar semantics (full months only,
    ending with the previous one) instead of mirroring the helper."""
    today = date.today()
    end = date(today.year, today.month, 1) - timedelta(days=1)
    year, month = today.year, today.month
    for _ in range(months):
        year, month = (year - 1, 12) if month == 1 else (year, month - 1)
    return date(year, month, 1).isoformat(), end.isoformat()


def recurring_payload() -> list[dict[str, Any]]:
    # Extra UI fields on purpose: compaction must drop them and keep
    # the computed schedule fields instead.
    return [
        {
            "id": 2,
            "account_id": 1,
            "account_name": "Checking",
            "category_id": 4,
            "category_name": "Groceries",
            "category_color": "#22c55e",
            "category_icon": "shopping-cart",
            "transfer_account_id": None,
            "transfer_account_name": None,
            "type": "expense",
            "amount": "15.99",
            "description": "Netflix",
            "merchant": None,
            "notes": None,
            "frequency": "monthly",
            "anchor_date": "2026-01-05",
            "last_posted_date": "2026-11-05",
            "is_active": True,
            "next_due_date": "2026-12-05",
            "is_due": False,
            "days_until_due": 14,
        }
    ]


async def test_write_names_registry_is_exact(
    mock_client_factory: Any,
) -> None:
    client, _ = mock_client_factory(lambda request: httpx.Response(200, json=[]))
    bundle = build_tools(client)
    by_name = bundle_by_name(bundle)

    assert bundle.write_names == EXPECTED_WRITE_NAMES
    # A write name without a matching tool would break the router's trust.
    assert bundle.write_names <= set(by_name)


async def test_list_accounts_compacts_to_model_fields(mock_client_factory: Any) -> None:
    client, calls = mock_client_factory(lambda request: httpx.Response(200, json=account_payload()))
    bundle = build_tools(client)

    result = await bundle_by_name(bundle)["list_accounts"].ainvoke({})

    assert json.loads(result) == [
        {
            "id": 1,
            "name": "Checking",
            "type": "checking",
            "currency": "USD",
            "balance": "1523.40",
            "is_archived": False,
        }
    ]
    assert str(calls[0].url) == "http://test.local/api/accounts"
    # Archived accounts stay hidden without the explicit opt-in.
    assert "include_archived" not in calls[0].url.params


async def test_list_accounts_include_archived_param(mock_client_factory: Any) -> None:
    client, calls = mock_client_factory(lambda request: httpx.Response(200, json=[]))
    bundle = build_tools(client)

    await bundle_by_name(bundle)["list_accounts"].ainvoke({"include_archived": True})

    assert calls[0].url.params["include_archived"] == "true"


async def test_create_account_omits_unset_optionals(mock_client_factory: Any) -> None:
    client, calls = mock_client_factory(
        lambda request: httpx.Response(201, json=account_payload()[0])
    )
    bundle = build_tools(client)

    result = await bundle_by_name(bundle)["create_account"].ainvoke({"name": "Cash"})

    assert calls[0].method == "POST"
    assert body_of(calls[0]) == {"name": "Cash"}
    # The created object comes back compacted, not raw.
    assert json.loads(result)["name"] == "Checking"


async def test_update_account_sends_only_provided_fields(mock_client_factory: Any) -> None:
    client, calls = mock_client_factory(
        lambda request: httpx.Response(200, json=account_payload()[0])
    )
    bundle = build_tools(client)

    await bundle_by_name(bundle)["update_account"].ainvoke(
        {"account_id": 3, "name": "Wallet", "is_archived": True}
    )

    assert calls[0].method == "PATCH"
    assert str(calls[0].url) == "http://test.local/api/accounts/3"
    # is_archived=true travels with the rename; nothing else does.
    assert body_of(calls[0]) == {"name": "Wallet", "is_archived": True}


async def test_update_account_false_is_kept_not_dropped(mock_client_factory: Any) -> None:
    # False is a real value (unarchive), not "leave unchanged".
    client, calls = mock_client_factory(
        lambda request: httpx.Response(200, json=account_payload()[0])
    )
    bundle = build_tools(client)

    await bundle_by_name(bundle)["update_account"].ainvoke(
        {"account_id": 3, "is_archived": False}
    )

    assert body_of(calls[0]) == {"is_archived": False}


async def test_update_account_without_fields_makes_no_call(mock_client_factory: Any) -> None:
    client, calls = mock_client_factory(lambda request: httpx.Response(200, json={}))
    bundle = build_tools(client)

    result = await bundle_by_name(bundle)["update_account"].ainvoke({"account_id": 3})

    assert calls == []  # a no-op request would only confuse the backend
    assert "Nothing to update" in result


async def test_delete_account_reports_204_without_body(mock_client_factory: Any) -> None:
    client, calls = mock_client_factory(lambda request: httpx.Response(204))
    bundle = build_tools(client)

    result = await bundle_by_name(bundle)["delete_account"].ainvoke({"account_id": 5})

    assert calls[0].method == "DELETE"
    assert str(calls[0].url) == "http://test.local/api/accounts/5"
    assert "204" in result


async def test_list_categories_filters_by_kind(mock_client_factory: Any) -> None:
    payload = [
        {"id": 4, "name": "Groceries", "kind": "expense", "icon": "cart", "color": "#22c55e",
         "sort_order": 0, "parent_id": None, "is_default": True}
    ]
    client, calls = mock_client_factory(lambda request: httpx.Response(200, json=payload))
    bundle = build_tools(client)

    result = await bundle_by_name(bundle)["list_categories"].ainvoke({"kind": "expense"})

    assert calls[0].url.params["kind"] == "expense"
    assert json.loads(result) == [
        {"id": 4, "name": "Groceries", "kind": "expense", "parent_id": None, "is_default": True}
    ]


async def test_update_category_clear_parent_sends_explicit_null(
    mock_client_factory: Any,
) -> None:
    payload = {"id": 9, "name": "Sweets", "kind": "expense", "parent_id": None, "is_default": False}
    client, calls = mock_client_factory(lambda request: httpx.Response(200, json=payload))
    bundle = build_tools(client)

    await bundle_by_name(bundle)["update_category"].ainvoke(
        {"category_id": 9, "clear_parent": True}
    )

    # Omitted parent_id keeps the parent; explicit null detaches — two
    # different requests per DOCS.md, so the flag must produce null.
    assert body_of(calls[0]) == {"parent_id": None}


async def test_update_category_parent_value_passes_through(mock_client_factory: Any) -> None:
    payload = {"id": 9, "name": "Sweets", "kind": "expense", "parent_id": 4, "is_default": False}
    client, calls = mock_client_factory(lambda request: httpx.Response(200, json=payload))
    bundle = build_tools(client)

    await bundle_by_name(bundle)["update_category"].ainvoke(
        {"category_id": 9, "parent_id": 4}
    )

    assert body_of(calls[0]) == {"parent_id": 4}


async def test_create_tag_posts_name(mock_client_factory: Any) -> None:
    client, calls = mock_client_factory(
        lambda request: httpx.Response(201, json={"id": 2, "name": "Vacation"})
    )
    bundle = build_tools(client)

    result = await bundle_by_name(bundle)["create_tag"].ainvoke({"name": "Vacation"})

    assert calls[0].method == "POST"
    assert body_of(calls[0]) == {"name": "Vacation"}
    assert json.loads(result) == {"id": 2, "name": "Vacation"}


async def test_api_error_becomes_tool_text_not_exception(mock_client_factory: Any) -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(400, json={"detail": "Category 'Salary' is a income category"})

    client, _ = mock_client_factory(handler)
    bundle = build_tools(client)

    # The model must see the backend's own message to self-correct.
    result = await bundle_by_name(bundle)["create_tag"].ainvoke({"name": "x"})

    assert "API error (HTTP 400)" in result
    assert "income category" in result


async def test_validation_error_list_reaches_tool_text(mock_client_factory: Any) -> None:
    # 422 bodies carry a per-field list; the model needs it field-named.
    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(
            422,
            json={"detail": [{"loc": ["body", "name"], "msg": "Field required", "type": "missing"}]},
        )

    client, _ = mock_client_factory(handler)
    bundle = build_tools(client)

    result = await bundle_by_name(bundle)["create_category"].ainvoke(
        {"name": "x", "kind": "expense", "color": "#22c55e"}
    )

    assert "API error (HTTP 422)" in result
    assert "name: Field required" in result


async def test_transport_failure_reaches_tool_text(mock_client_factory: Any) -> None:
    # The stack being down must read as an actionable tool result, not
    # as an exception the graph has to catch.
    def handler(request: httpx.Request) -> httpx.Response:
        raise httpx.ConnectError("no route to host", request=request)

    client, _ = mock_client_factory(handler)
    bundle = build_tools(client)

    result = await bundle_by_name(bundle)["list_accounts"].ainvoke({})

    assert "API error (HTTP 0)" in result
    assert "Connection" in result


async def test_get_transaction_flattens_nested_names(mock_client_factory: Any) -> None:
    client, calls = mock_client_factory(
        lambda request: httpx.Response(200, json=transaction_payload())
    )
    bundle = build_tools(client)

    result = await bundle_by_name(bundle)["get_transaction"].ainvoke({"transaction_id": 7})

    assert str(calls[0].url) == "http://test.local/api/transactions/7"
    parsed = json.loads(result)
    assert parsed["account_name"] == "Cash"
    assert parsed["category_name"] == "Groceries"
    assert parsed["tags"] == ["weekend"]
    assert parsed["splits"] == []


async def test_get_transaction_compacts_splits(mock_client_factory: Any) -> None:
    payload = transaction_payload()
    payload["splits"] = [
        {
            "id": 1,
            "category_id": 12,
            "category": {"id": 12, "name": "Sweets", "kind": "expense", "color": "#f97316"},
            "amount": "60.00",
            "note": "Sweets",
        }
    ]
    client, _ = mock_client_factory(lambda request: httpx.Response(200, json=payload))
    bundle = build_tools(client)

    result = await bundle_by_name(bundle)["get_transaction"].ainvoke({"transaction_id": 7})

    # The split branch: nested category flattened, amount stays a string
    # Decimal, note passes through.
    assert json.loads(result)["splits"] == [
        {"category_name": "Sweets", "amount": "60.00", "note": "Sweets"}
    ]


async def test_search_transactions_builds_filters_and_keeps_pager(
    mock_client_factory: Any,
) -> None:
    page_payload = {
        "items": [transaction_payload()],
        "total": 43,
        "page": 2,
        "page_size": 20,
    }
    client, calls = mock_client_factory(lambda request: httpx.Response(200, json=page_payload))
    bundle = build_tools(client)

    result = await bundle_by_name(bundle)["search_transactions"].ainvoke(
        {
            "year": 2026,
            "month": 11,
            "account_id": 1,
            "type": "expense",
            "search": "coffee",
            "sort": "amount_desc",
            "page": 2,
        }
    )

    params = calls[0].url.params
    assert params["year"] == "2026"
    assert params["month"] == "11"
    assert params["account_id"] == "1"
    assert params["type"] == "expense"
    assert params["search"] == "coffee"
    assert params["sort"] == "amount_desc"
    assert params["page"] == "2"
    parsed = json.loads(result)
    # The pager fields tell the model whether more pages exist.
    assert parsed["total"] == 43
    assert parsed["page"] == 2
    assert parsed["page_size"] == 20
    assert parsed["items"][0]["description"] == "Groceries"


async def test_search_transactions_drops_unset_filters(mock_client_factory: Any) -> None:
    client, calls = mock_client_factory(lambda request: httpx.Response(200, json={"items": [], "total": 0}))
    bundle = build_tools(client)

    await bundle_by_name(bundle)["search_transactions"].ainvoke({})

    # Only the defaults travel; no "None" strings leak into the query.
    assert dict(calls[0].url.params) == {"page": "1", "page_size": "20"}


async def test_search_transactions_drops_blank_string_filters(
    mock_client_factory: Any,
) -> None:
    # "" or whitespace-only would fail backend validation — treat as unset.
    client, calls = mock_client_factory(lambda request: httpx.Response(200, json={"items": [], "total": 0}))
    bundle = build_tools(client)

    await bundle_by_name(bundle)["search_transactions"].ainvoke(
        {"search": "   ", "start_date": "", "end_date": " "}
    )

    assert dict(calls[0].url.params) == {"page": "1", "page_size": "20"}


async def test_search_transactions_date_range_and_id_filters(
    mock_client_factory: Any,
) -> None:
    client, calls = mock_client_factory(lambda request: httpx.Response(200, json={"items": [], "total": 0}))
    bundle = build_tools(client)

    await bundle_by_name(bundle)["search_transactions"].ainvoke(
        {
            "start_date": "2026-11-01",
            "end_date": "2026-11-30",
            "category_id": 4,
            "tag_id": 3,
        }
    )

    params = dict(calls[0].url.params)
    assert params["start_date"] == "2026-11-01"
    assert params["end_date"] == "2026-11-30"
    assert params["category_id"] == "4"
    assert params["tag_id"] == "3"


async def test_create_transaction_income_body(mock_client_factory: Any) -> None:
    client, calls = mock_client_factory(
        lambda request: httpx.Response(201, json=transaction_payload())
    )
    bundle = build_tools(client)

    await bundle_by_name(bundle)["create_transaction"].ainvoke(
        {
            "account_id": 1,
            "type": "expense",
            "amount": 42.5,
            "description": "Groceries",
            "date": "2026-11-21",
            "category_id": 4,
            "tag_ids": [3],
        }
    )

    assert calls[0].method == "POST"
    assert body_of(calls[0]) == {
        "account_id": 1,
        "type": "expense",
        "amount": 42.5,
        "description": "Groceries",
        "date": "2026-11-21",
        "category_id": 4,
        "tag_ids": [3],
    }


async def test_create_transaction_transfer_omits_category(mock_client_factory: Any) -> None:
    client, calls = mock_client_factory(
        lambda request: httpx.Response(201, json=transaction_payload())
    )
    bundle = build_tools(client)

    await bundle_by_name(bundle)["create_transaction"].ainvoke(
        {
            "account_id": 1,
            "type": "transfer",
            "amount": 100.0,
            "description": "Move to savings",
            "date": "2026-11-21",
            "transfer_account_id": 2,
        }
    )

    # A transfer must not carry a category — omitted, not null.
    assert body_of(calls[0]) == {
        "account_id": 1,
        "type": "transfer",
        "amount": 100.0,
        "description": "Move to savings",
        "date": "2026-11-21",
        "transfer_account_id": 2,
    }


async def test_update_transaction_clear_flags_send_nulls(mock_client_factory: Any) -> None:
    client, calls = mock_client_factory(
        lambda request: httpx.Response(200, json=transaction_payload())
    )
    bundle = build_tools(client)

    await bundle_by_name(bundle)["update_transaction"].ainvoke(
        {"transaction_id": 7, "type": "expense", "clear_category": True, "clear_transfer": True}
    )

    # The backend's exclude_unset treats null as "clear", omit as "keep";
    # the flags must produce the nulls.
    assert body_of(calls[0]) == {
        "type": "expense",
        "category_id": None,
        "transfer_account_id": None,
    }


async def test_update_transaction_clear_flags_win_over_ids(mock_client_factory: Any) -> None:
    client, calls = mock_client_factory(
        lambda request: httpx.Response(200, json=transaction_payload())
    )
    bundle = build_tools(client)

    await bundle_by_name(bundle)["update_transaction"].ainvoke(
        {"transaction_id": 7, "category_id": 5, "clear_category": True}
    )

    assert body_of(calls[0]) == {"category_id": None}


async def test_update_transaction_empty_tag_list_replaces_set(mock_client_factory: Any) -> None:
    # An empty list is a real value ("remove all tags"), not "unset" —
    # _omit_none must keep it.
    client, calls = mock_client_factory(
        lambda request: httpx.Response(200, json=transaction_payload())
    )
    bundle = build_tools(client)

    await bundle_by_name(bundle)["update_transaction"].ainvoke(
        {"transaction_id": 7, "tag_ids": []}
    )

    assert body_of(calls[0]) == {"tag_ids": []}


async def test_delete_transaction_path_and_204(mock_client_factory: Any) -> None:
    client, calls = mock_client_factory(lambda request: httpx.Response(204))
    bundle = build_tools(client)

    result = await bundle_by_name(bundle)["delete_transaction"].ainvoke({"transaction_id": 9})

    assert calls[0].method == "DELETE"
    assert str(calls[0].url) == "http://test.local/api/transactions/9"
    assert "204" in result


async def test_list_budgets_compacts_to_model_fields(mock_client_factory: Any) -> None:
    client, calls = mock_client_factory(lambda request: httpx.Response(200, json=budget_payload()))
    bundle = build_tools(client)

    result = await bundle_by_name(bundle)["list_budgets"].ainvoke({})

    # color/icon are UI-only and must not reach the model's context.
    assert json.loads(result) == [
        {"id": 1, "category_id": 4, "category_name": "Groceries", "monthly_limit": "500.00"}
    ]
    assert str(calls[0].url) == "http://test.local/api/budgets"


async def test_budget_status_passes_period_and_compacts_items(mock_client_factory: Any) -> None:
    client, calls = mock_client_factory(
        lambda request: httpx.Response(200, json=budget_status_payload())
    )
    bundle = build_tools(client)

    result = await bundle_by_name(bundle)["get_budget_status"].ainvoke({"year": 2026, "month": 11})

    assert calls[0].url.params["year"] == "2026"
    assert calls[0].url.params["month"] == "11"
    parsed = json.loads(result)
    assert parsed["year"] == 2026
    # percent > 100 with is_over_budget=true stays honest — the model
    # reports overspending as it is.
    assert parsed["items"] == [
        {
            "budget_id": 1,
            "category_id": 4,
            "category_name": "Groceries",
            "monthly_limit": "500.00",
            "spent": "612.30",
            "remaining": "-112.30",
            "percent": 122.46,
            "is_over_budget": True,
        }
    ]


async def test_budget_status_omits_unset_period(mock_client_factory: Any) -> None:
    client, calls = mock_client_factory(
        lambda request: httpx.Response(200, json=budget_status_payload())
    )
    bundle = build_tools(client)

    await bundle_by_name(bundle)["get_budget_status"].ainvoke({})

    # No period travel: the backend defaults to the current month.
    assert dict(calls[0].url.params) == {}


async def test_create_budget_body_and_compacted_answer(mock_client_factory: Any) -> None:
    client, calls = mock_client_factory(
        lambda request: httpx.Response(201, json=budget_payload()[0])
    )
    bundle = build_tools(client)

    result = await bundle_by_name(bundle)["create_budget"].ainvoke(
        {"category_id": 4, "monthly_limit": 500.0}
    )

    assert calls[0].method == "POST"
    assert str(calls[0].url) == "http://test.local/api/budgets"
    assert body_of(calls[0]) == {"category_id": 4, "monthly_limit": 500.0}
    assert json.loads(result)["category_name"] == "Groceries"


async def test_update_budget_sends_limit_only(mock_client_factory: Any) -> None:
    client, calls = mock_client_factory(
        lambda request: httpx.Response(200, json=budget_payload()[0])
    )
    bundle = build_tools(client)

    await bundle_by_name(bundle)["update_budget"].ainvoke({"budget_id": 1, "monthly_limit": 600.0})

    assert calls[0].method == "PATCH"
    assert str(calls[0].url) == "http://test.local/api/budgets/1"
    assert body_of(calls[0]) == {"monthly_limit": 600.0}


async def test_delete_budget_path_and_204(mock_client_factory: Any) -> None:
    client, calls = mock_client_factory(lambda request: httpx.Response(204))
    bundle = build_tools(client)

    result = await bundle_by_name(bundle)["delete_budget"].ainvoke({"budget_id": 1})

    assert calls[0].method == "DELETE"
    assert str(calls[0].url) == "http://test.local/api/budgets/1"
    assert "204" in result


async def test_list_goals_passes_compact_rows_through(mock_client_factory: Any) -> None:
    client, calls = mock_client_factory(lambda request: httpx.Response(200, json=goal_payload()))
    bundle = build_tools(client)

    result = await bundle_by_name(bundle)["list_goals"].ainvoke({})

    # GoalRead is already model-sized; no compaction layer on purpose.
    assert json.loads(result) == goal_payload()
    assert str(calls[0].url) == "http://test.local/api/goals"


async def test_create_goal_omits_unset_target_date(mock_client_factory: Any) -> None:
    client, calls = mock_client_factory(
        lambda request: httpx.Response(201, json=goal_payload()[0])
    )
    bundle = build_tools(client)

    await bundle_by_name(bundle)["create_goal"].ainvoke(
        {"name": "Emergency fund", "target_amount": 10000.0}
    )

    assert calls[0].method == "POST"
    # Omitted target_date stays omitted — an open-ended goal.
    assert body_of(calls[0]) == {"name": "Emergency fund", "target_amount": 10000.0}


async def test_create_goal_with_target_date_sends_it(mock_client_factory: Any) -> None:
    client, calls = mock_client_factory(
        lambda request: httpx.Response(201, json=goal_payload()[0])
    )
    bundle = build_tools(client)

    await bundle_by_name(bundle)["create_goal"].ainvoke(
        {"name": "Emergency fund", "target_amount": 10000.0, "target_date": "2027-01-01"}
    )

    assert body_of(calls[0]) == {
        "name": "Emergency fund",
        "target_amount": 10000.0,
        "target_date": "2027-01-01",
    }


async def test_update_goal_clear_target_date_sends_explicit_null(
    mock_client_factory: Any,
) -> None:
    client, calls = mock_client_factory(
        lambda request: httpx.Response(200, json=goal_payload()[0])
    )
    bundle = build_tools(client)

    await bundle_by_name(bundle)["update_goal"].ainvoke({"goal_id": 1, "clear_target_date": True})

    # Omitted target_date keeps the deadline; explicit null clears it —
    # two different requests per the backend's exclude_unset rule.
    assert body_of(calls[0]) == {"target_date": None}


async def test_update_goal_clear_wins_over_value(mock_client_factory: Any) -> None:
    client, calls = mock_client_factory(
        lambda request: httpx.Response(200, json=goal_payload()[0])
    )
    bundle = build_tools(client)

    await bundle_by_name(bundle)["update_goal"].ainvoke(
        {"goal_id": 1, "target_date": "2027-06-01", "clear_target_date": True}
    )

    assert body_of(calls[0]) == {"target_date": None}


async def test_update_goal_without_fields_makes_no_call(mock_client_factory: Any) -> None:
    client, calls = mock_client_factory(lambda request: httpx.Response(200, json={}))
    bundle = build_tools(client)

    result = await bundle_by_name(bundle)["update_goal"].ainvoke({"goal_id": 1})

    assert calls == []
    assert "Nothing to update" in result


async def test_add_goal_contribution_body_omits_unset_note(
    mock_client_factory: Any,
) -> None:
    client, calls = mock_client_factory(
        lambda request: httpx.Response(201, json=goal_payload()[0])
    )
    bundle = build_tools(client)

    await bundle_by_name(bundle)["add_goal_contribution"].ainvoke(
        {"goal_id": 1, "amount": 250.0, "date": "2026-11-21"}
    )

    assert calls[0].method == "POST"
    assert str(calls[0].url) == "http://test.local/api/goals/1/contributions"
    assert body_of(calls[0]) == {"amount": 250.0, "date": "2026-11-21"}


async def test_add_goal_contribution_negative_amount_travels_as_is(
    mock_client_factory: Any,
) -> None:
    # A withdrawal is a negative contribution — the tool must not
    # touch the sign, only the backend knows what it means.
    client, calls = mock_client_factory(
        lambda request: httpx.Response(201, json=goal_payload()[0])
    )
    bundle = build_tools(client)

    await bundle_by_name(bundle)["add_goal_contribution"].ainvoke(
        {"goal_id": 1, "amount": -250.0, "date": "2026-11-21", "note": "Pullback"}
    )

    assert body_of(calls[0]) == {"amount": -250.0, "date": "2026-11-21", "note": "Pullback"}


async def test_delete_goal_path_and_204(mock_client_factory: Any) -> None:
    client, calls = mock_client_factory(lambda request: httpx.Response(204))
    bundle = build_tools(client)

    result = await bundle_by_name(bundle)["delete_goal"].ainvoke({"goal_id": 1})

    assert calls[0].method == "DELETE"
    assert str(calls[0].url) == "http://test.local/api/goals/1"
    assert "204" in result


async def test_dashboard_summary_pins_period_and_compacts_breakdown(
    mock_client_factory: Any,
) -> None:
    client, calls = mock_client_factory(lambda request: httpx.Response(200, json=dashboard_payload()))
    bundle = build_tools(client)

    result = await bundle_by_name(bundle)["get_dashboard_summary"].ainvoke({"year": 2026, "month": 11})

    # With params on the wire the full string carries the query —
    # pin the path and the params separately.
    assert calls[0].url.path == "/api/dashboard/summary"
    assert calls[0].url.params["year"] == "2026"
    assert calls[0].url.params["month"] == "11"
    parsed = json.loads(result)
    # color/icon dropped on both levels; the children rollup stays.
    assert parsed["spending_by_category"] == [
        {
            "category_id": 4,
            "name": "Groceries",
            "amount": "612.30",
            "percent": 19.6,
            "children": [{"category_id": 5, "name": "Snacks", "amount": "112.30"}],
        }
    ]
    assert parsed["net"] == "2079.55"


async def test_dashboard_summary_omits_unset_period(mock_client_factory: Any) -> None:
    client, calls = mock_client_factory(lambda request: httpx.Response(200, json=dashboard_payload()))
    bundle = build_tools(client)

    await bundle_by_name(bundle)["get_dashboard_summary"].ainvoke({})

    # No period travel: the backend defaults to the current month.
    assert dict(calls[0].url.params) == {}


async def test_cash_flow_passes_dates_and_body_as_is(mock_client_factory: Any) -> None:
    client, calls = mock_client_factory(lambda request: httpx.Response(200, json=cash_flow_payload()))
    bundle = build_tools(client)

    result = await bundle_by_name(bundle)["get_cash_flow"].ainvoke(
        {"start_date": "2026-01-01", "end_date": "2026-11-30"}
    )

    assert calls[0].url.path == "/api/cash-flow"
    assert calls[0].url.params["start_date"] == "2026-01-01"
    assert calls[0].url.params["end_date"] == "2026-11-30"
    # The response is already model-sized: no compaction layer.
    assert json.loads(result) == cash_flow_payload()


async def test_cash_flow_blank_dates_are_not_sent(mock_client_factory: Any) -> None:
    client, calls = mock_client_factory(lambda request: httpx.Response(200, json=cash_flow_payload()))
    bundle = build_tools(client)

    await bundle_by_name(bundle)["get_cash_flow"].ainvoke({"start_date": " ", "end_date": ""})

    # A blank date is "not provided" — the same rule as search filters.
    assert dict(calls[0].url.params) == {}


async def test_category_spending_pins_category_and_compacts(mock_client_factory: Any) -> None:
    client, calls = mock_client_factory(
        lambda request: httpx.Response(200, json=category_spending_payload())
    )
    bundle = build_tools(client)

    result = await bundle_by_name(bundle)["get_category_spending"].ainvoke({"category_id": 4})

    assert calls[0].url.path == "/api/reports/category-spending"
    assert calls[0].url.params["category_id"] == "4"
    # category_color/category_icon dropped; the series stays intact.
    parsed = json.loads(result)
    assert parsed["category_name"] == "Groceries"
    assert "category_color" not in parsed
    assert parsed["series"][0] == {"year": 2026, "month": 10, "amount": "306.15"}


async def test_category_ranking_sends_kind_and_compacts_items(mock_client_factory: Any) -> None:
    client, calls = mock_client_factory(
        lambda request: httpx.Response(200, json=category_ranking_payload())
    )
    bundle = build_tools(client)

    result = await bundle_by_name(bundle)["get_category_ranking"].ainvoke({})

    # kind defaults to 'expense' and travels explicitly.
    assert calls[0].url.params["kind"] == "expense"
    parsed = json.loads(result)
    # An empty children list is dropped, not passed through as noise.
    assert parsed["items"] == [
        {
            "category_id": 4,
            "name": "Groceries",
            "amount": "612.30",
            "percent": 19.6,
            "transaction_count": 14,
        }
    ]


async def test_tag_ranking_keeps_totals_and_compacts_categories(mock_client_factory: Any) -> None:
    client, calls = mock_client_factory(lambda request: httpx.Response(200, json=tag_ranking_payload()))
    bundle = build_tools(client)

    result = await bundle_by_name(bundle)["get_tag_ranking"].ainvoke({"kind": "income"})

    assert calls[0].url.params["kind"] == "income"
    parsed = json.loads(result)
    # tagged_amount stays: with total_amount it frames how much of the
    # period the report actually covers.
    assert parsed["tagged_amount"] == "1200.00"
    assert parsed["items"] == [
        {
            "tag_id": 3,
            "name": "weekend",
            "amount": "800.00",
            "percent": 25.6,
            "transaction_count": 5,
            "categories": [
                {"category_id": 4, "name": "Groceries", "amount": "500.00"},
                {"category_id": None, "name": "", "amount": "300.00"},
            ],
        }
    ]


async def test_tag_spending_pins_tag_and_kind(mock_client_factory: Any) -> None:
    client, calls = mock_client_factory(lambda request: httpx.Response(200, json=tag_spending_payload()))
    bundle = build_tools(client)

    result = await bundle_by_name(bundle)["get_tag_spending"].ainvoke({"tag_id": 3})

    assert calls[0].url.path == "/api/reports/tag-spending"
    assert calls[0].url.params["tag_id"] == "3"
    # kind defaults to 'expense' and travels explicitly.
    assert calls[0].url.params["kind"] == "expense"
    assert json.loads(result)["tag_name"] == "weekend"


async def test_insights_passes_alerts_through(mock_client_factory: Any) -> None:
    client, calls = mock_client_factory(lambda request: httpx.Response(200, json=insights_payload()))
    bundle = build_tools(client)

    result = await bundle_by_name(bundle)["get_insights"].ainvoke({})

    assert str(calls[0].url) == "http://test.local/api/insights/alerts"
    # key+params IS the payload — wording is the model's job.
    assert json.loads(result) == insights_payload()


async def test_advice_passes_items_through(mock_client_factory: Any) -> None:
    client, calls = mock_client_factory(lambda request: httpx.Response(200, json=advice_payload()))
    bundle = build_tools(client)

    result = await bundle_by_name(bundle)["get_advice"].ainvoke({})

    assert str(calls[0].url) == "http://test.local/api/advice"
    assert json.loads(result) == advice_payload()


async def test_net_worth_passes_range_and_compacts(mock_client_factory: Any) -> None:
    client, calls = mock_client_factory(
        lambda request: httpx.Response(200, json=net_worth_payload())
    )
    bundle = build_tools(client)

    result = await bundle_by_name(bundle)["get_net_worth"].ainvoke({"range": "90d"})

    assert calls[0].url.path == "/api/net-worth/summary"
    assert calls[0].url.params["range"] == "90d"
    parsed = json.loads(result)
    # The headline and the three breakdowns survive; the daily series
    # and every color/icon do not.
    assert parsed["current"] == "48250.00"
    assert parsed["change_amount"] == "1200.00"
    assert parsed["breakdown"] == [
        {"key": "cash", "name": "Cash", "amount": "5250.00", "percent": 10.88}
    ]
    assert parsed["capital_roles"] == [
        {
            "role": "income",
            "label": "Income",
            "total_value": "25000.00",
            "monthly_cash_flow": "0.00",
            "count": 1,
        }
    ]
    assert parsed["risk_levels"] == [
        {
            "risk_level": "low",
            "label": "Low",
            "total_value": "5250.00",
            "percent": 10.88,
            "items": [
                {"key": "cash", "name": "Cash", "amount": "5250.00", "percent": 100.0}
            ],
        }
    ]
    assert "series" not in parsed


async def test_net_worth_defaults_to_30d(mock_client_factory: Any) -> None:
    client, calls = mock_client_factory(
        lambda request: httpx.Response(200, json=net_worth_payload())
    )
    bundle = build_tools(client)

    await bundle_by_name(bundle)["get_net_worth"].ainvoke({})

    assert calls[0].url.params["range"] == "30d"


async def test_suggest_budgets_averages_and_marks_existing(
    mock_client_factory: Any,
) -> None:
    ranking = {
        "start_date": None,
        "end_date": None,
        "total_amount": "4273.80",
        "items": [
            {
                "category_id": 4,
                "name": "Groceries",
                "color": "#22c55e",
                "icon": "shopping-cart",
                "amount": "3673.80",
                "percent": 85.97,
                "transaction_count": 84,
                "children": [],
            },
            {
                "category_id": 7,
                "name": "Dining",
                "color": "#f97316",
                "icon": "utensils",
                "amount": "600.00",
                "percent": 14.03,
                "transaction_count": 21,
                "children": [],
            },
        ],
    }

    def handler(request: httpx.Request) -> httpx.Response:
        if request.url.path == "/api/budgets":
            return httpx.Response(200, json=budget_payload())
        return httpx.Response(200, json=ranking)

    client, calls = mock_client_factory(handler)
    bundle = build_tools(client)

    result = await bundle_by_name(bundle)["suggest_budgets"].ainvoke({"months": 6})

    # Two reads: the limits first, then the ranking bounded to the window.
    assert [call.url.path for call in calls] == [
        "/api/budgets",
        "/api/reports/category-ranking",
    ]
    ranking_params = calls[1].url.params
    assert ranking_params["kind"] == "expense"
    assert ranking_params["start_date"] == expected_full_month_window(6)[0]
    assert ranking_params["end_date"] == expected_full_month_window(6)[1]
    parsed = json.loads(result)
    assert parsed["months"] == 6
    # 3673.80 / 6 = 612.30, rounded up to the next 10 → 620; the
    # existing 500 limit rides along for an update_budget comparison.
    assert parsed["items"][0] == {
        "category_id": 4,
        "name": "Groceries",
        "total_amount": "3673.80",
        "average_per_month": "612.30",
        "suggested_limit": "620.00",
        "has_budget": True,
        "current_limit": "500.00",
    }
    # 600.00 / 6 = 100 exactly — the step rounding must not inflate it.
    assert parsed["items"][1] == {
        "category_id": 7,
        "name": "Dining",
        "total_amount": "600.00",
        "average_per_month": "100.00",
        "suggested_limit": "100.00",
        "has_budget": False,
        "current_limit": None,
    }


async def test_suggest_budgets_skips_zero_spending(mock_client_factory: Any) -> None:
    ranking = {
        "start_date": None,
        "end_date": None,
        "total_amount": "0.00",
        "items": [
            {
                "category_id": 4,
                "name": "Groceries",
                "color": "#22c55e",
                "icon": "shopping-cart",
                "amount": "0.00",
                "percent": 0.0,
                "transaction_count": 0,
                "children": [],
            }
        ],
    }

    def handler(request: httpx.Request) -> httpx.Response:
        if request.url.path == "/api/budgets":
            return httpx.Response(200, json=[])
        return httpx.Response(200, json=ranking)

    client, _ = mock_client_factory(handler)
    bundle = build_tools(client)

    result = await bundle_by_name(bundle)["suggest_budgets"].ainvoke({})

    # Zero spend has no average worth suggesting a limit from.
    assert json.loads(result)["items"] == []


async def test_suggest_budgets_rejects_out_of_range_months(
    mock_client_factory: Any,
) -> None:
    client, calls = mock_client_factory(lambda request: httpx.Response(200, json=[]))
    bundle = build_tools(client)

    for months in (0, -1, 25):
        result = await bundle_by_name(bundle)["suggest_budgets"].ainvoke({"months": months})
        assert result == "months must be between 1 and 24."

    # The guard fires before any request travels.
    assert calls == []


async def test_suggest_budgets_error_becomes_tool_text(mock_client_factory: Any) -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(500, json={"detail": "boom"})

    client, _ = mock_client_factory(handler)
    bundle = build_tools(client)

    result = await bundle_by_name(bundle)["suggest_budgets"].ainvoke({})

    # This tool fetches via client.request directly, so its own except
    # must produce the same model-facing text shape as `call`'s.
    assert "API error (HTTP 500)" in result
    assert "boom" in result


async def test_savings_forecast_amount_and_contribution(mock_client_factory: Any) -> None:
    client, calls = mock_client_factory(lambda request: httpx.Response(200, json=[]))
    bundle = build_tools(client)

    result = await bundle_by_name(bundle)["savings_forecast"].ainvoke(
        {"target_amount": 6750.0, "monthly_contribution": 500.0}
    )

    # Pure calculator: no API behind this shape.
    assert calls == []
    parsed = json.loads(result)
    assert parsed["target_amount"] == "6750.00"
    assert parsed["monthly_contribution"] == "500.00"
    # 6750 / 500 = 13.5 — the half month still has to be waited out.
    assert parsed["months_needed"] == 14
    today = date.today()
    total = today.year * 12 + (today.month - 1) + 14
    assert parsed["reached_on"] == f"{total // 12:04d}-{total % 12 + 1:02d}"


async def test_savings_forecast_amount_and_target_date(mock_client_factory: Any) -> None:
    client, _ = mock_client_factory(lambda request: httpx.Response(200, json=[]))
    bundle = build_tools(client)

    today = date.today()
    due = date(today.year + 1, today.month, 1)  # exactly 12 months out
    result = await bundle_by_name(bundle)["savings_forecast"].ainvoke(
        {"target_amount": 1200.0, "target_date": due.isoformat()}
    )

    parsed = json.loads(result)
    assert parsed["months_available"] == 12
    # 1200 / 12 = 100 exactly — the cent ceiling must not inflate it.
    assert parsed["required_monthly"] == "100.00"


async def test_savings_forecast_ceils_required_monthly_to_cent(
    mock_client_factory: Any,
) -> None:
    client, _ = mock_client_factory(lambda request: httpx.Response(200, json=[]))
    bundle = build_tools(client)

    today = date.today()
    total = today.year * 12 + (today.month - 1) + 3
    due = date(total // 12, total % 12 + 1, 1)  # 3 months out
    result = await bundle_by_name(bundle)["savings_forecast"].ainvoke(
        {"target_amount": 100.0, "target_date": due.isoformat()}
    )

    # 100 / 3 = 33.33… — a cent short would miss the target, so up.
    assert json.loads(result)["required_monthly"] == "33.34"


async def test_savings_forecast_goal_uses_remaining(mock_client_factory: Any) -> None:
    client, calls = mock_client_factory(lambda request: httpx.Response(200, json=goal_payload()))
    bundle = build_tools(client)

    result = await bundle_by_name(bundle)["savings_forecast"].ainvoke(
        {"goal_id": 1, "monthly_contribution": 500.0}
    )

    assert str(calls[0].url) == "http://test.local/api/goals"
    parsed = json.loads(result)
    # The goal's remaining (10000 - 3250) is the target, not its full
    # amount — the log already holds the 3250.
    assert parsed["goal"] == {"id": 1, "name": "Emergency fund", "remaining": "6750.00"}
    assert parsed["months_needed"] == 14


async def test_savings_forecast_reached_goal_says_so(mock_client_factory: Any) -> None:
    reached = [
        dict(goal_payload()[0], current_amount="10000.00", remaining="0.00", is_reached=True)
    ]
    client, _ = mock_client_factory(lambda request: httpx.Response(200, json=reached))
    bundle = build_tools(client)

    result = await bundle_by_name(bundle)["savings_forecast"].ainvoke(
        {"goal_id": 1, "monthly_contribution": 500.0}
    )

    assert "already reached" in result


async def test_savings_forecast_unknown_goal(mock_client_factory: Any) -> None:
    client, _ = mock_client_factory(lambda request: httpx.Response(200, json=[]))
    bundle = build_tools(client)

    result = await bundle_by_name(bundle)["savings_forecast"].ainvoke(
        {"goal_id": 99, "monthly_contribution": 500.0}
    )

    assert result == "No goal with id 99."


async def test_savings_forecast_requires_one_target(mock_client_factory: Any) -> None:
    client, calls = mock_client_factory(lambda request: httpx.Response(200, json=[]))
    bundle = build_tools(client)

    neither = await bundle_by_name(bundle)["savings_forecast"].ainvoke(
        {"monthly_contribution": 500.0}
    )
    both = await bundle_by_name(bundle)["savings_forecast"].ainvoke(
        {"goal_id": 1, "target_amount": 1000.0, "monthly_contribution": 500.0}
    )

    assert neither == both == "Pass exactly one of goal_id or target_amount."
    assert calls == []


async def test_savings_forecast_requires_one_contribution_mode(
    mock_client_factory: Any,
) -> None:
    client, _ = mock_client_factory(lambda request: httpx.Response(200, json=[]))
    bundle = build_tools(client)

    none_given = await bundle_by_name(bundle)["savings_forecast"].ainvoke(
        {"target_amount": 1000.0}
    )
    two_given = await bundle_by_name(bundle)["savings_forecast"].ainvoke(
        {"target_amount": 1000.0, "monthly_contribution": 5.0, "use_average_net": True}
    )

    assert none_given == two_given == (
        "Pass exactly one of monthly_contribution, target_date or use_average_net=true."
    )


async def test_savings_forecast_blank_target_date_is_unset(mock_client_factory: Any) -> None:
    # "" or whitespace is "not provided" — the same blank rule as the
    # list filters; it must not hit the future-month guard as a date.
    client, calls = mock_client_factory(lambda request: httpx.Response(200, json=[]))
    bundle = build_tools(client)

    result = await bundle_by_name(bundle)["savings_forecast"].ainvoke(
        {"target_amount": 1000.0, "monthly_contribution": 250.0, "target_date": "  "}
    )

    assert calls == []  # contribution mode: no request needed
    assert json.loads(result)["months_needed"] == 4


async def test_savings_forecast_rejects_nonpositive_inputs(
    mock_client_factory: Any,
) -> None:
    client, _ = mock_client_factory(lambda request: httpx.Response(200, json=[]))
    bundle = build_tools(client)

    zero = await bundle_by_name(bundle)["savings_forecast"].ainvoke(
        {"target_amount": 1000.0, "monthly_contribution": 0.0}
    )
    negative = await bundle_by_name(bundle)["savings_forecast"].ainvoke(
        {"target_amount": -5.0, "monthly_contribution": 10.0}
    )

    assert zero == "monthly_contribution must be positive."
    assert negative == "target_amount must be positive."


async def test_savings_forecast_target_date_validation(mock_client_factory: Any) -> None:
    client, _ = mock_client_factory(lambda request: httpx.Response(200, json=[]))
    bundle = build_tools(client)

    today = date.today()
    past = await bundle_by_name(bundle)["savings_forecast"].ainvoke(
        {"target_amount": 1000.0, "target_date": today.isoformat()}
    )
    malformed = await bundle_by_name(bundle)["savings_forecast"].ainvoke(
        {"target_amount": 1000.0, "target_date": "next month"}
    )

    # The current month is still being written — it is not available.
    assert past == "target_date must be in a future month."
    assert malformed == "target_date must be 'YYYY-MM-DD'."


async def test_savings_forecast_average_net_grounding(mock_client_factory: Any) -> None:
    flow = {
        "start_date": None,
        "end_date": None,
        "points": [
            {"year": 2026, "month": month, "income": "4000.00", "expense": "3700.00", "net": "300.00"}
            for month in range(5, 11)
        ],
        "total_income": "24000.00",
        "total_expense": "22200.00",
        "total_net": "1800.00",
    }

    def handler(request: httpx.Request) -> httpx.Response:
        if request.url.path == "/api/goals":
            return httpx.Response(200, json=goal_payload())
        return httpx.Response(200, json=flow)

    client, calls = mock_client_factory(handler)
    bundle = build_tools(client)

    result = await bundle_by_name(bundle)["savings_forecast"].ainvoke(
        {"goal_id": 1, "use_average_net": True}
    )

    # The grounding window is the last 6 full months — same bounds as
    # suggest_budgets, and the cash-flow call is bounded by them.
    assert calls[1].url.path == "/api/cash-flow"
    assert calls[1].url.params["start_date"] == expected_full_month_window(6)[0]
    assert calls[1].url.params["end_date"] == expected_full_month_window(6)[1]
    parsed = json.loads(result)
    # 1800 over 6 points → 300/month; 6750 at 300 → 22.5 → 23 months.
    assert parsed["average_net_monthly"] == "300.00"
    assert parsed["window_months"] == 6
    assert parsed["monthly_contribution"] == "300.00"
    assert parsed["months_needed"] == 23


async def test_savings_forecast_negative_average_net(mock_client_factory: Any) -> None:
    flow = {
        "start_date": None,
        "end_date": None,
        "points": [
            {"year": 2026, "month": month, "income": "3000.00", "expense": "3100.00", "net": "-100.00"}
            for month in range(5, 11)
        ],
        "total_income": "18000.00",
        "total_expense": "18600.00",
        "total_net": "-600.00",
    }

    def handler(request: httpx.Request) -> httpx.Response:
        if request.url.path == "/api/goals":
            return httpx.Response(200, json=goal_payload())
        return httpx.Response(200, json=flow)

    client, _ = mock_client_factory(handler)
    bundle = build_tools(client)

    result = await bundle_by_name(bundle)["savings_forecast"].ainvoke(
        {"goal_id": 1, "use_average_net": True}
    )

    # Spending above income is a situation to report, not a negative
    # months figure to compute with.
    assert "nothing can be saved" in result
    assert "-100.00" in result


async def test_savings_forecast_no_history_for_average(mock_client_factory: Any) -> None:
    # A shape today's bounded cash-flow cannot produce (zero-filled
    # months always come back as points) — the test pins the
    # defensive branch for the day that contract shifts.
    def handler(request: httpx.Request) -> httpx.Response:
        if request.url.path == "/api/goals":
            return httpx.Response(200, json=goal_payload())
        return httpx.Response(
            200,
            json={"points": [], "total_income": "0.00", "total_expense": "0.00", "total_net": "0.00"},
        )

    client, _ = mock_client_factory(handler)
    bundle = build_tools(client)

    result = await bundle_by_name(bundle)["savings_forecast"].ainvoke(
        {"goal_id": 1, "use_average_net": True}
    )

    assert "nothing to average" in result


async def test_list_recurring_compacts_to_model_fields(mock_client_factory: Any) -> None:
    client, calls = mock_client_factory(lambda request: httpx.Response(200, json=recurring_payload()))
    bundle = build_tools(client)

    result = await bundle_by_name(bundle)["list_recurring"].ainvoke({})

    assert str(calls[0].url) == "http://test.local/api/recurring"
    # color/icon dropped; the computed schedule fields stay.
    assert json.loads(result) == [
        {
            "id": 2,
            "account_id": 1,
            "account_name": "Checking",
            "category_id": 4,
            "category_name": "Groceries",
            "transfer_account_id": None,
            "transfer_account_name": None,
            "type": "expense",
            "amount": "15.99",
            "description": "Netflix",
            "merchant": None,
            "notes": None,
            "frequency": "monthly",
            "anchor_date": "2026-01-05",
            "last_posted_date": "2026-11-05",
            "is_active": True,
            "next_due_date": "2026-12-05",
            "is_due": False,
            "days_until_due": 14,
        }
    ]


async def test_create_recurring_body_and_compacted_answer(mock_client_factory: Any) -> None:
    client, calls = mock_client_factory(
        lambda request: httpx.Response(201, json=recurring_payload()[0])
    )
    bundle = build_tools(client)

    result = await bundle_by_name(bundle)["create_recurring"].ainvoke(
        {
            "account_id": 1,
            "type": "expense",
            "amount": 15.99,
            "description": "Netflix",
            "frequency": "monthly",
            "anchor_date": "2026-01-05",
            "category_id": 4,
        }
    )

    assert calls[0].method == "POST"
    assert str(calls[0].url) == "http://test.local/api/recurring"
    assert body_of(calls[0]) == {
        "account_id": 1,
        "type": "expense",
        "amount": 15.99,
        "description": "Netflix",
        "frequency": "monthly",
        "anchor_date": "2026-01-05",
        "category_id": 4,
    }
    assert json.loads(result)["next_due_date"] == "2026-12-05"


async def test_update_recurring_keeps_false_is_active(mock_client_factory: Any) -> None:
    client, calls = mock_client_factory(
        lambda request: httpx.Response(200, json=recurring_payload()[0])
    )
    bundle = build_tools(client)

    result = await bundle_by_name(bundle)["update_recurring"].ainvoke(
        {"recurring_id": 2, "is_active": False}
    )

    assert calls[0].method == "PATCH"
    assert str(calls[0].url) == "http://test.local/api/recurring/2"
    # False is a real value (a pause), not "leave unchanged" — it
    # must travel, unlike None.
    assert body_of(calls[0]) == {"is_active": False}
    # The mock's canned answer, untouched by the patch body above.
    assert json.loads(result)["is_active"] is True


async def test_update_recurring_without_fields_makes_no_call(mock_client_factory: Any) -> None:
    client, calls = mock_client_factory(lambda request: httpx.Response(200, json={}))
    bundle = build_tools(client)

    result = await bundle_by_name(bundle)["update_recurring"].ainvoke({"recurring_id": 2})

    assert calls == []
    assert "Nothing to update" in result


async def test_delete_recurring_path_and_204(mock_client_factory: Any) -> None:
    client, calls = mock_client_factory(lambda request: httpx.Response(204))
    bundle = build_tools(client)

    result = await bundle_by_name(bundle)["delete_recurring"].ainvoke({"recurring_id": 2})

    assert calls[0].method == "DELETE"
    assert str(calls[0].url) == "http://test.local/api/recurring/2"
    assert "204" in result


async def test_post_recurring_path_returns_advanced_template(mock_client_factory: Any) -> None:
    client, calls = mock_client_factory(
        lambda request: httpx.Response(201, json=recurring_payload()[0])
    )
    bundle = build_tools(client)

    result = await bundle_by_name(bundle)["post_recurring"].ainvoke({"recurring_id": 2})

    # The /post endpoint answers with the TEMPLATE's new state, so
    # the compacted result talks schedule, not the new transaction.
    assert calls[0].method == "POST"
    assert calls[0].url.path == "/api/recurring/2/post"
    parsed = json.loads(result)
    assert parsed["last_posted_date"] == "2026-11-05"
    assert parsed["next_due_date"] == "2026-12-05"


@pytest.mark.parametrize(
    ("tool_name", "is_write"),
    [
        ("list_accounts", False),
        ("create_account", True),
        ("update_account", True),
        ("delete_account", True),
        ("list_categories", False),
        ("create_category", True),
        ("update_category", True),
        ("delete_category", True),
        ("list_tags", False),
        ("create_tag", True),
        ("get_transaction", False),
        ("search_transactions", False),
        ("create_transaction", True),
        ("update_transaction", True),
        ("delete_transaction", True),
        ("list_budgets", False),
        ("get_budget_status", False),
        ("create_budget", True),
        ("update_budget", True),
        ("delete_budget", True),
        ("list_goals", False),
        ("create_goal", True),
        ("update_goal", True),
        ("delete_goal", True),
        ("add_goal_contribution", True),
        ("get_dashboard_summary", False),
        ("get_cash_flow", False),
        ("get_category_spending", False),
        ("get_category_ranking", False),
        ("get_tag_ranking", False),
        ("get_tag_spending", False),
        ("get_insights", False),
        ("get_advice", False),
        ("get_net_worth", False),
        ("suggest_budgets", False),
        ("savings_forecast", False),
        ("list_recurring", False),
        ("create_recurring", True),
        ("update_recurring", True),
        ("delete_recurring", True),
        ("post_recurring", True),
    ],
)
async def test_every_tool_is_classified(
    mock_client_factory: Any, tool_name: str, is_write: bool
) -> None:
    # Pins the read/write split for each tool — the router depends on it.
    client, _ = mock_client_factory(lambda request: httpx.Response(200, json=[]))
    bundle = build_tools(client)
    assert (tool_name in bundle.write_names) is is_write
    assert tool_name in bundle_by_name(bundle)
