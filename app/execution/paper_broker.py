from datetime import datetime, timezone
from pathlib import Path
from typing import Any

import pandas as pd


DATA_DIR = Path("data")
PAPER_TRADES_PATH = DATA_DIR / "paper_trades.csv"


def now_utc() -> str:
    return datetime.now(timezone.utc).isoformat()


def estimate_shares(usdc_amount: float, price: float) -> float:
    if price <= 0:
        return 0.0

    return round(usdc_amount / price, 4)


def should_paper_buy(
    row: dict[str, Any],
    min_score: int = 75,
    allowed_actions: set[str] | None = None,
) -> bool:
    if allowed_actions is None:
        allowed_actions = {"PRIORITY_WATCH", "WATCH"}

    score = int(row.get("score") or 0)
    action = str(row.get("action") or "")
    ask = float(row.get("best_ask") or 0)
    top_liquidity = float(row.get("top_liquidity") or 0)

    if score < min_score:
        return False

    if action not in allowed_actions:
        return False

    if ask <= 0 or ask >= 1:
        return False

    if top_liquidity < 10:
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
        "observed_at": row.get("observed_at", ""),
    }


def load_existing_open_token_ids() -> set[str]:
    if not PAPER_TRADES_PATH.exists():
        return set()

    df = pd.read_csv(PAPER_TRADES_PATH)

    if df.empty or "status" not in df.columns or "token_id" not in df.columns:
        return set()

    open_df = df[df["status"] == "OPEN"]
    return set(open_df["token_id"].astype(str).tolist())


def save_paper_trades(trades: list[dict[str, Any]]) -> None:
    if not trades:
        return

    DATA_DIR.mkdir(exist_ok=True)

    df = pd.DataFrame(trades)

    if PAPER_TRADES_PATH.exists():
        df.to_csv(PAPER_TRADES_PATH, mode="a", header=False, index=False)
    else:
        df.to_csv(PAPER_TRADES_PATH, index=False)


def generate_paper_buys(
    rows: list[dict[str, Any]],
    usdc_amount: float = 5.0,
    min_score: int = 75,
    avoid_duplicates: bool = True,
) -> list[dict[str, Any]]:
    existing_open_token_ids = load_existing_open_token_ids() if avoid_duplicates else set()

    trades = []

    for row in rows:
        token_id = str(row.get("token_id", ""))

        if avoid_duplicates and token_id in existing_open_token_ids:
            continue

        if should_paper_buy(row, min_score=min_score):
            trade = create_paper_buy(row, usdc_amount=usdc_amount)
            trades.append(trade)
            existing_open_token_ids.add(token_id)

    save_paper_trades(trades)

    return trades
