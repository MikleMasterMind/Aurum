"""Default chart periods on /api/settings — the only parts of the settings
surface this change touched: the seeded defaults surface through GET, a
partial PATCH rewrites exactly one chart's period and leaves the others
untouched, and the Literal unions reject values the corresponding page's
selector doesn't offer (including "custom", which needs live years).
"""
from httpx import AsyncClient


async def test_get_settings_returns_seeded_chart_range_defaults(client: AsyncClient):
    resp = await client.get("/settings")
    assert resp.status_code == 200
    body = resp.json()
    # The values the pages hardcoded before the setting existed — anything
    # else would silently change behavior on upgrade.
    assert body["default_net_worth_range"] == "5y"
    assert body["default_cash_flow_range"] == "this_year"
    assert body["default_reports_range"] == "all"
    assert body["default_crypto_range"] == "all"


async def test_patch_updates_one_chart_range_and_persists(client: AsyncClient):
    resp = await client.patch("/settings", json={"default_net_worth_range": "all"})
    assert resp.status_code == 200
    body = resp.json()
    assert body["default_net_worth_range"] == "all"
    # A single-field PATCH must leave the other charts (and the unrelated
    # thresholds) exactly as they were — same exclude_unset contract as the
    # rest of the settings card.
    assert body["default_cash_flow_range"] == "this_year"
    assert body["default_reports_range"] == "all"
    assert body["default_crypto_range"] == "all"
    assert body["negative_cash_flow_threshold_months"] == 2

    # And it survives a fresh read, i.e. the value actually hit the DB.
    refetched = (await client.get("/settings")).json()
    assert refetched["default_net_worth_range"] == "all"


async def test_patch_accepts_every_period_each_page_offers(client: AsyncClient):
    # One value per chart, chosen different from the seeded default, so a
    # union that's missing a page's pill fails here instead of 422ing in
    # the UI when the user picks it.
    resp = await client.patch(
        "/settings",
        json={
            "default_net_worth_range": "30d",
            "default_cash_flow_range": "5y",
            "default_reports_range": "this_year",
            "default_crypto_range": "7d",
        },
    )
    assert resp.status_code == 200, resp.text
    body = resp.json()
    assert body["default_net_worth_range"] == "30d"
    assert body["default_cash_flow_range"] == "5y"
    assert body["default_reports_range"] == "this_year"
    assert body["default_crypto_range"] == "7d"


async def test_patch_rejects_period_the_page_does_not_offer(client: AsyncClient):
    # Each chart's union is its own: a valid crypto pill isn't valid for
    # net worth, and vice versa.
    resp = await client.patch("/settings", json={"default_net_worth_range": "7d"})
    assert resp.status_code == 422
    resp = await client.patch("/settings", json={"default_crypto_range": "1y"})
    assert resp.status_code == 422
    resp = await client.patch("/settings", json={"default_cash_flow_range": "nonsense"})
    assert resp.status_code == 422


async def test_patch_rejects_custom_as_a_stored_default(client: AsyncClient):
    # "custom" is a live-only choice — it needs the years entered on the
    # page, so storing it as a default would open the chart on nothing.
    for field in ("default_cash_flow_range", "default_reports_range"):
        resp = await client.patch("/settings", json={field: "custom"})
        assert resp.status_code == 422, field
