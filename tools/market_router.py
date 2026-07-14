from __future__ import annotations

from pathlib import Path
import json
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


def write_route_decision(route: str, reason: str, updown: dict, above: dict, best: dict | None = None) -> None:
    out = Path("data/market_router_last.json")
    out.parent.mkdir(parents=True, exist_ok=True)

    payload = {
        "route": route,
        "reason": reason,
        "updown_rows": updown.get("rows", 0),
        "updown_tradeable": updown.get("tradeable", 0),
        "above_rows": above.get("rows", 0),
        "above_tradeable": above.get("tradeable", 0),
        "best": best or {},
    }

    with out.open("w") as file:
        json.dump(payload, file, indent=2, default=str)


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
        reason = "hay orderbook CLOB tradeable."
        write_route_decision("UPDOWN_5M", reason, updown, above, best)

        print("Ruta elegida: UPDOWN_5M")
        print("Motivo:", reason)
        print("symbol:", best.get("symbol"))
        print("outcome:", best.get("outcome"))
        print("bid/ask:", best.get("clob_best_bid"), "/", best.get("clob_best_ask"))
        print("spread:", best.get("clob_spread"))
        print("question:", best.get("question"))
        print("Archivo decisión: data/market_router_last.json")
        return

    if above["tradeable"] > 0:
        best = above["best"]
        reason = "Up/Down no tiene CLOB; above-date sí tiene oportunidad BUY/WATCH."
        write_route_decision("ABOVE_DATE", reason, updown, above, best)

        print("Ruta elegida: ABOVE_DATE")
        print("Motivo:", reason)
        print("symbol:", best.get("crypto_symbol"))
        print("outcome:", best.get("outcome"))
        print("decision:", best.get("crypto_decision"))
        print("bid/ask:", best.get("best_bid"), "/", best.get("best_ask"))
        print("edge:", best.get("fair_edge_to_ask"))
        print("question:", best.get("question"))
        print("Archivo decisión: data/market_router_last.json")
        return

    reason = "no hay Up/Down CLOB tradeable ni above-date BUY/WATCH."
    write_route_decision("NONE", reason, updown, above)

    print("Ruta elegida: NONE")
    print("Motivo:", reason)
    print("Archivo decisión: data/market_router_last.json")


if __name__ == "__main__":
    main()
