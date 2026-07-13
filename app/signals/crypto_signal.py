from __future__ import annotations

from pathlib import Path
from typing import Any

import pandas as pd


ASSET_SYMBOL_MAP = {
    "bitcoin": "BTCUSDT",
    "btc": "BTCUSDT",
    "ethereum": "ETHUSDT",
    "eth": "ETHUSDT",
    "solana": "SOLUSDT",
    "sol": "SOLUSDT",
    "xrp": "XRPUSDT",
}


def safe_float(value: Any, default: float = 0.0) -> float:
    try:
        if value is None or value == "":
            return default
        return float(value)
    except (TypeError, ValueError):
        return default


def safe_str(value: Any) -> str:
    return str(value or "").strip()


def infer_symbol_from_question(question: str) -> str:
    text = safe_str(question).lower()

    # Longer names first so "ethereum" wins before "eth".
    for term, symbol in sorted(ASSET_SYMBOL_MAP.items(), key=lambda item: len(item[0]), reverse=True):
        if len(term) <= 3:
            padded = f" {text} "
            if f" {term} " in padded:
                return symbol
        elif term in text:
            return symbol

    return ""


def infer_market_bias(question: str, outcome: str) -> str:
    """
    Returns the directional bias of buying a Polymarket outcome.

    BULLISH:
    - Yes on above/hit/reach/up style markets
    - Up outcome

    BEARISH:
    - No on above/hit/reach/up style markets
    - Down outcome
    - Yes on below/lower style markets
    """
    q = safe_str(question).lower()
    o = safe_str(outcome).lower()

    bullish_question_terms = [
        "hit",
        "hits",
        "reach",
        "reaches",
        "above",
        "higher",
        "up",
        "greater",
        "exceed",
        "exceeds",
    ]

    bearish_question_terms = [
        "below",
        "lower",
        "down",
        "under",
        "less than",
    ]

    if o in ("up", "higher", "above"):
        return "BULLISH"

    if o in ("down", "lower", "below"):
        return "BEARISH"

    is_bullish_question = any(term in q for term in bullish_question_terms)
    is_bearish_question = any(term in q for term in bearish_question_terms)

    if o == "yes":
        if is_bullish_question and not is_bearish_question:
            return "BULLISH"
        if is_bearish_question and not is_bullish_question:
            return "BEARISH"

    if o == "no":
        if is_bullish_question and not is_bearish_question:
            return "BEARISH"
        if is_bearish_question and not is_bullish_question:
            return "BULLISH"

    return "UNKNOWN"


def infer_binance_bias(binance_row: dict[str, Any]) -> tuple[str, int, str]:
    """
    Build a simple directional read from Binance public data.

    This is not a trading model yet. It is a context score.
    """
    mom_5m = safe_float(binance_row.get("momentum_5m_pct"))
    mom_15m = safe_float(binance_row.get("momentum_15m_pct"))
    window = safe_float(binance_row.get("momentum_full_window_pct"))
    change_24h = safe_float(binance_row.get("price_change_pct_24h"))
    price = safe_float(binance_row.get("price"))
    vwap = safe_float(binance_row.get("vwap_full_window"))

    score = 0
    reasons = []

    if mom_5m > 0.05:
        score += 20
        reasons.append("5m_up")
    elif mom_5m < -0.05:
        score -= 20
        reasons.append("5m_down")

    if mom_15m > 0.10:
        score += 30
        reasons.append("15m_up")
    elif mom_15m < -0.10:
        score -= 30
        reasons.append("15m_down")

    if window > 0.15:
        score += 20
        reasons.append("window_up")
    elif window < -0.15:
        score -= 20
        reasons.append("window_down")

    if change_24h > 1.0:
        score += 10
        reasons.append("24h_up")
    elif change_24h < -1.0:
        score -= 10
        reasons.append("24h_down")

    if price > 0 and vwap > 0:
        if price > vwap:
            score += 10
            reasons.append("price_above_vwap")
        elif price < vwap:
            score -= 10
            reasons.append("price_below_vwap")

    if score >= 30:
        return "BULLISH", score, ",".join(reasons)

    if score <= -30:
        return "BEARISH", score, ",".join(reasons)

    return "NEUTRAL", score, ",".join(reasons)


def attach_crypto_signals(
    polymarket_rows: list[dict[str, Any]],
    binance_rows: list[dict[str, Any]],
) -> list[dict[str, Any]]:
    binance_by_symbol = {
        safe_str(row.get("symbol")).upper(): row
        for row in binance_rows
        if safe_str(row.get("symbol"))
    }

    enriched_rows: list[dict[str, Any]] = []

    for row in polymarket_rows:
        question = safe_str(row.get("question"))
        outcome = safe_str(row.get("outcome"))
        symbol = infer_symbol_from_question(question)
        market_bias = infer_market_bias(question, outcome)

        binance_row = binance_by_symbol.get(symbol, {})
        binance_bias, binance_score, binance_reason = infer_binance_bias(binance_row)

        alignment = "UNKNOWN"
        crypto_action = "NO_SIGNAL"

        if not symbol:
            alignment = "NO_SYMBOL"
            crypto_action = "IGNORE_NO_SYMBOL"
        elif not binance_row:
            alignment = "NO_BINANCE_DATA"
            crypto_action = "IGNORE_NO_BINANCE_DATA"
        elif market_bias == "UNKNOWN":
            alignment = "UNKNOWN_MARKET_BIAS"
            crypto_action = "IGNORE_UNKNOWN_BIAS"
        elif binance_bias == "NEUTRAL":
            alignment = "NEUTRAL"
            crypto_action = "WATCH_NEUTRAL"
        elif market_bias == binance_bias:
            alignment = "ALIGNED"
            crypto_action = "WATCH_ALIGNED"
        else:
            alignment = "CONFLICT"
            crypto_action = "AVOID_CONFLICT"

        enriched = {
            **row,
            "crypto_symbol": symbol,
            "market_bias": market_bias,
            "binance_price": safe_float(binance_row.get("price")),
            "binance_24h_pct": safe_float(binance_row.get("price_change_pct_24h")),
            "binance_momentum_5m_pct": safe_float(binance_row.get("momentum_5m_pct")),
            "binance_momentum_15m_pct": safe_float(binance_row.get("momentum_15m_pct")),
            "binance_window_pct": safe_float(binance_row.get("momentum_full_window_pct")),
            "binance_vwap": safe_float(binance_row.get("vwap_full_window")),
            "binance_bias": binance_bias,
            "binance_bias_score": binance_score,
            "binance_bias_reason": binance_reason,
            "crypto_alignment": alignment,
            "crypto_action": crypto_action,
        }

        crypto_score, crypto_decision, crypto_reasons = score_crypto_signal(enriched)

        enriched["crypto_signal_score"] = crypto_score
        enriched["crypto_decision"] = crypto_decision
        enriched["crypto_decision_reasons"] = crypto_reasons

        enriched_rows.append(enriched)

    return enriched_rows



def score_crypto_signal(row: dict[str, Any]) -> tuple[int, str, str]:
    """
    Score a combined Polymarket + Binance crypto signal.

    This is still research-only. It does not execute trades.
    """
    reasons: list[str] = []
    score = 0

    alignment = safe_str(row.get("crypto_alignment"))
    market_bias = safe_str(row.get("market_bias"))
    binance_bias = safe_str(row.get("binance_bias"))
    crypto_action = safe_str(row.get("crypto_action"))

    ask = safe_float(row.get("best_ask"))
    pm_score = safe_float(row.get("score"))
    pm_edge = safe_float(row.get("edge_score"))
    binance_bias_score = safe_float(row.get("binance_bias_score"))
    top_liquidity = max(
        safe_float(row.get("bid_size")),
        safe_float(row.get("ask_size")),
        safe_float(row.get("top_liquidity")),
    )
    rel_spread = safe_float(row.get("relative_spread_pct"))

    if alignment == "ALIGNED":
        score += 40
        reasons.append("ALIGNED")
    elif alignment == "CONFLICT":
        score -= 50
        reasons.append("CONFLICT")
    elif alignment == "NEUTRAL":
        score += 5
        reasons.append("NEUTRAL")
    else:
        score -= 20
        reasons.append(alignment or "UNKNOWN_ALIGNMENT")

    if market_bias in ("BULLISH", "BEARISH"):
        score += 10
    else:
        reasons.append("UNKNOWN_MARKET_BIAS")

    if binance_bias in ("BULLISH", "BEARISH"):
        score += min(30, abs(int(binance_bias_score)))
    elif binance_bias == "NEUTRAL":
        reasons.append("BINANCE_NEUTRAL")
    else:
        reasons.append("UNKNOWN_BINANCE_BIAS")

    if pm_score >= 80:
        score += 20
    elif pm_score >= 70:
        score += 10
    elif pm_score >= 60:
        score += 5
    else:
        reasons.append("PM_SCORE_LOW")

    if pm_edge >= 75:
        score += 20
    elif pm_edge >= 60:
        score += 10
    elif pm_edge > 0:
        score += 3
    else:
        reasons.append("PM_EDGE_LOW_OR_MISSING")

    if ask < 0.05:
        score -= 30
        reasons.append("ENTRY_TOO_LOW")
    elif ask > 0.90:
        score -= 35
        reasons.append("ENTRY_TOO_HIGH")
    elif 0.10 <= ask <= 0.85:
        score += 15
    else:
        score += 5

    if top_liquidity >= 100:
        score += 10
    elif top_liquidity >= 25:
        score += 5
    elif top_liquidity > 0:
        reasons.append("LOW_TOP_LIQUIDITY")
    else:
        reasons.append("NO_TOP_LIQUIDITY")

    if rel_spread > 10:
        score -= 25
        reasons.append("REL_SPREAD_TOO_HIGH")
    elif rel_spread > 0 and rel_spread <= 3:
        score += 10

    if alignment == "CONFLICT":
        decision = "CRYPTO_AVOID_CONFLICT"
    elif ask < 0.05:
        decision = "CRYPTO_WATCH_ENTRY_TOO_LOW"
    elif ask > 0.90:
        decision = "CRYPTO_WATCH_ENTRY_TOO_HIGH"
    elif alignment == "ALIGNED" and score >= 85:
        decision = "CRYPTO_BUY_CANDIDATE"
    elif alignment == "ALIGNED" and score >= 65:
        decision = "CRYPTO_WATCH_ALIGNED"
    elif alignment == "NEUTRAL":
        decision = "CRYPTO_WAIT_NEUTRAL"
    else:
        decision = "CRYPTO_NO_SIGNAL"

    return int(score), decision, ",".join(reasons)


def save_crypto_signal_snapshot(
    rows: list[dict[str, Any]],
    output_path: str | Path = "data/crypto_signal_snapshot.csv",
    append: bool = False,
) -> Path:
    path = Path(output_path)
    path.parent.mkdir(parents=True, exist_ok=True)

    # Do not create empty CSV files. Empty files break pd.read_csv later.
    if not rows:
        return path

    df = pd.DataFrame(rows)

    if append and path.exists() and path.stat().st_size > 0:
        try:
            existing = pd.read_csv(path)
            if not existing.empty:
                df = pd.concat([existing, df], ignore_index=True)
        except pd.errors.EmptyDataError:
            # Previous run may have left an empty file. Treat it as no history.
            pass

    df.to_csv(path, index=False)

    return path
