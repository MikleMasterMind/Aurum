from decimal import Decimal
from typing import Literal

from pydantic import BaseModel, ConfigDict, Field

from app.core.config import APP_VERSION

# Exactly the periods the corresponding page's own selector offers (see
# frontend/src/types/index.ts). The model defaults in models/settings.py
# intentionally mirror the pages' pre-setting hardcoded behavior ("5y",
# "this_year", "all", "all") rather than the first choice of each union —
# an upgrade must not silently change what the charts open with.
NetWorthRangeChoice = Literal["30d", "90d", "1y", "5y", "all"]
# No "custom": it needs the years entered live on the page, so it can't be
# a stored default that must show data the moment the page opens.
DateRangeChoice = Literal["all", "this_year", "5y"]
CryptoRangeChoice = Literal["7d", "30d", "90d", "all"]


class AppSettingsRead(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    currency: str
    negative_cash_flow_threshold_months: int
    net_worth_decline_threshold_months: int
    risky_allocation_threshold_percent: int
    idle_cash_threshold_amount: Decimal
    idle_cash_threshold_days: int
    default_net_worth_range: str
    default_cash_flow_range: str
    default_reports_range: str
    default_crypto_range: str
    # Not a stored column: the default fills itself in when FastAPI validates
    # the ORM row against this model, so neither route has to assemble it.
    # It lives on this (authenticated) response rather than on /api/health,
    # which is deliberately unauthenticated and so would hand the running
    # version to anyone who can reach the instance.
    app_version: str = APP_VERSION


class AppSettingsUpdate(BaseModel):
    """All fields optional — the route applies a partial update
    (`exclude_unset`), same as CategoryUpdate, so a single-field PATCH from
    e.g. CurrencyCard doesn't need to resend the alert thresholds."""

    # ISO 4217 code, e.g. "USD"/"UAH"/"EUR" — the frontend only ever sends
    # values from its curated currency list, but validate the shape anyway
    # since Intl.NumberFormat would otherwise silently accept garbage.
    currency: str | None = Field(default=None, min_length=3, max_length=3, pattern=r"^[A-Z]{3}$")
    # Consecutive complete months before the corresponding alert fires.
    # Capped at 24 to match insights_service.py's MAX_LOOKBACK_MONTHS.
    negative_cash_flow_threshold_months: int | None = Field(default=None, ge=1, le=24)
    net_worth_decline_threshold_months: int | None = Field(default=None, ge=1, le=24)
    # Max % of capital allowed in medium/high risk tiers (the 80/20 rule's
    # "20% at most exposed" half) before risky_allocation_exceeded fires.
    risky_allocation_threshold_percent: int | None = Field(default=None, ge=1, le=100)
    # Balance (in the app's display currency) and days of no activity a
    # depository account needs to hit before idle_cash fires.
    idle_cash_threshold_amount: Decimal | None = Field(default=None, ge=0, max_digits=14, decimal_places=2)
    idle_cash_threshold_days: int | None = Field(default=None, ge=1, le=365)
    # Period the corresponding chart opens with. Validated against the
    # Literal unions above so the stored value always matches one of the
    # page's own selector pills.
    default_net_worth_range: NetWorthRangeChoice | None = None
    default_cash_flow_range: DateRangeChoice | None = None
    default_reports_range: DateRangeChoice | None = None
    default_crypto_range: CryptoRangeChoice | None = None
