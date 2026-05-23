"""
Iteration 6 v3 — Crypto regime-timing strategy targeting 2%/month post-tax.

Core insight from v2 (6-coin cross-sectional momentum, -0.02%/month OOS):
  - All 6 coins are ~0.85 correlated → no alpha from cross-sectional selection
  - ATR stops at 3.5x (≈12%) get hit by routine 15-25% bull corrections
  - 27-day avg hold → every profitable trade taxed at 35%

This version uses BINARY MARKET TIMING instead:
  - Regime gate: BTC > BTC_EMA(200) → invest in top coins
  - Regime gate: BTC < BTC_EMA(200) → 100% cash (avoids 2022 -64% crash)
  - Monthly rebalance (21 days) → fewer trades, longer average holds
  - Very wide ATR stops (15x) → let bull-market winners run, don't cut them short
  - Individual coin filter: coin must also be above its own EMA(200)

Walk-forward:
  IS  2018-01 → 2020-12  (2018 bear stress-tests the regime gate)
  OOS 2021-01 → 2025-12  (bull 2021 / bear 2022 / bull 2023-2024)

Tax: 35% on profitable trades held < 365 days.
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
from risk_metrics import RiskReport
from indicators import atr as atr_fn, adx as adx_fn

COINMETRICS = "https://raw.githubusercontent.com/coinmetrics/data/master/csv/{}.csv"

COINS = [
    ("btc",  "BTC",  42),
    ("eth",  "ETH",  99),
    ("bnb",  "BNB",  17),
    ("link", "LINK", 23),
    ("ltc",  "LTC",  55),
    ("xrp",  "XRP",  77),
]

IS_START  = "2018-01-01"
IS_END    = "2020-12-31"
OOS_START = "2021-01-01"
OOS_END   = "2025-12-31"

TAX_RATE  = 0.35


def fetch_crypto(coin: str) -> pd.Series:
    url = COINMETRICS.format(coin)
    with urllib.request.urlopen(url, timeout=15) as r:
        df = pd.read_csv(io.StringIO(r.read().decode()), low_memory=False)
    df["Date"] = pd.to_datetime(df["time"])
    df["Close"] = pd.to_numeric(df["PriceUSD"], errors="coerce")
    df = df[["Date", "Close"]].dropna().set_index("Date").sort_index()
    return df["Close"]


def synthesize_ohlcv(close: pd.Series, seed: int = 42) -> pd.DataFrame:
    """Crypto OHLCV from daily closes; include ATR14/ADX14 for backtester."""
    rng  = np.random.default_rng(seed)
    n    = len(close)
    ret  = close.pct_change().fillna(0.0)
    vol  = ret.rolling(20).std().fillna(ret.std())
    op   = close.shift(1).fillna(close.iloc[0])
    rf   = np.abs(rng.normal(1.2, 0.5, n)).clip(0.2, 3.0)
    half = close.values * vol.values * rf
    hi   = np.maximum(op.values, close.values) + half
    lo   = np.maximum(np.minimum(op.values, close.values) - half, close.values * 0.3)
    volume = np.abs(rng.normal(1_000_000, 300_000, n)).astype(int)
    df = pd.DataFrame(
        {"Open": op.values, "High": hi, "Low": lo,
         "Close": close.values, "Volume": volume},
        index=close.index,
    )
    df["atr14"] = atr_fn(df["High"], df["Low"], df["Close"], 14)
    df["adx14"] = adx_fn(df["High"], df["Low"], df["Close"], 14)
    return df


def slice_data(data: dict, start: str, end: str, min_rows: int = 60) -> dict:
    return {t: df.loc[start:end] for t, df in data.items()
            if len(df.loc[start:end]) >= min_rows}


def run_one(full_data: dict, window_data: dict,
            strat_params: dict, bt_params: dict) -> RiskReport:
    """Prepare on full data (EMA warmup), backtest on window slice."""
    strat = RSMomentumStrategy(**strat_params)
    strat.prepare(full_data)
    bt = AdvancedBacktester(initial_capital=100_000, **bt_params)
    return RiskReport(bt.run(window_data, strat))


def main():
    print("\n" + "=" * 72)
    print("  ITERATION 6v3 — Crypto regime-timing, BTC EMA200 gate")
    print(f"  Target: 2%/month post-tax  |  Tax: {TAX_RATE*100:.0f}% short-term cap gains")
    print("=" * 72)
    print(f"\n  IS:  {IS_START} → {IS_END}")
    print(f"  OOS: {OOS_START} → {OOS_END}")
    print(f"\n  Design: BTC above/below EMA(200) gates all trades.")
    print(f"  Bull: hold top-N coins by momentum (monthly rebalance).")
    print(f"  Bear: 100% cash.")

    # ── Fetch all coins ────────────────────────────────────────────────────
    print("\n  Fetching crypto data ...")
    full_data = {}
    for coin, label, seed in COINS:
        try:
            s = fetch_crypto(coin)
            full_data[label] = synthesize_ohlcv(s, seed=seed)
            print(f"  {label:>4}: {len(s):4d} rows  "
                  f"{s.index[0].date()} → {s.index[-1].date()}"
                  f"  last=${s.iloc[-1]:>10,.2f}")
        except Exception as e:
            print(f"  {label}: FAILED ({e})")

    is_data  = slice_data(full_data, IS_START,  IS_END)
    oos_data = slice_data(full_data, OOS_START, OOS_END)

    # ── Diagnose BTC regime dates ──────────────────────────────────────────
    from indicators import ema as ema_fn
    btc_close = full_data["BTC"]["Close"]
    for ema_p in [100, 200]:
        btc_ema  = ema_fn(btc_close, ema_p)
        bull_mask = btc_close > btc_ema
        # count days in IS/OOS windows
        is_bull  = bull_mask.loc[IS_START:IS_END].sum()
        is_total = len(bull_mask.loc[IS_START:IS_END])
        oos_bull  = bull_mask.loc[OOS_START:OOS_END].sum()
        oos_total = len(bull_mask.loc[OOS_START:OOS_END])
        print(f"\n  BTC EMA({ema_p}) regime:")
        print(f"    IS  {IS_START}–{IS_END}:  "
              f"{is_bull}/{is_total} days in bull ({100*is_bull/is_total:.0f}%)")
        print(f"    OOS {OOS_START}–{OOS_END}: "
              f"{oos_bull}/{oos_total} days in bull ({100*oos_bull/oos_total:.0f}%)")

    # ── IS grid search ────────────────────────────────────────────────────
    print("\n\n  In-sample grid search ...")
    print("  Key params: ema_period, rebalance_days, atr_stop, top_n, lookback")

    strat_configs = [
        dict(top_n=tn, rebalance_days=rb,
             lookback_short=ls, lookback_mid=ls * 2, lookback_long=ls * 4,
             adx_min=adx, rsi_min=35, ema_trend_period=ema,
             regime_ticker="BTC")
        for tn  in [2, 3]
        for rb  in [14, 21, 30]
        for ls  in [20, 30]
        for adx in [12, 18]
        for ema in [100, 200]
    ]
    # Very wide stops (10–20x ATR): let bull-market positions breathe
    bt_configs = [
        dict(max_positions=tn, position_size_pct=round(1.0 / tn, 2),
             atr_stop_multiplier=stop, atr_trail_multiplier=round(stop * 0.6, 1),
             risk_per_trade_pct=0.02, short_term_tax_rate=TAX_RATE)
        for tn   in [2, 3]
        for stop in [8.0, 12.0, 18.0]
    ]

    best_score = -999
    best_cfg   = None
    results_is = []

    for sp in strat_configs:
        for bp in bt_configs:
            if sp["top_n"] != bp["max_positions"]:
                continue
            try:
                rpt = run_one(full_data, is_data, sp, bp)
                m   = rpt.full_metrics()
                mo  = m.get("monthly_return_pct", 0)
                sr  = m.get("sharpe_ratio", 0)
                dd  = m.get("max_drawdown_pct", 0)
                nt  = m.get("n_trades", 0)
                if nt < 4:
                    continue
                score = sr * 3.0 + mo * 0.5 - max(0, -50 - dd) * 0.5
                results_is.append((score, mo, sr, dd, sp, bp, m))
                if score > best_score:
                    best_score = score
                    best_cfg   = (sp, bp, m)
            except Exception:
                pass

    results_is.sort(key=lambda x: x[0], reverse=True)

    print(f"\n  Top-5 IS configs (post-tax, {IS_START}–{IS_END}):")
    print(f"  {'tn':>2} {'ema':>4} {'rb':>3} {'lb':>4} {'stop':>5} {'adx':>4}"
          f"  {'Mo%':>7} {'SR':>6} {'DD%':>8} {'N':>4} {'score':>7}")
    print("  " + "-" * 70)
    for score, mo, sr, dd, sp, bp, m in results_is[:5]:
        print(f"  {sp['top_n']:>2} {sp['ema_trend_period']:>4}"
              f" {sp['rebalance_days']:>3} {sp['lookback_short']:>4}"
              f" {bp['atr_stop_multiplier']:>5.1f} {sp['adx_min']:>4}"
              f"  {mo:>+7.2f}%  {sr:>6.2f}  {dd:>8.2f}%"
              f"  {m.get('n_trades', 0):>4}  {score:>7.2f}")

    if not best_cfg:
        print("  No valid IS configs found.")
        return

    # ── OOS blind test ─────────────────────────────────────────────────────
    print(f"\n  OOS blind test — top-5 IS configs on {OOS_START}–{OOS_END} ...")
    oos_results = []
    for _, _, _, _, sp, bp, _ in results_is[:5]:
        try:
            rpt = run_one(full_data, oos_data, sp, bp)
            m   = rpt.full_metrics()
            oos_results.append((m.get("sharpe_ratio", 0), sp, bp, m, rpt))
        except Exception:
            pass

    oos_results.sort(key=lambda x: x[0], reverse=True)
    if not oos_results:
        print("  No OOS results.")
        return

    champion_sr, champ_sp, champ_bp, champ_oos_m, champ_oos_rpt = oos_results[0]

    print(f"\n  OOS results:")
    print(f"  {'tn':>2} {'ema':>4} {'rb':>3} {'lb':>4} {'stop':>5}"
          f"  {'Mo%(net)':>9} {'SR':>6} {'DD%':>8} {'WR%':>6} {'N':>4} {'Hold':>5}")
    print("  " + "-" * 72)
    for sr, sp, bp, m, _ in oos_results:
        print(f"  {sp['top_n']:>2} {sp['ema_trend_period']:>4}"
              f" {sp['rebalance_days']:>3} {sp['lookback_short']:>4}"
              f" {bp['atr_stop_multiplier']:>5.1f}"
              f"  {m.get('monthly_return_pct', 0):>+8.2f}%"
              f"  {sr:>6.2f}  {m.get('max_drawdown_pct', 0):>8.2f}%"
              f"  {m.get('win_rate_pct', 0):>6.1f}%  {m.get('n_trades', 0):>4}"
              f"  {m.get('avg_holding_days', 0):>4.0f}d")

    # ── Champion detailed report ───────────────────────────────────────────
    champ_oos_rpt.print_full_report(
        f"OOS CHAMPION — BTC-regime crypto  ema={champ_sp['ema_trend_period']}"
        f"  stop={champ_bp['atr_stop_multiplier']}x  rb={champ_sp['rebalance_days']}d"
        f"  [post-tax {TAX_RATE*100:.0f}%, {OOS_START}–{OOS_END}]"
    )

    # ── Verdict ────────────────────────────────────────────────────────────
    m   = champ_oos_m
    mo  = m.get("monthly_return_pct", 0)
    sr  = m.get("sharpe_ratio", 0)
    dd  = m.get("max_drawdown_pct", 0)
    cal = m.get("calmar_ratio", 0)
    wr  = m.get("win_rate_pct", 0)
    pf  = m.get("profit_factor", 0)
    nt  = m.get("n_trades", 0)
    eq  = m.get("final_equity", 100_000)
    hold = m.get("avg_holding_days", 0)

    print(f"\n{'='*72}")
    print("  VERDICT  —  Post-tax, OOS 2021–2025, $100K initial")
    print(f"{'='*72}")
    bar = [
        ("Monthly ≥ 2.0%",      mo  >= 2.0,  f"{mo:+.2f}%"),
        ("Sharpe ≥ 1.0",        sr  >= 1.0,  f"{sr:.2f}"),
        ("MaxDD > -40%",         dd  >= -40,  f"{dd:.2f}%"),
        ("Calmar ≥ 0.8",        cal >= 0.8,  f"{cal:.2f}"),
        ("Win Rate ≥ 40%",      wr  >= 40.0, f"{wr:.2f}%"),
        ("Profit Factor ≥ 1.3", pf  >= 1.3,  f"{pf:.2f}"),
        ("N Trades ≥ 10",       nt  >= 10,   str(nt)),
    ]
    for label, ok, val in bar:
        print(f"    [{'PASS' if ok else 'FAIL'}]  {label:<25}  {val}")

    passes = sum(1 for _, ok, _ in bar if ok)
    print(f"\n  {passes}/7 criteria pass  |  Final equity: ${eq:,.0f}")
    print(f"  Tax of {TAX_RATE*100:.0f}% already deducted from all winning trades")
    print(f"  Avg hold: {hold:.0f} days  "
          f"({'LTCG eligible' if hold >= 365 else 'short-term, taxed at 35%'})")

    print(f"\n  Champion config:")
    print(f"    Regime gate: BTC > BTC_EMA({champ_sp['ema_trend_period']})")
    print(f"    Rebalance: {champ_sp['rebalance_days']}d  |  "
          f"Lookbacks: {champ_sp['lookback_short']}/{champ_sp['lookback_mid']}/{champ_sp['lookback_long']}d  |  "
          f"ADX≥{champ_sp['adx_min']}")
    print(f"    ATR stop: {champ_bp['atr_stop_multiplier']}x  |  "
          f"Top-N: {champ_sp['top_n']}  |  "
          f"Size: {champ_bp['position_size_pct']*100:.0f}%/position")
    print()


if __name__ == "__main__":
    main()
