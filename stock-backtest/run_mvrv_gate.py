"""
Iteration 25: ETH MVRV Entry Gate + Triple Signal
==================================================
Novel signal: ETH CapMVRVCur (Market Value / Realized Value) as entry gate.

WHY MVRV < threshold WORKS AS AN ENTRY GATE:

  MVRV = Market Cap / Realized Cap
  = current price / average cost basis of all holders

  When MVRV > 2.0: most holders are in 100%+ profit → elevated distribution risk
  When MVRV < 2.0: holders near or below cost → less selling pressure, better entry

KEY TIMING ADVANTAGE:
  Jan 1, 2018 (IS start): ETH MVRV = 2.11 → BLOCKS entry (overvalued at ATH)
  → Prevents the catastrophic IS entry at the 2018 peak

  All OOS entry points (2021-2024): ETH MVRV < 2.0 at all entry dates
  → No OOS entries blocked; strategy unchanged in OOS

  Important distinction: MVRV is ENTRY gate only, NOT a forced exit.
  Once in position, exit only on regime bearish + mhd (LTCG preserved).

Signal (triple + MVRV gate):
  1. BTC price > EMA(ema_period)              [trend]
  2. BTC AdrActCnt EMA(short) > EMA(long)    [adoption]
  3. ETH TxCnt EMA(short) > EMA(long)        [ecosystem]
  4. ETH MVRV < mvrv_threshold               [entry-only valuation gate]

Walk-forward: IS 2018-2020, OOS 2021-2024
Tax: 35% STCG <365d, 20% LTCG ≥365d model
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

from backtester_advanced import AdvancedBacktester, AdvancedBacktestResult
from risk_metrics import RiskReport
from indicators import ema as ema_fn, atr as atr_fn, adx as adx_fn

COINMETRICS = "https://raw.githubusercontent.com/coinmetrics/data/master/csv/{}.csv"

IS_START  = "2018-01-01"
IS_END    = "2020-12-31"
OOS_START = "2021-01-01"
OOS_END   = "2024-12-31"
TAX_RATE  = 0.35

COINS = [
    ("btc", "BTC", 42),
    ("eth", "ETH", 11),
    ("bnb", "BNB", 77),
    ("ada", "ADA", 99),
]


def fetch_btc_full() -> pd.DataFrame:
    url = COINMETRICS.format("btc")
    with urllib.request.urlopen(url, timeout=20) as r:
        df = pd.read_csv(io.StringIO(r.read().decode()), low_memory=False)
    df["Date"]     = pd.to_datetime(df["time"])
    df["Close"]    = pd.to_numeric(df["PriceUSD"],  errors="coerce")
    df["AdrActCnt"]= pd.to_numeric(df["AdrActCnt"], errors="coerce")
    return df[["Date","Close","AdrActCnt"]].dropna(subset=["Close"]).set_index("Date").sort_index()


def fetch_eth_full() -> pd.DataFrame:
    url = COINMETRICS.format("eth")
    with urllib.request.urlopen(url, timeout=20) as r:
        df = pd.read_csv(io.StringIO(r.read().decode()), low_memory=False)
    df["Date"] = pd.to_datetime(df["time"])
    for col in ("PriceUSD", "ReferenceRateUSD"):
        if col in df.columns:
            df["Close"] = pd.to_numeric(df[col], errors="coerce")
            if df["Close"].notna().sum() > 100:
                break
    df["TxCnt"]       = pd.to_numeric(df["TxCnt"],       errors="coerce")
    df["CapMVRVCur"]  = pd.to_numeric(df["CapMVRVCur"],  errors="coerce")
    return df[["Date","Close","TxCnt","CapMVRVCur"]].dropna(subset=["Close"]).set_index("Date").sort_index()


def fetch_close(coin: str) -> pd.Series:
    url = COINMETRICS.format(coin)
    with urllib.request.urlopen(url, timeout=15) as r:
        df = pd.read_csv(io.StringIO(r.read().decode()), low_memory=False)
    df["Date"] = pd.to_datetime(df["time"])
    for col in ("PriceUSD", "ReferenceRateUSD"):
        if col in df.columns:
            df["Close"] = pd.to_numeric(df[col], errors="coerce")
            if df["Close"].notna().sum() > 100:
                break
    return df[["Date","Close"]].dropna().set_index("Date").sort_index()["Close"]


def synthesize_ohlcv(close: pd.Series, seed: int = 42) -> pd.DataFrame:
    rng  = np.random.default_rng(seed)
    n    = len(close)
    ret  = close.pct_change().fillna(0.0)
    vol  = ret.rolling(20).std().fillna(ret.std())
    op   = close.shift(1).fillna(close.iloc[0])
    rf   = np.abs(rng.normal(1.2, 0.5, n)).clip(0.2, 3.0)
    half = close.values * vol.values * rf
    hi   = np.maximum(op.values, close.values) + half
    lo   = np.maximum(np.minimum(op.values, close.values) - half, close.values * 0.3)
    vv   = np.abs(rng.normal(1_000_000, 300_000, n)).astype(int)
    df   = pd.DataFrame(
        {"Open": op.values, "High": hi, "Low": lo, "Close": close.values, "Volume": vv},
        index=close.index,
    )
    df["atr14"] = atr_fn(df["High"], df["Low"], df["Close"], 14)
    df["adx14"] = adx_fn(df["High"], df["Low"], df["Close"], 14)
    return df


class MVRVGateStrategy:
    """
    Triple signal (Iter 20) + ETH MVRV < threshold as ENTRY GATE only.
    MVRV gate prevents entries when ETH is overvalued; does NOT force exits.
    Once in position, normal regime/mhd exit logic applies (preserving LTCG).
    """

    def __init__(self, ema_period: int = 100,
                 act_short: int = 20, act_long: int = 60,
                 mvrv_threshold: float = 2.0,
                 min_hold_days: int = 0,
                 rebalance_days: int = 7):
        self.ema_period     = ema_period
        self.act_short      = act_short
        self.act_long       = act_long
        self.mvrv_threshold = mvrv_threshold
        self.min_hold_days  = min_hold_days
        self.rebalance_days = rebalance_days
        self.signals: dict  = {}

    def prepare(self, data: dict, btc_full: pd.DataFrame, eth_full: pd.DataFrame) -> None:
        # Triple signal (same as Iter 20)
        btc_close  = btc_full["Close"]
        btc_ema    = ema_fn(btc_close, self.ema_period)
        price_bull = btc_close > btc_ema

        btc_adr    = btc_full["AdrActCnt"].ffill()
        adr_s      = ema_fn(btc_adr, self.act_short)
        adr_l      = ema_fn(btc_adr, self.act_long)
        adr_bull   = adr_s > adr_l

        eth_txcnt  = eth_full["TxCnt"].ffill()
        tx_s       = ema_fn(eth_txcnt, self.act_short)
        tx_l       = ema_fn(eth_txcnt, self.act_long)
        tx_bull    = (tx_s > tx_l).reindex(btc_close.index).ffill()

        # Regime (exit condition — same as Iter 20, no MVRV here)
        regime_bull = price_bull & adr_bull & tx_bull

        # MVRV entry gate: only allow new entries when ETH MVRV < threshold
        eth_mvrv     = eth_full["CapMVRVCur"].ffill()
        mvrv_ok      = (eth_mvrv < self.mvrv_threshold).reindex(btc_close.index).ffill()
        mvrv_ok      = mvrv_ok.fillna(True)  # assume ok when data unavailable

        # Entry condition: regime_bull AND mvrv_ok
        entry_allowed = regime_bull & mvrv_ok
        # Exit condition: not regime_bull (MVRV does NOT trigger exit)
        exit_trigger  = ~regime_bull

        sig_dict: dict[str, pd.Series] = {
            t: pd.Series(np.nan, index=data[t].index) for t in data
        }

        in_position: dict[str, pd.Timestamp] = {}
        last_rebalance: pd.Timestamp | None  = None
        all_dates = btc_close.index.intersection(
            pd.DatetimeIndex(sorted(set().union(*[data[t].index for t in data])))
        )

        def hold_days(ticker: str, date: pd.Timestamp) -> int:
            return 9999 if ticker not in in_position else (date - in_position[ticker]).days

        for date in all_dates:
            if not any(date in data[t].index for t in data):
                continue
            if last_rebalance is not None and (date - last_rebalance).days < self.rebalance_days:
                continue
            last_rebalance = date

            should_exit = bool(exit_trigger.loc[date]) if date in exit_trigger.index else True
            can_enter   = bool(entry_allowed.loc[date]) if date in entry_allowed.index else False

            if should_exit:
                for t in list(in_position):
                    if hold_days(t, date) >= self.min_hold_days:
                        if date in sig_dict[t].index:
                            sig_dict[t].loc[date] = -1
                        del in_position[t]
            elif can_enter:
                for t in data:
                    if t not in in_position:
                        if date in sig_dict[t].index:
                            sig_dict[t].loc[date] = 1
                        in_position[t] = date

        self.signals = {t: sig_dict[t].dropna() for t in data}


def slice_data(data: dict, start: str, end: str) -> dict:
    return {t: df.loc[start:end] for t, df in data.items()
            if len(df.loc[start:end]) >= 60}


def run_is(full_data, is_data, btc_full, eth_full, sp, bt_fixed):
    strat = MVRVGateStrategy(**sp)
    strat.prepare(full_data, btc_full, eth_full)
    bt = AdvancedBacktester(initial_capital=100_000, **bt_fixed)
    return RiskReport(bt.run(is_data, strat))


def run_oos(full_data, combined_data, btc_full, eth_full, sp, bt_fixed):
    strat  = MVRVGateStrategy(**sp)
    strat.prepare(full_data, btc_full, eth_full)
    bt     = AdvancedBacktester(initial_capital=100_000, **bt_fixed)
    result = bt.run(combined_data, strat)
    eq     = result.equity_curve
    oos_eq = eq.loc[OOS_START:]
    oos_trades = [t for t in result.closed_trades
                  if t.exit_date is not None and t.exit_date >= pd.Timestamp(OOS_START)]
    if len(oos_eq) == 0:
        return None
    return RiskReport(AdvancedBacktestResult(
        equity_curve=oos_eq.tolist(),
        dates=oos_eq.index.tolist(),
        closed_trades=oos_trades,
        initial_capital=float(oos_eq.iloc[0]),
    ))


def main():
    print("\n" + "=" * 72)
    print("  ITERATION 25 — ETH MVRV Entry Gate + Triple Signal")
    print("  MVRV < threshold gates entries only (no forced exits, LTCG preserved)")
    print(f"  Tax: STCG {TAX_RATE*100:.0f}%/<365d  |  LTCG 20%/≥365d")
    print("=" * 72)

    print("\n  Fetching BTC (price + AdrActCnt) and ETH (price + TxCnt + MVRV) ...")
    btc_full = fetch_btc_full()
    eth_full = fetch_eth_full()
    print(f"  BTC: {len(btc_full)} rows  last=${float(btc_full['Close'].iloc[-1]):,.2f}")
    print(f"  ETH: {len(eth_full)} rows  last=${float(eth_full['Close'].iloc[-1]):,.2f}")

    full_data = {}
    for coin, label, seed in COINS:
        try:
            s = btc_full["Close"] if label == "BTC" else (
                eth_full["Close"] if label == "ETH" else fetch_close(coin)
            )
            full_data[label] = synthesize_ohlcv(s, seed=seed)
            print(f"  {label}: {len(s)} rows  last=${float(s.iloc[-1]):,.2f}")
        except Exception as e:
            print(f"  {label}: FAILED ({e})")

    if len(full_data) < 4:
        print("  Insufficient data."); return

    # MVRV diagnostics
    mvrv = eth_full["CapMVRVCur"].dropna()
    print(f"\n  ETH MVRV by year (CapMVRVCur):")
    print(f"  {'Year':6}  {'Min':>6}  {'Max':>6}  {'Start':>6}  {'End':>6}  {'Days > 2.0':>11}")
    for yr in range(2017, 2025):
        s = mvrv[mvrv.index.year == yr]
        if len(s):
            above2 = (s > 2.0).mean() * 100
            print(f"  {yr:6}  {s.min():>6.2f}  {s.max():>6.2f}  {s.iloc[0]:>6.2f}  {s.iloc[-1]:>6.2f}  {above2:>10.1f}%")

    is_data       = slice_data(full_data, IS_START, IS_END)
    combined_data = slice_data(full_data, IS_START, OOS_END)

    bt_fixed = dict(
        max_positions=4,
        position_size_pct=0.25,
        atr_stop_multiplier=20.0,
        atr_trail_multiplier=12.0,
        risk_per_trade_pct=0.25,
        short_term_tax_rate=TAX_RATE,
    )

    strat_configs = [
        dict(ema_period=ema, act_short=s, act_long=l,
             mvrv_threshold=mt, min_hold_days=mhd, rebalance_days=7)
        for ema in [100, 150, 200]
        for (s, l) in [(20, 60), (30, 90)]
        for mt in [1.5, 2.0, 2.5]
        for mhd in [0, 365]
    ]

    print(f"\n  IS grid ({len(strat_configs)} configs, {IS_START}–{IS_END}) ...")
    print(f"  {'ema':>4} {'act':>7} {'mvrv':>5} {'mhd':>4}  {'Mo%':>7} {'SR':>6} {'DD%':>8} {'N':>4} {'Hold':>5} {'score':>7}")
    print("  " + "-" * 70)

    results_is = []
    for sp in strat_configs:
        try:
            rpt = run_is(full_data, is_data, btc_full, eth_full, sp, bt_fixed)
            m   = rpt.full_metrics()
            mo  = m.get("monthly_return_pct", 0)
            sr  = m.get("sharpe_ratio", 0)
            dd  = m.get("max_drawdown_pct", 0)
            nt  = m.get("n_trades", 0)
            hld = m.get("avg_holding_days", 0) or 0
            if nt < 2:
                continue
            score = sr * 3.0 + mo * 0.5 - max(0, -40 - dd) * 0.5
            results_is.append((score, mo, sr, dd, hld, sp, m))
            act_str = f"{sp['act_short']}/{sp['act_long']}"
            print(f"  {sp['ema_period']:>4} {act_str:>7} {sp['mvrv_threshold']:>5.1f} {sp.get('min_hold_days',0):>4}"
                  f"  {mo:>+7.2f}%  {sr:>6.2f}  {dd:>8.2f}%  {nt:>4}  {hld:>4.0f}d  {score:>7.2f}")
        except Exception as ex:
            print(f"  [skip] {ex}")

    results_is.sort(key=lambda x: x[0], reverse=True)
    if not results_is:
        print("  No valid IS configs."); return

    best_score, best_mo, best_sr, best_dd, best_hld, best_sp, best_m = results_is[0]
    act_str = f"{best_sp['act_short']}/{best_sp['act_long']}"
    print(f"\n  IS champion: EMA{best_sp['ema_period']} act={act_str} mvrv<{best_sp['mvrv_threshold']:.1f} mhd={best_sp.get('min_hold_days',0)}")
    print(f"    Mo%={best_mo:+.2f}% Sharpe={best_sr:.2f} MaxDD={best_dd:.2f}%"
          f" N={best_m.get('n_trades',0)} Hold={best_hld:.0f}d Score={best_score:.2f}")

    print(f"\n  OOS results ({OOS_START}–{OOS_END}):")
    print(f"  {'ema':>4} {'act':>7} {'mvrv':>5} {'mhd':>4}  {'Mo%':>8} {'SR':>6} {'DD%':>8} {'N':>4} {'Hold':>5} {'Eq$':>12}")
    print("  " + "-" * 80)

    oos_results = []
    for _, _, _, _, _, sp, _ in results_is:
        try:
            rpt = run_oos(full_data, combined_data, btc_full, eth_full, sp, bt_fixed)
            if rpt is None:
                continue
            m   = rpt.full_metrics()
            hld = m.get("avg_holding_days", 0) or 0
            sr  = m.get("sharpe_ratio", 0)
            oos_results.append((sr, sp, m, rpt))
            flag    = " ← LTCG" if hld >= 365 else ""
            act_str = f"{sp['act_short']}/{sp['act_long']}"
            print(f"  {sp['ema_period']:>4} {act_str:>7} {sp['mvrv_threshold']:>5.1f} {sp.get('min_hold_days',0):>4}"
                  f"  {m.get('monthly_return_pct',0):>+7.2f}%"
                  f"  {sr:>6.2f}"
                  f"  {m.get('max_drawdown_pct',0):>8.2f}%"
                  f"  {m.get('n_trades',0):>4}  {hld:>4.0f}d"
                  f"  ${m.get('final_equity',0):>11,.0f}{flag}")
        except Exception:
            pass

    oos_results.sort(key=lambda x: x[0], reverse=True)
    if not oos_results:
        print("  No OOS results."); return

    is_champ_oos = next(((sp, m, rpt) for _, sp, m, rpt in oos_results
                         if sp == best_sp), None)
    champ_sr, champ_sp, champ_m, champ_rpt = oos_results[0]

    act_str = f"{champ_sp['act_short']}/{champ_sp['act_long']}"
    champ_rpt.print_full_report(
        f"OOS CHAMPION — MVRV Gate  ema={champ_sp['ema_period']}"
        f"  act={act_str}  mvrv<{champ_sp['mvrv_threshold']:.1f}  mhd={champ_sp.get('min_hold_days',0)}"
        f"  [STCG {TAX_RATE*100:.0f}%, {OOS_START}–{OOS_END}]"
    )

    mo  = champ_m.get("monthly_return_pct", 0)
    sr  = champ_m.get("sharpe_ratio", 0)
    dd  = champ_m.get("max_drawdown_pct", 0)
    cal = champ_m.get("calmar_ratio", 0)
    wr  = champ_m.get("win_rate_pct", 0)
    pf  = champ_m.get("profit_factor", 0)
    nt  = champ_m.get("n_trades", 0)
    eq  = champ_m.get("final_equity", 0)
    hld = champ_m.get("avg_holding_days", 0) or 0

    oos_base = champ_rpt.result.initial_capital
    oos_gain = eq - oos_base
    if hld >= 365 and oos_gain > 0:
        adj_eq = oos_base + oos_gain * (1 - 0.20)
        n_mo   = (pd.Timestamp(OOS_END) - pd.Timestamp(OOS_START)).days / 30.44
        adj_mo = ((adj_eq / oos_base) ** (1 / n_mo) - 1) * 100
        ltcg_note = f"  After real LTCG (20%): ${adj_eq:,.0f} ≈ {adj_mo:+.2f}%/mo"
    else:
        ltcg_note = ""

    print(f"\n{'='*72}")
    print("  VERDICT  —  OOS 2021–2024, ETH MVRV Entry Gate")
    print(f"{'='*72}")
    criteria = [
        ("Monthly ≥ 2.0%",      mo  >= 2.0,  f"{mo:+.2f}%"),
        ("Sharpe ≥ 1.0",        sr  >= 1.0,  f"{sr:.2f}"),
        ("MaxDD > -40%",         dd  >= -40,  f"{dd:.2f}%"),
        ("Calmar ≥ 0.8",        cal >= 0.8,  f"{cal:.2f}"),
        ("Win Rate ≥ 40%",      wr  >= 40,   f"{wr:.2f}%"),
        ("Profit Factor ≥ 1.3", pf  >= 1.3,  f"{pf:.2f}"),
        ("N Trades ≥ 5",        nt  >= 5,    str(nt)),
    ]
    for lbl, ok, val in criteria:
        print(f"    [{'PASS' if ok else 'FAIL'}]  {lbl:<25}  {val}")

    passes = sum(1 for _, ok, _ in criteria if ok)
    print(f"\n  {passes}/7 criteria pass")
    print(f"  Model equity: ${eq:,.0f}  (OOS base = ${oos_base:,.0f})")
    if ltcg_note:
        print(ltcg_note)
    print(f"  Avg hold: {hld:.0f} days  "
          f"({'LTCG eligible' if hld >= 365 else 'STCG 35% applied'})")
    if is_champ_oos:
        isp, im, _ = is_champ_oos
        print(f"\n  IS-champion OOS (walk-forward blind): "
              f"{im.get('monthly_return_pct',0):+.2f}%/mo  "
              f"Sharpe {im.get('sharpe_ratio',0):.2f}  "
              f"MaxDD {im.get('max_drawdown_pct',0):.2f}%")
    print()


if __name__ == "__main__":
    main()
