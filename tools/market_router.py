from __future__ import annotations

from pathlib import Path
import pandas as pd


SOURCES = [
    ("updown_clob", "data/updown_clob_probe.csv"),
    ("above_date", "data/crypto_signal_snapshot_fair_value.csv"),
]


def load_csv(path: str) -> pd.DataFrame:
    p = Path(path)

    if not p.exists():
        return pd.DataFrame()

    try:
        return pd.read_csv(p)
    except pd.errors.EmptyDataError:
        return pd.DataFrame()


def summarize_updown(df: pd.DataFrame) -> dict:
    if df.empty:
        return {
            "source": "updown_clob",
            "rows": 0,
            "tradeable": 0,
            "best": None,
        }

    bid = pd.to_numeric(df.get("clob_best_bid"), errors="coerce")
    ask = pd.to_numeric(df.get("clob_best_ask"), errors="coerce")

    tradeable_df = df[
        bid.notna()
        & ask.notna()
        & (bid > 0)
        & (ask < 1)
    ].copy()

    if tradeable_df.empty:
        return {
            "source": "updown_clob",
            "rows": len(df),
            "tradeable": 0,
            "best": None,
        }

    tradeable_df["clob_spread"] = pd.to_numeric(
        tradeable_df.get("clob_spread"),
        errors="coerce",
    )

    tradeable_df = tradeable_df.sort_values(
        ["clob_spread", "clob_best_ask"],
        ascending=[True, True],
        na_position="last",
    )

    best = tradeable_df.iloc[0].to_dict()

    return {
        "source": "updown_clob",
        "rows": len(df),
        "tradeable": len(tradeable_df),
        "best": best,
    }


def summarize_above_date(df: pd.DataFrame) -> dict:
    if df.empty:
        return {
            "source": "above_date",
            "rows": 0,
            "tradeable": 0,
            "best": None,
        }

    decision = df.get("crypto_decision")
    if decision is None:
        return {
            "source": "above_date",
            "rows": len(df),
            "tradeable": 0,
            "best": None,
        }

    candidates = df[
        df["crypto_decision"].isin([
            "CRYPTO_BUY_FAIR_EDGE",
            "CRYPTO_WATCH_FAIR_EDGE",
        ])
    ].copy()

    if candidates.empty:
        return {
            "source": "above_date",
            "rows": len(df),
            "tradeable": 0,
            "best": None,
        }

    candidates["fair_edge_to_ask"] = pd.to_numeric(
        candidates.get("fair_edge_to_ask"),
        errors="coerce",
    )

    candidates["best_ask"] = pd.to_numeric(
        candidates.get("best_ask"),
        errors="coerce",
    )

    candidates["spread"] = pd.to_numeric(
        candidates.get("spread"),
        errors="coerce",
    )

    candidates = candidates.sort_values(
        ["crypto_decision", "fair_edge_to_ask", "spread"],
        ascending=[True, False, True],
        na_position="last",
    )

    best = candidates.iloc[0].to_dict()

    return {
        "source": "above_date",
        "rows": len(df),
        "tradeable": len(candidates),
        "best": best,
    }


def main() -> None:
    updown = summarize_updown(load_csv("data/updown_clob_probe.csv"))
    above = summarize_above_date(load_csv("data/crypto_signal_snapshot_fair_value.csv"))

    print("\n=== MARKET ROUTER ===")
    print(f"Up/Down CLOB rows: {updown['rows']}")
    print(f"Up/Down tradeable: {updown['tradeable']}")
    print(f"Above-date rows: {above['rows']}")
    print(f"Above-date BUY/WATCH: {above['tradeable']}")

    print("\n=== DECISIÓN ===")

    if updown["tradeable"] > 0:
        best = updown["best"]
        print("Ruta elegida: UPDOWN_5M")
        print("Motivo: hay orderbook CLOB tradeable.")
        print("symbol:", best.get("symbol"))
        print("outcome:", best.get("outcome"))
        print("bid/ask:", best.get("clob_best_bid"), "/", best.get("clob_best_ask"))
        print("spread:", best.get("clob_spread"))
        print("question:", best.get("question"))
        return

    if above["tradeable"] > 0:
        best = above["best"]
        print("Ruta elegida: ABOVE_DATE")
        print("Motivo: Up/Down no tiene CLOB; above-date sí tiene oportunidad BUY/WATCH.")
        print("symbol:", best.get("crypto_symbol"))
        print("outcome:", best.get("outcome"))
        print("decision:", best.get("crypto_decision"))
        print("bid/ask:", best.get("best_bid"), "/", best.get("best_ask"))
        print("edge:", best.get("fair_edge_to_ask"))
        print("question:", best.get("question"))
        return

    print("Ruta elegida: NONE")
    print("Motivo: no hay Up/Down CLOB tradeable ni above-date BUY/WATCH.")


if __name__ == "__main__":
    main()
