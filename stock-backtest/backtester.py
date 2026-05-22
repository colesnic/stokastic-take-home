"""
Event-driven backtesting engine — longs only, clean accounting.
"""
import numpy as np
import pandas as pd
from dataclasses import dataclass, field
from typing import Optional, List
import warnings
warnings.filterwarnings("ignore")


@dataclass
class Trade:
    ticker: str
    entry_date: pd.Timestamp
    entry_price: float
    shares: float
    exit_date: Optional[pd.Timestamp] = None
    exit_price: Optional[float] = None
    exit_reason: str = ""
    pnl: float = 0.0
    pnl_pct: float = 0.0


class Backtester:
    def __init__(self,
                 initial_capital: float = 100_000,
                 commission: float = 0.001,
                 slippage: float = 0.0005,
                 max_positions: int = 5,
                 position_size_pct: float = 0.20,
                 stop_loss_pct: float = 0.05,
                 take_profit_pct: float = 0.15):

        self.initial_capital = initial_capital
        self.commission = commission
        self.slippage = slippage
        self.max_positions = max_positions
        self.position_size_pct = position_size_pct
        self.stop_loss_pct = stop_loss_pct
        self.take_profit_pct = take_profit_pct

    def run(self, data: dict, strategy: "BaseStrategy") -> "BacktestResult":
        all_dates = sorted(set(d for df in data.values() for d in df.index))

        cash = self.initial_capital
        open_trades: List[Trade] = []
        closed_trades: List[Trade] = []
        equity_curve = []
        dates_out = []

        for today in all_dates:
            # Current mark-to-market value of all open positions
            def position_value():
                return sum(
                    t.shares * data[t.ticker].loc[today, "Close"]
                    for t in open_trades
                    if today in data[t.ticker].index
                )

            # ── Check exit conditions ──────────────────────────────────────
            to_close = []
            for trade in open_trades:
                if today not in data[trade.ticker].index:
                    continue
                cur_price = data[trade.ticker].loc[today, "Close"]
                ret = (cur_price - trade.entry_price) / trade.entry_price

                reason = None
                exit_price = cur_price

                if ret <= -self.stop_loss_pct:
                    reason = "stop_loss"
                    exit_price = trade.entry_price * (1 - self.stop_loss_pct)
                elif ret >= self.take_profit_pct:
                    reason = "take_profit"
                    exit_price = trade.entry_price * (1 + self.take_profit_pct)
                else:
                    sig = strategy.signals.get(trade.ticker)
                    if sig is not None and today in sig.index and sig.loc[today] == -1:
                        reason = "signal_exit"

                if reason:
                    to_close.append((trade, exit_price, reason))

            for trade, ep, reason in to_close:
                open_trades.remove(trade)
                # Apply exit slippage (slightly worse fill)
                actual_exit = ep * (1 - self.slippage)
                exit_commission = trade.shares * actual_exit * self.commission
                proceeds = trade.shares * actual_exit - exit_commission
                cash += proceeds
                trade.exit_date = today
                trade.exit_price = actual_exit
                trade.exit_reason = reason
                entry_cost = trade.shares * trade.entry_price * (1 + self.commission)
                trade.pnl = proceeds - entry_cost
                trade.pnl_pct = trade.pnl / entry_cost
                closed_trades.append(trade)

            # ── Open new positions ─────────────────────────────────────────
            open_tickers = {t.ticker for t in open_trades}
            n_open = len(open_trades)
            total_value = cash + position_value()

            for ticker, df in sorted(data.items()):
                if n_open >= self.max_positions:
                    break
                if ticker in open_tickers:
                    continue
                if today not in df.index:
                    continue

                sig = strategy.signals.get(ticker)
                if sig is None or today not in sig.index:
                    continue
                if sig.loc[today] != 1:
                    continue

                alloc = total_value * self.position_size_pct
                raw_price = df.loc[today, "Close"]
                entry_price = raw_price * (1 + self.slippage)
                entry_commission_rate = self.commission

                shares = alloc / (entry_price * (1 + entry_commission_rate))
                total_cost = shares * entry_price * (1 + entry_commission_rate)

                # Cap at available cash
                if total_cost > cash:
                    shares = cash / (entry_price * (1 + entry_commission_rate))
                    total_cost = shares * entry_price * (1 + entry_commission_rate)

                if shares < 0.001 or total_cost < 1.0:
                    continue

                cash -= total_cost
                open_trades.append(Trade(
                    ticker=ticker,
                    entry_date=today,
                    entry_price=entry_price,
                    shares=shares,
                ))
                open_tickers.add(ticker)
                n_open += 1

            # ── Snapshot equity ────────────────────────────────────────────
            equity_curve.append(cash + position_value())
            dates_out.append(today)

        # Close remaining at last price
        if all_dates:
            last_date = all_dates[-1]
            for trade in list(open_trades):
                if last_date in data[trade.ticker].index:
                    ep = data[trade.ticker].loc[last_date, "Close"]
                    actual_exit = ep * (1 - self.slippage)
                    exit_commission = trade.shares * actual_exit * self.commission
                    proceeds = trade.shares * actual_exit - exit_commission
                    cash += proceeds
                    trade.exit_date = last_date
                    trade.exit_price = actual_exit
                    trade.exit_reason = "end_of_backtest"
                    entry_cost = trade.shares * trade.entry_price * (1 + self.commission)
                    trade.pnl = proceeds - entry_cost
                    trade.pnl_pct = trade.pnl / entry_cost
                    closed_trades.append(trade)
            open_trades.clear()

        return BacktestResult(
            equity_curve=equity_curve,
            dates=dates_out,
            closed_trades=closed_trades,
            initial_capital=self.initial_capital,
        )


class BacktestResult:
    def __init__(self, equity_curve, dates, closed_trades, initial_capital):
        self.initial_capital = initial_capital
        self.closed_trades = closed_trades
        self.equity_curve = pd.Series(equity_curve, index=dates, name="equity")

    @property
    def total_return(self):
        if len(self.equity_curve) < 2:
            return 0.0
        return (self.equity_curve.iloc[-1] - self.initial_capital) / self.initial_capital

    @property
    def trades_df(self):
        if not self.closed_trades:
            return pd.DataFrame()
        return pd.DataFrame([{
            "ticker": t.ticker,
            "entry_date": t.entry_date,
            "exit_date": t.exit_date,
            "entry_price": round(t.entry_price, 4),
            "exit_price": round(t.exit_price, 4) if t.exit_price else None,
            "shares": round(t.shares, 4),
            "pnl": round(t.pnl, 2),
            "pnl_pct": round(t.pnl_pct * 100, 2),
            "exit_reason": t.exit_reason
        } for t in self.closed_trades])

    def metrics(self) -> dict:
        curve = self.equity_curve
        if len(curve) < 10:
            return {}

        daily_returns = curve.pct_change().dropna()
        n_days = len(curve)
        n_months = n_days / 21

        total_return = self.total_return
        monthly_return = (1 + total_return) ** (1 / max(n_months, 1)) - 1
        annualized = (1 + total_return) ** (252 / max(n_days, 1)) - 1
        vol = daily_returns.std() * np.sqrt(252)
        sharpe = (annualized - 0.05) / vol if vol > 0 else 0

        rolling_max = curve.cummax()
        drawdown = (curve - rolling_max) / rolling_max
        max_dd = drawdown.min()
        calmar = annualized / abs(max_dd) if max_dd != 0 else 0

        trades = self.trades_df
        if len(trades) > 0:
            win_rate = (trades["pnl"] > 0).mean()
            wins = trades.loc[trades["pnl"] > 0, "pnl_pct"]
            losses = trades.loc[trades["pnl"] <= 0, "pnl_pct"]
            avg_win = wins.mean() if len(wins) > 0 else 0
            avg_loss = losses.mean() if len(losses) > 0 else 0
            gross_profit = trades.loc[trades["pnl"] > 0, "pnl"].sum()
            gross_loss = abs(trades.loc[trades["pnl"] <= 0, "pnl"].sum())
            profit_factor = gross_profit / gross_loss if gross_loss > 0 else float("inf")
        else:
            win_rate = avg_win = avg_loss = profit_factor = 0

        return {
            "total_return_pct": round(total_return * 100, 2),
            "monthly_return_pct": round(monthly_return * 100, 2),
            "annualized_return_pct": round(annualized * 100, 2),
            "sharpe_ratio": round(sharpe, 2),
            "max_drawdown_pct": round(max_dd * 100, 2),
            "calmar_ratio": round(calmar, 2),
            "volatility_annualized_pct": round(vol * 100, 2),
            "n_trades": len(trades),
            "win_rate_pct": round(win_rate * 100, 2),
            "avg_win_pct": round(avg_win, 2),
            "avg_loss_pct": round(avg_loss, 2),
            "profit_factor": round(profit_factor, 2),
            "final_equity": round(self.equity_curve.iloc[-1], 2),
        }

    def print_summary(self, strategy_name: str = ""):
        m = self.metrics()
        print(f"\n{'='*55}")
        print(f"  Strategy: {strategy_name}")
        print(f"{'='*55}")
        if not m:
            print("  (no data)")
            print(f"{'='*55}")
            return
        print(f"  Final Equity:      ${m['final_equity']:>12,.2f}")
        print(f"  Total Return:      {m['total_return_pct']:>10.2f}%")
        print(f"  Monthly Return:    {m['monthly_return_pct']:>10.2f}%  ← target ≥10%")
        print(f"  Annualized Return: {m['annualized_return_pct']:>10.2f}%")
        print(f"  Sharpe Ratio:      {m['sharpe_ratio']:>10.2f}")
        print(f"  Max Drawdown:      {m['max_drawdown_pct']:>10.2f}%")
        print(f"  Calmar Ratio:      {m['calmar_ratio']:>10.2f}")
        print(f"  Volatility:        {m['volatility_annualized_pct']:>10.2f}%")
        print(f"  N Trades:          {m['n_trades']:>10}")
        print(f"  Win Rate:          {m['win_rate_pct']:>10.2f}%")
        print(f"  Avg Win:           {m['avg_win_pct']:>10.2f}%")
        print(f"  Avg Loss:          {m['avg_loss_pct']:>10.2f}%")
        print(f"  Profit Factor:     {m['profit_factor']:>10.2f}")
        print(f"{'='*55}")
