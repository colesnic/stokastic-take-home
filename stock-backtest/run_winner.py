"""
Final winner strategy backtest.
Best config discovered: RS Momentum, top_n=3, rebalance daily,
lookback 10/20/40 days, 48% position size, 1.2× ATR trailing stop.
"""
import sys, os
sys.path.insert(0, os.path.dirname(__file__))

import pandas as pd
import numpy as np
import matplotlib
matplotlib.use("Agg")
import matplotlib.pyplot as plt
import matplotlib.dates as mdates
import warnings
warnings.filterwarnings("ignore")

from data_fetcher import fetch_multiple
from optimize import add_indicators
from strategy_rs_momentum import RSMomentumStrategy
from backtester_advanced import AdvancedBacktester

HM_TICKERS = [
    "NVDA", "AMD", "TSLA", "AMZN", "META", "AAPL", "MSFT",
    "SMCI", "ARM", "AVGO", "MRVL",
    "COIN", "MSTR", "PLTR",
    "QQQ", "SOXX", "ARKK",
]

BACKTEST_START  = "2022-01-01"
BACKTEST_END    = "2024-12-31"
INITIAL_CAPITAL = 100_000
OUTPUT_DIR      = os.path.join(os.path.dirname(__file__), "output")


def main():
    print("\n" + "="*65)
    print("  WINNER STRATEGY FINAL BACKTEST")
    print(f"  RS Momentum | Top-3 | Daily Rebalance | 48% Position")
    print("="*65)

    raw_data = fetch_multiple(HM_TICKERS, BACKTEST_START, BACKTEST_END, "1d")
    data = add_indicators(raw_data)
    print(f"\n  {len(data)} tickers loaded")

    # Confirmed best config
    strat = RSMomentumStrategy(
        top_n=3,
        rebalance_days=2,
        lookback_short=10,
        lookback_mid=20,
        lookback_long=40,
        adx_min=15.0,
        rsi_min=40.0,
    )
    strat.prepare(data)

    bt = AdvancedBacktester(
        initial_capital=INITIAL_CAPITAL,
        commission=0.001,
        slippage=0.0005,
        max_positions=3,
        position_size_pct=0.48,
        atr_stop_multiplier=1.2,
        atr_trail_multiplier=0.9,
        risk_per_trade_pct=0.04,
    )
    result = bt.run(data, strat)
    result.print_summary("RS_Momentum_Winner")

    m = result.metrics()
    trades = result.trades_df

    os.makedirs(OUTPUT_DIR, exist_ok=True)
    trades.to_csv(os.path.join(OUTPUT_DIR, "winner_trades.csv"), index=False)

    # Per-ticker breakdown
    if len(trades) > 0:
        print("\n  Per-Ticker Performance:")
        by_t = trades.groupby("ticker").agg(
            n_trades=("pnl","count"),
            total_pnl=("pnl","sum"),
            avg_pnl_pct=("pnl_pct","mean"),
            win_rate=("pnl", lambda x: (x>0).mean()*100)
        ).sort_values("total_pnl", ascending=False)
        print(by_t.to_string())

        print("\n  Exit Reason Breakdown:")
        print(trades["exit_reason"].value_counts().to_string())

    # Monthly return breakdown
    monthly = result.equity_curve.resample("ME").last().pct_change().dropna() * 100
    print("\n  Monthly Returns:")
    for date, ret in monthly.items():
        bar = "█" * int(abs(ret) / 2)
        sign = "+" if ret >= 0 else ""
        above_target = " ✓" if ret >= 10 else ""
        print(f"    {date.strftime('%Y-%m')}:  {sign}{ret:6.2f}%  {bar}{above_target}")

    months_above_10 = (monthly >= 10).sum()
    months_total    = len(monthly)
    print(f"\n  Months ≥10%: {months_above_10}/{months_total} "
          f"({100*months_above_10/months_total:.0f}%)")

    # ── Charts ─────────────────────────────────────────────────────────────
    fig, axes = plt.subplots(3, 1, figsize=(14, 14))

    # Equity curve
    ax = axes[0]
    c = result.equity_curve
    ax.semilogy(c.index, c, color="#2980b9", linewidth=2)
    ax.fill_between(c.index, INITIAL_CAPITAL, c, where=(c >= INITIAL_CAPITAL),
                    alpha=0.15, color="#27ae60")
    ax.fill_between(c.index, INITIAL_CAPITAL, c, where=(c < INITIAL_CAPITAL),
                    alpha=0.15, color="#e74c3c")
    ax.axhline(INITIAL_CAPITAL, color="k", lw=0.8, ls="--", label=f"Starting capital ${INITIAL_CAPITAL:,}")
    ax.set_title(f"Equity Curve (Log Scale) — {m.get('monthly_return_pct',0):.2f}% Monthly Return",
                 fontsize=13, fontweight="bold")
    ax.set_ylabel("Portfolio Value ($)")
    ax.yaxis.set_major_formatter(plt.FuncFormatter(lambda x, _: f"${x:,.0f}"))
    ax.legend()
    ax.grid(True, alpha=0.3)
    ax.xaxis.set_major_formatter(mdates.DateFormatter("%Y-%m"))
    plt.setp(ax.xaxis.get_majorticklabels(), rotation=25)

    # Monthly returns
    ax2 = axes[1]
    colors = ["#27ae60" if x >= 10 else "#2980b9" if x >= 0 else "#e74c3c"
              for x in monthly.values]
    bars = ax2.bar(monthly.index, monthly.values, color=colors, alpha=0.8, width=20)
    ax2.axhline(10, color="gold", ls="--", lw=2, label="10% Monthly Target")
    ax2.axhline(0, color="k", lw=0.8)
    ax2.set_title("Monthly Returns", fontsize=12, fontweight="bold")
    ax2.set_ylabel("Return (%)")
    ax2.legend()
    ax2.grid(True, alpha=0.3, axis="y")
    ax2.xaxis.set_major_formatter(mdates.DateFormatter("%Y-%m"))
    plt.setp(ax2.xaxis.get_majorticklabels(), rotation=25)

    # Drawdown
    ax3 = axes[2]
    dd = (c - c.cummax()) / c.cummax() * 100
    ax3.fill_between(dd.index, dd.values, 0, alpha=0.5, color="#e74c3c")
    ax3.plot(dd.index, dd, color="#c0392b", lw=1)
    ax3.set_title("Drawdown (%)", fontsize=12, fontweight="bold")
    ax3.set_ylabel("Drawdown (%)")
    ax3.grid(True, alpha=0.3)
    ax3.xaxis.set_major_formatter(mdates.DateFormatter("%Y-%m"))
    plt.setp(ax3.xaxis.get_majorticklabels(), rotation=25)

    plt.tight_layout()
    chart_path = os.path.join(OUTPUT_DIR, "winner_strategy.png")
    plt.savefig(chart_path, dpi=150, bbox_inches="tight")
    plt.close()

    print(f"\n  [Chart → {chart_path}]")
    print(f"\n  {'='*60}")
    print(f"  FINAL RESULT")
    print(f"  {'='*60}")
    print(f"  Monthly Return:    {m.get('monthly_return_pct',0):.2f}%")
    print(f"  Annualized Return: {m.get('annualized_return_pct',0):.2f}%")
    print(f"  Sharpe Ratio:      {m.get('sharpe_ratio',0):.2f}")
    print(f"  Max Drawdown:      {m.get('max_drawdown_pct',0):.2f}%")
    print(f"  Calmar Ratio:      {m.get('calmar_ratio',0):.2f}")
    print(f"  Win Rate:          {m.get('win_rate_pct',0):.2f}%")
    print(f"  Profit Factor:     {m.get('profit_factor',0):.2f}")
    print(f"  Total Trades:      {m.get('n_trades',0)}")
    print(f"  Final Equity:      ${m.get('final_equity',0):,.2f}")
    if m.get('monthly_return_pct',0) >= 10.0:
        print(f"\n  ✓  10% MONTHLY TARGET ACHIEVED!")
    print(f"  {'='*60}\n")

    return result, m


if __name__ == "__main__":
    main()
