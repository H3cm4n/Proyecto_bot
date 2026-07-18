from __future__ import annotations

from pathlib import Path
import math
import os

import pandas as pd


TRADES = Path(os.getenv("PAPER_TRADES_PATH", "data/paper_trades.csv"))
CYCLES = Path(os.getenv("CYCLE_JOURNAL_PATH", "data/cycle_journal.csv"))
JOURNAL = Path(os.getenv("CANDIDATE_JOURNAL_PATH", "data/candidate_journal.csv"))

SUMMARY_OUT = Path(os.getenv("TS_RISK_SUMMARY_OUT", "data/time_series_risk_summary.csv"))
EXPECTANCY_OUT = Path(os.getenv("TS_EXPECTANCY_OUT", "data/trade_expectancy_by_signal.csv"))
BAYES_OUT = Path(os.getenv("TS_BAYES_OUT", "data/bayes_trade_evidence_report.csv"))
OPEN_RISK_OUT = Path(os.getenv("TS_OPEN_RISK_OUT", "data/open_position_stat_risk.csv"))

INITIAL_CAPITAL = float(os.getenv("RISK_INITIAL_CAPITAL", "1000"))
MIN_EXPECTANCY_SAMPLES = int(os.getenv("RISK_MIN_EXPECTANCY_SAMPLES", "10"))
BAYES_EARLY_WINDOW_MINUTES = int(os.getenv("BAYES_EARLY_WINDOW_MINUTES", "10"))


def safe_str(value) -> str:
    if value is None:
        return ""

    text = str(value)

    if text.lower() == "nan":
        return ""

    return text


def safe_float(value, default=None):
    try:
        if value is None:
            return default

        text = str(value).strip()

        if text == "" or text.lower() == "nan":
            return default

        return float(text)
    except Exception:
        return default


def ratio(mean_value: float, std_value: float):
    if std_value is None or std_value == 0 or math.isnan(std_value):
        return None

    return mean_value / std_value


def ci95(mean_value: float, std_value: float, n: int) -> tuple[float | None, float | None]:
    if n <= 1 or std_value is None or math.isnan(std_value):
        return None, None

    margin = 1.96 * std_value / math.sqrt(n)
    return mean_value - margin, mean_value + margin


def signal_group(row: pd.Series) -> str:
    parts = []

    for col in ["crypto_symbol", "outcome", "trade_direction", "crypto_decision"]:
        if col in row.index:
            value = safe_str(row.get(col)).strip()

            if value:
                parts.append(value)

    if not parts:
        parts = [
            safe_str(row.get("crypto_symbol")).strip(),
            safe_str(row.get("outcome")).strip(),
        ]

    return "|".join([p for p in parts if p]) or "UNKNOWN"


def load_trades() -> pd.DataFrame:
    if not TRADES.exists():
        raise FileNotFoundError(f"No existe {TRADES}")

    trades = pd.read_csv(TRADES)

    if trades.empty:
        return trades

    for col in [
        "entry_price",
        "current_bid",
        "current_ask",
        "trade_usd",
        "current_value_usd",
        "pnl_usd",
        "pnl_pct",
        "take_profit_price",
        "stop_loss_price",
    ]:
        if col in trades.columns:
            trades[col] = pd.to_numeric(trades[col], errors="coerce")

    for col in ["opened_at", "closed_at"]:
        if col in trades.columns:
            trades[col + "_dt"] = pd.to_datetime(trades[col], errors="coerce", utc=True)

    trades["signal_group"] = trades.apply(signal_group, axis=1)

    return trades


def load_cycles() -> pd.DataFrame:
    if not CYCLES.exists():
        return pd.DataFrame()

    cycles = pd.read_csv(CYCLES)

    if cycles.empty:
        return cycles

    if "observed_at" in cycles.columns:
        cycles["observed_at_dt"] = pd.to_datetime(cycles["observed_at"], errors="coerce", utc=True)

    if "paper_total_pnl_usd" in cycles.columns:
        cycles["paper_total_pnl_usd"] = pd.to_numeric(cycles["paper_total_pnl_usd"], errors="coerce")

    return cycles


def load_journal() -> pd.DataFrame:
    if not JOURNAL.exists():
        return pd.DataFrame()

    journal = pd.read_csv(JOURNAL)

    if journal.empty:
        return journal

    if "observed_at" in journal.columns:
        journal["observed_at_dt"] = pd.to_datetime(journal["observed_at"], errors="coerce", utc=True)

    return journal


def compute_equity_metrics(cycles: pd.DataFrame, trades: pd.DataFrame) -> list[dict]:
    rows = []

    if not cycles.empty and "paper_total_pnl_usd" in cycles.columns:
        equity = cycles[["observed_at_dt", "paper_total_pnl_usd"]].copy()
        equity = equity.dropna(subset=["paper_total_pnl_usd"])
        equity = equity.sort_values("observed_at_dt")

        equity["equity_usd"] = INITIAL_CAPITAL + equity["paper_total_pnl_usd"]
        equity["running_peak"] = equity["equity_usd"].cummax()
        equity["drawdown_usd"] = equity["equity_usd"] - equity["running_peak"]
        equity["drawdown_pct"] = equity["drawdown_usd"] / equity["running_peak"] * 100
        equity["return"] = equity["equity_usd"].pct_change()

        returns = equity["return"].dropna()
        downside = returns[returns < 0]

        mean_return = returns.mean() if not returns.empty else None
        std_return = returns.std(ddof=1) if len(returns) > 1 else None
        downside_std = downside.std(ddof=1) if len(downside) > 1 else None

        rows.extend(
            [
                {
                    "metric": "initial_capital_usd",
                    "value": INITIAL_CAPITAL,
                    "notes": "Base usada para calcular drawdown y retornos.",
                },
                {
                    "metric": "max_drawdown_usd",
                    "value": equity["drawdown_usd"].min(),
                    "notes": "Mayor caída desde un pico de equity.",
                },
                {
                    "metric": "max_drawdown_pct",
                    "value": equity["drawdown_pct"].min(),
                    "notes": "Drawdown porcentual sobre capital configurado.",
                },
                {
                    "metric": "cycle_sharpe_ratio",
                    "value": ratio(mean_return, std_return) if mean_return is not None else None,
                    "notes": "Sharpe por ciclo, no anualizado.",
                },
                {
                    "metric": "cycle_sortino_ratio",
                    "value": ratio(mean_return, downside_std) if mean_return is not None else None,
                    "notes": "Sortino por ciclo, no anualizado.",
                },
                {
                    "metric": "best_equity_usd",
                    "value": equity["equity_usd"].max(),
                    "notes": "Mayor equity observada.",
                },
                {
                    "metric": "worst_equity_usd",
                    "value": equity["equity_usd"].min(),
                    "notes": "Menor equity observada.",
                },
            ]
        )

    closed = trades[trades["status"].astype(str).eq("CLOSED")].copy() if not trades.empty else pd.DataFrame()

    if not closed.empty and "pnl_pct" in closed.columns:
        trade_returns = closed["pnl_pct"].dropna() / 100
        downside = trade_returns[trade_returns < 0]

        mean_trade_return = trade_returns.mean() if not trade_returns.empty else None
        std_trade_return = trade_returns.std(ddof=1) if len(trade_returns) > 1 else None
        downside_std = downside.std(ddof=1) if len(downside) > 1 else None

        rows.extend(
            [
                {
                    "metric": "closed_trades",
                    "value": len(closed),
                    "notes": "Número de trades cerrados.",
                },
                {
                    "metric": "trade_expectancy_usd",
                    "value": closed["pnl_usd"].mean(),
                    "notes": "Esperanza matemática promedio por trade.",
                },
                {
                    "metric": "trade_expectancy_pct",
                    "value": closed["pnl_pct"].mean(),
                    "notes": "PnL porcentual promedio por trade.",
                },
                {
                    "metric": "trade_pnl_std_pct",
                    "value": closed["pnl_pct"].std(ddof=1),
                    "notes": "Desviación estándar del PnL porcentual.",
                },
                {
                    "metric": "trade_sharpe_ratio",
                    "value": ratio(mean_trade_return, std_trade_return) if mean_trade_return is not None else None,
                    "notes": "Sharpe basado en retornos por trade, no anualizado.",
                },
                {
                    "metric": "trade_sortino_ratio",
                    "value": ratio(mean_trade_return, downside_std) if mean_trade_return is not None else None,
                    "notes": "Sortino basado en retornos por trade, no anualizado.",
                },
            ]
        )

    return rows


def compute_expectancy(trades: pd.DataFrame) -> pd.DataFrame:
    if trades.empty:
        return pd.DataFrame()

    closed = trades[trades["status"].astype(str).eq("CLOSED")].copy()

    if closed.empty:
        return pd.DataFrame()

    rows = []

    for group_name, group in closed.groupby("signal_group", dropna=False):
        wins = group[group["pnl_usd"] > 0]
        losses = group[group["pnl_usd"] < 0]

        n = len(group)
        win_rate = len(wins) / n if n else 0
        avg_win = wins["pnl_usd"].mean() if not wins.empty else 0
        avg_loss = losses["pnl_usd"].mean() if not losses.empty else 0
        expectancy = win_rate * avg_win + (1 - win_rate) * avg_loss

        mean_pct = group["pnl_pct"].mean()
        std_pct = group["pnl_pct"].std(ddof=1) if n > 1 else None
        low_ci, high_ci = ci95(mean_pct, std_pct, n)

        if std_pct is not None and not math.isnan(std_pct):
            noise_stop_2sigma_pct = mean_pct - 2 * std_pct
        else:
            noise_stop_2sigma_pct = None

        rows.append(
            {
                "signal_group": group_name,
                "trades": n,
                "wins": len(wins),
                "losses": len(losses),
                "win_rate_pct": win_rate * 100,
                "avg_win_usd": avg_win,
                "avg_loss_usd": avg_loss,
                "expectancy_usd": expectancy,
                "avg_pnl_pct": mean_pct,
                "std_pnl_pct": std_pct,
                "ci95_low_avg_pnl_pct": low_ci,
                "ci95_high_avg_pnl_pct": high_ci,
                "noise_stop_2sigma_pct": noise_stop_2sigma_pct,
                "entry_decision": (
                    "ALLOW_STATISTICALLY"
                    if n >= MIN_EXPECTANCY_SAMPLES and expectancy > 0 and low_ci is not None and low_ci > 0
                    else "BLOCK_OR_LOW_CONFIDENCE"
                ),
                "notes": (
                    "Muestra insuficiente"
                    if n < MIN_EXPECTANCY_SAMPLES
                    else "Evaluación estadística disponible"
                ),
            }
        )

    return pd.DataFrame(rows).sort_values(
        ["entry_decision", "expectancy_usd"],
        ascending=[True, False],
    )


def early_evidence_state(trade: pd.Series, journal: pd.DataFrame) -> str:
    if journal.empty:
        return "NO_JOURNAL"

    required = ["crypto_symbol", "outcome", "question", "observed_at_dt"]
    if any(col not in journal.columns for col in required):
        return "NO_JOURNAL_COLUMNS"

    opened_at = trade.get("opened_at_dt")

    if pd.isna(opened_at):
        return "NO_OPEN_TIME"

    symbol = safe_str(trade.get("crypto_symbol")).strip().upper()
    outcome = safe_str(trade.get("outcome")).strip()
    question = safe_str(trade.get("question")).strip()

    end_at = opened_at + pd.Timedelta(minutes=BAYES_EARLY_WINDOW_MINUTES)

    rows = journal[
        journal["crypto_symbol"].astype(str).str.upper().eq(symbol)
        & journal["outcome"].astype(str).eq(outcome)
        & journal["question"].astype(str).eq(question)
        & (journal["observed_at_dt"] >= opened_at)
        & (journal["observed_at_dt"] <= end_at)
    ].copy()

    if rows.empty:
        return "NO_EARLY_EVIDENCE"

    alignments = rows.get("crypto_alignment", pd.Series(dtype=str)).astype(str).str.upper()

    conflict_frac = (alignments == "CONFLICT").mean()
    aligned_frac = (alignments == "ALIGNED").mean()
    neutral_frac = (alignments == "NEUTRAL").mean()

    if conflict_frac > 0:
        return "EARLY_CONFLICT"

    if aligned_frac >= 0.5:
        return "EARLY_ALIGNED"

    if neutral_frac >= 0.5:
        return "EARLY_NEUTRAL"

    return "EARLY_MIXED"


def compute_bayes_report(trades: pd.DataFrame, journal: pd.DataFrame) -> pd.DataFrame:
    if trades.empty:
        return pd.DataFrame()

    closed = trades[trades["status"].astype(str).eq("CLOSED")].copy()

    if closed.empty:
        return pd.DataFrame()

    closed["is_win"] = closed["pnl_usd"] > 0
    closed["early_evidence"] = closed.apply(lambda row: early_evidence_state(row, journal), axis=1)

    evidence_states = sorted(closed["early_evidence"].dropna().unique().tolist())
    k = max(len(evidence_states), 1)

    total = len(closed)
    wins = int(closed["is_win"].sum())
    losses = total - wins

    # Beta(1,1) smoothing.
    prior_success = (wins + 1) / (total + 2)

    rows = []

    for _, trade in closed.iterrows():
        evidence = trade["early_evidence"]

        wins_with_evidence = len(closed[(closed["is_win"]) & (closed["early_evidence"] == evidence)])
        losses_with_evidence = len(closed[(~closed["is_win"]) & (closed["early_evidence"] == evidence)])

        p_evidence_given_win = (wins_with_evidence + 1) / (wins + k)
        p_evidence_given_loss = (losses_with_evidence + 1) / (losses + k)

        numerator = p_evidence_given_win * prior_success
        denominator = numerator + p_evidence_given_loss * (1 - prior_success)

        posterior_success = numerator / denominator if denominator else prior_success

        if posterior_success < 0.35:
            bayes_action = "STAT_CONVICTION_LOSS"
        elif posterior_success >= 0.55:
            bayes_action = "STAT_SUPPORTS_HOLD"
        else:
            bayes_action = "STAT_UNCERTAIN"

        rows.append(
            {
                "crypto_symbol": trade.get("crypto_symbol"),
                "outcome": trade.get("outcome"),
                "question": trade.get("question"),
                "signal_group": trade.get("signal_group"),
                "pnl_usd": trade.get("pnl_usd"),
                "pnl_pct": trade.get("pnl_pct"),
                "is_win": trade.get("is_win"),
                "early_evidence": evidence,
                "prior_success_prob": prior_success,
                "posterior_success_prob": posterior_success,
                "bayes_action": bayes_action,
                "notes": "Bayes empírico con smoothing; baja confianza si hay pocos trades.",
            }
        )

    return pd.DataFrame(rows)


def compute_open_position_risk(trades: pd.DataFrame, expectancy: pd.DataFrame) -> pd.DataFrame:
    if trades.empty:
        return pd.DataFrame()

    open_trades = trades[trades["status"].astype(str).eq("OPEN")].copy()

    if open_trades.empty:
        return pd.DataFrame()

    expectancy_by_group = {
        row["signal_group"]: row
        for _, row in expectancy.iterrows()
    }

    rows = []

    for _, trade in open_trades.iterrows():
        group_name = trade.get("signal_group")
        stats = expectancy_by_group.get(group_name)

        pnl_pct = safe_float(trade.get("pnl_pct"), 0)

        if stats is None:
            rows.append(
                {
                    "signal_group": group_name,
                    "crypto_symbol": trade.get("crypto_symbol"),
                    "outcome": trade.get("outcome"),
                    "pnl_pct": pnl_pct,
                    "risk_state": "NO_HISTORY",
                    "z_score": None,
                    "notes": "No hay historial para comparar esta posición.",
                }
            )
            continue

        mean_pct = safe_float(stats.get("avg_pnl_pct"))
        std_pct = safe_float(stats.get("std_pnl_pct"))

        if std_pct is None or std_pct == 0:
            risk_state = "NO_STD"
            z_score = None
        else:
            z_score = (pnl_pct - mean_pct) / std_pct

            if z_score <= -2:
                risk_state = "OUTLIER_LOW"
            elif z_score >= 2:
                risk_state = "OUTLIER_HIGH"
            else:
                risk_state = "WITHIN_EXPECTED_RANGE"

        rows.append(
            {
                "signal_group": group_name,
                "crypto_symbol": trade.get("crypto_symbol"),
                "outcome": trade.get("outcome"),
                "pnl_pct": pnl_pct,
                "expected_avg_pnl_pct": mean_pct,
                "std_pnl_pct": std_pct,
                "z_score": z_score,
                "risk_state": risk_state,
                "notes": "OUTLIER_LOW puede justificar salida estadística.",
            }
        )

    return pd.DataFrame(rows)


def main() -> None:
    print("\n=== TIME SERIES RISK REPORT ===")

    trades = load_trades()
    cycles = load_cycles()
    journal = load_journal()

    summary = pd.DataFrame(compute_equity_metrics(cycles, trades))
    expectancy = compute_expectancy(trades)
    bayes = compute_bayes_report(trades, journal)
    open_risk = compute_open_position_risk(trades, expectancy)

    SUMMARY_OUT.parent.mkdir(parents=True, exist_ok=True)

    summary.to_csv(SUMMARY_OUT, index=False)
    expectancy.to_csv(EXPECTANCY_OUT, index=False)
    bayes.to_csv(BAYES_OUT, index=False)
    open_risk.to_csv(OPEN_RISK_OUT, index=False)

    print(f"Capital base: ${INITIAL_CAPITAL:.2f}")
    print(f"Archivo resumen: {SUMMARY_OUT}")
    print(f"Archivo expectancy: {EXPECTANCY_OUT}")
    print(f"Archivo Bayes: {BAYES_OUT}")
    print(f"Archivo riesgo posiciones abiertas: {OPEN_RISK_OUT}")

    if not summary.empty:
        print("\n=== MÉTRICAS PRINCIPALES ===")
        print(summary.to_string(index=False))

    if not expectancy.empty:
        print("\n=== EXPECTANCY POR SEÑAL ===")
        cols = [
            "signal_group",
            "trades",
            "win_rate_pct",
            "expectancy_usd",
            "avg_pnl_pct",
            "std_pnl_pct",
            "noise_stop_2sigma_pct",
            "entry_decision",
            "notes",
        ]
        print(expectancy[cols].to_string(index=False))

    if not bayes.empty:
        print("\n=== BAYES EARLY EVIDENCE ===")
        cols = [
            "crypto_symbol",
            "outcome",
            "early_evidence",
            "prior_success_prob",
            "posterior_success_prob",
            "bayes_action",
            "pnl_pct",
            "question",
        ]
        print(bayes[cols].to_string(index=False))

    if not open_risk.empty:
        print("\n=== OPEN POSITION STAT RISK ===")
        print(open_risk.to_string(index=False))
    else:
        print("\nNo hay posiciones abiertas para evaluar con bandas estadísticas.")


if __name__ == "__main__":
    main()
