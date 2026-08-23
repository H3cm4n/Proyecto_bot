from __future__ import annotations

from pathlib import Path
import os
import pandas as pd


SRC = Path(os.getenv("RAPID_SOURCE_SNAPSHOT", "data/crypto_signal_snapshot_fair_value.csv"))
DST = Path(os.getenv("RAPID_FILTERED_SNAPSHOT", "data/rapid_shadow_snapshot.csv"))

SYMBOLS = {
    x.strip().upper()
    for x in os.getenv("RAPID_SYMBOLS", "BTCUSDT,ETHUSDT").split(",")
    if x.strip()
}

MIN_EDGE = float(os.getenv("RAPID_MIN_EDGE", "0.15"))
MIN_SCORE = float(os.getenv("RAPID_MIN_SCORE", "70"))
MAX_SPREAD = float(os.getenv("RAPID_MAX_SPREAD", "0.02"))
MIN_ASK = float(os.getenv("RAPID_MIN_ASK", "0.45"))
MAX_ASK = float(os.getenv("RAPID_MAX_ASK", "0.70"))

# Por defecto no exigimos flow_bias porque crypto_signal_snapshot_fair_value.csv
# puede no traer esa columna. Si existe y quieres exigirla, usa RAPID_REQUIRE_FLOW=1.
REQUIRE_FLOW = os.getenv("RAPID_REQUIRE_FLOW", "0") == "1"


def num(df: pd.DataFrame, col: str) -> None:
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

    for col in ["best_bid", "best_ask", "spread", "score", "fair_edge_to_ask"]:
        num(df, col)

    for col in [
        "question",
        "outcome",
        "crypto_symbol",
        "crypto_decision",
        "crypto_alignment",
        "binance_bias",
        "flow_bias",
        "signal_key",
        "token_id",
    ]:
        ensure_text(df, col)

    if "spread" not in df.columns or df["spread"].isna().all():
        df["spread"] = df["best_ask"] - df["best_bid"]

    base_mask = (
        df["crypto_symbol"].str.upper().isin(SYMBOLS)
        & (df["outcome"].str.lower() == "yes")
        & df["crypto_decision"].isin(["CRYPTO_BUY_FAIR_EDGE", "CRYPTO_WAIT_ENTRY_ASK_TOO_HIGH"])
        & (df["crypto_alignment"] == "ALIGNED")
        & df["best_bid"].notna()
        & df["best_ask"].notna()
        & df["best_ask"].between(MIN_ASK, MAX_ASK, inclusive="both")
        & (df["spread"].fillna(999) <= MAX_SPREAD)
        & (df["score"].fillna(0) >= MIN_SCORE)
        & (df["fair_edge_to_ask"].fillna(-999) >= MIN_EDGE)
    )

    if REQUIRE_FLOW:
        base_mask = base_mask & (df["flow_bias"] == "BULLISH")

    out = df[base_mask].copy()

    if not out.empty:
        out = out.sort_values(
            ["fair_edge_to_ask", "score"],
            ascending=[False, False],
            na_position="last",
        )

    DST.parent.mkdir(parents=True, exist_ok=True)
    out.to_csv(DST, index=False)

    print("\n=== RAPID FILTER ===")
    print("Source:", SRC)
    print("Output:", DST)
    print("Rows source:", len(df))
    print("Rapid candidates:", len(out))
    print("Require flow:", REQUIRE_FLOW)
    print("Symbols:", sorted(SYMBOLS))
    print("Allowed decisions: CRYPTO_BUY_FAIR_EDGE + CRYPTO_WAIT_ENTRY_ASK_TOO_HIGH")
    print(f"Edge >= {MIN_EDGE}, score >= {MIN_SCORE}, spread <= {MAX_SPREAD}, ask {MIN_ASK}-{MAX_ASK}")

    print("\nDecisiones source:")
    print(df["crypto_decision"].value_counts(dropna=False).head(20).to_string())

    if not out.empty:
        print("\nTop rapid candidates:")
        cols = [
            "question",
            "outcome",
            "crypto_symbol",
            "binance_bias",
            "flow_bias",
            "best_bid",
            "best_ask",
            "spread",
            "score",
            "fair_edge_to_ask",
            "crypto_decision",
            "crypto_alignment",
        ]
        cols = [c for c in cols if c in out.columns]
        print(out[cols].head(20).to_string(index=False))


if __name__ == "__main__":
    main()
