"""Duplicate-finder tests: matching rules, degradation, request shape."""

from __future__ import annotations

import json
from datetime import date
from typing import Any

import httpx

from aurum_agent.dedup import (
    DUPLICATE_PAGE_SIZE,
    find_duplicates,
    find_duplicates_for_recurring,
)


def backend_row(row_id: int, amount: str, description: str) -> dict[str, Any]:
    """A TransactionRead-shaped row the API could return for the search."""
    return {
        "id": row_id,
        "type": "expense",
        "amount": amount,
        "description": description,
        "date": "2026-11-21",
        "account": {"id": 1, "name": "Cash"},
        "category": {"id": 4, "name": "Groceries"},
    }


def page_of(*rows: dict[str, Any]) -> httpx.Response:
    return httpx.Response(200, json={"items": list(rows), "total": len(rows)})


async def test_exact_match_is_found(mock_client_factory: Any) -> None:
    # Amount arrives from the model as a float; the backend answers
    # with a string Decimal — both must normalize to the same cents.
    client, _ = mock_client_factory(lambda request: page_of(backend_row(7, "42.50", "Кофе")))

    duplicates = await find_duplicates(
        client, date="2026-11-21", amount=42.5, description="кофе"
    )

    assert len(duplicates) == 1
    assert duplicates[0]["id"] == 7
    assert duplicates[0]["account_name"] == "Cash"
    assert duplicates[0]["category_name"] == "Groceries"


async def test_amount_mismatch_is_not_a_duplicate(mock_client_factory: Any) -> None:
    # One cent off is a different purchase as far as doubling goes.
    client, _ = mock_client_factory(lambda request: page_of(backend_row(8, "42.51", "Кофе")))

    duplicates = await find_duplicates(
        client, date="2026-11-21", amount=42.5, description="Кофе"
    )

    assert duplicates == []


async def test_description_mismatch_is_not_a_duplicate(mock_client_factory: Any) -> None:
    # "Кофе и круассан" merely CONTAINS "кофе" (API search semantics);
    # a duplicate must have the same description, not a shared word.
    client, _ = mock_client_factory(
        lambda request: page_of(backend_row(9, "42.50", "Кофе и круассан"))
    )

    duplicates = await find_duplicates(
        client, date="2026-11-21", amount=42.5, description="Кофе"
    )

    assert duplicates == []


async def test_request_is_scoped_to_the_one_date(mock_client_factory: Any) -> None:
    client, calls = mock_client_factory(lambda request: page_of())

    await find_duplicates(client, date="2026-11-21", amount=42.5, description="Кофе")

    params = dict(calls[0].url.params)
    assert params["start_date"] == "2026-11-21"
    assert params["end_date"] == "2026-11-21"
    assert params["search"] == "Кофе"
    assert params["page"] == "1"
    assert params["page_size"] == str(DUPLICATE_PAGE_SIZE)


async def test_transport_error_degrades_to_no_matches(mock_client_factory: Any) -> None:
    # The stack being down must not block a confirmation with an
    # exception — the preview just loses its duplicate warning.
    def handler(request: httpx.Request) -> httpx.Response:
        raise httpx.ConnectError("down", request=request)

    client, _ = mock_client_factory(handler)

    duplicates = await find_duplicates(
        client, date="2026-11-21", amount=42.5, description="Кофе"
    )

    assert duplicates == []


async def test_api_error_degrades_to_no_matches(mock_client_factory: Any) -> None:
    # E.g. a validation 422 or 404 from a misrouted proxy.
    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(422, json={"detail": [{"loc": ["body", "search"], "msg": "short"}]})

    client, _ = mock_client_factory(handler)

    duplicates = await find_duplicates(
        client, date="2026-11-21", amount=42.5, description="Кофе"
    )

    assert duplicates == []


async def test_unexpected_body_shape_degrades_to_no_matches(mock_client_factory: Any) -> None:
    client, _ = mock_client_factory(lambda request: httpx.Response(200, json=[1, 2, 3]))

    duplicates = await find_duplicates(
        client, date="2026-11-21", amount=42.5, description="Кофе"
    )

    assert duplicates == []


async def test_whitespace_and_case_are_ignored_in_description(
    mock_client_factory: Any,
) -> None:
    client, _ = mock_client_factory(lambda request: page_of(backend_row(7, "42.50", "  КОФЕ ")))

    duplicates = await find_duplicates(
        client, date="2026-11-21", amount=42.5, description=" кофе "
    )

    assert len(duplicates) == 1


async def test_garbage_amount_degrades_to_no_matches(mock_client_factory: Any) -> None:
    # Raw model output can carry "42,50" or null — the check must not
    # crash the confirmation path with a ValueError/TypeError.
    client, _ = mock_client_factory(lambda request: page_of(backend_row(7, "42.50", "Кофе")))

    assert await find_duplicates(client, date="2026-11-21", amount="42,50", description="Кофе") == []
    assert await find_duplicates(client, date="2026-11-21", amount=None, description="Кофе") == []


async def test_missing_description_degrades_to_no_matches(mock_client_factory: Any) -> None:
    # And without an HTTP round trip — there is nothing to match on.
    client, calls = mock_client_factory(lambda request: page_of())

    assert await find_duplicates(client, date="2026-11-21", amount=42.5, description=None) == []
    assert await find_duplicates(client, date="2026-11-21", amount=42.5, description="   ") == []
    assert calls == []


async def test_items_of_unexpected_type_degrades_to_no_matches(
    mock_client_factory: Any,
) -> None:
    client, _ = mock_client_factory(
        lambda request: httpx.Response(200, json={"items": 5, "total": 5})
    )

    assert await find_duplicates(client, date="2026-11-21", amount=42.5, description="Кофе") == []


async def test_row_with_unparseable_amount_is_skipped_not_fatal(
    mock_client_factory: Any,
) -> None:
    good = backend_row(7, "42.50", "Кофе")
    bad = backend_row(8, None, "Кофе")
    bad["amount"] = None
    client, _ = mock_client_factory(lambda request: page_of(bad, good))

    duplicates = await find_duplicates(
        client, date="2026-11-21", amount=42.5, description="Кофе"
    )

    assert [row["id"] for row in duplicates] == [7]


def netflix_template() -> dict[str, Any]:
    """A RecurringTransactionRead-shaped row the list endpoint could return."""
    return {
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
        "last_posted_date": None,
        "is_active": True,
        "next_due_date": "2026-12-05",
        "is_due": False,
        "days_until_due": 14,
    }


def recurring_list(*templates: dict[str, Any]) -> httpx.Response:
    return httpx.Response(200, json=list(templates))


async def test_recurring_post_finds_today_duplicate(mock_client_factory: Any) -> None:
    # Posting writes a transaction dated today — the template's
    # amount/description are matched against today's rows.
    def handler(request: httpx.Request) -> httpx.Response:
        if request.url.path == "/api/recurring":
            return recurring_list(netflix_template())
        return page_of(backend_row(7, "15.99", "Netflix"))

    client, calls = mock_client_factory(handler)

    duplicates = await find_duplicates_for_recurring(client, recurring_id=2)

    assert [row["id"] for row in duplicates] == [7]
    # The transaction search is scoped to today, the post date.
    search = calls[1]
    assert dict(search.url.params)["start_date"] == date.today().isoformat()
    assert dict(search.url.params)["end_date"] == date.today().isoformat()


async def test_recurring_unknown_id_makes_no_search(mock_client_factory: Any) -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        return recurring_list(netflix_template())  # id 2 only

    client, calls = mock_client_factory(handler)

    assert await find_duplicates_for_recurring(client, recurring_id=99) == []
    # One request total (the template list) — no doomed search.
    assert len(calls) == 1


async def test_recurring_list_error_degrades_to_no_matches(mock_client_factory: Any) -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(500, json={"detail": "boom"})

    client, _ = mock_client_factory(handler)

    assert await find_duplicates_for_recurring(client, recurring_id=2) == []


async def test_recurring_garbage_id_degrades_to_no_matches(mock_client_factory: Any) -> None:
    # A raw model-issued id (None, a string) matches nothing.
    client, calls = mock_client_factory(lambda request: recurring_list(netflix_template()))

    assert await find_duplicates_for_recurring(client, recurring_id=None) == []
    assert await find_duplicates_for_recurring(client, recurring_id="2") == []
    # Each attempt still fetched the list before finding no match.
    assert len(calls) == 2
