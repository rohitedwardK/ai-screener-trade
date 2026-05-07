"""Tests for `data.live_quotes.fetch_live_prices` source-routing.

These tests stub out `upstox_client` and `yf.download` so they don't touch
the network. They cover the four interesting routing branches:

  1. Upstox covers everything                  -> source == "upstox"
  2. Upstox covers nothing (mapped or not)     -> source == "yfinance"
  3. Mixed: some Upstox, some yfinance         -> source == "mixed"
  4. Upstox returns partial result; yfinance fills the gap (still "mixed")
  5. Cache hit: same symbol-set within TTL skips both fetchers
"""
from __future__ import annotations

from typing import Dict, List
from unittest.mock import patch

import pandas as pd
import pytest

from app.data import live_quotes


@pytest.fixture(autouse=True)
def _reset_cache():
    live_quotes.reset_cache()
    yield
    live_quotes.reset_cache()


def _df_close_only(prices: Dict[str, float]) -> pd.DataFrame:
    """Build the MultiIndex DataFrame shape that `yf.download(..., group_by='ticker')`
    produces so the parser in `_fetch_from_yfinance` can dig the close out."""
    cols = pd.MultiIndex.from_tuples(
        [(sym, "Close") for sym in prices], names=[None, None],
    )
    data = [list(prices.values())]
    return pd.DataFrame(data, columns=cols)


def _fake_upstox_module(supported: List[str], returned_prices: Dict[str, float]):
    """Patch context: make `upstox_client.instrument_key_for` recognise `supported`
    and `fetch_ltp_batch` return `returned_prices`."""
    def _key(sym: str):
        return f"NSE_EQ|{sym}" if sym in supported else None

    def _ltp(symbols, *, timeout_s=6.0):  # noqa: ARG001
        return {s: p for s, p in returned_prices.items() if s in symbols}

    return patch.multiple(
        "app.data.live_quotes.upstox_client",
        is_configured=lambda: True,
        instrument_key_for=_key,
        fetch_ltp_batch=_ltp,
    )


def test_upstox_covers_everything_skips_yfinance():
    with _fake_upstox_module(["AAA.NS", "BBB.NS"], {"AAA.NS": 100.0, "BBB.NS": 200.0}), \
         patch("app.data.live_quotes._fetch_from_yfinance") as yf_mock:
        yf_mock.return_value = {}
        out = live_quotes.fetch_live_prices(["AAA.NS", "BBB.NS"])

    assert out == {"AAA.NS": 100.0, "BBB.NS": 200.0}
    assert live_quotes.last_source() == live_quotes.SOURCE_UPSTOX
    yf_mock.assert_called_once()
    assert yf_mock.call_args.args[0] == []  # no yfinance work needed


def test_upstox_unknown_symbols_route_to_yfinance():
    with _fake_upstox_module([], {}), \
         patch("app.data.live_quotes._fetch_from_yfinance") as yf_mock:
        yf_mock.return_value = {"AAA.NS": 100.0, "BBB.NS": 200.0}
        out = live_quotes.fetch_live_prices(["AAA.NS", "BBB.NS"])

    assert out == {"AAA.NS": 100.0, "BBB.NS": 200.0}
    assert live_quotes.last_source() == live_quotes.SOURCE_YFINANCE
    yf_mock.assert_called_once_with(["AAA.NS", "BBB.NS"])


def test_mixed_when_some_symbols_only_in_upstox_and_others_only_in_yfinance():
    with _fake_upstox_module(["AAA.NS"], {"AAA.NS": 111.0}), \
         patch("app.data.live_quotes._fetch_from_yfinance") as yf_mock:
        yf_mock.return_value = {"BBB.NS": 222.0}
        out = live_quotes.fetch_live_prices(["AAA.NS", "BBB.NS"])

    assert out == {"AAA.NS": 111.0, "BBB.NS": 222.0}
    assert live_quotes.last_source() == live_quotes.SOURCE_MIXED
    # Only the unmapped symbol should be sent to yfinance.
    yf_mock.assert_called_once_with(["BBB.NS"])


def test_upstox_partial_response_is_filled_in_by_yfinance():
    """If Upstox is configured to return AAA but silently drops BBB,
    yfinance fills the gap and we still report mixed."""
    with _fake_upstox_module(["AAA.NS", "BBB.NS"], {"AAA.NS": 111.0}), \
         patch("app.data.live_quotes._fetch_from_yfinance") as yf_mock:
        yf_mock.return_value = {"BBB.NS": 222.0}
        out = live_quotes.fetch_live_prices(["AAA.NS", "BBB.NS"])

    assert out == {"AAA.NS": 111.0, "BBB.NS": 222.0}
    assert live_quotes.last_source() == live_quotes.SOURCE_MIXED
    # Upstox missed BBB so it should be recovered via yfinance.
    yf_mock.assert_called_once_with(["BBB.NS"])


def test_repeated_call_within_ttl_uses_cache_and_does_not_refetch():
    with _fake_upstox_module(["AAA.NS"], {"AAA.NS": 100.0}), \
         patch("app.data.live_quotes._fetch_from_yfinance") as yf_mock:
        yf_mock.return_value = {}
        out1 = live_quotes.fetch_live_prices(["AAA.NS"])
        out2 = live_quotes.fetch_live_prices(["AAA.NS"])

    assert out1 == out2 == {"AAA.NS": 100.0}
    yf_mock.assert_called_once()  # only the first call did any work


def test_total_failure_returns_empty_and_source_none():
    with _fake_upstox_module([], {}), \
         patch("app.data.live_quotes._fetch_from_yfinance") as yf_mock:
        yf_mock.return_value = {}
        out = live_quotes.fetch_live_prices(["AAA.NS"])

    assert out == {}
    assert live_quotes.last_source() == live_quotes.SOURCE_NONE
