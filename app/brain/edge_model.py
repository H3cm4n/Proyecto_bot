from pathlib import Path
from typing import Any

import pandas as pd


DATA_DIR = Path("data")
HISTORY_PATH = DATA_DIR / "orderbook_history.csv"


def safe_float(value: Any, default: float = 0.0) -> float:
    try:
        return float(value)
    except (TypeError, ValueError):
        return default


def load_history() -> pd.DataFrame:
    if not HISTORY_PATH.exists():
        return pd.DataFrame()

    df = pd.read_csv(HISTORY_PATH)

    if df.empty:
        return pd.DataFrame()

    if "observed_at" in df.columns:
        df["observed_dt"] = pd.to_datetime(
            df["observed_at"],
            errors="coerce",
            utc=True,
        )

    return df


def get_previous_observation(
    history_df: pd.DataFrame,
    token_id: str,
    current_observed_at: str,
) -> dict[str, Any] | None:
    if history_df.empty:
        return None

    if "token_id" not in history_df.columns:
        return None

    token_history = history_df[history_df["token_id"].astype(str) == str(token_id)].copy()

    if token_history.empty:
        return None

    if "observed_dt" not in token_history.columns:
        return token_history.tail(1).to_dict("records")[0]

    current_dt = pd.to_datetime(
        current_observed_at,
        errors="coerce",
        utc=True,
    )

    if pd.notna(current_dt):
        token_history = token_history[token_history["observed_dt"] < current_dt]

    token_history = token_history.dropna(subset=["observed_dt"]).sort_values("observed_dt")

    if token_history.empty:
        return None

    return token_history.tail(1).to_dict("records")[0]


def score_mid_momentum(mid_delta: float) -> int:
    if mid_delta >= 0.03:
        return 45

    if mid_delta >= 0.02:
        return 35

    if mid_delta >= 0.01:
        return 25

    if mid_delta >= 0.005:
        return 15

    if mid_delta > 0:
        return 8

    if mid_delta == 0:
        return 0

    if mid_delta <= -0.03:
        return -35

    if mid_delta <= -0.02:
        return -25

    if mid_delta <= -0.01:
        return -15

    return -8


def score_liquidity_change(current_liquidity: float, previous_liquidity: float) -> tuple[int, float]:
    if previous_liquidity <= 0:
        return 0, 0.0

    ratio = current_liquidity / previous_liquidity

    if ratio >= 1.25:
        return 15, round(ratio, 4)

    if ratio >= 1.0:
        return 10, round(ratio, 4)

    if ratio >= 0.75:
        return 5, round(ratio, 4)

    if ratio >= 0.50:
        return -5, round(ratio, 4)

    return -15, round(ratio, 4)


def score_execution_quality(relative_spread_pct: float) -> int:
    if relative_spread_pct <= 3:
        return 15

    if relative_spread_pct <= 7:
        return 8

    if relative_spread_pct <= 10:
        return 0

    return -15


def action_from_edge(edge_score: int) -> str:
    if edge_score >= 75:
        return "EDGE_BUY"

    if edge_score >= 60:
        return "EDGE_WATCH"

    if edge_score >= 45:
        return "EDGE_NEUTRAL"

    return "EDGE_AVOID"


def compute_edge_score(
    row: dict[str, Any],
    previous_row: dict[str, Any] | None,
) -> dict[str, Any]:
    if previous_row is None:
        return {
            "edge_score": 0,
            "edge_action": "NO_HISTORY",
            "edge_mid_delta": "",
            "edge_liquidity_ratio": "",
            "edge_reason": "No hay historial previo para este token.",
        }

    current_mid = safe_float(row.get("mid_price"))
    previous_mid = safe_float(previous_row.get("mid_price"))

    current_liquidity = safe_float(row.get("top_liquidity"))
    previous_liquidity = safe_float(previous_row.get("top_liquidity"))

    relative_spread_pct = safe_float(row.get("relative_spread_pct"))

    mid_delta = round(current_mid - previous_mid, 4)

    momentum_points = score_mid_momentum(mid_delta)
    liquidity_points, liquidity_ratio = score_liquidity_change(
        current_liquidity=current_liquidity,
        previous_liquidity=previous_liquidity,
    )
    execution_points = score_execution_quality(relative_spread_pct)

    raw_score = 40 + momentum_points + liquidity_points + execution_points
    edge_score = max(0, min(100, raw_score))

    if mid_delta > 0:
        direction = "UP"
    elif mid_delta < 0:
        direction = "DOWN"
    else:
        direction = "FLAT"

    return {
        "edge_score": edge_score,
        "edge_action": action_from_edge(edge_score),
        "edge_mid_delta": mid_delta,
        "edge_liquidity_ratio": liquidity_ratio,
        "edge_reason": (
            f"direction={direction}; "
            f"mid_delta={mid_delta}; "
            f"liquidity_ratio={liquidity_ratio}; "
            f"relative_spread_pct={relative_spread_pct}"
        ),
    }


def attach_edge_scores(rows: list[dict[str, Any]]) -> list[dict[str, Any]]:
    history_df = load_history()

    enriched_rows = []

    for row in rows:
        previous_row = get_previous_observation(
            history_df=history_df,
            token_id=str(row.get("token_id", "")),
            current_observed_at=str(row.get("observed_at", "")),
        )

        edge_data = compute_edge_score(row, previous_row)
        enriched_rows.append({**row, **edge_data})

    return enriched_rows
