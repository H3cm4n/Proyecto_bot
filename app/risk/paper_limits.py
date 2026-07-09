from dataclasses import dataclass
from pathlib import Path

import pandas as pd


DATA_DIR = Path("data")
PAPER_TRADES_PATH = DATA_DIR / "paper_trades.csv"


@dataclass
class PaperRiskState:
    open_positions: int
    open_exposure_usdc: float


def load_paper_risk_state() -> PaperRiskState:
    if not PAPER_TRADES_PATH.exists():
        return PaperRiskState(open_positions=0, open_exposure_usdc=0.0)

    df = pd.read_csv(PAPER_TRADES_PATH)

    if df.empty or "status" not in df.columns:
        return PaperRiskState(open_positions=0, open_exposure_usdc=0.0)

    open_df = df[df["status"] == "OPEN"].copy()

    if open_df.empty:
        return PaperRiskState(open_positions=0, open_exposure_usdc=0.0)

    open_df["notional_usdc"] = pd.to_numeric(
        open_df.get("notional_usdc", 0),
        errors="coerce",
    ).fillna(0)

    return PaperRiskState(
        open_positions=len(open_df),
        open_exposure_usdc=round(float(open_df["notional_usdc"].sum()), 4),
    )


def check_paper_risk_limits(
    state: PaperRiskState,
    new_trade_size_usdc: float,
    new_trades_this_cycle: int,
    max_open_positions: int = 3,
    max_total_exposure_usdc: float = 15.0,
    max_new_trades_per_cycle: int = 1,
) -> tuple[bool, str]:
    if new_trades_this_cycle >= max_new_trades_per_cycle:
        return False, "MAX_NEW_TRADES_PER_CYCLE"

    if state.open_positions >= max_open_positions:
        return False, "MAX_OPEN_POSITIONS"

    projected_exposure = state.open_exposure_usdc + new_trade_size_usdc

    if projected_exposure > max_total_exposure_usdc:
        return False, "MAX_TOTAL_EXPOSURE"

    return True, "OK"
