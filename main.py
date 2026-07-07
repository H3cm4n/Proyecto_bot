import argparse
import time
from pathlib import Path

from rich.console import Console
from rich.table import Table

from app.config import settings
from app.scanner import collect_orderbook_snapshot, save_snapshot
from app.execution.paper_broker import generate_paper_buys
from app.execution.paper_portfolio import mark_open_trades_to_market, save_portfolio_snapshot
from app.execution.paper_manager import evaluate_open_positions

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


def print_paper_trades_table(trades: list[dict]) -> None:
    if not trades:
        console.print("[yellow]Paper-trading: no se generaron compras simuladas.[/yellow]")
        return

    table = Table(title="Compras simuladas PAPER")

    table.add_column("#", justify="right")
    table.add_column("Outcome")
    table.add_column("Entry", justify="right")
    table.add_column("Shares", justify="right")
    table.add_column("USDC", justify="right")
    table.add_column("Score", justify="right")
    table.add_column("Pregunta", overflow="fold")

    for idx, trade in enumerate(trades, start=1):
        table.add_row(
            str(idx),
            str(trade.get("outcome", "")),
            str(trade.get("entry_price", "")),
            str(trade.get("shares", "")),
            str(trade.get("notional_usdc", "")),
            str(trade.get("score", "")),
            str(trade.get("question", ""))[:80],
        )

    console.print(table)


def print_portfolio_table(rows: list[dict]) -> None:
    if not rows:
        console.print("[yellow]No hay posiciones PAPER abiertas.[/yellow]")
        return

    table = Table(title="Portfolio PAPER - Mark to Market")

    table.add_column("#", justify="right")
    table.add_column("Outcome")
    table.add_column("Entry", justify="right")
    table.add_column("Bid", justify="right")
    table.add_column("Ask", justify="right")
    table.add_column("Shares", justify="right")
    table.add_column("Value@Bid", justify="right")
    table.add_column("PnL@Bid", justify="right")
    table.add_column("ROI%", justify="right")
    table.add_column("Pregunta", overflow="fold")

    total_notional = 0.0
    total_value_bid = 0.0
    total_pnl_bid = 0.0

    for idx, row in enumerate(rows, start=1):
        if "error" in row:
            table.add_row(
                str(idx),
                str(row.get("outcome", "")),
                "ERR",
                "ERR",
                "ERR",
                "ERR",
                "ERR",
                "ERR",
                "ERR",
                str(row.get("question", ""))[:80],
            )
            continue

        total_notional += float(row.get("notional_usdc") or 0)
        total_value_bid += float(row.get("exit_value_bid") or 0)
        total_pnl_bid += float(row.get("pnl_bid") or 0)

        table.add_row(
            str(idx),
            str(row.get("outcome", "")),
            str(row.get("entry_price", "")),
            str(row.get("current_bid", "")),
            str(row.get("current_ask", "")),
            str(row.get("shares", "")),
            str(row.get("exit_value_bid", "")),
            str(row.get("pnl_bid", "")),
            str(row.get("roi_bid_pct", "")),
            str(row.get("question", ""))[:80],
        )

    console.print(table)

    total_roi = round((total_pnl_bid / total_notional) * 100, 2) if total_notional else 0

    console.print(f"[bold]Capital simulado invertido:[/bold] ${round(total_notional, 4)}")
    console.print(f"[bold]Valor conservador @ bid:[/bold] ${round(total_value_bid, 4)}")
    console.print(f"[bold]PnL no realizado @ bid:[/bold] ${round(total_pnl_bid, 4)}")
    console.print(f"[bold]ROI no realizado @ bid:[/bold] {total_roi}%")


def maybe_run_paper_trading(args: argparse.Namespace, rows: list[dict]) -> None:
    if not args.paper:
        return

    trades = generate_paper_buys(
        rows=rows,
        usdc_amount=args.paper_size,
        min_score=args.paper_min_score,
        avoid_duplicates=True,
    )

    print_paper_trades_table(trades)

    if trades:
        console.print("[green]Paper trades guardados en:[/green] data/paper_trades.csv")


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

    maybe_run_paper_trading(args, rows)

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

                maybe_run_paper_trading(args, rows)

                console.print(f"[green]Historial actualizado:[/green] {history_path}")
                console.print(f"[green]Filas agregadas:[/green] {len(rows)}")
            else:
                console.print("[yellow]No se obtuvieron filas en este ciclo.[/yellow]")

            if cycle < args.cycles:
                console.print(f"[dim]Esperando {args.interval} segundos...[/dim]")
                time.sleep(args.interval)

    except KeyboardInterrupt:
        console.print("\n[yellow]Scanner detenido por el usuario.[/yellow]")


def run_portfolio(args: argparse.Namespace) -> None:
    console.print(f"[bold cyan]Proyecto:[/bold cyan] {settings.app_name}")
    console.print("[bold green]Modo actual:[/bold green] PAPER PORTFOLIO, sin wallet, sin compras")

    rows = mark_open_trades_to_market()
    output_path = save_portfolio_snapshot(rows)

    print_portfolio_table(rows)

    if rows:
        console.print(f"[green]Snapshot de portfolio guardado en:[/green] {output_path}")

def print_paper_management_table(rows: list[dict]) -> None:
    if not rows:
        console.print("[yellow]No hay posiciones PAPER abiertas para evaluar.[/yellow]")
        return

    table = Table(title="Gestión de posiciones PAPER")

    table.add_column("#", justify="right")
    table.add_column("Outcome")
    table.add_column("Entry", justify="right")
    table.add_column("Bid", justify="right")
    table.add_column("Ask", justify="right")
    table.add_column("PnL", justify="right")
    table.add_column("ROI%", justify="right")
    table.add_column("Decisión")
    table.add_column("Pregunta", overflow="fold")

    for idx, row in enumerate(rows, start=1):
        table.add_row(
            str(idx),
            str(row.get("outcome", "")),
            str(row.get("entry_price", "")),
            str(row.get("current_bid", "")),
            str(row.get("current_ask", "")),
            str(row.get("pnl_bid", "")),
            str(row.get("roi_bid_pct", "")),
            str(row.get("exit_reason", "")),
            str(row.get("question", ""))[:80],
        )

    console.print(table)


def run_paper_manage(args: argparse.Namespace) -> None:
    console.print(f"[bold cyan]Proyecto:[/bold cyan] {settings.app_name}")
    console.print("[bold green]Modo actual:[/bold green] PAPER POSITION MANAGER, sin wallet, sin compras reales")

    rows = evaluate_open_positions(
        stop_loss_pct=args.stop_loss,
        take_profit_pct=args.take_profit,
        close_positions=args.close,
    )

    print_paper_management_table(rows)

    if args.close:
        console.print("[green]Archivo actualizado:[/green] data/paper_trades.csv")
    else:
        console.print("[yellow]Modo revisión: no se cerró ninguna posición. Usa --close para aplicar cierres.[/yellow]")

def add_common_args(parser: argparse.ArgumentParser) -> None:
    parser.add_argument("--event-limit", type=int, default=20)
    parser.add_argument("--market-limit", type=int, default=10)
    parser.add_argument("--request-delay", type=float, default=0.25)
    parser.add_argument("--alerts", action="store_true", help="Oculta acciones IGNORE.")
    parser.add_argument("--min-score", type=int, default=0, help="Score mínimo a mostrar.")
    parser.add_argument("--paper", action="store_true", help="Activa compras simuladas.")
    parser.add_argument("--paper-size", type=float, default=5.0, help="Tamaño ficticio por trade en USDC.")
    parser.add_argument("--paper-min-score", type=int, default=75, help="Score mínimo para compra simulada.")


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description="Bot read-only para escanear mercados de Polymarket."
    )

    subparsers = parser.add_subparsers(dest="command")

    snapshot = subparsers.add_parser("snapshot", help="Toma un snapshot único.")
    add_common_args(snapshot)
    snapshot.set_defaults(func=run_snapshot)

    scan = subparsers.add_parser("scan", help="Ejecuta scanner continuo.")
    add_common_args(scan)
    scan.add_argument("--interval", type=int, default=30)
    scan.add_argument("--cycles", type=int, default=5)
    scan.set_defaults(func=run_scan)

    portfolio = subparsers.add_parser("portfolio", help="Valúa posiciones PAPER abiertas.")
    portfolio.set_defaults(func=run_portfolio)
    paper_manage = subparsers.add_parser("paper-manage", help="Evalúa/cierra posiciones PAPER.")
    paper_manage.add_argument("--stop-loss", type=float, default=-20.0)
    paper_manage.add_argument("--take-profit", type=float, default=25.0)
    paper_manage.add_argument("--close", action="store_true", help="Aplica cierres en paper_trades.csv.")
    paper_manage.set_defaults(func=run_paper_manage)

    return parser


def main() -> None:
    parser = build_parser()
    args = parser.parse_args()

    if not hasattr(args, "func"):
        args = parser.parse_args(["snapshot"])

    args.func(args)


if __name__ == "__main__":
    main()
