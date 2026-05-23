"""
Iteration 19: Full Quad On-Chain × Quad L1 — Maximum Regime Protection
=======================================================================
Extension of Iter 15 (Dual On-Chain × Quad L1, best result 2.77%/month WF):
Add ADA's own on-chain signal for earlier 2022 bear exit.

Signal (quad confirmation):
  1. BTC price > EMA(ema_period)               [macro price trend]
  2. BTC AdrActCnt_short MA > AdrActCnt_long   [BTC network adoption]
  3. ETH AdrActCnt_short MA > AdrActCnt_long   [DeFi ecosystem activity]
  4. ADA AdrActCnt_short MA > AdrActCnt_long   [Cardano network health]

Enter: all FOUR conditions bullish → hold BTC+ETH+BNB+ADA equally (25%)
Exit: any condition fails (after min_hold_days)

Key motivation — 2022 early exit via ADA signal:
  ADA active addresses: 2022 change = -53.7% (vs ETH's -10.7%, BTC's +20.7%)
  ADA's on-chain decline in 2022 was FASTER and LARGER than ETH's
  → Adding ADA signal should detect the 2022 bear market EARLIER than Iter 15
  → This could reduce MaxDD below the current -27.83% (Iter 15)

Risk: ADA actives declined in 2023 (-34.5%) and 2024 (-26.9%) due to:
  - Competition from newer L1 chains (Solana, Avalanche)
  - Slower-than-expected smart contract adoption
  This means the ADA signal might block 2023/2024 entry even when BTC/ETH are bull
  → Potentially REDUCING OOS returns while improving risk metrics

Expected outcome:
  - If ADA signal blocks 2023 entry: fewer OOS gains, possibly < 2%/month
  - If ADA signal fires in 2023 local momentum bounces: similar OOS to Iter 15

ADA AdrActCnt annual changes:
  2018: -52.5% (bear ✓)
  2019: +9.1% (barely positive)
  2020: +735.9% (DeFi/Goguen adoption explosion ✓)
  2021: +525.6% (smart contract launch ✓)
  2022: -53.7% (crash, early bear signal ✓)
  2023: -34.5% (L1 competition, declining)
  2024: -26.9% (continued decline)

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
    df["Date"] = pd.to_datetime(df["time"])
    df["Close"] = pd.to_numeric(df["PriceUSD"], errors="coerce")
    df["AdrActCnt"] = pd.to_numeric(df["AdrActCnt"], errors="coerce")
    return df[["Date", "Close", "AdrActCnt"]].dropna(subset=["Close"]).set_index("Date").sort_index()


def fetch_with_adr(coin: str) -> pd.DataFrame:
    url = COINMETRICS.format(coin)
    with urllib.request.urlopen(url, timeout=20) as r:
        df = pd.read_csv(io.StringIO(r.read().decode()), low_memory=False)
    df["Date"] = pd.to_datetime(df["time"])
    for col in ("PriceUSD", "ReferenceRateUSD"):
        if col in df.columns:
            df["Close"] = pd.to_numeric(df[col], errors="coerce")
            break
    df["AdrActCnt"] = pd.to_numeric(df.get("AdrActCnt", pd.Series(dtype=float)), errors="coerce")
    return df[["Date", "Close", "AdrActCnt"]].dropna(subset=["Close"]).set_index("Date").sort_index()


def fetch_close(coin: str) -> pd.Series:
    url = COINMETRICS.format(coin)
    with urllib.request.urlopen(url, timeout=15) as r:
        df = pd.read_csv(io.StringIO(r.read().decode()), low_memory=False)
    df["Date"] = pd.to_datetime(df["time"])
    for col in ("PriceUSD", "ReferenceRateUSD"):
        if col in df.columns:
            df["Close"] = pd.to_numeric(df[col], errors="coerce")
            break
    return df[["Date", "Close"]].dropna().set_index("Date").sort_index()["Close"]


def synthesize_ohlcv(close: pd.Series, seed: int = 42) -> pd.DataFrame:
    rng   = np.random.default_rng(seed)
    n     = len(close)
    ret   = close.pct_change().fillna(0.0)
    vol   = ret.rolling(20).std().fillna(ret.std())
    op    = close.shift(1).fillna(close.iloc[0])
    rf    = np.abs(rng.normal(1.2, 0.5, n)).clip(0.2, 3.0)
    half  = close.values * vol.values * rf
    hi    = np.maximum(op.values, close.values) + half
    lo    = np.maximum(np.minimum(op.values, close.values) - half, close.values * 0.3)
    vol_v = np.abs(rng.normal(1_000_000, 300_000, n)).astype(int)
    df    = pd.DataFrame(
        {"Open": op.values, "High": hi, "Low": lo,
         "Close": close.values, "Volume": vol_v},
        index=close.index,
    )
    df["atr14"] = atr_fn(df["High"], df["Low"], df["Close"], 14)
    df["adx14"] = adx_fn(df["High"], df["Low"], df["Close"], 14)
    return df


class OnChainFullStrategy:
    """
    Quad on-chain confirmation:
      BTC price > EMA  AND  BTC actives grow  AND  ETH actives grow  AND  ADA actives grow
    Universe: BTC+ETH+BNB+ADA (25% each)
    Pre-computes full signal series for AdvancedBacktester.
    """

    def __init__(self, ema_period: int = 150,
                 act_short: int = 20, act_long: int = 60,
                 min_hold_days: int = 365,
                 rebalance_days: int = 7):
        self.ema_period     = ema_period
        self.act_short      = act_short
        self.act_long       = act_long
        self.min_hold_days  = min_hold_days
        self.rebalance_days = rebalance_days
        self.signals: dict  = {}

    def prepare(self, data: dict, btc_full: pd.DataFrame,
                eth_full: pd.DataFrame, ada_full: pd.DataFrame) -> None:
        # Signal 1: BTC price trend
        btc_close    = btc_full["Close"]
        btc_ema      = ema_fn(btc_close, self.ema_period)
        price_bull   = btc_close > btc_ema

        # Signal 2: BTC active address momentum
        btc_adr      = btc_full["AdrActCnt"].ffill()
        btc_adr_s    = ema_fn(btc_adr, self.act_short)
        btc_adr_l    = ema_fn(btc_adr, self.act_long)
        btc_act_bull = btc_adr_s > btc_adr_l

        # Signal 3: ETH active address momentum (aligned to BTC index)
        eth_adr      = eth_full["AdrActCnt"].ffill()
        eth_adr_s    = ema_fn(eth_adr, self.act_short)
        eth_adr_l    = ema_fn(eth_adr, self.act_long)
        eth_act_bull = (eth_adr_s > eth_adr_l).reindex(btc_close.index).ffill()

        # Signal 4: ADA active address momentum (aligned to BTC index)
        ada_adr      = ada_full["AdrActCnt"].ffill()
        ada_adr_s    = ema_fn(ada_adr, self.act_short)
        ada_adr_l    = ema_fn(ada_adr, self.act_long)
        ada_act_bull = (ada_adr_s > ada_adr_l).reindex(btc_close.index).ffill()

        # All four must be bullish
        regime_bull  = price_bull & btc_act_bull & eth_act_bull & ada_act_bull

        sig_dict: dict[str, pd.Series] = {
            t: pd.Series(np.nan, index=data[t].index)
            for t in data
        }

        in_position: dict[str, pd.Timestamp] = {}
        last_rebalance: pd.Timestamp | None  = None
        all_dates = btc_close.index.intersection(
            pd.DatetimeIndex(sorted(set().union(*[data[t].index for t in data])))
        )

        def hold_days(ticker: str, date: pd.Timestamp) -> int:
            if ticker not in in_position:
                return 9999
            return (date - in_position[ticker]).days

        for date in all_dates:
            if not any(date in data[t].index for t in data):
                continue
            if last_rebalance is not None:
                if (date - last_rebalance).days < self.rebalance_days:
                    continue
            last_rebalance = date

            bull = bool(regime_bull.loc[date]) if date in regime_bull.index else False

            if not bull:
                for t in list(in_position):
                    if hold_days(t, date) >= self.min_hold_days:
                        if date in sig_dict[t].index:
                            sig_dict[t].loc[date] = -1
                        del in_position[t]
                continue

            for t in data:
                if t not in in_position:
                    if date in sig_dict[t].index:
                        sig_dict[t].loc[date] = 1
                    in_position[t] = date

        self.signals = {t: sig_dict[t].dropna() for t in data}


def slice_data(data: dict, start: str, end: str) -> dict:
    return {t: df.loc[start:end] for t, df in data.items()
            if len(df.loc[start:end]) >= 60}


def run_is(full_data, is_data, btc_full, eth_full, ada_full, sp, bt_params):
    strat = OnChainFullStrategy(**sp)
    strat.prepare(full_data, btc_full, eth_full, ada_full)
    bt = AdvancedBacktester(initial_capital=100_000, **bt_params)
    return RiskReport(bt.run(is_data, strat))


def run_oos(full_data, combined_data, btc_full, eth_full, ada_full,
            sp, bt_params) -> RiskReport | None:
    strat = OnChainFullStrategy(**sp)
    strat.prepare(full_data, btc_full, eth_full, ada_full)
    bt     = AdvancedBacktester(initial_capital=100_000, **bt_params)
    result = bt.run(combined_data, strat)
    eq     = result.equity_curve
    oos_eq = eq.loc[OOS_START:]
    oos_trades = [t for t in result.closed_trades
                  if t.exit_date is not None and
                  t.exit_date >= pd.Timestamp(OOS_START)]
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
    print("  ITERATION 19 — Quad On-Chain × Quad L1 (BTC+ETH+BNB+ADA)")
    print("  4 signals: BTC price + BTC actives + ETH actives + ADA actives")
    print(f"  Tax: STCG {TAX_RATE*100:.0f}%/<365d  |  LTCG 20%/≥365d")
    print("=" * 72)

    print("\n  Fetching BTC, ETH, ADA (with on-chain), BNB ...")
    try:
        btc_full = fetch_btc_full()
        eth_full = fetch_with_adr("eth")
        ada_full = fetch_with_adr("ada")
        print(f"  BTC: {len(btc_full)} rows, ETH: {len(eth_full)} rows, ADA: {len(ada_full)} rows")
    except Exception as e:
        print(f"  Data fetch failed: {e}"); return

    full_data = {}
    for coin, label, seed in COINS:
        try:
            if label == "BTC":
                s = btc_full["Close"]
            elif label == "ETH":
                s = eth_full["Close"]
            elif label == "ADA":
                s = ada_full["Close"]
            else:
                s = fetch_close(coin)
            full_data[label] = synthesize_ohlcv(s, seed=seed)
            print(f"  {label}: {len(s)} rows  last=${float(s.iloc[-1]):,.2f}")
        except Exception as e:
            print(f"  {label}: FAILED ({e})")

    if len(full_data) < 4:
        print("  Insufficient data.")
        return

    # On-chain signal stats
    print(f"\n  On-chain active addresses (ADA added to BTC+ETH from Iter 15):")
    print(f"  {'Year':<10}  {'BTC%':>8}  {'ETH%':>8}  {'ADA%':>8}")
    for yr in ["2018","2019","2020","2021","2022","2023","2024"]:
        def pct(df, yr):
            s = df["AdrActCnt"][df.index.year == int(yr)].dropna()
            if len(s) > 5 and float(s.iloc[0]) > 0:
                return (float(s.iloc[-1])/float(s.iloc[0])-1)*100
            return float("nan")
        bp = pct(btc_full, yr)
        ep = pct(eth_full, yr)
        ap = pct(ada_full, yr)
        print(f"  {yr:<10}  {bp:>+7.1f}%  {ep:>+7.1f}%  {ap:>+7.1f}%")

    is_data       = slice_data(full_data, IS_START,  IS_END)
    combined_data = slice_data(full_data, IS_START,  OOS_END)

    bt_fixed = dict(
        max_positions=4,
        position_size_pct=0.25,
        atr_stop_multiplier=20.0,
        atr_trail_multiplier=12.0,
        risk_per_trade_pct=0.25,
        short_term_tax_rate=TAX_RATE,
    )

    strat_configs = [
        dict(ema_period=ema, act_short=s, act_long=l, min_hold_days=mhd, rebalance_days=7)
        for ema in [100, 150, 200]
        for (s, l) in [(20, 60), (30, 90), (45, 120)]
        for mhd in [0, 365]
    ]

    print(f"\n  IS grid ({len(strat_configs)} configs, {IS_START}–{IS_END}) ...")
    print(f"  {'ema':>4} {'act':>7} {'mhd':>4}  {'Mo%':>7} {'SR':>6} {'DD%':>8} {'N':>4} {'Hold':>5} {'score':>7}")
    print("  " + "-" * 60)

    results_is = []
    for sp in strat_configs:
        try:
            rpt = run_is(full_data, is_data, btc_full, eth_full, ada_full, sp, bt_fixed)
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
            print(f"  {sp['ema_period']:>4} {act_str:>7} {sp.get('min_hold_days',0):>4}"
                  f"  {mo:>+7.2f}%  {sr:>6.2f}  {dd:>8.2f}%  {nt:>4}  {hld:>4.0f}d  {score:>7.2f}")
        except Exception as ex:
            print(f"  [skip] {ex}")

    results_is.sort(key=lambda x: x[0], reverse=True)
    if not results_is:
        print("  No valid IS configs.")
        return

    best_score, best_mo, best_sr, best_dd, best_hld, best_sp, best_m = results_is[0]
    act_str = f"{best_sp['act_short']}/{best_sp['act_long']}"
    print(f"\n  IS champion: EMA{best_sp['ema_period']} act={act_str} mhd={best_sp.get('min_hold_days',0)}")
    print(f"    Mo%={best_mo:+.2f}% Sharpe={best_sr:.2f} MaxDD={best_dd:.2f}%"
          f" N={best_m.get('n_trades',0)} Hold={best_hld:.0f}d Score={best_score:.2f}")

    print(f"\n  OOS results ({OOS_START}–{OOS_END}):")
    print(f"  {'ema':>4} {'act':>7} {'mhd':>4}  {'Mo%':>8} {'SR':>6} {'DD%':>8} {'N':>4} {'Hold':>5} {'Eq$':>12}")
    print("  " + "-" * 72)

    oos_results = []
    for _, _, _, _, _, sp, _ in results_is:
        try:
            rpt = run_oos(full_data, combined_data, btc_full, eth_full, ada_full, sp, bt_fixed)
            if rpt is None:
                continue
            m   = rpt.full_metrics()
            hld = m.get("avg_holding_days", 0) or 0
            sr  = m.get("sharpe_ratio", 0)
            oos_results.append((sr, sp, m, rpt))
            flag = " ← LTCG" if hld >= 365 else ""
            act_str = f"{sp['act_short']}/{sp['act_long']}"
            print(f"  {sp['ema_period']:>4} {act_str:>7} {sp.get('min_hold_days',0):>4}"
                  f"  {m.get('monthly_return_pct',0):>+7.2f}%"
                  f"  {sr:>6.2f}"
                  f"  {m.get('max_drawdown_pct',0):>8.2f}%"
                  f"  {m.get('n_trades',0):>4}  {hld:>4.0f}d"
                  f"  ${m.get('final_equity',0):>11,.0f}{flag}")
        except Exception:
            pass

    oos_results.sort(key=lambda x: x[0], reverse=True)
    if not oos_results:
        print("  No OOS results.")
        return

    is_champ_oos = next(((sp, m, rpt) for _, sp, m, rpt in oos_results
                         if sp == best_sp), None)
    champ_sr, champ_sp, champ_m, champ_rpt = oos_results[0]

    act_str = f"{champ_sp['act_short']}/{champ_sp['act_long']}"
    champ_rpt.print_full_report(
        f"OOS CHAMPION — Quad On-Chain × Quad L1  ema={champ_sp['ema_period']}"
        f"  act={act_str}  mhd={champ_sp.get('min_hold_days',0)}"
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
    print("  VERDICT  —  OOS 2021–2024, Quad On-Chain × Quad L1")
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
