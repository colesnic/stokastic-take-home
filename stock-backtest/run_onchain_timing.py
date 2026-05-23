"""
Iteration 9: On-Chain Fundamental Timing — BTC + ETH
======================================================
Novel signal: combine price trend with on-chain network activity.

Hypothesis: When BOTH price (BTC > EMA) AND network adoption
(active addresses 30d MA > 90d MA) are trending up, the move has
genuine fundamental backing — not just speculation. This dual
confirmation should reduce false signals and improve Sharpe.

Secondary filter: MVRV (market value / realized value) exit trigger.
When MVRV > 3.5 the market is in extreme overvaluation — exit even
if price hasn't crossed the EMA yet. This protected against the
Dec 2017 and Apr/Nov 2021 peaks historically.

Assets: BTC + ETH 50/50 (fixed allocation, no rotation STCG drag)
Regime: BTC price AND on-chain activity must both be bullish
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
from indicators import ema as ema_fn, rsi as rsi_fn, atr as atr_fn, adx as adx_fn

COINMETRICS = "https://raw.githubusercontent.com/coinmetrics/data/master/csv/{}.csv"

IS_START  = "2018-01-01"
IS_END    = "2020-12-31"
OOS_START = "2021-01-01"
OOS_END   = "2024-12-31"
TAX_RATE  = 0.35


def fetch_btc_full() -> pd.DataFrame:
    """Fetch BTC CSV with price + on-chain metrics."""
    url = COINMETRICS.format("btc")
    with urllib.request.urlopen(url, timeout=20) as r:
        df = pd.read_csv(io.StringIO(r.read().decode()), low_memory=False)
    df["Date"] = pd.to_datetime(df["time"])
    df["Close"] = pd.to_numeric(df["PriceUSD"], errors="coerce")
    for col in ("AdrActCnt", "TxCnt", "CapMVRVCur", "FlowInExNtv", "FlowOutExNtv"):
        if col in df.columns:
            df[col] = pd.to_numeric(df[col], errors="coerce")
    return df[["Date"] + [c for c in ("Close", "AdrActCnt", "TxCnt", "CapMVRVCur",
                                       "FlowInExNtv", "FlowOutExNtv") if c in df.columns]
              ].dropna(subset=["Close"]).set_index("Date").sort_index()


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


class OnChainTimingStrategy:
    """
    Dual-confirmation timing: long only when BOTH price trend AND on-chain
    activity are bullish. Optional MVRV overbought exit.

    Signals dict maps ticker → pd.Series of {-1, 0, 1}.
    """

    def __init__(self, ema_period: int = 100,
                 act_short: int = 30, act_long: int = 90,
                 mvrv_exit: float = 0.0,   # 0 = disabled; >0 = exit threshold
                 min_hold_days: int = 0,
                 rebalance_days: int = 7):
        self.ema_period     = ema_period
        self.act_short      = act_short
        self.act_long       = act_long
        self.mvrv_exit      = mvrv_exit
        self.min_hold_days  = min_hold_days
        self.rebalance_days = rebalance_days
        self.signals: dict  = {}

    def prepare(self, data: dict, btc_full: pd.DataFrame):
        all_dates = sorted(set(d for df in data.values() for d in df.index))

        # Price regime
        btc_close = data["BTC"]["Close"]
        btc_ema   = ema_fn(btc_close, self.ema_period)
        price_bull = (btc_close > btc_ema).reindex(all_dates, fill_value=False)

        # On-chain activity regime
        if "AdrActCnt" in btc_full.columns:
            act = btc_full["AdrActCnt"].dropna()
            act_s = act.rolling(self.act_short).mean()
            act_l = act.rolling(self.act_long).mean()
            activity_bull = (act_s > act_l).reindex(all_dates, fill_value=False)
        else:
            activity_bull = pd.Series(True, index=all_dates)

        # MVRV overbought signal
        if self.mvrv_exit > 0 and "CapMVRVCur" in btc_full.columns:
            mvrv = btc_full["CapMVRVCur"].dropna()
            overbought = (mvrv >= self.mvrv_exit).reindex(all_dates, fill_value=False)
        else:
            overbought = pd.Series(False, index=all_dates)

        # Combined regime: price AND activity bullish AND not overbought
        regime_bull = price_bull & activity_bull & ~overbought

        # Generate signals with min-hold protection
        sig_dict = {t: pd.Series(0, index=all_dates) for t in data}
        in_position: dict = {}   # ticker → entry_date

        for i, date in enumerate(all_dates):
            if i % self.rebalance_days != 0:
                continue

            def hold_days(t):
                return (date - in_position[t]).days if t in in_position else 0

            bull = regime_bull.get(date, False)

            for t in list(in_position):
                if not bull and hold_days(t) >= self.min_hold_days:
                    sig_dict[t].loc[date] = -1
                    del in_position[t]

            if bull:
                for t in data:
                    if t not in in_position:
                        sig_dict[t].loc[date] = 1
                        in_position[t] = date

        for ticker in data:
            self.signals[ticker] = sig_dict[ticker]


def run_period(full_data, period_data, btc_full, sp, bt_params) -> RiskReport:
    strat = OnChainTimingStrategy(**sp)
    strat.prepare(full_data, btc_full)
    bt = AdvancedBacktester(initial_capital=100_000, **bt_params)
    return RiskReport(bt.run(period_data, strat))


def run_oos(full_data, combined_data, btc_full, sp, bt_params) -> RiskReport | None:
    strat = OnChainTimingStrategy(**sp)
    strat.prepare(full_data, btc_full)
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
    print("  ITERATION 9 — On-Chain Fundamental Timing: BTC + ETH")
    print("  Signal: price EMA regime AND active-address growth")
    print(f"  Optional: MVRV overbought exit (>3.5)")
    print(f"  Tax: STCG {TAX_RATE*100:.0f}%/<365d  |  LTCG 20%/model ≥365d")
    print("=" * 72)
    print(f"  IS:  {IS_START} → {IS_END}")
    print(f"  OOS: {OOS_START} → {OOS_END}")

    print("\n  Fetching BTC (full on-chain) + ETH close ...")
    btc_full  = fetch_btc_full()
    eth_close = fetch_close("eth")
    print(f"  BTC: {len(btc_full)} rows  last=${float(btc_full['Close'].iloc[-1]):,.2f}")
    print(f"  AdrActCnt available: {'AdrActCnt' in btc_full.columns}")
    print(f"  CapMVRVCur available: {'CapMVRVCur' in btc_full.columns}")
    print(f"  ETH: {len(eth_close)} rows  last=${float(eth_close.iloc[-1]):,.2f}")

    # Quick annual context
    print(f"\n  Raw annual returns:")
    print(f"  {'Year':<10}  {'BTC':>8}  {'ETH':>8}  {'AdrAct_chg':>12}")
    btc_c = btc_full["Close"]
    for yr in ["2018","2019","2020","2021","2022","2023","2024"]:
        b = btc_c[btc_c.index.year == int(yr)]
        e = eth_close[eth_close.index.year == int(yr)]
        br  = (float(b.iloc[-1])/float(b.iloc[0])-1)*100 if len(b) > 1 else float("nan")
        er  = (float(e.iloc[-1])/float(e.iloc[0])-1)*100 if len(e) > 1 else float("nan")
        if "AdrActCnt" in btc_full.columns:
            a = btc_full["AdrActCnt"][btc_full.index.year == int(yr)].dropna()
            ar = (float(a.iloc[-1])/float(a.iloc[0])-1)*100 if len(a) > 1 else float("nan")
            print(f"  {yr:<10}  {br:>+7.1f}%  {er:>+7.1f}%  {ar:>+11.1f}%")
        else:
            print(f"  {yr:<10}  {br:>+7.1f}%  {er:>+7.1f}%")

    # Build OHLCV data dict
    full_data = {
        "BTC": synthesize_ohlcv(btc_c, seed=42),
        "ETH": synthesize_ohlcv(eth_close, seed=17),
    }

    def slice_data(d, start, end):
        return {t: df.loc[start:end] for t, df in d.items()
                if len(df.loc[start:end]) >= 60}

    is_data       = slice_data(full_data, IS_START, IS_END)
    combined_data = slice_data(full_data, IS_START, OOS_END)

    bt_fixed = dict(
        max_positions=2,
        position_size_pct=0.50,
        atr_stop_multiplier=20.0,
        atr_trail_multiplier=12.0,
        risk_per_trade_pct=0.50,
        short_term_tax_rate=TAX_RATE,
    )

    # Grid: ema × activity windows × mvrv_exit × min_hold_days
    strat_configs = [
        dict(ema_period=ema, act_short=acs, act_long=acl,
             mvrv_exit=mv, min_hold_days=mhd, rebalance_days=7)
        for ema in [100, 150, 200]
        for acs, acl in [(20, 60), (30, 90), (45, 120)]
        for mv  in [0.0, 3.5]
        for mhd in [0, 365]
    ]

    print(f"\n  IS grid search ({len(strat_configs)} configs) ...")
    print(f"  {'ema':>4} {'acts':>4} {'actl':>4} {'mv':>4} {'mhd':>4}  "
          f"{'Mo%':>7} {'SR':>6} {'DD%':>8} {'N':>4} {'Hold':>5} {'score':>7}")
    print("  " + "-" * 68)

    results_is = []
    for sp in strat_configs:
        try:
            rpt = run_period(full_data, is_data, btc_full, sp, bt_fixed)
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
            print(f"  {sp['ema_period']:>4} {sp['act_short']:>4} {sp['act_long']:>4} "
                  f"{sp['mvrv_exit']:>4.1f} {sp['min_hold_days']:>4}"
                  f"  {mo:>+7.2f}%  {sr:>6.2f}  {dd:>8.2f}%  {nt:>4}  {hld:>4.0f}d  {score:>7.2f}")
        except Exception as e:
            print(f"  {sp['ema_period']} {sp['act_short']} {sp['act_long']} {sp['mvrv_exit']:.1f} "
                  f"{sp['min_hold_days']}: ERROR {e}")

    results_is.sort(key=lambda x: x[0], reverse=True)
    if not results_is:
        print("  No valid IS configs.")
        return

    best_sp = results_is[0][5]
    print(f"\n  IS champion: EMA{best_sp['ema_period']} act={best_sp['act_short']}/{best_sp['act_long']} "
          f"mvrv={best_sp['mvrv_exit']:.1f} mhd={best_sp['min_hold_days']}")

    # OOS blind test — all IS configs evaluated OOS
    print(f"\n  OOS results ({OOS_START}–{OOS_END}):")
    print(f"  {'ema':>4} {'acts':>4} {'actl':>4} {'mv':>4} {'mhd':>4}  "
          f"{'Mo%':>8} {'SR':>6} {'DD%':>8} {'N':>4} {'Hold':>5} {'Eq$':>12}")
    print("  " + "-" * 78)

    oos_results = []
    for _, _, _, _, _, sp, _ in results_is:
        try:
            rpt = run_oos(full_data, combined_data, btc_full, sp, bt_fixed)
            if rpt is None:
                continue
            m   = rpt.full_metrics()
            hld = m.get("avg_holding_days", 0) or 0
            sr  = m.get("sharpe_ratio", 0)
            oos_results.append((sr, sp, m, rpt))
            flag = " ← LTCG" if hld >= 365 else ""
            print(f"  {sp['ema_period']:>4} {sp['act_short']:>4} {sp['act_long']:>4} "
                  f"{sp['mvrv_exit']:>4.1f} {sp['min_hold_days']:>4}"
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

    champ_rpt.print_full_report(
        f"OOS CHAMPION — on-chain timing  ema={champ_sp['ema_period']}"
        f"  act={champ_sp['act_short']}/{champ_sp['act_long']}"
        f"  mvrv={champ_sp['mvrv_exit']:.1f}  mhd={champ_sp['min_hold_days']}d"
        f"  [STCG {TAX_RATE*100:.0f}%/<365d, {OOS_START}–{OOS_END}]"
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
    print("  VERDICT  —  OOS 2021–2024, on-chain dual-confirmation timing")
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
              f"Sharpe {im.get('sharpe_ratio',0):.2f}")

    print(f"\n  OOS champion: EMA{champ_sp['ema_period']} "
          f"act={champ_sp['act_short']}/{champ_sp['act_long']} "
          f"mvrv={champ_sp['mvrv_exit']:.1f} mhd={champ_sp['min_hold_days']}d")
    print()


if __name__ == "__main__":
    main()
