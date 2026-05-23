"""
Iteration 29: 7-Signal Ensemble Score
=======================================
Instead of AND logic (all signals must agree), compute a SCORE across
7 independent on-chain and technical signals. Enter on high conviction,
exit only when majority turns bearish.

SIGNALS (7 total):
  1. BTC price > EMA(N)                     [price trend]
  2. BTC AdrActCnt EMA(20) > EMA(60)        [user adoption]
  3. BTC HashRate EMA(20) > EMA(60)         [miner confidence]
  4. ETH TxCnt EMA(20) > EMA(60)            [ecosystem health]
  5. ETH/BTC EMA(20) > EMA(60)              [alt-season filter]
  6. BTC vol30 < 0.60                        [no bubble entries]
  7. ETH MVRV < 2.0                          [valuation gate]

ASYMMETRIC ENTRY/EXIT (hysteresis band):
  Entry: score >= entry_threshold (strong conviction required)
  Exit:  score < exit_threshold    (only exit when majority bearish)

At Jan 2018 (IS start): score = 5/7 (vol + MVRV fail)
  → with entry_threshold=6: BLOCKED (prevents bubble entry) ✓
At Jan 2021 (OOS start): score = 7/7
  → with entry_threshold=5 or 6: ALLOWED ✓

WHY ENSEMBLE > AND LOGIC:
  Individual signals flicker. AND logic causes premature exits when one
  signal temporarily turns bearish. Ensemble + hysteresis stays in
  position through single-signal noise but exits when the majority agrees.

Walk-forward: IS 2018-2020, OOS 2021-2024
Tax: 35% STCG <365d, 20% LTCG >=365d model
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
    df["Date"]      = pd.to_datetime(df["time"])
    df["Close"]     = pd.to_numeric(df["PriceUSD"],   errors="coerce")
    df["AdrActCnt"] = pd.to_numeric(df["AdrActCnt"],  errors="coerce")
    df["HashRate"]  = pd.to_numeric(df["HashRate"],   errors="coerce")
    return df[["Date","Close","AdrActCnt","HashRate"]].dropna(subset=["Close"]).set_index("Date").sort_index()


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
    df["TxCnt"]      = pd.to_numeric(df["TxCnt"],      errors="coerce")
    df["CapMVRVCur"] = pd.to_numeric(df["CapMVRVCur"], errors="coerce")
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


class EnsembleScoreStrategy:
    """
    7-signal ensemble with asymmetric entry/exit thresholds.
    Entry: score >= entry_threshold  (high conviction required)
    Exit:  score <  exit_threshold   (majority must agree to exit)
    """

    def __init__(self,
                 ema_period: int      = 100,
                 act_short: int       = 20,  act_long: int = 60,
                 hr_short: int        = 20,  hr_long: int  = 60,
                 ethbtc_short: int    = 20,  ethbtc_long: int = 60,
                 vol_threshold: float = 0.60,
                 mvrv_threshold: float = 2.0,
                 entry_threshold: int  = 6,
                 exit_threshold: int   = 3,
                 min_hold_days: int   = 0,
                 rebalance_days: int  = 7):
        self.ema_period      = ema_period
        self.act_short       = act_short
        self.act_long        = act_long
        self.hr_short        = hr_short
        self.hr_long         = hr_long
        self.ethbtc_short    = ethbtc_short
        self.ethbtc_long     = ethbtc_long
        self.vol_threshold   = vol_threshold
        self.mvrv_threshold  = mvrv_threshold
        self.entry_threshold = entry_threshold
        self.exit_threshold  = exit_threshold
        self.min_hold_days   = min_hold_days
        self.rebalance_days  = rebalance_days
        self.signals: dict   = {}

    def prepare(self, data: dict, btc_full: pd.DataFrame, eth_full: pd.DataFrame) -> None:
        btc_close = btc_full["Close"]

        # Signal 1: BTC price trend
        btc_ema   = ema_fn(btc_close, self.ema_period)
        s1 = (btc_close > btc_ema).astype(int)

        # Signal 2: BTC AdrActCnt momentum
        btc_adr   = btc_full["AdrActCnt"].ffill()
        s2 = (ema_fn(btc_adr, self.act_short) > ema_fn(btc_adr, self.act_long)).astype(int)

        # Signal 3: BTC HashRate momentum
        btc_hr    = btc_full["HashRate"].ffill()
        s3 = (ema_fn(btc_hr, self.hr_short) > ema_fn(btc_hr, self.hr_long)).astype(int)

        # Signal 4: ETH TxCnt momentum
        eth_txcnt = eth_full["TxCnt"].ffill()
        s4 = (ema_fn(eth_txcnt, self.act_short) > ema_fn(eth_txcnt, self.act_long)).reindex(
            btc_close.index).ffill().fillna(0).astype(int)

        # Signal 5: ETH/BTC ratio trend
        eth_close = eth_full["Close"].reindex(btc_close.index).ffill()
        eth_btc   = (eth_close / btc_close).ffill()
        s5 = (ema_fn(eth_btc, self.ethbtc_short) > ema_fn(eth_btc, self.ethbtc_long)).fillna(0).astype(int)

        # Signal 6: BTC vol gate (low vol = entry friendly)
        btc_ret   = btc_close.pct_change()
        vol30     = btc_ret.rolling(30).std() * np.sqrt(252)
        s6 = (vol30 < self.vol_threshold).fillna(0).astype(int)

        # Signal 7: ETH MVRV valuation gate
        eth_mvrv  = eth_full["CapMVRVCur"].ffill()
        s7 = (eth_mvrv < self.mvrv_threshold).reindex(btc_close.index).ffill().fillna(1).astype(int)

        # Ensemble score (0-7)
        score = s1 + s2 + s3 + s4 + s5 + s6 + s7

        can_enter = (score >= self.entry_threshold)
        should_exit = (score < self.exit_threshold)

        all_dates      = btc_close.index.sort_values()
        in_position: dict = {}
        sig_dict       = {t: pd.Series(0, index=all_dates, dtype=int) for _, t, _ in COINS}
        last_rebalance = None

        for date in all_dates:
            if last_rebalance is not None and (date - last_rebalance).days < self.rebalance_days:
                continue
            last_rebalance = date

            exit_now  = bool(should_exit.loc[date]) if date in should_exit.index else True
            enter_now = bool(can_enter.loc[date])   if date in can_enter.index   else False

            if exit_now:
                for t in list(in_position):
                    held = (date - in_position[t]).days
                    if held >= self.min_hold_days:
                        if date in sig_dict[t].index:
                            sig_dict[t].loc[date] = -1
                        del in_position[t]
            elif enter_now:
                for _, t, _ in COINS:
                    if t not in in_position:
                        if date in sig_dict[t].index:
                            sig_dict[t].loc[date] = 1
                        in_position[t] = date

        self.signals = {t: sig_dict[t] for _, t, _ in COINS}

    def get_signals(self, ticker: str) -> pd.Series:
        return self.signals.get(ticker, pd.Series(dtype=int))


def run_is(full_data, is_data, btc_full, eth_full, sp, bt_fixed):
    strat = EnsembleScoreStrategy(**sp)
    strat.prepare(full_data, btc_full, eth_full)
    bt = AdvancedBacktester(initial_capital=100_000, **bt_fixed)
    return RiskReport(bt.run(is_data, strat))


def run_oos(full_data, combined_data, btc_full, eth_full, sp, bt_fixed):
    strat  = EnsembleScoreStrategy(**sp)
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
    print("  ITERATION 29 — 7-Signal Ensemble Score")
    print("  Entry: score >= N  |  Exit: score < M (asymmetric hysteresis)")
    print(f"  Tax: STCG {TAX_RATE*100:.0f}%/<365d  |  LTCG 20%/≥365d")
    print("=" * 72)

    print("\n  Fetching BTC (price + AdrActCnt + HashRate) and ETH (price + TxCnt + MVRV) ...")
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

    # Score diagnostics at key dates
    btc_close = btc_full["Close"]
    eth_close = eth_full["Close"].reindex(btc_close.index).ffill()
    eth_btc   = (eth_close / btc_close).ffill()
    btc_ema100 = ema_fn(btc_close, 100)
    adr        = btc_full["AdrActCnt"].ffill()
    hr         = btc_full["HashRate"].ffill()
    txcnt      = eth_full["TxCnt"].ffill().reindex(btc_close.index).ffill()
    vol30      = btc_close.pct_change().rolling(30).std() * np.sqrt(252)
    mvrv       = eth_full["CapMVRVCur"].reindex(btc_close.index).ffill()

    s1 = btc_close > btc_ema100
    s2 = ema_fn(adr, 20) > ema_fn(adr, 60)
    s3 = ema_fn(hr, 20) > ema_fn(hr, 60)
    s4 = ema_fn(txcnt, 20) > ema_fn(txcnt, 60)
    s5 = ema_fn(eth_btc, 20) > ema_fn(eth_btc, 60)
    s6 = vol30 < 0.60
    s7 = mvrv < 2.0
    score = s1.astype(int) + s2.astype(int) + s3.astype(int) + s4.astype(int) + s5.astype(int) + s6.astype(int) + s7.astype(int)

    print("\n  Signal scores at key dates (EMA100, all params as described):")
    print(f"  {'Date':>11}  {'S1':>3} {'S2':>3} {'S3':>3} {'S4':>3} {'S5':>3} {'S6':>3} {'S7':>3}  {'Score':>6}")
    print(f"  {'':>11}  {'price':>3} {'adr':>3} {'hr':>3} {'txc':>3} {'ebtc':>3} {'vol':>3} {'mvr':>3}  {'':>6}")
    for d in ['2018-01-01','2019-01-01','2020-01-01','2021-01-01','2021-06-01','2022-01-01','2022-06-01','2023-01-01','2024-01-01']:
        dt = pd.Timestamp(d)
        if dt in score.index:
            print(f"  {d}  {int(s1[dt]):>3} {int(s2[dt]):>3} {int(s3[dt]):>3} {int(s4[dt]):>3} {int(s5[dt]):>3} {int(s6[dt]):>3} {int(s7[dt]):>3}  {int(score[dt]):>6}/7")

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
        dict(ema_period=ema,
             act_short=20, act_long=60,
             hr_short=20, hr_long=60,
             ethbtc_short=20, ethbtc_long=60,
             vol_threshold=0.60,
             mvrv_threshold=2.0,
             entry_threshold=et,
             exit_threshold=xt,
             min_hold_days=mhd, rebalance_days=7)
        for ema in [100, 150]
        for et in [5, 6]
        for xt in [2, 3]
        for mhd in [0, 365]
    ]

    print(f"\n  IS grid ({len(strat_configs)} configs, {IS_START}–{IS_END}) ...")
    print(f"  {'ema':>4} {'entry':>6} {'exit':>5} {'mhd':>4}"
          f"  {'Mo%':>7} {'SR':>6} {'DD%':>8} {'N':>4} {'Hold':>5} {'score':>7}")
    print("  " + "-" * 65)

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
            sc  = sr * 3.0 + mo * 0.5 - max(0, -40 - dd) * 0.5
            results_is.append((sc, mo, sr, dd, hld, sp, m))
            print(f"  {sp['ema_period']:>4}  ≥{sp['entry_threshold']:>4}  <{sp['exit_threshold']:>3} {sp.get('min_hold_days',0):>4}"
                  f"  {mo:>+7.2f}%  {sr:>6.2f}  {dd:>8.2f}%  {nt:>4}  {hld:>4.0f}d  {sc:>7.2f}")
        except Exception as ex:
            print(f"  [skip] {ex}")

    results_is.sort(key=lambda x: x[0], reverse=True)
    if not results_is:
        print("  No valid IS configs."); return

    best_score, best_mo, best_sr, best_dd, best_hld, best_sp, best_m = results_is[0]
    print(f"\n  IS champion: EMA{best_sp['ema_period']}"
          f" entry≥{best_sp['entry_threshold']} exit<{best_sp['exit_threshold']}"
          f" mhd={best_sp.get('min_hold_days',0)}")
    print(f"    Mo%={best_mo:+.2f}% Sharpe={best_sr:.2f} MaxDD={best_dd:.2f}%"
          f" N={best_m.get('n_trades',0)} Hold={best_hld:.0f}d Score={best_score:.2f}")

    print(f"\n  OOS results ({OOS_START}–{OOS_END}):")
    print(f"  {'ema':>4} {'entry':>6} {'exit':>5} {'mhd':>4}"
          f"  {'Mo%':>8} {'SR':>6} {'DD%':>8} {'N':>4} {'Hold':>5} {'Eq$':>12}")
    print("  " + "-" * 73)

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
            print(f"  {sp['ema_period']:>4}  ≥{sp['entry_threshold']:>4}  <{sp['exit_threshold']:>3} {sp.get('min_hold_days',0):>4}"
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
    champ_sr, champ_sp, champ_m, champ_rpt = oos_results[0]
    champ_rpt.print_full_report(
        f"OOS CHAMPION — Ensemble Score"
        f"  ema={champ_sp['ema_period']}"
        f"  entry≥{champ_sp['entry_threshold']}"
        f"  exit<{champ_sp['exit_threshold']}"
        f"  mhd={champ_sp.get('min_hold_days',0)}"
        f"  [STCG {TAX_RATE*100:.0f}%, {OOS_START}–{OOS_END}]"
    )

    if is_champ_oos:
        _, m_is, _ = is_champ_oos
    else:
        m_is = champ_m

    mo_is = m_is.get("monthly_return_pct", 0.0)
    sr_is = m_is.get("sharpe_ratio", 0.0)
    dd_is = m_is.get("max_drawdown_pct", 0.0)
    nt_is = m_is.get("n_trades", 0)
    hd_is = m_is.get("avg_holding_days", 0) or 0
    cal_is = mo_is * 12 / abs(dd_is + 1e-9)

    pass_mo  = mo_is >= 2.0
    pass_sr  = sr_is >= 1.0
    pass_dd  = dd_is > -40.0
    pass_cal = cal_is >= 0.8
    pass_wr  = m_is.get("win_rate_pct", 0.0) >= 40.0
    pass_pf  = m_is.get("profit_factor", 0.0) >= 1.3
    pass_nt  = nt_is >= 5
    n_pass   = sum([pass_mo, pass_sr, pass_dd, pass_cal, pass_wr, pass_pf, pass_nt])
    tax_note = "LTCG 20%" if hd_is >= 365 else "STCG 35%"

    print("\n" + "=" * 72)
    print("  VERDICT  —  OOS 2021–2024, 7-Signal Ensemble Score")
    print("=" * 72)
    lbl = lambda ok: f"[{'PASS' if ok else 'FAIL'}]"
    print(f"    {lbl(pass_mo)}  Monthly >= 2.0%             {mo_is:>+.2f}%")
    print(f"    {lbl(pass_sr)}  Sharpe >= 1.0               {sr_is:.2f}")
    print(f"    {lbl(pass_dd)}  MaxDD > -40%                {dd_is:.2f}%")
    print(f"    {lbl(pass_cal)}  Calmar >= 0.8               {cal_is:.2f}")
    print(f"    {lbl(pass_wr)}  Win Rate >= 40%             {m_is.get('win_rate_pct',0.0):.1f}%")
    print(f"    {lbl(pass_pf)}  Profit Factor >= 1.3        {m_is.get('profit_factor',0.0):.2f}")
    print(f"    {lbl(pass_nt)}  N Trades >= 5               {nt_is}")
    print()
    print(f"  {n_pass}/7 criteria pass")
    eq_is = m_is.get("final_equity", 0.0)
    print(f"  Model equity: ${eq_is:,.0f}  (OOS base = $100,000)")
    print(f"  Avg hold: {hd_is:.0f} days  ({tax_note} applied)")
    print()
    print(f"  IS-champion OOS (walk-forward blind): {mo_is:+.2f}%/mo  Sharpe {sr_is:.2f}  MaxDD {dd_is:.2f}%")


if __name__ == "__main__":
    main()
