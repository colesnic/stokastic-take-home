"""
Advanced backtester with trailing stops, ATR position sizing, and pyramiding support.
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
    atr_at_entry: float = 0.0
    trail_stop: float = 0.0   # current trailing stop price
    highest_close: float = 0.0  # highest close seen since entry
    exit_date: Optional[pd.Timestamp] = None
    exit_price: Optional[float] = None
    exit_reason: str = ""
    pnl: float = 0.0
    pnl_pct: float = 0.0


class AdvancedBacktester:
    """
    Ten real-world adjustments vs naive backtester (all off by default):

    1.  execution_lag=1         Signal on close-T → fill at open-T+1
    2.  max_overnight_gap_pct   Skip entry if open-T+1 gaps >N% above signal close
    3.  (lag=1 implicit)        Stop-loss fills at open if stock gaps below stop price
    4.  variable_slippage=True  Price-tiered bid-ask spread instead of flat slippage
    5.  market_impact_factor    Extra slippage proportional to order notional / $10K
    6.  short_term_tax_rate     Deduct % from realised gains on trades held < 365 days
    7.  borrowing_rate          Daily interest on capital deployed beyond initial equity
    8.  max_portfolio_heat_pct  Cap total open ATR-risk across all positions
    9.  portfolio_stop_pct      Flatten all positions if equity drops >N% from HWM
    10. max_position_correlation Skip new position if 20-day corr with any holding > N
    """
    def __init__(self,
                 initial_capital: float = 100_000,
                 commission: float = 0.001,
                 slippage: float = 0.0005,
                 max_positions: int = 3,
                 position_size_pct: float = 0.30,
                 atr_stop_multiplier: float = 2.5,
                 atr_trail_multiplier: float = 2.0,
                 min_atr_risk_pct: float = 0.02,
                 max_atr_risk_pct: float = 0.08,
                 risk_per_trade_pct: float = 0.02,
                 # ── Real-world adjustments ───────────────────────────────
                 execution_lag: int = 0,
                 max_overnight_gap_pct: float = 0.0,
                 variable_slippage: bool = False,
                 market_impact_factor: float = 0.0,
                 short_term_tax_rate: float = 0.0,
                 borrowing_rate: float = 0.0,
                 max_portfolio_heat_pct: float = 1.0,
                 portfolio_stop_pct: float = 0.0,
                 max_position_correlation: float = 1.0,
                 ):

        self.initial_capital = initial_capital
        self.commission = commission
        self.slippage = slippage
        self.max_positions = max_positions
        self.position_size_pct = position_size_pct
        self.atr_stop_multiplier = atr_stop_multiplier
        self.atr_trail_multiplier = atr_trail_multiplier
        self.min_atr_risk_pct = min_atr_risk_pct
        self.max_atr_risk_pct = max_atr_risk_pct
        self.risk_per_trade_pct = risk_per_trade_pct
        self.execution_lag = execution_lag
        self.max_overnight_gap_pct = max_overnight_gap_pct
        self.variable_slippage = variable_slippage
        self.market_impact_factor = market_impact_factor
        self.short_term_tax_rate = short_term_tax_rate
        self.borrowing_rate = borrowing_rate
        self.max_portfolio_heat_pct = max_portfolio_heat_pct
        self.portfolio_stop_pct = portfolio_stop_pct
        self.max_position_correlation = max_position_correlation

    def _effective_slippage(self, price: float, order_value: float = 0.0) -> float:
        """Adjustments 4 + 5: variable spread and market impact."""
        if self.variable_slippage:
            if price < 10:     base = 0.002
            elif price < 50:   base = 0.001
            elif price < 200:  base = 0.0005
            else:              base = 0.0002
        else:
            base = self.slippage
        impact = self.market_impact_factor * (order_value / 10_000)
        return base + impact

    def _passes_correlation(self, ticker: str, today,
                            open_trades: list, data: dict) -> bool:
        """Adjustment 10: skip if 20-day correlation with any open position > threshold."""
        if self.max_position_correlation >= 1.0 or not open_trades:
            return True
        cand = data[ticker]["Close"].pct_change().loc[:today].iloc[-20:]
        for t in open_trades:
            held = data[t.ticker]["Close"].pct_change().loc[:today].iloc[-20:]
            aligned = cand.align(held, join="inner")[0]
            held_aligned = cand.align(held, join="inner")[1]
            if len(aligned) >= 10:
                corr = float(aligned.corr(held_aligned))
                if not np.isnan(corr) and corr > self.max_position_correlation:
                    return False
        return True

    def run(self, data: dict, strategy) -> "AdvancedBacktestResult":
        execution_lag = self.execution_lag
        all_dates = sorted(set(d for df in data.values() for d in df.index))
        next_date  = {all_dates[i]: all_dates[i + 1]
                      for i in range(len(all_dates) - 1)}

        cash = self.initial_capital
        open_trades: List[Trade] = []
        closed_trades: List[Trade] = []
        equity_curve = []
        dates_out = []
        portfolio_hwm = self.initial_capital   # for adjustment 9

        # Queued for next-open execution (only used when execution_lag=1)
        pending_entries: list = []   # (ticker, atr_val, signal_close)
        pending_exits:   list = []   # (trade, reason)

        def get_close(ticker, date):
            if date in data[ticker].index:
                return float(data[ticker].loc[date, "Close"])
            return None

        def position_value(ref_date):
            return sum(
                t.shares * (get_close(t.ticker, ref_date) or t.entry_price)
                for t in open_trades
            )

        def close_trade(trade, ep, reason, date):
            nonlocal cash
            open_trades.remove(trade)
            slip  = self._effective_slippage(ep, trade.shares * ep)
            actual_exit = max(ep * (1 - slip), 0.01)
            exit_comm   = trade.shares * actual_exit * self.commission
            proceeds    = trade.shares * actual_exit - exit_comm
            gross_pnl   = proceeds - trade.shares * trade.entry_price * (1 + self.commission)
            # Adjustment 6: short-term capital gains tax
            if self.short_term_tax_rate > 0 and gross_pnl > 0:
                hold_days = (date - trade.entry_date).days if hasattr(date - trade.entry_date, 'days') else 0
                if hold_days < 365:
                    tax      = gross_pnl * self.short_term_tax_rate
                    proceeds -= tax
            cash += proceeds
            trade.exit_date   = date
            trade.exit_price  = actual_exit
            trade.exit_reason = reason
            entry_cost        = trade.shares * trade.entry_price * (1 + self.commission)
            trade.pnl         = proceeds - entry_cost
            trade.pnl_pct     = trade.pnl / entry_cost
            closed_trades.append(trade)

        def open_trade(ticker, fill_price, atr_val, total_val, fill_date):
            nonlocal cash
            # Adjustment 8: portfolio heat cap — don't enter if total ATR risk is maxed
            existing_heat = sum(
                (t.entry_price - t.trail_stop) * t.shares for t in open_trades
            )
            heat_budget = total_val * self.max_portfolio_heat_pct
            if existing_heat >= heat_budget:
                return
            initial_stop   = fill_price - self.atr_stop_multiplier * atr_val
            risk_per_share = fill_price - initial_stop
            if risk_per_share <= 0:
                return
            dollar_risk     = total_val * self.risk_per_trade_pct
            shares_by_risk  = dollar_risk / risk_per_share
            alloc           = total_val * self.position_size_pct
            slip            = self._effective_slippage(fill_price, alloc)
            entry_price     = fill_price * (1 + slip)
            shares_by_alloc = alloc / (entry_price * (1 + self.commission))
            shares          = min(shares_by_risk, shares_by_alloc)
            total_cost      = shares * entry_price * (1 + self.commission)
            if total_cost > cash:
                shares     = cash / (entry_price * (1 + self.commission)) * 0.98
                total_cost = shares * entry_price * (1 + self.commission)
            if shares < 0.001 or total_cost < 1.0:
                return
            cash -= total_cost
            open_trades.append(Trade(
                ticker=ticker, entry_date=fill_date, entry_price=entry_price,
                shares=shares, atr_at_entry=atr_val,
                trail_stop=initial_stop, highest_close=fill_price,
            ))

        for i, today in enumerate(all_dates):

            # ── 1. Execute pending next-open entries / exits (lag=1 only) ──
            if execution_lag == 1 and pending_entries:
                open_tickers_now = {t.ticker for t in open_trades}
                tv = cash + position_value(today)
                for (ticker, sig_atr, sig_close) in pending_entries:
                    if len(open_trades) >= self.max_positions:
                        break
                    if ticker in open_tickers_now:
                        continue
                    if today not in data[ticker].index:
                        continue
                    fill_px = float(data[ticker].loc[today, "Open"])
                    # Adjustment 2: skip if open gaps up more than max_overnight_gap_pct
                    if (self.max_overnight_gap_pct > 0 and sig_close > 0 and
                            fill_px / sig_close - 1 > self.max_overnight_gap_pct):
                        continue
                    open_trade(ticker, fill_px, sig_atr, tv, today)
                    open_tickers_now.add(ticker)
                pending_entries.clear()

            if execution_lag == 1 and pending_exits:
                for (trade, reason) in list(pending_exits):
                    if trade not in open_trades:
                        continue
                    if today not in data[trade.ticker].index:
                        continue
                    fill_px = float(data[trade.ticker].loc[today, "Open"])
                    close_trade(trade, fill_px, reason, today)
                pending_exits.clear()

            # ── 2. Check stop triggers on today's intraday data ────────────
            # IMPORTANT: check the EXISTING stop level (set at yesterday's close)
            # BEFORE ratcheting it with today's close. The intraday low happens
            # before today's close — using today's close to update the stop and
            # then checking against today's low is chronologically wrong.
            to_stop = []
            for trade in open_trades:
                if today not in data[trade.ticker].index:
                    continue
                row            = data[trade.ticker].loc[today]
                existing_stop  = trade.trail_stop   # stop as of start of day

                if execution_lag == 0:
                    # Original: triggered if close falls below existing stop
                    cur_close = float(row["Close"])
                    if cur_close <= existing_stop:
                        to_stop.append((trade, existing_stop, "trailing_stop"))
                else:
                    # Realistic: triggered if intraday low (or gap-down open) hits stop
                    day_low  = float(row["Low"])
                    day_open = float(row["Open"])
                    if min(day_open, day_low) <= existing_stop:
                        fill = day_open if day_open < existing_stop else existing_stop
                        to_stop.append((trade, fill, "trailing_stop"))

            for trade, ep, reason in to_stop:
                close_trade(trade, ep, reason, today)

            # Ratchet trailing stops upward using today's close (affects tomorrow+)
            for trade in open_trades:
                if today not in data[trade.ticker].index:
                    continue
                row       = data[trade.ticker].loc[today]
                cur_close = float(row["Close"])
                atr_now   = float(row.get("atr14", trade.atr_at_entry))
                if cur_close > trade.highest_close:
                    trade.highest_close = cur_close
                    new_trail = cur_close - self.atr_trail_multiplier * atr_now
                    if new_trail > trade.trail_stop:
                        trade.trail_stop = new_trail

            # ── 3. Check signal exits ──────────────────────────────────────
            sig_exits = []
            for trade in open_trades:
                sig = strategy.signals.get(trade.ticker)
                if (sig is not None and today in sig.index and sig.loc[today] == -1):
                    sig_exits.append(trade)

            if execution_lag == 0:
                for trade in sig_exits:
                    ep = get_close(trade.ticker, today) or trade.entry_price
                    close_trade(trade, ep, "signal_exit", today)
            else:
                for trade in sig_exits:
                    pending_exits.append((trade, "signal_exit"))

            # ── 4. Check entry signals ─────────────────────────────────────
            total_val    = cash + position_value(today)
            open_tickers = {t.ticker for t in open_trades}
            n_open       = len(open_trades)

            candidates = []
            for ticker, df in data.items():
                if ticker in open_tickers or n_open >= self.max_positions:
                    continue
                if today not in df.index:
                    continue
                sig = strategy.signals.get(ticker)
                if sig is None or today not in sig.index or sig.loc[today] != 1:
                    continue
                row   = df.loc[today]
                adx_v = float(row.get("adx14", 0))
                candidates.append((ticker, adx_v, row))

            candidates.sort(key=lambda x: x[1], reverse=True)

            for ticker, adx_v, row in candidates:
                if len(open_trades) >= self.max_positions:
                    break
                atr_val = float(row.get("atr14", float(row["Close"]) * 0.02))

                # Adjustment 10: skip if highly correlated with an open position
                if not self._passes_correlation(ticker, today, open_trades, data):
                    continue

                sig_close = float(row["Close"])
                if execution_lag == 0:
                    open_trade(ticker, sig_close, atr_val, total_val, today)
                else:
                    # Queue for next open (only if next day exists)
                    if today in next_date:
                        pending_entries.append((ticker, atr_val, sig_close))
                        open_tickers.add(ticker)
                        n_open += 1

            # Adjustment 7: borrowing cost — daily interest only when cash goes
            # negative (i.e. genuinely leveraged / margin). For a standard
            # equity-funded account cash stays >= 0 so this costs nothing.
            if self.borrowing_rate > 0 and cash < 0:
                daily_interest = (-cash) * (self.borrowing_rate / 252)
                cash -= daily_interest

            eq_today = cash + position_value(today)

            # Adjustment 9: portfolio circuit breaker — flatten if down >N% from HWM
            portfolio_hwm = max(portfolio_hwm, eq_today)
            if (self.portfolio_stop_pct > 0 and
                    eq_today < portfolio_hwm * (1 - self.portfolio_stop_pct)):
                for trade in list(open_trades):
                    ep = get_close(trade.ticker, today) or trade.entry_price
                    close_trade(trade, ep, "portfolio_stop", today)
                eq_today = cash + position_value(today)

            equity_curve.append(eq_today)
            dates_out.append(today)

        # ── Close remaining open positions at end of data ──────────────────
        if all_dates:
            last_date = all_dates[-1]
            for trade in list(open_trades):
                if last_date in data[trade.ticker].index:
                    ep = float(data[trade.ticker].loc[last_date, "Close"])
                    close_trade(trade, ep, "end_of_backtest", last_date)
            open_trades.clear()

        return AdvancedBacktestResult(
            equity_curve=equity_curve,
            dates=dates_out,
            closed_trades=closed_trades,
            initial_capital=self.initial_capital,
        )


class AdvancedBacktestResult:
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
