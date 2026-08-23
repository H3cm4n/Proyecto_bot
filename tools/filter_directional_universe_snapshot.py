from __future__ import annotations

from pathlib import Path
import os
import pandas as pd


SRC = Path(os.getenv("DIRECTIONAL_SOURCE_SNAPSHOT", "data/universe_discovery/latest_combined.csv"))
DST = Path(os.getenv("DIRECTIONAL_FILTERED_SNAPSHOT", "data/directional_universe_shadow_snapshot.csv"))

SYMBOLS = {
    x.strip().upper()
    for x in os.getenv("DIRECTIONAL_SYMBOLS", "BTCUSDT,ETHUSDT").split(",")
    if x.strip()
}

MIN_EDGE = float(os.getenv("DIRECTIONAL_MIN_EDGE", "0.15"))
MIN_SCORE = float(os.getenv("DIRECTIONAL_MIN_SCORE", "80"))
MAX_SPREAD = float(os.getenv("DIRECTIONAL_MAX_SPREAD", "0.01"))
MIN_ASK = float(os.getenv("DIRECTIONAL_MIN_ASK", "0.45"))
MAX_ASK = float(os.getenv("DIRECTIONAL_MAX_ASK", "0.65"))

ALLOW_WAIT_ENTRY_HIGH = os.getenv("DIRECTIONAL_ALLOW_WAIT_ENTRY_HIGH", "0") == "1"


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

    for col in [
        "best_bid",
        "best_ask",
        "spread",
        "score",
        "fair_edge_to_ask",
        "fair_probability",
        "binance_spot_price",
        "threshold_price",
    ]:
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

    allowed_decisions = ["CRYPTO_BUY_FAIR_EDGE"]
    if ALLOW_WAIT_ENTRY_HIGH:
        allowed_decisions.append("CRYPTO_WAIT_ENTRY_ASK_TOO_HIGH")

    bullish_yes = (
        df["binance_bias"].eq("BULLISH")
        & df["crypto_alignment"].eq("ALIGNED")
        & df["outcome"].str.lower().eq("yes")
    )

    bearish_no = (
        df["binance_bias"].eq("BEARISH")
        & df["crypto_alignment"].eq("ALIGNED")
        & df["outcome"].str.lower().eq("no")
    )

    mask = (
        df["crypto_symbol"].str.upper().isin(SYMBOLS)
        & df["crypto_decision"].isin(allowed_decisions)
        & (bullish_yes | bearish_no)
        & df["best_bid"].notna()
        & df["best_ask"].notna()
        & df["best_ask"].between(MIN_ASK, MAX_ASK, inclusive="both")
        & df["spread"].fillna(999).le(MAX_SPREAD)
        & df["score"].fillna(0).ge(MIN_SCORE)
        & df["fair_edge_to_ask"].fillna(-999).ge(MIN_EDGE)
    )

    out = df[mask].copy()

    if not out.empty:
        out["directional_side"] = out["binance_bias"].map(
            {
                "BULLISH": "BULLISH_YES",
                "BEARISH": "BEARISH_NO",
            }
        )

        out = out.sort_values(
            ["fair_edge_to_ask", "score", "spread"],
            ascending=[False, False, True],
            na_position="last",
        )
    else:
        out["directional_side"] = pd.Series(dtype="object")

    DST.parent.mkdir(parents=True, exist_ok=True)
    out.to_csv(DST, index=False)

    print("\n=== DIRECTIONAL UNIVERSE FILTER ===")
    print("Source:", SRC)
    print("Output:", DST)
    print("Rows source:", len(df))
    print("Directional candidates:", len(out))
    print("Symbols:", sorted(SYMBOLS))
    print("Allowed decisions:", allowed_decisions)
    print(f"Edge >= {MIN_EDGE}, score >= {MIN_SCORE}, spread <= {MAX_SPREAD}, ask {MIN_ASK}-{MAX_ASK}")

    print("\nBinance bias source:")
    print(df["binance_bias"].value_counts(dropna=False).head(20).to_string())

    print("\nAlignment source:")
    print(df["crypto_alignment"].value_counts(dropna=False).head(20).to_string())

    print("\nDecisiones source:")
    print(df["crypto_decision"].value_counts(dropna=False).head(20).to_string())

    if not out.empty:
        print("\nTop directional candidates:")
        cols = [
            "directional_side",
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
