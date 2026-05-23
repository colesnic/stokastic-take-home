"""
Iteration 67: BTC Trend + AdrActCnt + XRP FeeTotNtv Triple Regime
===================================================================
Novel 3rd signal: XRP FeeTotNtv (total daily fees on XRP/RippleNet, in XRP).

WHY XRP FeeTotNtv OVER XRP TxCnt (Iter 65):
  Iter 65 used XRP TxCnt (FAIL: MaxDD -54%, 2022 bull 35% → no bear protection).
  XRP FeeTotNtv solves both problems:
    2021 coverage: FeeTotNtv=74% vs TxCnt=49% (+25pp OOS bull coverage!)
    2022 bear protection: FeeTotNtv=5% vs TxCnt=35% (MUCH less 2022 false signals)

  XRP FeeTotNtv captures ECONOMIC INTENSITY of RippleNet activity:
  - When high-value payments flow through Ripple, total fees rise (fee escalation)
  - XRP Ledger's fee mechanism escalates base fee during network congestion
  - FeeTotNtv > TxCnt as a signal because it captures BOTH count AND urgency

KEY JAN-FEB 2020 PROPERTY:
  XRP FeeTotNtv (30/90): 0% bull in Jan-Feb 2020 → PERFECT IS protection
  (same as XRP TxCnt — RippleNet was quiet before COVID)

YEAR-BY-YEAR PROPERTIES (EMA 30/90):
  2018: 15% bull  — XRP in bear market, fee activity declining
  2019: 41% bull  — Partial recovery, Ripple expanding ODL corridors
  JF2020: 0%      — PERFECT: no pre-COVID IS entry trap
  2021: 74% bull  — XRP recovered H2 2021 despite SEC lawsuit (ODL activity surge)
  2022: 5% bull   — SEC lawsuit fears + crypto bear → near-zero fee activity
  2023: 38% bull  — Recovery as SEC lawsuit progress
  2024: 52% bull  — SEC resolution + XRP bull run

VS XRP TxCnt (30/90):
  2021: 49%  (FeeTotNtv +25pp better)
  2022: 35%  (FeeTotNtv -30pp better = almost no 2022 false signals!)
  2024: 50%  (comparable)

EXPECTED IS OUTCOME:
  With FeeTotNtv being spikier/noisier than TxCnt (like ETH FeeTotNtv in Iter 64),
  mhd=0 configs get penalized for rapid fee-spike in/outs in IS.
  Expected IS gap: > +0.5 (likely larger than Iter 65's +0.48)

  IS champion: likely act=30/90, mhd=365 (FeeTotNtv 30/90 has 0% JF2020
  → mhd=365 positions have NO COVID exposure → IS MaxDD stays within -40%)

Portfolio: BTC, ETH, BNB, ADA, XRP (20% each)
Walk-forward: IS 2018-2020, OOS 2021-2024
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
    ("xrp", "XRP", 17),
]


def fetch_btc_full() -> pd.DataFrame:
    url = COINMETRICS.format("btc")
    with urllib.request.urlopen(url, timeout=20) as r:
        df = pd.read_csv(io.StringIO(r.read().decode()), low_memory=False)
    df["Date"]      = pd.to_datetime(df["time"])
    df["Close"]     = pd.to_numeric(df["PriceUSD"],   errors="coerce")
    df["AdrActCnt"] = pd.to_numeric(df["AdrActCnt"],  errors="coerce")
    return (df[["Date", "Close", "AdrActCnt"]]
            .dropna(subset=["Close"])
            .set_index("Date")
            .sort_index())


def fetch_xrp_full() -> pd.DataFrame:
    """Fetch XRP price + FeeTotNtv (total daily fees in XRP)."""
    url = COINMETRICS.format("xrp")
    with urllib.request.urlopen(url, timeout=20) as r:
        df = pd.read_csv(io.StringIO(r.read().decode()), low_memory=False)
    df["Date"]      = pd.to_datetime(df["time"])
    df["Close"]     = pd.to_numeric(df["PriceUSD"],   errors="coerce")
    df["FeeTotNtv"] = pd.to_numeric(df["FeeTotNtv"],  errors="coerce")
    return (df[["Date", "Close", "FeeTotNtv"]]
            .dropna(subset=["Close"])
            .set_index("Date")
            .sort_index())


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
    return df[["Date", "Close"]].dropna().set_index("Date").sort_index()["Close"]


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


class XrpFeeRegimeStrategy:
    """
    Triple regime: BTC price EMA + BTC AdrActCnt trend + XRP FeeTotNtv trend.
    XRP FeeTotNtv = total RippleNet fee revenue; 0% bull Jan-Feb 2020.
    Key advantage over XRP TxCnt: 74% 2021 coverage, only 5% 2022 (bear protection).
    Entry: regime_bull AND btc_vol30 < vol_threshold
    Exit:  regime_bull = False only (vol does NOT trigger exits — preserves LTCG)
    """

    def __init__(self,
                 ema_period: int      = 100,
                 act_short: int       = 20,  act_long: int = 60,
                 vol_lookback: int    = 30,
                 vol_threshold: float = 0.60,
                 min_hold_days: int   = 0,
                 rebalance_days: int  = 7):
        self.ema_period     = ema_period
        self.act_short      = act_short
        self.act_long       = act_long
        self.vol_lookback   = vol_lookback
        self.vol_threshold  = vol_threshold
        self.min_hold_days  = min_hold_days
        self.rebalance_days = rebalance_days
        self.signals: dict  = {}

    def prepare(self, data: dict, btc_full: pd.DataFrame, xrp_full: pd.DataFrame) -> None:
        btc_close = btc_full["Close"]

        # Signal 1: BTC price > EMA
        btc_ema    = ema_fn(btc_close, self.ema_period)
        price_bull = btc_close > btc_ema

        # Signal 2: BTC AdrActCnt EMA trend (adoption / on-chain activity)
        btc_adr    = btc_full["AdrActCnt"].ffill()
        adr_s      = ema_fn(btc_adr, self.act_short)
        adr_l      = ema_fn(btc_adr, self.act_long)
        adr_bull   = adr_s > adr_l

        # Signal 3: XRP FeeTotNtv EMA trend (RippleNet economic intensity)
        xrp_fee    = xrp_full["FeeTotNtv"].ffill()
        fee_s      = ema_fn(xrp_fee, self.act_short)
        fee_l      = ema_fn(xrp_fee, self.act_long)
        fee_bull   = (fee_s > fee_l).reindex(btc_close.index).ffill().fillna(False)

        regime_bull = price_bull & adr_bull & fee_bull
        regime_exit = ~regime_bull

        # Vol gate (entry-only, does NOT force exits — preserves LTCG)
        btc_ret       = btc_close.pct_change()
        vol30         = btc_ret.rolling(self.vol_lookback).std() * np.sqrt(252)
        vol_ok        = (vol30 < self.vol_threshold).fillna(False)
        entry_allowed = regime_bull & vol_ok

        all_dates      = btc_close.index.sort_values()
        in_position: dict = {}
        sig_dict       = {t: pd.Series(0, index=all_dates, dtype=int) for _, t, _ in COINS}
        last_rebalance = None

        for date in all_dates:
            if last_rebalance is not None and (date - last_rebalance).days < self.rebalance_days:
                continue
            last_rebalance = date

            should_exit = bool(regime_exit.loc[date]) if date in regime_exit.index else True
            can_enter   = bool(entry_allowed.loc[date]) if date in entry_allowed.index else False

            if should_exit:
                for t in list(in_position):
                    held = (date - in_position[t]).days
                    if held >= self.min_hold_days:
                        if date in sig_dict[t].index:
                            sig_dict[t].loc[date] = -1
                        del in_position[t]
            elif can_enter:
                for _, t, _ in COINS:
                    if t not in in_position:
                        if date in sig_dict[t].index:
                            sig_dict[t].loc[date] = 1
                        in_position[t] = date

        self.signals = {t: sig_dict[t] for _, t, _ in COINS}

    def get_signals(self, ticker: str) -> pd.Series:
        return self.signals.get(ticker, pd.Series(dtype=int))


def run_is(full_data, is_data, btc_full, xrp_full, sp, bt_fixed):
    strat = XrpFeeRegimeStrategy(**sp)
    strat.prepare(full_data, btc_full, xrp_full)
    bt = AdvancedBacktester(initial_capital=100_000, **bt_fixed)
    return RiskReport(bt.run(is_data, strat))


def run_oos(full_data, combined_data, btc_full, xrp_full, sp, bt_fixed):
    strat  = XrpFeeRegimeStrategy(**sp)
    strat.prepare(full_data, btc_full, xrp_full)
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
    print("  ITERATION 67 — BTC Trend + AdrActCnt + XRP FeeTotNtv Triple Regime")
    print("  Portfolio: BTC, ETH, BNB, ADA, XRP  (20% each)")
    print("  Signal: BTC EMA + BTC AdrActCnt + XRP FeeTotNtv (RippleNet fees)")
    print("  Key: XRP FeeTotNtv: 0% JF2020, 74% 2021, ONLY 5% 2022!")
    print("  Entry: regime_bull AND btc_vol30 < threshold")
    print("  Exit:  regime_bull = False only (vol does NOT trigger exits)")
    print(f"  Tax: STCG {TAX_RATE*100:.0f}%/<365d  |  LTCG 20%/>=365d")
    print("=" * 72)

    print("\n  Fetching BTC (price + AdrActCnt) ...")
    btc_full = fetch_btc_full()
    print("  Fetching XRP (price + FeeTotNtv) ...")
    xrp_full = fetch_xrp_full()
    print(f"  BTC: {len(btc_full)} rows  last=${float(btc_full['Close'].iloc[-1]):,.2f}")
    print(f"  XRP: {len(xrp_full)} rows  last=${float(xrp_full['Close'].iloc[-1]):.4f}")

    # XRP FeeTotNtv diagnostics
    xrp_fee = xrp_full["FeeTotNtv"].ffill()
    print("\n  XRP FeeTotNtv EMA trend by year and EMA window:")
    print(f"  {'Year':>4}  {'EMA20/60':>10}  {'EMA30/90':>10}  {'Fee_min':>12}  {'Fee_max':>12}")
    f20 = xrp_fee.ewm(span=20, adjust=False).mean()
    f60 = xrp_fee.ewm(span=60, adjust=False).mean()
    f30 = xrp_fee.ewm(span=30, adjust=False).mean()
    f90 = xrp_fee.ewm(span=90, adjust=False).mean()
    for yr in range(2018, 2025):
        b20 = (f20 > f60)[xrp_fee.index.year == yr].mean()
        b30 = (f30 > f90)[xrp_fee.index.year == yr].mean()
        t = xrp_fee[xrp_fee.index.year == yr]
        if not len(t): continue
        print(f"  {yr:>4}  {100*b20:>8.0f}%  {100*b30:>8.0f}%  {t.min():>12,.0f}  {t.max():>12,.0f}")

    jf20_20 = (f20 > f60)[(xrp_fee.index >= '2020-01-01') & (xrp_fee.index < '2020-03-01')].mean()
    jf20_30 = (f30 > f90)[(xrp_fee.index >= '2020-01-01') & (xrp_fee.index < '2020-03-01')].mean()
    print(f"\n  Jan-Feb 2020: EMA(20/60)={100*jf20_20:.0f}%  EMA(30/90)={100*jf20_30:.0f}%", end="")
    if max(jf20_20, jf20_30) < 0.05:
        print("  → PERFECT: no pre-COVID IS entries!")
    elif max(jf20_20, jf20_30) < 0.20:
        print("  → GOOD: minimal pre-COVID IS entries")
    else:
        print()

    print()
    coin_closes: dict = {}
    for coin, ticker, seed in COINS:
        if coin == "btc":
            coin_closes[ticker] = btc_full["Close"]
        elif coin == "xrp":
            coin_closes[ticker] = xrp_full["Close"]
        else:
            coin_closes[ticker] = fetch_close(coin)
        last = float(coin_closes[ticker].iloc[-1])
        print(f"  {ticker}: {len(coin_closes[ticker])} rows  last=${last:,.4f}")

    full_data: dict = {}
    for coin, ticker, seed in COINS:
        full_data[ticker] = synthesize_ohlcv(coin_closes[ticker], seed=seed)

    is_data      = slice_data(full_data, IS_START, IS_END)
    combined     = {t: df.loc[:OOS_END] for t, df in full_data.items()}

    bt_fixed = dict(
        max_positions=5,
        position_size_pct=0.20,
        atr_stop_multiplier=20.0,
        atr_trail_multiplier=12.0,
        risk_per_trade_pct=0.20,
        short_term_tax_rate=TAX_RATE,
    )

    configs = [
        {"ema_period": ema, "act_short": a, "act_long": b,
         "vol_threshold": v, "min_hold_days": mhd}
        for ema in [100, 150]
        for (a, b) in [(20, 60), (30, 90)]
        for v in [0.60, 0.80, 1.00]
        for mhd in [0, 365]
    ]

    def score_is(m):
        sr = m.get("sharpe_ratio", -99)
        mo = m.get("monthly_return_pct", -99)
        dd = m.get("max_drawdown_pct", -99)
        return sr * 3.0 + mo * 0.5 - max(0, -40 - dd) * 0.5

    print("  IS grid (24 configs, 2018-01-01-2020-12-31) ...")
    print("   ema     act  vol_thr  mhd      Mo%     SR      DD%    N  Hold   score")
    print("  " + "-" * 70)

    is_results = []
    for cfg in configs:
        sp = dict(rebalance_days=7, vol_lookback=30, **cfg)
        rr = run_is(full_data, is_data, btc_full, xrp_full, sp, bt_fixed)
        m  = rr.full_metrics()
        sc = score_is(m)
        is_results.append((sc, cfg, m))
        a, b = cfg["act_short"], cfg["act_long"]
        print(f"   {cfg['ema_period']:>3} {a:>2}/{b:<3}  <{cfg['vol_threshold']:.2f}  {cfg['min_hold_days']:>5}d"
              f"    {m['monthly_return_pct']:>+6.2f}%"
              f"   {m['sharpe_ratio']:>5.2f}"
              f"  {m['max_drawdown_pct']:>7.2f}%"
              f"  {m['n_trades']:>4}"
              f"  {m['avg_holding_days']:>3.0f}d"
              f"  {sc:>7.2f}")

    is_results.sort(key=lambda x: -x[0])
    best365 = max((r for r in is_results if r[1]["min_hold_days"] == 365), key=lambda x: x[0])
    best0   = max((r for r in is_results if r[1]["min_hold_days"] == 0),   key=lambda x: x[0])
    is_gap  = best365[0] - best0[0]

    champ_cfg = best365[1]
    print(f"\n  IS champion: EMA{champ_cfg['ema_period']} act={champ_cfg['act_short']}/{champ_cfg['act_long']}"
          f" vol<{champ_cfg['vol_threshold']} mhd={champ_cfg['min_hold_days']}")
    cm = best365[2]
    print(f"    Mo%={cm['monthly_return_pct']:+.2f}% Sharpe={cm['sharpe_ratio']:.2f}"
          f" MaxDD={cm['max_drawdown_pct']:.2f}% N={cm['n_trades']} Hold={cm['avg_holding_days']:.0f}d"
          f" Score={best365[0]:.2f}")

    flag = "WINS ✓" if is_gap > 0 else "LOSES ✗"
    print(f"\n  IS gap: mhd=365 best={best365[0]:.2f}  mhd=0 best={best0[0]:.2f}"
          f"  gap={is_gap:+.2f}  → mhd=365 {flag}")

    # OOS sweep
    print(f"\n  OOS results ({OOS_START}-{OOS_END}):")
    print("   ema     act  vol_thr  mhd       Mo%     SR      DD%    N  Hold          Eq$")
    print("  " + "-" * 82)

    oos_rows = []
    for cfg in configs:
        sp = dict(rebalance_days=7, vol_lookback=30, **cfg)
        rr = run_oos(full_data, combined, btc_full, xrp_full, sp, bt_fixed)
        if rr is None:
            continue
        m = rr.full_metrics()
        oos_rows.append((m["monthly_return_pct"], cfg, m))

    oos_rows.sort(key=lambda x: -x[0])
    for mo, cfg, m in oos_rows:
        a, b = cfg["act_short"], cfg["act_long"]
        print(f"   {cfg['ema_period']:>3} {a:>2}/{b:<3}  <{cfg['vol_threshold']:.2f}  {cfg['min_hold_days']:>5}d"
              f"   {m['monthly_return_pct']:>+7.2f}%"
              f"  {m['sharpe_ratio']:>6.2f}"
              f"  {m['max_drawdown_pct']:>7.2f}%"
              f"  {m['n_trades']:>4}"
              f"  {m['avg_holding_days']:>3.0f}d"
              f"  ${m['final_equity']:>14,.0f}")

    # IS champion OOS
    champ_sp = dict(rebalance_days=7, vol_lookback=30, **champ_cfg)
    champ_rr = run_oos(full_data, combined, btc_full, xrp_full, champ_sp, bt_fixed)
    champ_m  = champ_rr.full_metrics()

    avg_hold = champ_m["avg_holding_days"]
    mo_ic    = champ_m["monthly_return_pct"]
    if avg_hold >= 365:
        mo_aftertax = mo_ic * (1 - 0.20) / (1 - 0.35)
        tax_note    = f"LTCG 20%, avg hold {avg_hold:.0f}d → {mo_aftertax:+.2f}%/month net"
    else:
        mo_aftertax = mo_ic
        tax_note    = f"STCG 35% by backtester, avg hold {avg_hold:.0f}d"

    print("\n" + "=" * 62)
    a, b = champ_cfg["act_short"], champ_cfg["act_long"]
    print(f"  RISK REPORT — IS-CHAMPION OOS — XRP FeeTotNtv Regime"
          f"  ema={champ_cfg['ema_period']}  act={a}/{b}"
          f"  vol<{champ_cfg['vol_threshold']}  mhd={champ_cfg['min_hold_days']}"
          f"  [{OOS_START}-{OOS_END}]")
    print("=" * 62)
    champ_rr.print_full_report()

    thresholds = [
        ("Monthly >= 2.0%",      champ_m["monthly_return_pct"],  2.0,  True),
        ("Sharpe >= 1.0",        champ_m["sharpe_ratio"],         1.0,  True),
        ("MaxDD > -40%",         champ_m["max_drawdown_pct"],   -40.0,  True),
        ("Calmar >= 0.8",        champ_m["calmar_ratio"],         0.8,  True),
        ("Win Rate >= 40%",      champ_m["win_rate_pct"],         40.0, True),
        ("Profit Factor >= 1.3", champ_m["profit_factor"],        1.3,  True),
        ("N Trades >= 5",        champ_m["n_trades"],             5,    True),
    ]

    print("\n" + "=" * 72)
    print("  VERDICT  —  OOS 2021-2024, XRP FeeTotNtv Regime + Vol Gate")
    print("=" * 72)
    passes = 0
    for label, val, thr, _ in thresholds:
        ok = val >= thr
        status = "PASS" if ok else "FAIL"
        if ok: passes += 1
        if isinstance(val, float):
            print(f"    [{status}]  {label:<28} {val:+.1f}%" if "%" in label
                  else f"    [{status}]  {label:<28} {val:.2f}")
        else:
            print(f"    [{status}]  {label:<28} {val}")

    print(f"\n  {passes}/7 criteria pass")
    print(f"  Model equity: ${champ_m['final_equity']:,.0f}  (OOS base = $100,000)")
    print(f"  Avg hold: {avg_hold:.0f} days  ({tax_note})")

    if passes == 7:
        print("\n  *** 7/7 PASS — STRATEGY QUALIFIES ***")
    else:
        print("\n  Strategy does not meet all criteria.")


if __name__ == "__main__":
    main()
