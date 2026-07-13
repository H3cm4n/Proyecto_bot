from __future__ import annotations

import math
import re
from typing import Any


def safe_float(value: Any) -> float | None:
    try:
        if value is None or value == "":
            return None
        if isinstance(value, str) and value.lower() in {"none", "nan", "null"}:
            return None
        return float(value)
    except (TypeError, ValueError):
        return None


def clamp(value: float, low: float, high: float) -> float:
    return max(low, min(high, value))


def sigmoid(value: float) -> float:
    value = clamp(value, -8.0, 8.0)
    return 1.0 / (1.0 + math.exp(-value))


def text(value: Any) -> str:
    return str(value or "").lower().strip()


def extract_threshold_price(question: str) -> float | None:
    q = text(question)
    patterns = [
        r"above\s+\$?([\d,]+(?:\.\d+)?)",
        r"over\s+\$?([\d,]+(?:\.\d+)?)",
        r"below\s+\$?([\d,]+(?:\.\d+)?)",
        r"under\s+\$?([\d,]+(?:\.\d+)?)",
    ]

    for pattern in patterns:
        match = re.search(pattern, q)
        if match:
            return safe_float(match.group(1).replace(",", ""))

    return None


def classify_market_kind(question: str) -> str:
    q = text(question)

    if "up or down" in q:
        return "up_down"

    if "above" in q and " on " in q:
        return "above_date"

    if "below" in q and " on " in q:
        return "below_date"

    if "reach" in q or "hit" in q:
        return "reach_period"

    if "dip" in q:
        return "dip_period"

    return "unknown"


def get_binance_spot(row: dict[str, Any]) -> float | None:
    for key in (
        "binance_price",
        "binance_last_price",
        "binance_last_close",
        "last_close",
        "price",
    ):
        value = safe_float(row.get(key))
        if value is not None:
            return value
    return None


def get_momentum_score_pct(row: dict[str, Any]) -> float:
    mom_5m = safe_float(row.get("binance_momentum_5m_pct")) or 0.0
    mom_15m = safe_float(row.get("binance_momentum_15m_pct")) or 0.0
    mom_window = safe_float(row.get("binance_momentum_full_window_pct")) or 0.0
    return (0.45 * mom_5m) + (0.35 * mom_15m) + (0.20 * mom_window)


def get_volatility_proxy_pct(row: dict[str, Any]) -> float:
    range_pct = abs(safe_float(row.get("binance_range_full_window_pct")) or 0.0)
    mom_15m = abs(safe_float(row.get("binance_momentum_15m_pct")) or 0.0)
    mom_window = abs(safe_float(row.get("binance_momentum_full_window_pct")) or 0.0)
    return max(range_pct, mom_15m, mom_window, 0.25)


def estimate_above_date_fair_value(row: dict[str, Any]) -> dict[str, Any]:
    question = str(row.get("question") or "")
    outcome = str(row.get("outcome") or "").lower()

    threshold = extract_threshold_price(question)
    spot = get_binance_spot(row)

    if threshold is None or spot is None or threshold <= 0:
        return {
            "fair_value_status": "NO_THRESHOLD_OR_SPOT",
            "threshold_price": threshold,
            "binance_spot_price": spot,
            "fair_yes_probability": None,
            "fair_probability": None,
            "fair_edge_to_ask": None,
        }

    distance_pct = ((spot - threshold) / threshold) * 100.0
    momentum_pct = get_momentum_score_pct(row)
    volatility_pct = get_volatility_proxy_pct(row)

    z_distance = distance_pct / volatility_pct
    z_momentum = momentum_pct / volatility_pct
    z = (1.25 * z_distance) + (0.75 * z_momentum)

    fair_yes = clamp(sigmoid(z), 0.01, 0.99)

    if outcome == "yes":
        fair_probability = fair_yes
    elif outcome == "no":
        fair_probability = 1.0 - fair_yes
    else:
        fair_probability = None

    ask = safe_float(row.get("best_ask"))
    edge = None

    if fair_probability is not None and ask is not None:
        edge = fair_probability - ask

    return {
        "fair_value_status": "OK",
        "threshold_price": round(threshold, 8),
        "binance_spot_price": round(spot, 8),
        "distance_to_threshold_pct": round(distance_pct, 6),
        "momentum_score_pct": round(momentum_pct, 6),
        "volatility_proxy_pct": round(volatility_pct, 6),
        "fair_yes_probability": round(fair_yes, 6),
        "fair_probability": round(fair_probability, 6) if fair_probability is not None else None,
        "fair_edge_to_ask": round(edge, 6) if edge is not None else None,
    }


def classify_fair_decision(row: dict[str, Any]) -> dict[str, Any]:
    market_kind = str(row.get("market_kind") or "")
    status = str(row.get("fair_value_status") or "")
    alignment = str(row.get("crypto_alignment") or "")
    ask = safe_float(row.get("best_ask"))
    bid = safe_float(row.get("best_bid"))
    spread = safe_float(row.get("spread"))
    score = safe_float(row.get("score")) or 0.0
    edge = safe_float(row.get("fair_edge_to_ask"))
    distance_pct = safe_float(row.get("distance_to_threshold_pct"))

    if market_kind != "above_date":
        return {
            "fair_decision": "CRYPTO_IGNORE_NOT_ABOVE_DATE",
            "fair_signal_score": 0,
            "fair_decision_reasons": "NOT_ABOVE_DATE",
        }

    # First hard venue filter: no executable orderbook, no trade.
    if ask is None or bid is None:
        return {
            "fair_decision": "CRYPTO_IGNORE_INCOMPLETE_ORDERBOOK",
            "fair_signal_score": 0,
            "fair_decision_reasons": "INCOMPLETE_ORDERBOOK",
        }

    if status != "OK" or edge is None:
        return {
            "fair_decision": "CRYPTO_IGNORE_NO_FAIR_VALUE",
            "fair_signal_score": 0,
            "fair_decision_reasons": "NO_FAIR_VALUE",
        }

    fair_signal_score = int(round((edge * 100.0) + min(score, 100.0)))

    # Binance-first rule: no real-market alignment, no trade.
    if alignment == "CONFLICT":
        return {
            "fair_decision": "CRYPTO_AVOID_BINANCE_CONFLICT",
            "fair_signal_score": fair_signal_score,
            "fair_decision_reasons": "BINANCE_CONFLICT",
        }

    if alignment != "ALIGNED":
        return {
            "fair_decision": "CRYPTO_WAIT_BINANCE_NOT_ALIGNED",
            "fair_signal_score": fair_signal_score,
            "fair_decision_reasons": "BINANCE_NOT_ALIGNED",
        }

    # Real-market relevance: reject strikes too far from Binance spot.
    if distance_pct is None:
        return {
            "fair_decision": "CRYPTO_IGNORE_NO_DISTANCE",
            "fair_signal_score": fair_signal_score,
            "fair_decision_reasons": "NO_DISTANCE_TO_THRESHOLD",
        }

    if abs(distance_pct) > 3.0:
        return {
            "fair_decision": "CRYPTO_IGNORE_THRESHOLD_TOO_FAR",
            "fair_signal_score": fair_signal_score,
            "fair_decision_reasons": "THRESHOLD_TOO_FAR_FROM_SPOT",
        }

    # Avoid lottery tickets and expensive near-certainties.
    if ask < 0.10:
        return {
            "fair_decision": "CRYPTO_IGNORE_ASK_TOO_LOW",
            "fair_signal_score": fair_signal_score,
            "fair_decision_reasons": "ASK_TOO_LOW",
        }

    if ask > 0.70:
        return {
            "fair_decision": "CRYPTO_AVOID_ASK_TOO_HIGH",
            "fair_signal_score": fair_signal_score,
            "fair_decision_reasons": "ASK_TOO_HIGH",
        }

    if spread is not None and spread > 0.02:
        return {
            "fair_decision": "CRYPTO_WAIT_SPREAD_TOO_WIDE",
            "fair_signal_score": fair_signal_score,
            "fair_decision_reasons": "SPREAD_TOO_WIDE",
        }

    if score < 70:
        return {
            "fair_decision": "CRYPTO_WAIT_LOW_ORDERBOOK_SCORE",
            "fair_signal_score": fair_signal_score,
            "fair_decision_reasons": "LOW_ORDERBOOK_SCORE",
        }

    if edge >= 0.12:
        return {
            "fair_decision": "CRYPTO_BUY_FAIR_EDGE",
            "fair_signal_score": fair_signal_score,
            "fair_decision_reasons": "FAIR_EDGE_STRONG",
        }

    if edge >= 0.06:
        return {
            "fair_decision": "CRYPTO_WATCH_FAIR_EDGE",
            "fair_signal_score": fair_signal_score,
            "fair_decision_reasons": "FAIR_EDGE_WEAK",
        }

    if edge <= -0.04:
        return {
            "fair_decision": "CRYPTO_AVOID_NEGATIVE_FAIR_EDGE",
            "fair_signal_score": fair_signal_score,
            "fair_decision_reasons": "NEGATIVE_FAIR_EDGE",
        }

    return {
        "fair_decision": "CRYPTO_WAIT_NO_FAIR_EDGE",
        "fair_signal_score": fair_signal_score,
        "fair_decision_reasons": "NO_CLEAR_FAIR_EDGE",
    }


def attach_fair_value_signal(row: dict[str, Any]) -> dict[str, Any]:
    enriched = dict(row)
    question = str(enriched.get("question") or "")
    market_kind = classify_market_kind(question)

    enriched["market_kind"] = market_kind

    if market_kind == "above_date":
        enriched.update(estimate_above_date_fair_value(enriched))
    else:
        enriched.update(
            {
                "fair_value_status": "NOT_APPLICABLE",
                "threshold_price": None,
                "binance_spot_price": get_binance_spot(enriched),
                "distance_to_threshold_pct": None,
                "momentum_score_pct": get_momentum_score_pct(enriched),
                "volatility_proxy_pct": get_volatility_proxy_pct(enriched),
                "fair_yes_probability": None,
                "fair_probability": None,
                "fair_edge_to_ask": None,
            }
        )

    enriched.update(classify_fair_decision(enriched))
    return enriched
