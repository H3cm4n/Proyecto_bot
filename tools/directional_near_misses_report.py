from __future__ import annotations

from pathlib import Path
import pandas as pd


SRC = Path("data/universe_discovery/latest_combined.csv")

SYMBOLS = {"BTCUSDT", "ETHUSDT"}
ALLOWED_DECISIONS = {
    "CRYPTO_BUY_FAIR_EDGE",
    "CRYPTO_WAIT_ENTRY_ASK_TOO_HIGH",
}

MIN_EDGE = 0.15
MIN_SCORE = 70
MAX_SPREAD = 0.02
MIN_ASK = 0.45
MAX_ASK = 0.65


def ensure_num(df: pd.DataFrame, col: str) -> None:
    if col not in df.columns:
        df[col] = pd.NA
    df[col] = pd.to_numeric(df[col], errors="coerce")


def ensure_text(df: pd.DataFrame, col: str) -> None:
    if col not in df.columns:
        df[col] = ""
    df[col] = df[col].astype(str)


def fail_reasons(row: pd.Series) -> str:
    reasons = []

    symbol = str(row.get("crypto_symbol", "")).upper()
    outcome = str(row.get("outcome", "")).lower()
    bias = str(row.get("binance_bias", ""))
    alignment = str(row.get("crypto_alignment", ""))
    decision = str(row.get("crypto_decision", ""))

    ask = row.get("best_ask")
    spread = row.get("spread")
    score = row.get("score")
    edge = row.get("fair_edge_to_ask")

    directional_ok = (
        (bias == "BULLISH" and outcome == "yes")
        or (bias == "BEARISH" and outcome == "no")
    )

    if symbol not in SYMBOLS:
        reasons.append("symbol")
    if not directional_ok:
        reasons.append("direction")
    if alignment != "ALIGNED":
        reasons.append("alignment")
    if decision not in ALLOWED_DECISIONS:
        reasons.append("decision")
    if pd.isna(ask):
        reasons.append("ask_missing")
    else:
        if ask < MIN_ASK:
            reasons.append("ask_low")
        if ask > MAX_ASK:
            reasons.append("ask_high")
    if pd.isna(spread):
        reasons.append("spread_missing")
    elif spread > MAX_SPREAD:
        reasons.append("spread_high")
    if pd.isna(score):
        reasons.append("score_missing")
    elif score < MIN_SCORE:
        reasons.append("score_low")
    if pd.isna(edge):
        reasons.append("edge_missing")
    elif edge < MIN_EDGE:
        reasons.append("edge_low")

    return ",".join(reasons) if reasons else "PASS"


def main() -> None:
    if not SRC.exists():
        raise SystemExit(f"No existe {SRC}. Corre universe discovery primero.")

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
        "discovery_group",
    ]:
        ensure_text(df, col)

    if df["spread"].isna().all():
        df["spread"] = df["best_ask"] - df["best_bid"]

    df["fail_reasons"] = df.apply(fail_reasons, axis=1)

    direction_mask = (
        (
            df["binance_bias"].eq("BULLISH")
            & df["outcome"].str.lower().eq("yes")
        )
        | (
            df["binance_bias"].eq("BEARISH")
            & df["outcome"].str.lower().eq("no")
        )
    )

    near = df[
        df["crypto_symbol"].str.upper().isin(SYMBOLS)
        & direction_mask
        & df["crypto_alignment"].eq("ALIGNED")
        & df["best_ask"].notna()
        & df["fair_edge_to_ask"].fillna(-999).ge(0.10)
    ].copy()

    near["near_score"] = (
        near["fair_edge_to_ask"].fillna(-1).clip(-1, 1) * 100
        + near["score"].fillna(0)
        - near["spread"].fillna(1) * 100
    )

    near = near.sort_values(
        ["near_score", "fair_edge_to_ask", "score"],
        ascending=False,
        na_position="last",
    )

    print("\n=== DIRECTIONAL NEAR MISSES ===")
    print("Source:", SRC)
    print("Rows source:", len(df))
    print("Directional aligned BTC/ETH near rows:", len(near))

    print("\nFail reasons all rows:")
    print(df["fail_reasons"].value_counts().head(30).to_string())

    print("\nNear miss fail reasons:")
    if len(near):
        print(near["fail_reasons"].value_counts().head(30).to_string())
    else:
        print("Sin near misses.")

    print("\nTop near misses:")
    cols = [
        "near_score",
        "fail_reasons",
        "discovery_group",
        "question",
        "outcome",
        "crypto_symbol",
        "crypto_decision",
        "crypto_alignment",
        "binance_bias",
        "best_bid",
        "best_ask",
        "spread",
        "score",
        "fair_probability",
        "fair_edge_to_ask",
        "binance_spot_price",
        "threshold_price",
    ]
    cols = [c for c in cols if c in near.columns]

    if len(near):
        print(near[cols].head(40).to_string(index=False))
    else:
        print("Nada que mostrar.")


if __name__ == "__main__":
    main()
