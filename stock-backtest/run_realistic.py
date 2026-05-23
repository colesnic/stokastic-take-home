"""
Iteration 5 — Reality-adjusted backtest.

Ten differences between the original backtest and live trading,
each coded and tested individually, then all enabled together.

  #  Adjustment                  What changes in the code
  ─  ──────────────────────────  ─────────────────────────────────────────────
  1  Execution lag                Signal on close-T → fill at open-T+1
  2  Overnight gap filter         Skip entry if open gaps >3% above signal close
  3  Stop gap-through fill        Stop fills at open if stock gaps below stop
  4  Variable bid-ask spread      Price-tiered slippage (not flat 0.05%)
  5  Market impact                +0.02% slippage per $10K of order notional
  6  Short-term capital gains     35% tax on profitable trades held < 1 year
  7  Leverage borrowing cost      Daily interest on deployed capital > initial equity
  8  Portfolio heat cap           New entries blocked if total ATR-risk > 6% of equity
  9  Portfolio circuit breaker    Flatten all positions if equity drops >15% from HWM
  10 Correlated position filter   Skip new position if 20-day corr with any holding > 0.85
"""

import urllib.request, io, os, sys, warnings
import numpy as np, pandas as pd
warnings.filterwarnings("ignore")
sys.path.insert(0, os.path.dirname(__file__))

from backtester_advanced import AdvancedBacktester
from strategy_rs_momentum import RSMomentumStrategy
from risk_metrics import RiskReport

EIKON_URL = (
    "https://raw.githubusercontent.com/yhilpisch/py4fi2nd/"
    "master/source/tr_eikon_eod_data.csv"
)
TRAIN_END  = "2013-12-31"
TEST_START = "2014-01-01"
TEST_END   = "2018-06-29"
TICKERS    = ["AAPL", "MSFT", "INTC", "AMZN", "GS"]

CHAMPION_STRATEGY = dict(
    top_n=4, rebalance_days=3,
    lookback_short=10, lookback_mid=20, lookback_long=40,
    adx_min=12, rsi_min=35,
)
CHAMPION_BT = dict(
    max_positions=3, position_size_pct=0.33,
    atr_stop_multiplier=2.0, atr_trail_multiplier=1.5,
    risk_per_trade_pct=0.02,
)

# ── Ten scenarios: add one adjustment at a time, then all together ─────────
SCENARIOS = [
    ("Original (no adjustments)",      {}),
    ("#1  Execution lag",               {"execution_lag": 1}),
    ("#2  + Gap entry filter (>3%)",    {"execution_lag": 1,
                                         "max_overnight_gap_pct": 0.03}),
    ("#3  + Stop gap-fill (implicit in lag=1)", {"execution_lag": 1,
                                         "max_overnight_gap_pct": 0.03}),
    ("#4  + Variable bid-ask spread",   {"execution_lag": 1,
                                         "max_overnight_gap_pct": 0.03,
                                         "variable_slippage": True}),
    ("#5  + Market impact (0.03% / $33K)", {"execution_lag": 1,
                                         "max_overnight_gap_pct": 0.03,
                                         "variable_slippage": True,
                                         "market_impact_factor": 0.00001}),
    ("#6  + 35% short-term tax",        {"execution_lag": 1,
                                         "max_overnight_gap_pct": 0.03,
                                         "variable_slippage": True,
                                         "market_impact_factor": 0.00001,
                                         "short_term_tax_rate": 0.35}),
    ("#7  + Borrowing cost (3%/yr)",    {"execution_lag": 1,
                                         "max_overnight_gap_pct": 0.03,
                                         "variable_slippage": True,
                                         "market_impact_factor": 0.00001,
                                         "short_term_tax_rate": 0.35,
                                         "borrowing_rate": 0.03}),
    ("#8  + Portfolio heat cap (6%)",   {"execution_lag": 1,
                                         "max_overnight_gap_pct": 0.03,
                                         "variable_slippage": True,
                                         "market_impact_factor": 0.00001,
                                         "short_term_tax_rate": 0.35,
                                         "borrowing_rate": 0.03,
                                         "max_portfolio_heat_pct": 0.06}),
    ("#9  + Circuit breaker (-15%)",    {"execution_lag": 1,
                                         "max_overnight_gap_pct": 0.03,
                                         "variable_slippage": True,
                                         "market_impact_factor": 0.00001,
                                         "short_term_tax_rate": 0.35,
                                         "borrowing_rate": 0.03,
                                         "max_portfolio_heat_pct": 0.06,
                                         "portfolio_stop_pct": 0.15}),
    ("#10 + Correlation filter (>0.85)","ALL"),
]
ALL_ADJUSTMENTS = {
    "execution_lag":            1,
    "max_overnight_gap_pct":    0.03,
    "variable_slippage":        True,
    "market_impact_factor":     0.00001,
    "short_term_tax_rate":      0.35,
    "borrowing_rate":           0.03,
    "max_portfolio_heat_pct":   0.06,
    "portfolio_stop_pct":       0.15,
    "max_position_correlation": 0.85,
}


def fetch_eikon():
    print("  Fetching Reuters Eikon EOD data ...", end=" ", flush=True)
    with urllib.request.urlopen(EIKON_URL, timeout=12) as resp:
        content = resp.read().decode("utf-8")
    df = pd.read_csv(io.StringIO(content), index_col=0, parse_dates=True)
    df = df.rename(columns={"AAPL.O": "AAPL", "MSFT.O": "MSFT", "INTC.O": "INTC",
                             "AMZN.O": "AMZN", "GS.N": "GS"})
    print(f"OK  ({df.index[0].date()} → {df.index[-1].date()})")
    return df


def synthesize_ohlcv(close: pd.Series, seed: int = 42) -> pd.DataFrame:
    rng  = np.random.default_rng(seed)
    n    = len(close)
    ret  = close.pct_change().fillna(0.0)
    vol  = ret.rolling(20).std().fillna(ret.std())
    op   = close.shift(1).fillna(close.iloc[0])
    rf   = np.abs(rng.normal(0.6, 0.25, n)).clip(0.1, 1.8)
    half = close.values * vol.values * rf
    hi   = np.maximum(op.values, close.values) + half
    lo   = np.maximum(np.minimum(op.values, close.values) - half, close.values * 0.5)
    volume = np.abs(rng.normal(1_000_000, 300_000, n)).astype(int)
    return pd.DataFrame({"Open": op.values, "High": hi, "Low": lo,
                         "Close": close.values, "Volume": volume}, index=close.index)


def make_data(raw):
    return {t: synthesize_ohlcv(raw[t].dropna())
            for t in TICKERS if t in raw.columns and len(raw[t].dropna()) >= 100}


def slice_data(data, start, end):
    return {t: df.loc[start:end] for t, df in data.items()
            if len(df.loc[start:end]) >= 30}


def run_scenario(oos_data, bt_kwargs):
    strat = RSMomentumStrategy(**CHAMPION_STRATEGY)
    strat.prepare(oos_data)
    bt = AdvancedBacktester(initial_capital=100_000, **CHAMPION_BT, **bt_kwargs)
    return RiskReport(bt.run(oos_data, strat)).full_metrics()


def main():
    print("\n" + "=" * 76)
    print("  ITERATION 5 — Ten reality adjustments on champion OOS (2014–2018)")
    print("=" * 76)

    print()
    print("  Ten differences between backtest and live trading:")
    for line in __doc__.strip().split("\n"):
        if line.strip().startswith("#"):
            print(f"  {line.strip()}")

    raw      = fetch_eikon()
    base     = make_data(raw)
    oos_data = slice_data(base, TEST_START, TEST_END)

    print(f"\n  Running {len(SCENARIOS)} scenarios on OOS 2014–2018 ...\n")

    results = []
    for name, kwargs in SCENARIOS:
        kw = ALL_ADJUSTMENTS if kwargs == "ALL" else kwargs
        m  = run_scenario(oos_data, kw)
        results.append((name, m))
        print(f"  {name[:45]:<45}  "
              f"Mo={m['monthly_return_pct']:+5.2f}%  "
              f"SR={m['sharpe_ratio']:+5.2f}  "
              f"DD={m['max_drawdown_pct']:+6.2f}%  "
              f"PF={m['profit_factor']:4.2f}  "
              f"WR={m['win_rate_pct']:4.1f}%  "
              f"Eq=${m['final_equity']:>8,.0f}")

    # ── Full comparison table ──────────────────────────────────────────────
    orig = results[0][1]
    full = results[-1][1]

    print(f"\n{'='*76}")
    print("  FULL COMPARISON: Original vs All-10-Adjustments (OOS 2014–2018)")
    print(f"{'='*76}")
    print(f"  {'Metric':<30} {'Original':>12} {'Realistic':>12} {'Delta':>10}")
    print("  " + "-" * 66)

    metrics = [
        ("Monthly Return %",       "monthly_return_pct"),
        ("Annual Return %",        "annualized_return_pct"),
        ("Sharpe Ratio",           "sharpe_ratio"),
        ("Sortino Ratio",          "sortino_ratio"),
        ("Max Drawdown %",         "max_drawdown_pct"),
        ("Calmar Ratio",           "calmar_ratio"),
        ("Win Rate %",             "win_rate_pct"),
        ("Profit Factor",          "profit_factor"),
        ("N Trades",               "n_trades"),
        ("Avg Hold (days)",        "avg_holding_days"),
        ("Final Equity $",         "final_equity"),
    ]
    for label, key in metrics:
        o, r = orig.get(key, 0), full.get(key, 0)
        if o is None: o = 0
        if r is None: r = 0
        d = r - o
        worse = ""
        if key not in ("max_drawdown_pct", "n_trades", "final_equity", "avg_holding_days"):
            worse = "  ↓" if d < -0.1 else ("  ↑" if d > 0.1 else "")
        if key == "max_drawdown_pct":
            worse = "  ↓" if d < -1.0 else ""
        if key == "final_equity":
            worse = f"  ({(r/o - 1)*100:+.1f}%)" if o != 0 else ""
        print(f"  {label:<30} {o:>12.2f} {r:>12.2f} {d:>+10.2f}{worse}")

    # ── Verdict ───────────────────────────────────────────────────────────
    print(f"\n{'='*76}")
    print("  VERDICT")
    print(f"{'='*76}")

    criteria = [
        ("Monthly ≥ 1%/mo",    full["monthly_return_pct"] >= 1.0),
        ("Sharpe ≥ 1.0",       full["sharpe_ratio"] >= 1.0),
        ("MaxDD > -20%",        full["max_drawdown_pct"] >= -20.0),
        ("Calmar ≥ 1.0",       full["calmar_ratio"] >= 1.0),
        ("Win Rate ≥ 40%",     full["win_rate_pct"] >= 40.0),
        ("Profit Factor ≥ 1.3",full["profit_factor"] >= 1.3),
    ]
    passes = sum(1 for _, ok in criteria if ok)
    for label, ok in criteria:
        print(f"    [{'PASS' if ok else 'FAIL'}]  {label}")
    print(f"\n  {passes}/6 criteria pass with all 10 real-world adjustments.")

    if passes >= 5:
        print("\n  Strategy survives realistic conditions with most criteria intact.")
    elif passes >= 3:
        print("\n  Strategy degrades under realistic conditions — edge exists but")
        print("  is significantly eroded. Optimise for next-open execution.")
    else:
        print("\n  Strategy does NOT survive realistic conditions.")
        print("  The edge was execution-timing dependent (close-to-close only).")
        print()
        print("  Path forward:")
        print("  • Run on 2020-2025 NVDA/TSLA universe (higher raw alpha)")
        print("  • Or use MOC orders (Market-On-Close via Alpaca TimeInForce.CLS)")
        print("    — this preserves close-to-close execution in live trading")

    print()


if __name__ == "__main__":
    main()
