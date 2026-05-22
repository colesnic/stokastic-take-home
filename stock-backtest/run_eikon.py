"""
Real-data backtest using Reuters Eikon EOD data (AAPL/MSFT/INTC/AMZN/GS/SPY, 2010-2018).
Fetched directly from accessible GitHub raw URL — no API key needed.

Walk-forward split:
  In-sample  (optimize):  2010-01-04 → 2013-12-31
  Out-of-sample (blind):  2014-01-01 → 2018-06-29

OHLCV synthesis: Close prices are real. High/Low generated from rolling vol.
"""

import urllib.request
import io
import os
import sys
import numpy as np
import pandas as pd
import warnings
warnings.filterwarnings("ignore")

sys.path.insert(0, os.path.dirname(__file__))

from backtester_advanced import AdvancedBacktester
from strategy_rs_momentum import RSMomentumStrategy
from strategy_regime import RegimeAwareMomentumStrategy
from risk_metrics import RiskReport

EIKON_URL = (
    "https://raw.githubusercontent.com/yhilpisch/py4fi2nd/"
    "master/source/tr_eikon_eod_data.csv"
)

TRAIN_END  = "2013-12-31"
TEST_START = "2014-01-01"
TEST_END   = "2018-06-29"

STOCK_TICKERS = ["AAPL", "MSFT", "INTC", "AMZN", "GS"]
BENCH_TICKER  = "SPY"


# ──────────────────────────────────────────────────────────────────────────────
# Data fetching and OHLCV synthesis
# ──────────────────────────────────────────────────────────────────────────────

def fetch_eikon() -> pd.DataFrame:
    print("  Fetching Reuters Eikon EOD data from GitHub ...", end=" ", flush=True)
    with urllib.request.urlopen(EIKON_URL, timeout=12) as resp:
        content = resp.read().decode("utf-8")
    df = pd.read_csv(io.StringIO(content), index_col=0, parse_dates=True)
    rename = {"AAPL.O": "AAPL", "MSFT.O": "MSFT", "INTC.O": "INTC",
              "AMZN.O": "AMZN", "GS.N": "GS"}
    df = df.rename(columns=rename)
    df = df.dropna(subset=["AAPL"])
    print(f"OK  ({len(df)} trading days, {df.index[0].date()} → {df.index[-1].date()})")
    return df


def synthesize_ohlcv(close: pd.Series, seed: int = 42) -> pd.DataFrame:
    """
    Synthesize realistic OHLCV from close prices.
    Close is real. High/Low are generated from rolling vol so that
    ATR and Bollinger Bands are computed on plausible data.
    """
    rng = np.random.default_rng(seed)
    n   = len(close)

    returns  = close.pct_change().fillna(0.0)
    roll_vol = returns.rolling(20).std().fillna(returns.std())

    open_price = close.shift(1).fillna(close.iloc[0])

    # Intraday range ~ vol * half-normal draw
    range_factor = np.abs(rng.normal(0.6, 0.25, n)).clip(0.1, 1.8)
    half_range   = close.values * roll_vol.values * range_factor

    high_price = np.maximum(open_price.values, close.values) + half_range
    low_price  = np.minimum(open_price.values, close.values) - half_range
    low_price  = np.maximum(low_price, close.values * 0.5)

    volume = np.abs(rng.normal(1_000_000, 300_000, n)).astype(int)

    return pd.DataFrame({
        "Open":   open_price.values,
        "High":   high_price,
        "Low":    low_price,
        "Close":  close.values,
        "Volume": volume,
    }, index=close.index)


def make_data_dict(raw: pd.DataFrame, tickers: list) -> dict:
    data = {}
    for ticker in tickers:
        if ticker not in raw.columns:
            continue
        close = raw[ticker].dropna()
        if len(close) < 100:
            continue
        data[ticker] = synthesize_ohlcv(close)
    return data


def slice_period(data: dict, start: str, end: str) -> dict:
    out = {}
    for ticker, df in data.items():
        sliced = df.loc[start:end]
        if len(sliced) >= 50:
            out[ticker] = sliced
    return out


# ──────────────────────────────────────────────────────────────────────────────
# Strategy configurations to grid-search in-sample
# ──────────────────────────────────────────────────────────────────────────────

BACKTESTER_CONFIGS = [
    dict(max_positions=3, position_size_pct=0.33, atr_stop_multiplier=2.0,
         atr_trail_multiplier=1.5, risk_per_trade_pct=0.02),
    dict(max_positions=3, position_size_pct=0.33, atr_stop_multiplier=3.5,
         atr_trail_multiplier=3.0, risk_per_trade_pct=0.02),
    dict(max_positions=2, position_size_pct=0.48, atr_stop_multiplier=3.0,
         atr_trail_multiplier=2.5, risk_per_trade_pct=0.03),
    dict(max_positions=1, position_size_pct=0.90, atr_stop_multiplier=3.0,
         atr_trail_multiplier=2.5, risk_per_trade_pct=0.04),
    dict(max_positions=4, position_size_pct=0.25, atr_stop_multiplier=2.0,
         atr_trail_multiplier=1.5, risk_per_trade_pct=0.015),
]

STRATEGY_CONFIGS = [
    # RS Momentum variants
    dict(name="RSMom_Fast",
         cls=RSMomentumStrategy,
         kw=dict(top_n=3, rebalance_days=5, lookback_short=10,
                 lookback_mid=20, lookback_long=60, adx_min=15, rsi_min=40)),
    dict(name="RSMom_Daily",
         cls=RSMomentumStrategy,
         kw=dict(top_n=2, rebalance_days=1, lookback_short=5,
                 lookback_mid=10, lookback_long=20, adx_min=12, rsi_min=35)),
    dict(name="RSMom_Concentrated",
         cls=RSMomentumStrategy,
         kw=dict(top_n=1, rebalance_days=3, lookback_short=5,
                 lookback_mid=10, lookback_long=20, adx_min=12, rsi_min=35)),
    dict(name="RSMom_Wide",
         cls=RSMomentumStrategy,
         kw=dict(top_n=4, rebalance_days=3, lookback_short=10,
                 lookback_mid=20, lookback_long=40, adx_min=12, rsi_min=35)),
    # Regime-aware variants (correct param names: bull_top_n, neutral_top_n)
    dict(name="Regime_Bull3",
         cls=RegimeAwareMomentumStrategy,
         kw=dict(bull_top_n=3, neutral_top_n=2, lb_short=10, lb_mid=20, lb_long=40)),
    dict(name="Regime_Bull2",
         cls=RegimeAwareMomentumStrategy,
         kw=dict(bull_top_n=2, neutral_top_n=1, lb_short=10, lb_mid=20, lb_long=40)),
    dict(name="Regime_Aggressive",
         cls=RegimeAwareMomentumStrategy,
         kw=dict(bull_top_n=4, neutral_top_n=2, lb_short=5, lb_mid=10, lb_long=20,
                 adx_min_bull=10, rsi_min=35)),
]


def run_one(data: dict, bench_ohlcv: pd.DataFrame | None, strat_cfg: dict, bt_cfg: dict):
    cls = strat_cfg["cls"]
    kw  = strat_cfg["kw"].copy()

    # Provide SPY as "QQQ" so RegimeAwareMomentumStrategy can detect market regime
    run_data = dict(data)
    if cls == RegimeAwareMomentumStrategy and bench_ohlcv is not None and "QQQ" not in run_data:
        run_data["QQQ"] = bench_ohlcv

    # Exclude the benchmark from the tradeable universe
    trade_data = {k: v for k, v in run_data.items() if k != "QQQ"}

    strategy = cls(**kw)
    # For regime strategy: prepare with QQQ included so it can find the benchmark
    if cls == RegimeAwareMomentumStrategy:
        strategy.prepare(run_data)
    else:
        strategy.prepare(trade_data)

    bt = AdvancedBacktester(initial_capital=100_000, **bt_cfg)
    result = bt.run(trade_data, strategy)
    report = RiskReport(result)
    return report


# ──────────────────────────────────────────────────────────────────────────────
# Main
# ──────────────────────────────────────────────────────────────────────────────

def main():
    print("\n" + "=" * 70)
    print("  REAL-DATA BACKTEST  —  Reuters Eikon EOD  (2010–2018)")
    print("  Walk-forward: train 2010–2013  |  test 2014–2018")
    print("=" * 70)

    # ── 1. Fetch data ──────────────────────────────────────────────────────
    raw      = fetch_eikon()
    all_data = make_data_dict(raw, STOCK_TICKERS + [BENCH_TICKER])

    # Split into periods — exclude SPY from stock universe for trading
    stock_data = {k: v for k, v in all_data.items() if k != BENCH_TICKER}
    bench_ohlcv = all_data.get(BENCH_TICKER)

    train_data   = slice_period(stock_data, "2010-01-01", TRAIN_END)
    test_data    = slice_period(stock_data, TEST_START,   TEST_END)
    bench_train  = slice_period({BENCH_TICKER: bench_ohlcv}, "2010-01-01", TRAIN_END).get(BENCH_TICKER) if bench_ohlcv is not None else None
    bench_test   = slice_period({BENCH_TICKER: bench_ohlcv}, TEST_START,   TEST_END).get(BENCH_TICKER)  if bench_ohlcv is not None else None

    print(f"\n  Stock tickers: {list(train_data.keys())}")
    print(f"  Train days: {len(next(iter(train_data.values())))}   "
          f"Test days: {len(next(iter(test_data.values())))}")

    # ── 2. In-sample sweep ─────────────────────────────────────────────────
    print("\n" + "-" * 70)
    print("  IN-SAMPLE OPTIMIZATION  (2010–2013 — real market data)")
    print("-" * 70)

    best_score  = -9999
    best_config = None
    best_report = None
    results_summary = []

    for sc in STRATEGY_CONFIGS:
        for bc in BACKTESTER_CONFIGS:
            label = f"{sc['name']} | mp={bc['max_positions']} ps={bc['position_size_pct']}"
            try:
                rpt = run_one(train_data, bench_train, sc, bc)
                m = rpt.full_metrics()

                monthly = m.get("monthly_return_pct", 0)
                sharpe  = m.get("sharpe_ratio", 0)
                maxdd   = m.get("max_drawdown_pct", 0)
                calmar  = m.get("calmar_ratio", 0)
                wr      = m.get("win_rate_pct", 0)
                pf      = m.get("profit_factor", 0)
                ntrades = m.get("n_trades", 0)

                # Score: weighted combination of metrics
                score = (monthly * 2.0 + sharpe * 0.5 + calmar * 0.3
                         - max(0, -30 - maxdd) * 0.5)

                flag = "✓ ALL" if rpt.meets_target() else ""
                print(f"  {label:<52}  mo={monthly:+6.2f}%  sr={sharpe:.2f}  dd={maxdd:.1f}%"
                      f"  wr={wr:.0f}%  pf={pf:.2f}  nt={ntrades}  {flag}")

                results_summary.append({
                    "label": label, "monthly": monthly, "sharpe": sharpe,
                    "maxdd": maxdd, "calmar": calmar, "wr": wr, "pf": pf,
                    "ntrades": ntrades, "meets": rpt.meets_target(),
                    "score": score, "sc": sc, "bc": bc, "report": rpt
                })

                if score > best_score:
                    best_score  = score
                    best_config = (sc, bc)
                    best_report = rpt

            except Exception as e:
                print(f"  {label:<52}  ERROR: {e}")

    # ── 3. Best in-sample strategy ─────────────────────────────────────────
    if best_report is None:
        print("\n  No valid strategies found.")
        return

    best_sc, best_bc = best_config
    print(f"\n  Best in-sample: {best_sc['name']} | "
          f"mp={best_bc['max_positions']} ps={best_bc['position_size_pct']}")
    best_report.print_full_report(f"IN-SAMPLE — {best_sc['name']}")

    # ── 4. Out-of-sample (blind test) ──────────────────────────────────────
    print("\n" + "=" * 70)
    print("  OUT-OF-SAMPLE VALIDATION  (2014–2018 — NEVER SEEN BEFORE)")
    print("=" * 70)

    oos_report = run_one(test_data, bench_test, best_sc, best_bc)
    oos_report.print_full_report(f"OUT-OF-SAMPLE — {best_sc['name']}")

    # ── 5. Full-period run ─────────────────────────────────────────────────
    print("\n" + "=" * 70)
    print("  FULL PERIOD  (2010–2018, combined)")
    print("=" * 70)

    full_stock = slice_period(stock_data, "2010-01-01", TEST_END)
    bench_full = slice_period({BENCH_TICKER: bench_ohlcv}, "2010-01-01", TEST_END).get(BENCH_TICKER) if bench_ohlcv is not None else None
    full_report = run_one(full_stock, bench_full, best_sc, best_bc)
    full_report.print_full_report(f"FULL PERIOD — {best_sc['name']}")

    # ── 6. Summary across all periods ─────────────────────────────────────
    print("\n" + "=" * 70)
    print("  STRATEGY COMPARISON  (in-sample top 5 by score)")
    print("=" * 70)
    top5 = sorted(results_summary, key=lambda x: x["score"], reverse=True)[:5]
    print(f"\n  {'Strategy':<52}  {'Mo%':>6}  {'SR':>5}  {'MaxDD':>7}  {'WR':>5}  {'PF':>5}")
    print("  " + "-" * 80)
    for r in top5:
        flag = " ✓" if r["meets"] else ""
        print(f"  {r['label']:<52}  {r['monthly']:>+6.2f}  {r['sharpe']:>5.2f}"
              f"  {r['maxdd']:>7.2f}%  {r['wr']:>5.1f}%  {r['pf']:>5.2f}{flag}")

    # ── 7. Honest assessment ───────────────────────────────────────────────
    oos_m = oos_report.full_metrics()
    oos_monthly = oos_m.get("monthly_return_pct", 0)
    oos_sr      = oos_m.get("sharpe_ratio", 0)
    oos_dd      = oos_m.get("max_drawdown_pct", 0)
    oos_meets   = oos_report.meets_target()

    print("\n" + "=" * 70)
    print("  TRADABILITY ASSESSMENT")
    print("=" * 70)
    print(f"\n  Out-of-sample monthly return: {oos_monthly:+.2f}%")
    print(f"  Out-of-sample Sharpe ratio:   {oos_sr:.2f}")
    print(f"  Out-of-sample max drawdown:   {oos_dd:.2f}%")

    if oos_meets:
        print("\n  ✅  Strategy meets ALL targets on out-of-sample real data.")
        print("  This is a strong signal for live tradability.")
    else:
        print("\n  ⚠   Not all targets met on out-of-sample data.")
        print("  Realistic assessment of this strategy on major stocks (2014–2018):")
        if oos_monthly >= 2.0:
            print(f"  → {oos_monthly:.1f}%/month is excellent vs S&P (~0.8%/mo). "
                  "Tradable with realistic expectations.")
        elif oos_monthly >= 1.0:
            print(f"  → {oos_monthly:.1f}%/month = ~{oos_monthly*12:.0f}%/year. "
                  "Market-beating. Add leverage to scale.")
        else:
            print(f"  → {oos_monthly:.1f}%/month — marginal. "
                  "Need different universe (small caps, crypto, options).")

        print("\n  NOTE: 10%/month = 214%/year. No large-cap equity strategy achieves")
        print("  this consistently. Best hedge funds return 20-30%/year. To hit")
        print("  10%/month you need: options, crypto, leveraged ETFs, or small caps.")

    print("\n  Data source: Reuters Eikon EOD (2010-2018)")
    print("  For 2020-2025 real data: run `python3 download_real_data.py` locally,")
    print("  then commit stock-backtest/data/ and push.\n")


if __name__ == "__main__":
    main()
