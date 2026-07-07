from datetime import datetime, timezone
from pathlib import Path
from typing import Any

import pandas as pd

from app.execution.paper_portfolio import mark_trade_to_market


DATA_DIR = Path("data")
PAPER_TRADES_PATH = DATA_DIR / "paper_trades.csv"


def now_utc() -> str:
    return datetime.now(timezone.utc).isoformat()


def load_trades() -> pd.DataFrame:
    if not PAPER_TRADES_PATH.exists():
        return pd.DataFrame()

    return pd.read_csv(PAPER_TRADES_PATH)


def save_trades(df: pd.DataFrame) -> None:
    DATA_DIR.mkdir(exist_ok=True)
    df.to_csv(PAPER_TRADES_PATH, index=False)


def ensure_exit_columns(df: pd.DataFrame) -> pd.DataFrame:
    exit_columns = {
        "closed_at": "",
        "exit_price": "",
        "exit_value_usdc": "",
        "realized_pnl_usdc": "",
        "realized_roi_pct": "",
        "exit_reason": "",
    }

    for column, default in exit_columns.items():
        if column not in df.columns:
            df[column] = default

        # Evita errores de dtype al asignar floats/strings después.
        df[column] = df[column].astype("object")

    if "status" in df.columns:
        df["status"] = df["status"].astype("object")

    return df


def get_exit_reason(
    roi_bid_pct: float,
    stop_loss_pct: float,
    take_profit_pct: float,
) -> str | None:
    if roi_bid_pct <= stop_loss_pct:
        return "STOP_LOSS"

    if roi_bid_pct >= take_profit_pct:
        return "TAKE_PROFIT"

    return None


def close_trade_in_dataframe(
    df: pd.DataFrame,
    index: int,
    marked: dict[str, Any],
    exit_reason: str,
) -> None:
    """
    Cierra una posición PAPER dentro del DataFrame.
    Todos los valores se asignan de forma compatible con Pandas.
    """
    df.at[index, "status"] = "CLOSED"
    df.at[index, "closed_at"] = now_utc()
    df.at[index, "exit_price"] = float(marked.get("current_bid") or 0)
    df.at[index, "exit_value_usdc"] = float(marked.get("exit_value_bid") or 0)
    df.at[index, "realized_pnl_usdc"] = float(marked.get("pnl_bid") or 0)
    df.at[index, "realized_roi_pct"] = float(marked.get("roi_bid_pct") or 0)
    df.at[index, "exit_reason"] = exit_reason


def evaluate_open_positions(
    stop_loss_pct: float = -20.0,
    take_profit_pct: float = 25.0,
    close_positions: bool = False,
) -> list[dict[str, Any]]:
    """
    Evalúa posiciones PAPER abiertas.
    Si close_positions=True, actualiza paper_trades.csv y cierra posiciones que disparen reglas.
    """
    df = load_trades()

    if df.empty:
        return []

    df = ensure_exit_columns(df)

    results = []

    for index, trade in df.iterrows():
        status = str(trade.get("status", ""))

        if status != "OPEN":
            continue

        try:
            marked = mark_trade_to_market(trade.to_dict())
            roi_bid_pct = float(marked.get("roi_bid_pct") or 0)

            exit_reason = get_exit_reason(
                roi_bid_pct=roi_bid_pct,
                stop_loss_pct=stop_loss_pct,
                take_profit_pct=take_profit_pct,
            )

            will_close = exit_reason is not None

            if close_positions and will_close:
                close_trade_in_dataframe(
                    df=df,
                    index=index,
                    marked=marked,
                    exit_reason=exit_reason,
                )

            results.append(
                {
                    "row_index": index,
                    "question": marked.get("question", ""),
                    "outcome": marked.get("outcome", ""),
                    "entry_price": marked.get("entry_price", ""),
                    "current_bid": marked.get("current_bid", ""),
                    "current_ask": marked.get("current_ask", ""),
                    "shares": marked.get("shares", ""),
                    "exit_value_bid": marked.get("exit_value_bid", ""),
                    "pnl_bid": marked.get("pnl_bid", ""),
                    "roi_bid_pct": roi_bid_pct,
                    "exit_reason": exit_reason or "HOLD",
                    "will_close": will_close,
                }
            )

        except Exception as error:
            results.append(
                {
                    "row_index": index,
                    "question": trade.get("question", ""),
                    "outcome": trade.get("outcome", ""),
                    "entry_price": trade.get("entry_price", ""),
                    "current_bid": "",
                    "current_ask": "",
                    "shares": trade.get("shares", ""),
                    "exit_value_bid": "",
                    "pnl_bid": "",
                    "roi_bid_pct": "",
                    "exit_reason": f"ERROR: {error}",
                    "will_close": False,
                }
            )

    if close_positions:
        save_trades(df)

    return results
