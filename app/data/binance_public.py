from __future__ import annotations

from datetime import datetime, timezone
from pathlib import Path
from typing import Any

import pandas as pd
import requests


BINANCE_BASE_URLS = [
    "https://api.binance.com",
    "https://api1.binance.com",
    "https://api2.binance.com",
    "https://api3.binance.com",
    "https://api4.binance.com",
]


DEFAULT_SYMBOLS = ["BTCUSDT", "ETHUSDT", "SOLUSDT", "XRPUSDT"]


def utc_now_iso() -> str:
    return datetime.now(timezone.utc).isoformat()


def safe_float(value: Any, default: float = 0.0) -> float:
    try:
        if value is None or value == "":
            return default
        return float(value)
    except (TypeError, ValueError):
        return default


def normalize_symbol(symbol: str) -> str:
    return str(symbol or "").strip().upper().replace("/", "")


def request_binance_json(
    path: str,
    params: dict[str, Any] | None = None,
    timeout: float = 10.0,
) -> tuple[Any, str]:
    """
    Request public Binance Spot REST data.

    Uses fallback base URLs because api.binance.com can occasionally timeout
    or be unavailable from some networks.
    """
    last_error: Exception | None = None

    for base_url in BINANCE_BASE_URLS:
        url = f"{base_url}{path}"
        try:
            response = requests.get(url, params=params or {}, timeout=timeout)
            response.raise_for_status()
            return response.json(), base_url
        except requests.RequestException as exc:
            last_error = exc
            continue

    raise RuntimeError(f"No Binance base URL responded successfully. Last error: {last_error}")


def get_symbol_price(symbol: str, timeout: float = 10.0) -> dict[str, Any]:
    symbol = normalize_symbol(symbol)
    data, base_url = request_binance_json(
        "/api/v3/ticker/price",
        params={"symbol": symbol},
        timeout=timeout,
    )

    return {
        "symbol": symbol,
        "price": safe_float(data.get("price")),
        "price_source_base_url": base_url,
    }


def get_24hr_ticker(symbol: str, timeout: float = 10.0) -> dict[str, Any]:
    symbol = normalize_symbol(symbol)
    data, base_url = request_binance_json(
        "/api/v3/ticker/24hr",
        params={"symbol": symbol},
        timeout=timeout,
    )

    return {
        "symbol": symbol,
        "price_change": safe_float(data.get("priceChange")),
        "price_change_pct_24h": safe_float(data.get("priceChangePercent")),
        "weighted_avg_price_24h": safe_float(data.get("weightedAvgPrice")),
        "last_price": safe_float(data.get("lastPrice")),
        "last_qty": safe_float(data.get("lastQty")),
        "open_price_24h": safe_float(data.get("openPrice")),
        "high_price_24h": safe_float(data.get("highPrice")),
        "low_price_24h": safe_float(data.get("lowPrice")),
        "volume_24h": safe_float(data.get("volume")),
        "quote_volume_24h": safe_float(data.get("quoteVolume")),
        "ticker_source_base_url": base_url,
    }


def get_klines(
    symbol: str,
    interval: str = "1m",
    limit: int = 60,
    timeout: float = 10.0,
) -> tuple[list[list[Any]], str]:
    symbol = normalize_symbol(symbol)

    data, base_url = request_binance_json(
        "/api/v3/klines",
        params={
            "symbol": symbol,
            "interval": interval,
            "limit": int(limit),
        },
        timeout=timeout,
    )

    return data, base_url


def calculate_kline_features(klines: list[list[Any]]) -> dict[str, Any]:
    """
    Binance kline format:
    [
      open_time, open, high, low, close, volume,
      close_time, quote_asset_volume, number_of_trades,
      taker_buy_base_volume, taker_buy_quote_volume, ignore
    ]
    """
    if not klines:
        return {
            "kline_count": 0,
            "last_close": 0.0,
            "momentum_5m_pct": 0.0,
            "momentum_15m_pct": 0.0,
            "momentum_full_window_pct": 0.0,
            "range_full_window_pct": 0.0,
            "vwap_full_window": 0.0,
            "quote_volume_full_window": 0.0,
            "trades_full_window": 0,
        }

    closes = [safe_float(k[4]) for k in klines]
    highs = [safe_float(k[2]) for k in klines]
    lows = [safe_float(k[3]) for k in klines]
    base_volumes = [safe_float(k[5]) for k in klines]
    quote_volumes = [safe_float(k[7]) for k in klines]
    trades = [int(safe_float(k[8])) for k in klines]

    last_close = closes[-1]
    first_close = closes[0]
    high = max(highs) if highs else 0.0
    low = min(lows) if lows else 0.0

    def momentum_pct(periods_back: int) -> float:
        if len(closes) <= periods_back:
            return 0.0

        previous = closes[-1 - periods_back]
        if previous <= 0:
            return 0.0

        return round(((last_close - previous) / previous) * 100, 4)

    full_window_pct = 0.0
    if first_close > 0:
        full_window_pct = round(((last_close - first_close) / first_close) * 100, 4)

    range_pct = 0.0
    if last_close > 0:
        range_pct = round(((high - low) / last_close) * 100, 4)

    total_base_volume = sum(base_volumes)
    total_quote_volume = sum(quote_volumes)

    vwap = 0.0
    if total_base_volume > 0:
        vwap = total_quote_volume / total_base_volume

    return {
        "kline_count": len(klines),
        "last_close": round(last_close, 8),
        "momentum_5m_pct": momentum_pct(5),
        "momentum_15m_pct": momentum_pct(15),
        "momentum_full_window_pct": full_window_pct,
        "range_full_window_pct": range_pct,
        "vwap_full_window": round(vwap, 8),
        "quote_volume_full_window": round(total_quote_volume, 4),
        "trades_full_window": sum(trades),
    }


def get_crypto_market_snapshot(
    symbols: list[str] | None = None,
    interval: str = "1m",
    kline_limit: int = 60,
    timeout: float = 10.0,
) -> list[dict[str, Any]]:
    rows: list[dict[str, Any]] = []

    for symbol in symbols or DEFAULT_SYMBOLS:
        symbol = normalize_symbol(symbol)

        try:
            price = get_symbol_price(symbol, timeout=timeout)
            ticker = get_24hr_ticker(symbol, timeout=timeout)
            klines, kline_base_url = get_klines(
                symbol,
                interval=interval,
                limit=kline_limit,
                timeout=timeout,
            )
            features = calculate_kline_features(klines)

            row = {
                "observed_at": utc_now_iso(),
                "symbol": symbol,
                "interval": interval,
                "kline_limit": int(kline_limit),
                "price": price.get("price", 0.0),
                "price_change_pct_24h": ticker.get("price_change_pct_24h", 0.0),
                "high_price_24h": ticker.get("high_price_24h", 0.0),
                "low_price_24h": ticker.get("low_price_24h", 0.0),
                "volume_24h": ticker.get("volume_24h", 0.0),
                "quote_volume_24h": ticker.get("quote_volume_24h", 0.0),
                "price_source_base_url": price.get("price_source_base_url", ""),
                "ticker_source_base_url": ticker.get("ticker_source_base_url", ""),
                "kline_source_base_url": kline_base_url,
                **features,
                "status": "OK",
                "error": "",
            }

        except Exception as exc:
            row = {
                "observed_at": utc_now_iso(),
                "symbol": symbol,
                "interval": interval,
                "kline_limit": int(kline_limit),
                "price": 0.0,
                "price_change_pct_24h": 0.0,
                "high_price_24h": 0.0,
                "low_price_24h": 0.0,
                "volume_24h": 0.0,
                "quote_volume_24h": 0.0,
                "price_source_base_url": "",
                "ticker_source_base_url": "",
                "kline_source_base_url": "",
                "kline_count": 0,
                "last_close": 0.0,
                "momentum_5m_pct": 0.0,
                "momentum_15m_pct": 0.0,
                "momentum_full_window_pct": 0.0,
                "range_full_window_pct": 0.0,
                "vwap_full_window": 0.0,
                "quote_volume_full_window": 0.0,
                "trades_full_window": 0,
                "status": "ERROR",
                "error": str(exc),
            }

        rows.append(row)

    return rows


def save_crypto_market_snapshot(
    rows: list[dict[str, Any]],
    output_path: str | Path = "data/binance_crypto_snapshot.csv",
    append: bool = False,
) -> Path:
    path = Path(output_path)
    path.parent.mkdir(parents=True, exist_ok=True)

    df = pd.DataFrame(rows)

    if append and path.exists():
        existing = pd.read_csv(path)
        df = pd.concat([existing, df], ignore_index=True)

    df.to_csv(path, index=False)

    return path
