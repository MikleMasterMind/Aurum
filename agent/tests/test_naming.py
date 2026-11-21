"""Name-resolver tests: resolution rules, degradation, request shape."""

from __future__ import annotations

from collections.abc import Callable
from typing import Any

import httpx

from aurum_agent.naming import find_names


def call(call_id: str, args: dict[str, Any]) -> dict[str, Any]:
    """One pending write call, the shape the graph's prepare passes in."""
    return {"id": call_id, "name": "create_transaction", "args": args}


def listing(*rows: dict[str, Any]) -> httpx.Response:
    return httpx.Response(200, json=list(rows))


def make_handler(
    *,
    accounts: httpx.Response | None = None,
    categories: httpx.Response | None = None,
    tags: httpx.Response | None = None,
) -> Callable[[httpx.Request], httpx.Response]:
    """Serve the three listings by path; anything else is a 404."""

    def handler(request: httpx.Request) -> httpx.Response:
        if request.url.path == "/api/accounts":
            return accounts or listing()
        if request.url.path == "/api/categories":
            return categories or listing()
        if request.url.path == "/api/tags":
            return tags or listing()
        return httpx.Response(404, json={"detail": "no such route"})

    return handler


async def test_account_and_category_ids_resolve(mock_client_factory: Any) -> None:
    client, _ = mock_client_factory(
        make_handler(
            accounts=listing({"id": 1, "name": "Карта"}),
            categories=listing({"id": 4, "name": "Продукты"}),
        )
    )

    resolved = await find_names(client, [call("c1", {"account_id": 1, "category_id": 4})])

    assert resolved == {"c1": {"account_id": "Карта", "category_id": "Продукты"}}


async def test_transfer_and_parent_keys_resolve(mock_client_factory: Any) -> None:
    # The transfer's destination is an account, a subcategory's parent
    # is a category — same registries, other arg keys.
    client, _ = mock_client_factory(
        make_handler(
            accounts=listing({"id": 2, "name": "Наличные"}),
            categories=listing({"id": 4, "name": "Еда"}),
        )
    )

    resolved = await find_names(
        client, [call("c1", {"account_id": 1, "transfer_account_id": 2, "parent_id": 4})]
    )

    # account_id=1 is not in the listing — only the known ids resolve.
    assert resolved == {"c1": {"transfer_account_id": "Наличные", "parent_id": "Еда"}}


async def test_tags_resolve_as_one_joined_label(mock_client_factory: Any) -> None:
    client, _ = mock_client_factory(
        make_handler(
            accounts=listing({"id": 1, "name": "Карта"}),
            tags=listing({"id": 3, "name": "кофе"}, {"id": 7, "name": "книги"}),
        )
    )

    resolved = await find_names(client, [call("c1", {"account_id": 1, "tag_ids": [3, 7]})])

    assert resolved == {"c1": {"account_id": "Карта", "tag_ids": "кофе, книги"}}


async def test_partially_known_tags_stay_raw(mock_client_factory: Any) -> None:
    # Half-named tags would read as two different fields — all or
    # nothing is the rule.
    client, _ = mock_client_factory(
        make_handler(tags=listing({"id": 3, "name": "кофе"}))
    )

    resolved = await find_names(client, [call("c1", {"tag_ids": [3, 99]})])

    assert resolved == {}


async def test_empty_tag_list_is_left_raw(mock_client_factory: Any) -> None:
    # [] means "replace the tag set with nothing" — there are no names
    # to show, so no request happens either.
    client, calls = mock_client_factory(make_handler())

    resolved = await find_names(client, [call("c1", {"tag_ids": []})])

    assert resolved == {}
    assert calls == []


async def test_accounts_request_includes_archived(mock_client_factory: Any) -> None:
    # update_account can touch an archived row, and the preview must
    # name the row it is about to change.
    client, calls = mock_client_factory(make_handler())

    await find_names(client, [call("c1", {"account_id": 1})])

    params = dict(calls[0].url.params)
    assert params["include_archived"] == "true"


async def test_api_error_degrades_per_listing(mock_client_factory: Any) -> None:
    # A failing accounts read must not take the category names down
    # with it — each listing degrades on its own.
    client, _ = mock_client_factory(
        make_handler(
            accounts=httpx.Response(500, json={"detail": "boom"}),
            categories=listing({"id": 4, "name": "Продукты"}),
        )
    )

    resolved = await find_names(client, [call("c1", {"account_id": 1, "category_id": 4})])

    assert resolved == {"c1": {"category_id": "Продукты"}}


async def test_transport_error_degrades_to_no_names(mock_client_factory: Any) -> None:
    # The stack being down must not block a confirmation with an
    # exception — the card simply keeps its raw ids.
    def handler(request: httpx.Request) -> httpx.Response:
        raise httpx.ConnectError("down", request=request)

    client, _ = mock_client_factory(handler)

    resolved = await find_names(client, [call("c1", {"account_id": 1})])

    assert resolved == {}


async def test_unexpected_body_shape_degrades_to_no_names(mock_client_factory: Any) -> None:
    # A dict where rows were expected — the shape is checked, not
    # trusted.
    client, _ = mock_client_factory(make_handler(accounts=httpx.Response(200, json={"oops": True})))

    resolved = await find_names(client, [call("c1", {"account_id": 1})])

    assert resolved == {}


async def test_rows_with_garbage_fields_are_skipped(mock_client_factory: Any) -> None:
    # No id, no name, a bool id — anything unusable just doesn't
    # resolve; the usable row next to it still does.
    client, _ = mock_client_factory(
        make_handler(
            accounts=listing(
                {"id": 1, "name": "Карта"},
                {"name": "Безымянный"},
                {"id": 2},
                {"id": True, "name": "Ложный"},
            )
        )
    )

    resolved = await find_names(client, [call("c1", {"account_id": 1, "transfer_account_id": 2})])

    assert resolved == {"c1": {"account_id": "Карта"}}


async def test_garbage_args_are_ignored_not_fatal(mock_client_factory: Any) -> None:
    # Raw model output can carry "abc" or null where an int belongs —
    # nothing resolves, nothing crashes, no pointless requests.
    client, calls = mock_client_factory(
        make_handler(accounts=listing({"id": 1, "name": "Карта"}))
    )

    resolved = await find_names(
        client,
        [
            call("c1", {"account_id": "abc", "category_id": None}),
            call("c2", {"tag_ids": "не список"}),
            # A bool is an int subclass — it must not sneak in as id 1.
            call("c3", {"tag_ids": [True, "не id"]}),
            {"id": "c4", "name": "update_account", "args": "не словарь"},
        ],
    )

    assert resolved == {}
    # Nothing worth a request was in the batch — no HTTP round trips.
    assert calls == []


async def test_call_without_resolvable_names_is_omitted(mock_client_factory: Any) -> None:
    # No empty maps in the payload: a call that resolved nothing is
    # simply absent, and the renderer falls back to raw args.
    client, _ = mock_client_factory(
        make_handler(accounts=listing({"id": 1, "name": "Карта"}))
    )

    resolved = await find_names(
        client,
        [
            call("c1", {"account_id": 1}),
            call("c2", {"account_id": 99}),
        ],
    )

    assert resolved == {"c1": {"account_id": "Карта"}}


async def test_no_id_arguments_means_no_requests(mock_client_factory: Any) -> None:
    # create_tag carries only a name — a batch of nothing to resolve
    # costs no HTTP round trips at all.
    client, calls = mock_client_factory(make_handler())

    resolved = await find_names(client, [call("c1", {"name": "кофе"})])

    assert resolved == {}
    assert calls == []


async def test_only_writes_given_are_scanned(mock_client_factory: Any) -> None:
    # The caller hands in the write calls it already filtered; the
    # resolver trusts that and scans exactly what it got.
    client, calls = mock_client_factory(make_handler(accounts=listing({"id": 1, "name": "Карта"})))

    resolved = await find_names(client, [call("c1", {"account_id": 1})])

    assert resolved == {"c1": {"account_id": "Карта"}}
    assert len(calls) == 1
