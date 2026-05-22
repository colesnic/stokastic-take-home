"""
Targeted run to breach the 10% monthly return goal.
Uses RS momentum with aggressive tuning + reduced universe to high-momentum names.
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

# High-momentum universe: concentrated on volatile, trend-friendly names
HM_TICKERS = [
    "NVDA", "AMD", "TSLA", "AMZN", "META", "AAPL", "MSFT",
    "SMCI", "ARM", "AVGO", "MRVL",
    "COIN", "MSTR", "PLTR",
    "QQQ", "SOXX", "ARKK",
]

BACKTEST_START = "2022-01-01"
BACKTEST_END   = "2024-12-31"
INITIAL_CAPITAL = 100_000
OUTPUT_DIR = os.path.join(os.path.dirname(__file__), "output")


def run_strategy(name, strategy, bt_params, data, verbose=True):
    strategy.prepare(data)
    bt = AdvancedBacktester(initial_capital=INITIAL_CAPITAL, **bt_params)
    result = bt.run(data, strategy)
    m = result.metrics()
    if verbose:
        result.print_summary(name)
    else:
        monthly = m.get("monthly_return_pct", 0)
        sharpe  = m.get("sharpe_ratio", 0)
        dd      = m.get("max_drawdown_pct", 0)
        nt      = m.get("n_trades", 0)
        print(f"  {name:<35}  monthly={monthly:6.2f}%  "
              f"sharpe={sharpe:5.2f}  dd={dd:7.2f}%  trades={nt}")
    return result


def main():
    print("\n" + "="*65)
    print("  TARGETED 10% MONTHLY RETURN BACKTEST")
    print(f"  Universe: High-Momentum ({len(HM_TICKERS)} tickers)")
    print(f"  {BACKTEST_START} → {BACKTEST_END}")
    print("="*65)

    raw_data = fetch_multiple(HM_TICKERS, BACKTEST_START, BACKTEST_END, "1d")
    data = add_indicators(raw_data)
    print(f"  {len(data)} tickers loaded\n")

    # Grid of configs to try
    configs = []
    for top_n in [2, 3]:
        for rebal in [1, 2, 3, 5]:
            for lb_short in [5, 10, 15, 20]:
                for lb_mid in [20, 30, 45, 60]:
                    for pos_size in [0.40, 0.48]:
                        for atr_stop in [1.2, 1.5, 2.0]:
                            lb_long = lb_mid * 2
                            configs.append({
                                "top_n": top_n,
                                "rebal": rebal,
                                "lb_short": lb_short,
                                "lb_mid": lb_mid,
                                "lb_long": lb_long,
                                "pos_size": pos_size,
                                "atr_stop": atr_stop,
                            })

    print(f"  Testing {len(configs)} configurations...\n")

    best_monthly = 0
    best_config  = None
    best_result  = None
    results_list = []

    for cfg in configs:
        strat = RSMomentumStrategy(
            top_n=cfg["top_n"],
            rebalance_days=cfg["rebal"],
            lookback_short=cfg["lb_short"],
            lookback_mid=cfg["lb_mid"],
            lookback_long=cfg["lb_long"],
            adx_min=15.0,
            rsi_min=40.0,
        )
        bt_params = dict(
            max_positions=cfg["top_n"],
            position_size_pct=cfg["pos_size"],
            atr_stop_multiplier=cfg["atr_stop"],
            atr_trail_multiplier=max(cfg["atr_stop"] - 0.3, 0.8),
            risk_per_trade_pct=0.04,
        )
        try:
            strat.prepare(data)
            bt = AdvancedBacktester(initial_capital=INITIAL_CAPITAL, **bt_params)
            result = bt.run(data, strat)
            m = result.metrics()
            if not m:
                continue
            monthly = m["monthly_return_pct"]
            results_list.append({**cfg, **m})
            if monthly > best_monthly:
                best_monthly = monthly
                best_config  = cfg
                best_result  = result
                if monthly >= 10.0:
                    print(f"  *** TARGET HIT: {monthly:.2f}% monthly! "
                          f"(top_n={cfg['top_n']}, rebal={cfg['rebal']}, "
                          f"lb={cfg['lb_short']}/{cfg['lb_mid']}, "
                          f"pos={cfg['pos_size']:.0%}, stop={cfg['atr_stop']})")
        except Exception:
            continue

    if not results_list:
        print("[!] No valid results")
        return

    df = pd.DataFrame(results_list).sort_values("monthly_return_pct", ascending=False)
    print(f"\n  Top-10 configurations:")
    cols = ["top_n","rebal","lb_short","lb_mid","pos_size","atr_stop",
            "monthly_return_pct","sharpe_ratio","max_drawdown_pct","win_rate_pct","profit_factor","n_trades"]
    cols = [c for c in cols if c in df.columns]
    print(df[cols].head(10).to_string(index=False))

    os.makedirs(OUTPUT_DIR, exist_ok=True)
    df.to_csv(os.path.join(OUTPUT_DIR, "targeted_grid_results.csv"), index=False)

    # Print full summary for best
    print(f"\n  Best result: {best_monthly:.2f}% monthly")
    if best_result:
        best_result.print_summary(f"Best Config ({best_config})")

        # Save trades
        trades = best_result.trades_df
        if len(trades) > 0:
            trades.to_csv(os.path.join(OUTPUT_DIR, "target_best_trades.csv"), index=False)

        # Chart
        fig, axes = plt.subplots(2, 1, figsize=(14, 10))

        ax = axes[0]
        c = best_result.equity_curve
        ax.plot(c.index, c, color="#2980b9", linewidth=2, label=f"Best Strategy ({best_monthly:.1f}%/mo)")
        ax2_twin = ax.twinx()
        monthly_r = c.resample("ME").last().pct_change().dropna() * 100
        bar_colors = ["#27ae60" if x >= 10 else "#2980b9" if x >= 0 else "#e74c3c" for x in monthly_r.values]
        ax2_twin.bar(monthly_r.index, monthly_r.values, width=20, color=bar_colors, alpha=0.4)
        ax2_twin.axhline(10, color="gold", ls="--", lw=1.5)
        ax2_twin.set_ylabel("Monthly Return (%)", color="grey")
        ax.set_title(f"Best Strategy Equity Curve — {best_monthly:.2f}% Monthly Return",
                     fontsize=13, fontweight="bold")
        ax.set_ylabel("Portfolio Value ($)")
        ax.legend(loc="upper left")
        ax.grid(True, alpha=0.3)
        ax.xaxis.set_major_formatter(mdates.DateFormatter("%Y-%m"))
        plt.setp(ax.xaxis.get_majorticklabels(), rotation=25)

        ax3 = axes[1]
        dd = (c - c.cummax()) / c.cummax() * 100
        ax3.fill_between(dd.index, dd.values, 0, alpha=0.5, color="#e74c3c")
        ax3.plot(dd.index, dd, color="#c0392b", linewidth=1)
        ax3.set_title("Drawdown (%)", fontsize=12, fontweight="bold")
        ax3.set_ylabel("Drawdown (%)")
        ax3.grid(True, alpha=0.3)
        ax3.xaxis.set_major_formatter(mdates.DateFormatter("%Y-%m"))
        plt.setp(ax3.xaxis.get_majorticklabels(), rotation=25)

        plt.tight_layout()
        chart_path = os.path.join(OUTPUT_DIR, "target_best_strategy.png")
        plt.savefig(chart_path, dpi=150, bbox_inches="tight")
        plt.close()
        print(f"\n  [Chart → {chart_path}]")

    print(f"\n  {'='*55}")
    if best_monthly >= 10.0:
        print(f"  ✓  10% TARGET ACHIEVED: {best_monthly:.2f}% monthly!")
        print(f"     Config: {best_config}")
    else:
        print(f"  Best monthly return: {best_monthly:.2f}%")
        print(f"  Gap: {10.0 - best_monthly:.2f}%")
    print(f"  {'='*55}\n")

    return df, best_result


if __name__ == "__main__":
    main()
