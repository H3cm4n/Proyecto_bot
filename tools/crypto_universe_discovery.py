from __future__ import annotations

from pathlib import Path
from datetime import datetime, timezone
import argparse
import shutil
import subprocess
import sys
import re

import pandas as pd


ROOT = Path(__file__).resolve().parents[1]
OUTDIR = ROOT / "data" / "universe_discovery"


ABOVE_GROUPS = {
    "major_names_above": [
        "bitcoin above",
        "ethereum above",
        "solana above",
        "xrp above",
    ],
    "ticker_above": [
        "BTC above",
        "ETH above",
        "SOL above",
        "XRP above",
    ],
    "price_above": [
        "bitcoin price above",
        "ethereum price above",
        "solana price above",
        "xrp price above",
        "crypto above",
    ],
}

BROAD_GROUPS = {
    "major_names_broad": [
        "bitcoin",
        "ethereum",
        "solana",
        "xrp",
        "crypto",
    ],
    "ticker_broad": [
        "BTC",
        "ETH",
        "SOL",
        "XRP",
    ],
    "price_broad": [
        "bitcoin price",
        "ethereum price",
        "solana price",
        "xrp price",
        "crypto price",
    ],
}


TEXT_COLS = [
    "question",
    "outcome",
    "crypto_symbol",
    "crypto_decision",
    "crypto_alignment",
    "binance_bias",
    "flow_bias",
    "signal_key",
    "token_id",
    "event_slug",
    "market_slug",
]

NUM_COLS = [
    "best_bid",
    "best_ask",
    "spread",
    "score",
    "fair_edge_to_ask",
    "fair_probability",
    "binance_spot_price",
    "threshold_price",
    "distance_pct",
    "volume",
    "liquidity",
]


def utc_run_id() -> str:
    return datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ")


def safe_name(value: str) -> str:
    value = value.lower().strip()
    value = re.sub(r"[^a-z0-9]+", "_", value)
    return value.strip("_") or "group"


def run_snapshot(
    group_name: str,
    queries: list[str],
    output_path: Path,
    log_path: Path,
    mode: str,
    event_limit: int,
    market_limit: int,
    request_delay: float,
) -> bool:
    cmd = [
        sys.executable,
        "main.py",
        "crypto-snapshot",
        "--gamma-source",
        "search",
    ]

    for q in queries:
        cmd.extend(["--search-query", q])

    cmd.extend(
        [
            "--event-limit",
            str(event_limit),
            "--market-limit",
            str(market_limit),
            "--request-delay",
            str(request_delay),
            "--market-profile",
            "crypto-price",
        ]
    )

    if mode == "above":
        cmd.extend(["--include-keyword", "above"])

    for bad in ["GTA", "tax", "hack", "liquidation"]:
        cmd.extend(["--exclude-keyword", bad])

    cmd.extend(
        [
            "--symbols",
            "BTCUSDT,ETHUSDT,SOLUSDT,XRPUSDT",
            "--interval",
            "1m",
            "--kline-limit",
            "60",
            "--output-path",
            str(output_path),
        ]
    )

    print(f"\n=== DISCOVERY GROUP: {group_name} ===")
    print("Queries:", ", ".join(queries))
    print("Output:", output_path)

    with log_path.open("w") as log:
        p = subprocess.run(
            cmd,
            cwd=ROOT,
            stdout=log,
            stderr=subprocess.STDOUT,
            text=True,
        )

    if p.returncode != 0:
        print(f"ERROR en grupo {group_name}. Revisa log: {log_path}")
        return False

    if not output_path.exists():
        print(f"No se creó output para {group_name}: {output_path}")
        return False

    try:
        df = pd.read_csv(output_path)
        print("Filas:", len(df))
    except Exception as e:
        print(f"No pude leer CSV de {group_name}: {e}")
        return False

    return True


def normalize(df: pd.DataFrame) -> pd.DataFrame:
    df = df.copy()

    for col in TEXT_COLS:
        if col not in df.columns:
            df[col] = ""
        df[col] = df[col].astype(str)

    for col in NUM_COLS:
        if col not in df.columns:
            df[col] = pd.NA
        df[col] = pd.to_numeric(df[col], errors="coerce")

    if df["spread"].isna().all():
        df["spread"] = df["best_ask"] - df["best_bid"]

    df["has_orderbook"] = (
        df["best_bid"].notna()
        & df["best_ask"].notna()
        & (df["best_bid"] > 0)
        & (df["best_ask"] > 0)
    )

    df["tight_spread_001"] = df["has_orderbook"] & df["spread"].le(0.01)
    df["tight_spread_003"] = df["has_orderbook"] & df["spread"].le(0.03)
    df["mid_ask"] = df["has_orderbook"] & df["best_ask"].between(0.20, 0.85, inclusive="both")
    df["rapid_zone"] = df["has_orderbook"] & df["best_ask"].between(0.45, 0.85, inclusive="both")

    decision = df["crypto_decision"]

    df["is_buy"] = decision.eq("CRYPTO_BUY_FAIR_EDGE")
    df["is_wait_entry_high"] = decision.eq("CRYPTO_WAIT_ENTRY_ASK_TOO_HIGH")
    df["is_wait_not_aligned"] = decision.eq("CRYPTO_WAIT_BINANCE_NOT_ALIGNED")
    df["is_avoid_conflict"] = decision.eq("CRYPTO_AVOID_BINANCE_CONFLICT")
    df["is_incomplete"] = decision.eq("CRYPTO_IGNORE_INCOMPLETE_ORDERBOOK")

    df["candidate_sniper_like"] = (
        df["crypto_symbol"].str.upper().isin(["BTCUSDT", "ETHUSDT"])
        & df["outcome"].str.lower().eq("yes")
        & df["is_buy"]
        & df["has_orderbook"]
        & df["best_ask"].between(0.50, 0.60, inclusive="both")
        & df["spread"].le(0.01)
        & df["score"].fillna(0).ge(80)
        & df["fair_edge_to_ask"].fillna(-999).ge(0.30)
    )

    df["candidate_rapid_like"] = (
        df["crypto_symbol"].str.upper().isin(["BTCUSDT", "ETHUSDT"])
        & df["outcome"].str.lower().eq("yes")
        & decision.isin(["CRYPTO_BUY_FAIR_EDGE", "CRYPTO_WAIT_ENTRY_ASK_TOO_HIGH"])
        & df["has_orderbook"]
        & df["best_ask"].between(0.45, 0.85, inclusive="both")
        & df["spread"].le(0.03)
        & df["score"].fillna(0).ge(65)
        & df["fair_edge_to_ask"].fillna(-999).ge(0.15)
    )

    df["candidate_limit_watch"] = (
        df["crypto_symbol"].str.upper().isin(["BTCUSDT", "ETHUSDT", "SOLUSDT", "XRPUSDT"])
        & df["outcome"].str.lower().eq("yes")
        & decision.isin(["CRYPTO_BUY_FAIR_EDGE", "CRYPTO_WAIT_ENTRY_ASK_TOO_HIGH"])
        & df["has_orderbook"]
        & df["best_ask"].between(0.55, 0.95, inclusive="both")
        & df["spread"].le(0.04)
        & df["score"].fillna(0).ge(60)
        & df["fair_edge_to_ask"].fillna(-999).ge(0.10)
    )

    return df


def dedupe(df: pd.DataFrame) -> pd.DataFrame:
    df = df.copy()

    if "token_id" in df.columns and df["token_id"].astype(str).str.len().gt(3).any():
        key_cols = ["token_id"]
    else:
        key_cols = ["question", "outcome", "crypto_symbol"]

    df["_rank"] = (
        df["has_orderbook"].astype(int) * 1000
        + df["tight_spread_003"].astype(int) * 200
        + df["score"].fillna(0)
        + df["fair_edge_to_ask"].fillna(-999).clip(lower=-10, upper=10) * 10
    )

    df = (
        df.sort_values("_rank", ascending=False)
        .drop_duplicates(subset=key_cols, keep="first")
        .drop(columns=["_rank"])
    )

    return df


def add_candidate_score(df: pd.DataFrame) -> pd.DataFrame:
    df = df.copy()

    decision_bonus = pd.Series(0, index=df.index, dtype=float)
    decision_bonus[df["crypto_decision"].eq("CRYPTO_BUY_FAIR_EDGE")] = 100
    decision_bonus[df["crypto_decision"].eq("CRYPTO_WAIT_ENTRY_ASK_TOO_HIGH")] = 70
    decision_bonus[df["crypto_decision"].eq("CRYPTO_WAIT_BINANCE_NOT_ALIGNED")] = 20
    decision_bonus[df["crypto_decision"].eq("CRYPTO_WAIT_SPREAD_TOO_WIDE")] = 10

    spread_bonus = pd.Series(0, index=df.index, dtype=float)
    spread_bonus[df["spread"].le(0.01)] = 20
    spread_bonus[df["spread"].between(0.010001, 0.03, inclusive="both")] = 10

    ask_penalty = pd.Series(0, index=df.index, dtype=float)
    ask_penalty[df["best_ask"].gt(0.90)] = 25
    ask_penalty[df["best_ask"].lt(0.10)] = 25

    df["candidate_score"] = (
        decision_bonus
        + df["score"].fillna(0)
        + df["fair_edge_to_ask"].fillna(-1).clip(lower=-1, upper=1) * 100
        + spread_bonus
        - ask_penalty
    )

    return df.sort_values("candidate_score", ascending=False, na_position="last")


def vc(df: pd.DataFrame, col: str, n: int = 20) -> str:
    if col not in df.columns:
        return "(columna ausente)"
    return df[col].value_counts(dropna=False).head(n).to_string()


def write_report(run_id: str, mode: str, combined: pd.DataFrame, top: pd.DataFrame, report_path: Path) -> None:
    lines: list[str] = []

    lines.append("CRYPTO UNIVERSE DISCOVERY")
    lines.append("=" * 32)
    lines.append(f"Run ID: {run_id}")
    lines.append(f"Mode: {mode}")
    lines.append(f"Rows combined deduped: {len(combined)}")
    lines.append("")

    lines.append("GENERAL")
    lines.append("-" * 32)
    lines.append(f"Orderbook completo: {int(combined['has_orderbook'].sum())}")
    lines.append(f"Spread <= 0.01: {int(combined['tight_spread_001'].sum())}")
    lines.append(f"Spread <= 0.03: {int(combined['tight_spread_003'].sum())}")
    lines.append(f"Ask 0.20-0.85: {int(combined['mid_ask'].sum())}")
    lines.append(f"Rapid zone ask 0.45-0.85: {int(combined['rapid_zone'].sum())}")
    lines.append("")

    lines.append("CANDIDATE BUCKETS")
    lines.append("-" * 32)
    lines.append(f"Sniper-like: {int(combined['candidate_sniper_like'].sum())}")
    lines.append(f"Rapid-like: {int(combined['candidate_rapid_like'].sum())}")
    lines.append(f"Limit-watch: {int(combined['candidate_limit_watch'].sum())}")
    lines.append("")

    lines.append("DECISIONES")
    lines.append("-" * 32)
    lines.append(vc(combined, "crypto_decision"))
    lines.append("")

    lines.append("SÍMBOLOS")
    lines.append("-" * 32)
    lines.append(vc(combined, "crypto_symbol"))
    lines.append("")

    lines.append("OUTCOMES")
    lines.append("-" * 32)
    lines.append(vc(combined, "outcome"))
    lines.append("")

    lines.append("BINANCE BIAS")
    lines.append("-" * 32)
    lines.append(vc(combined, "binance_bias"))
    lines.append("")

    lines.append("ALIGNMENT")
    lines.append("-" * 32)
    lines.append(vc(combined, "crypto_alignment"))
    lines.append("")

    lines.append("POR GRUPO")
    lines.append("-" * 32)
    if "discovery_group" in combined.columns:
        lines.append(vc(combined, "discovery_group"))
    lines.append("")

    lines.append("TOP 30 CANDIDATOS POR candidate_score")
    lines.append("-" * 32)
    display_cols = [
        "candidate_score",
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
        "distance_pct",
    ]
    display_cols = [c for c in display_cols if c in top.columns]

    if len(top):
        lines.append(top[display_cols].head(30).to_string(index=False))
    else:
        lines.append("Sin candidatos con orderbook.")

    report_path.write_text("\n".join(lines))


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--mode", choices=["above", "broad"], default="above")
    parser.add_argument("--event-limit", type=int, default=1000)
    parser.add_argument("--market-limit", type=int, default=100)
    parser.add_argument("--request-delay", type=float, default=0.25)
    args = parser.parse_args()

    run_id = utc_run_id()
    OUTDIR.mkdir(parents=True, exist_ok=True)

    groups = ABOVE_GROUPS if args.mode == "above" else BROAD_GROUPS

    frames: list[pd.DataFrame] = []

    print("==============================================")
    print("CRYPTO UNIVERSE DISCOVERY")
    print("Solo lectura. No abre trades.")
    print("Run ID:", run_id)
    print("Mode:", args.mode)
    print("Output dir:", OUTDIR)
    print("==============================================")

    for group_name, queries in groups.items():
        output_path = OUTDIR / f"{run_id}_{safe_name(group_name)}.csv"
        log_path = OUTDIR / f"{run_id}_{safe_name(group_name)}.log"

        ok = run_snapshot(
            group_name=group_name,
            queries=queries,
            output_path=output_path,
            log_path=log_path,
            mode=args.mode,
            event_limit=args.event_limit,
            market_limit=args.market_limit,
            request_delay=args.request_delay,
        )

        if not ok:
            continue

        df = pd.read_csv(output_path)
        df["discovery_group"] = group_name
        frames.append(df)

    if not frames:
        raise SystemExit("No hubo snapshots válidos.")

    combined_raw = pd.concat(frames, ignore_index=True)
    combined = dedupe(normalize(combined_raw))
    top = add_candidate_score(combined[combined["has_orderbook"]].copy())

    combined_path = OUTDIR / f"{run_id}_combined.csv"
    top_path = OUTDIR / f"{run_id}_top_candidates.csv"
    report_path = OUTDIR / f"{run_id}_summary.txt"

    combined.to_csv(combined_path, index=False)
    top.to_csv(top_path, index=False)
    write_report(run_id, args.mode, combined, top, report_path)

    shutil.copyfile(combined_path, OUTDIR / "latest_combined.csv")
    shutil.copyfile(top_path, OUTDIR / "latest_top_candidates.csv")
    shutil.copyfile(report_path, OUTDIR / "latest_summary.txt")

    print("\n==============================================")
    print("DISCOVERY TERMINADO")
    print("Combined:", combined_path)
    print("Top candidates:", top_path)
    print("Summary:", report_path)
    print("Latest summary:", OUTDIR / "latest_summary.txt")
    print("==============================================")

    print(report_path.read_text())


if __name__ == "__main__":
    main()
