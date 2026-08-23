from __future__ import annotations

from pathlib import Path
import os
import pandas as pd


SRC = Path(os.getenv("BEAR_NO_SOURCE_SNAPSHOT", "data/crypto_signal_snapshot_fair_value.csv"))
DST = Path(os.getenv("BEAR_NO_FILTERED_SNAPSHOT", "data/bear_no_shadow_snapshot.csv"))

SYMBOLS = {
    x.strip().upper()
    for x in os.getenv("BEAR_NO_SYMBOLS", "BTCUSDT,ETHUSDT,SOLUSDT,XRPUSDT").split(",")
    if x.strip()
}

MIN_EDGE = float(os.getenv("BEAR_NO_MIN_EDGE", "0.20"))
MIN_SCORE = float(os.getenv("BEAR_NO_MIN_SCORE", "80"))
MAX_SPREAD = float(os.getenv("BEAR_NO_MAX_SPREAD", "0.01"))
MIN_ASK = float(os.getenv("BEAR_NO_MIN_ASK", "0.45"))
MAX_ASK = float(os.getenv("BEAR_NO_MAX_ASK", "0.65"))


def ensure_num(df: pd.DataFrame, col: str) -> None:
    if col not in df.columns:
        df[col] = pd.NA
    df[col] = pd.to_numeric(df[col], errors="coerce")


def ensure_text(df: pd.DataFrame, col: str, default: str = "") -> None:
    if col not in df.columns:
        df[col] = default
    df[col] = df[col].astype(str)


def main() -> None:
    if not SRC.exists():
        raise SystemExit(f"No existe snapshot: {SRC}")

    df = pd.read_csv(SRC)

    for col in ["best_bid", "best_ask", "spread", "score", "fair_edge_to_ask", "fair_probability"]:
        ensure_num(df, col)

    for col in [
        "question",
        "outcome",
        "crypto_symbol",
        "crypto_decision",
        "crypto_alignment",
        "binance_bias",
        "signal_key",
        "token_id",
    ]:
        ensure_text(df, col)

    if df["spread"].isna().all():
        df["spread"] = df["best_ask"] - df["best_bid"]

    mask = (
        df["crypto_symbol"].str.upper().isin(SYMBOLS)
        & df["outcome"].str.lower().eq("no")
        & df["crypto_decision"].eq("CRYPTO_BUY_FAIR_EDGE")
        & df["crypto_alignment"].eq("ALIGNED")
        & df["binance_bias"].eq("BEARISH")
        & df["best_bid"].notna()
        & df["best_ask"].notna()
        & df["best_ask"].between(MIN_ASK, MAX_ASK, inclusive="both")
        & df["spread"].fillna(999).le(MAX_SPREAD)
        & df["score"].fillna(0).ge(MIN_SCORE)
        & df["fair_edge_to_ask"].fillna(-999).ge(MIN_EDGE)
    )

    out = df[mask].copy()

    if not out.empty:
        out = out.sort_values(
            ["fair_edge_to_ask", "score", "spread"],
            ascending=[False, False, True],
            na_position="last",
        )

    DST.parent.mkdir(parents=True, exist_ok=True)
    out.to_csv(DST, index=False)

    print("\n=== BEAR NO FILTER ===")
    print("Source:", SRC)
    print("Output:", DST)
    print("Rows source:", len(df))
    print("Bear No candidates:", len(out))
    print("Symbols:", sorted(SYMBOLS))
    print(f"Edge >= {MIN_EDGE}, score >= {MIN_SCORE}, spread <= {MAX_SPREAD}, ask {MIN_ASK}-{MAX_ASK}")

    print("\nDecisiones source:")
    print(df["crypto_decision"].value_counts(dropna=False).head(20).to_string())

    if not out.empty:
        print("\nTop Bear No candidates:")
        cols = [
            "question",
            "outcome",
            "crypto_symbol",
            "binance_bias",
            "crypto_alignment",
            "best_bid",
            "best_ask",
            "spread",
            "score",
            "fair_probability",
            "fair_edge_to_ask",
            "crypto_decision",
        ]
        cols = [c for c in cols if c in out.columns]
        print(out[cols].head(20).to_string(index=False))


if __name__ == "__main__":
    main()
