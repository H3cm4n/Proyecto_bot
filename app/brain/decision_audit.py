from typing import Any

from app.execution.paper_broker import (
    calc_relative_spread_pct,
    load_existing_open_questions,
    sort_candidates,
)
from app.risk.paper_limits import check_paper_risk_limits, load_paper_risk_state


def safe_int(value: Any, default: int = 0) -> int:
    try:
        return int(float(value))
    except (TypeError, ValueError):
        return default


def safe_float(value: Any, default: float = 0.0) -> float:
    try:
        if value == "":
            return default
        return float(value)
    except (TypeError, ValueError):
        return default


def explain_trade_decision(
    row: dict[str, Any],
    usdc_amount: float = 5.0,
    min_score: int = 75,
    min_edge_score: int = 0,
    min_edge_mid_delta: float = 0.005,
    min_entry_price: float = 0.05,
    max_entry_price: float = 0.90,
    min_top_liquidity: float = 10.0,
    max_relative_spread_pct: float = 10.0,
    max_open_positions: int = 3,
    max_total_exposure_usdc: float = 15.0,
    max_new_trades_per_cycle: int = 1,
    new_trades_this_cycle: int = 0,
    existing_open_questions: set[str] | None = None,
) -> dict[str, Any]:
    reasons = []

    if existing_open_questions is None:
        existing_open_questions = load_existing_open_questions()

    risk_state = load_paper_risk_state()

    question = str(row.get("question", ""))
    outcome = str(row.get("outcome", ""))

    score = safe_int(row.get("score"))
    action = str(row.get("action") or "")

    edge_score = safe_int(row.get("edge_score"))
    edge_action = str(row.get("edge_action") or "")
    edge_mid_delta = safe_float(row.get("edge_mid_delta"))

    ask = safe_float(row.get("best_ask"))
    spread = safe_float(row.get("spread"))
    top_liquidity = safe_float(row.get("top_liquidity"))
    relative_spread_pct = safe_float(
        row.get("relative_spread_pct"),
        default=calc_relative_spread_pct(spread, ask),
    )

    if not question:
        reasons.append("NO_QUESTION")

    if question in existing_open_questions:
        reasons.append("DUPLICATE_OPEN_POSITION")

    if score < min_score:
        reasons.append("SCORE_TOO_LOW")

    if action not in {"PRIORITY_WATCH", "WATCH"}:
        reasons.append("BAD_MARKET_ACTION")

    if min_edge_score > 0:
        if edge_score < min_edge_score:
            reasons.append("EDGE_TOO_LOW")

        if edge_action not in {"EDGE_BUY", "EDGE_WATCH"}:
            reasons.append("BAD_EDGE_ACTION")

        if edge_mid_delta < min_edge_mid_delta:
            reasons.append("DELTA_TOO_SMALL")

    if ask < min_entry_price:
        reasons.append("ENTRY_TOO_LOW")

    if ask > max_entry_price:
        reasons.append("ENTRY_TOO_HIGH")

    if top_liquidity < min_top_liquidity:
        reasons.append("LOW_TOP_LIQUIDITY")

    if relative_spread_pct > max_relative_spread_pct:
        reasons.append("RELATIVE_SPREAD_TOO_HIGH")

    allowed_by_risk, risk_reason = check_paper_risk_limits(
        state=risk_state,
        new_trade_size_usdc=usdc_amount,
        new_trades_this_cycle=new_trades_this_cycle,
        max_open_positions=max_open_positions,
        max_total_exposure_usdc=max_total_exposure_usdc,
        max_new_trades_per_cycle=max_new_trades_per_cycle,
    )

    if not allowed_by_risk:
        reasons.append(risk_reason)

    eligible = len(reasons) == 0

    return {
        "eligible": eligible,
        "decision": "PASS" if eligible else "REJECT",
        "reasons": "OK" if eligible else ", ".join(reasons),
        "question": question,
        "outcome": outcome,
        "score": score,
        "action": action,
        "edge_score": edge_score,
        "edge_action": edge_action,
        "edge_mid_delta": edge_mid_delta,
        "ask": ask,
        "relative_spread_pct": relative_spread_pct,
        "top_liquidity": top_liquidity,
    }


def audit_trade_rows(
    rows: list[dict[str, Any]],
    usdc_amount: float = 5.0,
    min_score: int = 75,
    min_edge_score: int = 0,
    min_edge_mid_delta: float = 0.005,
    limit: int = 15,
) -> list[dict[str, Any]]:
    existing_open_questions = load_existing_open_questions()
    audited_rows = []

    for row in sort_candidates(rows)[:limit]:
        audited_rows.append(
            explain_trade_decision(
                row=row,
                usdc_amount=usdc_amount,
                min_score=min_score,
                min_edge_score=min_edge_score,
                min_edge_mid_delta=min_edge_mid_delta,
                existing_open_questions=existing_open_questions,
            )
        )

    return audited_rows
