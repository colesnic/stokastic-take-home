"""
Advanced backtest runner: high-momentum strategy with trailing stops.
Tests several hand-tuned configurations and reports best monthly return.
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
from indicators import ema, rsi, macd, bollinger_bands, atr, adx, donchian
from backtester_advanced import AdvancedBacktester, AdvancedBacktestResult
from optimize import HighMomentumStrategy, add_indicators


TICKERS = [
    "NVDA", "AMD", "AAPL", "MSFT", "META", "GOOGL", "TSLA", "AMZN",
    "SMCI", "ARM", "AVGO", "MRVL", "QQQ", "SOXX", "ARKK", "XLK", "XLY",
    "MRNA", "BIIB", "COIN", "MSTR", "PLTR",
]

BACKTEST_START = "2022-01-01"
BACKTEST_END   = "2024-12-31"
INITIAL_CAPITAL = 100_000


# Hand-tuned configurations to test
CONFIGS = [
    {
        "name": "Momentum_Conservative",
        "strategy": dict(dc_period=20, ema_fast=10, ema_slow=50, ema_trend=200,
                         rsi_lo=45, rsi_hi=76, adx_min=25, vol_mult=1.2, macd_confirm=True),
        "backtest": dict(max_positions=5, position_size_pct=0.20,
                         atr_stop_multiplier=2.5, atr_trail_multiplier=2.0, risk_per_trade_pct=0.02),
    },
    {
        "name": "Momentum_Aggressive",
        "strategy": dict(dc_period=20, ema_fast=10, ema_slow=50, ema_trend=200,
                         rsi_lo=45, rsi_hi=76, adx_min=25, vol_mult=1.2, macd_confirm=True),
        "backtest": dict(max_positions=3, position_size_pct=0.33,
                         atr_stop_multiplier=2.0, atr_trail_multiplier=1.5, risk_per_trade_pct=0.03),
    },
    {
        "name": "Momentum_MaxConcentrated",
        "strategy": dict(dc_period=15, ema_fast=8, ema_slow=30, ema_trend=100,
                         rsi_lo=50, rsi_hi=78, adx_min=28, vol_mult=1.0, macd_confirm=True),
        "backtest": dict(max_positions=2, position_size_pct=0.45,
                         atr_stop_multiplier=1.8, atr_trail_multiplier=1.5, risk_per_trade_pct=0.04),
    },
    {
        "name": "Breakout_LooseFilters",
        "strategy": dict(dc_period=20, ema_fast=10, ema_slow=50, ema_trend=200,
                         rsi_lo=40, rsi_hi=80, adx_min=20, vol_mult=1.0, macd_confirm=False),
        "backtest": dict(max_positions=5, position_size_pct=0.20,
                         atr_stop_multiplier=3.0, atr_trail_multiplier=2.5, risk_per_trade_pct=0.02),
    },
    {
        "name": "Breakout_TightFilters",
        "strategy": dict(dc_period=25, ema_fast=10, ema_slow=50, ema_trend=200,
                         rsi_lo=50, rsi_hi=74, adx_min=30, vol_mult=1.5, macd_confirm=True),
        "backtest": dict(max_positions=4, position_size_pct=0.25,
                         atr_stop_multiplier=2.5, atr_trail_multiplier=2.0, risk_per_trade_pct=0.025),
    },
    {
        "name": "FastEMA_HighConviction",
        "strategy": dict(dc_period=15, ema_fast=5, ema_slow=20, ema_trend=100,
                         rsi_lo=55, rsi_hi=76, adx_min=28, vol_mult=1.3, macd_confirm=True),
        "backtest": dict(max_positions=3, position_size_pct=0.33,
                         atr_stop_multiplier=2.0, atr_trail_multiplier=1.8, risk_per_trade_pct=0.03),
    },
    {
        "name": "WideTrail_LetWinnersRun",
        "strategy": dict(dc_period=20, ema_fast=10, ema_slow=50, ema_trend=200,
                         rsi_lo=45, rsi_hi=80, adx_min=22, vol_mult=1.1, macd_confirm=True),
        "backtest": dict(max_positions=4, position_size_pct=0.25,
                         atr_stop_multiplier=3.0, atr_trail_multiplier=3.0, risk_per_trade_pct=0.02),
    },
    {
        "name": "Ultra_Aggressive",
        "strategy": dict(dc_period=10, ema_fast=5, ema_slow=20, ema_trend=50,
                         rsi_lo=50, rsi_hi=80, adx_min=25, vol_mult=1.0, macd_confirm=True),
        "backtest": dict(max_positions=2, position_size_pct=0.48,
                         atr_stop_multiplier=1.5, atr_trail_multiplier=1.2, risk_per_trade_pct=0.05),
    },
]


def run_config(name, strat_params, bt_params, data):
    strat = HighMomentumStrategy(**strat_params)
    strat.prepare(data)
    bt = AdvancedBacktester(initial_capital=INITIAL_CAPITAL, **bt_params)
    result = bt.run(data, strat)
    result.print_summary(name)
    return result


def plot_advanced(results: dict, output_dir: str):
    os.makedirs(output_dir, exist_ok=True)
    colors = plt.cm.tab10.colors

    fig, axes = plt.subplots(3, 1, figsize=(14, 16))

    # Equity curves
    ax = axes[0]
    for i, (name, res) in enumerate(results.items()):
        c = res.equity_curve
        if len(c) < 2:
            continue
        norm = c / c.iloc[0] * 100
        ax.plot(c.index, norm, label=name, color=colors[i % 10], linewidth=1.5)
    ax.axhline(100, color="black", linewidth=0.8, linestyle="--")
    ax.set_title("Equity Curves (Normalized to 100)", fontsize=12, fontweight="bold")
    ax.set_ylabel("Equity (Base=100)")
    ax.legend(fontsize=7, ncol=2)
    ax.grid(True, alpha=0.3)
    ax.xaxis.set_major_formatter(mdates.DateFormatter("%Y-%m"))

    # Monthly returns — best strategy
    ax2 = axes[1]
    best_name = max(results, key=lambda n: results[n].metrics().get("monthly_return_pct", -999))
    best = results[best_name]
    monthly = best.equity_curve.resample("ME").last().pct_change().dropna() * 100
    bar_colors = ["#27ae60" if x >= 10 else "#2980b9" if x >= 0 else "#e74c3c" for x in monthly.values]
    ax2.bar(monthly.index, monthly.values, color=bar_colors, alpha=0.8, width=20)
    ax2.axhline(10, color="gold", linestyle="--", linewidth=1.5, label="10% Monthly Target")
    ax2.axhline(0, color="black", linewidth=0.8)
    ax2.set_title(f"Monthly Returns — {best_name}", fontsize=12, fontweight="bold")
    ax2.set_ylabel("Monthly Return (%)")
    ax2.legend()
    ax2.grid(True, alpha=0.3, axis="y")

    # Drawdown
    ax3 = axes[2]
    for i, (name, res) in enumerate(results.items()):
        c = res.equity_curve
        if len(c) < 2:
            continue
        dd = (c - c.cummax()) / c.cummax() * 100
        ax3.plot(dd.index, dd, label=name, color=colors[i % 10], linewidth=1.2)
    ax3.set_title("Drawdown (%)", fontsize=12, fontweight="bold")
    ax3.set_ylabel("Drawdown (%)")
    ax3.legend(fontsize=7, ncol=2)
    ax3.grid(True, alpha=0.3)
    ax3.xaxis.set_major_formatter(mdates.DateFormatter("%Y-%m"))

    for a in axes:
        plt.setp(a.xaxis.get_majorticklabels(), rotation=25)

    plt.tight_layout()
    plt.savefig(os.path.join(output_dir, "advanced_equity_curves.png"), dpi=150, bbox_inches="tight")
    plt.close()
    print(f"  [Charts saved to {output_dir}/advanced_equity_curves.png]")


def comparison_table(results: dict) -> pd.DataFrame:
    rows = []
    for name, res in results.items():
        m = res.metrics()
        if m:
            m["strategy"] = name
            rows.append(m)
    df = pd.DataFrame(rows).set_index("strategy")
    cols = ["monthly_return_pct", "annualized_return_pct", "sharpe_ratio",
            "max_drawdown_pct", "calmar_ratio", "win_rate_pct",
            "profit_factor", "n_trades", "final_equity"]
    df = df[[c for c in cols if c in df.columns]]
    print("\n" + "="*90)
    print("ADVANCED STRATEGY COMPARISON")
    print("="*90)
    print(df.sort_values("monthly_return_pct", ascending=False).to_string())
    return df


def main():
    print("\n" + "="*60)
    print("  ADVANCED BACKTESTING ENGINE")
    print(f"  Period: {BACKTEST_START} → {BACKTEST_END}")
    print(f"  Capital: ${INITIAL_CAPITAL:,}  |  Trailing Stops")
    print("="*60)

    print("\n[Loading data]...")
    raw_data = fetch_multiple(TICKERS, BACKTEST_START, BACKTEST_END, "1d")
    data = add_indicators(raw_data)
    print(f"  {len(data)} tickers loaded")

    print("\n[Running configs]...")
    results = {}
    for cfg in CONFIGS:
        print(f"\n  [{cfg['name']}]")
        results[cfg["name"]] = run_config(
            cfg["name"], cfg["strategy"], cfg["backtest"], data
        )

    cdf = comparison_table(results)

    output_dir = os.path.join(os.path.dirname(__file__), "output")
    plot_advanced(results, output_dir)
    cdf.to_csv(os.path.join(output_dir, "advanced_comparison.csv"))

    best_name = cdf["monthly_return_pct"].idxmax()
    best_monthly = cdf.loc[best_name, "monthly_return_pct"]
    best_sharpe  = cdf.loc[best_name, "sharpe_ratio"]
    best_dd      = cdf.loc[best_name, "max_drawdown_pct"]

    print(f"\n{'='*60}")
    print(f"  BEST STRATEGY: {best_name}")
    print(f"  Monthly Return: {best_monthly:.2f}%")
    print(f"  Sharpe Ratio:   {best_sharpe:.2f}")
    print(f"  Max Drawdown:   {best_dd:.2f}%")
    if best_monthly >= 10.0:
        print(f"  ✓ TARGET MET: ≥10% monthly return achieved!")
    else:
        print(f"  ✗ Gap to target: {10.0 - best_monthly:.2f}%")
    print("="*60)

    # Save best strategy trade log
    best_res = results[best_name]
    trades = best_res.trades_df
    if len(trades) > 0:
        trades.to_csv(os.path.join(output_dir, f"advanced_trades_{best_name}.csv"), index=False)
        print(f"\n  [Trade log: output/advanced_trades_{best_name}.csv]")

    print("\n[DONE]\n")
    return results, cdf


if __name__ == "__main__":
    main()
