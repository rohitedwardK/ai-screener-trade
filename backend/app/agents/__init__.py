"""Agentic layer.

A CrewAI head agent + four worker agents wrap the existing read-only
analysis stack. The package is import-safe even if `crewai` is not
installed — every public entry point degrades gracefully so the rest of
the API keeps working.
"""
from __future__ import annotations
