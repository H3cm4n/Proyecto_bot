import argparse
import time
import sys
from pathlib import Path

from rich.console import Console
from rich.table import Table

from app.config import settings
from app.scanner import collect_orderbook_snapshot, save_snapshot
from app.execution.paper_broker import generate_paper_buys
from app.execution.paper_portfolio import mark_open_trades_to_market, save_portfolio_snapshot
from app.execution.paper_manager import evaluate_open_positions
from app.brain.edge_model import attach_edge_scores
from app.brain.decision_audit import audit_trade_rows
from app.brain.trade_proposals import approve_trade_proposal, create_trade_proposals, list_trade_proposals, reject_trade_proposal
from app.risk.paper_limits import load_paper_risk_state
from app.execution.paper_report import build_performance_report, save_performance_report
from app.monitoring.supervisor_journal import load_supervisor_journal, save_supervisor_journal_entry
from app.monitoring.health_check import run_health_check
from app.backtesting.replay_audit import run_replay_audit
from app.backtesting.paper_backtest import run_signal_backtest
from app.backtesting.universe_report import calculate_universe_report

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
        exclude_keywords=getattr(args, "exclude_keyword", []),
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
    if report.get("message"):
        console.print(f"[yellow]{report.get('message')}[/yellow]")
        return

    table = Table(title="Reporte de performance PAPER")

    table.add_column("Métrica")
    table.add_column("Valor", justify="right")

    table.add_row("Trades cerrados", str(report.get("closed_trade_count", 0)))
    table.add_row("Trades abiertos", str(report.get("open_trade_count", 0)))
    table.add_row("Capital cerrado", f"${report.get('closed_invested_usdc', 0)}")
    table.add_row("PnL realizado", f"${report.get('closed_pnl_usdc', 0)}")
    table.add_row("ROI realizado", f"{report.get('closed_roi_pct', 0)}%")
    table.add_row("Exposición abierta", f"${report.get('open_exposure_usdc', 0)}")
    table.add_row("Valor abierto @ bid", f"${report.get('open_value_bid_usdc', 0)}")
    table.add_row("PnL no realizado @ bid", f"${report.get('open_unrealized_pnl_bid_usdc', 0)}")
    table.add_row("ROI no realizado @ bid", f"{report.get('open_unrealized_roi_bid_pct', 0)}%")
    table.add_row("Capital total desplegado", f"${report.get('total_deployed_usdc', 0)}")
    table.add_row("PnL total PAPER", f"${report.get('total_paper_pnl_usdc', 0)}")
    table.add_row("ROI total PAPER", f"{report.get('total_paper_roi_pct', 0)}%")
    table.add_row("Winrate cerrado", f"{report.get('winrate_pct', 0)}%")
    table.add_row("Loss rate cerrado", f"{report.get('loss_rate_pct', 0)}%")
    table.add_row("ROI promedio cerrado", f"{report.get('avg_closed_roi_pct', 0)}%")
    table.add_row("Wins cerrados", str(report.get("wins", 0)))
    table.add_row("Losses cerrados", str(report.get("losses", 0)))
    table.add_row("Breakeven cerrados", str(report.get("breakeven", 0)))

    console.print(table)

    exit_reason_counts = report.get("exit_reason_counts", {})

    if exit_reason_counts:
        reasons_table = Table(title="Motivos de salida")

        reasons_table.add_column("Motivo")
        reasons_table.add_column("Cantidad", justify="right")

        for reason, count in exit_reason_counts.items():
            reasons_table.add_row(str(reason), str(count))

        console.print(reasons_table)

    open_positions = report.get("open_positions", [])

    if open_positions:
        open_table = Table(title="Posiciones abiertas PAPER")

        open_table.add_column("#", justify="right")
        open_table.add_column("Outcome")
        open_table.add_column("Entry", justify="right")
        open_table.add_column("Bid", justify="right")
        open_table.add_column("PnL", justify="right")
        open_table.add_column("ROI%", justify="right")
        open_table.add_column("Pregunta", overflow="fold")

        for idx, row in enumerate(open_positions, start=1):
            open_table.add_row(
                str(idx),
                str(row.get("outcome", "")),
                str(row.get("entry_price", "")),
                str(row.get("current_bid", "")),
                str(row.get("pnl_bid", "")),
                str(row.get("roi_bid_pct", "")),
                str(row.get("question", ""))[:80],
            )

        console.print(open_table)

    best_trade = report.get("best_trade")
    worst_trade = report.get("worst_trade")

    if best_trade:
        console.print("[green]Mejor trade cerrado:[/green]")
        console.print(
            f"{best_trade.get('outcome')} | "
            f"PnL: ${best_trade.get('realized_pnl_usdc')} | "
            f"ROI: {best_trade.get('realized_roi_pct')}% | "
            f"{best_trade.get('question')}"
        )

    if worst_trade:
        console.print("[red]Peor trade cerrado:[/red]")
        console.print(
            f"{worst_trade.get('outcome')} | "
            f"PnL: ${worst_trade.get('realized_pnl_usdc')} | "
            f"ROI: {worst_trade.get('realized_roi_pct')}% | "
            f"{worst_trade.get('question')}"
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


def print_decision_audit_table(rows: list[dict]) -> None:
    if not rows:
        console.print("[yellow]No hay candidatos para auditar.[/yellow]")
        return

    table = Table(title="Auditor de decisiones PAPER")

    table.add_column("#", justify="right")
    table.add_column("Decision")
    table.add_column("Score", justify="right")
    table.add_column("Edge", justify="right")
    table.add_column("ΔMid", justify="right")
    table.add_column("Outcome")
    table.add_column("Ask", justify="right")
    table.add_column("RelSpread%", justify="right")
    table.add_column("Razones", overflow="fold")
    table.add_column("Pregunta", overflow="fold")

    for idx, row in enumerate(rows, start=1):
        table.add_row(
            str(idx),
            str(row.get("decision", "")),
            str(row.get("score", "")),
            str(row.get("edge_score", "")),
            str(row.get("edge_mid_delta", "")),
            str(row.get("outcome", "")),
            str(row.get("ask", "")),
            str(row.get("relative_spread_pct", "")),
            str(row.get("reasons", "")),
            str(row.get("question", ""))[:80],
        )

    console.print(table)


def run_audit(args: argparse.Namespace) -> None:
    console.print(f"[bold cyan]Proyecto:[/bold cyan] {settings.app_name}")
    console.print("[bold green]Modo actual:[/bold green] PAPER DECISION AUDIT, sin wallet, sin compras")

    rows = collect_orderbook_snapshot(
        event_limit=args.event_limit,
        market_limit=args.market_limit,
        request_delay=args.request_delay,
        exclude_keywords=getattr(args, "exclude_keyword", []),
    )

    if not rows:
        console.print("[red]No se obtuvieron orderbooks.[/red]")
        return

    rows = attach_edge_scores(rows)

    print_snapshot_table(
        rows,
        alerts_only=args.alerts,
        min_score=args.min_score,
    )

    audited_rows = audit_trade_rows(
        rows=rows,
        usdc_amount=args.paper_size,
        min_score=args.paper_min_score,
        min_edge_score=getattr(args, "paper_min_edge", 0),
        min_edge_mid_delta=getattr(args, "paper_min_edge_delta", 0.005),
    )

    print_decision_audit_table(audited_rows)


def print_trade_proposals_table(rows: list[dict], title: str = "Propuestas de trade PAPER") -> None:
    if not rows:
        console.print("[yellow]No hay propuestas para mostrar.[/yellow]")
        return

    table = Table(title=title)

    table.add_column("#", justify="right")
    table.add_column("Status")
    table.add_column("ID", overflow="fold")
    table.add_column("Score", justify="right")
    table.add_column("Edge", justify="right")
    table.add_column("ΔMid", justify="right")
    table.add_column("Outcome")
    table.add_column("Entry", justify="right")
    table.add_column("USDC", justify="right")
    table.add_column("Pregunta", overflow="fold")

    for idx, row in enumerate(rows, start=1):
        table.add_row(
            str(idx),
            str(row.get("status", "")),
            str(row.get("proposal_id", "")),
            str(row.get("score", "")),
            str(row.get("edge_score", "")),
            str(row.get("edge_mid_delta", "")),
            str(row.get("outcome", "")),
            str(row.get("proposed_entry_price", "")),
            str(row.get("usdc_amount", "")),
            str(row.get("question", ""))[:80],
        )

    console.print(table)


def run_propose(args: argparse.Namespace) -> None:
    console.print(f"[bold cyan]Proyecto:[/bold cyan] {settings.app_name}")
    console.print("[bold green]Modo actual:[/bold green] PAPER PROPOSAL MODE, sin wallet, sin compras automáticas")

    rows = collect_orderbook_snapshot(
        event_limit=args.event_limit,
        market_limit=args.market_limit,
        request_delay=args.request_delay,
        exclude_keywords=getattr(args, "exclude_keyword", []),
    )

    if not rows:
        console.print("[red]No se obtuvieron orderbooks.[/red]")
        return

    rows = attach_edge_scores(rows)

    print_snapshot_table(
        rows,
        alerts_only=args.alerts,
        min_score=args.min_score,
    )

    proposals = create_trade_proposals(
        rows=rows,
        usdc_amount=args.paper_size,
        min_score=args.paper_min_score,
        min_edge_score=getattr(args, "paper_min_edge", 0),
        min_edge_mid_delta=getattr(args, "paper_min_edge_delta", 0.005),
        limit=getattr(args, "proposal_limit", 3),
        ttl_minutes=getattr(args, "proposal_ttl_minutes", 10),
    )

    print_trade_proposals_table(proposals, title="Nuevas propuestas PENDING_APPROVAL")

    if proposals:
        console.print("[green]Propuestas guardadas en:[/green] data/trade_proposals.csv")
        console.print("[cyan]Aprueba con:[/cyan] python main.py approve '<proposal_id>'")
    else:
        console.print("[yellow]No hubo propuestas elegibles. El bot decidió esperar.[/yellow]")
        console.print("[cyan]Mostrando auditoría de candidatos rechazados:[/cyan]")

        audited_rows = audit_trade_rows(
            rows=rows,
            usdc_amount=args.paper_size,
            min_score=args.paper_min_score,
            min_edge_score=getattr(args, "paper_min_edge", 0),
            min_edge_mid_delta=getattr(args, "paper_min_edge_delta", 0.005),
        )

        print_decision_audit_table(audited_rows)


def run_proposals(args: argparse.Namespace) -> None:
    console.print(f"[bold cyan]Proyecto:[/bold cyan] {settings.app_name}")
    console.print("[bold green]Modo actual:[/bold green] PAPER PROPOSALS LIST")

    status = getattr(args, "status", "") or None
    proposals = list_trade_proposals(status=status)
    print_trade_proposals_table(proposals)


def run_approve(args: argparse.Namespace) -> None:
    console.print(f"[bold cyan]Proyecto:[/bold cyan] {settings.app_name}")
    console.print("[bold green]Modo actual:[/bold green] PAPER APPROVAL, sin wallet, sin compras reales")

    result = approve_trade_proposal(
        proposal_id=args.proposal_id,
        max_price_slippage=args.max_price_slippage,
    )

    if result.get("ok"):
        console.print(f"[green]{result.get('message')}[/green]")
        console.print(f"Mercado: {result.get('question')}")
        console.print(f"Outcome: {result.get('outcome')}")
        console.print(f"Execution price: {result.get('execution_price')}")
        console.print(f"Paper trade id: {result.get('paper_trade_id')}")
    else:
        console.print(f"[red]{result.get('message')}[/red]")


def run_reject(args: argparse.Namespace) -> None:
    console.print(f"[bold cyan]Proyecto:[/bold cyan] {settings.app_name}")
    console.print("[bold green]Modo actual:[/bold green] PAPER REJECT PROPOSAL")

    result = reject_trade_proposal(
        proposal_id=args.proposal_id,
        reason=args.reason,
    )

    if result.get("ok"):
        console.print(f"[green]{result.get('message')}[/green]")
        console.print(f"Razón: {result.get('reason')}")
    else:
        console.print(f"[red]{result.get('message')}[/red]")


def run_risk_status(args: argparse.Namespace) -> None:
    console.print(f"[bold cyan]Proyecto:[/bold cyan] {settings.app_name}")
    console.print("[bold green]Modo actual:[/bold green] PAPER RISK STATUS")

    state = load_paper_risk_state()

    max_open_positions = getattr(args, "max_open_positions", 3)
    max_total_exposure_usdc = getattr(args, "max_total_exposure_usdc", 15.0)
    default_trade_size = getattr(args, "paper_size", 5.0)

    available_positions = max(0, max_open_positions - state.open_positions)
    available_exposure = max(0.0, round(max_total_exposure_usdc - state.open_exposure_usdc, 4))

    can_open_default_trade = (
        available_positions > 0
        and available_exposure >= default_trade_size
    )

    table = Table(title="Estado de riesgo PAPER")

    table.add_column("Métrica")
    table.add_column("Valor", justify="right")

    table.add_row("Posiciones abiertas", f"{state.open_positions} / {max_open_positions}")
    table.add_row("Exposición abierta", f"${state.open_exposure_usdc} / ${max_total_exposure_usdc}")
    table.add_row("Slots disponibles", str(available_positions))
    table.add_row("Exposición disponible", f"${available_exposure}")
    table.add_row("Tamaño default trade", f"${default_trade_size}")
    table.add_row("Puede abrir trade default", "YES" if can_open_default_trade else "NO")

    console.print(table)

    if can_open_default_trade:
        console.print("[green]Riesgo OK:[/green] el bot todavía puede abrir una posición PAPER con el tamaño default.")
    else:
        console.print("[yellow]Riesgo limitado:[/yellow] el bot no debería abrir nuevas posiciones PAPER con el tamaño default.")


def run_proposal_cycle(args: argparse.Namespace) -> None:
    console.print(f"[bold cyan]Proyecto:[/bold cyan] {settings.app_name}")
    console.print("[bold green]Modo actual:[/bold green] PAPER PROPOSAL CYCLE, sin wallet, sin compras automáticas")
    console.print("[yellow]El bot generará propuestas, pero NO ejecutará trades sin aprobación humana.[/yellow]")
    console.print("Presiona Ctrl+C para detener.\n")

    history_path = Path("data") / "orderbook_history.csv"

    try:
        for cycle_number in range(1, args.cycles + 1):
            console.print(f"\n[bold magenta]Ciclo de propuestas {cycle_number}/{args.cycles}[/bold magenta]")

            state = load_paper_risk_state()
            console.print(
                f"[cyan]Riesgo PAPER:[/cyan] "
                f"{state.open_positions}/3 posiciones abiertas | "
                f"${state.open_exposure_usdc}/$15.0 expuesto"
            )

            rows = collect_orderbook_snapshot(
                event_limit=args.event_limit,
                market_limit=args.market_limit,
                request_delay=args.request_delay,
            )

            if not rows:
                console.print("[red]No se obtuvieron orderbooks.[/red]")
                continue

            rows = attach_edge_scores(rows)

            print_snapshot_table(
                rows,
                alerts_only=args.alerts,
                min_score=args.min_score,
            )

            proposals = create_trade_proposals(
                rows=rows,
                usdc_amount=args.paper_size,
                min_score=args.paper_min_score,
                min_edge_score=getattr(args, "paper_min_edge", 0),
                min_edge_mid_delta=getattr(args, "paper_min_edge_delta", 0.005),
                limit=getattr(args, "proposal_limit", 3),
                ttl_minutes=getattr(args, "proposal_ttl_minutes", 10),
            )

            print_trade_proposals_table(
                proposals,
                title="Nuevas propuestas PENDING_APPROVAL",
            )

            if proposals:
                console.print("[green]Propuestas guardadas en:[/green] data/trade_proposals.csv")
                console.print("[cyan]Lista pendientes con:[/cyan] python main.py proposals --status PENDING_APPROVAL")
                console.print("[cyan]Aprueba con:[/cyan] python main.py approve '<proposal_id>'")
            else:
                console.print("[yellow]No hubo propuestas elegibles en este ciclo.[/yellow]")

                if getattr(args, "audit_on_empty", False):
                    audited_rows = audit_trade_rows(
                        rows=rows,
                        usdc_amount=args.paper_size,
                        min_score=args.paper_min_score,
                        min_edge_score=getattr(args, "paper_min_edge", 0),
                        min_edge_mid_delta=getattr(args, "paper_min_edge_delta", 0.005),
                    )

                    print_decision_audit_table(audited_rows)

            save_snapshot(rows, history_path, append=True)
            console.print("[green]Historial actualizado:[/green] data/orderbook_history.csv")
            console.print(f"Filas agregadas: {len(rows)}")

            if cycle_number < args.cycles:
                console.print(f"[yellow]Esperando {args.interval} segundos...[/yellow]")
                time.sleep(args.interval)

    except KeyboardInterrupt:
        console.print("\n[yellow]Proposal cycle detenido por el usuario.[/yellow]")


def run_watch_positions(args: argparse.Namespace) -> None:
    console.print(f"[bold cyan]Proyecto:[/bold cyan] {settings.app_name}")
    console.print("[bold green]Modo actual:[/bold green] PAPER POSITION WATCH")

    if args.close_paper:
        console.print("[red]Modo cierre PAPER activado:[/red] si una posición toca stop-loss o take-profit, se cerrará en PAPER.")
    else:
        console.print("[yellow]Modo vigilancia:[/yellow] no se cerrará ninguna posición. Solo se mostrarán señales.")

    console.print("Presiona Ctrl+C para detener.\n")

    try:
        for cycle_number in range(1, args.cycles + 1):
            console.print(f"\n[bold magenta]Watch cycle {cycle_number}/{args.cycles}[/bold magenta]")

            if args.portfolio:
                portfolio_rows = mark_open_trades_to_market()

                if portfolio_rows:
                    print_portfolio_table(portfolio_rows)
                    save_portfolio_snapshot(portfolio_rows)
                    console.print("[green]Snapshot de portfolio actualizado.[/green]")
                else:
                    console.print("[yellow]No hay posiciones abiertas para valorar.[/yellow]")

            management_rows = evaluate_open_positions(
                stop_loss_pct=args.stop_loss,
                take_profit_pct=args.take_profit,
                close_positions=args.close_paper,
            )

            if not management_rows:
                console.print("[yellow]No hay posiciones abiertas para vigilar.[/yellow]")
            else:
                print_paper_management_table(management_rows)

                actionable = []

                for row in management_rows:
                    decision = (
                        row.get("decision")
                        or row.get("exit_decision")
                        or row.get("exit_reason")
                        or "HOLD"
                    )

                    decision = str(decision).upper()

                    if decision not in {"", "NONE", "HOLD"}:
                        actionable.append(row)

                if actionable and args.close_paper:
                    console.print("[green]Se aplicaron cierres PAPER según las reglas configuradas.[/green]")
                elif actionable:
                    console.print("[cyan]Hay posiciones que cumplen regla de salida, pero no se cerraron porque --close-paper no está activo.[/cyan]")
                else:
                    console.print("[green]Todas las posiciones siguen en HOLD.[/green]")

            if args.report:
                report = build_performance_report()
                print_performance_report(report)
                save_performance_report(report)
                console.print("[green]Reporte PAPER actualizado.[/green]")

            if cycle_number < args.cycles:
                console.print(f"[yellow]Esperando {args.interval} segundos...[/yellow]")
                time.sleep(args.interval)

    except KeyboardInterrupt:
        console.print("\n[yellow]Vigilancia de posiciones detenida por el usuario.[/yellow]")



SUPERVISOR_PROFILES = {
    "conservative": {
        "min_score": 50,
        "paper_min_score": 85,
        "paper_min_edge": 75,
        "paper_min_edge_delta": 0.0075,
        "proposal_limit": 1,
        "proposal_ttl_minutes": 5,
        "stop_loss": -15.0,
        "take_profit": 20.0,
        "health_check_every": 1,
        "health_min_orderbook_rows": 20,
        "health_stop_on_fail": True,
    },
    "normal": {
        "min_score": 50,
        "paper_min_score": 80,
        "paper_min_edge": 65,
        "paper_min_edge_delta": 0.005,
        "proposal_limit": 3,
        "proposal_ttl_minutes": 10,
        "stop_loss": -20.0,
        "take_profit": 25.0,
        "health_check_every": 1,
        "health_min_orderbook_rows": 20,
        "health_stop_on_fail": True,
    },
    "aggressive": {
        "min_score": 45,
        "paper_min_score": 70,
        "paper_min_edge": 50,
        "paper_min_edge_delta": 0.0,
        "proposal_limit": 5,
        "proposal_ttl_minutes": 15,
        "stop_loss": -25.0,
        "take_profit": 35.0,
        "health_check_every": 1,
        "health_min_orderbook_rows": 20,
        "health_stop_on_fail": True,
    },
}


PROFILE_FLAG_MAP = {
    "min_score": "--min-score",
    "paper_min_score": "--paper-min-score",
    "paper_min_edge": "--paper-min-edge",
    "paper_min_edge_delta": "--paper-min-edge-delta",
    "proposal_limit": "--proposal-limit",
    "proposal_ttl_minutes": "--proposal-ttl-minutes",
    "stop_loss": "--stop-loss",
    "take_profit": "--take-profit",
    "health_check_every": "--health-check-every",
    "health_min_orderbook_rows": "--health-min-orderbook-rows",
    "health_stop_on_fail": "--health-stop-on-fail",
}


def cli_arg_was_provided(flag: str) -> bool:
    args = sys.argv[1:]

    for item in args:
        if item == flag or item.startswith(flag + "="):
            return True

    return False


def apply_supervisor_profile(args: argparse.Namespace) -> dict:
    profile = getattr(args, "profile", "custom")

    if profile == "custom":
        return {}

    if profile not in SUPERVISOR_PROFILES:
        raise ValueError(f"Perfil desconocido: {profile}")

    applied = {}

    for attr, value in SUPERVISOR_PROFILES[profile].items():
        flag = PROFILE_FLAG_MAP.get(attr)

        if flag and cli_arg_was_provided(flag):
            continue

        setattr(args, attr, value)
        applied[attr] = value

    return applied


def print_supervisor_profile(profile: str, applied: dict) -> None:
    if profile == "custom":
        console.print("[cyan]Perfil supervisor:[/cyan] custom")
        return

    console.print(f"[cyan]Perfil supervisor:[/cyan] {profile}")

    if not applied:
        console.print("[yellow]Perfil seleccionado, pero todos sus valores fueron sobrescritos por flags manuales.[/yellow]")
        return

    table = Table(title=f"Supervisor Profile: {profile}")
    table.add_column("Parámetro")
    table.add_column("Valor", justify="right")

    for key, value in applied.items():
        table.add_row(str(key), str(value))

    console.print(table)

def run_paper_supervisor(args: argparse.Namespace) -> None:
    applied_profile = apply_supervisor_profile(args)

    console.print(f"[bold cyan]Proyecto:[/bold cyan] {settings.app_name}")
    console.print("[bold green]Modo actual:[/bold green] PAPER SUPERVISOR")
    print_supervisor_profile(getattr(args, "profile", "custom"), applied_profile)
    console.print("[yellow]Autopilot PAPER: vigila posiciones, actualiza reportes y genera propuestas.[/yellow]")
    console.print("[yellow]No usa wallet. No ejecuta compras reales. No aprueba nuevas entradas sin humano.[/yellow]")

    if args.close_paper:
        console.print("[red]Cierre PAPER activado:[/red] puede cerrar posiciones PAPER por stop-loss/take-profit.")
    else:
        console.print("[cyan]Cierre PAPER desactivado:[/cyan] solo vigila salidas, no cierra posiciones.")

    console.print("Presiona Ctrl+C para detener.\n")

    history_path = Path("data") / "orderbook_history.csv"

    try:
        for cycle_number in range(1, args.cycles + 1):
            console.print(f"\n[bold magenta]Supervisor cycle {cycle_number}/{args.cycles}[/bold magenta]")

            cycle_status = "OK"
            cycle_notes = []
            orderbook_rows_scanned = 0
            proposals_created = 0
            report = None

            state = load_paper_risk_state()
            console.print(
                f"[cyan]Riesgo PAPER:[/cyan] "
                f"{state.open_positions}/3 posiciones abiertas | "
                f"${state.open_exposure_usdc}/$15.0 expuesto"
            )

            if not args.no_portfolio:
                portfolio_rows = mark_open_trades_to_market()

                if portfolio_rows:
                    print_portfolio_table(portfolio_rows)
                    save_portfolio_snapshot(portfolio_rows)
                    console.print("[green]Snapshot de portfolio actualizado.[/green]")
                else:
                    console.print("[yellow]No hay posiciones abiertas para valorar.[/yellow]")

            management_rows = evaluate_open_positions(
                stop_loss_pct=args.stop_loss,
                take_profit_pct=args.take_profit,
                close_positions=args.close_paper,
            )

            if management_rows:
                print_paper_management_table(management_rows)

                actionable = []

                for row in management_rows:
                    decision = (
                        row.get("decision")
                        or row.get("exit_decision")
                        or row.get("exit_reason")
                        or "HOLD"
                    )

                    decision = str(decision).upper()

                    if decision not in {"", "NONE", "HOLD"}:
                        actionable.append(row)

                if actionable and args.close_paper:
                    console.print("[green]Se aplicaron cierres PAPER según las reglas configuradas.[/green]")
                elif actionable:
                    console.print("[cyan]Hay posiciones que cumplen regla de salida, pero no se cerraron porque --close-paper no está activo.[/cyan]")
                else:
                    console.print("[green]Todas las posiciones siguen en HOLD.[/green]")
            else:
                console.print("[yellow]No hay posiciones abiertas para vigilar.[/yellow]")

            if not args.no_report:
                report = build_performance_report()
                print_performance_report(report)
                save_performance_report(report)
                console.print("[green]Reporte PAPER actualizado.[/green]")

            if not args.no_proposals:
                console.print("\n[bold blue]Buscando nuevas oportunidades para propuesta...[/bold blue]")

                rows = collect_orderbook_snapshot(
                    event_limit=args.event_limit,
                    market_limit=args.market_limit,
                    request_delay=args.request_delay,
                )

                if not rows:
                    console.print("[red]No se obtuvieron orderbooks.[/red]")
                    cycle_status = "WARN"
                    cycle_notes.append("No se obtuvieron orderbooks.")
                else:
                    orderbook_rows_scanned = len(rows)
                    rows = attach_edge_scores(rows)

                    print_snapshot_table(
                        rows,
                        alerts_only=args.alerts,
                        min_score=args.min_score,
                    )

                    proposals = create_trade_proposals(
                        rows=rows,
                        usdc_amount=args.paper_size,
                        min_score=args.paper_min_score,
                        min_edge_score=getattr(args, "paper_min_edge", 0),
                        min_edge_mid_delta=getattr(args, "paper_min_edge_delta", 0.005),
                        limit=getattr(args, "proposal_limit", 3),
                        ttl_minutes=getattr(args, "proposal_ttl_minutes", 10),
                    )

                    proposals_created = len(proposals)

                    print_trade_proposals_table(
                        proposals,
                        title="Nuevas propuestas PENDING_APPROVAL",
                    )

                    if proposals:
                        console.print("[green]Propuestas guardadas en:[/green] data/trade_proposals.csv")
                        console.print("[cyan]Lista pendientes con:[/cyan] python main.py proposals --status PENDING_APPROVAL")
                        console.print("[cyan]Aprueba con:[/cyan] python main.py approve '<proposal_id>'")
                    else:
                        console.print("[yellow]No hubo propuestas elegibles en este ciclo.[/yellow]")

                        if getattr(args, "audit_on_empty", False):
                            audited_rows = audit_trade_rows(
                                rows=rows,
                                usdc_amount=args.paper_size,
                                min_score=args.paper_min_score,
                                min_edge_score=getattr(args, "paper_min_edge", 0),
                                min_edge_mid_delta=getattr(args, "paper_min_edge_delta", 0.005),
                            )

                            print_decision_audit_table(audited_rows)

                    save_snapshot(rows, history_path, append=True)
                    console.print("[green]Historial actualizado:[/green] data/orderbook_history.csv")
                    console.print(f"Filas agregadas: {len(rows)}")

            end_state = load_paper_risk_state()
            console.print(
                f"[bold cyan]Estado final ciclo:[/bold cyan] "
                f"{end_state.open_positions}/3 posiciones abiertas | "
                f"${end_state.open_exposure_usdc}/$15.0 expuesto"
            )

            if not args.no_journal:
                if report is None:
                    try:
                        report = build_performance_report()
                    except Exception as exc:
                        report = {}
                        cycle_status = "WARN"
                        cycle_notes.append(f"No se pudo construir reporte para journal: {exc}")

                save_supervisor_journal_entry(
                    {
                        "cycle_number": cycle_number,
                        "open_positions": end_state.open_positions,
                        "open_exposure_usdc": end_state.open_exposure_usdc,
                        "closed_pnl_usdc": report.get("closed_pnl_usdc", ""),
                        "open_unrealized_pnl_bid_usdc": report.get("open_unrealized_pnl_bid_usdc", ""),
                        "total_paper_pnl_usdc": report.get("total_paper_pnl_usdc", ""),
                        "total_paper_roi_pct": report.get("total_paper_roi_pct", ""),
                        "proposals_created": proposals_created,
                        "orderbook_rows_scanned": orderbook_rows_scanned,
                        "status": cycle_status,
                        "notes": " | ".join(cycle_notes),
                    }
                )

                console.print("[green]Supervisor journal actualizado:[/green] data/supervisor_journal.csv")

            if args.health_check_every > 0 and cycle_number % args.health_check_every == 0:
                console.print("\n[bold blue]Ejecutando health-check del supervisor...[/bold blue]")

                health_min_orderbook_rows = args.health_min_orderbook_rows

                if args.no_proposals and health_min_orderbook_rows > 0:
                    health_min_orderbook_rows = 0
                    console.print(
                        "[cyan]Health-check: --no-proposals activo; "
                        "mínimo de orderbooks ajustado a 0.[/cyan]"
                    )

                health_result = run_health_check(
                    max_journal_age_minutes=args.health_max_journal_age_minutes,
                    min_orderbook_rows=health_min_orderbook_rows,
                    max_open_positions=args.health_max_open_positions,
                    max_total_exposure_usdc=args.health_max_total_exposure_usdc,
                    skip_api=args.health_skip_api,
                )

                print_health_check(health_result)

                health_status = str(health_result.get("overall_status", "UNKNOWN")).upper()

                if health_status == "FAIL" and args.health_stop_on_fail:
                    console.print("[red]Supervisor detenido porque health-check terminó en FAIL.[/red]")
                    raise SystemExit(1)

                if health_status == "WARN" and args.health_stop_on_warn:
                    console.print("[yellow]Supervisor detenido porque health-check terminó en WARN.[/yellow]")
                    raise SystemExit(1)

            if cycle_number < args.cycles:
                console.print(f"[yellow]Esperando {args.interval} segundos...[/yellow]")
                time.sleep(args.interval)

    except KeyboardInterrupt:
        console.print("\n[yellow]Paper supervisor detenido por el usuario.[/yellow]")


def print_supervisor_journal(rows: list[dict]) -> None:
    if not rows:
        console.print("[yellow]No hay entradas en data/supervisor_journal.csv[/yellow]")
        return

    table = Table(title="Supervisor Journal")

    table.add_column("#", justify="right")
    table.add_column("Time")
    table.add_column("Cycle", justify="right")
    table.add_column("Open", justify="right")
    table.add_column("Exposure", justify="right")
    table.add_column("Unrealized", justify="right")
    table.add_column("Total PnL", justify="right")
    table.add_column("ROI%", justify="right")
    table.add_column("Props", justify="right")
    table.add_column("Rows", justify="right")
    table.add_column("Status")
    table.add_column("Notes", overflow="fold")

    for idx, row in enumerate(rows, start=1):
        table.add_row(
            str(idx),
            str(row.get("observed_at", "")),
            str(row.get("cycle_number", "")),
            str(row.get("open_positions", "")),
            f"${row.get('open_exposure_usdc', '')}",
            f"${row.get('open_unrealized_pnl_bid_usdc', '')}",
            f"${row.get('total_paper_pnl_usdc', '')}",
            str(row.get("total_paper_roi_pct", "")),
            str(row.get("proposals_created", "")),
            str(row.get("orderbook_rows_scanned", "")),
            str(row.get("status", "")),
            str(row.get("notes", "")),
        )

    console.print(table)


def run_supervisor_journal(args: argparse.Namespace) -> None:
    console.print(f"[bold cyan]Proyecto:[/bold cyan] {settings.app_name}")
    console.print("[bold green]Modo actual:[/bold green] SUPERVISOR JOURNAL")

    rows = load_supervisor_journal(tail=args.tail)
    print_supervisor_journal(rows)


def print_health_check(result: dict) -> None:
    overall_status = result.get("overall_status", "UNKNOWN")

    if overall_status == "OK":
        console.print("[bold green]HEALTH CHECK: OK[/bold green]")
    elif overall_status == "WARN":
        console.print("[bold yellow]HEALTH CHECK: WARN[/bold yellow]")
    else:
        console.print("[bold red]HEALTH CHECK: FAIL[/bold red]")

    table = Table(title="Bot Health Check")

    table.add_column("#", justify="right")
    table.add_column("Check")
    table.add_column("Status")
    table.add_column("Detail", overflow="fold")

    for idx, check in enumerate(result.get("checks", []), start=1):
        status = str(check.get("status", "UNKNOWN"))

        if status == "OK":
            status_text = "[green]OK[/green]"
        elif status == "WARN":
            status_text = "[yellow]WARN[/yellow]"
        elif status == "FAIL":
            status_text = "[red]FAIL[/red]"
        else:
            status_text = status

        table.add_row(
            str(idx),
            str(check.get("name", "")),
            status_text,
            str(check.get("detail", "")),
        )

    console.print(table)


def run_health_check_command(args: argparse.Namespace) -> None:
    console.print(f"[bold cyan]Proyecto:[/bold cyan] {settings.app_name}")
    console.print("[bold green]Modo actual:[/bold green] HEALTH CHECK")

    result = run_health_check(
        max_journal_age_minutes=args.max_journal_age_minutes,
        min_orderbook_rows=args.min_orderbook_rows,
        max_open_positions=args.max_open_positions,
        max_total_exposure_usdc=args.max_total_exposure_usdc,
        skip_api=args.skip_api,
    )

    print_health_check(result)

    overall_status = result.get("overall_status", "UNKNOWN")

    if overall_status == "FAIL":
        raise SystemExit(1)

    if overall_status == "WARN" and args.fail_on_warn:
        raise SystemExit(1)


def print_bot_status_risk() -> None:
    state = load_paper_risk_state()

    table = Table(title="Risk Status PAPER")
    table.add_column("Métrica")
    table.add_column("Valor", justify="right")

    table.add_row("Posiciones abiertas", f"{state.open_positions}/3")
    table.add_row("Exposición abierta", f"${state.open_exposure_usdc}/$15.0")
    table.add_row("Slots disponibles", str(max(0, 3 - state.open_positions)))
    table.add_row("Exposición disponible", f"${max(0.0, 15.0 - state.open_exposure_usdc)}")

    console.print(table)


def run_bot_status(args: argparse.Namespace) -> None:
    console.print(f"[bold cyan]Proyecto:[/bold cyan] {settings.app_name}")
    console.print("[bold green]Modo actual:[/bold green] BOT STATUS")
    console.print("[cyan]Resumen general del bot PAPER.[/cyan]\n")

    health_result = run_health_check(
        max_journal_age_minutes=args.max_journal_age_minutes,
        min_orderbook_rows=args.min_orderbook_rows,
        max_open_positions=args.max_open_positions,
        max_total_exposure_usdc=args.max_total_exposure_usdc,
        skip_api=args.skip_api,
    )

    print_health_check(health_result)

    console.print()
    print_bot_status_risk()

    console.print()
    portfolio_rows = mark_open_trades_to_market()

    if portfolio_rows:
        print_portfolio_table(portfolio_rows)
    else:
        console.print("[yellow]No hay posiciones abiertas PAPER.[/yellow]")

    console.print()
    report = build_performance_report()
    print_performance_report(report)

    console.print()
    pending_proposals = list_trade_proposals(status="PENDING_APPROVAL")
    print_trade_proposals_table(
        pending_proposals,
        title="Propuestas pendientes PENDING_APPROVAL",
    )

    console.print()
    journal_rows = load_supervisor_journal(tail=args.tail)
    print_supervisor_journal(journal_rows)


REPLAY_PROFILE_KEYS = [
    "min_score",
    "paper_min_score",
    "paper_min_edge",
    "paper_min_edge_delta",
    "proposal_limit",
]


def apply_replay_profile(args: argparse.Namespace) -> dict:
    profile = getattr(args, "profile", "normal")

    if profile == "custom":
        return {}

    if profile not in SUPERVISOR_PROFILES:
        raise ValueError(f"Perfil desconocido: {profile}")

    applied = {}

    for attr in REPLAY_PROFILE_KEYS:
        value = SUPERVISOR_PROFILES[profile].get(attr)
        flag = PROFILE_FLAG_MAP.get(attr)

        if value is None:
            continue

        if flag and cli_arg_was_provided(flag):
            continue

        setattr(args, attr, value)
        applied[attr] = value

    return applied


def print_replay_profile(profile: str, applied: dict) -> None:
    console.print(f"[cyan]Replay profile:[/cyan] {profile}")

    if not applied:
        console.print("[yellow]Usando valores custom/manuales.[/yellow]")
        return

    table = Table(title=f"Replay Profile: {profile}")
    table.add_column("Parámetro")
    table.add_column("Valor", justify="right")

    for key, value in applied.items():
        table.add_row(str(key), str(value))

    console.print(table)


def print_replay_summary(result: dict, limit: int = 10) -> None:
    summary = result.get("summary", {})

    table = Table(title="Replay/Audit Summary")
    table.add_column("Métrica")
    table.add_column("Valor", justify="right")

    table.add_row("Historial", str(result.get("history_path", "")))
    table.add_row("Output", str(result.get("output_path", "")))
    table.add_row("Filas analizadas", str(summary.get("rows_analyzed", 0)))
    table.add_row("Ciclos analizados", str(summary.get("cycles_analyzed", 0)))
    table.add_row("Candidatos seleccionados", str(summary.get("selected_count", 0)))
    table.add_row("Filas rechazadas", str(summary.get("rejected_count", 0)))

    console.print(table)

    reason_counts = summary.get("reason_counts", {})

    reason_table = Table(title="Principales razones de rechazo")
    reason_table.add_column("Razón")
    reason_table.add_column("Cantidad", justify="right")

    if reason_counts:
        for reason, count in list(reason_counts.items())[:15]:
            reason_table.add_row(str(reason), str(count))
    else:
        reason_table.add_row("Sin rechazos", "0")

    console.print(reason_table)

    selected_rows = summary.get("selected_rows", [])

    selected_table = Table(title=f"Candidatos seleccionados por replay - Top {limit}")
    selected_table.add_column("#", justify="right")
    selected_table.add_column("Time")
    selected_table.add_column("Score", justify="right")
    selected_table.add_column("Edge", justify="right")
    selected_table.add_column("ΔMid", justify="right")
    selected_table.add_column("Outcome")
    selected_table.add_column("Ask", justify="right")
    selected_table.add_column("RelSpread%", justify="right")
    selected_table.add_column("Pregunta", overflow="fold")

    if selected_rows:
        for idx, row in enumerate(selected_rows[:limit], start=1):
            selected_table.add_row(
                str(idx),
                str(row.get("observed_at", "")),
                str(row.get("score", "")),
                str(row.get("edge_score", "")),
                str(row.get("edge_mid_delta", "")),
                str(row.get("outcome", "")),
                str(row.get("ask", "")),
                str(row.get("relative_spread_pct", "")),
                str(row.get("question", "")),
            )
    else:
        selected_table.add_row("-", "-", "-", "-", "-", "-", "-", "-", "No hubo candidatos seleccionados.")

    console.print(selected_table)

    near_miss_rows = summary.get("near_miss_rows", [])

    near_miss_table = Table(title=f"Near Misses - Candidatos casi elegibles - Top {limit}")
    near_miss_table.add_column("#", justify="right")
    near_miss_table.add_column("Time")
    near_miss_table.add_column("Score", justify="right")
    near_miss_table.add_column("Edge", justify="right")
    near_miss_table.add_column("ΔMid", justify="right")
    near_miss_table.add_column("Outcome")
    near_miss_table.add_column("Ask", justify="right")
    near_miss_table.add_column("RelSpread%", justify="right")
    near_miss_table.add_column("Razones", overflow="fold")
    near_miss_table.add_column("Pregunta", overflow="fold")

    if near_miss_rows:
        for idx, row in enumerate(near_miss_rows[:limit], start=1):
            near_miss_table.add_row(
                str(idx),
                str(row.get("observed_at", "")),
                str(row.get("score", "")),
                str(row.get("edge_score", "")),
                str(row.get("edge_mid_delta", "")),
                str(row.get("outcome", "")),
                str(row.get("ask", "")),
                str(row.get("relative_spread_pct", "")),
                str(row.get("reasons", "")),
                str(row.get("question", "")),
            )
    else:
        near_miss_table.add_row("-", "-", "-", "-", "-", "-", "-", "-", "Sin near misses.", "-")

    console.print(near_miss_table)


def run_replay_command(args: argparse.Namespace) -> None:
    applied_profile = apply_replay_profile(args)

    console.print(f"[bold cyan]Proyecto:[/bold cyan] {settings.app_name}")
    console.print("[bold green]Modo actual:[/bold green] REPLAY/AUDIT")
    console.print("[cyan]Lee data/orderbook_history.csv. No toca API. No abre trades. No modifica posiciones.[/cyan]\n")

    print_replay_profile(args.profile, applied_profile)

    result = run_replay_audit(
        history_path=Path(args.history_path),
        output_path=Path(args.output_path),
        min_score=args.paper_min_score,
        min_edge_score=args.paper_min_edge,
        min_edge_mid_delta=args.paper_min_edge_delta,
        proposal_limit=args.proposal_limit,
        min_entry_price=args.min_entry_price,
        max_entry_price=args.max_entry_price,
        min_top_liquidity=args.min_top_liquidity,
        max_relative_spread_pct=args.max_relative_spread_pct,
        save_output=not args.no_save,
    )

    print_replay_summary(result, limit=args.limit)


BACKTEST_PROFILE_KEYS = [
    "min_score",
    "paper_min_score",
    "paper_min_edge",
    "paper_min_edge_delta",
    "proposal_limit",
    "stop_loss",
    "take_profit",
]


def apply_backtest_profile(args: argparse.Namespace) -> dict:
    profile = getattr(args, "profile", "normal")

    if profile == "custom":
        return {}

    if profile not in SUPERVISOR_PROFILES:
        raise ValueError(f"Perfil desconocido: {profile}")

    applied = {}

    for attr in BACKTEST_PROFILE_KEYS:
        value = SUPERVISOR_PROFILES[profile].get(attr)
        flag = PROFILE_FLAG_MAP.get(attr)

        if value is None:
            continue

        if flag and cli_arg_was_provided(flag):
            continue

        setattr(args, attr, value)
        applied[attr] = value

    return applied


def print_backtest_profile(profile: str, applied: dict) -> None:
    console.print(f"[cyan]Backtest profile:[/cyan] {profile}")

    if not applied:
        console.print("[yellow]Usando valores custom/manuales.[/yellow]")
        return

    table = Table(title=f"Backtest Profile: {profile}")
    table.add_column("Parámetro")
    table.add_column("Valor", justify="right")

    for key, value in applied.items():
        table.add_row(str(key), str(value))

    console.print(table)


def print_backtest_summary(result: dict, limit: int = 10) -> None:
    summary = result.get("summary", {})

    table = Table(title="Signal Backtest Summary")
    table.add_column("Métrica")
    table.add_column("Valor", justify="right")

    table.add_row("Historial", str(result.get("history_path", "")))
    table.add_row("Output", str(result.get("output_path", "")))
    table.add_row("Señales seleccionadas", str(summary.get("selected_signals", 0)))
    table.add_row("Duplicados omitidos", str(summary.get("skipped_duplicate_questions", 0)))
    table.add_row("Trades simulados", str(summary.get("total_trades", 0)))
    table.add_row("Capital simulado", f"${summary.get('invested_usdc', 0)}")
    table.add_row("Valor final", f"${summary.get('exit_value_usdc', 0)}")
    table.add_row("PnL", f"${summary.get('pnl_usdc', 0)}")
    table.add_row("ROI", f"{summary.get('roi_pct', 0)}%")
    table.add_row("Wins", str(summary.get("wins", 0)))
    table.add_row("Losses", str(summary.get("losses", 0)))
    table.add_row("Breakeven", str(summary.get("breakeven", 0)))
    table.add_row("Winrate", f"{summary.get('winrate_pct', 0)}%")

    console.print(table)

    exit_reasons = summary.get("exit_reason_counts", {})

    reason_table = Table(title="Motivos de salida BACKTEST")
    reason_table.add_column("Motivo")
    reason_table.add_column("Cantidad", justify="right")

    if exit_reasons:
        for reason, count in exit_reasons.items():
            reason_table.add_row(str(reason), str(count))
    else:
        reason_table.add_row("Sin trades", "0")

    console.print(reason_table)

    trades = result.get("trades", [])

    trades_table = Table(title=f"Trades simulados - Top {limit}")
    trades_table.add_column("#", justify="right")
    trades_table.add_column("Entry")
    trades_table.add_column("Exit")
    trades_table.add_column("Reason")
    trades_table.add_column("Outcome")
    trades_table.add_column("EntryPx", justify="right")
    trades_table.add_column("ExitPx", justify="right")
    trades_table.add_column("PnL", justify="right")
    trades_table.add_column("ROI%", justify="right")
    trades_table.add_column("Pregunta", overflow="fold")

    if trades:
        for idx, trade in enumerate(trades[:limit], start=1):
            trades_table.add_row(
                str(idx),
                str(trade.get("entry_time", "")),
                str(trade.get("exit_time", "")),
                str(trade.get("exit_reason", "")),
                str(trade.get("outcome", "")),
                str(trade.get("entry_price", "")),
                str(trade.get("exit_price", "")),
                str(trade.get("pnl_usdc", "")),
                str(trade.get("roi_pct", "")),
                str(trade.get("question", "")),
            )
    else:
        trades_table.add_row("-", "-", "-", "-", "-", "-", "-", "-", "-", "No hubo trades simulados.")

    console.print(trades_table)


def run_backtest_command(args: argparse.Namespace) -> None:
    applied_profile = apply_backtest_profile(args)

    console.print(f"[bold cyan]Proyecto:[/bold cyan] {settings.app_name}")
    console.print("[bold green]Modo actual:[/bold green] SIGNAL BACKTEST")
    console.print("[cyan]Lee historial local. No toca API. No abre trades. No modifica posiciones.[/cyan]\n")

    print_backtest_profile(args.profile, applied_profile)

    result = run_signal_backtest(
        history_path=Path(args.history_path),
        output_path=Path(args.output_path),
        usdc_amount=args.paper_size,
        min_score=args.paper_min_score,
        min_edge_score=args.paper_min_edge,
        min_edge_mid_delta=args.paper_min_edge_delta,
        proposal_limit=args.proposal_limit,
        stop_loss_pct=args.stop_loss,
        take_profit_pct=args.take_profit,
        min_entry_price=args.min_entry_price,
        max_entry_price=args.max_entry_price,
        min_top_liquidity=args.min_top_liquidity,
        max_relative_spread_pct=args.max_relative_spread_pct,
        avoid_duplicate_questions=not args.allow_duplicate_questions,
        save_output=not args.no_save,
    )

    print_backtest_summary(result, limit=args.limit)


def print_simple_count_table(title: str, rows: list[dict], name_label: str = "Nombre") -> None:
    table = Table(title=title)
    table.add_column(name_label, overflow="fold")
    table.add_column("Cantidad", justify="right")

    if rows:
        for row in rows:
            table.add_row(str(row.get("name", "")), str(row.get("count", "")))
    else:
        table.add_row("Sin datos", "0")

    console.print(table)


def print_question_metric_table(title: str, rows: list[dict], metric_label: str = "Metric") -> None:
    table = Table(title=title)
    table.add_column("#", justify="right")
    table.add_column("Rows", justify="right")
    table.add_column("AvgScore", justify="right")
    table.add_column("MaxScore", justify="right")
    table.add_column("AvgEdge", justify="right")
    table.add_column("MaxEdge", justify="right")
    table.add_column("AvgΔ", justify="right")
    table.add_column("RelSpread%", justify="right")
    table.add_column("TopLiq", justify="right")
    table.add_column("Category")
    table.add_column("Pregunta", overflow="fold")

    if rows:
        for idx, row in enumerate(rows, start=1):
            table.add_row(
                str(idx),
                str(row.get("rows", "")),
                f"{float(row.get('avg_score', 0)):.2f}",
                f"{float(row.get('max_score', 0)):.0f}",
                f"{float(row.get('avg_edge', 0)):.2f}",
                f"{float(row.get('max_edge', 0)):.0f}",
                f"{float(row.get('avg_delta', 0)):.4f}",
                f"{float(row.get('avg_rel_spread', 0)):.2f}",
                f"{float(row.get('avg_top_liq', 0)):.2f}",
                str(row.get("category", "")),
                str(row.get("question_clean", "")),
            )
    else:
        table.add_row("-", "-", "-", "-", "-", "-", "-", "-", "-", "-", "Sin datos")

    console.print(table)


def print_universe_report(report: dict, limit: int = 15) -> None:
    summary = report.get("summary", {})
    tables = report.get("tables", {})

    table = Table(title="Universe Report Summary")
    table.add_column("Métrica")
    table.add_column("Valor", justify="right")

    table.add_row("Historial", str(report.get("history_path", "")))
    table.add_row("Filas", str(summary.get("rows", 0)))
    table.add_row("Ciclos", str(summary.get("cycles", 0)))
    table.add_row("Preguntas únicas", str(summary.get("unique_questions", 0)))
    table.add_row("Tokens únicos", str(summary.get("unique_tokens", 0)))
    table.add_row("Rows score >= 80", str(summary.get("strong_score_rows", 0)))
    table.add_row("Rows edge >= 65", str(summary.get("strong_edge_rows", 0)))
    table.add_row("Rows ΔMid >= 0.005", str(summary.get("positive_delta_rows", 0)))
    table.add_row("Rows tipo elegible", str(summary.get("eligible_like_rows", 0)))
    table.add_row("Score promedio", str(summary.get("avg_score", 0)))
    table.add_row("Edge promedio", str(summary.get("avg_edge", 0)))
    table.add_row("RelSpread promedio", str(summary.get("avg_relative_spread_pct", 0)))

    console.print(table)

    print_simple_count_table("Categorías detectadas", tables.get("categories", []), "Categoría")
    print_simple_count_table("Distribución de acciones", tables.get("actions", []), "Action")
    print_simple_count_table("Distribución de edge_action", tables.get("edge_actions", []), "Edge Action")
    print_simple_count_table("Buckets de edge", tables.get("edge_buckets", []), "Bucket")
    print_simple_count_table("Buckets de score", tables.get("score_buckets", []), "Bucket")
    print_simple_count_table("Buckets de precio ask", tables.get("price_buckets", []), "Bucket")

    print_question_metric_table(
        f"Mercados más repetidos - Top {limit}",
        tables.get("most_repeated_questions", []),
    )
    print_question_metric_table(
        f"Mercados por avg score - Top {limit}",
        tables.get("top_avg_score_questions", []),
    )
    print_question_metric_table(
        f"Mercados por max edge - Top {limit}",
        tables.get("top_max_edge_questions", []),
    )
    print_question_metric_table(
        f"Mercados por liquidez promedio - Top {limit}",
        tables.get("top_avg_liquidity_questions", []),
    )


def run_universe_report_command(args: argparse.Namespace) -> None:
    console.print(f"[bold cyan]Proyecto:[/bold cyan] {settings.app_name}")
    console.print("[bold green]Modo actual:[/bold green] UNIVERSE REPORT")
    console.print("[cyan]Analiza el historial local para entender qué mercados está viendo el bot.[/cyan]\n")

    report = calculate_universe_report(
        history_path=Path(args.history_path),
        limit=args.limit,
    )

    print_universe_report(report, limit=args.limit)

def add_common_args(parser: argparse.ArgumentParser) -> None:
    parser.add_argument("--event-limit", type=int, default=20)
    parser.add_argument("--market-limit", type=int, default=10)
    parser.add_argument("--request-delay", type=float, default=0.25)
    parser.add_argument(
        "--exclude-keyword",
        action="append",
        default=[],
        help="Excluye mercados cuya pregunta contenga esta palabra/frase. Puede repetirse.",
    )
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

    audit = subparsers.add_parser("audit", help="Explica por qué el bot aceptaría o rechazaría candidatos PAPER.")
    add_common_args(audit)
    audit.set_defaults(func=run_audit)

    propose = subparsers.add_parser("propose", help="Genera propuestas PAPER que requieren aprobación humana.")
    add_common_args(propose)
    propose.add_argument("--proposal-limit", type=int, default=3, help="Máximo de propuestas nuevas.")
    propose.add_argument("--proposal-ttl-minutes", type=int, default=10, help="Minutos antes de expirar una propuesta.")
    propose.set_defaults(func=run_propose)

    proposals = subparsers.add_parser("proposals", help="Lista propuestas PAPER.")
    proposals.add_argument("--status", default="", help="Filtra por status, por ejemplo PENDING_APPROVAL.")
    proposals.set_defaults(func=run_proposals)

    approve = subparsers.add_parser("approve", help="Aprueba una propuesta y la ejecuta como PAPER.")
    approve.add_argument("proposal_id", help="ID de la propuesta a aprobar.")
    approve.add_argument("--max-price-slippage", type=float, default=0.02, help="Movimiento máximo permitido contra el precio propuesto.")
    approve.set_defaults(func=run_approve)

    reject = subparsers.add_parser("reject", help="Rechaza una propuesta PAPER.")
    reject.add_argument("proposal_id", help="ID de la propuesta a rechazar.")
    reject.add_argument("--reason", default="Rejected by human.", help="Razón del rechazo.")
    reject.set_defaults(func=run_reject)

    risk_status = subparsers.add_parser("risk-status", help="Muestra exposición y límites PAPER actuales.")
    risk_status.add_argument("--paper-size", type=float, default=5.0, help="Tamaño default de trade PAPER.")
    risk_status.add_argument("--max-open-positions", type=int, default=3, help="Máximo de posiciones abiertas PAPER.")
    risk_status.add_argument("--max-total-exposure-usdc", type=float, default=15.0, help="Exposición máxima PAPER.")
    risk_status.set_defaults(func=run_risk_status)

    proposal_cycle = subparsers.add_parser("proposal-cycle", help="Genera propuestas PAPER de forma recurrente sin ejecutar trades.")
    add_common_args(proposal_cycle)
    proposal_cycle.add_argument("--cycles", type=int, default=5, help="Número de ciclos de propuestas.")
    proposal_cycle.add_argument("--interval", type=int, default=60, help="Segundos entre ciclos.")
    proposal_cycle.add_argument("--proposal-limit", type=int, default=3, help="Máximo de propuestas nuevas por ciclo.")
    proposal_cycle.add_argument("--proposal-ttl-minutes", type=int, default=10, help="Minutos antes de expirar una propuesta.")
    proposal_cycle.add_argument("--audit-on-empty", action="store_true", help="Muestra auditoría si no hay propuestas.")
    proposal_cycle.set_defaults(func=run_proposal_cycle)

    watch_positions = subparsers.add_parser("watch-positions", help="Vigila posiciones PAPER abiertas de forma recurrente.")
    watch_positions.add_argument("--cycles", type=int, default=10, help="Número de ciclos de vigilancia.")
    watch_positions.add_argument("--interval", type=int, default=60, help="Segundos entre ciclos.")
    watch_positions.add_argument("--stop-loss", type=float, default=-20.0, help="ROI porcentual para stop-loss PAPER.")
    watch_positions.add_argument("--take-profit", type=float, default=25.0, help="ROI porcentual para take-profit PAPER.")
    watch_positions.add_argument("--close-paper", action="store_true", help="Cierra posiciones PAPER si cumplen stop-loss/take-profit.")
    watch_positions.add_argument("--portfolio", action="store_true", help="Muestra valuación mark-to-market antes de gestionar.")
    watch_positions.add_argument("--report", action="store_true", help="Actualiza reporte de performance en cada ciclo.")
    watch_positions.set_defaults(func=run_watch_positions)

    paper_supervisor = subparsers.add_parser("paper-supervisor", help="Autopilot PAPER: vigila posiciones, reporta y genera propuestas.")
    add_common_args(paper_supervisor)
    paper_supervisor.add_argument(
        "--profile",
        choices=["custom", "conservative", "normal", "aggressive"],
        default="custom",
        help="Perfil preconfigurado del supervisor PAPER.",
    )
    paper_supervisor.add_argument("--cycles", type=int, default=5, help="Número de ciclos del supervisor.")
    paper_supervisor.add_argument("--interval", type=int, default=60, help="Segundos entre ciclos.")
    paper_supervisor.add_argument("--stop-loss", type=float, default=-20.0, help="ROI porcentual para stop-loss PAPER.")
    paper_supervisor.add_argument("--take-profit", type=float, default=25.0, help="ROI porcentual para take-profit PAPER.")
    paper_supervisor.add_argument("--close-paper", action="store_true", help="Cierra posiciones PAPER si cumplen stop-loss/take-profit.")
    paper_supervisor.add_argument("--proposal-limit", type=int, default=3, help="Máximo de propuestas nuevas por ciclo.")
    paper_supervisor.add_argument("--proposal-ttl-minutes", type=int, default=10, help="Minutos antes de expirar una propuesta.")
    paper_supervisor.add_argument("--audit-on-empty", action="store_true", help="Muestra auditoría si no hay propuestas.")
    paper_supervisor.add_argument("--no-proposals", action="store_true", help="Desactiva generación de propuestas.")
    paper_supervisor.add_argument("--no-portfolio", action="store_true", help="No muestra portfolio mark-to-market.")
    paper_supervisor.add_argument("--no-report", action="store_true", help="No actualiza reporte PAPER.")
    paper_supervisor.add_argument("--no-journal", action="store_true", help="No guarda data/supervisor_journal.csv.")
    paper_supervisor.add_argument("--health-check-every", type=int, default=1, help="Corre health-check cada N ciclos. Usa 0 para desactivar.")
    paper_supervisor.add_argument("--health-max-journal-age-minutes", type=float, default=30.0, help="Edad máxima permitida del último journal para health-check.")
    paper_supervisor.add_argument("--health-min-orderbook-rows", type=int, default=1, help="Mínimo de filas de orderbook esperadas por health-check.")
    paper_supervisor.add_argument("--health-max-open-positions", type=int, default=3, help="Máximo de posiciones abiertas para health-check.")
    paper_supervisor.add_argument("--health-max-total-exposure-usdc", type=float, default=15.0, help="Máxima exposición PAPER para health-check.")
    paper_supervisor.add_argument("--health-skip-api", action="store_true", help="Omite chequeo de API externa dentro del supervisor.")
    paper_supervisor.add_argument("--health-stop-on-fail", action="store_true", help="Detiene supervisor si health-check termina en FAIL.")
    paper_supervisor.add_argument("--health-stop-on-warn", action="store_true", help="Detiene supervisor si health-check termina en WARN.")
    paper_supervisor.set_defaults(func=run_paper_supervisor)

    supervisor_journal = subparsers.add_parser("supervisor-journal", help="Muestra últimas entradas del supervisor journal.")
    supervisor_journal.add_argument("--tail", type=int, default=10, help="Número de entradas recientes a mostrar.")
    supervisor_journal.set_defaults(func=run_supervisor_journal)

    health_check = subparsers.add_parser("health-check", help="Revisa salud general del bot PAPER.")
    health_check.add_argument("--max-journal-age-minutes", type=float, default=30.0, help="Edad máxima permitida del último journal.")
    health_check.add_argument("--min-orderbook-rows", type=int, default=1, help="Mínimo de filas de orderbook esperadas en el último ciclo.")
    health_check.add_argument("--max-open-positions", type=int, default=3, help="Máximo de posiciones abiertas PAPER.")
    health_check.add_argument("--max-total-exposure-usdc", type=float, default=15.0, help="Máxima exposición PAPER permitida.")
    health_check.add_argument("--skip-api", action="store_true", help="Omite chequeo de API externa.")
    health_check.add_argument("--fail-on-warn", action="store_true", help="Devuelve error también si hay WARN.")
    health_check.set_defaults(func=run_health_check_command)

    bot_status = subparsers.add_parser("bot-status", help="Muestra salud, riesgo, portfolio, reporte, propuestas y journal.")
    bot_status.add_argument("--tail", type=int, default=5, help="Número de entradas recientes del journal.")
    bot_status.add_argument("--skip-api", action="store_true", help="Omite chequeo de API externa.")
    bot_status.add_argument("--max-journal-age-minutes", type=float, default=30.0, help="Edad máxima permitida del último journal.")
    bot_status.add_argument("--min-orderbook-rows", type=int, default=1, help="Mínimo de filas de orderbook esperadas en el último ciclo.")
    bot_status.add_argument("--max-open-positions", type=int, default=3, help="Máximo de posiciones abiertas PAPER.")
    bot_status.add_argument("--max-total-exposure-usdc", type=float, default=15.0, help="Máxima exposición PAPER permitida.")
    bot_status.set_defaults(func=run_bot_status)

    replay = subparsers.add_parser("replay", help="Audita el historial de orderbooks con los filtros del bot.")
    replay.add_argument("--profile", choices=["custom", "conservative", "normal", "aggressive"], default="normal")
    replay.add_argument("--history-path", default="data/orderbook_history.csv")
    replay.add_argument("--output-path", default="data/replay_audit.csv")
    replay.add_argument("--limit", type=int, default=10, help="Número de candidatos seleccionados a mostrar.")
    replay.add_argument("--no-save", action="store_true", help="No guarda CSV de auditoría.")
    replay.add_argument("--min-score", type=int, default=50, help="Score mínimo visual/reference.")
    replay.add_argument("--paper-min-score", type=int, default=80, help="Score mínimo para que replay seleccione candidato.")
    replay.add_argument("--paper-min-edge", type=int, default=65, help="Edge mínimo para que replay seleccione candidato.")
    replay.add_argument("--paper-min-edge-delta", type=float, default=0.005, help="Delta mínimo de mid price.")
    replay.add_argument("--proposal-limit", type=int, default=3, help="Máximo de candidatos seleccionados por ciclo.")
    replay.add_argument("--min-entry-price", type=float, default=0.05)
    replay.add_argument("--max-entry-price", type=float, default=0.90)
    replay.add_argument("--min-top-liquidity", type=float, default=10.0)
    replay.add_argument("--max-relative-spread-pct", type=float, default=10.0)
    replay.set_defaults(func=run_replay_command)

    backtest = subparsers.add_parser("backtest", help="Simula trades desde señales seleccionadas por replay.")
    backtest.add_argument("--profile", choices=["custom", "conservative", "normal", "aggressive"], default="normal")
    backtest.add_argument("--history-path", default="data/orderbook_history.csv")
    backtest.add_argument("--output-path", default="data/backtest_trades.csv")
    backtest.add_argument("--limit", type=int, default=10, help="Número de trades simulados a mostrar.")
    backtest.add_argument("--no-save", action="store_true", help="No guarda CSV de trades simulados.")
    backtest.add_argument("--allow-duplicate-questions", action="store_true", help="Permite múltiples entradas en la misma pregunta.")
    backtest.add_argument("--paper-size", type=float, default=5.0, help="USDC simulado por trade.")
    backtest.add_argument("--min-score", type=int, default=50)
    backtest.add_argument("--paper-min-score", type=int, default=80)
    backtest.add_argument("--paper-min-edge", type=int, default=65)
    backtest.add_argument("--paper-min-edge-delta", type=float, default=0.005)
    backtest.add_argument("--proposal-limit", type=int, default=3)
    backtest.add_argument("--stop-loss", type=float, default=-20.0)
    backtest.add_argument("--take-profit", type=float, default=25.0)
    backtest.add_argument("--min-entry-price", type=float, default=0.05)
    backtest.add_argument("--max-entry-price", type=float, default=0.90)
    backtest.add_argument("--min-top-liquidity", type=float, default=10.0)
    backtest.add_argument("--max-relative-spread-pct", type=float, default=10.0)
    backtest.set_defaults(func=run_backtest_command)

    universe_report = subparsers.add_parser("universe-report", help="Diagnostica el universo de mercados visto por el bot.")
    universe_report.add_argument("--history-path", default="data/orderbook_history.csv")
    universe_report.add_argument("--limit", type=int, default=15)
    universe_report.set_defaults(func=run_universe_report_command)

    return parser


def main() -> None:
    parser = build_parser()
    args = parser.parse_args()

    if not hasattr(args, "func"):
        args = parser.parse_args(["snapshot"])

    args.func(args)


if __name__ == "__main__":
    main()
