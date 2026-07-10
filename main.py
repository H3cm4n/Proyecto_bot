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
from app.brain.decision_audit import audit_trade_rows
from app.brain.trade_proposals import approve_trade_proposal, create_trade_proposals, list_trade_proposals, reject_trade_proposal
from app.risk.paper_limits import load_paper_risk_state
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

    return parser


def main() -> None:
    parser = build_parser()
    args = parser.parse_args()

    if not hasattr(args, "func"):
        args = parser.parse_args(["snapshot"])

    args.func(args)


if __name__ == "__main__":
    main()
