"""
Main runner: fetch data, run all strategies, print results, generate charts.
"""
import sys
import os
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
from indicators import ema, rsi, macd, bollinger_bands, atr, adx, donchian, stochastic
from strategies import (
    MomentumBreakoutStrategy,
    MACDMomentumStrategy,
    RSIMeanReversionStrategy,
    SqueezeBreakoutStrategy,
    TrendFollowingStrategy,
    BollingerMomentumStrategy,
    ComboStrategy,
)
from backtester import Backtester, BacktestResult

# ── Universe ──────────────────────────────────────────────────────────────────
# Volatile, high-momentum stocks that respond well to technical strategies.
# Focus on liquid large/mid caps + sector ETFs.
TICKERS = [
    # Tech momentum
    "NVDA", "AMD", "AAPL", "MSFT", "META", "GOOGL", "TSLA", "AMZN",
    # Semis / growth
    "SMCI", "ARM", "AVGO", "MRVL",
    # ETFs (sector momentum)
    "QQQ", "SOXX", "ARKK", "XLK", "XLY",
    # Biotech (high vol)
    "MRNA", "BIIB",
    # High beta
    "COIN", "MSTR", "PLTR",
]

# ── Config ────────────────────────────────────────────────────────────────────
BACKTEST_START = "2022-01-01"
BACKTEST_END   = "2024-12-31"   # 3 years of data
INITIAL_CAPITAL = 100_000


def add_indicators(data: dict) -> dict:
    """Precompute all indicators and add them to each DataFrame."""
    enriched = {}
    for ticker, df in data.items():
        d = df.copy()
        c, h, l, v = d["Close"], d["High"], d["Low"], d["Volume"]
        d["ema10"]  = ema(c, 10)
        d["ema20"]  = ema(c, 20)
        d["ema50"]  = ema(c, 50)
        d["ema100"] = ema(c, 100)
        d["ema200"] = ema(c, 200)
        d["rsi14"]  = rsi(c, 14)
        d["atr14"]  = atr(h, l, c, 14)
        d["adx14"]  = adx(h, l, c, 14)
        macd_line, sig_line, hist = macd(c)
        d["macd"], d["macd_signal"], d["macd_hist"] = macd_line, sig_line, hist
        d["bb_upper"], d["bb_mid"], d["bb_lower"] = bollinger_bands(c, 20, 2.0)
        d["dc_upper"], d["dc_mid"], d["dc_lower"] = donchian(h, l, 20)
        d["stoch_k"], d["stoch_d"] = stochastic(h, l, c)
        d["vol_sma20"] = v.rolling(20).mean()
        d.dropna(inplace=True)
        if len(d) > 50:
            enriched[ticker] = d
    return enriched


def run_strategy(name: str, strategy, data: dict, bt: Backtester) -> BacktestResult:
    print(f"\n[Running] {name}...")
    strategy.prepare(data)
    result = bt.run(data, strategy)
    result.print_summary(name)
    return result


def plot_results(results: dict, output_dir: str):
    os.makedirs(output_dir, exist_ok=True)

    # Equity curves
    fig, ax = plt.subplots(figsize=(14, 7))
    colors = plt.cm.tab10.colors
    for i, (name, res) in enumerate(results.items()):
        curve = res.equity_curve
        if len(curve) < 2:
            continue
        normalized = curve / curve.iloc[0] * 100
        ax.plot(curve.index, normalized, label=name, color=colors[i % 10], linewidth=1.5)

    ax.axhline(100, color="black", linestyle="--", linewidth=0.8, alpha=0.5, label="Breakeven")
    ax.set_title("Strategy Equity Curves (Base=100)", fontsize=14, fontweight="bold")
    ax.set_xlabel("Date")
    ax.set_ylabel("Equity (Normalized)")
    ax.legend(fontsize=9)
    ax.grid(True, alpha=0.3)
    ax.xaxis.set_major_formatter(mdates.DateFormatter("%Y-%m"))
    plt.xticks(rotation=30)
    plt.tight_layout()
    plt.savefig(os.path.join(output_dir, "equity_curves.png"), dpi=150)
    plt.close()

    # Monthly returns heatmap for best strategy
    best_name = max(results, key=lambda n: results[n].metrics().get("monthly_return_pct", -999))
    best = results[best_name]
    monthly = best.equity_curve.resample("ME").last().pct_change().dropna() * 100

    if len(monthly) > 0:
        fig2, ax2 = plt.subplots(figsize=(14, 5))
        colors_monthly = ["green" if x >= 0 else "red" for x in monthly.values]
        ax2.bar(monthly.index, monthly.values, color=colors_monthly, alpha=0.75, width=20)
        ax2.axhline(10, color="blue", linestyle="--", linewidth=1, label="10% Target")
        ax2.axhline(0, color="black", linewidth=0.8)
        ax2.set_title(f"Monthly Returns — {best_name}", fontsize=13, fontweight="bold")
        ax2.set_ylabel("Monthly Return (%)")
        ax2.set_xlabel("Month")
        ax2.legend()
        ax2.grid(True, alpha=0.3, axis="y")
        plt.xticks(rotation=30)
        plt.tight_layout()
        plt.savefig(os.path.join(output_dir, "monthly_returns.png"), dpi=150)
        plt.close()

    # Drawdown chart
    fig3, ax3 = plt.subplots(figsize=(14, 5))
    for i, (name, res) in enumerate(results.items()):
        curve = res.equity_curve
        if len(curve) < 2:
            continue
        dd = (curve - curve.cummax()) / curve.cummax() * 100
        ax3.plot(dd.index, dd, label=name, color=colors[i % 10], linewidth=1.2)
    ax3.set_title("Drawdown (%)", fontsize=13, fontweight="bold")
    ax3.set_ylabel("Drawdown (%)")
    ax3.set_xlabel("Date")
    ax3.legend(fontsize=9)
    ax3.grid(True, alpha=0.3)
    ax3.xaxis.set_major_formatter(mdates.DateFormatter("%Y-%m"))
    plt.xticks(rotation=30)
    plt.tight_layout()
    plt.savefig(os.path.join(output_dir, "drawdowns.png"), dpi=150)
    plt.close()

    print(f"\n[Charts saved to {output_dir}]")


def comparison_table(results: dict):
    rows = []
    for name, res in results.items():
        m = res.metrics()
        m["strategy"] = name
        rows.append(m)
    df = pd.DataFrame(rows).set_index("strategy")
    cols = ["monthly_return_pct", "annualized_return_pct", "sharpe_ratio",
            "max_drawdown_pct", "calmar_ratio", "win_rate_pct",
            "profit_factor", "n_trades"]
    df = df[[c for c in cols if c in df.columns]]
    print("\n" + "="*80)
    print("STRATEGY COMPARISON TABLE")
    print("="*80)
    print(df.to_string())
    return df


def main():
    print(f"\n{'='*60}")
    print("  STOCK BACKTESTING ENGINE")
    print(f"  Period: {BACKTEST_START} → {BACKTEST_END}")
    print(f"  Capital: ${INITIAL_CAPITAL:,}")
    print(f"  Universe: {len(TICKERS)} tickers")
    print(f"{'='*60}")

    # ── 1. Fetch Data ─────────────────────────────────────────────────────────
    print("\n[Step 1] Fetching data...")
    raw_data = fetch_multiple(TICKERS, BACKTEST_START, BACKTEST_END, "1d")
    print(f"  Loaded {len(raw_data)} tickers")

    # ── 2. Add Indicators ─────────────────────────────────────────────────────
    print("\n[Step 2] Computing indicators...")
    data = add_indicators(raw_data)
    print(f"  {len(data)} tickers after indicator computation")

    # ── 3. Run Strategies ─────────────────────────────────────────────────────
    print("\n[Step 3] Running backtests...")

    # More aggressive parameters targeting 10% monthly
    bt_aggressive = Backtester(
        initial_capital=INITIAL_CAPITAL,
        commission=0.001,
        slippage=0.0005,
        max_positions=5,
        position_size_pct=0.20,
        stop_loss_pct=0.06,
        take_profit_pct=0.20,
    )

    bt_tight = Backtester(
        initial_capital=INITIAL_CAPITAL,
        commission=0.001,
        slippage=0.0005,
        max_positions=8,
        position_size_pct=0.12,
        stop_loss_pct=0.04,
        take_profit_pct=0.12,
    )

    results = {}

    results["MomentumBreakout"] = run_strategy(
        "MomentumBreakout", MomentumBreakoutStrategy(), data, bt_aggressive
    )
    results["MACD_Momentum"] = run_strategy(
        "MACD_Momentum", MACDMomentumStrategy(), data, bt_aggressive
    )
    results["RSI_MeanReversion"] = run_strategy(
        "RSI_MeanReversion", RSIMeanReversionStrategy(), data, bt_tight
    )
    results["SqueezeBreakout"] = run_strategy(
        "SqueezeBreakout", SqueezeBreakoutStrategy(), data, bt_aggressive
    )
    results["TrendFollowing"] = run_strategy(
        "TrendFollowing", TrendFollowingStrategy(), data, bt_aggressive
    )
    results["BollingerMomentum"] = run_strategy(
        "BollingerMomentum", BollingerMomentumStrategy(), data, bt_aggressive
    )
    results["Combo_2of4"] = run_strategy(
        "Combo_2of4", ComboStrategy(), data, bt_aggressive
    )

    # ── 4. Comparison ─────────────────────────────────────────────────────────
    cdf = comparison_table(results)

    # ── 5. Find Best ──────────────────────────────────────────────────────────
    if "monthly_return_pct" not in cdf.columns or cdf.empty:
        print("\n[!] No metrics computed — no data loaded.")
        return results, cdf

    best_name = cdf["monthly_return_pct"].idxmax()
    best_monthly = cdf.loc[best_name, "monthly_return_pct"]
    print(f"\n[Best Strategy] {best_name} → {best_monthly:.2f}% monthly return")
    if best_monthly >= 10.0:
        print("  ✓ TARGET MET: ≥10% monthly return achieved!")
    else:
        print(f"  ✗ Below target (gap: {10.0 - best_monthly:.2f}%)")

    # ── 6. Charts ─────────────────────────────────────────────────────────────
    print("\n[Step 4] Generating charts...")
    output_dir = os.path.join(os.path.dirname(__file__), "output")
    plot_results(results, output_dir)

    # ── 7. Save trade log ─────────────────────────────────────────────────────
    best_result = results[best_name]
    trades = best_result.trades_df
    if len(trades) > 0:
        trades_path = os.path.join(output_dir, f"trades_{best_name}.csv")
        trades.to_csv(trades_path, index=False)
        print(f"[Trade log saved to {trades_path}]")

    # ── 8. Summary CSV ────────────────────────────────────────────────────────
    cdf.to_csv(os.path.join(output_dir, "strategy_comparison.csv"))
    print(f"[Comparison table saved]")

    print(f"\n{'='*60}")
    print("  BACKTEST COMPLETE")
    print(f"{'='*60}\n")

    return results, cdf


if __name__ == "__main__":
    main()
