import argparse
import time
from pathlib import Path

from rich.console import Console
from rich.table import Table

from app.config import settings
from app.scanner import collect_orderbook_snapshot, save_snapshot


console = Console()
DATA_DIR = Path("data")


def print_snapshot_table(rows: list[dict], alerts_only: bool = False) -> None:
    display_rows = rows

    if alerts_only:
        display_rows = [row for row in rows if row.get("is_alert")]

    table = Table(title="Scanner de orderbooks")

    table.add_column("#", justify="right")
    table.add_column("Pregunta", overflow="fold")
    table.add_column("Outcome")
    table.add_column("Bid", justify="right")
    table.add_column("Ask", justify="right")
    table.add_column("Spread", justify="right")
    table.add_column("Mid", justify="right")
    table.add_column("Top Liq", justify="right")
    table.add_column("Señal")
    table.add_column("Score", justify="right")
    table.add_column("Grade", justify="center")
    table.add_column("Action")

    for idx, row in enumerate(display_rows[:30], start=1):
        table.add_row(
            str(idx),
            str(row.get("question", ""))[:55],
            str(row.get("outcome", "")),
            str(row.get("best_bid", "")),
            str(row.get("best_ask", "")),
            str(row.get("spread", "")),
            str(row.get("mid_price", "")),
            str(row.get("top_liquidity", "")),
            str(row.get("signal", "")),
            str(row.get("score", "")),
            str(row.get("grade", "")),
            str(row.get("action", "")),
        )

    console.print(table)


def run_snapshot(args: argparse.Namespace) -> None:
    console.print(f"[bold cyan]Proyecto:[/bold cyan] {settings.app_name}")
    console.print(f"[bold yellow]Live trading:[/bold yellow] {settings.live_trading}")
    console.print("[bold green]Modo actual:[/bold green] SNAPSHOT READ-ONLY, sin wallet, sin compras")

    rows = collect_orderbook_snapshot(
        event_limit=args.event_limit,
        market_limit=args.market_limit,
        request_delay=args.request_delay,
    )

    if not rows:
        console.print("[red]No se obtuvieron orderbooks.[/red]")
        return

    snapshot_path = DATA_DIR / "orderbook_snapshot.csv"
    save_snapshot(rows, snapshot_path, append=False)

    print_snapshot_table(rows, alerts_only=args.alerts)

    console.print(f"\n[green]Snapshot guardado en:[/green] {snapshot_path}")
    console.print(f"[green]Filas obtenidas:[/green] {len(rows)}")


def run_scan(args: argparse.Namespace) -> None:
    console.print(f"[bold cyan]Proyecto:[/bold cyan] {settings.app_name}")
    console.print(f"[bold yellow]Live trading:[/bold yellow] {settings.live_trading}")
    console.print("[bold green]Modo actual:[/bold green] SCANNER READ-ONLY, sin wallet, sin compras")
    console.print("[bold]Presiona Ctrl+C para detener.[/bold]\n")

    history_path = DATA_DIR / "orderbook_history.csv"

    try:
        for cycle in range(1, args.cycles + 1):
            console.print(f"\n[bold blue]Ciclo {cycle}/{args.cycles}[/bold blue]")

            rows = collect_orderbook_snapshot(
                event_limit=args.event_limit,
                market_limit=args.market_limit,
                request_delay=args.request_delay,
            )

            if rows:
                save_snapshot(rows, history_path, append=True)
                print_snapshot_table(rows, alerts_only=args.alerts)
                console.print(f"[green]Historial actualizado:[/green] {history_path}")
                console.print(f"[green]Filas agregadas:[/green] {len(rows)}")
            else:
                console.print("[yellow]No se obtuvieron filas en este ciclo.[/yellow]")

            if cycle < args.cycles:
                console.print(f"[dim]Esperando {args.interval} segundos...[/dim]")
                time.sleep(args.interval)

    except KeyboardInterrupt:
        console.print("\n[yellow]Scanner detenido por el usuario.[/yellow]")


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description="Bot read-only para escanear mercados de Polymarket."
    )

    subparsers = parser.add_subparsers(dest="command")

    snapshot = subparsers.add_parser("snapshot", help="Toma un snapshot único.")
    snapshot.add_argument("--event-limit", type=int, default=20)
    snapshot.add_argument("--market-limit", type=int, default=10)
    snapshot.add_argument("--request-delay", type=float, default=0.25)
    snapshot.add_argument("--alerts", action="store_true", help="Muestra solo señales WATCH.")
    snapshot.set_defaults(func=run_snapshot)

    scan = subparsers.add_parser("scan", help="Ejecuta scanner continuo.")
    scan.add_argument("--event-limit", type=int, default=20)
    scan.add_argument("--market-limit", type=int, default=10)
    scan.add_argument("--request-delay", type=float, default=0.25)
    scan.add_argument("--interval", type=int, default=30)
    scan.add_argument("--cycles", type=int, default=5)
    scan.add_argument("--alerts", action="store_true", help="Muestra solo señales WATCH.")
    scan.set_defaults(func=run_scan)

    return parser


def main() -> None:
    parser = build_parser()
    args = parser.parse_args()

    if not hasattr(args, "func"):
        args = parser.parse_args(["snapshot"])

    args.func(args)


if __name__ == "__main__":
    main()
