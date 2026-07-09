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
from app.brain.edge_model import attach_edge_scores
from app.execution.paper_report import build_performance_report, save_performance_report

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
    table.add_column("Edge", justify="right", width=5)
    table.add_column("ΔMid", justify="right", width=7)
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
            str(row.get("edge_score", "")),
            str(row.get("edge_mid_delta", "")),
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
        min_edge_score=getattr(args, "paper_min_edge", 0),
        min_edge_mid_delta=getattr(args, "paper_min_edge_delta", 0.005),
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
    rows = attach_edge_scores(rows)

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
            rows = attach_edge_scores(rows)

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


def print_performance_report(report: dict) -> None:
    if not report.get("has_data"):
        console.print(f"[yellow]{report.get('message', 'No hay datos PAPER.')}[/yellow]")
        return

    if report.get("closed_trades", 0) == 0:
        console.print(f"[yellow]{report.get('message', 'No hay trades cerrados.')}[/yellow]")
        console.print(f"[bold]Trades abiertos:[/bold] {report.get('open_trades', 0)}")
        return

    table = Table(title="Reporte de performance PAPER")

    table.add_column("Métrica")
    table.add_column("Valor", justify="right")

    table.add_row("Trades cerrados", str(report.get("closed_trades", 0)))
    table.add_row("Trades abiertos", str(report.get("open_trades", 0)))
    table.add_row("Capital invertido", f"${report.get('total_invested', 0)}")
    table.add_row("PnL total", f"${report.get('total_pnl', 0)}")
    table.add_row("ROI total", f"{report.get('total_roi_pct', 0)}%")
    table.add_row("Winrate", f"{report.get('winrate_pct', 0)}%")
    table.add_row("Loss rate", f"{report.get('loss_rate_pct', 0)}%")
    table.add_row("ROI promedio", f"{report.get('avg_roi_pct', 0)}%")
    table.add_row("Wins", str(report.get("wins", 0)))
    table.add_row("Losses", str(report.get("losses", 0)))
    table.add_row("Breakeven", str(report.get("breakeven", 0)))

    console.print(table)

    exit_counts = report.get("exit_reason_counts", {})
    if exit_counts:
        reason_table = Table(title="Motivos de salida")
        reason_table.add_column("Motivo")
        reason_table.add_column("Cantidad", justify="right")

        for reason, count in exit_counts.items():
            reason_table.add_row(str(reason), str(count))

        console.print(reason_table)

    best_trade = report.get("best_trade", {})
    worst_trade = report.get("worst_trade", {})

    console.print("[bold green]Mejor trade:[/bold green]")
    console.print(
        f"{best_trade.get('outcome', '')} | "
        f"PnL: ${best_trade.get('realized_pnl_usdc', '')} | "
        f"ROI: {best_trade.get('realized_roi_pct', '')}% | "
        f"{str(best_trade.get('question', ''))[:100]}"
    )

    console.print("[bold red]Peor trade:[/bold red]")
    console.print(
        f"{worst_trade.get('outcome', '')} | "
        f"PnL: ${worst_trade.get('realized_pnl_usdc', '')} | "
        f"ROI: {worst_trade.get('realized_roi_pct', '')}% | "
        f"{str(worst_trade.get('question', ''))[:100]}"
    )


def run_paper_report(args: argparse.Namespace) -> None:
    console.print(f"[bold cyan]Proyecto:[/bold cyan] {settings.app_name}")
    console.print("[bold green]Modo actual:[/bold green] PAPER PERFORMANCE REPORT")

    report = build_performance_report()
    output_path = save_performance_report(report)

    print_performance_report(report)

    if report.get("has_data"):
        console.print(f"[green]Reporte guardado en:[/green] {output_path}")


def run_cycle(args: argparse.Namespace) -> None:
    console.print(f"[bold cyan]Proyecto:[/bold cyan] {settings.app_name}")
    console.print(f"[bold yellow]Live trading:[/bold yellow] {settings.live_trading}")
    console.print("[bold green]Modo actual:[/bold green] PAPER CYCLE, sin wallet, sin compras reales")
    console.print("[bold]Presiona Ctrl+C para detener.[/bold]\n")

    history_path = DATA_DIR / "orderbook_history.csv"

    try:
        for cycle_number in range(1, args.cycles + 1):
            console.print(f"\n[bold blue]Ciclo automático {cycle_number}/{args.cycles}[/bold blue]")

            rows = collect_orderbook_snapshot(
                event_limit=args.event_limit,
                market_limit=args.market_limit,
                request_delay=args.request_delay,
            )
            rows = attach_edge_scores(rows)

            if not rows:
                console.print("[yellow]No se obtuvieron orderbooks en este ciclo.[/yellow]")
            else:
                save_snapshot(rows, history_path, append=True)

                print_snapshot_table(
                    rows,
                    alerts_only=args.alerts,
                    min_score=args.min_score,
                )

                maybe_run_paper_trading(args, rows)

                console.print(f"[green]Historial actualizado:[/green] {history_path}")
                console.print(f"[green]Filas agregadas:[/green] {len(rows)}")

            if args.portfolio:
                portfolio_rows = mark_open_trades_to_market()
                save_portfolio_snapshot(portfolio_rows)
                print_portfolio_table(portfolio_rows)
                console.print("[green]Snapshot de portfolio actualizado.[/green]")

            if args.manage:
                management_rows = evaluate_open_positions(
                    stop_loss_pct=args.stop_loss,
                    take_profit_pct=args.take_profit,
                    close_positions=args.close,
                )

                print_paper_management_table(management_rows)

                if args.close:
                    console.print("[green]Archivo actualizado:[/green] data/paper_trades.csv")
                else:
                    console.print("[yellow]Modo revisión: no se cerró ninguna posición. Usa --close para aplicar cierres.[/yellow]")

            if args.report:
                report = build_performance_report()
                output_path = save_performance_report(report)
                print_performance_report(report)

                if report.get("has_data"):
                    console.print(f"[green]Reporte guardado en:[/green] {output_path}")

            if cycle_number < args.cycles:
                console.print(f"[blue]Esperando {args.interval} segundos...[/blue]")
                time.sleep(args.interval)

    except KeyboardInterrupt:
        console.print("\n[yellow]Ciclo detenido por el usuario.[/yellow]")

def add_common_args(parser: argparse.ArgumentParser) -> None:
    parser.add_argument("--event-limit", type=int, default=20)
    parser.add_argument("--market-limit", type=int, default=10)
    parser.add_argument("--request-delay", type=float, default=0.25)
    parser.add_argument("--alerts", action="store_true", help="Oculta acciones IGNORE.")
    parser.add_argument("--min-score", type=int, default=0, help="Score mínimo a mostrar.")
    parser.add_argument("--paper", action="store_true", help="Activa compras simuladas.")
    parser.add_argument("--paper-size", type=float, default=5.0, help="Tamaño ficticio por trade en USDC.")
    parser.add_argument("--paper-min-score", type=int, default=75, help="Score mínimo para compra simulada.")
    parser.add_argument("--paper-min-edge", type=int, default=0, help="Edge mínimo para compra simulada.")
    parser.add_argument("--paper-min-edge-delta", type=float, default=0.005, help="Delta mínimo de mid price para compra simulada.")


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

    paper_report = subparsers.add_parser("paper-report", help="Muestra performance de trades PAPER.")
    paper_report.set_defaults(func=run_paper_report)

    cycle = subparsers.add_parser("cycle", help="Ejecuta scan + paper + portfolio + manager + report.")
    add_common_args(cycle)
    cycle.add_argument("--cycles", type=int, default=1)
    cycle.add_argument("--interval", type=int, default=30)
    cycle.add_argument("--portfolio", action="store_true", help="Valúa posiciones PAPER abiertas.")
    cycle.add_argument("--manage", action="store_true", help="Evalúa stop-loss/take-profit en posiciones PAPER.")
    cycle.add_argument("--close", action="store_true", help="Aplica cierres PAPER cuando se activen reglas.")
    cycle.add_argument("--stop-loss", type=float, default=-20.0)
    cycle.add_argument("--take-profit", type=float, default=25.0)
    cycle.add_argument("--report", action="store_true", help="Genera reporte de performance PAPER.")
    cycle.set_defaults(func=run_cycle)

    return parser


def main() -> None:
    parser = build_parser()
    args = parser.parse_args()

    if not hasattr(args, "func"):
        args = parser.parse_args(["snapshot"])

    args.func(args)


if __name__ == "__main__":
    main()
