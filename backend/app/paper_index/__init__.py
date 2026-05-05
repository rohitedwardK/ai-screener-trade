"""Paper-index trading layer (simulation only).

Parallel to `app.paper` but trades index OPTIONS (CE/PE) instead of stock
spot. Same hard rules apply: no broker, no live orders, every position
carries a non-null stop, the AI journal ends with the standard disclaimer.

Pure modules (no DB / no I/O):
  - adapter, decision, sizing, simulator, kill_switch, performance,
    regime, backtest

Stateful modules (DB / orchestration):
  - service, ledger, positions, journal, config, index_pipeline
"""
