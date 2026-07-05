from pathlib import Path
import time

import pandas as pd
from rich.console import Console
from rich.table import Table

from app.config import settings
from app.data.polymarket_gamma import get_active_events, extract_market_rows
from app.data.polymarket_clob import get_orderbook, summarize_orderbook
from app.signals.orderbook_signal import classify_orderbook


console = Console()
DATA_DIR = Path("data")


def main():
    DATA_DIR.mkdir(exist_ok=True)

    console.print(f"[bold cyan]Proyecto:[/bold cyan] {settings.app_name}")
    console.print(f"[bold yellow]Live trading:[/bold yellow] {settings.live_trading}")
    console.print("[bold green]Modo actual:[/bold green] READ-ONLY, sin wallet, sin compras")

    console.print("\n[bold]Leyendo eventos activos de Polymarket...[/bold]")

    events = get_active_events(limit=20)
    markets = extract_market_rows(events)

    if not markets:
        console.print("[red]No se encontraron mercados abiertos con orderbook.[/red]")
        return

    markets_df = pd.DataFrame(markets)
    markets_path = DATA_DIR / "active_markets.csv"
    markets_df.to_csv(markets_path, index=False)

    console.print(f"[green]Mercados abiertos encontrados:[/green] {len(markets_df)}")
    console.print(f"[green]CSV de mercados guardado en:[/green] {markets_path}")

    console.print("\n[bold]Leyendo orderbooks de los primeros mercados...[/bold]")

    snapshot_rows = []

    for _, market in markets_df.head(10).iterrows():
        token_ids = market["clob_token_ids"]
        outcomes = market["outcomes"]

        if not token_ids:
            continue

        for idx, token_id in enumerate(token_ids[:2]):
            outcome_name = outcomes[idx] if idx < len(outcomes) else f"Outcome {idx + 1}"

            try:
                orderbook = get_orderbook(str(token_id))
                summary = summarize_orderbook(orderbook)
                signal = classify_orderbook(summary)

                snapshot_rows.append(
                    {
                        "question": market["question"],
                        "outcome": outcome_name,
                        "token_id": token_id,
                        "best_bid": summary["best_bid"],
                        "best_ask": summary["best_ask"],
                        "spread": summary["spread"],
                        "mid_price": summary["mid_price"],
                        "bid_size": summary["bid_size"],
                        "ask_size": summary["ask_size"],
                        "last_trade_price": summary["last_trade_price"],
                        "signal": signal,
                    }
                )

                time.sleep(0.25)

            except Exception as error:
                snapshot_rows.append(
                    {
                        "question": market["question"],
                        "outcome": outcome_name,
                        "token_id": token_id,
                        "best_bid": None,
                        "best_ask": None,
                        "spread": None,
                        "mid_price": None,
                        "bid_size": None,
                        "ask_size": None,
                        "last_trade_price": None,
                        "signal": f"ERROR: {error}",
                    }
                )

    if not snapshot_rows:
        console.print("[red]No se pudieron leer orderbooks.[/red]")
        return

    snapshot_df = pd.DataFrame(snapshot_rows)
    snapshot_path = DATA_DIR / "orderbook_snapshot.csv"
    snapshot_df.to_csv(snapshot_path, index=False)

    table = Table(title="Snapshot de orderbooks")

    table.add_column("#", justify="right")
    table.add_column("Pregunta", overflow="fold")
    table.add_column("Outcome")
    table.add_column("Bid", justify="right")
    table.add_column("Ask", justify="right")
    table.add_column("Spread", justify="right")
    table.add_column("Mid", justify="right")
    table.add_column("Señal")

    for idx, row in snapshot_df.head(20).iterrows():
        table.add_row(
            str(idx + 1),
            str(row["question"])[:70],
            str(row["outcome"]),
            str(row["best_bid"]),
            str(row["best_ask"]),
            str(row["spread"]),
            str(row["mid_price"]),
            str(row["signal"]),
        )

    console.print(table)
    console.print(f"\n[green]CSV de orderbook guardado en:[/green] {snapshot_path}")


if __name__ == "__main__":
    main()
