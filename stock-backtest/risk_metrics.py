"""
RiskReport: extended risk metrics on top of AdvancedBacktestResult.

Metrics included beyond what backtester_advanced.py already computes:
  - Sortino ratio (downside deviation)
  - Omega ratio
  - Value at Risk (95%, 99%)
  - Conditional VaR / Expected Shortfall (CVaR 95%, 99%)
  - Monthly return consistency (% months profitable, % months >= target)
  - Best and worst month
  - Recovery time from maximum drawdown (trading days)
  - Average holding period (trading days per trade)

Usage
-----
    from risk_metrics import RiskReport
    report = RiskReport(backtest_result)
    report.print_full_report("MyStrategy")
    ok = report.meets_target()
"""

import numpy as np
import pandas as pd
import warnings
warnings.filterwarnings("ignore")


class RiskReport:
    """Extended risk analytics wrapper around AdvancedBacktestResult."""

    def __init__(self, result):
        """
        Parameters
        ----------
        result : AdvancedBacktestResult
            The object returned by AdvancedBacktester.run()
        """
        self.result = result
        self._base = result.metrics()          # dict from backtester_advanced
        self._extra: dict | None = None        # computed lazily

    # ------------------------------------------------------------------
    # Internal helpers
    # ------------------------------------------------------------------

    def _daily_returns(self) -> pd.Series:
        return self.result.equity_curve.pct_change().dropna()

    def _monthly_returns(self) -> pd.Series:
        """Calendar-month returns from equity curve."""
        curve = self.result.equity_curve
        monthly_eq = curve.resample("ME").last()
        return monthly_eq.pct_change().dropna()

    def _compute_extra(self) -> dict:
        if self._extra is not None:
            return self._extra

        curve  = self.result.equity_curve
        dr     = self._daily_returns()
        mr     = self._monthly_returns()
        trades = self.result.trades_df

        n_days   = len(curve)
        n_months = len(mr)

        # ── Sortino ratio ──────────────────────────────────────────────
        rf_daily     = 0.05 / 252
        excess_daily = dr - rf_daily
        downside     = excess_daily[excess_daily < 0]
        downside_dev = np.sqrt((downside ** 2).mean()) * np.sqrt(252) if len(downside) > 0 else np.nan
        ann_ret      = self._base.get("annualized_return_pct", 0) / 100
        sortino      = (ann_ret - 0.05) / downside_dev if (downside_dev and downside_dev > 0) else 0.0

        # ── Omega ratio ────────────────────────────────────────────────
        threshold = 0.0  # daily hurdle
        gains      = (dr - threshold).clip(lower=0).sum()
        losses_neg = (threshold - dr).clip(lower=0).sum()
        omega = gains / losses_neg if losses_neg > 0 else float("inf")

        # ── VaR / CVaR ─────────────────────────────────────────────────
        var_95  = float(np.percentile(dr, 5))   if len(dr) > 20 else np.nan
        var_99  = float(np.percentile(dr, 1))   if len(dr) > 20 else np.nan
        cvar_95 = float(dr[dr <= var_95].mean()) if (len(dr) > 20 and not np.isnan(var_95)) else np.nan
        cvar_99 = float(dr[dr <= var_99].mean()) if (len(dr) > 20 and not np.isnan(var_99)) else np.nan

        # ── Monthly consistency ────────────────────────────────────────
        pct_months_profitable = float((mr > 0).mean() * 100)    if n_months > 0 else 0.0
        pct_months_above_10   = float((mr >= 0.10).mean() * 100) if n_months > 0 else 0.0
        best_month            = float(mr.max() * 100)            if n_months > 0 else 0.0
        worst_month           = float(mr.min() * 100)            if n_months > 0 else 0.0

        # ── Recovery time ──────────────────────────────────────────────
        rolling_max = curve.cummax()
        dd          = (curve - rolling_max) / rolling_max
        max_dd_val  = dd.min()
        recovery_days = None
        if len(dd) > 0 and max_dd_val < 0:
            trough_idx = int(dd.argmin())
            # find first date after trough where we reclaimed the rolling max
            peak_val_at_trough = rolling_max.iloc[trough_idx]
            after_trough       = curve.iloc[trough_idx:]
            recovered          = after_trough[after_trough >= peak_val_at_trough]
            if len(recovered) > 0:
                delta = recovered.index[0] - curve.index[trough_idx]
                recovery_days = int(pd.Timedelta(delta).days)
            # else: recovery_days stays None (still in drawdown at end of backtest)

        # ── Average holding period ─────────────────────────────────────
        avg_holding = None
        if len(trades) > 0 and "entry_date" in trades.columns and "exit_date" in trades.columns:
            holds = (pd.to_datetime(trades["exit_date"]) - pd.to_datetime(trades["entry_date"])).dt.days
            holds = holds.dropna()
            avg_holding = float(holds.mean()) if len(holds) > 0 else None

        self._extra = {
            "sortino_ratio":            round(sortino, 2),
            "omega_ratio":              round(omega, 2),
            "var_95_pct":               round(var_95 * 100, 2) if not np.isnan(var_95) else None,
            "var_99_pct":               round(var_99 * 100, 2) if not np.isnan(var_99) else None,
            "cvar_95_pct":              round(cvar_95 * 100, 2) if not np.isnan(cvar_95) else None,
            "cvar_99_pct":              round(cvar_99 * 100, 2) if not np.isnan(cvar_99) else None,
            "pct_months_profitable":    round(pct_months_profitable, 1),
            "pct_months_above_10":      round(pct_months_above_10, 1),
            "best_month_pct":           round(best_month, 2),
            "worst_month_pct":          round(worst_month, 2),
            "recovery_days":            recovery_days,
            "avg_holding_days":         round(avg_holding, 1) if avg_holding is not None else None,
            "n_months":                 n_months,
        }
        return self._extra

    # ------------------------------------------------------------------
    # Public API
    # ------------------------------------------------------------------

    def full_metrics(self) -> dict:
        """Return all metrics (base + extended) as a single flat dict."""
        return {**self._base, **self._compute_extra()}

    def print_full_report(self, strategy_name: str = ""):
        """Print a formatted full risk report to stdout."""
        b = self._base
        e = self._compute_extra()

        if not b:
            print(f"\n{'='*62}")
            print(f"  Strategy: {strategy_name}  — no data / insufficient history")
            print(f"{'='*62}")
            return

        W = 62
        sep   = "=" * W
        thin  = "-" * W

        def row(label, value, suffix="", flag=""):
            lbl = f"  {label}"
            val = f"{value}{suffix}"
            pad = W - 4 - len(lbl) + 2 - len(val) - len(flag)
            return f"{lbl}{'.' * max(pad, 1)}{val}  {flag}"

        def fmt(v, decimals=2, prefix="", suffix=""):
            if v is None:
                return "N/A"
            return f"{prefix}{v:.{decimals}f}{suffix}"

        print(f"\n{sep}")
        print(f"  RISK REPORT  —  {strategy_name}")
        print(sep)

        # ── Returns ───────────────────────────────────────────────────
        print(f"\n  [ RETURNS ]")
        print(row("Total Return",      fmt(b.get("total_return_pct"), 2), "%"))
        mr = b.get("monthly_return_pct", 0)
        flag = "<-- TARGET >=10%" if mr >= 10 else "<-- BELOW TARGET"
        print(row("Monthly Return",    fmt(mr, 2), "%", flag))
        print(row("Annualized Return", fmt(b.get("annualized_return_pct"), 2), "%"))
        print(row("Best Month",        fmt(e.get("best_month_pct"), 2), "%"))
        print(row("Worst Month",       fmt(e.get("worst_month_pct"), 2), "%"))

        # ── Risk-Adjusted ─────────────────────────────────────────────
        print(f"\n  [ RISK-ADJUSTED ]")
        sr = b.get("sharpe_ratio", 0)
        print(row("Sharpe Ratio",   fmt(sr, 2), "", ">1.5 target" if sr >= 1.5 else ""))
        print(row("Sortino Ratio",  fmt(e.get("sortino_ratio"), 2)))
        print(row("Omega Ratio",    fmt(e.get("omega_ratio"), 2)))
        cal = b.get("calmar_ratio", 0)
        print(row("Calmar Ratio",   fmt(cal, 2), "", ">2.0 target" if cal >= 2.0 else ""))
        print(row("Volatility Ann", fmt(b.get("volatility_annualized_pct"), 2), "%"))

        # ── Drawdown ──────────────────────────────────────────────────
        print(f"\n  [ DRAWDOWN ]")
        mdd = b.get("max_drawdown_pct", 0)
        print(row("Max Drawdown",     fmt(mdd, 2), "%", "> -30% limit" if mdd < -30 else "OK"))
        rec = e.get("recovery_days")
        print(row("Recovery Time",    f"{rec} days" if rec is not None else "N/A (still in DD or no DD)"))

        # ── VaR / CVaR ────────────────────────────────────────────────
        print(f"\n  [ TAIL RISK (Daily) ]")
        print(row("VaR 95%",   fmt(e.get("var_95_pct"), 2), "%"))
        print(row("VaR 99%",   fmt(e.get("var_99_pct"), 2), "%"))
        print(row("CVaR 95%",  fmt(e.get("cvar_95_pct"), 2), "%"))
        print(row("CVaR 99%",  fmt(e.get("cvar_99_pct"), 2), "%"))

        # ── Trade stats ───────────────────────────────────────────────
        print(f"\n  [ TRADE STATISTICS ]")
        wr = b.get("win_rate_pct", 0)
        print(row("N Trades",         str(b.get("n_trades", 0))))
        print(row("Win Rate",         fmt(wr, 2), "%", ">50% target" if wr >= 50 else ""))
        print(row("Avg Win",          fmt(b.get("avg_win_pct"), 2), "%"))
        print(row("Avg Loss",         fmt(b.get("avg_loss_pct"), 2), "%"))
        pf = b.get("profit_factor", 0)
        print(row("Profit Factor",    fmt(pf, 2), "", ">1.5 target" if pf >= 1.5 else ""))
        print(row("Avg Holding",      fmt(e.get("avg_holding_days"), 1, suffix=" days") if e.get("avg_holding_days") is not None else "N/A"))

        # ── Monthly consistency ────────────────────────────────────────
        print(f"\n  [ MONTHLY CONSISTENCY ]")
        print(row("Months Tracked",       str(e.get("n_months", 0))))
        print(row("% Months Profitable",  fmt(e.get("pct_months_profitable"), 1), "%"))
        print(row("% Months >= 10%",      fmt(e.get("pct_months_above_10"), 1), "%"))

        # ── Summary verdict ───────────────────────────────────────────
        print(f"\n  [ TARGET CHECK ]")
        ok = self.meets_target()
        checks = [
            ("Monthly >=10%",    mr >= 10.0,            f"{mr:.2f}%"),
            ("Sharpe >1.5",      sr >= 1.5,             f"{sr:.2f}"),
            ("MaxDD > -30%",     mdd >= -30.0,          f"{mdd:.2f}%"),
            ("Calmar >2.0",      cal >= 2.0,            f"{cal:.2f}"),
            ("Win Rate >50%",    wr >= 50.0,            f"{wr:.2f}%"),
            ("Profit Factor >1.5", pf >= 1.5,           f"{pf:.2f}"),
        ]
        for label, passed, val in checks:
            status = "PASS" if passed else "FAIL"
            print(f"    [{status}]  {label:<25} {val}")
        overall = "ALL TARGETS MET" if ok else "NOT ALL TARGETS MET"
        print(f"\n  >>> {overall} <<<")
        print(f"  Final Equity: ${b.get('final_equity', 0):>12,.2f}")
        print(f"{sep}\n")

    def meets_target(self,
                     monthly_pct: float = 10.0,
                     sharpe: float = 1.5,
                     max_dd: float = -30.0,
                     calmar: float = 2.0,
                     win_rate: float = 50.0,
                     pf: float = 1.5) -> bool:
        """
        Returns True if ALL of the following are satisfied:
          - Monthly return >= monthly_pct (%)
          - Sharpe ratio  >= sharpe
          - Max drawdown  >= max_dd  (i.e. drawdown is less severe than the limit)
          - Calmar ratio  >= calmar
          - Win rate      >= win_rate (%)
          - Profit factor >= pf
        """
        b = self._base
        if not b:
            return False
        return (
            b.get("monthly_return_pct",    0) >= monthly_pct and
            b.get("sharpe_ratio",          0) >= sharpe      and
            b.get("max_drawdown_pct",      0) >= max_dd      and
            b.get("calmar_ratio",          0) >= calmar      and
            b.get("win_rate_pct",          0) >= win_rate    and
            b.get("profit_factor",         0) >= pf
        )
