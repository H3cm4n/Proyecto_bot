"""
services/market_resolver.py
Resuelve token_ids de Polymarket priorizando mercados activos de alto volumen mediante q y tags.
"""

import sys
import json
import re
import requests


class MarketResolver:
    def __init__(self):
        self.gamma_events_url = "https://gamma-api.polymarket.com/events"
        self.gamma_markets_url = "https://gamma-api.polymarket.com/markets"
        self.blacklist = ["megaeth", "ethernet", "bitcoincash", "hegseth"]

    def _is_valid_match(self, text: str, aliases: list) -> bool:
        t = text.lower()
        if any(b in t for b in self.blacklist):
            return False
        for a in aliases:
            # Revisa coincidencia con separadores comunes en preguntas/slugs (espacio, guion, punto, etc.)
            pattern = r"(^|[^a-z0-9])" + re.escape(a) + r"($|[^a-z0-9])"
            if re.search(pattern, t):
                return True
        return False

    def get_market_tokens(self, query_text: str) -> dict:
        try:
            query_lower = query_text.lower().strip()
            aliases = [query_lower]
            tag_slug = None

            if query_lower in ["ethereum", "eth"]:
                aliases = ["ethereum", "eth"]
                tag_slug = "ethereum"
            elif query_lower in ["bitcoin", "btc"]:
                aliases = ["bitcoin", "btc"]
                tag_slug = "bitcoin"

            # 1. Búsqueda en /events filtrando por q (cadena o alias)
            for alias in aliases:
                params = {"limit": 50, "active": "true", "closed": "false", "q": alias}
                res = requests.get(self.gamma_events_url, params=params, timeout=10)
                if res.status_code == 200:
                    for ev in res.json():
                        for m in ev.get("markets", []):
                            q_text = m.get("question", "")
                            s_text = m.get("slug", "")
                            if self._is_valid_match(q_text, aliases) or self._is_valid_match(s_text, aliases):
                                clob_ids = m.get("clobTokenIds", [])
                                if isinstance(clob_ids, str):
                                    clob_ids = json.loads(clob_ids)
                                if len(clob_ids) >= 2:
                                    return {
                                        "YES": clob_ids[0],
                                        "NO": clob_ids[1],
                                        "question": m.get("question"),
                                        "condition_id": m.get("conditionId")
                                    }

            # 2. Búsqueda en /events filtrando por tag_slug si la búsqueda textual directa falló
            if tag_slug:
                params_tag = {"limit": 50, "active": "true", "closed": "false", "tag_slug": tag_slug}
                res_t = requests.get(self.gamma_events_url, params=params_tag, timeout=10)
                if res_t.status_code == 200:
                    for ev in res_t.json():
                        for m in ev.get("markets", []):
                            clob_ids = m.get("clobTokenIds", [])
                            if isinstance(clob_ids, str):
                                clob_ids = json.loads(clob_ids)
                            if len(clob_ids) >= 2:
                                return {
                                    "YES": clob_ids[0],
                                    "NO": clob_ids[1],
                                    "question": m.get("question"),
                                    "condition_id": m.get("conditionId")
                                }

            # 3. Fallback general ordenado por volumen en /markets
            params_m = {"active": "true", "closed": "false", "limit": 200, "order": "volume", "ascending": "false"}
            res_m = requests.get(self.gamma_markets_url, params=params_m, timeout=10)
            if res_m.status_code == 200:
                for m in res_m.json():
                    q_text = m.get("question", "")
                    s_text = m.get("slug", "")
                    if self._is_valid_match(q_text, aliases) or self._is_valid_match(s_text, aliases):
                        clob_ids = m.get("clobTokenIds", [])
                        if isinstance(clob_ids, str):
                            clob_ids = json.loads(clob_ids)
                        if len(clob_ids) >= 2:
                            return {
                                "YES": clob_ids[0],
                                "NO": clob_ids[1],
                                "question": m.get("question"),
                                "condition_id": m.get("conditionId")
                            }

            sys.stderr.write(f"[RESOLVER] No se encontro mercado para: '{query_text}'\n")
            return {}
        except Exception as e:
            sys.stderr.write(f"Resolver error: {e}\n")
            return {}
