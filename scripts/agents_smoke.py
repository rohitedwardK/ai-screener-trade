r"""Agentic-layer smoke runner.

Runs one full deep cycle outside the FastAPI lifespan + scheduler. Useful
when you want to:

    - Validate that all four worker agents wire up cleanly
    - Iterate on the head-agent prompt without rebooting the server
    - See the structured payload + markdown briefing in your terminal

Usage (from the repo root, with the backend venv active):

    .\backend\.venv\Scripts\python.exe scripts/agents_smoke.py
    .\backend\.venv\Scripts\python.exe scripts/agents_smoke.py --no-llm
    .\backend\.venv\Scripts\python.exe scripts/agents_smoke.py --json

The runner imports the same orchestrator the scheduler uses, so anything
that works here will work in production. It does NOT mutate the scheduler.
"""
from __future__ import annotations

import argparse
import json
import logging
import sys
from pathlib import Path

# Make the backend package importable regardless of CWD.
REPO_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(REPO_ROOT / "backend"))


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--no-llm", action="store_true",
                        help="Skip the LLM markdown synthesis (deterministic only).")
    parser.add_argument("--json", action="store_true",
                        help="Emit the full BriefingResult as JSON.")
    parser.add_argument("--verbose", "-v", action="store_true",
                        help="Enable INFO-level logging from the agent layer.")
    args = parser.parse_args()

    logging.basicConfig(
        level=logging.INFO if args.verbose else logging.WARNING,
        format="%(asctime)s %(levelname)s %(name)s: %(message)s",
    )

    from app.agents.orchestrator import run_deep_cycle
    from app.db import init_db

    init_db()

    print("--- Running deep cycle (use_llm=%s) ---" % (not args.no_llm))
    result = run_deep_cycle(triggered_by="cli_smoke", use_llm=not args.no_llm)

    if args.json:
        from dataclasses import asdict
        print(json.dumps(asdict(result), indent=2, default=str))
        return 0

    print()
    print(f"Status: {result.status} ({result.head_agent_status})  "
          f"duration={result.duration_s:.1f}s")
    print(f"Workers: {result.worker_statuses}")
    print(f"Regime: {result.regime}  Trend: {result.market_trend}  "
          f"VIX: {result.vix_value} ({result.vix_band})")
    print(f"Top picks: {len(result.top_picks)}  "
          f"Sectors: {len(result.sector_rotation)}  "
          f"Headlines: {len(result.news_headlines)}")
    print()
    print("--- Markdown briefing ---")
    print(result.market_summary_md)
    print()
    print(f"(disclaimer: {result.disclaimer})")
    return 0 if result.status != "ERROR" else 1


if __name__ == "__main__":
    raise SystemExit(main())
