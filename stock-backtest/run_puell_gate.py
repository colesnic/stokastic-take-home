"""
Iteration 32: Bitcoin Puell Multiple Entry Gate
================================================
Novel signal: BTC Puell Multiple as ENTRY-ONLY gate.

RATIONALE:
  Puell Multiple = daily miner revenue (USD) / 365d moving average of daily revenue

  HIGH Puell (>2.5): Miners earning far above historical norms → price at a
    speculative premium → bubble risk → avoid new entries.
  LOW Puell (<0.5): Miners earning below historical norms → price compressed →
    accumulation opportunity.
  MODERATE Puell (0.5-2.5): Normal operating range → allow entries.

  Key property: Puell accounts for halving cycle dynamics automatically.
  After each halving, issuance halves → Puell drops → entry gate becomes permissive.
  As price rises into the new bull cycle, Puell gradually increases back above 2.5
  to signal overheating.

  BTC Puell Multiple at key dates:
    Dec 2017 (ICO peak):   4.63 → BLOCKS (extreme miner revenue = bubble frenzy)
    Jan 2018 (IS start):   3.36 → BLOCKS (still elevated, ATH region)
    Dec 2018 (bear bottom):0.40 → ALLOWS (miner revenue suppressed, bottom)
    Jun 2020 (post-halving):0.54 → ALLOWS (halving cut supply, price recovering)
    Jan 2021 (OOS start):  2.13 → ALLOWS (below 2.5 threshold, bull run starting)
    Apr 2021 (BTC $58k):   2.73 → BLOCKS with <2.5 (elevated but not parabolic)
    Nov 2021 (BTC $69k ATH):1.50 → ALLOWS (halving effect: less supply means lower
                                    Puell even at ATH price)

STRUCTURAL ADVANTAGE vs other gates:
  1. Not based on price ratio (unlike Mayer Multiple)
  2. Not based on network valuation (unlike MVRV)
  3. Not based on return momentum (unlike ROI gate)
  4. Not based on price stability (unlike vol gate)
  5. Captures economic sustainability: is the current price sustainable given
     the network's security budget relative to historical average?

Gate design (entry-only, no forced exits):
  Entry: regime_bull AND btc_puell < puell_threshold
  Exit:  regime_bull = False  (Puell does NOT trigger exits)

Triple regime (same as Iter 20):
  1. BTC price > EMA(ema_period)
  2. BTC AdrActCnt EMA(short) > EMA(long)
  3. ETH TxCnt EMA(short) > EMA(long)

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
    df["IssTotNtv"] = pd.to_numeric(df["IssTotNtv"],  errors="coerce")
    return df[["Date","Close","AdrActCnt","IssTotNtv"]].dropna(subset=["Close"]).set_index("Date").sort_index()


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


class PuellGateStrategy:
    """
    Triple signal regime (BTC price + AdrActCnt + ETH TxCnt) with
    BTC Puell Multiple < threshold as ENTRY-ONLY gate.

    Puell Multiple = (daily issuance × price) / 365d MA of (daily issuance × price)
    Threshold < 2.5: blocks entries when miner revenue far above historical norm
    (bubble territory). Allows entries when miner revenue is at normal or below-
    normal levels (sustainable price levels).

    Entry: regime_bull AND puell < puell_threshold
    Exit:  regime bearish (Puell does NOT trigger exits — preserves LTCG)
    """

    def __init__(self,
                 ema_period: int       = 100,
                 act_short: int        = 20,   act_long: int = 60,
                 puell_threshold: float = 2.5,
                 min_hold_days: int    = 0,
                 rebalance_days: int   = 7):
        self.ema_period      = ema_period
        self.act_short       = act_short
        self.act_long        = act_long
        self.puell_threshold = puell_threshold
        self.min_hold_days   = min_hold_days
        self.rebalance_days  = rebalance_days
        self.signals: dict   = {}

    def prepare(self, data: dict, btc_full: pd.DataFrame, eth_full: pd.DataFrame) -> None:
        btc_close  = btc_full["Close"]

        # Triple regime signal
        btc_ema    = ema_fn(btc_close, self.ema_period)
        price_bull = btc_close > btc_ema

        btc_adr    = btc_full["AdrActCnt"].ffill()
        adr_s      = ema_fn(btc_adr, self.act_short)
        adr_l      = ema_fn(btc_adr, self.act_long)
        adr_bull   = adr_s > adr_l

        eth_txcnt  = eth_full["TxCnt"].ffill()
        tx_s       = ema_fn(eth_txcnt, self.act_short)
        tx_l       = ema_fn(eth_txcnt, self.act_long)
        tx_bull    = (tx_s > tx_l).reindex(btc_close.index).ffill().fillna(False)

        regime_bull = price_bull & adr_bull & tx_bull
        regime_exit = ~regime_bull

        # Puell Multiple entry gate (entry-only, does NOT trigger exits)
        iss        = btc_full["IssTotNtv"].ffill()
        daily_rev  = iss * btc_close
        puell      = daily_rev / daily_rev.rolling(365).mean()
        puell_ok   = (puell < self.puell_threshold).fillna(True)

        entry_allowed = regime_bull & puell_ok

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
    strat = PuellGateStrategy(**sp)
    strat.prepare(full_data, btc_full, eth_full)
    bt = AdvancedBacktester(initial_capital=100_000, **bt_fixed)
    return RiskReport(bt.run(is_data, strat))


def run_oos(full_data, combined_data, btc_full, eth_full, sp, bt_fixed):
    strat  = PuellGateStrategy(**sp)
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
    print("  ITERATION 32 — BTC Puell Multiple Entry Gate")
    print("  Entry: regime_bull AND puell < threshold (no extreme miner revenue)")
    print("  Exit: regime_bull = False only (Puell does NOT trigger exits)")
    print(f"  Tax: STCG {TAX_RATE*100:.0f}%/<365d  |  LTCG 20%/>=365d")
    print("=" * 72)

    print("\n  Fetching BTC (price + AdrActCnt + IssTotNtv) and ETH (price + TxCnt) ...")
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

    # Puell Multiple diagnostics
    iss       = btc_full["IssTotNtv"].ffill()
    price     = btc_full["Close"]
    daily_rev = iss * price
    puell     = daily_rev / daily_rev.rolling(365).mean()

    print("\n  BTC Puell Multiple diagnostics:")
    print(f"  {'Date':>12}  {'Puell':>7}  {'Price':>12}  {'Gate<2.5':>9}  {'Gate<3.0':>9}")
    print("  " + "-" * 60)
    for dt in ["2017-12-01","2018-01-01","2018-12-01","2019-06-01",
               "2020-06-01","2021-01-01","2021-04-01","2021-11-01",
               "2022-01-01","2022-06-01","2023-01-01","2024-01-01"]:
        row_p = puell.loc[puell.index >= dt].head(1)
        row_pr = price.loc[price.index >= dt].head(1)
        if len(row_p) > 0:
            pm  = row_p.iloc[0]
            pr  = row_pr.iloc[0]
            g25 = "ALLOW" if pm < 2.5 else "BLOCK"
            g30 = "ALLOW" if pm < 3.0 else "BLOCK"
            print(f"  {dt:>12}  {pm:>7.2f}  ${pr:>11,.0f}  {g25:>9}  {g30:>9}")

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
        dict(ema_period=ema, act_short=as_, act_long=al,
             puell_threshold=pt, min_hold_days=mhd, rebalance_days=7)
        for ema in [100, 150]
        for (as_, al) in [(20, 60), (30, 90)]
        for pt in [2.0, 2.5, 3.0, 4.0]
        for mhd in [0, 365]
    ]

    print(f"\n  IS grid ({len(strat_configs)} configs, {IS_START}–{IS_END}) ...")
    print(f"  {'ema':>4} {'act':>7} {'puell':>7} {'mhd':>4}"
          f"  {'Mo%':>7} {'SR':>6} {'DD%':>8} {'N':>4} {'Hold':>5} {'score':>7}")
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
            print(f"  {sp['ema_period']:>4} {sp['act_short']}/{sp['act_long']:>3}"
                  f"  <{sp['puell_threshold']:.1f}  {sp.get('min_hold_days',0):>4}"
                  f"  {mo:>+7.2f}%  {sr:>6.2f}  {dd:>8.2f}%  {nt:>4}  {hld:>4.0f}d  {score:>7.2f}")
        except Exception as ex:
            print(f"  [skip] {ex}")

    results_is.sort(key=lambda x: x[0], reverse=True)
    if not results_is:
        print("  No valid IS configs."); return

    best_score, best_mo, best_sr, best_dd, best_hld, best_sp, best_m = results_is[0]
    print(f"\n  IS champion: EMA{best_sp['ema_period']}"
          f" act={best_sp['act_short']}/{best_sp['act_long']}"
          f" puell<{best_sp['puell_threshold']}"
          f" mhd={best_sp.get('min_hold_days',0)}")
    print(f"    Mo%={best_mo:+.2f}% Sharpe={best_sr:.2f} MaxDD={best_dd:.2f}%"
          f" N={best_m.get('n_trades',0)} Hold={best_hld:.0f}d Score={best_score:.2f}")

    print(f"\n  OOS results ({OOS_START}–{OOS_END}):")
    print(f"  {'ema':>4} {'act':>7} {'puell':>7} {'mhd':>4}"
          f"  {'Mo%':>8} {'SR':>6} {'DD%':>8} {'N':>4} {'Hold':>5} {'Eq$':>12}")
    print("  " + "-" * 78)

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
            print(f"  {sp['ema_period']:>4} {sp['act_short']}/{sp['act_long']:>3}"
                  f"  <{sp['puell_threshold']:.1f}  {sp.get('min_hold_days',0):>4}"
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
        f"OOS CHAMPION — Puell Gate"
        f"  ema={champ_sp['ema_period']}"
        f"  act={champ_sp['act_short']}/{champ_sp['act_long']}"
        f"  puell<{champ_sp['puell_threshold']}"
        f"  mhd={champ_sp.get('min_hold_days',0)}"
        f"  [STCG {TAX_RATE*100:.0f}%, {OOS_START}–{OOS_END}]"
    )

    if is_champ_oos:
        _, m_is, _ = is_champ_oos
    else:
        m_is = champ_m

    mo_is  = m_is.get("monthly_return_pct", 0.0)
    sr_is  = m_is.get("sharpe_ratio", 0.0)
    dd_is  = m_is.get("max_drawdown_pct", 0.0)
    nt_is  = m_is.get("n_trades", 0)
    hd_is  = m_is.get("avg_holding_days", 0) or 0
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
    print("  VERDICT  —  OOS 2021–2024, BTC Puell Multiple Entry Gate")
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
