"""stools/filter_directional_limit_hunter_snapshot.py
Filetro v1.5 para candidato Directional Limit Hunter.
Incorpora filtrado por Spread Relativo desde core.orderbook.
"""

import sys
import json
from core.orderbook import calculate_relative_spread

def filter_candidates(snapshot_data: list, min_score: float = 65.0, min_edge: float = 0.20, max_rel_spread: float = 0.08) -> list:
    candidates = []
    
    for item in snapshot_data:
        best_bid = item.get("best_bid", 0.0)
        best_ask = item.get("best_ask", 1.0)
        score = item.get("score", 0.0)
        edge = item.get("fair_edge_to_ask", item.get("fair_edge", 0.0))
        decision = item.get("crypto_decision", item.get("decision", ""))
        
        if decision not in ["CRYPTO_BUY_FAIR_EDGE", "CRYPTO_WAIT_ENTRY_ASK_TOO_HIGH"]:
            continue
            
        if score < min_score or edge < min_edge:
            continue
            
        rel_spread = calculate_relative_spread(best_bid, best_ask)
        if rel_spread > max_rel_spread:
            continue

        item["limit_price"] = round(min(best_ask, 0.80), 4)
        item["relative_spread"] = rel_spread
        candidates.append(item)
        
    return candidates

if __name__ == "__main__":
    try:
        raw = sys.stdin.read()
        if raw.strip():
            data = json.loads(raw)
            filtered = filter_candidates(data)
            print(json.dumps(filtered, indent=2))
        else:
            print(json.dumps([]))
    except Exception as e:
        sys.stderr.write(f"Error filtrando snapshot: {e}\n")
        print(json.dumps([]))
