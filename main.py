import argparse
import time
from pathlib import Path

from rich.console import Console
from rich.table import Table

from app.config import settings
from app.scanner import collect_orderbook_snapshot, save_snapshot


console = Console()
DATA_DIR = Path("data")


def filter_and_sort_rows(
    rows: list[dict],
    alerts_only: bool = False,
    min_score: int = 0,
) -> list[dict]:
    filtered_rows = []

    for row in rows:
        score = int(row.get("score") or 0)
        action = str(row.get("action") or "")

        if score < min_score:
            continue

        if alerts_only and action == "IGNORE":
            continue

        filtered_rows.append(row)

    return sorted(
        filtered_rows,
        key=lambda row: int(row.get("score") or 0),
        reverse=True,
    )


def print_snapshot_table(
    rows: list[dict],
    alerts_only: bool = False,
    min_score: int = 0,
) -> None:
    display_rows = filter_and_sort_rows(
        rows=rows,
        alerts_only=alerts_only,
        min_score=min_score,
    )

    table = Table(title="Ranking de orderbooks")

    table.add_column("#", justify="right", width=3)
    table.add_column("Score", justify="right", width=5)
    table.add_column("Grade", justify="center", width=5)
    table.add_column("Action", width=14)
    table.add_column("Outcome", width=7)
    table.add_column("Bid", justify="right", width=7)
    table.add_column("Ask", justify="right", width=7)
    table.add_column("Spread", justify="right", width=7)
    table.add_column("TopLiq", justify="right", width=8)
    table.add_column("Pregunta", overflow="fold")

    for idx, row in enumerate(display_rows[:25], start=1):
        table.add_row(
            str(idx),
            str(row.get("score", "")),
            str(row.get("grade", "")),
            str(row.get("action", "")),
            str(row.get("outcome", "")),
            str(row.get("best_bid", "")),
            str(row.get("best_ask", "")),
            str(row.get("spread", "")),
            str(row.get("top_liquidity", "")),
            str(row.get("question", ""))[:80],
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

    print_snapshot_table(
        rows,
        alerts_only=args.alerts,
        min_score=args.min_score,
    )

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

                print_snapshot_table(
                    rows,
                    alerts_only=args.alerts,
                    min_score=args.min_score,
                )

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
    snapshot.add_argument("--alerts", action="store_true", help="Oculta acciones IGNORE.")
    snapshot.add_argument("--min-score", type=int, default=0, help="Score mínimo a mostrar.")
    snapshot.set_defaults(func=run_snapshot)

    scan = subparsers.add_parser("scan", help="Ejecuta scanner continuo.")
    scan.add_argument("--event-limit", type=int, default=20)
    scan.add_argument("--market-limit", type=int, default=10)
    scan.add_argument("--request-delay", type=float, default=0.25)
    scan.add_argument("--interval", type=int, default=30)
    scan.add_argument("--cycles", type=int, default=5)
    scan.add_argument("--alerts", action="store_true", help="Oculta acciones IGNORE.")
    scan.add_argument("--min-score", type=int, default=0, help="Score mínimo a mostrar.")
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
