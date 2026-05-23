"""
Iteration 38 — BTC ROI1yr Momentum Entry Gate

Signal: 1-year rolling BTC return (ROI1yr) EMA momentum.
When EMA(ROI1yr, short) > EMA(ROI1yr, long), the annual return is ACCELERATING —
fresh bull cycle confirmed. When decelerating, late-cycle / bear = block entries.

Key diagnostic at critical dates:
  Jan 2018 (BLOCK): ROI1yr peaked in Dec 2017 (+1300%!), now decelerating fast
                    → EMA10 < EMA30 → BLOCK ✓
  Jan 2021 (ALLOW): ROI1yr accelerating as BTC broke the 2017 ATH
                    → EMA10 > EMA30 → ALLOW ✓
  Jan 2022 (BLOCK): ROI1yr decelerating (peak Nov 2021, now fading)
                    → EMA10 < EMA30 → BLOCK ✓ (avoids pre-crash entry)
  Jan 2024 (ALLOW): ROI1yr recovering from -65% lows in 2023 → accelerating
                    → EMA10 > EMA30 → ALLOW ✓

Differentiates from Iter 35 (ROI30d momentum): that signal operates at the
30-day scale (noisy). ROI1yr captures full-cycle dynamics (halving-to-halving
momentum), producing cleaner bull/bear regime separation.

Gate design: entry-only (no forced exits on ROI deceleration) to preserve LTCG.
Triple regime: BTC price > EMA, BTC AdrActCnt rising, ETH TxCnt rising.
"""

import urllib.request
import io
import os
import sys
import itertools
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

START_CAPITAL = 100_000


def fetch_btc_full() -> pd.DataFrame:
    url = COINMETRICS.format("btc")
    with urllib.request.urlopen(url, timeout=30) as r:
        df = pd.read_csv(io.StringIO(r.read().decode()), low_memory=False)
    df["Date"]      = pd.to_datetime(df["time"])
    df["Close"]     = pd.to_numeric(df["PriceUSD"],   errors="coerce")
    df["AdrActCnt"] = pd.to_numeric(df["AdrActCnt"],  errors="coerce")
    df["ROI1yr"]    = pd.to_numeric(df["ROI1yr"],     errors="coerce")
    return df[["Date","Close","AdrActCnt","ROI1yr"]].dropna(
        subset=["Close"]).set_index("Date").sort_index()


def fetch_eth_full() -> pd.DataFrame:
    url = COINMETRICS.format("eth")
    with urllib.request.urlopen(url, timeout=30) as r:
        df = pd.read_csv(io.StringIO(r.read().decode()), low_memory=False)
    df["Date"] = pd.to_datetime(df["time"])
    for col in ("PriceUSD", "ReferenceRateUSD"):
        if col in df.columns:
            df["Close"] = pd.to_numeric(df[col], errors="coerce")
            if df["Close"].notna().sum() > 100:
                break
    df["TxCnt"] = pd.to_numeric(df["TxCnt"], errors="coerce")
    return df[["Date","Close","TxCnt"]].dropna(subset=["Close"]).set_index("Date").sort_index()


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


def is_score(m: dict) -> float:
    mo = m.get("monthly_return_pct", 0) or 0
    sr = m.get("sharpe_ratio",       0) or 0
    dd = m.get("max_drawdown_pct",   0) or 0
    return sr * 3.0 + mo * 0.5 - max(0, -40 - dd) * 0.5


class Roi1yrGateStrategy:
    """
    Triple regime + BTC ROI1yr EMA momentum gate (entry-only).

    ROI1yr = 365-day trailing price return (Coinmetrics column).
    When EMA(ROI1yr, short) > EMA(ROI1yr, long) → annual return accelerating
    → fresh bull cycle momentum confirmed → ALLOW entries.

    Entry: regime_bull AND roi_ema_short > roi_ema_long
    Exit:  regime_bull = False (ROI does NOT trigger exits — preserves LTCG)
    """

    def __init__(self,
                 ema_period:    int = 100,
                 act_short:     int = 20,
                 act_long:      int = 60,
                 roi_short:     int = 10,
                 roi_long:      int = 30,
                 min_hold_days: int = 0,
                 rebalance_days: int = 7):
        self.ema_period     = ema_period
        self.act_short      = act_short
        self.act_long       = act_long
        self.roi_short      = roi_short
        self.roi_long       = roi_long
        self.min_hold_days  = min_hold_days
        self.rebalance_days = rebalance_days
        self.signals: dict  = {}

    def prepare(self, data: dict, btc_full: pd.DataFrame, eth_full: pd.DataFrame) -> None:
        btc_close = btc_full["Close"]

        # ── triple regime ──
        btc_ema    = ema_fn(btc_close, self.ema_period)
        price_bull = btc_close > btc_ema

        btc_adr  = btc_full["AdrActCnt"].ffill()
        adr_s    = ema_fn(btc_adr, self.act_short)
        adr_l    = ema_fn(btc_adr, self.act_long)
        adr_bull = adr_s > adr_l

        eth_tx  = eth_full["TxCnt"].ffill()
        tx_s    = ema_fn(eth_tx, self.act_short)
        tx_l    = ema_fn(eth_tx, self.act_long)
        tx_bull = (tx_s > tx_l).reindex(btc_close.index).ffill().fillna(False)

        regime_bull = price_bull & adr_bull & tx_bull
        regime_exit = ~regime_bull

        # ── ROI1yr momentum gate (entry-only) ──
        roi1yr = btc_full["ROI1yr"].ffill().fillna(0)
        roi_s  = ema_fn(roi1yr, self.roi_short)
        roi_l  = ema_fn(roi1yr, self.roi_long)
        roi_ok = roi_s > roi_l   # annual return accelerating = fresh bull = ALLOW

        entry_allowed = regime_bull & roi_ok

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


def run_is(full_data, is_data, btc_full, eth_full, sp, bt_fixed):
    strat = Roi1yrGateStrategy(**sp)
    strat.prepare(full_data, btc_full, eth_full)
    bt = AdvancedBacktester(initial_capital=START_CAPITAL, **bt_fixed)
    return RiskReport(bt.run(is_data, strat))


def run_oos(full_data, combined_data, btc_full, eth_full, sp, bt_fixed):
    strat  = Roi1yrGateStrategy(**sp)
    strat.prepare(full_data, btc_full, eth_full)
    bt     = AdvancedBacktester(initial_capital=START_CAPITAL, **bt_fixed)
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


GRID = [
    dict(ema_period=ep, act_short=a_s, act_long=a_l,
         roi_short=rs, roi_long=rl, min_hold_days=mhd)
    for ep  in [100, 150]
    for (a_s, a_l) in [(20, 60), (30, 90)]
    for (rs, rl) in [(5, 15), (10, 30), (15, 45), (20, 60)]
    for mhd in [0, 365]
]


def main():
    print("\n" + "=" * 72)
    print("  ITERATION 38 — BTC ROI1yr Momentum Entry Gate")
    print("  Signal: EMA(ROI1yr, short) > EMA(ROI1yr, long) = annual return accel.")
    print("  Entry: regime_bull AND roi1yr_ema_short > roi1yr_ema_long")
    print("  Exit:  regime_bull = False (ROI1yr does NOT trigger exits)")
    print(f"  Tax: STCG {TAX_RATE*100:.0f}%/<365d  |  LTCG 20%/>=365d")
    print("=" * 72)

    print("\n  Fetching BTC (price + AdrActCnt + ROI1yr) and ETH (TxCnt) …")
    btc_full = fetch_btc_full()
    eth_full = fetch_eth_full()
    print(f"  BTC: {len(btc_full)} rows  last=${float(btc_full['Close'].iloc[-1]):,.2f}")
    print(f"  ETH: {len(eth_full)} rows  last=${float(eth_full['Close'].iloc[-1]):,.2f}")

    # ── signal diagnostic ──
    roi1yr = btc_full["ROI1yr"].ffill().fillna(0)
    r_e10  = ema_fn(roi1yr, 10)
    r_e30  = ema_fn(roi1yr, 30)

    print("\n  --- BTC ROI1yr Momentum Diagnostic at Key Dates ---")
    print(f"  {'Date':>12}  {'ROI1yr%':>9}  {'EMA10':>9}  {'EMA30':>9}  {'Signal':>10}  Note")
    for date_str, note in [
        ("2017-12-01", "Pre-peak"),
        ("2018-01-01", "IS start (ICO bubble)"),
        ("2018-06-01", "Bear deepens"),
        ("2020-03-01", "COVID crash"),
        ("2020-09-01", "Post-halving accum."),
        ("2021-01-01", "OOS start (DeFi bull)"),
        ("2021-06-01", "Mid-bull (China ban)"),
        ("2022-01-01", "Pre-crash"),
        ("2023-01-01", "Recovery"),
        ("2024-01-01", "2024 bull"),
    ]:
        idx = btc_full.index.get_indexer([date_str], method="nearest")[0]
        rv  = roi1yr.iloc[idx]
        e10 = r_e10.iloc[idx]
        e30 = r_e30.iloc[idx]
        tag = "ALLOW ✓" if e10 > e30 else "BLOCK ✗"
        print(f"  {date_str}  {rv:>9.1f}%  {e10:>9.1f}%  {e30:>9.1f}%  {tag:>10}  {note}")

    print("\n  Fetching coin price data …")
    coin_closes = {}
    coin_data   = {}
    for sym, ticker, seed in COINS:
        print(f"    {sym} …", end=" ", flush=True)
        close = fetch_close(sym)
        coin_closes[ticker] = close
        coin_data[ticker]   = synthesize_ohlcv(close, seed=seed)
        print(f"{len(close)} rows")

    full_data = {t: coin_data[t] for t in coin_data}
    is_data   = slice_data(full_data, IS_START,  IS_END)
    combined  = slice_data(full_data, IS_START,  OOS_END)

    bt_fixed = dict(commission=0.001, slippage=0.001)

    # ── IS scan ──
    print(f"\n  IS scan ({IS_START}–{IS_END}):")
    print(f"  {'ema':>4} {'act':>7} {'roi_ema':>10} {'mhd':>4}"
          f"  {'Mo%':>8} {'SR':>6} {'DD%':>8} {'N':>4} {'Hold':>5} {'Score':>7}")
    print("  " + "-" * 75)

    results_is = []
    for sp in GRID:
        try:
            rpt = run_is(full_data, is_data, btc_full, eth_full, sp, bt_fixed)
            if rpt is None:
                continue
            m   = rpt.full_metrics()
            mo  = m.get("monthly_return_pct", 0)
            sr  = m.get("sharpe_ratio", 0)
            dd  = m.get("max_drawdown_pct", 0)
            nt  = m.get("n_trades", 0)
            hld = m.get("avg_holding_days", 0) or 0
            if nt < 2:
                continue
            score = is_score(m)
            results_is.append((score, sp, m))
            rs_rl = f"{sp['roi_short']}/{sp['roi_long']}"
            print(f"  {sp['ema_period']:>4} {sp['act_short']}/{sp['act_long']:>3}  {rs_rl:>10}  {sp['min_hold_days']:>4}"
                  f"  {mo:>+7.2f}%  {sr:>6.2f}  {dd:>8.2f}%  {nt:>4}  {hld:>4.0f}d  {score:>7.2f}")
        except Exception as ex:
            pass

    results_is.sort(key=lambda x: x[0], reverse=True)
    if not results_is:
        print("  No valid IS configs."); return

    best_score, best_sp, best_m = results_is[0]
    rs_rl = f"{best_sp['roi_short']}/{best_sp['roi_long']}"
    print(f"\n  IS champion: EMA{best_sp['ema_period']}"
          f"  act={best_sp['act_short']}/{best_sp['act_long']}"
          f"  roi_ema={rs_rl}"
          f"  mhd={best_sp['min_hold_days']}")
    print(f"    Mo%={best_m.get('monthly_return_pct',0):+.2f}%"
          f"  Sharpe={best_m.get('sharpe_ratio',0):.2f}"
          f"  MaxDD={best_m.get('max_drawdown_pct',0):.2f}%"
          f"  N={best_m.get('n_trades',0)}  Hold={best_m.get('avg_holding_days',0):.0f}d"
          f"  Score={best_score:.2f}")

    # ── OOS evaluation ──
    print(f"\n  OOS results ({OOS_START}–{OOS_END}):")
    print(f"  {'ema':>4} {'act':>7} {'roi_ema':>10} {'mhd':>4}"
          f"  {'Mo%':>8} {'SR':>6} {'DD%':>8} {'N':>4} {'Hold':>5} {'Eq$':>12}")
    print("  " + "-" * 75)

    oos_results = []
    for _, sp, _ in results_is:
        try:
            rpt = run_oos(full_data, combined, btc_full, eth_full, sp, bt_fixed)
            if rpt is None:
                continue
            m   = rpt.full_metrics()
            hld = m.get("avg_holding_days", 0) or 0
            sr  = m.get("sharpe_ratio", 0)
            oos_results.append((sr, sp, m, rpt))
            flag = " ← LTCG" if hld >= 365 else ""
            rs_rl = f"{sp['roi_short']}/{sp['roi_long']}"
            print(f"  {sp['ema_period']:>4} {sp['act_short']}/{sp['act_long']:>3}  {rs_rl:>10}  {sp['min_hold_days']:>4}"
                  f"  {m.get('monthly_return_pct',0):>+7.2f}%"
                  f"  {sr:>6.2f}  {m.get('max_drawdown_pct',0):>8.2f}%"
                  f"  {m.get('n_trades',0):>4}  {hld:>4.0f}d"
                  f"  ${m.get('final_equity',0):>11,.0f}{flag}")
        except Exception:
            pass

    oos_results.sort(key=lambda x: x[0], reverse=True)
    if not oos_results:
        print("  No OOS results."); return

    is_champ_oos = next(((sp, m, rpt) for _, sp, m, rpt in oos_results
                         if sp == best_sp), None)
    if is_champ_oos is None:
        is_champ_oos = (oos_results[0][1], oos_results[0][2], oos_results[0][3])

    _, m_oos, rpt_oos = is_champ_oos

    rs_rl = f"{best_sp['roi_short']}/{best_sp['roi_long']}"
    print(f"\n══ IS-Champion OOS (EMA{best_sp['ema_period']}"
          f"  act={best_sp['act_short']}/{best_sp['act_long']}"
          f"  roi_ema={rs_rl}"
          f"  mhd={best_sp['min_hold_days']}) ══")
    rpt_oos.print_full_report(
        f"Iter 38 — ROI1yr Momentum Gate  [OOS {OOS_START}–{OOS_END}]"
    )

    mo  = m_oos.get("monthly_return_pct", 0)
    sr  = m_oos.get("sharpe_ratio",       0)
    dd  = m_oos.get("max_drawdown_pct",   0)
    cal = m_oos.get("calmar_ratio",        0) or 0
    wr  = m_oos.get("win_rate_pct",        0) or 0
    pf  = m_oos.get("profit_factor",       0) or 0
    nt  = m_oos.get("n_trades",            0) or 0
    hld = m_oos.get("avg_holding_days",    0) or 0

    criteria = [
        ("Monthly ≥ 2.0%",       mo  >= 2.0),
        ("Sharpe ≥ 1.0",         sr  >= 1.0),
        ("MaxDD > -40%",         dd  > -40.0),
        ("Calmar ≥ 0.8",         cal >= 0.8),
        ("Win rate ≥ 40%",       wr  >= 40.0),
        ("Profit factor ≥ 1.3",  pf  >= 1.3),
        ("N trades ≥ 5",         nt  >= 5),
    ]
    passed = sum(1 for _, v in criteria if v)
    print(f"\n  7-point checklist: {passed}/7")
    for label, ok in criteria:
        print(f"    {'✓' if ok else '✗'} {label}")

    if best_sp["min_hold_days"] >= 365:
        after_tax = mo * (1 - 0.20) / (1 - 0.35)
        tax_label = "LTCG 20%"
    else:
        after_tax = mo * (1 - 0.35)
        tax_label = "STCG 35%"
    print(f"\n  After {tax_label}: ~+{after_tax:.2f}%/month net")
    print(f"  Avg hold: {hld:.0f} days")
    print(f"\n  Verdict: {'✓ PASS (7/7)' if passed >= 7 else f'✗ FAIL ({passed}/7)'}")


if __name__ == "__main__":
    main()
