"""Tests for the Upstox option-chain client.

Mocks `httpx.get` so we never touch the network — same pattern other Upstox
tests use. Verifies normalisation, 401 → None + dead-token latch, empty
payload → None, and instrument-key map extraction.
"""
from __future__ import annotations

from datetime import date
from typing import Any, Dict
from unittest.mock import patch

import httpx
import pytest

from app.data import upstox_client, upstox_options


_VALID_TOKEN = "test-access-token-do-not-use"


def _settings_with_token(token: str = _VALID_TOKEN):
    """Patch `get_settings` to return a stub object with our test token."""
    class _S:
        UPSTOX_API_KEY = ""
        UPSTOX_ACCESS_TOKEN = token
        UPSTOX_BASE_URL = "https://api.upstox.com/v2"
    return patch.object(upstox_options, "get_settings", return_value=_S())


def _sample_payload() -> Dict[str, Any]:
    """Synthetic two-strike Upstox option-chain payload."""
    return {
        "status": "success",
        "data": [
            {
                "strike_price": 22500,
                "underlying_spot_price": 22510.3,
                "expiry": "2026-05-12",
                "pcr": 0.91,
                "call_options": {
                    "instrument_key": "NSE_FO|CE-22500",
                    "market_data": {
                        "ltp": 80.5, "bid_price": 80.0, "ask_price": 81.0,
                        "oi": 50_000, "oi_change": 1_500, "volume": 12_000,
                    },
                    "option_greeks": {"iv": 14.7, "delta": 0.51},
                },
                "put_options": {
                    "instrument_key": "NSE_FO|PE-22500",
                    "market_data": {
                        "ltp": 75.0, "bid_price": 74.5, "ask_price": 75.5,
                        "oi": 45_000, "oi_change": 900, "volume": 9_000,
                    },
                    "option_greeks": {"iv": 14.5, "delta": -0.49},
                },
            },
            {
                "strike_price": 22550,
                "underlying_spot_price": 22510.3,
                "expiry": "2026-05-12",
                "pcr": 0.88,
                "call_options": {
                    "instrument_key": "NSE_FO|CE-22550",
                    "market_data": {
                        "ltp": 60.0, "bid_price": 59.5, "ask_price": 60.5,
                        "oi": 30_000, "oi_change": 800, "volume": 6_000,
                    },
                    "option_greeks": {"iv": 14.2, "delta": 0.42},
                },
                "put_options": {
                    "instrument_key": "NSE_FO|PE-22550",
                    "market_data": {
                        "ltp": 90.0, "bid_price": 89.5, "ask_price": 90.5,
                        "oi": 40_000, "oi_change": 1_100, "volume": 8_000,
                    },
                    "option_greeks": {"iv": 14.6, "delta": -0.58},
                },
            },
        ],
    }


@pytest.fixture(autouse=True)
def _reset_token_state():
    """Clear the dead-token latch and module cache between tests."""
    upstox_client.reset_token_state()
    upstox_options._cache.clear()  # noqa: SLF001 - intentional test reset
    yield
    upstox_client.reset_token_state()
    upstox_options._cache.clear()  # noqa: SLF001


def _mock_response(status_code: int, json_body: Any) -> httpx.Response:
    return httpx.Response(
        status_code=status_code,
        request=httpx.Request("GET", "https://api.upstox.com/v2/option/chain"),
        json=json_body,
    )


def test_fetch_normalises_payload_and_extracts_keys():
    with _settings_with_token(), patch("httpx.get") as mock_get:
        mock_get.return_value = _mock_response(200, _sample_payload())
        result = upstox_options.fetch_upstox_option_chain("NIFTY", date(2026, 5, 12))
    assert result is not None
    payload, keys = result
    assert payload.source == "upstox"
    assert payload.code == "NIFTY"
    assert payload.expiry == date(2026, 5, 12)
    assert payload.spot == pytest.approx(22510.3)
    assert len(payload.rows) == 2
    # Rows are sorted by strike.
    assert payload.rows[0].strike == 22500.0
    # Bid/ask + IV propagate.
    assert payload.rows[0].ce_bid == 80.0
    assert payload.rows[0].ce_ask == 81.0
    assert payload.rows[0].ce_iv == 14.7
    # Instrument key map is per-strike, per-leg.
    assert keys[22500.0] == {"CE": "NSE_FO|CE-22500", "PE": "NSE_FO|PE-22500"}


def test_401_returns_none_and_latches_token():
    with _settings_with_token(), patch("httpx.get") as mock_get:
        mock_get.return_value = _mock_response(401, {"error": "expired"})
        result = upstox_options.fetch_upstox_option_chain("NIFTY", date(2026, 5, 12))
    assert result is None
    # Dead-token latch is shared with `upstox_client`.
    assert upstox_client._is_token_dead(_VALID_TOKEN)  # noqa: SLF001 - test introspection


def test_empty_data_returns_none():
    with _settings_with_token(), patch("httpx.get") as mock_get:
        mock_get.return_value = _mock_response(200, {"status": "success", "data": []})
        result = upstox_options.fetch_upstox_option_chain("NIFTY", date(2026, 5, 12))
    assert result is None


def test_missing_token_returns_none_without_calling_http():
    with _settings_with_token(token=""), patch("httpx.get") as mock_get:
        result = upstox_options.fetch_upstox_option_chain("NIFTY", date(2026, 5, 12))
    assert result is None
    mock_get.assert_not_called()


def test_unknown_code_returns_none():
    with _settings_with_token(), patch("httpx.get") as mock_get:
        result = upstox_options.fetch_upstox_option_chain("UNKNOWN", date(2026, 5, 12))
    assert result is None
    mock_get.assert_not_called()


def test_cache_avoids_second_http_call():
    with _settings_with_token(), patch("httpx.get") as mock_get:
        mock_get.return_value = _mock_response(200, _sample_payload())
        first = upstox_options.fetch_upstox_option_chain("NIFTY", date(2026, 5, 12))
        second = upstox_options.fetch_upstox_option_chain("NIFTY", date(2026, 5, 12))
    assert first is not None and second is not None
    # Cached path returns an empty key map by design (we don't cache it).
    assert mock_get.call_count == 1
    assert second[0].rows == first[0].rows
