from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Any

import pandas as pd

from app.brain.decision_audit import explain_trade_decision
from app.data.polymarket_clob import get_orderbook, summarize_orderbook
from app.execution.paper_broker import (
    calc_relative_spread_pct,
    create_paper_buy,
    load_existing_open_questions,
    save_paper_trades,
    sort_candidates,
)
from app.risk.paper_limits import check_paper_risk_limits, load_paper_risk_state


DATA_DIR = Path("data")
PROPOSALS_PATH = DATA_DIR / "trade_proposals.csv"

PROPOSAL_COLUMNS = [
    "proposal_id",
    "created_at",
    "expires_at",
    "status",
    "question",
    "outcome",
    "token_id",
    "proposed_entry_price",
    "current_bid_at_proposal",
    "spread",
    "top_liquidity",
    "relative_spread_pct",
    "usdc_amount",
    "score",
    "grade",
    "action",
    "edge_score",
    "edge_action",
    "edge_mid_delta",
    "edge_direction",
    "observed_at",
    "decision_reason",
    "approved_at",
    "rejected_at",
    "executed_at",
    "execution_price",
    "paper_trade_id",
    "notes",
]


def now_utc() -> str:
    return datetime.now(timezone.utc).isoformat()


def safe_float(value: Any, default: float = 0.0) -> float:
    try:
        if value == "":
            return default
        return float(value)
    except (TypeError, ValueError):
        return default


def parse_datetime(value: Any) -> datetime | None:
    try:
        if not value:
            return None

        return pd.to_datetime(value, errors="coerce", utc=True).to_pydatetime()
    except Exception:
        return None


def normalize_proposal_dataframe(df: pd.DataFrame) -> pd.DataFrame:
    for column in PROPOSAL_COLUMNS:
        if column not in df.columns:
            df[column] = ""

    extra_columns = [column for column in df.columns if column not in PROPOSAL_COLUMNS]
    return df[PROPOSAL_COLUMNS + extra_columns]


def load_proposals() -> pd.DataFrame:
    if not PROPOSALS_PATH.exists():
        return pd.DataFrame(columns=PROPOSAL_COLUMNS)

    df = pd.read_csv(PROPOSALS_PATH, dtype=str).fillna("")
    return normalize_proposal_dataframe(df)


def save_proposals(df: pd.DataFrame) -> None:
    DATA_DIR.mkdir(exist_ok=True)
    output_df = normalize_proposal_dataframe(df.copy())
    output_df.to_csv(PROPOSALS_PATH, index=False)


def proposal_is_expired(row: dict[str, Any]) -> bool:
    expires_at = parse_datetime(row.get("expires_at"))

    if expires_at is None:
        return False

    return datetime.now(timezone.utc) > expires_at


def get_pending_token_ids() -> set[str]:
    df = load_proposals()

    if df.empty:
        return set()

    pending = df[df["status"] == "PENDING_APPROVAL"].copy()
    token_ids = set()

    for _, row in pending.iterrows():
        row_dict = row.to_dict()

        if proposal_is_expired(row_dict):
            continue

        token_ids.add(str(row_dict.get("token_id", "")))

    return token_ids


def create_trade_proposals(
    rows: list[dict[str, Any]],
    usdc_amount: float = 5.0,
    min_score: int = 75,
    min_edge_score: int = 0,
    min_edge_mid_delta: float = 0.005,
    limit: int = 3,
    ttl_minutes: int = 10,
) -> list[dict[str, Any]]:
    existing_open_questions = load_existing_open_questions()
    pending_token_ids = get_pending_token_ids()

    proposals = []

    for row in sort_candidates(rows):
        if len(proposals) >= limit:
            break

        token_id = str(row.get("token_id", ""))

        if not token_id or token_id in pending_token_ids:
            continue

        decision = explain_trade_decision(
            row=row,
            usdc_amount=usdc_amount,
            min_score=min_score,
            min_edge_score=min_edge_score,
            min_edge_mid_delta=min_edge_mid_delta,
            existing_open_questions=existing_open_questions,
        )

        if not decision["eligible"]:
            continue

        created_at = now_utc()
        expires_at = (
            datetime.now(timezone.utc) + timedelta(minutes=ttl_minutes)
        ).isoformat()

        proposal = {
            "proposal_id": f"proposal-{created_at}-{token_id}",
            "created_at": created_at,
            "expires_at": expires_at,
            "status": "PENDING_APPROVAL",
            "question": row.get("question", ""),
            "outcome": row.get("outcome", ""),
            "token_id": token_id,
            "proposed_entry_price": row.get("best_ask", ""),
            "current_bid_at_proposal": row.get("best_bid", ""),
            "spread": row.get("spread", ""),
            "top_liquidity": row.get("top_liquidity", ""),
            "relative_spread_pct": row.get("relative_spread_pct", ""),
            "usdc_amount": usdc_amount,
            "score": row.get("score", ""),
            "grade": row.get("grade", ""),
            "action": row.get("action", ""),
            "edge_score": row.get("edge_score", ""),
            "edge_action": row.get("edge_action", ""),
            "edge_mid_delta": row.get("edge_mid_delta", ""),
            "edge_direction": row.get("edge_direction", ""),
            "observed_at": row.get("observed_at", ""),
            "decision_reason": decision.get("reasons", "OK"),
            "approved_at": "",
            "rejected_at": "",
            "executed_at": "",
            "execution_price": "",
            "paper_trade_id": "",
            "notes": "Generated by PAPER approval workflow.",
        }

        proposals.append(proposal)
        pending_token_ids.add(token_id)

    if proposals:
        existing_df = load_proposals()
        new_df = normalize_proposal_dataframe(pd.DataFrame(proposals))
        output_df = pd.concat([existing_df, new_df], ignore_index=True)
        save_proposals(output_df)

    return proposals


def list_trade_proposals(status: str | None = None) -> list[dict[str, Any]]:
    df = load_proposals()

    if df.empty:
        return []

    rows = []

    for _, row in df.iterrows():
        row_dict = row.to_dict()

        if row_dict.get("status") == "PENDING_APPROVAL" and proposal_is_expired(row_dict):
            row_dict["status"] = "EXPIRED"

        if status and row_dict.get("status") != status:
            continue

        rows.append(row_dict)

    return rows


def approve_trade_proposal(
    proposal_id: str,
    max_price_slippage: float = 0.02,
) -> dict[str, Any]:
    df = load_proposals()

    matches = df.index[df["proposal_id"].astype(str) == str(proposal_id)].tolist()

    if not matches:
        return {"ok": False, "message": "Propuesta no encontrada."}

    idx = matches[0]
    proposal = df.loc[idx].to_dict()

    if proposal.get("status") != "PENDING_APPROVAL":
        return {
            "ok": False,
            "message": f"La propuesta no está pendiente. Status actual: {proposal.get('status')}",
        }

    if proposal_is_expired(proposal):
        df.at[idx, "status"] = "EXPIRED"
        df.at[idx, "notes"] = "Proposal expired before approval."
        save_proposals(df)
        return {"ok": False, "message": "La propuesta expiró antes de aprobarse."}

    question = str(proposal.get("question", ""))
    token_id = str(proposal.get("token_id", ""))
    usdc_amount = safe_float(proposal.get("usdc_amount"), 5.0)

    if question in load_existing_open_questions():
        df.at[idx, "status"] = "BLOCKED_DUPLICATE_OPEN_POSITION"
        df.at[idx, "notes"] = "Blocked at approval because an open position already exists."
        save_proposals(df)
        return {"ok": False, "message": "Ya existe una posición abierta para ese mercado."}

    risk_state = load_paper_risk_state()
    allowed_by_risk, risk_reason = check_paper_risk_limits(
        state=risk_state,
        new_trade_size_usdc=usdc_amount,
        new_trades_this_cycle=0,
    )

    if not allowed_by_risk:
        df.at[idx, "status"] = f"BLOCKED_{risk_reason}"
        df.at[idx, "notes"] = f"Blocked by risk check: {risk_reason}"
        save_proposals(df)
        return {"ok": False, "message": f"Bloqueado por riesgo: {risk_reason}"}

    try:
        orderbook = get_orderbook(token_id)
        summary = summarize_orderbook(orderbook)
    except Exception as exc:
        df.at[idx, "status"] = "BLOCKED_ORDERBOOK_ERROR"
        df.at[idx, "notes"] = f"Orderbook error: {exc}"
        save_proposals(df)
        return {"ok": False, "message": f"Error leyendo orderbook: {exc}"}

    current_ask = safe_float(summary.get("best_ask"))
    current_bid = safe_float(summary.get("best_bid"))
    current_spread = safe_float(summary.get("spread"))
    bid_size = safe_float(summary.get("bid_size"))
    ask_size = safe_float(summary.get("ask_size"))

    if current_ask <= 0:
        df.at[idx, "status"] = "BLOCKED_NO_ASK"
        df.at[idx, "notes"] = "No valid ask at approval time."
        save_proposals(df)
        return {"ok": False, "message": "No hay ask válido al aprobar."}

    proposed_entry = safe_float(proposal.get("proposed_entry_price"))

    if current_ask > proposed_entry + max_price_slippage:
        df.at[idx, "status"] = "BLOCKED_PRICE_MOVED"
        df.at[idx, "notes"] = (
            f"Current ask {current_ask} exceeded proposed entry "
            f"{proposed_entry} + slippage {max_price_slippage}."
        )
        save_proposals(df)
        return {
            "ok": False,
            "message": (
                f"Precio se movió demasiado. Propuesto={proposed_entry}, "
                f"Actual={current_ask}"
            ),
        }

    top_liquidity = min(bid_size, ask_size) if bid_size > 0 and ask_size > 0 else 0.0

    current_row = {
        "question": proposal.get("question", ""),
        "outcome": proposal.get("outcome", ""),
        "token_id": token_id,
        "best_bid": current_bid,
        "best_ask": current_ask,
        "spread": current_spread,
        "top_liquidity": top_liquidity,
        "relative_spread_pct": calc_relative_spread_pct(current_spread, current_ask),
        "score": proposal.get("score", ""),
        "grade": proposal.get("grade", ""),
        "action": proposal.get("action", ""),
        "edge_score": proposal.get("edge_score", ""),
        "edge_action": proposal.get("edge_action", ""),
        "edge_mid_delta": proposal.get("edge_mid_delta", ""),
        "edge_direction": proposal.get("edge_direction", ""),
        "observed_at": now_utc(),
    }

    trade = create_paper_buy(current_row, usdc_amount=usdc_amount)
    save_paper_trades([trade])

    execution_time = now_utc()

    df.at[idx, "status"] = "EXECUTED_PAPER"
    df.at[idx, "approved_at"] = execution_time
    df.at[idx, "executed_at"] = execution_time
    df.at[idx, "execution_price"] = current_ask
    df.at[idx, "paper_trade_id"] = trade.get("paper_trade_id", "")
    df.at[idx, "notes"] = "Approved by human and executed as PAPER trade."

    save_proposals(df)

    return {
        "ok": True,
        "message": "Propuesta aprobada y ejecutada en PAPER.",
        "proposal_id": proposal_id,
        "paper_trade_id": trade.get("paper_trade_id", ""),
        "question": proposal.get("question", ""),
        "outcome": proposal.get("outcome", ""),
        "execution_price": current_ask,
    }


def reject_trade_proposal(
    proposal_id: str,
    reason: str = "Rejected by human.",
) -> dict[str, Any]:
    df = load_proposals()

    matches = df.index[df["proposal_id"].astype(str) == str(proposal_id)].tolist()

    if not matches:
        return {"ok": False, "message": "Propuesta no encontrada."}

    idx = matches[0]
    proposal = df.loc[idx].to_dict()

    if proposal.get("status") != "PENDING_APPROVAL":
        return {
            "ok": False,
            "message": f"La propuesta no está pendiente. Status actual: {proposal.get('status')}",
        }

    df.at[idx, "status"] = "REJECTED"
    df.at[idx, "rejected_at"] = now_utc()
    df.at[idx, "notes"] = reason

    save_proposals(df)

    return {
        "ok": True,
        "message": "Propuesta rechazada.",
        "proposal_id": proposal_id,
        "reason": reason,
    }
