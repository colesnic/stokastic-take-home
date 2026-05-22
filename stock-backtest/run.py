"""
run.py — Main entry point for the stock backtesting framework.

Data loading priority
---------------------
1. stock-backtest/data/*.csv  (real data committed to repo)
2. yfinance (works locally when network is available)
3. raw.githubusercontent.com CSV files (committed remote data)
4. Graceful exit with clear instructions if nothing works

Strategies run
--------------
  - RegimeAwareMomentum   (strategy_regime.py)
  - KellyMomentum         (strategy_regime.py)
  - VolatilityScaled      (strategy_regime.py)
  - RS_Momentum           (strategy_rs_momentum.py — proven winner)
  - HiMom_Concentrated    (optimize.py — breakout/trend)

Output
------
  Charts saved to stock-backtest/output/
  Final comparison table printed to stdout.
"""

import sys
import os
import warnings
warnings.filterwarnings("ignore")

# Ensure imports find siblings regardless of cwd
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

import numpy as np
import pandas as pd
import matplotlib
matplotlib.use("Agg")
import matplotlib.pyplot as plt
import matplotlib.dates as mdates

# ── Project imports ────────────────────────────────────────────────────────
from backtester_advanced import AdvancedBacktester
from strategy_rs_momentum import RSMomentumStrategy
from strategy_regime import (
    RegimeAwareMomentumStrategy,
    KellyMomentumStrategy,
    VolatilityScaledStrategy,
)
from optimize import add_indicators, HighMomentumStrategy
from risk_metrics import RiskReport

# ── Configuration ──────────────────────────────────────────────────────────
TICKERS = [
    "NVDA", "AMD", "TSLA", "AMZN", "META", "AAPL", "MSFT",
    "SMCI", "ARM", "AVGO", "MRVL",
    "COIN", "MSTR", "PLTR",
    "QQQ", "SOXX", "ARKK",
]

BACKTEST_START  = "2022-01-01"
BACKTEST_END    = "2024-12-31"
INITIAL_CAPITAL = 100_000

SCRIPT_DIR  = os.path.dirname(os.path.abspath(__file__))
DATA_DIR    = os.path.join(SCRIPT_DIR, "data")
OUTPUT_DIR  = os.path.join(SCRIPT_DIR, "output")

# Base URL for remote CSV files (branch-specific)
GITHUB_BASE = (
    "https://raw.githubusercontent.com/colesnic/stokastic-take-home/"
    "claude%2Fstock-backtesting-algo-IVqoW/stock-backtest/data"
)


# ── Data loading ───────────────────────────────────────────────────────────

def _from_local_csv(ticker: str) -> pd.DataFrame | None:
    """Load from data/<TICKER>.csv committed in the repo."""
    path = os.path.join(DATA_DIR, f"{ticker}.csv")
    if not os.path.exists(path):
        return None
    try:
        df = pd.read_csv(path, index_col=0, parse_dates=True)
        df.index = pd.to_datetime(df.index)
        if df.index.tz is not None:
            df.index = df.index.tz_localize(None)
        needed = {"Open", "High", "Low", "Close", "Volume"}
        if not needed.issubset(df.columns):
            return None
        df = df[list(needed)].dropna()
        return df if len(df) >= 50 else None
    except Exception:
        return None


def _from_yfinance(ticker: str, start: str, end: str) -> pd.DataFrame | None:
    """Attempt a yfinance download (requires live network)."""
    try:
        import io
        import yfinance as yf
        # Suppress yfinance's internal stderr chatter
        devnull = open(os.devnull, "w")
        old_stderr = sys.stderr
        sys.stderr = devnull
        try:
            t = yf.Ticker(ticker)
            df = t.history(start=start, end=end, interval="1d", auto_adjust=True)
        finally:
            sys.stderr = old_stderr
            devnull.close()
        if df is None or len(df) < 50:
            return None
        df.index = pd.to_datetime(df.index)
        if df.index.tz is not None:
            df.index = df.index.tz_localize(None)
        df = df[["Open", "High", "Low", "Close", "Volume"]].dropna()
        return df if len(df) >= 50 else None
    except Exception:
        return None


def _from_github(ticker: str) -> pd.DataFrame | None:
    """Download CSV from the GitHub raw URL (committed remote data)."""
    try:
        import urllib.request
        url = f"{GITHUB_BASE}/{ticker}.csv"
        with urllib.request.urlopen(url, timeout=8) as resp:
            import io
            content = resp.read().decode("utf-8")
        df = pd.read_csv(io.StringIO(content), index_col=0, parse_dates=True)
        df.index = pd.to_datetime(df.index)
        if df.index.tz is not None:
            df.index = df.index.tz_localize(None)
        needed = {"Open", "High", "Low", "Close", "Volume"}
        if not needed.issubset(df.columns):
            return None
        df = df[list(needed)].dropna()
        return df if len(df) >= 50 else None
    except Exception:
        return None


def load_data(tickers: list, start: str, end: str) -> tuple[dict, str]:
    """
    Try each data source in order.
    Returns (data_dict, source_description).
    Raises RuntimeError if no source works for any ticker.
    """
    os.makedirs(DATA_DIR, exist_ok=True)

    # ── Pass 1: local CSVs ─────────────────────────────────────────────
    local_data = {}
    for t in tickers:
        df = _from_local_csv(t)
        if df is not None:
            df = df.loc[start:end]
            if len(df) >= 50:
                local_data[t] = df
    if local_data:
        print(f"  [data] Loaded {len(local_data)}/{len(tickers)} tickers from local CSV files.")
        return local_data, "local CSV (data/)"

    # ── Pass 2: yfinance ──────────────────────────────────────────────
    print("  [data] No local CSVs found. Trying yfinance...")
    yf_data = {}
    yf_errors = []
    for t in tickers:
        df = _from_yfinance(t, start, end)
        if df is not None:
            yf_data[t] = df
        else:
            yf_errors.append(t)
    if yf_data:
        if yf_errors:
            print(f"  [data] yfinance: {len(yf_data)} loaded, {len(yf_errors)} failed: {yf_errors}")
        else:
            print(f"  [data] yfinance: all {len(yf_data)} tickers loaded.")
        return yf_data, "yfinance (live)"

    # ── Pass 3: GitHub raw ────────────────────────────────────────────
    print("  [data] yfinance unavailable. Trying GitHub raw CSV...")
    gh_data = {}
    gh_errors = []
    for t in tickers:
        df = _from_github(t)
        if df is not None:
            df = df.loc[start:end]
            if len(df) >= 50:
                gh_data[t] = df
        else:
            gh_errors.append(t)
    if gh_data:
        if gh_errors:
            print(f"  [data] GitHub: {len(gh_data)} loaded, {len(gh_errors)} failed: {gh_errors}")
        else:
            print(f"  [data] GitHub: all {len(gh_data)} tickers loaded.")
        return gh_data, "GitHub raw CSV"

    # ── All sources failed ────────────────────────────────────────────
    raise RuntimeError(
        "\n"
        "  NO DATA AVAILABLE — all three sources failed:\n"
        "    1. No files in stock-backtest/data/*.csv\n"
        "    2. yfinance returned HTTP 403 (blocked in this sandbox)\n"
        "    3. GitHub raw URL returned 404 (data not committed yet)\n"
        "\n"
        "  To fix:\n"
        "    Run locally:  python3 stock-backtest/download_real_data.py\n"
        "    Then commit:  git add stock-backtest/data/ && git commit -m 'add data'\n"
        "    Then push and re-run here.\n"
    )


# ── Strategy runner ────────────────────────────────────────────────────────

def run_strategy(name: str, strategy, backtester: AdvancedBacktester, data: dict):
    """Prepare strategy, run backtest, return (name, result, report)."""
    print(f"\n  Running: {name}...")
    strategy.prepare(data)
    result = backtester.run(data, strategy)
    report = RiskReport(result)
    return name, result, report


def build_strategies(data: dict) -> list:
    """
    Return list of (name, strategy, backtester) tuples.
    All strategies share the same initial capital and base cost model;
    position-sizing parameters vary per strategy.
    """
    common = dict(
        initial_capital=INITIAL_CAPITAL,
        commission=0.001,
        slippage=0.0005,
    )

    strategies = [
        # 1. Regime-Aware Momentum — conservative, adapts to market regime
        (
            "RegimeAwareMomentum",
            RegimeAwareMomentumStrategy(
                bull_top_n=3, neutral_top_n=2,
                rebalance_days=3,
                lb_short=10, lb_mid=20, lb_long=60,
                adx_min_bull=15.0, adx_min_neutral=20.0,
                rsi_min=40.0,
            ),
            AdvancedBacktester(
                **common,
                max_positions=3,
                position_size_pct=0.40,
                atr_stop_multiplier=1.5,
                atr_trail_multiplier=1.2,
                risk_per_trade_pct=0.03,
            ),
        ),

        # 2. Kelly Momentum — half-Kelly position sizing, bull-regime only
        (
            "KellyMomentum",
            KellyMomentumStrategy(
                top_n=3, rebalance_days=3,
                lb_short=10, lb_mid=20, lb_long=60,
                kelly_lookback=60,
                adx_min=15.0, rsi_min=40.0,
            ),
            AdvancedBacktester(
                **common,
                max_positions=3,
                position_size_pct=0.33,
                atr_stop_multiplier=1.5,
                atr_trail_multiplier=1.2,
                risk_per_trade_pct=0.03,
            ),
        ),

        # 3. Volatility-Scaled — inverse-vol position sizing, bull-regime only
        (
            "VolatilityScaled",
            VolatilityScaledStrategy(
                top_n=3, rebalance_days=3,
                lb_short=10, lb_mid=20, lb_long=60,
                vol_target=0.20, vol_lookback=20,
                adx_min=15.0, rsi_min=40.0,
            ),
            AdvancedBacktester(
                **common,
                max_positions=3,
                position_size_pct=0.35,
                atr_stop_multiplier=1.5,
                atr_trail_multiplier=1.2,
                risk_per_trade_pct=0.03,
            ),
        ),

        # 4. RS_Momentum — proven winner from run_winner.py
        (
            "RS_Momentum",
            RSMomentumStrategy(
                top_n=3, rebalance_days=2,
                lookback_short=10, lookback_mid=20, lookback_long=40,
                adx_min=15.0, rsi_min=40.0,
            ),
            AdvancedBacktester(
                **common,
                max_positions=3,
                position_size_pct=0.48,
                atr_stop_multiplier=1.2,
                atr_trail_multiplier=0.9,
                risk_per_trade_pct=0.04,
            ),
        ),

        # 5. HiMom_Concentrated — Donchian breakout + trend stack, concentrated
        (
            "HiMom_Concentrated",
            HighMomentumStrategy(
                dc_period=15,
                ema_fast=8, ema_slow=30, ema_trend=100,
                rsi_lo=40, rsi_hi=78,
                adx_min=20, vol_mult=1.0,
                macd_confirm=True,
            ),
            AdvancedBacktester(
                **common,
                max_positions=3,
                position_size_pct=0.45,
                atr_stop_multiplier=1.2,
                atr_trail_multiplier=0.9,
                risk_per_trade_pct=0.04,
            ),
        ),
    ]
    return strategies


# ── Charts ─────────────────────────────────────────────────────────────────

def save_equity_chart(results: list, output_dir: str):
    """Save overlaid equity curves for all strategies."""
    os.makedirs(output_dir, exist_ok=True)
    fig, axes = plt.subplots(2, 1, figsize=(14, 10))

    colors = ["#2980b9", "#27ae60", "#e67e22", "#8e44ad", "#e74c3c"]

    ax = axes[0]
    for (name, result, report), color in zip(results, colors):
        curve = result.equity_curve
        if len(curve) < 2:
            continue
        ax.plot(curve.index, curve, label=name, color=color, linewidth=1.5)
    ax.axhline(INITIAL_CAPITAL, color="k", lw=0.8, ls="--", label=f"Initial ${INITIAL_CAPITAL:,}")
    ax.set_title("Equity Curves — All Strategies", fontsize=13, fontweight="bold")
    ax.set_ylabel("Portfolio Value ($)")
    ax.yaxis.set_major_formatter(plt.FuncFormatter(lambda x, _: f"${x:,.0f}"))
    ax.legend(fontsize=9)
    ax.grid(True, alpha=0.3)
    ax.xaxis.set_major_formatter(mdates.DateFormatter("%Y-%m"))
    plt.setp(ax.xaxis.get_majorticklabels(), rotation=25)

    ax2 = axes[1]
    for (name, result, report), color in zip(results, colors):
        curve = result.equity_curve
        if len(curve) < 2:
            continue
        dd = (curve - curve.cummax()) / curve.cummax() * 100
        ax2.plot(dd.index, dd, label=name, color=color, linewidth=1.2, alpha=0.8)
    ax2.set_title("Drawdown — All Strategies", fontsize=12, fontweight="bold")
    ax2.set_ylabel("Drawdown (%)")
    ax2.axhline(-30, color="red", ls="--", lw=0.8, label="-30% limit")
    ax2.legend(fontsize=9)
    ax2.grid(True, alpha=0.3)
    ax2.xaxis.set_major_formatter(mdates.DateFormatter("%Y-%m"))
    plt.setp(ax2.xaxis.get_majorticklabels(), rotation=25)

    plt.tight_layout()
    path = os.path.join(output_dir, "all_strategies.png")
    plt.savefig(path, dpi=150, bbox_inches="tight")
    plt.close()
    return path


def save_monthly_chart(results: list, output_dir: str):
    """Save bar chart of monthly returns for each strategy."""
    os.makedirs(output_dir, exist_ok=True)
    n = len(results)
    fig, axes = plt.subplots(n, 1, figsize=(14, 3 * n), sharex=False)
    if n == 1:
        axes = [axes]

    for ax, (name, result, report) in zip(axes, results):
        curve = result.equity_curve
        if len(curve) < 10:
            ax.set_title(f"{name} — no data", fontsize=10)
            continue
        mr = curve.resample("ME").last().pct_change().dropna() * 100
        colors = ["#27ae60" if x >= 10 else "#2980b9" if x >= 0 else "#e74c3c"
                  for x in mr.values]
        ax.bar(mr.index, mr.values, color=colors, alpha=0.85, width=20)
        ax.axhline(10, color="gold", ls="--", lw=1.5, label="10% target")
        ax.axhline(0, color="k", lw=0.8)
        m = report._base
        title = (f"{name}  |  Monthly avg: {m.get('monthly_return_pct',0):.2f}%  "
                 f"Sharpe: {m.get('sharpe_ratio',0):.2f}  "
                 f"MaxDD: {m.get('max_drawdown_pct',0):.2f}%")
        ax.set_title(title, fontsize=10, fontweight="bold")
        ax.set_ylabel("Return (%)")
        ax.legend(fontsize=8)
        ax.grid(True, alpha=0.3, axis="y")
        ax.xaxis.set_major_formatter(mdates.DateFormatter("%Y-%m"))
        plt.setp(ax.xaxis.get_majorticklabels(), rotation=25)

    plt.tight_layout()
    path = os.path.join(output_dir, "monthly_returns_all.png")
    plt.savefig(path, dpi=150, bbox_inches="tight")
    plt.close()
    return path


# ── Comparison table ───────────────────────────────────────────────────────

def print_comparison_table(results: list):
    rows = []
    for name, result, report in results:
        b = report._base
        e = report._compute_extra()
        rows.append({
            "Strategy":     name,
            "Monthly%":     b.get("monthly_return_pct", 0),
            "Annual%":      b.get("annualized_return_pct", 0),
            "Sharpe":       b.get("sharpe_ratio", 0),
            "Sortino":      e.get("sortino_ratio", 0),
            "MaxDD%":       b.get("max_drawdown_pct", 0),
            "Calmar":       b.get("calmar_ratio", 0),
            "WinRate%":     b.get("win_rate_pct", 0),
            "PF":           b.get("profit_factor", 0),
            "Trades":       b.get("n_trades", 0),
            "Meets?":       "YES" if report.meets_target() else "no",
        })

    df = pd.DataFrame(rows).sort_values("Monthly%", ascending=False)

    W = 120
    print("\n" + "=" * W)
    print("  FINAL COMPARISON TABLE  (sorted by monthly return)")
    print("=" * W)
    # Header
    hdr = (f"  {'Strategy':<24} {'Monthly%':>8} {'Annual%':>8} "
           f"{'Sharpe':>7} {'Sortino':>8} {'MaxDD%':>8} "
           f"{'Calmar':>7} {'WinRate%':>9} {'PF':>6} {'Trades':>7} {'Meets?':>7}")
    print(hdr)
    print("  " + "-" * (W - 2))
    for _, r in df.iterrows():
        tag = "  <-- BEST" if r["Monthly%"] == df["Monthly%"].max() else ""
        print(
            f"  {r['Strategy']:<24} {r['Monthly%']:>8.2f} {r['Annual%']:>8.2f} "
            f"{r['Sharpe']:>7.2f} {r['Sortino']:>8.2f} {r['MaxDD%']:>8.2f} "
            f"{r['Calmar']:>7.2f} {r['WinRate%']:>9.2f} {r['PF']:>6.2f} "
            f"{r['Trades']:>7} {r['Meets?']:>7}{tag}"
        )
    print("=" * W)

    # Target legend
    print("\n  Targets:  Monthly>=10%  Sharpe>=1.5  MaxDD>=-30%  Calmar>=2.0  WinRate>=50%  PF>=1.5")
    print()
    return df


# ── Main ───────────────────────────────────────────────────────────────────

def main():
    print("\n" + "=" * 65)
    print("  STOCK BACKTESTING FRAMEWORK  —  run.py")
    print(f"  Period: {BACKTEST_START} to {BACKTEST_END}")
    print(f"  Initial Capital: ${INITIAL_CAPITAL:,}")
    print("=" * 65)

    # ── Load data ──────────────────────────────────────────────────────
    try:
        raw_data, source = load_data(TICKERS, BACKTEST_START, BACKTEST_END)
    except RuntimeError as exc:
        print(str(exc))
        sys.exit(1)

    print(f"  Data source: {source}")
    print(f"  Tickers loaded: {len(raw_data)}")

    # ── Add indicators ─────────────────────────────────────────────────
    print("\n  Adding technical indicators...")
    data = add_indicators(raw_data)
    print(f"  {len(data)} tickers survived indicator enrichment (need >50 rows)")

    if len(data) == 0:
        print("\n  ERROR: No tickers have enough history after indicator computation.")
        print("  Need at least 200 trading days. Check your data files.\n")
        sys.exit(1)

    # ── Build and run all strategies ───────────────────────────────────
    strategy_specs = build_strategies(data)
    all_results = []

    for name, strategy, backtester in strategy_specs:
        try:
            name_, result, report = run_strategy(name, strategy, backtester, data)
            report.print_full_report(name_)
            all_results.append((name_, result, report))
        except Exception as exc:
            print(f"\n  [ERROR] {name} failed: {exc}")
            import traceback
            traceback.print_exc()

    if not all_results:
        print("\n  No strategies completed successfully.")
        sys.exit(1)

    # ── Comparison table ───────────────────────────────────────────────
    comparison = print_comparison_table(all_results)

    # ── Charts ─────────────────────────────────────────────────────────
    os.makedirs(OUTPUT_DIR, exist_ok=True)
    try:
        p1 = save_equity_chart(all_results, OUTPUT_DIR)
        print(f"  [Chart] Equity curves  -> {p1}")
    except Exception as exc:
        print(f"  [warn] Equity chart failed: {exc}")

    try:
        p2 = save_monthly_chart(all_results, OUTPUT_DIR)
        print(f"  [Chart] Monthly returns -> {p2}")
    except Exception as exc:
        print(f"  [warn] Monthly chart failed: {exc}")

    # ── Save comparison CSV ────────────────────────────────────────────
    csv_path = os.path.join(OUTPUT_DIR, "run_comparison.csv")
    try:
        comparison.to_csv(csv_path, index=False)
        print(f"  [CSV]   Comparison table -> {csv_path}")
    except Exception:
        pass

    print("\n  Done.\n")


if __name__ == "__main__":
    main()
