from collections import Counter, defaultdict
from pathlib import Path
from typing import Any, Dict, List, Tuple
import pandas as pd

from app.backtesting.replay_audit import (
    load_replay_history,
    explain_replay_decision,
    safe_float,
    safe_str,
    safe_int,
    calc_relative_spread_pct,
    get_top_liquidity,
)


DEFAULT_HISTORY_PATH = Path("data/orderbook_history.csv")
DEFAULT_TRADES_OUTPUT_PATH = Path("data/portfolio_backtest_trades.csv")
DEFAULT_EQUITY_OUTPUT_PATH = Path("data/portfolio_equity_curve.csv")


def prepare_history(history: pd.DataFrame) -> pd.DataFrame:
    """Prepare and sort the history data by timestamp."""
    if history.empty:
        return history

    df = history.copy()
    df["observed_dt"] = pd.to_datetime(df.get("observed_at", ""), utc=True, errors="coerce")
    df = df.dropna(subset=["observed_dt"]).sort_values("observed_dt")
    
    # Convert numeric columns
    numeric_columns = ["best_bid", "best_ask", "spread"]
    for col in numeric_columns:
        df[f"{col}_num"] = df.get(col, "").apply(safe_float)
    
    return df


def compute_trade_values(
    entry_price: float, 
    exit_price: float, 
    shares: float
) -> Dict[str, float]:
    """Calculate trade performance metrics."""
    notional = shares * entry_price
    exit_value = shares * exit_price
    pnl = exit_value - notional
    roi = (pnl / notional) * 100 if notional > 0 else 0.0

    return {
        "notional_usdc": round(notional, 4),
        "exit_value_usdc": round(exit_value, 4),
        "pnl_usdc": round(pnl, 4),
        "roi_pct": round(roi, 2),
    }


def check_exit_conditions(
    position: Dict[str, Any],
    current_bid: float,
    stop_loss_pct: float,
    take_profit_pct: float,
) -> Tuple[bool, str]:
    """Check if a position should be exited based on stop loss or take profit."""
    if current_bid <= 0:
        return False, ""
    
    entry_price = safe_float(position.get("entry_price"))
    if entry_price <= 0:
        return False, ""
    
    # Calculate current ROI
    shares = safe_float(position.get("shares"))
    notional = shares * entry_price
    current_value = shares * current_bid
    current_pnl = current_value - notional
    current_roi = (current_pnl / notional) * 100 if notional > 0 else 0.0
    
    if current_roi <= stop_loss_pct:
        return True, "STOP_LOSS"
    
    if current_roi >= take_profit_pct:
        return True, "TAKE_PROFIT"
    
    return False, ""


def create_position(
    signal: Dict[str, Any],
    paper_size: float,
    entry_ask: float,
) -> Dict[str, Any]:
    """Create a new position from a signal."""
    if entry_ask <= 0:
        return {}
    
    shares = paper_size / entry_ask
    
    return {
        "entry_time": safe_str(signal.get("observed_at")),
        "question": safe_str(signal.get("question")),
        "outcome": safe_str(signal.get("outcome")),
        "token_id": safe_str(signal.get("token_id")),
        "entry_price": entry_ask,
        "shares": round(shares, 4),
        "notional_usdc": round(shares * entry_ask, 4),
    }


def close_position(
    position: Dict[str, Any],
    exit_time: str,
    exit_price: float,
    exit_reason: str,
) -> Dict[str, Any]:
    """Close a position and calculate performance metrics."""
    exit_data = compute_trade_values(
        entry_price=safe_float(position.get("entry_price")),
        exit_price=exit_price,
        shares=safe_float(position.get("shares")),
    )
    
    return {
        "entry_time": safe_str(position.get("entry_time")),
        "exit_time": exit_time,
        "exit_reason": exit_reason,
        "question": safe_str(position.get("question")),
        "outcome": safe_str(position.get("outcome")),
        "token_id": safe_str(position.get("token_id")),
        "entry_price": safe_float(position.get("entry_price")),
        "exit_price": exit_price,
        "shares": safe_float(position.get("shares")),
        "notional_usdc": exit_data["notional_usdc"],
        "exit_value_usdc": exit_data["exit_value_usdc"],
        "pnl_usdc": exit_data["pnl_usdc"],
        "roi_pct": exit_data["roi_pct"],
    }


def mark_open_positions_value(
    open_positions: List[Dict[str, Any]],
    cycle_data: pd.DataFrame,
) -> float:
    """Mark open positions to market using current bid prices from the cycle."""
    total_value = 0.0

    for position in open_positions:
        token_id = safe_str(position.get("token_id"))
        shares = safe_float(position.get("shares"))
        token_rows = cycle_data[cycle_data["token_id"] == token_id]

        if token_rows.empty:
            continue

        current_bid = safe_float(token_rows.iloc[0].get("best_bid_num"))
        total_value += shares * current_bid

    return round(total_value, 4)



def build_equity_curve(
    trades: List[Dict[str, Any]],
    initial_capital: float = 100.0,
) -> List[Dict[str, Any]]:
    """Build an equity curve from closed trades."""
    # Sort trades by exit time
    sorted_trades = sorted(
        trades, 
        key=lambda t: safe_str(t.get("exit_time", ""))
    )
    
    equity_points = []
    current_capital = initial_capital
    
    for trade in sorted_trades:
        exit_time = safe_str(trade.get("exit_time"))
        pnl = safe_float(trade.get("pnl_usdc"))
        
        current_capital += pnl
        equity_points.append({
            "timestamp": exit_time,
            "pnl": pnl,
            "capital": round(current_capital, 4),
        })
    
    return equity_points


def summarize_portfolio_backtest(
    trades: List[Dict[str, Any]],
    initial_capital: float,
    equity_curve: List[Dict[str, Any]],
) -> Dict[str, Any]:
    """Summarize portfolio backtest results."""
    total_trades = len(trades)
    
    if total_trades == 0:
        return {
            "initial_capital": initial_capital,
            "final_capital": initial_capital,
            "total_pnl": 0.0,
            "total_roi_pct": 0.0,
            "total_trades": 0,
            "wins": 0,
            "losses": 0,
            "breakeven": 0,
            "winrate_pct": 0.0,
            "max_drawdown": 0.0,
            "max_exposure_used": 0.0,
            "max_positions_open": 0,
            "exit_reason_counts": {},
            "top_trades": [],
        }
    
    invested = sum(safe_float(row.get("notional_usdc")) for row in trades)
    pnl_values = [safe_float(row.get("pnl_usdc")) for row in trades]
    roi_values = [safe_float(row.get("roi_pct")) for row in trades]
    
    total_pnl = sum(pnl_values)
    final_capital = initial_capital + total_pnl
    total_roi = (total_pnl / initial_capital) * 100 if initial_capital > 0 else 0.0
    
    wins = sum(1 for pnl in pnl_values if pnl > 0)
    losses = sum(1 for pnl in pnl_values if pnl < 0)
    breakeven = total_trades - wins - losses
    winrate = (wins / total_trades) * 100 if total_trades > 0 else 0.0
    
    # Calculate max drawdown from equity curve
    max_drawdown = 0.0
    if equity_curve:
        peak = initial_capital
        for point in equity_curve:
            capital = safe_float(point.get("capital"))
            if capital > peak:
                peak = capital
            drawdown = (peak - capital) / peak * 100 if peak > 0 else 0.0
            if drawdown > max_drawdown:
                max_drawdown = drawdown
    
    exit_reasons = Counter(safe_str(row.get("exit_reason")) for row in trades)
    
    # Get top 20 trades by ROI
    sorted_trades = sorted(
        trades, 
        key=lambda t: safe_float(t.get("roi_pct")), 
        reverse=True
    )
    top_trades = sorted_trades[:20]
    
    return {
        "initial_capital": initial_capital,
        "final_capital": round(final_capital, 4),
        "total_pnl": round(total_pnl, 4),
        "total_roi_pct": round(total_roi, 2),
        "total_trades": total_trades,
        "wins": wins,
        "losses": losses,
        "breakeven": breakeven,
        "winrate_pct": round(winrate, 2),
        "max_drawdown": round(max_drawdown, 2),
        "exit_reason_counts": dict(exit_reasons),
        "top_trades": top_trades,
    }


def save_portfolio_backtest_results(
    trades: List[Dict[str, Any]],
    equity_curve: List[Dict[str, Any]],
    trades_output_path: Path = DEFAULT_TRADES_OUTPUT_PATH,
    equity_output_path: Path = DEFAULT_EQUITY_OUTPUT_PATH,
) -> None:
    """Save portfolio backtest results to CSV files."""
    # Save trades
    trades_output_path.parent.mkdir(parents=True, exist_ok=True)
    if trades:
        pd.DataFrame(trades).to_csv(trades_output_path, index=False)
    
    # Save equity curve
    equity_output_path.parent.mkdir(parents=True, exist_ok=True)
    if equity_curve:
        pd.DataFrame(equity_curve).to_csv(equity_output_path, index=False)


def run_portfolio_backtest(
    history_path: Path = DEFAULT_HISTORY_PATH,
    trades_output_path: Path = DEFAULT_TRADES_OUTPUT_PATH,
    equity_output_path: Path = DEFAULT_EQUITY_OUTPUT_PATH,
    profile: str = "custom",
    paper_min_score: int = 70,
    paper_min_edge: int = 65,
    paper_min_edge_delta: float = 0.005,
    initial_capital: float = 100.0,
    paper_size: float = 5.0,
    max_open_positions: int = 3,
    max_total_exposure: float = 15.0,
    stop_loss: float = -20.0,
    take_profit: float = 25.0,
    min_entry_price: float = 0.05,
    max_entry_price: float = 0.90,
    min_top_liquidity: float = 10.0,
    max_relative_spread_pct: float = 10.0,
    max_new_trades_per_cycle: int = 1,
    save_output: bool = True,
) -> Dict[str, Any]:
    """
    Run a portfolio backtest simulation.
    
    Reads orderbook history and simulates portfolio trading with position management.
    """
    # Load and prepare history data
    history = prepare_history(load_replay_history(history_path))
    
    if history.empty:
        return {
            "history_path": str(history_path),
            "trades_output_path": str(trades_output_path),
            "equity_output_path": str(equity_output_path),
            "trades": [],
            "equity_curve": [],
            "summary": {
                "initial_capital": initial_capital,
                "final_capital": initial_capital,
                "total_pnl": 0.0,
                "total_roi_pct": 0.0,
                "total_trades": 0,
                "wins": 0,
                "losses": 0,
                "breakeven": 0,
                "winrate_pct": 0.0,
                "max_drawdown": 0.0,
                "exit_reason_counts": {},
                "top_trades": [],
            }
        }
    
    # Get unique timestamps ordered chronologically
    timestamps = sorted(history["observed_dt"].unique())
    
    # Initialize state
    current_capital = initial_capital
    open_positions: List[Dict[str, Any]] = []
    closed_trades: List[Dict[str, Any]] = []
    equity_curve: List[Dict[str, Any]] = []
    max_exposure_used = 0.0
    max_positions_count = 0
    
    # Process each timestamp
    for timestamp in timestamps:
        # Filter data for current timestamp
        cycle_data = history[history["observed_dt"] == timestamp]
        
        if cycle_data.empty:
            continue
            
        # Mark to market and check for exits
        positions_to_close = []
        for i, position in enumerate(open_positions):
            token_id = safe_str(position.get("token_id"))
            token_data = cycle_data[cycle_data["token_id"] == token_id]
            
            if not token_data.empty:
                current_bid = safe_float(token_data.iloc[0]["best_bid_num"])
                
                # Check exit conditions
                should_exit, exit_reason = check_exit_conditions(
                    position=position,
                    current_bid=current_bid,
                    stop_loss_pct=stop_loss,
                    take_profit_pct=take_profit,
                )
                
                if should_exit:
                    closed_trade = close_position(
                        position=position,
                        exit_time=str(timestamp),
                        exit_price=current_bid,
                        exit_reason=exit_reason,
                    )
                    closed_trades.append(closed_trade)
                    positions_to_close.append(i)
                    
                    # Update cash: we subtracted notional at entry, so add full exit value at close.
                    current_capital += safe_float(closed_trade.get("exit_value_usdc", 0))
        
        # Remove closed positions (in reverse order to maintain indices)
        for i in reversed(positions_to_close):
            open_positions.pop(i)
        
        # Update exposure tracking
        current_exposure = sum(
            safe_float(pos.get("notional_usdc", 0)) for pos in open_positions
        )
        if current_exposure > max_exposure_used:
            max_exposure_used = current_exposure
            
        if len(open_positions) > max_positions_count:
            max_positions_count = len(open_positions)
        
        # Evaluate new signals if we have capacity
        if (len(open_positions) < max_open_positions and 
            current_exposure < max_total_exposure):
            
            # Get all rows for this timestamp
            rows = cycle_data.to_dict(orient="records")
            
            # Filter rows using replay audit logic
            eligible_signals = []
            for row in rows:
                audit_result = explain_replay_decision(
                    row=row,
                    min_score=paper_min_score,
                    min_edge_score=paper_min_edge,
                    min_edge_mid_delta=paper_min_edge_delta,
                    min_entry_price=min_entry_price,
                    max_entry_price=max_entry_price,
                    min_top_liquidity=min_top_liquidity,
                    max_relative_spread_pct=max_relative_spread_pct,
                )
                
                if audit_result.get("decision") == "PASS":
                    eligible_signals.append(row)
            
            # Sort by score (descending)
            eligible_signals.sort(
                key=lambda x: (
                    safe_int(x.get("score", 0)),
                    safe_int(x.get("edge_score", 0)),
                ),
                reverse=True
            )
            
            # Open new positions within limits
            new_trades_count = 0
            for signal in eligible_signals:
                # Check if we've hit the new trades limit for this cycle
                if new_trades_count >= max_new_trades_per_cycle:
                    break
                
                # Check position limits
                if len(open_positions) >= max_open_positions:
                    break
                
                # Check exposure limit
                ask_price = safe_float(signal.get("best_ask"))
                if ask_price <= 0:
                    continue
                    
                potential_exposure = paper_size
                if current_exposure + potential_exposure > max_total_exposure:
                    continue
                
                # Check if we already have a position in this question
                question = safe_str(signal.get("question"))
                already_positioned = any(
                    safe_str(pos.get("question")) == question 
                    for pos in open_positions
                )
                if already_positioned:
                    continue
                
                # Check if we have enough capital
                if current_capital < paper_size:
                    continue
                
                # Create new position
                new_position = create_position(signal, paper_size, ask_price)
                if new_position:
                    open_positions.append(new_position)
                    current_capital -= paper_size
                    current_exposure += paper_size
                    new_trades_count += 1

                    if current_exposure > max_exposure_used:
                        max_exposure_used = current_exposure

                    if len(open_positions) > max_positions_count:
                        max_positions_count = len(open_positions)

        # Record real portfolio equity for this timestamp.
        # equity = available cash + current bid value of open positions.
        open_value = mark_open_positions_value(open_positions, cycle_data)
        equity = current_capital + open_value
        equity_curve.append({
            "timestamp": str(timestamp),
            "cash": round(current_capital, 4),
            "open_value": round(open_value, 4),
            "equity": round(equity, 4),
            "capital": round(equity, 4),
            "open_positions": len(open_positions),
            "open_exposure": round(current_exposure, 4),
        })
    
    # Close any remaining open positions at the last available bid price
    if open_positions:
        last_timestamp = timestamps[-1] if timestamps else None
        if last_timestamp:
            for position in open_positions:
                token_id = safe_str(position.get("token_id"))
                token_data = history[history["token_id"] == token_id]
                
                if not token_data.empty:
                    # Get the last bid price for this token
                    last_token_data = token_data.sort_values("observed_dt").iloc[-1]
                    last_bid = safe_float(last_token_data["best_bid_num"])
                    
                    closed_trade = close_position(
                        position=position,
                        exit_time=str(last_timestamp),
                        exit_price=last_bid,
                        exit_reason="END_OF_HISTORY",
                    )
                    closed_trades.append(closed_trade)
                    current_capital += safe_float(closed_trade.get("exit_value_usdc", 0))

            open_positions = []

            equity_curve.append({
                "timestamp": str(last_timestamp),
                "cash": round(current_capital, 4),
                "open_value": 0.0,
                "equity": round(current_capital, 4),
                "capital": round(current_capital, 4),
                "open_positions": 0,
                "open_exposure": 0.0,
            })
    
    # Equity curve is built during the timestamp loop using cash + open position value.
    
    # Save results if requested
    if save_output:
        save_portfolio_backtest_results(
            trades=closed_trades,
            equity_curve=equity_curve,
            trades_output_path=trades_output_path,
            equity_output_path=equity_output_path,
        )
    
    # Generate summary
    summary = summarize_portfolio_backtest(
        trades=closed_trades,
        initial_capital=initial_capital,
        equity_curve=equity_curve,
    )
    
    # Add additional metrics to summary
    summary["max_exposure_used"] = round(max_exposure_used, 4)
    summary["max_positions_open"] = max_positions_count
    
    return {
        "history_path": str(history_path),
        "trades_output_path": str(trades_output_path),
        "equity_output_path": str(equity_output_path),
        "trades": closed_trades,
        "equity_curve": equity_curve,
        "summary": summary,
    }