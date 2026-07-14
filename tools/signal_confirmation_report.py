from __future__ import annotations

from datetime import timedelta
from pathlib import Path
import os

import pandas as pd


SIGNAL_JOURNAL_PATH = Path("data/signal_journal.csv")


def truthy(value: str | None, default: bool = True) -> bool:
    if value is None:
        return default

    return str(value).strip().lower() in {"1", "true", "yes", "y", "on"}


def build_signal_key(row: pd.Series) -> str:
    token_id = str(row.get("token_id") or "").strip()

    if token_id and token_id.lower() != "nan":
        return token_id

    return "|".join(
        str(row.get(col) or "").strip()
        for col in ["crypto_symbol", "outcome", "question"]
    )


def main() -> None:
    require_confirmation = truthy(
        os.getenv("PAPER_REQUIRE_SIGNAL_CONFIRMATION"),
        default=True,
    )

    min_observations = int(os.getenv("PAPER_CONFIRMATION_MIN_OBSERVATIONS", "2"))
    lookback_minutes = int(os.getenv("PAPER_CONFIRMATION_LOOKBACK_MINUTES", "10"))

    print("\n=== SIGNAL CONFIRMATION REPORT ===")

    if not SIGNAL_JOURNAL_PATH.exists():
        print("No existe data/signal_journal.csv")
        return

    try:
        df = pd.read_csv(SIGNAL_JOURNAL_PATH)
    except pd.errors.EmptyDataError:
        print("signal_journal.csv está vacío.")
        return

    if df.empty:
        print("No hay señales registradas.")
        return

    if "observed_at" not in df.columns:
        print("No existe columna observed_at en signal_journal.csv")
        return

    df = df.copy()
    df["observed_at_dt"] = pd.to_datetime(df["observed_at"], errors="coerce", utc=True)
    df = df.dropna(subset=["observed_at_dt"]).sort_values("observed_at_dt")

    if df.empty:
        print("No hay fechas válidas en signal_journal.csv")
        return

    df["signal_key"] = df.apply(build_signal_key, axis=1)

    lookback = timedelta(minutes=lookback_minutes)
    confirmation_counts = []

    for _, row in df.iterrows():
        now = row["observed_at_dt"]
        key = row["signal_key"]

        same_signal = df[
            (df["signal_key"] == key)
            & (df["observed_at_dt"] >= now - lookback)
            & (df["observed_at_dt"] <= now)
        ]

        confirmation_counts.append(len(same_signal))

    df["confirmation_count"] = confirmation_counts

    if require_confirmation:
        df["confirmation_result"] = df["confirmation_count"].apply(
            lambda count: "PASS" if count >= min_observations else "BLOCKED_CONFIRMATION"
        )
    else:
        df["confirmation_result"] = "DISABLED"

    entry_pass = df.get("entry_filter_result", pd.Series(["UNKNOWN"] * len(df))).eq("PASS")
    confirmation_pass = df["confirmation_result"].isin(["PASS", "DISABLED"])

    df["would_be_allowed_by_confirmation"] = entry_pass & confirmation_pass

    print(f"Señales registradas: {len(df)}")
    print(f"Confirmación requerida: {require_confirmation}")
    print(f"Confirmación mínima: {min_observations} observaciones / {lookback_minutes} min")

    print("\n=== RESULTADO CONFIRMACIÓN ===")
    print(df["confirmation_result"].value_counts(dropna=False).to_string())

    print("\n=== ENTRADA + CONFIRMACIÓN ===")
    print("Señales con entry_filter PASS:", int(entry_pass.sum()))
    print("Señales permitidas por confirmación:", int(df["would_be_allowed_by_confirmation"].sum()))
    print("Señales bloqueadas por confirmación:", int((entry_pass & ~confirmation_pass).sum()))

    cols = [
        "observed_at",
        "crypto_symbol",
        "outcome",
        "entry_filter_result",
        "confirmation_count",
        "confirmation_result",
        "paper_status",
        "best_bid",
        "best_ask",
        "spread",
        "score",
        "fair_edge_to_ask",
        "question",
    ]
    cols = [col for col in cols if col in df.columns]

    print("\n=== ÚLTIMAS SEÑALES ===")
    print(df[cols].tail(20).to_string(index=False))


if __name__ == "__main__":
    main()
