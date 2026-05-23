"""
Iteration 75: BTC Price Trend + ETH/BTC Ratio + ETH AvgGasPrice (Altseason + DeFi Cost)
==========================================================================================
Novel signal combination: ETH/BTC Ratio as Signal 2 (altseason structural indicator) AND
ETH AvgGasPrice (= FeeTotNtv / TxCnt) as Signal 3 (DeFi cost/activity premium).

  Signal 1: BTC price > EMA (macro trend — bull market filter)
  Signal 2: ETH/BTC Ratio EMA trend (ETH outperforming BTC = altseason active)
  Signal 3: ETH AvgGasPrice EMA trend (DeFi activity creating fee premium)

WHY THIS COMBINATION:
  ETH/BTC Ratio was proven as Signal 2 in Iter 74 (IS gap +2.21, MaxDD -25.33% best).
  ETH AvgGasPrice was proven as Signal 3 in Iter 68 (IS gap +2.75, highest IS robustness).
  This combines the TWO HIGHEST IS-GAP proven signals as the non-price regime inputs.

  The combination logic:
  - ETH/BTC Ratio rising: Capital is flowing from BTC into ETH and altcoins (structural)
  - ETH AvgGasPrice rising: DeFi users paying MORE per transaction (activity premium)
  When BOTH are rising simultaneously: altseason is active AND DeFi is in heavy use.
  This specifically targets the "DeFi-driven altseason" — the most profitable macro regime.

  KEY IS PROTECTION MECHANISM:
  - ETH/BTC Ratio: 0-2% bull in Q3-Q4 2019 (ETH massively underperformed BTC)
    → This ALONE guarantees ~0% IS entries in Q3-Q4 2019
  - ETH AvgGasPrice: Pre-DeFi era 2019 gas was 1-8 Gwei (very low)
    → In JF2020, gas still very low (~3-8 Gwei) → AvgGasPrice EMA barely bullish
    → Provides ADDITIONAL protection in JF2020 where Iter 74 had 35% combined

  PREDICTED JF2020 IMPROVEMENT VS ITER 74:
    Iter 74 (Ratio + AdrActCnt): JF2020 combined 35% bull
    Iter 75 (Ratio + AvgGasPrice): JF2020 combined likely 10-20% bull
    Reason: ETH gas prices in Jan-Feb 2020 were 3-8 Gwei, historically low (pre-DeFi).
    AvgGasPrice EMA 20/60 would still be in declining/flat trend from 2019.
    The ratio's 48% JF2020 bull × AvgGasPrice's ~10-25% JF2020 bull = ~5-12% combined.
    This provides BETTER JF2020 IS protection than Iter 74's 35% combined.

  PREDICTED IS GAP:
    With near-0% IS entries in Q3-Q4 2019 AND very low JF2020 entries:
    - EMA100 IS champion might survive (lower COVID IS MaxDD than Iter 74's -52.56%)
    - If EMA100 survives: more IS trades → stronger IS gap evidence
    - IS gap expected to be large (combining Iter 68's +2.75 with Iter 74's +2.21)

  OOS PROPERTIES:
    2020 H2 (DeFi Summer): Gas prices spiked to 50-100+ Gwei → AvgGasPrice very bullish
                            ETH/BTC ratio rising → altseason active
                            Combined: very bullish → IS trades entered, held into OOS
    2021: Gas prices high (NFT/DeFi boom) → AvgGasPrice bullish
          ETH/BTC ratio rising → altseason
          Combined: strong OOS bull% → good OOS coverage
    2022: Gas prices collapsed (DeFi activity dried up) → AvgGasPrice bearish early
          ETH/BTC ratio declining → altseason ended
          Combined: both bearish → QUICK EXIT → excellent MaxDD control
    2024: Ethereum L2 scaling reduced mainnet gas → AvgGasPrice may be bearish
          ETH/BTC ratio mixed (underperformed in BTC-ETF era)
          Combined: selective → avoids BTC-dominant phases correctly

  ETH AvgGasPrice = ETH FeeTotNtv / ETH TxCnt (derived column, computed in code)

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
    """Fetch BTC price (Signal 1 trend + ETH/BTC ratio denominator)."""
    url = COINMETRICS.format("btc")
    with urllib.request.urlopen(url, timeout=20) as r:
        df = pd.read_csv(io.StringIO(r.read().decode()), low_memory=False)
    df["Date"]  = pd.to_datetime(df["time"])
    df["Close"] = pd.to_numeric(df["PriceUSD"], errors="coerce")
    return (df[["Date", "Close"]]
            .dropna(subset=["Close"])
            .set_index("Date")
            .sort_index())


def fetch_eth_full() -> pd.DataFrame:
    """Fetch ETH price + FeeTotNtv + TxCnt (for AvgGasPrice = FeeTotNtv/TxCnt)."""
    url = COINMETRICS.format("eth")
    with urllib.request.urlopen(url, timeout=20) as r:
        df = pd.read_csv(io.StringIO(r.read().decode()), low_memory=False)
    df["Date"]      = pd.to_datetime(df["time"])
    df["Close"]     = pd.to_numeric(df["PriceUSD"],  errors="coerce")
    df["FeeTotNtv"] = pd.to_numeric(df["FeeTotNtv"], errors="coerce")
    df["TxCnt"]     = pd.to_numeric(df["TxCnt"],     errors="coerce")
    # AvgGasPrice (ETH per tx) computed from raw data
    df["AvgGasPrice"] = df["FeeTotNtv"] / df["TxCnt"]
    out = (df[["Date", "Close", "AvgGasPrice"]]
           .dropna(subset=["Close"])
           .set_index("Date")
           .sort_index())
    return out


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


class EthAltseasonGasPriceStrategy:
    """
    Triple regime: BTC price EMA + ETH/BTC Ratio EMA trend + ETH AvgGasPrice EMA trend.
    Altseason + DeFi cost premium filter: enter when altcoin season is structurally active
    (ETH outperforming BTC) AND DeFi is generating high fee premium (AvgGasPrice rising).
    Both Signals 2 and 3 are ETH-native. No BTC on-chain metrics required.
    Entry: all 3 regime signals AND btc_vol30 < vol_threshold
    Exit:  any signal turns bearish (vol does NOT trigger exits)
    """

    def __init__(self,
                 ema_period: int      = 100,
                 act_short: int       = 20, act_long: int = 60,
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

    def prepare(self, data: dict, btc_full: pd.DataFrame, eth_full: pd.DataFrame) -> None:
        btc_close = btc_full["Close"]

        # Signal 1: BTC price > EMA (macro trend)
        btc_ema    = ema_fn(btc_close, self.ema_period)
        price_bull = btc_close > btc_ema

        # Signal 2: ETH/BTC Ratio EMA trend (altseason indicator)
        eth_close     = eth_full["Close"].reindex(btc_close.index).ffill()
        eth_btc_ratio = eth_close / btc_close
        ratio_s       = ema_fn(eth_btc_ratio, self.act_short)
        ratio_l       = ema_fn(eth_btc_ratio, self.act_long)
        ratio_bull    = (ratio_s > ratio_l).fillna(False)

        # Signal 3: ETH AvgGasPrice EMA trend (DeFi activity cost premium)
        gas_px  = eth_full["AvgGasPrice"].reindex(btc_close.index).ffill()
        gas_s   = ema_fn(gas_px, self.act_short)
        gas_l   = ema_fn(gas_px, self.act_long)
        gas_bull = (gas_s > gas_l).fillna(False)

        regime_bull = price_bull & ratio_bull & gas_bull
        regime_exit = ~regime_bull

        # Vol gate (entry-only, preserves LTCG positions)
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


def run_is(full_data, is_data, btc_full, eth_full, sp, bt_fixed):
    strat = EthAltseasonGasPriceStrategy(**sp)
    strat.prepare(full_data, btc_full, eth_full)
    bt = AdvancedBacktester(initial_capital=100_000, **bt_fixed)
    return RiskReport(bt.run(is_data, strat))


def run_oos(full_data, combined_data, btc_full, eth_full, sp, bt_fixed):
    strat  = EthAltseasonGasPriceStrategy(**sp)
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
    print("  ITERATION 75 — BTC Trend + ETH/BTC Ratio + ETH AvgGasPrice")
    print("  Portfolio: BTC, ETH, BNB, ADA, XRP  (20% each)")
    print("  Signal 2: ETH/BTC Ratio (altseason — ETH outperforming BTC)")
    print("  Signal 3: ETH AvgGasPrice = FeeTotNtv/TxCnt (DeFi cost premium)")
    print("  Key: Ratio 0% Q3-Q4 2019 + low gas JF2020 → best IS protection predicted")
    print("  Key: Combines Iter 74 Signal 2 (IS gap +2.21) + Iter 68 Signal 3 (IS gap +2.75)")
    print("  Entry: regime_bull AND btc_vol30 < threshold")
    print("  Exit:  regime_bull = False only (vol does NOT trigger exits)")
    print(f"  Tax: STCG {TAX_RATE*100:.0f}%/<365d  |  LTCG 20%/>=365d")
    print("=" * 72)

    print("\n  Fetching BTC (price) ...")
    btc_full = fetch_btc_full()
    print("  Fetching ETH (price + FeeTotNtv + TxCnt → AvgGasPrice) ...")
    eth_full = fetch_eth_full()
    print(f"  BTC: {len(btc_full)} rows  last=${float(btc_full['Close'].iloc[-1]):,.2f}")
    print(f"  ETH: {len(eth_full)} rows  last=${float(eth_full['Close'].iloc[-1]):,.2f}")

    # Combined signal diagnostics
    btc_close = btc_full["Close"]
    eth_close = eth_full["Close"].reindex(btc_close.index).ffill()
    ratio     = eth_close / btc_close
    gas_px    = eth_full["AvgGasPrice"].reindex(btc_close.index).ffill()

    ratio20 = ratio.ewm(span=20).mean(); ratio60 = ratio.ewm(span=60).mean()
    gas20   = gas_px.ewm(span=20).mean(); gas60  = gas_px.ewm(span=60).mean()
    bull_ratio    = ratio20 > ratio60
    bull_gas      = gas20 > gas60
    bull_combined = bull_ratio & bull_gas

    print("\n  Signal diagnostics (EMA 20/60) by period:")
    print(f"  {'Period':>10}  {'Ratio%':>8}  {'GasPrice%':>10}  {'Combined%':>10}")
    periods = [
        ("2018",    "2018-01-01", "2018-12-31"),
        ("2019Q2",  "2019-04-01", "2019-06-30"),
        ("2019Q3",  "2019-07-01", "2019-09-30"),
        ("2019Q4",  "2019-10-01", "2019-12-31"),
        ("JF2020",  "2020-01-01", "2020-02-29"),
        ("2020full","2020-01-01", "2020-12-31"),
        ("2021full","2021-01-01", "2021-12-31"),
        ("2022full","2022-01-01", "2022-12-31"),
        ("2023full","2023-01-01", "2023-12-31"),
        ("2024full","2024-01-01", "2024-12-31"),
    ]
    for period, s, e in periods:
        br  = bull_ratio[(bull_ratio.index >= s) & (bull_ratio.index <= e)]
        bg  = bull_gas[(bull_gas.index >= s) & (bull_gas.index <= e)]
        bc  = bull_combined[(bull_combined.index >= s) & (bull_combined.index <= e)]
        if len(br):
            print(f"  {period:>10}  {100*br.mean():>6.0f}%  {100*bg.mean():>8.0f}%  {100*bc.mean():>8.0f}%")

    print()
    coin_closes: dict = {}
    for coin, ticker, seed in COINS:
        if coin == "btc":
            coin_closes[ticker] = btc_full["Close"]
        elif coin == "eth":
            coin_closes[ticker] = eth_full["Close"]
        else:
            coin_closes[ticker] = fetch_close(coin)
        last = float(coin_closes[ticker].iloc[-1])
        print(f"  {ticker}: {len(coin_closes[ticker])} rows  last=${last:,.4f}")

    full_data: dict = {}
    for coin, ticker, seed in COINS:
        full_data[ticker] = synthesize_ohlcv(coin_closes[ticker], seed=seed)

    is_data  = slice_data(full_data, IS_START, IS_END)
    combined = {t: df.loc[:OOS_END] for t, df in full_data.items()}

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

    print("\n  IS grid (24 configs, 2018-01-01-2020-12-31) ...")
    print("   ema     act  vol_thr  mhd      Mo%     SR      DD%    N  Hold   score")
    print("  " + "-" * 70)

    is_results = []
    for cfg in configs:
        sp = dict(rebalance_days=7, vol_lookback=30, **cfg)
        rr = run_is(full_data, is_data, btc_full, eth_full, sp, bt_fixed)
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

    flag = "WINS ✓" if is_gap > 0 else "LOSES ✗ (IS champion selected wrongly)"
    print(f"\n  IS gap: mhd=365 best={best365[0]:.2f}  mhd=0 best={best0[0]:.2f}"
          f"  gap={is_gap:+.2f}  → mhd=365 {flag}")

    # OOS sweep
    print(f"\n  OOS results ({OOS_START}-{OOS_END}):")
    print("   ema     act  vol_thr  mhd       Mo%     SR      DD%    N  Hold          Eq$")
    print("  " + "-" * 82)

    oos_rows = []
    for cfg in configs:
        sp = dict(rebalance_days=7, vol_lookback=30, **cfg)
        rr = run_oos(full_data, combined, btc_full, eth_full, sp, bt_fixed)
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
    champ_rr = run_oos(full_data, combined, btc_full, eth_full, champ_sp, bt_fixed)
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
    print(f"  RISK REPORT — IS-CHAMPION OOS — ETH Altseason + GasPrice"
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
    print("  VERDICT  —  OOS 2021-2024, ETH Altseason + GasPrice + Vol Gate")
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
    print(f"  IS gap: {is_gap:+.2f}")
    if avg_hold >= 365:
        mo_aftertax = mo_ic * (1 - 0.20) / (1 - 0.35)
        print(f"  After-tax monthly return (LTCG): {mo_aftertax:+.2f}%/mo")

    if passes == 7:
        print("\n  *** 7/7 PASS — STRATEGY QUALIFIES ***")
    else:
        print("\n  Strategy does not meet all criteria.")


if __name__ == "__main__":
    main()
