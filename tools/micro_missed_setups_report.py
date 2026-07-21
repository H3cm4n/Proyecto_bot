from __future__ import annotations

from pathlib import Path
import math

import pandas as pd


JOURNAL_PATH = Path("data/candidate_journal.csv")
TRADES_PATH = Path("data/micro_tpsl_paper_trades.csv")

OUT_CSV = Path("data/micro_missed_setups_report.csv")
OUT_TXT = Path("data/micro_missed_setups_report.txt")

COOLDOWN_MINUTES = 180
MAX_ENTRY_MATCH_SECONDS = 120


def to_dt(series: pd.Series) -> pd.Series:
    return pd.to_datetime(series, utc=True, errors="coerce")


def short_signal(value: object) -> str:
    text = str(value)
    if len(text) <= 32:
        return text
    return text[:18] + "..." + text[-10:]


def load_inputs() -> tuple[pd.DataFrame, pd.DataFrame]:
    if not JOURNAL_PATH.exists():
        raise SystemExit(f"No existe {JOURNAL_PATH}")

    if not TRADES_PATH.exists():
        raise SystemExit(f"No existe {TRADES_PATH}")

    journal = pd.read_csv(JOURNAL_PATH)
    trades = pd.read_csv(TRADES_PATH)

    journal["observed_at_dt"] = to_dt(journal["observed_at"])

    if not trades.empty:
        trades["entry_time_dt"] = to_dt(trades["entry_time"])
        trades["exit_time_dt"] = to_dt(trades["exit_time"])

    return journal, trades


def filter_micro_setups(journal: pd.DataFrame) -> pd.DataFrame:
    work = journal.copy()

    required = [
        "crypto_symbol",
        "outcome",
        "crypto_decision",
        "crypto_alignment",
        "flow_bias",
        "fair_edge_to_ask",
        "score",
        "spread",
        "best_ask",
    ]

    missing = [c for c in required if c not in work.columns]
    if missing:
        raise SystemExit(f"Faltan columnas en candidate_journal.csv: {missing}")

    micro = work[
        (work["crypto_symbol"].astype(str).str.upper() == "BTCUSDT")
        & (work["outcome"].astype(str).str.lower() == "yes")
        & (work["crypto_decision"] == "CRYPTO_BUY_FAIR_EDGE")
        & (work["crypto_alignment"] == "ALIGNED")
        & (work["flow_bias"] == "BULLISH")
        & (work["fair_edge_to_ask"] >= 0.30)
        & (work["score"] >= 80)
        & (work["spread"] <= 0.01)
        & (work["best_ask"] >= 0.50)
        & (work["best_ask"] <= 0.60)
    ].copy()

    return micro.sort_values("observed_at_dt").reset_index(drop=True)


def find_matching_trade(row: pd.Series, trades: pd.DataFrame) -> pd.Series | None:
    if trades.empty:
        return None

    observed_at = row.get("observed_at_dt")

    if pd.isna(observed_at):
        return None

    signal_key = str(row.get("signal_key", ""))
    token_id = str(row.get("token_id", ""))
    question = str(row.get("question", ""))
    outcome = str(row.get("outcome", "")).lower()

    candidates = trades.copy()

    masks = []

    if "signal_key" in candidates.columns and signal_key:
        masks.append(candidates["signal_key"].astype(str) == signal_key)

    if "token_id" in candidates.columns and token_id:
        masks.append(candidates["token_id"].astype(str) == token_id)

    if {"question", "outcome"}.issubset(candidates.columns):
        masks.append(
            (candidates["question"].astype(str) == question)
            & (candidates["outcome"].astype(str).str.lower() == outcome)
        )

    if not masks:
        return None

    combined = masks[0]
    for mask in masks[1:]:
        combined = combined | mask

    same_signal = candidates[combined].copy()

    if same_signal.empty:
        return None

    same_signal["entry_diff_seconds"] = (
        same_signal["entry_time_dt"] - observed_at
    ).abs().dt.total_seconds()

    matched = same_signal[same_signal["entry_diff_seconds"] <= MAX_ENTRY_MATCH_SECONDS]

    if matched.empty:
        return None

    return matched.sort_values("entry_diff_seconds").iloc[0]


def active_trade_at(observed_at, trades: pd.DataFrame) -> pd.Series | None:
    if trades.empty or pd.isna(observed_at):
        return None

    for _, trade in trades.iterrows():
        entry = trade.get("entry_time_dt")
        exit_ = trade.get("exit_time_dt")

        if pd.isna(entry):
            continue

        if pd.isna(exit_):
            exit_ = pd.Timestamp.max.tz_localize("UTC")

        if entry <= observed_at < exit_:
            return trade

    return None


def same_cycle_trade(row: pd.Series, trades: pd.DataFrame) -> pd.Series | None:
    if trades.empty:
        return None

    observed_at = row.get("observed_at_dt")
    if pd.isna(observed_at):
        return None

    tmp = trades.copy()
    tmp["entry_diff_seconds"] = (
        tmp["entry_time_dt"] - observed_at
    ).abs().dt.total_seconds()

    matched = tmp[tmp["entry_diff_seconds"] <= MAX_ENTRY_MATCH_SECONDS]

    if matched.empty:
        return None

    return matched.sort_values("entry_diff_seconds").iloc[0]


def same_signal_cooldown(row: pd.Series, trades: pd.DataFrame) -> pd.Series | None:
    if trades.empty:
        return None

    signal_key = str(row.get("signal_key"))
    observed_at = row.get("observed_at_dt")

    if pd.isna(observed_at):
        return None

    same_signal = trades[trades["signal_key"].astype(str) == signal_key].copy()

    if same_signal.empty:
        return None

    same_signal = same_signal[same_signal["entry_time_dt"] < observed_at].copy()

    if same_signal.empty:
        return None

    same_signal["minutes_after_entry"] = (
        observed_at - same_signal["entry_time_dt"]
    ).dt.total_seconds() / 60

    blocked = same_signal[
        (same_signal["minutes_after_entry"] >= 0)
        & (same_signal["minutes_after_entry"] <= COOLDOWN_MINUTES)
    ]

    if blocked.empty:
        return None

    return blocked.sort_values("minutes_after_entry").iloc[-1]


def classify(row: pd.Series, trades: pd.DataFrame, first_trade_time) -> dict:
    observed_at = row.get("observed_at_dt")

    matched = find_matching_trade(row, trades)
    if matched is not None:
        return {
            "taken_status": "TAKEN",
            "why_not_taken": "TAKEN_AS_MICRO_TRADE",
            "blocking_trade_id": matched.get("trade_id", ""),
            "blocking_note": "Este setup sí fue ejecutado por el micro executor.",
        }

    if trades.empty:
        return {
            "taken_status": "NOT_TAKEN",
            "why_not_taken": "NO_MICRO_TRADES_FILE",
            "blocking_trade_id": "",
            "blocking_note": "No hay trades micro registrados.",
        }

    if pd.notna(first_trade_time) and pd.notna(observed_at) and observed_at < first_trade_time:
        return {
            "taken_status": "NOT_TAKEN",
            "why_not_taken": "BEFORE_FIRST_RECORDED_MICRO_TRADE",
            "blocking_trade_id": "",
            "blocking_note": "El setup apareció antes del primer trade micro registrado; probablemente el executor aún no estaba activo o no estaba corriendo.",
        }

    active = active_trade_at(observed_at, trades)
    if active is not None:
        return {
            "taken_status": "NOT_TAKEN",
            "why_not_taken": "BLOCKED_MAX_OPEN",
            "blocking_trade_id": active.get("trade_id", ""),
            "blocking_note": "Ya había un micro trade abierto; la estrategia permite max open = 1.",
        }

    cooldown = same_signal_cooldown(row, trades)
    if cooldown is not None:
        minutes = cooldown.get("minutes_after_entry")
        minutes_text = "" if pd.isna(minutes) else f"{minutes:.1f} min después de la entrada previa"
        return {
            "taken_status": "NOT_TAKEN",
            "why_not_taken": "BLOCKED_SAME_SIGNAL_COOLDOWN",
            "blocking_trade_id": cooldown.get("trade_id", ""),
            "blocking_note": f"Misma señal dentro del cooldown de {COOLDOWN_MINUTES} min. {minutes_text}.",
        }

    cycle_trade = same_cycle_trade(row, trades)
    if cycle_trade is not None:
        return {
            "taken_status": "NOT_TAKEN",
            "why_not_taken": "BLOCKED_MAX_NEW_PER_CYCLE",
            "blocking_trade_id": cycle_trade.get("trade_id", ""),
            "blocking_note": "En ese ciclo ya se tomó otro trade; max new/cycle = 1.",
        }

    return {
        "taken_status": "NOT_TAKEN",
        "why_not_taken": "NOT_EXECUTED_NO_DIRECT_BLOCK_FOUND",
        "blocking_trade_id": "",
        "blocking_note": "Pasaba filtros, pero no hay bloqueo directo detectable con el CSV. Posibles causas: executor no corriendo en ese minuto, cooldown global, diferencia de snapshot, o regla interna adicional.",
    }


def main() -> None:
    journal, trades = load_inputs()
    micro = filter_micro_setups(journal)

    if not trades.empty:
        first_trade_time = trades["entry_time_dt"].min()
    else:
        first_trade_time = pd.NaT

    rows = []

    for _, row in micro.iterrows():
        info = classify(row, trades, first_trade_time)

        rows.append({
            "observed_at": row.get("observed_at", ""),
            "taken_status": info["taken_status"],
            "why_not_taken": info["why_not_taken"],
            "blocking_trade_id": info["blocking_trade_id"],
            "blocking_note": info["blocking_note"],
            "signal_key_short": short_signal(row.get("signal_key", "")),
            "question": row.get("question", ""),
            "best_bid": row.get("best_bid", math.nan),
            "best_ask": row.get("best_ask", math.nan),
            "spread": row.get("spread", math.nan),
            "score": row.get("score", math.nan),
            "fair_edge_to_ask": row.get("fair_edge_to_ask", math.nan),
            "binance_bias": row.get("binance_bias", ""),
            "flow_bias": row.get("flow_bias", ""),
            "crypto_alignment": row.get("crypto_alignment", ""),
            "crypto_decision": row.get("crypto_decision", ""),
        })

    report = pd.DataFrame(rows)

    report.to_csv(OUT_CSV, index=False)

    with OUT_TXT.open("w") as f:
        f.write("=== MICRO MISSED SETUPS REPORT ===\n")
        f.write(f"Micro setups exactos encontrados: {len(report)}\n")
        f.write(f"Trades micro registrados: {len(trades)}\n")
        f.write(f"Archivo detalle: {OUT_CSV}\n\n")

        if report.empty:
            f.write("No hay setups micro exactos en el journal.\n")
        else:
            f.write("=== RESUMEN POR CAUSA ===\n")
            f.write(report["why_not_taken"].value_counts(dropna=False).to_string())
            f.write("\n\n")

            f.write("=== TOMADOS VS NO TOMADOS ===\n")
            f.write(report["taken_status"].value_counts(dropna=False).to_string())
            f.write("\n\n")

            f.write("=== DETALLE ===\n")
            cols = [
                "observed_at",
                "taken_status",
                "why_not_taken",
                "blocking_trade_id",
                "best_bid",
                "best_ask",
                "score",
                "fair_edge_to_ask",
                "flow_bias",
                "question",
                "blocking_note",
            ]
            f.write(report[cols].to_string(index=False))
            f.write("\n")

    print("\n=== MICRO MISSED SETUPS REPORT ===")
    print(f"Micro setups exactos encontrados: {len(report)}")
    print(f"Trades micro registrados: {len(trades)}")
    print(f"CSV: {OUT_CSV}")
    print(f"TXT: {OUT_TXT}")

    if not report.empty:
        print("\n=== RESUMEN POR CAUSA ===")
        print(report["why_not_taken"].value_counts(dropna=False).to_string())

        print("\n=== TOMADOS VS NO TOMADOS ===")
        print(report["taken_status"].value_counts(dropna=False).to_string())

        print("\n=== DETALLE CORTO ===")
        cols = [
            "observed_at",
            "taken_status",
            "why_not_taken",
            "best_ask",
            "score",
            "fair_edge_to_ask",
            "flow_bias",
            "question",
        ]
        print(report[cols].to_string(index=False))


if __name__ == "__main__":
    main()
