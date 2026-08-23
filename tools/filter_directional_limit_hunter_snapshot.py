from __future__ import annotations

from pathlib import Path
import os
import pandas as pd


SRC = Path(os.getenv("LIMIT_HUNTER_SOURCE_SNAPSHOT", "data/universe_discovery/latest_combined.csv"))
DST = Path(os.getenv("LIMIT_HUNTER_FILTERED_SNAPSHOT", "data/directional_limit_hunter_snapshot.csv"))

SYMBOLS = {
    x.strip().upper()
    for x in os.getenv("LIMIT_HUNTER_SYMBOLS", "BTCUSDT,ETHUSDT").split(",")
    if x.strip()
}

ALLOWED_DECISIONS = {
    x.strip()
    for x in os.getenv(
        "LIMIT_HUNTER_ALLOWED_DECISIONS",
        "CRYPTO_BUY_FAIR_EDGE,CRYPTO_WAIT_ENTRY_ASK_TOO_HIGH,CRYPTO_AVOID_ASK_TOO_HIGH",
    ).split(",")
    if x.strip()
}

MIN_EDGE = float(os.getenv("LIMIT_HUNTER_MIN_EDGE", "0.20"))
MIN_SCORE = float(os.getenv("LIMIT_HUNTER_MIN_SCORE", "40"))
MAX_SPREAD = float(os.getenv("LIMIT_HUNTER_MAX_SPREAD", "0.05"))
MIN_ASK = float(os.getenv("LIMIT_HUNTER_MIN_ASK", "0.50"))
MAX_ASK = float(os.getenv("LIMIT_HUNTER_MAX_ASK", "0.80"))
LIMIT_OFFSET = float(os.getenv("LIMIT_HUNTER_LIMIT_OFFSET", "0.03"))
MIN_LIMIT_PRICE = float(os.getenv("LIMIT_HUNTER_MIN_LIMIT_PRICE", "0.35"))
MAX_LIMIT_PRICE = float(os.getenv("LIMIT_HUNTER_MAX_LIMIT_PRICE", "0.72"))


def ensure_num(df: pd.DataFrame, col: str) -> None:
    if col not in df.columns:
        df[col] = pd.NA
    df[col] = pd.to_numeric(df[col], errors="coerce")


def ensure_text(df: pd.DataFrame, col: str) -> None:
    if col not in df.columns:
        df[col] = ""
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
        "discovery_group",
    ]:
        ensure_text(df, col)

    if df["spread"].isna().all():
        df["spread"] = df["best_ask"] - df["best_bid"]

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
        & (bullish_yes | bearish_no)
        & df["crypto_decision"].isin(ALLOWED_DECISIONS)
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

        out["limit_price"] = (out["best_ask"] - LIMIT_OFFSET).clip(
            lower=MIN_LIMIT_PRICE,
            upper=MAX_LIMIT_PRICE,
        )

        out["limit_edge"] = out["fair_probability"] - out["limit_price"]

        out = out[out["limit_edge"].fillna(-999).ge(MIN_EDGE)].copy()

        out = out.sort_values(
            ["limit_edge", "fair_edge_to_ask", "score"],
            ascending=False,
            na_position="last",
        )

    DST.parent.mkdir(parents=True, exist_ok=True)
    out.to_csv(DST, index=False)

    print("\n=== DIRECTIONAL LIMIT HUNTER FILTER ===")
    print("Source:", SRC)
    print("Output:", DST)
    print("Rows source:", len(df))
    print("Limit hunter candidates:", len(out))
    print("Symbols:", sorted(SYMBOLS))
    print("Allowed decisions:", sorted(ALLOWED_DECISIONS))
    print(f"Edge >= {MIN_EDGE}, score >= {MIN_SCORE}, spread <= {MAX_SPREAD}, ask {MIN_ASK}-{MAX_ASK}")
    print(f"Limit offset: {LIMIT_OFFSET}")

    if not out.empty:
        print("\nTop limit hunter candidates:")
        cols = [
            "directional_side",
            "question",
            "outcome",
            "crypto_symbol",
            "crypto_decision",
            "crypto_alignment",
            "binance_bias",
            "best_bid",
            "best_ask",
            "limit_price",
            "spread",
            "score",
            "fair_probability",
            "fair_edge_to_ask",
            "limit_edge",
        ]
        cols = [c for c in cols if c in out.columns]
        print(out[cols].head(20).to_string(index=False))


if __name__ == "__main__":
    main()
