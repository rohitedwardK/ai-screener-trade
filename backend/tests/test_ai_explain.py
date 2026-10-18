from app.ai.prompts import parse_structured_explanation, sections_to_text
from app.ai.template import TemplateProvider


def _payload() -> dict:
    return {
        "symbol": "RELIANCE.NS",
        "category": "PULLBACK_ENTRY",
        "regime": "UPTREND",
        "score": 72,
        "confidence": 0.64,
        "direction": "LONG",
        "reasons": ["Close above EMA20", "ADX > 20"],
        "indicators": {
            "rsi14": 58.2,
            "adx": 24.4,
            "atr_pct": 1.8,
            "ema20": 1400.0,
            "ema50": 1350.0,
            "vol_ratio": 1.4,
        },
        "plan": {
            "entry": 1410.0,
            "stop_loss": 1360.0,
            "target_1": 1460.0,
            "target_2": 1500.0,
            "invalidation": 1355.0,
        },
    }


def test_template_returns_fixed_sections() -> None:
    sections = TemplateProvider().explain(_payload())
    assert sections["setup"].startswith("RELIANCE.NS is offering a pullback")
    assert "Direction is LONG" in sections["setup"]
    assert "RSI is 58" in sections["indicators"]
    assert "EMA20 is above EMA50" in sections["indicators"]
    assert sections["rules"] == ["Close above EMA20", "ADX > 20"]
    assert "1410.0" in sections["plan"]
    assert "1355.0" in sections["risks"]
    assert "64%" in sections["risks"]


def test_wait_has_no_trade_plan() -> None:
    payload = _payload()
    payload["direction"] = "WAIT"
    payload["plan"] = {}
    sections = TemplateProvider().explain(payload)
    assert "WAIT" in sections["setup"]
    assert sections["plan"] == ""
    assert "No trade plan" in sections["risks"]


def test_parse_json_object_and_fenced_block() -> None:
    raw = '{"setup":"A","indicators":"B","rules":["r1"],"plan":"C","risks":"D"}'
    assert parse_structured_explanation(raw) == {
        "setup": "A",
        "indicators": "B",
        "rules": ["r1"],
        "plan": "C",
        "risks": "D",
    }
    fenced = "```json\n" + raw + "\n```"
    assert parse_structured_explanation(fenced)["setup"] == "A"


def test_parse_rejects_missing_setup() -> None:
    assert parse_structured_explanation('{"indicators":"only"}') is None
    assert parse_structured_explanation("not json") is None


def test_sections_to_text_order() -> None:
    text = sections_to_text(
        {
            "setup": "Setup line.",
            "indicators": "RSI is 50.",
            "rules": ["rule a"],
            "plan": "Plan line.",
            "risks": "Watch 100.",
        }
    )
    assert text.index("Setup line.") < text.index("RSI is 50.")
    assert "- rule a" in text
    assert "Watch 100." in text
