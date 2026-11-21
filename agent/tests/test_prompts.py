"""System prompt tests: session facts and the non-negotiable rules."""

from __future__ import annotations

from aurum_agent.prompts import build_system_prompt


def test_prompt_includes_session_facts() -> None:
    prompt = build_system_prompt(today="2026-11-21", currency="USD")

    assert "Today is 2026-11-21" in prompt
    assert "USD" in prompt


def test_prompt_pins_confirmation_etiquette() -> None:
    prompt = build_system_prompt(today="2026-11-21", currency="RUB")

    # No silent retries of declined writes, and duplicate warnings are
    # the user's call — both are the graph's contracts restated.
    assert "declines" in prompt
    assert "duplicate" in prompt
    assert "never guess" in prompt


def test_prompt_pins_budget_and_goal_rules() -> None:
    prompt = build_system_prompt(today="2026-11-21", currency="USD")

    # Budget questions go to the status endpoint, not to manual sums;
    # goal progress is contribution-log arithmetic, never a settable
    # balance — both rules mirror what the API actually allows.
    assert "get_budget_status" in prompt
    assert "contributions" in prompt
    assert "monthly limit per expense category" in prompt


def test_prompt_pins_analytics_rules() -> None:
    prompt = build_system_prompt(today="2026-11-21", currency="USD")

    # Spend questions go to the aggregation endpoints first; insights
    # and advice carry key+params, so the model words them itself.
    assert "get_dashboard_summary" in prompt
    assert "instead of paging through" in prompt
    assert "key+params" in prompt
