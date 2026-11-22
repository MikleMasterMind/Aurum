"""Aurum terminal AI agent (blocks 1-2: finance, planning, analytics).

A standalone local CLI that talks to a running Aurum instance over its
REST API (see DOCS.md) — accounts, categories, tags, transactions,
budgets, goals, recurring templates, reports and insights — driven by
an LLM through LangChain/LangGraph tool calling. Every write operation
requires an explicit terminal confirmation before it runs.
"""
