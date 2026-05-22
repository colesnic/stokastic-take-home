"""
Final comprehensive backtest: all strategies including RS momentum variants.
Produces the definitive comparison with charts and trade logs.
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
from optimize import HighMomentumStrategy, add_indicators
from strategy_rs_momentum import RSMomentumStrategy, DualMomentumStrategy, HybridMomentumStrategy
from backtester_advanced import AdvancedBacktester

TICKERS = [
    "NVDA", "AMD", "AAPL", "MSFT", "META", "GOOGL", "TSLA", "AMZN",
    "SMCI", "ARM", "AVGO", "MRVL", "QQQ", "SOXX", "ARKK", "XLK", "XLY",
    "MRNA", "BIIB", "COIN", "MSTR", "PLTR",
]

BACKTEST_START = "2022-01-01"
BACKTEST_END   = "2024-12-31"
INITIAL_CAPITAL = 100_000
OUTPUT_DIR = os.path.join(os.path.dirname(__file__), "output")


def run_strategy(name, strategy, bt_params, data):
    print(f"  [{name}] ...", end="", flush=True)
    strategy.prepare(data)
    bt = AdvancedBacktester(initial_capital=INITIAL_CAPITAL, **bt_params)
    result = bt.run(data, strategy)
    m = result.metrics()
    monthly = m.get("monthly_return_pct", 0)
    sharpe  = m.get("sharpe_ratio", 0)
    dd      = m.get("max_drawdown_pct", 0)
    trades  = m.get("n_trades", 0)
    print(f"  monthly={monthly:.2f}%  sharpe={sharpe:.2f}  dd={dd:.2f}%  trades={trades}")
    return result


def make_charts(results, output_dir):
    os.makedirs(output_dir, exist_ok=True)
    colors = plt.cm.Set1.colors + plt.cm.Set2.colors

    fig, axes = plt.subplots(3, 1, figsize=(16, 18))

    ax = axes[0]
    for i, (name, res) in enumerate(results.items()):
        c = res.equity_curve
        if len(c) < 2: continue
        norm = c / c.iloc[0] * 100
        ax.plot(c.index, norm, label=name, color=colors[i % len(colors)], linewidth=1.5)
    ax.axhline(100, color="k", lw=0.8, ls="--")
    ax.set_title("Equity Curves — All Strategies (Base=100)", fontsize=13, fontweight="bold")
    ax.set_ylabel("Equity")
    ax.legend(fontsize=7, ncol=3)
    ax.grid(True, alpha=0.3)
    ax.xaxis.set_major_formatter(mdates.DateFormatter("%Y-%m"))
    plt.setp(ax.xaxis.get_majorticklabels(), rotation=25)

    # Monthly returns bar chart — top 3 strategies
    ax2 = axes[1]
    top3 = sorted(results.items(),
                  key=lambda x: x[1].metrics().get("monthly_return_pct", -999),
                  reverse=True)[:3]
    bar_width = 18
    offsets = [-18, 0, 18]
    for j, (name, res) in enumerate(top3):
        monthly = res.equity_curve.resample("ME").last().pct_change().dropna() * 100
        ax2.bar(monthly.index + pd.Timedelta(days=offsets[j]),
                monthly.values, width=bar_width,
                label=name, color=colors[j], alpha=0.75)
    ax2.axhline(10, color="gold", lw=2, ls="--", label="10% Target")
    ax2.axhline(0, color="k", lw=0.8)
    ax2.set_title("Monthly Returns — Top 3 Strategies", fontsize=13, fontweight="bold")
    ax2.set_ylabel("Monthly Return (%)")
    ax2.legend(fontsize=9)
    ax2.grid(True, alpha=0.3, axis="y")
    ax2.xaxis.set_major_formatter(mdates.DateFormatter("%Y-%m"))
    plt.setp(ax2.xaxis.get_majorticklabels(), rotation=25)

    # Drawdown
    ax3 = axes[2]
    for i, (name, res) in enumerate(results.items()):
        c = res.equity_curve
        if len(c) < 2: continue
        dd = (c - c.cummax()) / c.cummax() * 100
        ax3.plot(dd.index, dd, label=name, color=colors[i % len(colors)], linewidth=1.2)
    ax3.set_title("Drawdown (%)", fontsize=13, fontweight="bold")
    ax3.set_ylabel("Drawdown (%)")
    ax3.legend(fontsize=7, ncol=3)
    ax3.grid(True, alpha=0.3)
    ax3.xaxis.set_major_formatter(mdates.DateFormatter("%Y-%m"))
    plt.setp(ax3.xaxis.get_majorticklabels(), rotation=25)

    plt.tight_layout()
    path = os.path.join(output_dir, "final_equity_curves.png")
    plt.savefig(path, dpi=150, bbox_inches="tight")
    plt.close()
    print(f"\n  [Chart saved → {path}]")

    # Scatter: monthly return vs sharpe
    fig2, ax4 = plt.subplots(figsize=(10, 7))
    for i, (name, res) in enumerate(results.items()):
        m = res.metrics()
        if not m: continue
        ax4.scatter(m["sharpe_ratio"], m["monthly_return_pct"],
                    s=max(m["n_trades"] * 2, 20), color=colors[i % len(colors)], alpha=0.85)
        ax4.annotate(name, (m["sharpe_ratio"], m["monthly_return_pct"]),
                     fontsize=7, ha="left", va="bottom")
    ax4.axhline(10, color="gold", ls="--", lw=1.5, label="10% Monthly Target")
    ax4.axvline(1.0, color="grey", ls="--", lw=1, label="Sharpe=1.0")
    ax4.set_xlabel("Sharpe Ratio")
    ax4.set_ylabel("Monthly Return (%)")
    ax4.set_title("Risk-Return Scatter (bubble size = # trades)", fontsize=12, fontweight="bold")
    ax4.legend()
    ax4.grid(True, alpha=0.3)
    plt.tight_layout()
    scatter_path = os.path.join(output_dir, "risk_return_scatter.png")
    plt.savefig(scatter_path, dpi=150)
    plt.close()
    print(f"  [Scatter saved → {scatter_path}]")


def main():
    print("\n" + "="*65)
    print("  FINAL COMPREHENSIVE BACKTEST")
    print(f"  {BACKTEST_START} → {BACKTEST_END}  |  Capital: ${INITIAL_CAPITAL:,}")
    print("="*65)

    raw_data = fetch_multiple(TICKERS, BACKTEST_START, BACKTEST_END, "1d")
    data = add_indicators(raw_data)
    print(f"\n  {len(data)} tickers loaded\n")

    # Common backtester kwargs
    bt_concentrated = dict(max_positions=2, position_size_pct=0.48,
                           atr_stop_multiplier=1.5, atr_trail_multiplier=1.2,
                           risk_per_trade_pct=0.05)
    bt_medium = dict(max_positions=3, position_size_pct=0.33,
                     atr_stop_multiplier=2.0, atr_trail_multiplier=1.5,
                     risk_per_trade_pct=0.03)
    bt_balanced = dict(max_positions=4, position_size_pct=0.25,
                       atr_stop_multiplier=2.5, atr_trail_multiplier=2.0,
                       risk_per_trade_pct=0.025)

    results = {}

    # ── Breakout variants ──────────────────────────────────────────────────
    results["HiMom_Concentrated"] = run_strategy(
        "HiMom_Concentrated",
        HighMomentumStrategy(dc_period=10, ema_fast=5, ema_slow=20, ema_trend=50,
                             rsi_lo=50, rsi_hi=80, adx_min=25, vol_mult=1.0, macd_confirm=True),
        bt_concentrated, data
    )

    results["HiMom_Medium"] = run_strategy(
        "HiMom_Medium",
        HighMomentumStrategy(dc_period=15, ema_fast=8, ema_slow=30, ema_trend=100,
                             rsi_lo=48, rsi_hi=78, adx_min=22, vol_mult=1.0, macd_confirm=True),
        bt_medium, data
    )

    results["HiMom_Balanced"] = run_strategy(
        "HiMom_Balanced",
        HighMomentumStrategy(dc_period=20, ema_fast=10, ema_slow=50, ema_trend=200,
                             rsi_lo=45, rsi_hi=76, adx_min=20, vol_mult=1.1, macd_confirm=True),
        bt_balanced, data
    )

    # ── Relative Strength Momentum ─────────────────────────────────────────
    results["RS_Momentum_Top2"] = run_strategy(
        "RS_Momentum_Top2",
        RSMomentumStrategy(top_n=2, rebalance_days=5, adx_min=18, rsi_min=45),
        bt_concentrated, data
    )
    results["RS_Momentum_Top3"] = run_strategy(
        "RS_Momentum_Top3",
        RSMomentumStrategy(top_n=3, rebalance_days=5, adx_min=18, rsi_min=45),
        bt_medium, data
    )
    results["RS_Momentum_Fast"] = run_strategy(
        "RS_Momentum_Fast",
        RSMomentumStrategy(top_n=2, rebalance_days=3, lookback_short=10, lookback_mid=30,
                           lookback_long=60, adx_min=15, rsi_min=40),
        bt_concentrated, data
    )

    # ── Dual Momentum ─────────────────────────────────────────────────────
    results["Dual_Momentum_Top2"] = run_strategy(
        "Dual_Momentum_Top2",
        DualMomentumStrategy(top_n=2, rebalance_days=21, momentum_period=120),
        bt_concentrated, data
    )
    results["Dual_Momentum_Top3"] = run_strategy(
        "Dual_Momentum_Top3",
        DualMomentumStrategy(top_n=3, rebalance_days=10, momentum_period=60),
        bt_medium, data
    )

    # ── Hybrid ────────────────────────────────────────────────────────────
    results["Hybrid_Top2"] = run_strategy(
        "Hybrid_Top2",
        HybridMomentumStrategy(top_n=2, rebalance_days=3, dc_period=10,
                               adx_min=22, rsi_lo=50, vol_mult=1.0),
        bt_concentrated, data
    )
    results["Hybrid_Top3"] = run_strategy(
        "Hybrid_Top3",
        HybridMomentumStrategy(top_n=3, rebalance_days=5, dc_period=15,
                               adx_min=22, rsi_lo=45, vol_mult=1.0),
        bt_medium, data
    )

    # ── Build comparison ───────────────────────────────────────────────────
    rows = []
    for name, res in results.items():
        m = res.metrics()
        if m:
            m["strategy"] = name
            rows.append(m)

    cdf = pd.DataFrame(rows).set_index("strategy")
    cols = ["monthly_return_pct", "annualized_return_pct", "sharpe_ratio",
            "max_drawdown_pct", "calmar_ratio", "win_rate_pct",
            "profit_factor", "n_trades", "final_equity"]
    cdf = cdf[[c for c in cols if c in cdf.columns]].sort_values("monthly_return_pct", ascending=False)

    print("\n" + "="*95)
    print("FINAL STRATEGY COMPARISON")
    print("="*95)
    print(cdf.to_string())

    os.makedirs(OUTPUT_DIR, exist_ok=True)
    cdf.to_csv(os.path.join(OUTPUT_DIR, "final_comparison.csv"))

    make_charts(results, OUTPUT_DIR)

    best_name    = cdf.index[0]
    best_monthly = cdf.loc[best_name, "monthly_return_pct"]
    best_sharpe  = cdf.loc[best_name, "sharpe_ratio"]
    best_dd      = cdf.loc[best_name, "max_drawdown_pct"]
    best_equity  = cdf.loc[best_name, "final_equity"]

    # Save best trade log
    best_res = results[best_name]
    trades = best_res.trades_df
    if len(trades) > 0:
        trades.to_csv(os.path.join(OUTPUT_DIR, f"best_trades_{best_name}.csv"), index=False)

    print(f"\n{'='*65}")
    print(f"  WINNER: {best_name}")
    print(f"  Monthly Return:    {best_monthly:.2f}%")
    print(f"  Annualized Return: {cdf.loc[best_name,'annualized_return_pct']:.2f}%")
    print(f"  Sharpe Ratio:      {best_sharpe:.2f}")
    print(f"  Max Drawdown:      {best_dd:.2f}%")
    print(f"  Final Equity:      ${best_equity:,.2f}  (started ${INITIAL_CAPITAL:,})")
    if best_monthly >= 10.0:
        print(f"\n  ✓  TARGET MET: ≥10% monthly return achieved!")
    else:
        print(f"\n  ✗  Gap to 10% target: {10.0 - best_monthly:.2f}%")
    print("="*65 + "\n")

    return results, cdf


if __name__ == "__main__":
    main()
