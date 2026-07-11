from collections import Counter, defaultdict
from pathlib import Path
from typing import Any

import pandas as pd


DEFAULT_HISTORY_PATH = Path("data/orderbook_history.csv")
DEFAULT_OUTPUT_PATH = Path("data/replay_audit.csv")

ALLOWED_ACTIONS = {"PRIORITY_WATCH", "WATCH"}
ALLOWED_EDGE_ACTIONS = {"EDGE_BUY", "EDGE_WATCH"}


def safe_float(value: Any, default: float = 0.0) -> float:
    try:
        if value is None or value == "":
            return default
        return float(value)
    except (TypeError, ValueError):
        return default


def safe_int(value: Any, default: int = 0) -> int:
    try:
        if value is None or value == "":
            return default
        return int(float(value))
    except (TypeError, ValueError):
        return default


def safe_str(value: Any) -> str:
    if value is None:
        return ""
    return str(value)


def load_replay_history(path: Path = DEFAULT_HISTORY_PATH) -> pd.DataFrame:
    if not path.exists():
        return pd.DataFrame()

    try:
        return pd.read_csv(path, dtype=str, on_bad_lines="skip").fillna("")
    except Exception:
        return pd.DataFrame()


def calc_relative_spread_pct(row: dict[str, Any]) -> float:
    existing = safe_str(row.get("relative_spread_pct", ""))

    if existing != "":
        return safe_float(existing, default=999.0)

    spread = safe_float(row.get("spread"), default=0.0)
    ask = safe_float(row.get("best_ask"), default=0.0)

    if ask <= 0:
        return 999.0

    return round((spread / ask) * 100, 2)


def get_top_liquidity(row: dict[str, Any]) -> float:
    existing = safe_str(row.get("top_liquidity", ""))

    if existing != "":
        return safe_float(existing)

    bid_size = safe_float(row.get("bid_size"))
    ask_size = safe_float(row.get("ask_size"))

    if bid_size <= 0 or ask_size <= 0:
        return 0.0

    return min(bid_size, ask_size)


def explain_replay_decision(
    row: dict[str, Any],
    min_score: int = 80,
    min_edge_score: int = 65,
    min_edge_mid_delta: float = 0.005,
    min_entry_price: float = 0.05,
    max_entry_price: float = 0.90,
    min_top_liquidity: float = 10.0,
    max_relative_spread_pct: float = 10.0,
) -> dict[str, Any]:
    question = safe_str(row.get("question"))
    outcome = safe_str(row.get("outcome"))
    observed_at = safe_str(row.get("observed_at"))

    score = safe_int(row.get("score"))
    action = safe_str(row.get("action"))

    edge_score = safe_int(row.get("edge_score"))
    edge_action = safe_str(row.get("edge_action"))
    edge_mid_delta = safe_float(row.get("edge_mid_delta"))

    ask = safe_float(row.get("best_ask"))
    bid = safe_float(row.get("best_bid"))
    spread = safe_float(row.get("spread"))

    top_liquidity = get_top_liquidity(row)
    relative_spread_pct = calc_relative_spread_pct(row)

    reasons: list[str] = []

    if not question:
        reasons.append("NO_QUESTION")

    if score < min_score:
        reasons.append("SCORE_TOO_LOW")

    if action not in ALLOWED_ACTIONS:
        reasons.append("BAD_MARKET_ACTION")

    if min_edge_score > 0 and edge_score < min_edge_score:
        reasons.append("EDGE_TOO_LOW")

    if min_edge_score > 0 and edge_action not in ALLOWED_EDGE_ACTIONS:
        reasons.append("BAD_EDGE_ACTION")

    if min_edge_score > 0 and edge_mid_delta < min_edge_mid_delta:
        reasons.append("DELTA_TOO_SMALL")

    if ask < min_entry_price:
        reasons.append("ENTRY_TOO_LOW")

    if ask > max_entry_price:
        reasons.append("ENTRY_TOO_HIGH")

    if top_liquidity < min_top_liquidity:
        reasons.append("LOW_TOP_LIQUIDITY")

    if relative_spread_pct > max_relative_spread_pct:
        reasons.append("RELATIVE_SPREAD_TOO_HIGH")

    eligible = len(reasons) == 0

    return {
        "observed_at": observed_at,
        "decision": "PASS" if eligible else "REJECT",
        "reasons": ", ".join(reasons),
        "question": question,
        "outcome": outcome,
        "token_id": safe_str(row.get("token_id")),
        "score": score,
        "action": action,
        "edge_score": edge_score,
        "edge_action": edge_action,
        "edge_mid_delta": edge_mid_delta,
        "bid": bid,
        "ask": ask,
        "spread": spread,
        "top_liquidity": top_liquidity,
        "relative_spread_pct": relative_spread_pct,
    }


def sort_replay_candidates(rows: list[dict[str, Any]]) -> list[dict[str, Any]]:
    return sorted(
        rows,
        key=lambda row: (
            safe_int(row.get("score")),
            safe_int(row.get("edge_score")),
            safe_float(row.get("top_liquidity")),
            -safe_float(row.get("relative_spread_pct")),
        ),
        reverse=True,
    )


def apply_cycle_selection(
    audited_rows: list[dict[str, Any]],
    proposal_limit: int = 3,
) -> list[dict[str, Any]]:
    grouped: dict[str, list[dict[str, Any]]] = defaultdict(list)

    for row in audited_rows:
        grouped[safe_str(row.get("observed_at"))].append(row)

    final_rows: list[dict[str, Any]] = []

    for observed_at, rows in grouped.items():
        pass_rows = [row for row in rows if row.get("decision") == "PASS"]
        reject_rows = [row for row in rows if row.get("decision") != "PASS"]

        selected_count = 0
        selected_questions: set[str] = set()

        for row in sort_replay_candidates(pass_rows):
            question = safe_str(row.get("question"))

            if question in selected_questions:
                row["decision"] = "REJECT"
                row["reasons"] = "DUPLICATE_QUESTION_IN_CYCLE"
            elif selected_count >= proposal_limit:
                row["decision"] = "REJECT"
                row["reasons"] = "CYCLE_PROPOSAL_LIMIT"
            else:
                row["decision"] = "SELECTED"
                row["reasons"] = ""
                selected_questions.add(question)
                selected_count += 1

            final_rows.append(row)

        final_rows.extend(reject_rows)

    return final_rows



def split_reasons(reasons: Any) -> list[str]:
    raw = safe_str(reasons)

    if not raw:
        return []

    return [reason.strip() for reason in raw.split(",") if reason.strip()]


def rank_near_misses(
    rows: list[dict[str, Any]],
    max_reasons: int = 2,
    limit: int = 20,
) -> list[dict[str, Any]]:
    candidates: list[dict[str, Any]] = []

    for row in rows:
        if row.get("decision") != "REJECT":
            continue

        reasons = split_reasons(row.get("reasons"))

        if not reasons:
            continue

        if len(reasons) > max_reasons:
            continue

        enriched = dict(row)
        enriched["reason_count"] = len(reasons)
        candidates.append(enriched)

    return sorted(
        candidates,
        key=lambda row: (
            -safe_int(row.get("reason_count")),
            safe_int(row.get("score")),
            safe_int(row.get("edge_score")),
            safe_float(row.get("edge_mid_delta")),
            safe_float(row.get("top_liquidity")),
            -safe_float(row.get("relative_spread_pct")),
        ),
        reverse=True,
    )[:limit]

def summarize_replay(rows: list[dict[str, Any]]) -> dict[str, Any]:
    reason_counter: Counter[str] = Counter()

    for row in rows:
        reasons = safe_str(row.get("reasons"))

        if not reasons:
            continue

        for reason in reasons.split(","):
            reason = reason.strip()

            if reason:
                reason_counter[reason] += 1

    selected_rows = [row for row in rows if row.get("decision") == "SELECTED"]
    rejected_rows = [row for row in rows if row.get("decision") == "REJECT"]

    cycles = {safe_str(row.get("observed_at")) for row in rows if safe_str(row.get("observed_at"))}

    return {
        "rows_analyzed": len(rows),
        "cycles_analyzed": len(cycles),
        "selected_count": len(selected_rows),
        "rejected_count": len(rejected_rows),
        "reason_counts": dict(reason_counter.most_common()),
        "selected_rows": sort_replay_candidates(selected_rows),
        "near_miss_rows": rank_near_misses(rows),
    }


def save_replay_audit(rows: list[dict[str, Any]], output_path: Path = DEFAULT_OUTPUT_PATH) -> None:
    output_path.parent.mkdir(parents=True, exist_ok=True)
    pd.DataFrame(rows).to_csv(output_path, index=False)


def run_replay_audit(
    history_path: Path = DEFAULT_HISTORY_PATH,
    output_path: Path = DEFAULT_OUTPUT_PATH,
    min_score: int = 80,
    min_edge_score: int = 65,
    min_edge_mid_delta: float = 0.005,
    proposal_limit: int = 3,
    min_entry_price: float = 0.05,
    max_entry_price: float = 0.90,
    min_top_liquidity: float = 10.0,
    max_relative_spread_pct: float = 10.0,
    save_output: bool = True,
) -> dict[str, Any]:
    history = load_replay_history(history_path)

    if history.empty:
        return {
            "history_path": str(history_path),
            "output_path": str(output_path),
            "rows": [],
            "summary": {
                "rows_analyzed": 0,
                "cycles_analyzed": 0,
                "selected_count": 0,
                "rejected_count": 0,
                "reason_counts": {},
                "selected_rows": [],
            },
        }

    raw_rows = history.to_dict(orient="records")

    audited_rows = [
        explain_replay_decision(
            row,
            min_score=min_score,
            min_edge_score=min_edge_score,
            min_edge_mid_delta=min_edge_mid_delta,
            min_entry_price=min_entry_price,
            max_entry_price=max_entry_price,
            min_top_liquidity=min_top_liquidity,
            max_relative_spread_pct=max_relative_spread_pct,
        )
        for row in raw_rows
    ]

    final_rows = apply_cycle_selection(
        audited_rows,
        proposal_limit=proposal_limit,
    )

    if save_output:
        save_replay_audit(final_rows, output_path)

    return {
        "history_path": str(history_path),
        "output_path": str(output_path),
        "rows": final_rows,
        "summary": summarize_replay(final_rows),
    }
