"""App-wide configuration that isn't tied to any single account/asset — a
single-row table (id is always 1). Primary display currency (see UPDATES.md
for why this doesn't do currency conversion) and the proactive-alert
thresholds consumed by services/insights_service.py."""
from decimal import Decimal

from sqlalchemy import Integer, Numeric, String
from sqlalchemy.orm import Mapped, mapped_column

from app.db.base import Base


class AppSettings(Base):
    __tablename__ = "app_settings"

    id: Mapped[int] = mapped_column(primary_key=True)
    currency: Mapped[str] = mapped_column(String(3), nullable=False, default="USD")
    # Consecutive complete months of negative cash flow / declining net worth
    # before insights_service.py raises the corresponding alert.
    negative_cash_flow_threshold_months: Mapped[int] = mapped_column(Integer, nullable=False, default=2)
    net_worth_decline_threshold_months: Mapped[int] = mapped_column(Integer, nullable=False, default=2)
    # Max % of total capital (cash + assets) allowed in medium/high risk
    # tiers before insights_service.py raises risky_allocation_exceeded —
    # the classic "80% at zero risk, 20% at most exposed" rule.
    risky_allocation_threshold_percent: Mapped[int] = mapped_column(Integer, nullable=False, default=20)
    # A depository account (checking/savings/cash) sitting at or above this
    # balance with no transaction touching it in idle_cash_threshold_days
    # raises insights_service.py's idle_cash alert — money that isn't
    # working. In the app's display currency (see `currency` above).
    idle_cash_threshold_amount: Mapped[Decimal] = mapped_column(Numeric(14, 2), nullable=False, default=Decimal("1000"))
    idle_cash_threshold_days: Mapped[int] = mapped_column(Integer, nullable=False, default=60)
    # Which period each page's chart opens with. The string choices mirror
    # the frontend's per-page selector types exactly (NetWorthRange /
    # RangePreset / CryptoRange in frontend/src/types/index.ts) — the
    # schemas/settings.py Literal unions are the single validation point, so
    # a value that isn't one of the page's own pills can never be stored.
    # "custom" is deliberately not among the cash-flow/report choices: it
    # only makes sense picked live, where the user also enters the years.
    default_net_worth_range: Mapped[str] = mapped_column(String(10), nullable=False, default="5y")
    default_cash_flow_range: Mapped[str] = mapped_column(String(10), nullable=False, default="this_year")
    default_reports_range: Mapped[str] = mapped_column(String(10), nullable=False, default="all")
    default_crypto_range: Mapped[str] = mapped_column(String(8), nullable=False, default="all")
