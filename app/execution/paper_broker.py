from datetime import datetime, timezone
from pathlib import Path
from typing import Any

import pandas as pd

from app.risk.paper_limits import check_paper_risk_limits, load_paper_risk_state


DATA_DIR = Path("data")
PAPER_TRADES_PATH = DATA_DIR / "paper_trades.csv"

PAPER_TRADE_COLUMNS = [
    "paper_trade_id",
    "created_at",
    "status",
    "side",
    "question",
    "outcome",
    "token_id",
    "entry_price",
    "shares",
    "notional_usdc",
    "score",
    "grade",
    "action",
    "spread",
    "top_liquidity",
    "relative_spread_pct",
    "observed_at",
    "closed_at",
    "exit_price",
    "exit_value_usdc",
    "realized_pnl_usdc",
    "realized_roi_pct",
    "exit_reason",
]


def now_utc() -> str:
    return datetime.now(timezone.utc).isoformat()


def estimate_shares(usdc_amount: float, price: float) -> float:
    if price <= 0:
        return 0.0

    return round(usdc_amount / price, 4)


def calc_relative_spread_pct(spread: float, ask: float) -> float:
    if ask <= 0:
        return 999.0

    return round((spread / ask) * 100, 2)


def should_paper_buy(
    row: dict[str, Any],
    min_score: int = 75,
    allowed_actions: set[str] | None = None,
    min_entry_price: float = 0.05,
    max_entry_price: float = 0.90,
    min_top_liquidity: float = 10.0,
    max_relative_spread_pct: float = 10.0,
) -> bool:
    if allowed_actions is None:
        allowed_actions = {"PRIORITY_WATCH", "WATCH"}

    score = int(row.get("score") or 0)
    action = str(row.get("action") or "")
    ask = float(row.get("best_ask") or 0)
    spread = float(row.get("spread") or 0)
    top_liquidity = float(row.get("top_liquidity") or 0)

    rel_spread = calc_relative_spread_pct(spread, ask)

    if score < min_score:
        return False

    if action not in allowed_actions:
        return False

    if ask < min_entry_price:
        return False

    if ask > max_entry_price:
        return False

    if top_liquidity < min_top_liquidity:
        return False

    if rel_spread > max_relative_spread_pct:
        return False

    return True


def create_paper_buy(
    row: dict[str, Any],
    usdc_amount: float = 5.0,
) -> dict[str, Any]:
    entry_price = float(row.get("best_ask") or 0)
    shares = estimate_shares(usdc_amount, entry_price)

    return {
        "paper_trade_id": f"paper-{now_utc()}-{row.get('token_id')}",
        "created_at": now_utc(),
        "status": "OPEN",
        "side": "BUY",
        "question": row.get("question", ""),
        "outcome": row.get("outcome", ""),
        "token_id": row.get("token_id", ""),
        "entry_price": entry_price,
        "shares": shares,
        "notional_usdc": usdc_amount,
        "score": row.get("score", 0),
        "grade": row.get("grade", ""),
        "action": row.get("action", ""),
        "spread": row.get("spread", ""),
        "top_liquidity": row.get("top_liquidity", ""),
        "relative_spread_pct": row.get("relative_spread_pct", ""),
        "observed_at": row.get("observed_at", ""),
        "closed_at": "",
        "exit_price": "",
        "exit_value_usdc": "",
        "realized_pnl_usdc": "",
        "realized_roi_pct": "",
        "exit_reason": "",
    }


def normalize_trade_dataframe(df: pd.DataFrame) -> pd.DataFrame:
    for column in PAPER_TRADE_COLUMNS:
        if column not in df.columns:
            df[column] = ""

    extra_columns = [column for column in df.columns if column not in PAPER_TRADE_COLUMNS]
    return df[PAPER_TRADE_COLUMNS + extra_columns]


def load_existing_open_questions() -> set[str]:
    if not PAPER_TRADES_PATH.exists():
        return set()

    df = pd.read_csv(PAPER_TRADES_PATH)

    if df.empty or "status" not in df.columns or "question" not in df.columns:
        return set()

    open_df = df[df["status"] == "OPEN"]
    return set(open_df["question"].astype(str).tolist())


def save_paper_trades(trades: list[dict[str, Any]]) -> None:
    if not trades:
        return

    DATA_DIR.mkdir(exist_ok=True)

    new_df = normalize_trade_dataframe(pd.DataFrame(trades))

    if PAPER_TRADES_PATH.exists():
        existing_df = pd.read_csv(PAPER_TRADES_PATH)
        existing_df = normalize_trade_dataframe(existing_df)
        output_df = pd.concat([existing_df, new_df], ignore_index=True)
    else:
        output_df = new_df

    output_df.to_csv(PAPER_TRADES_PATH, index=False)


def sort_candidates(rows: list[dict[str, Any]]) -> list[dict[str, Any]]:
    return sorted(
        rows,
        key=lambda row: (
            int(row.get("score") or 0),
            float(row.get("top_liquidity") or 0),
            -float(row.get("relative_spread_pct") or 999),
        ),
        reverse=True,
    )


def generate_paper_buys(
    rows: list[dict[str, Any]],
    usdc_amount: float = 5.0,
    min_score: int = 75,
    avoid_duplicates: bool = True,
    max_open_positions: int = 3,
    max_total_exposure_usdc: float = 15.0,
    max_new_trades_per_cycle: int = 1,
) -> list[dict[str, Any]]:
    existing_open_questions = load_existing_open_questions() if avoid_duplicates else set()
    opened_questions_this_run: set[str] = set()

    risk_state = load_paper_risk_state()
    new_trades_this_cycle = 0

    trades = []

    for row in sort_candidates(rows):
        question = str(row.get("question", ""))

        if not question:
            continue

        if avoid_duplicates and question in existing_open_questions:
            continue

        if question in opened_questions_this_run:
            continue

        if not should_paper_buy(row, min_score=min_score):
            continue

        allowed, reason = check_paper_risk_limits(
            state=risk_state,
            new_trade_size_usdc=usdc_amount,
            new_trades_this_cycle=new_trades_this_cycle,
            max_open_positions=max_open_positions,
            max_total_exposure_usdc=max_total_exposure_usdc,
            max_new_trades_per_cycle=max_new_trades_per_cycle,
        )

        if not allowed:
            break

        trade = create_paper_buy(row, usdc_amount=usdc_amount)
        trades.append(trade)

        opened_questions_this_run.add(question)
        existing_open_questions.add(question)

        risk_state.open_positions += 1
        risk_state.open_exposure_usdc = round(
            risk_state.open_exposure_usdc + usdc_amount,
            4,
        )
        new_trades_this_cycle += 1

    save_paper_trades(trades)

    return trades
