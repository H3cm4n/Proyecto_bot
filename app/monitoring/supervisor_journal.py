from datetime import datetime, timezone
from pathlib import Path
from typing import Any

import pandas as pd


DATA_DIR = Path("data")
JOURNAL_PATH = DATA_DIR / "supervisor_journal.csv"

JOURNAL_COLUMNS = [
    "observed_at",
    "cycle_number",
    "open_positions",
    "open_exposure_usdc",
    "closed_pnl_usdc",
    "open_unrealized_pnl_bid_usdc",
    "total_paper_pnl_usdc",
    "total_paper_roi_pct",
    "proposals_created",
    "orderbook_rows_scanned",
    "status",
    "notes",
]


def now_utc() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="seconds")


def normalize_journal_dataframe(df: pd.DataFrame) -> pd.DataFrame:
    for column in JOURNAL_COLUMNS:
        if column not in df.columns:
            df[column] = ""

    return df[JOURNAL_COLUMNS]


def save_supervisor_journal_entry(entry: dict[str, Any]) -> None:
    DATA_DIR.mkdir(exist_ok=True)

    row = {column: entry.get(column, "") for column in JOURNAL_COLUMNS}
    row["observed_at"] = row.get("observed_at") or now_utc()

    new_df = normalize_journal_dataframe(pd.DataFrame([row]))

    if JOURNAL_PATH.exists():
        try:
            old_df = pd.read_csv(JOURNAL_PATH, dtype=str, on_bad_lines="skip").fillna("")
        except Exception:
            backup_path = JOURNAL_PATH.with_suffix(".broken.csv")
            JOURNAL_PATH.rename(backup_path)
            old_df = pd.DataFrame(columns=JOURNAL_COLUMNS)

        old_df = normalize_journal_dataframe(old_df)
        out_df = pd.concat([old_df, new_df], ignore_index=True)
    else:
        out_df = new_df

    out_df = normalize_journal_dataframe(out_df)
    out_df.to_csv(JOURNAL_PATH, index=False)


def load_supervisor_journal(tail: int = 20) -> list[dict[str, Any]]:
    if not JOURNAL_PATH.exists():
        return []

    df = pd.read_csv(JOURNAL_PATH, dtype=str, on_bad_lines="skip").fillna("")
    df = normalize_journal_dataframe(df)

    if tail > 0:
        df = df.tail(tail)

    return df.to_dict(orient="records")
