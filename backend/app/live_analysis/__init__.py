"""Live Analysis Mode - Upstox-backed real-time intraday scanner.

Architecture mirrors `paper/` and `paper_index/`: pure modules
(`strategy`, `regime`, `movers`, `observer`) + thin `service` and `engine`
that touch the DB.

Hard rules upheld:
- Simulation/analysis only. No broker SDK. No order placement.
- Every directional decision carries an invalidation level.
- Every user-facing surface ends with the canonical disclaimer.
"""
