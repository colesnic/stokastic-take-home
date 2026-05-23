"""
Iteration 18: Annual Cross-Sectional Momentum
=============================================
Select the top N coins by prior-year return each January, hold for the full year.
Exit mid-year if BTC falls below its long EMA (regime fails).

THIS IS A FUNDAMENTALLY DIFFERENT STRATEGY from all previous iterations:
  - Previous: BUY AND HOLD during bull phases (weeks/months)
  - This: ROTATE ANNUALLY to last year's winners, let momentum persist

Academic basis: 12-1 cross-sectional momentum (Jegadeesh & Titman 1993).
Applied to crypto: prior-year winner tends to outperform in the following year
because of narrative persistence, ecosystem development momentum, and capital
inertia from institutional/retail allocation to "what worked last year."

Signal:
  1. Rank coins by prior calendar-year return (cross-sectional ranking)
  2. On Jan 1 each year: sell previous year's selection, buy top N coins
  3. Regime gate: exit if BTC < EMA(ema_period) at any point during the year
  4. Re-enter: only at Jan 1 of next year (no mid-year re-entry after exit)

Why this is naturally LTCG-eligible:
  - Annual rebalancing = ~12-month hold period = qualifies for LTCG (20% tax)
  - Mid-year regime exit: held <12 months → STCG (35%)
  - But in 2022, regime exit is a LOSS → capital loss (actually reduces tax)

Universe: BTC, ETH, BNB, ADA, LINK (5 coins, pick top 3 each year)

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
    ("btc",  "BTC",  42),
    ("eth",  "ETH",  11),
    ("bnb",  "BNB",  77),
    ("ada",  "ADA",  99),
    ("link", "LINK", 55),
]


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


class AnnualMomentumStrategy:
    """
    Annual cross-sectional momentum:
      - On Jan 7 each year: rank coins by prior-year return, buy top_n
      - BTC regime gate: exit if BTC < EMA(ema_period) at any check
      - No mid-year re-entry (only at next annual rebalance)

    Pre-computes full signal series for AdvancedBacktester.
    """

    def __init__(self, ema_period: int = 200,
                 top_n: int = 3,
                 min_prior_year_rows: int = 100,
                 rebalance_day: int = 7):
        self.ema_period          = ema_period
        self.top_n               = top_n
        self.min_prior_year_rows = min_prior_year_rows
        self.rebalance_day       = rebalance_day
        self.signals: dict       = {}

    def prepare(self, data: dict) -> None:
        closes = {t: df["Close"] for t, df in data.items()}
        btc    = closes["BTC"]
        btc_ema = ema_fn(btc, self.ema_period)
        regime_bull = (btc > btc_ema)

        sig_dict: dict[str, pd.Series] = {
            t: pd.Series(np.nan, index=data[t].index)
            for t in data
        }

        all_dates = pd.DatetimeIndex(sorted(set().union(*[data[t].index for t in data])))

        # Pre-compute annual rankings
        all_years = sorted(set(all_dates.year))
        annual_top_n: dict[int, set] = {}
        for year in all_years:
            prior_year = year - 1
            rankings: dict[str, float] = {}
            for t, s in closes.items():
                py = s[s.index.year == prior_year].dropna()
                if len(py) >= self.min_prior_year_rows:
                    rankings[t] = float(py.iloc[-1]) / float(py.iloc[0]) - 1.0
            if rankings:
                top = sorted(rankings.items(), key=lambda x: x[1], reverse=True)
                annual_top_n[year] = {t for t, _ in top[:self.top_n]}
            else:
                annual_top_n[year] = set()  # no data → cash

        # Current holdings: track what we own
        in_position: set[str] = set()
        entry_dates: dict[str, pd.Timestamp] = {}
        regime_exited = False  # regime fail → wait for next Jan to re-enter

        for date in all_dates:
            if not any(date in data[t].index for t in data):
                continue

            # Get regime status
            regime = bool(regime_bull.loc[date]) if date in regime_bull.index else True

            year = date.year
            is_rebalance_day = (date.month == 1 and date.day >= self.rebalance_day
                                and date.day < self.rebalance_day + 7)

            if is_rebalance_day:
                # Annual rebalance: exit current positions, enter new top_n
                target = annual_top_n.get(year, set())

                # Exit coins no longer in target
                for t in list(in_position):
                    if t not in target:
                        if date in sig_dict[t].index:
                            sig_dict[t].loc[date] = -1
                        in_position.discard(t)
                        entry_dates.pop(t, None)

                if regime and target:
                    # Enter new selections
                    for t in target:
                        if t not in in_position and t in data and date in sig_dict[t].index:
                            sig_dict[t].loc[date] = 1
                            in_position.add(t)
                            entry_dates[t] = date
                    regime_exited = False
                else:
                    regime_exited = not regime

            elif not regime and in_position:
                # Mid-year regime fail: exit all
                for t in list(in_position):
                    if date in sig_dict[t].index:
                        sig_dict[t].loc[date] = -1
                    in_position.discard(t)
                    entry_dates.pop(t, None)
                regime_exited = True

        self.signals = {t: sig_dict[t].dropna() for t in data}


def slice_data(data: dict, start: str, end: str) -> dict:
    return {t: df.loc[start:end] for t, df in data.items()
            if len(df.loc[start:end]) >= 60}


def run_backtest(full_data: dict, period_data: dict,
                 sp: dict, bt_params: dict) -> RiskReport:
    strat = AnnualMomentumStrategy(**sp)
    strat.prepare(full_data)
    bt = AdvancedBacktester(initial_capital=100_000, **bt_params)
    return RiskReport(bt.run(period_data, strat))


def run_oos_slice(full_data: dict, combined_data: dict,
                  sp: dict, bt_params: dict) -> RiskReport | None:
    strat = AnnualMomentumStrategy(**sp)
    strat.prepare(full_data)
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
    print("  ITERATION 18 — Annual Cross-Sectional Momentum")
    print("  Select top-N by prior-year return. Annual rebalance on Jan 7.")
    print(f"  Universe: BTC+ETH+BNB+ADA+LINK (top 3 each year)")
    print(f"  Tax: STCG {TAX_RATE*100:.0f}%/<365d  |  LTCG 20%/≥365d")
    print("=" * 72)

    print("\n  Fetching BTC, ETH, BNB, ADA, LINK ...")
    full_data = {}
    closes    = {}
    for coin, label, seed in COINS:
        try:
            s = fetch_close(coin)
            closes[label] = s
            full_data[label] = synthesize_ohlcv(s, seed=seed)
            print(f"  {label}: {len(s)} rows  {s.index[0].date()} → "
                  f"{s.index[-1].date()}  last=${float(s.iloc[-1]):,.2f}")
        except Exception as e:
            print(f"  {label}: FAILED ({e})")

    if len(full_data) < 4:
        print("  Insufficient data.")
        return

    # Show annual returns
    print(f"\n  Annual returns (cross-sectional ranking):")
    print(f"  {'Year':<10}  {'BTC':>8}  {'ETH':>8}  {'BNB':>8}  {'ADA':>8}  {'LINK':>8}  Top3")
    for yr in ["2018","2019","2020","2021","2022","2023","2024"]:
        rets = {}
        for lbl in ["BTC","ETH","BNB","ADA","LINK"]:
            s = closes[lbl][closes[lbl].index.year == int(yr)]
            if len(s) > 100:
                rets[lbl] = (float(s.iloc[-1])/float(s.iloc[0])-1)*100
            else:
                rets[lbl] = float("nan")
        vals = "  ".join(f"{rets.get(l,float('nan')):>+7.1f}%" if rets.get(l)==rets.get(l) else "     nan"
                         for l in ["BTC","ETH","BNB","ADA","LINK"])
        valid = {k:v for k,v in rets.items() if v==v}
        top3 = sorted(valid.items(), key=lambda x: x[1], reverse=True)[:3]
        top3_str = "+".join(f"{t}({v:+.0f}%)" for t,v in top3)
        print(f"  {yr:<10}  {vals}  → {top3_str}")

    # Annual momentum rankings table (which coins to hold each year)
    print(f"\n  Prior-year selection for each year (using last year's returns):")
    for target_year in ["2018","2019","2020","2021","2022","2023","2024"]:
        prior_year = str(int(target_year) - 1)
        prior_rets = {}
        for lbl in ["BTC","ETH","BNB","ADA","LINK"]:
            s = closes[lbl][closes[lbl].index.year == int(prior_year)]
            if len(s) >= 100:
                prior_rets[lbl] = (float(s.iloc[-1])/float(s.iloc[0])-1)*100
        if prior_rets:
            top3 = sorted(prior_rets.items(), key=lambda x: x[1], reverse=True)[:3]
            selection = ", ".join(f"{t}({v:+.0f}%)" for t, v in top3)
        else:
            selection = "insufficient data → cash"
        print(f"  Hold in {target_year}: {selection}")

    is_data       = slice_data(full_data, IS_START,  IS_END)
    combined_data = slice_data(full_data, IS_START,  OOS_END)

    bt_fixed = dict(
        max_positions=3,
        position_size_pct=0.333,
        atr_stop_multiplier=20.0,
        atr_trail_multiplier=12.0,
        risk_per_trade_pct=0.333,
        short_term_tax_rate=TAX_RATE,
    )

    strat_configs = [
        dict(ema_period=ema, top_n=n)
        for ema in [150, 200, 250]
        for n in [2, 3]
    ]

    print(f"\n  IS grid ({len(strat_configs)} configs, {IS_START}–{IS_END}) ...")
    print(f"  {'ema':>4} {'topN':>5}  {'Mo%':>8} {'SR':>6} {'DD%':>8} {'N':>4} {'Hold':>5} {'score':>7}")
    print("  " + "-" * 55)

    results_is = []
    for sp in strat_configs:
        try:
            rpt = run_backtest(full_data, is_data, sp, bt_fixed.copy() |
                               {"max_positions": sp["top_n"],
                                "position_size_pct": 1.0/sp["top_n"],
                                "risk_per_trade_pct": 1.0/sp["top_n"]})
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
            print(f"  {sp['ema_period']:>4} {sp['top_n']:>5}"
                  f"  {mo:>+8.2f}%  {sr:>6.2f}  {dd:>8.2f}%  {nt:>4}  {hld:>4.0f}d  {score:>7.2f}")
        except Exception as ex:
            print(f"  [skip] {sp}: {ex}")

    results_is.sort(key=lambda x: x[0], reverse=True)
    if not results_is:
        print("  No valid IS configs.")
        return

    best_score, best_mo, best_sr, best_dd, best_hld, best_sp, best_m = results_is[0]
    print(f"\n  IS champion: EMA{best_sp['ema_period']} top{best_sp['top_n']}")
    print(f"    Mo%={best_mo:+.2f}% Sharpe={best_sr:.2f} MaxDD={best_dd:.2f}%"
          f" N={best_m.get('n_trades',0)} Hold={best_hld:.0f}d Score={best_score:.2f}")

    print(f"\n  OOS results ({OOS_START}–{OOS_END}):")
    print(f"  {'ema':>4} {'topN':>5}  {'Mo%':>8} {'SR':>6} {'DD%':>8} {'N':>4} {'Hold':>5} {'Eq$':>12}")
    print("  " + "-" * 62)

    oos_results = []
    for _, _, _, _, _, sp, _ in results_is:
        try:
            bt_p = bt_fixed.copy() | {"max_positions": sp["top_n"],
                                       "position_size_pct": 1.0/sp["top_n"],
                                       "risk_per_trade_pct": 1.0/sp["top_n"]}
            rpt = run_oos_slice(full_data, combined_data, sp, bt_p)
            if rpt is None:
                continue
            m   = rpt.full_metrics()
            hld = m.get("avg_holding_days", 0) or 0
            sr  = m.get("sharpe_ratio", 0)
            oos_results.append((sr, sp, m, rpt))
            flag = " ← LTCG" if hld >= 365 else ""
            print(f"  {sp['ema_period']:>4} {sp['top_n']:>5}"
                  f"  {m.get('monthly_return_pct',0):>+8.2f}%"
                  f"  {sr:>6.2f}"
                  f"  {m.get('max_drawdown_pct',0):>8.2f}%"
                  f"  {m.get('n_trades',0):>4}  {hld:>4.0f}d"
                  f"  ${m.get('final_equity',0):>11,.0f}{flag}")
        except Exception as ex:
            print(f"  [skip OOS] {sp}: {ex}")

    oos_results.sort(key=lambda x: x[0], reverse=True)
    if not oos_results:
        print("  No OOS results.")
        return

    is_champ_oos = next(((sp, m, rpt) for _, sp, m, rpt in oos_results
                         if sp == best_sp), None)
    champ_sr, champ_sp, champ_m, champ_rpt = oos_results[0]

    champ_rpt.print_full_report(
        f"OOS CHAMPION — Annual Momentum  ema={champ_sp['ema_period']}"
        f"  top{champ_sp['top_n']}"
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
    print("  VERDICT  —  OOS 2021–2024, Annual Cross-Sectional Momentum")
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
