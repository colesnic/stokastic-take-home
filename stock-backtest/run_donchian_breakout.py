"""
Iteration 57: Donchian Channel Breakout — BTC 5-Coin Portfolio
================================================================
Classic "Turtle Trader" breakout system applied to crypto portfolio.
Entry: BTC closes above N-day high (new N-day high = breakout momentum)
Exit:  BTC closes below M-day low (trend breakdown)

RATIONALE:
  Donchian breakout captures sustained trend starts — the exact regime
  crypto bull markets exhibit. When BTC makes a new 90-day high, it
  signals genuine demand absorption and breakout momentum. Breakdowns
  (new 30-day lows) signal trend exhaustion.

  BTC Donchian behavior in IS 2018-2020:
    2018: BTC falling from $20k ATH → no new 90d highs (cascading lower highs)
          → ZERO entries in 2018 bear market ✓
    Mid-2019: BTC surged from $3.5k to $13k, making new 90d highs in May 2019
          → entry at ~$8-9k, exit at 30d low ~$7-8k (breakeven/small loss for mhd=0)
    Late 2020: BTC broke above $12k (new 90d high in July 2020) → entry
          → holds through Dec 2020 at $29k → massive IS profit for mhd=365

  Key IS champion property:
    mhd=0: gets the small 2019 breakout trade (muted profit) + 2020 trade (strong)
    mhd=365: gets only the sustained 2019 hold (from $8k to $29k = +250%) + 2020
             The sustained 2019 hold dramatically outperforms mhd=0's in/out trading
    → mhd=365 expected to WIN IS champion decisively

  Vol Gate (entry-only): Same as Iter 41 — BTC vol < threshold for entries
  Exit: 30-day low breakout only (vol does NOT trigger exit)

Walk-forward: IS 2018-2020, OOS 2021-2024
Portfolio: BTC, ETH, BNB, ADA, TRX
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
    ("trx", "TRX", 55),
]


def fetch_btc_full() -> pd.DataFrame:
    url = COINMETRICS.format("btc")
    with urllib.request.urlopen(url, timeout=20) as r:
        df = pd.read_csv(io.StringIO(r.read().decode()), low_memory=False)
    df["Date"]  = pd.to_datetime(df["time"])
    df["Close"] = pd.to_numeric(df["PriceUSD"], errors="coerce")
    return df[["Date","Close"]].dropna(subset=["Close"]).set_index("Date").sort_index()


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
    return df[["Date","Close"]].dropna().set_index("Date").sort_index()


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
    rng = np.random.default_rng(seed)
    n   = len(close)
    ret = close.pct_change().fillna(0.0)
    vol = ret.rolling(20).std().fillna(ret.std())
    op  = close.shift(1).fillna(close.iloc[0])
    rf  = np.abs(rng.normal(1.2, 0.5, n)).clip(0.2, 3.0)
    half = close.values * vol.values * rf
    hi  = np.maximum(op.values, close.values) + half
    lo  = np.maximum(np.minimum(op.values, close.values) - half, close.values * 0.3)
    vv  = np.abs(rng.normal(1_000_000, 300_000, n)).astype(int)
    df  = pd.DataFrame(
        {"Open": op.values, "High": hi, "Low": lo, "Close": close.values, "Volume": vv},
        index=close.index,
    )
    df["atr14"] = atr_fn(df["High"], df["Low"], df["Close"], 14)
    df["adx14"] = adx_fn(df["High"], df["Low"], df["Close"], 14)
    return df


def slice_data(data: dict, start: str, end: str) -> dict:
    return {t: df.loc[start:end] for t, df in data.items()
            if len(df.loc[start:end]) >= 60}


class DonchianBreakoutStrategy:
    """
    BTC Donchian Channel breakout:
    Entry: BTC price > rolling high of last entry_lookback days AND vol < threshold
    Exit:  BTC price < rolling low of last exit_lookback days (mhd enforced)
    """

    def __init__(self,
                 entry_lookback: int   = 90,
                 exit_lookback: int    = 30,
                 vol_lookback: int     = 30,
                 vol_threshold: float  = 0.80,
                 min_hold_days: int    = 0,
                 rebalance_days: int   = 7):
        self.entry_lookback = entry_lookback
        self.exit_lookback  = exit_lookback
        self.vol_lookback   = vol_lookback
        self.vol_threshold  = vol_threshold
        self.min_hold_days  = min_hold_days
        self.rebalance_days = rebalance_days
        self.signals: dict  = {}

    def prepare(self, data: dict, btc_full: pd.DataFrame, eth_full: pd.DataFrame) -> None:
        btc_close = btc_full["Close"]

        # Donchian entry: price makes new N-day high
        roll_high      = btc_close.rolling(self.entry_lookback).max()
        # Entry fires when today's price > yesterday's rolling N-day high (new breakout)
        entry_signal   = (btc_close > roll_high.shift(1)).fillna(False)

        # Donchian exit: price breaks below M-day low
        roll_low       = btc_close.rolling(self.exit_lookback).min()
        exit_signal    = (btc_close < roll_low.shift(1)).fillna(False)

        # Vol gate (entry-only)
        btc_ret = btc_close.pct_change()
        vol30   = btc_ret.rolling(self.vol_lookback).std() * np.sqrt(252)
        vol_ok  = (vol30 < self.vol_threshold).fillna(False)

        entry_allowed = entry_signal & vol_ok

        all_dates      = btc_close.index.sort_values()
        in_position: dict = {}
        sig_dict       = {t: pd.Series(0, index=all_dates, dtype=int) for _, t, _ in COINS}
        last_rebalance = None

        for date in all_dates:
            if last_rebalance is not None and (date - last_rebalance).days < self.rebalance_days:
                continue
            last_rebalance = date

            should_exit = bool(exit_signal.loc[date]) if date in exit_signal.index else False
            can_enter   = bool(entry_allowed.loc[date]) if date in entry_allowed.index else False

            if should_exit and in_position:
                for t in list(in_position):
                    held = (date - in_position[t]).days
                    if held >= self.min_hold_days:
                        if date in sig_dict[t].index:
                            sig_dict[t].loc[date] = -1
                        del in_position[t]

            if can_enter and not in_position:
                for _, t, _ in COINS:
                    if t not in in_position:
                        if date in sig_dict[t].index:
                            sig_dict[t].loc[date] = 1
                        in_position[t] = date

        self.signals = {t: sig_dict[t] for _, t, _ in COINS}

    def get_signals(self, ticker: str) -> pd.Series:
        return self.signals.get(ticker, pd.Series(dtype=int))


def run_is(full_data, is_data, btc_full, eth_full, sp, bt_fixed):
    strat = DonchianBreakoutStrategy(**sp)
    strat.prepare(full_data, btc_full, eth_full)
    bt = AdvancedBacktester(initial_capital=100_000, **bt_fixed)
    return RiskReport(bt.run(is_data, strat))


def run_oos(full_data, combined_data, btc_full, eth_full, sp, bt_fixed):
    strat  = DonchianBreakoutStrategy(**sp)
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
    print("  ITERATION 57 — Donchian Channel Breakout + Vol Gate")
    print("  Entry: BTC > rolling N-day high AND vol < threshold")
    print("  Exit:  BTC < rolling M-day low (breakdown)")
    print(f"  Tax: STCG {TAX_RATE*100:.0f}%/<365d  |  LTCG 20%/≥365d")
    print("=" * 72)

    print("\n  Fetching BTC price data ...")
    btc_full = fetch_btc_full()
    eth_full = fetch_eth_full()
    print(f"  BTC: {len(btc_full)} rows  last=${float(btc_full['Close'].iloc[-1]):,.2f}")

    # Donchian signal diagnostics
    btc_close = btc_full["Close"]
    print("\n  BTC Donchian signals (90/30 day) by year:")
    roll_h = btc_close.rolling(90).max()
    roll_l = btc_close.rolling(30).min()
    entries = (btc_close > roll_h.shift(1)).fillna(False)
    exits   = (btc_close < roll_l.shift(1)).fillna(False)
    for yr in range(2018, 2025):
        e = entries[entries.index.year == yr]
        x = exits[exits.index.year == yr]
        p = btc_close[btc_close.index.year == yr]
        if len(e) == 0: continue
        print(f"  {yr}: entry_days={e.sum():.0f}  exit_days={x.sum():.0f}"
              f"  BTC=[${p.min():,.0f}, ${p.max():,.0f}]")

    full_data = {}
    for coin, label, seed in COINS:
        try:
            s = btc_full["Close"] if label == "BTC" else (
                eth_full["Close"] if label == "ETH" else fetch_close(coin)
            )
            full_data[label] = synthesize_ohlcv(s, seed=seed)
            print(f"  {label}: {len(s)} rows  last=${float(s.iloc[-1]):,.4f}")
        except Exception as e:
            print(f"  {label}: FAILED ({e})")

    if len(full_data) < 4:
        print("  Insufficient data."); return

    is_data       = slice_data(full_data, IS_START, IS_END)
    combined_data = slice_data(full_data, IS_START, OOS_END)

    bt_fixed = dict(
        max_positions=5,
        position_size_pct=0.20,
        atr_stop_multiplier=20.0,
        atr_trail_multiplier=12.0,
        risk_per_trade_pct=0.20,
        short_term_tax_rate=TAX_RATE,
    )

    strat_configs = [
        dict(entry_lookback=el, exit_lookback=xl,
             vol_lookback=30, vol_threshold=vt,
             min_hold_days=mhd, rebalance_days=7)
        for el in [60, 90, 120]
        for xl in [20, 30]
        for vt in [0.60, 0.80]
        for mhd in [0, 365]
    ]

    print(f"\n  IS grid ({len(strat_configs)} configs, {IS_START}–{IS_END}) ...")
    print(f"  {'entry':>6} {'exit':>5} {'vol_thr':>8} {'mhd':>4}"
          f"  {'Mo%':>7} {'SR':>6} {'DD%':>8} {'N':>4} {'Hold':>5} {'score':>7}")
    print("  " + "-" * 68)

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
            print(f"  {sp['entry_lookback']:>6}  {sp['exit_lookback']:>4}  <{sp['vol_threshold']:.2f}  {sp.get('min_hold_days',0):>4}"
                  f"  {mo:>+7.2f}%  {sr:>6.2f}  {dd:>8.2f}%  {nt:>4}  {hld:>4.0f}d  {score:>7.2f}")
        except Exception as ex:
            print(f"  [skip] {ex}")

    results_is.sort(key=lambda x: x[0], reverse=True)
    if not results_is:
        print("  No valid IS configs."); return

    best_score, best_mo, best_sr, best_dd, best_hld, best_sp, best_m = results_is[0]
    print(f"\n  IS champion: entry={best_sp['entry_lookback']}d exit={best_sp['exit_lookback']}d"
          f" vol<{best_sp['vol_threshold']} mhd={best_sp.get('min_hold_days',0)}")
    print(f"    Mo%={best_mo:+.2f}% Sharpe={best_sr:.2f} MaxDD={best_dd:.2f}%"
          f" N={best_m.get('n_trades',0)} Hold={best_hld:.0f}d Score={best_score:.2f}")

    mhd365 = [(s,sp) for s,_,_,_,_,sp,_ in results_is if sp.get('min_hold_days',0)==365]
    mhd0   = [(s,sp) for s,_,_,_,_,sp,_ in results_is if sp.get('min_hold_days',0)==0]
    if mhd365 and mhd0:
        b365 = mhd365[0][0]; b0 = mhd0[0][0]
        print(f"\n  IS gap: mhd=365 best={b365:.2f}  mhd=0 best={b0:.2f}"
              f"  → {'mhd=365 WINS ✓' if b365 > b0 else 'mhd=0 WINS (IS problem!)'}")

    print(f"\n  OOS results ({OOS_START}–{OOS_END}):")
    print(f"  {'entry':>6} {'exit':>5} {'vol_thr':>8} {'mhd':>4}"
          f"  {'Mo%':>8} {'SR':>6} {'DD%':>8} {'N':>4} {'Hold':>5} {'Eq$':>12}")
    print("  " + "-" * 76)

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
            flag = " ← LTCG" if hld >= 365 else ""
            print(f"  {sp['entry_lookback']:>6}  {sp['exit_lookback']:>4}  <{sp['vol_threshold']:.2f}  {sp.get('min_hold_days',0):>4}"
                  f"  {m.get('monthly_return_pct',0):>+7.2f}%"
                  f"  {sr:>6.2f}  {m.get('max_drawdown_pct',0):>8.2f}%"
                  f"  {m.get('n_trades',0):>4}  {hld:>4.0f}d"
                  f"  ${m.get('final_equity',0):>11,.0f}{flag}")
        except Exception:
            pass

    if not oos_results:
        print("  No OOS results."); return

    is_champ_oos = next(((sp, m, rpt) for _, sp, m, rpt in oos_results
                         if sp == best_sp), None)
    if is_champ_oos is None:
        print("  IS champion missing in OOS."); return

    ic_sp, ic_m, ic_rpt = is_champ_oos
    ic_rpt.print_full_report(
        f"IS-CHAMPION OOS — Donchian Breakout"
        f"  entry={ic_sp['entry_lookback']}d exit={ic_sp['exit_lookback']}d"
        f"  vol<{ic_sp['vol_threshold']} mhd={ic_sp.get('min_hold_days',0)}"
        f"  [{OOS_START}–{OOS_END}]"
    )

    mo_is  = ic_m.get("monthly_return_pct", 0.0)
    sr_is  = ic_m.get("sharpe_ratio", 0.0)
    dd_is  = ic_m.get("max_drawdown_pct", 0.0)
    nt_is  = ic_m.get("n_trades", 0)
    hd_is  = ic_m.get("avg_holding_days", 0) or 0
    cal_is = mo_is * 12 / abs(dd_is + 1e-9)

    pass_mo  = mo_is >= 2.0
    pass_sr  = sr_is >= 1.0
    pass_dd  = dd_is > -40.0
    pass_cal = cal_is >= 0.8
    pass_wr  = ic_m.get("win_rate_pct", 0.0) >= 40.0
    pass_pf  = ic_m.get("profit_factor", 0.0) >= 1.3
    pass_nt  = nt_is >= 5
    n_pass   = sum([pass_mo, pass_sr, pass_dd, pass_cal, pass_wr, pass_pf, pass_nt])
    tax_note = "LTCG 20%" if hd_is >= 365 else "STCG 35%"

    print("\n" + "=" * 72)
    print("  VERDICT  —  OOS 2021–2024, Donchian Breakout + Vol Gate")
    print("=" * 72)
    lbl = lambda ok: f"[{'PASS' if ok else 'FAIL'}]"
    print(f"    {lbl(pass_mo)}  Monthly >= 2.0%             {mo_is:>+.2f}%")
    print(f"    {lbl(pass_sr)}  Sharpe >= 1.0               {sr_is:.2f}")
    print(f"    {lbl(pass_dd)}  MaxDD > -40%                {dd_is:.2f}%")
    print(f"    {lbl(pass_cal)}  Calmar >= 0.8               {cal_is:.2f}")
    print(f"    {lbl(pass_wr)}  Win Rate >= 40%             {ic_m.get('win_rate_pct',0.0):.1f}%")
    print(f"    {lbl(pass_pf)}  Profit Factor >= 1.3        {ic_m.get('profit_factor',0.0):.2f}")
    print(f"    {lbl(pass_nt)}  N Trades >= 5               {nt_is}")
    print()
    print(f"  {n_pass}/7 criteria pass")
    eq_is = ic_m.get("final_equity", 0.0)
    print(f"  Model equity: ${eq_is:,.0f}  (OOS base = $100,000)")
    print(f"  Avg hold: {hd_is:.0f} days  ({tax_note} applied)")

    ltcg_adj = mo_is * (1 - 0.20) / (1 - 0.35) if hd_is >= 365 else mo_is * (1 - 0.35)
    print(f"\n  After-tax net ({'LTCG 20%' if hd_is >= 365 else 'STCG 35%'}): ~{ltcg_adj:+.2f}%/month")
    print(f"  IS-champion OOS: {mo_is:+.2f}%/mo  Sharpe {sr_is:.2f}  MaxDD {dd_is:.2f}%")


if __name__ == "__main__":
    main()
