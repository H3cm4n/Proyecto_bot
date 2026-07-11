from collections import Counter
from pathlib import Path
from typing import Any

import pandas as pd

from app.backtesting.replay_audit import (
    load_replay_history,
    safe_float,
    safe_int,
    safe_str,
)


DEFAULT_HISTORY_PATH = Path("data/orderbook_history.csv")


def normalize_question(value: Any) -> str:
    return safe_str(value).strip()


def detect_category(question: str) -> str:
    q = question.lower()

    if "gta vi" in q or "album" in q or "taylor swift" in q or "rihanna" in q or "playboi" in q:
        return "culture_pop_gta"

    if "bitcoin" in q or "btc" in q or "crypto" in q or "ipo" in q or "kraken" in q:
        return "crypto_finance"

    if "election" in q or "president" in q or "speaker" in q or "trump" in q or "macron" in q:
        return "politics"

    if "ukraine" in q or "nato" in q or "china" in q or "india" in q or "taiwan" in q or "military" in q or "war" in q:
        return "geopolitics"

    if "pandemic" in q or "covid" in q or "disease" in q:
        return "health_global"

    return "other"


def add_numeric_columns(df: pd.DataFrame) -> pd.DataFrame:
    result = df.copy()

    for column in [
        "score",
        "edge_score",
        "edge_mid_delta",
        "best_bid",
        "best_ask",
        "spread",
        "top_liquidity",
        "relative_spread_pct",
    ]:
        if column not in result.columns:
            result[column] = ""

    result["question_clean"] = result["question"].apply(normalize_question) if "question" in result.columns else ""
    result["category"] = result["question_clean"].apply(detect_category)

    result["score_num"] = result["score"].apply(safe_int)
    result["edge_score_num"] = result["edge_score"].apply(safe_int)
    result["edge_mid_delta_num"] = result["edge_mid_delta"].apply(safe_float)
    result["best_bid_num"] = result["best_bid"].apply(safe_float)
    result["best_ask_num"] = result["best_ask"].apply(safe_float)
    result["spread_num"] = result["spread"].apply(safe_float)
    result["top_liquidity_num"] = result["top_liquidity"].apply(safe_float)
    result["relative_spread_pct_num"] = result["relative_spread_pct"].apply(safe_float)

    if "observed_at" not in result.columns:
        result["observed_at"] = ""

    if "action" not in result.columns:
        result["action"] = ""

    if "grade" not in result.columns:
        result["grade"] = ""

    if "edge_action" not in result.columns:
        result["edge_action"] = ""

    if "outcome" not in result.columns:
        result["outcome"] = ""

    if "token_id" not in result.columns:
        result["token_id"] = ""

    return result


def bucket_edge(edge_score: int) -> str:
    if edge_score <= 0:
        return "0_no_history_or_missing"
    if edge_score < 45:
        return "1_weak_under_45"
    if edge_score < 65:
        return "2_neutral_45_64"
    if edge_score < 80:
        return "3_strong_65_79"
    return "4_very_strong_80_plus"


def bucket_score(score: int) -> str:
    if score < 50:
        return "0_under_50"
    if score < 65:
        return "1_50_64"
    if score < 80:
        return "2_65_79"
    if score < 90:
        return "3_80_89"
    return "4_90_plus"


def bucket_price(ask: float) -> str:
    if ask <= 0:
        return "0_missing"
    if ask < 0.05:
        return "1_under_0.05"
    if ask <= 0.20:
        return "2_0.05_0.20"
    if ask <= 0.80:
        return "3_0.20_0.80"
    if ask <= 0.90:
        return "4_0.80_0.90"
    return "5_over_0.90"


def count_series(series: pd.Series, limit: int = 20) -> list[dict[str, Any]]:
    counts = series.fillna("").astype(str).value_counts().head(limit)

    return [
        {"name": str(index), "count": int(value)}
        for index, value in counts.items()
    ]


def top_questions_by_metric(
    df: pd.DataFrame,
    metric: str,
    limit: int = 15,
    min_rows: int = 1,
) -> list[dict[str, Any]]:
    if df.empty:
        return []

    grouped = (
        df.groupby("question_clean")
        .agg(
            rows=("question_clean", "size"),
            avg_score=("score_num", "mean"),
            max_score=("score_num", "max"),
            avg_edge=("edge_score_num", "mean"),
            max_edge=("edge_score_num", "max"),
            avg_delta=("edge_mid_delta_num", "mean"),
            avg_spread=("spread_num", "mean"),
            avg_rel_spread=("relative_spread_pct_num", "mean"),
            avg_top_liq=("top_liquidity_num", "mean"),
            category=("category", "first"),
        )
        .reset_index()
    )

    grouped = grouped[grouped["rows"] >= min_rows]

    if metric not in grouped.columns:
        return []

    grouped = grouped.sort_values(metric, ascending=False).head(limit)

    return grouped.to_dict(orient="records")


def calculate_universe_report(
    history_path: Path = DEFAULT_HISTORY_PATH,
    limit: int = 15,
) -> dict[str, Any]:
    raw = load_replay_history(history_path)

    if raw.empty:
        return {
            "history_path": str(history_path),
            "summary": {
                "rows": 0,
                "cycles": 0,
                "unique_questions": 0,
                "unique_tokens": 0,
            },
            "tables": {},
        }

    df = add_numeric_columns(raw)

    df["edge_bucket"] = df["edge_score_num"].apply(bucket_edge)
    df["score_bucket"] = df["score_num"].apply(bucket_score)
    df["price_bucket"] = df["best_ask_num"].apply(bucket_price)

    strong_score = df["score_num"] >= 80
    strong_edge = df["edge_score_num"] >= 65
    positive_delta = df["edge_mid_delta_num"] >= 0.005
    good_price = (df["best_ask_num"] >= 0.05) & (df["best_ask_num"] <= 0.90)
    good_spread = df["relative_spread_pct_num"] <= 10
    good_liquidity = df["top_liquidity_num"] >= 10

    eligible_like = strong_score & strong_edge & positive_delta & good_price & good_spread & good_liquidity

    summary = {
        "rows": len(df),
        "cycles": df["observed_at"].nunique(),
        "unique_questions": df["question_clean"].nunique(),
        "unique_tokens": df["token_id"].nunique(),
        "strong_score_rows": int(strong_score.sum()),
        "strong_edge_rows": int(strong_edge.sum()),
        "positive_delta_rows": int(positive_delta.sum()),
        "eligible_like_rows": int(eligible_like.sum()),
        "avg_score": round(float(df["score_num"].mean()), 2),
        "avg_edge": round(float(df["edge_score_num"].mean()), 2),
        "avg_relative_spread_pct": round(float(df["relative_spread_pct_num"].mean()), 2),
    }

    tables = {
        "categories": count_series(df["category"], limit=limit),
        "actions": count_series(df["action"], limit=limit),
        "edge_actions": count_series(df["edge_action"], limit=limit),
        "grades": count_series(df["grade"], limit=limit),
        "edge_buckets": count_series(df["edge_bucket"], limit=limit),
        "score_buckets": count_series(df["score_bucket"], limit=limit),
        "price_buckets": count_series(df["price_bucket"], limit=limit),
        "most_repeated_questions": top_questions_by_metric(df, "rows", limit=limit),
        "top_avg_score_questions": top_questions_by_metric(df, "avg_score", limit=limit, min_rows=2),
        "top_max_edge_questions": top_questions_by_metric(df, "max_edge", limit=limit),
        "top_avg_liquidity_questions": top_questions_by_metric(df, "avg_top_liq", limit=limit, min_rows=2),
    }

    return {
        "history_path": str(history_path),
        "summary": summary,
        "tables": tables,
    }
