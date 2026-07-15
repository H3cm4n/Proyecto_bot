from __future__ import annotations

import os
from typing import Any


def env_float(name: str, default: float) -> float:
    raw = os.getenv(name)

    if raw is None or raw == "":
        return default

    try:
        return float(raw)
    except ValueError:
        return default


def env_csv(name: str, default: str) -> set[str]:
    raw = os.getenv(name, default)

    return {
        item.strip()
        for item in raw.split(",")
        if item.strip()
    }


def value(row: Any, key: str, default: Any = "") -> Any:
    if hasattr(row, "get"):
        try:
            return row.get(key, default)
        except Exception:
            return default

    return default


def safe_str(raw: Any) -> str:
    if raw is None:
        return ""

    text = str(raw)

    if text.lower() == "nan":
        return ""

    return text


def safe_float(raw: Any, default: float | None = None) -> float | None:
    try:
        if raw is None:
            return default

        text = str(raw).strip()

        if text == "" or text.lower() == "nan":
            return default

        return float(text)
    except Exception:
        return default


def reason_tags(raw: Any) -> set[str]:
    text = safe_str(raw)

    return {
        item.strip()
        for item in text.split(",")
        if item.strip()
    }


def infer_trade_direction(question: Any, outcome: Any) -> str:
    q = safe_str(question).lower()
    o = safe_str(outcome).lower().strip()

    bullish_question = any(
        token in q
        for token in [
            "above",
            "reach",
            "reaches",
            "hit",
            "hits",
            "higher",
            "up",
        ]
    )

    bearish_question = any(
        token in q
        for token in [
            "below",
            "under",
            "dip",
            "dips",
            "lower",
            "down",
        ]
    )

    yes = o in {"yes", "y", "up", "higher"}
    no = o in {"no", "n", "down", "lower"}

    if bullish_question and yes:
        return "BULLISH"

    if bullish_question and no:
        return "BEARISH"

    if bearish_question and yes:
        return "BEARISH"

    if bearish_question and no:
        return "BULLISH"

    if o in {"up", "higher"}:
        return "BULLISH"

    if o in {"down", "lower"}:
        return "BEARISH"

    return "UNKNOWN"


def flow_support_label(flow_bias: Any, trade_direction: Any) -> str:
    flow_bias = safe_str(flow_bias).upper()
    trade_direction = safe_str(trade_direction).upper()

    if not flow_bias or not trade_direction or trade_direction == "UNKNOWN":
        return "UNKNOWN"

    if flow_bias == "NEUTRAL":
        return "NEUTRAL"

    if flow_bias == trade_direction:
        return "SUPPORTS"

    return "AGAINST"


def classify_research_lane(row: Any) -> dict[str, Any]:
    symbol = safe_str(value(row, "crypto_symbol")).strip().upper()
    decision = safe_str(value(row, "crypto_decision")).strip()
    alignment = safe_str(value(row, "crypto_alignment")).strip().upper()
    reasons = reason_tags(value(row, "crypto_decision_reasons"))

    best_bid = safe_float(value(row, "best_bid"))
    best_ask = safe_float(value(row, "best_ask"))
    spread = safe_float(value(row, "spread"))
    score = safe_float(value(row, "score"), 0.0)
    fair_edge = safe_float(value(row, "fair_edge_to_ask"), 0.0)

    trade_direction = infer_trade_direction(
        value(row, "question"),
        value(row, "outcome"),
    )

    allowed_decisions = env_csv(
        "RESEARCH_BTC_DECISIONS",
        ",".join(
            [
                "CRYPTO_IGNORE_THRESHOLD_TOO_FAR",
                "CRYPTO_IGNORE_ASK_TOO_LOW",
                "CRYPTO_WAIT_BINANCE_NOT_ALIGNED",
                "CRYPTO_AVOID_NEGATIVE_FAIR_EDGE",
                "CRYPTO_WAIT_LOW_ORDERBOOK_SCORE",
            ]
        ),
    )

    hard_reject_reasons = env_csv(
        "RESEARCH_BTC_HARD_REJECT_REASONS",
        ",".join(
            [
                "INCOMPLETE_ORDERBOOK",
                "REL_SPREAD_TOO_HIGH",
                "LOW_TOP_LIQUIDITY",
                "BINANCE_CONFLICT",
                "CONFLICT",
            ]
        ),
    )

    ask_min = env_float("RESEARCH_BTC_ASK_MIN", 0.03)
    ask_max = env_float("RESEARCH_BTC_ASK_MAX", 0.10)
    spread_max = env_float("RESEARCH_BTC_SPREAD_MAX", 0.005)
    score_min = env_float("RESEARCH_BTC_SCORE_MIN", 60.0)
    fair_edge_min = env_float("RESEARCH_BTC_MIN_FAIR_EDGE", -0.10)

    failures: list[str] = []

    if symbol != "BTCUSDT":
        failures.append("NOT_BTC")

    if trade_direction != "BULLISH":
        failures.append("NOT_BULLISH_CONVEX")

    if decision not in allowed_decisions:
        failures.append("DECISION_NOT_ALLOWED")

    if alignment == "CONFLICT":
        failures.append("ALIGNMENT_CONFLICT")

    if hard_reject_reasons.intersection(reasons):
        failures.append("HARD_REJECT_REASON")

    if best_bid is None or best_ask is None:
        failures.append("MISSING_BID_ASK")
    else:
        if best_bid <= 0 or best_ask <= 0:
            failures.append("BAD_BID_ASK")

        if best_ask < ask_min:
            failures.append("ASK_BELOW_RESEARCH_MIN")

        if best_ask > ask_max:
            failures.append("ASK_ABOVE_RESEARCH_MAX")

    if spread is None and best_bid is not None and best_ask is not None:
        spread = best_ask - best_bid

    if spread is None:
        failures.append("MISSING_SPREAD")
    elif spread > spread_max:
        failures.append("SPREAD_TOO_WIDE_FOR_RESEARCH")

    if score is None or score < score_min:
        failures.append("SCORE_TOO_LOW_FOR_RESEARCH")

    if fair_edge is not None and fair_edge < fair_edge_min:
        failures.append("FAIR_EDGE_TOO_NEGATIVE_FOR_RESEARCH")

    if failures:
        return {
            "research_lane": "",
            "research_reason": ",".join(failures),
            "trade_direction": trade_direction,
            "research_pass": False,
        }

    return {
        "research_lane": "BTC_CHEAP_CONVEX",
        "research_reason": "BTC_BULLISH_CHEAP_CONVEX_CANDIDATE",
        "trade_direction": trade_direction,
        "research_pass": True,
    }
