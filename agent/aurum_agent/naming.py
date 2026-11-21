"""Resolve the id arguments of a pending batch into display names.

The pending-write payload travels to two frontends — the terminal REPL
and the web Assistant page — and its ``args`` are the model's raw
proposal: honest, but ``account_id=3`` is unreadable. This module turns
the id arguments into names once, in the graph's prepare node (whose
result is checkpointed, so a resume never refetches), and both frontends
render the ``names`` map when the payload carries it. The lookup is
advisory only — a failing one degrades to the raw id and never blocks a
confirmation, the same rule as the duplicate warning (see dedup.py).
"""

from __future__ import annotations

from typing import Any

from .api_client import AurumApiError, AurumClient
from .tools import PATH_ACCOUNTS, PATH_CATEGORIES, PATH_TAGS

# Arg keys this module knows how to resolve, grouped by what their ids
# point at. The target of update_account/delete_account is the account
# (or category) itself, so its ``account_id``/``category_id`` resolves
# too: «Удалить счёт „Карта"» instead of «Удалить счёт 3».
ACCOUNT_KEYS = ("account_id", "transfer_account_id")
CATEGORY_KEYS = ("category_id", "parent_id")
# One arg holding a whole list of ids: the tags of a transaction.
TAG_LIST_KEY = "tag_ids"


def _collect_ids(bucket: set[int], args: dict[str, Any], keys: tuple[str, ...]) -> None:
    """Add every int id found under ``keys`` to ``bucket``.

    Tool-call args arrive from the model as ad-hoc JSON, so anything
    non-int (a hallucinated string id, null, a bool) is skipped rather
    than trusted — ``True`` is an int subclass and must not sneak in as
    id 1.
    """
    for key in keys:
        value = args.get(key)
        if isinstance(value, int) and not isinstance(value, bool):
            bucket.add(value)


async def _id_to_name(
    client: AurumClient,
    path: str,
    ids: set[int],
    *,
    params: dict[str, Any] | None = None,
) -> dict[int, str]:
    """``{id: name}`` for the wanted ids, or ``{}`` when none are.

    Nothing wanted means no request at all. Failures degrade to an empty
    map (see find_names); the body is checked, not trusted — the list
    endpoints answer rows, but a proxy page or a future shape change
    must not crash the preview.
    """
    if not ids:
        return {}
    try:
        payload = await client.request("GET", path, params=params)
    except AurumApiError:
        return {}
    if not isinstance(payload, list):
        return {}
    names: dict[int, str] = {}
    for item in payload:
        if not isinstance(item, dict):
            continue
        item_id = item.get("id")
        item_name = item.get("name")
        if (
            isinstance(item_id, int)
            and not isinstance(item_id, bool)
            and isinstance(item_name, str)
        ):
            names[item_id] = item_name
    return names


def _put_name(names: dict[str, str], args: dict[str, Any], key: str, known: dict[int, str]) -> None:
    """Record ``key``'s display name when its id is a known one."""
    value = args.get(key)
    if isinstance(value, int) and not isinstance(value, bool) and value in known:
        names[key] = known[value]


async def find_names(
    client: AurumClient,
    calls: list[dict[str, Any]],
) -> dict[str, dict[str, str]]:
    """Display names for a pending batch, keyed by tool-call id.

    ``calls`` are the model's write tool_calls (id/name/args). The
    return maps each call id to the arg keys this module could resolve:
    ``{"call_1": {"account_id": "Карта", "tag_ids": "кофе, книги"}}``.
    Raw tool-call arguments, transport failures, API errors and odd
    response bodies all degrade to "no names" — a failing lookup must
    never block the user's confirmation, the card simply shows the raw
    ids it cannot resolve. Calls with nothing resolved are omitted, so
    the payload carries no empty maps.
    """
    account_ids: set[int] = set()
    category_ids: set[int] = set()
    tag_ids: set[int] = set()
    for call in calls:
        args = call.get("args")
        if not isinstance(args, dict):
            continue
        _collect_ids(account_ids, args, ACCOUNT_KEYS)
        _collect_ids(category_ids, args, CATEGORY_KEYS)
        value = args.get(TAG_LIST_KEY)
        if isinstance(value, list):
            for item in value:
                if isinstance(item, int) and not isinstance(item, bool):
                    tag_ids.add(item)

    # Archived accounts must resolve too — update_account can touch
    # them, and a preview naming the row it is about to change is the
    # whole point of the exercise.
    accounts = await _id_to_name(
        client, PATH_ACCOUNTS, account_ids, params={"include_archived": "true"}
    )
    categories = await _id_to_name(client, PATH_CATEGORIES, category_ids)
    tags = await _id_to_name(client, PATH_TAGS, tag_ids)

    resolved: dict[str, dict[str, str]] = {}
    for call in calls:
        args = call.get("args")
        names: dict[str, str] = {}
        if isinstance(args, dict):
            for key in ACCOUNT_KEYS:
                _put_name(names, args, key, accounts)
            for key in CATEGORY_KEYS:
                _put_name(names, args, key, categories)
            # All or nothing: half-named tags next to raw ids would read
            # as two different fields. Every id must resolve, or the
            # whole key stays raw. An empty list replaces the tag set
            # with nothing — there are no names to show, so it stays
            # raw too.
            value = args.get(TAG_LIST_KEY)
            if (
                isinstance(value, list)
                and value
                and all(
                    isinstance(item, int) and not isinstance(item, bool) and item in tags
                    for item in value
                )
            ):
                names[TAG_LIST_KEY] = ", ".join(tags[item] for item in value)
        call_id = call.get("id")
        if names and isinstance(call_id, str):
            resolved[call_id] = names
    return resolved
