"""
Realistic Production Backtest — All 5 Remaining Passing Strategies
Iters 62, 69, 71, 73, 78

All use identical IS champion: EMA100, act=20/60, vol<0.60, mhd=365

7 Production Variables:
  1. $1,000 bankroll
  2. 1-day execution latency (EOD signal → next-day Open)
  3. 0.25% commission per leg
  4. Asset-specific bid-ask slippage (5-30 bps)
  5. Time-varying Fed Funds cash yield (0.1% → 5.25%)
  6. ±0.30% execution price noise
  7. $10 minimum position size
"""

import io
import urllib.request
from dataclasses import dataclass
from typing import Dict, List, Tuple

import numpy as np
import pandas as pd

# ─────────────────────────────────────────────────────────────────────────────
# CONSTANTS
# ─────────────────────────────────────────────────────────────────────────────

INITIAL_CAPITAL  = 1_000.0
EXEC_DELAY_DAYS  = 1
COMMISSION_RATE  = 0.0025
EXEC_NOISE_PCT   = 0.003
MIN_POSITION_USD = 10.0
POSITION_PCT     = 0.20
MAX_POS          = 5

SLIPPAGE: Dict[str, float] = {
    "BTC":  0.0005,
    "ETH":  0.0010,
    "BNB":  0.0020,
    "ADA":  0.0030,
    "XRP":  0.0025,
    "LINK": 0.0025,
}

CASH_YIELD_SCHEDULE = [
    (pd.Timestamp("2018-01-01"), pd.Timestamp("2022-03-15"), 0.0010),
    (pd.Timestamp("2022-03-16"), pd.Timestamp("2022-06-30"), 0.0100),
    (pd.Timestamp("2022-07-01"), pd.Timestamp("2022-12-31"), 0.0300),
    (pd.Timestamp("2023-01-01"), pd.Timestamp("2024-12-31"), 0.0525),
]

TAX_STCG   = 0.35
TAX_LTCG   = 0.20
LTCG_DAYS  = 365

IS_START  = "2018-01-01"
IS_END    = "2020-12-31"
OOS_START = "2021-01-01"
OOS_END   = "2024-12-31"

COINMETRICS = "https://raw.githubusercontent.com/coinmetrics/data/master/csv/{}.csv"

# Idealized OOS results for comparison (from walk-forward reports)
IDEAL = {
    "Iter62": {"mo": 3.02, "sharpe": 1.24, "mdd": -26.60, "wr": 90, "pf": 131.0,  "tax": "LTCG"},
    "Iter69": {"mo": 2.58, "sharpe": 1.04, "mdd": -25.37, "wr": 80, "pf": 17.46,  "tax": "LTCG"},
    "Iter71": {"mo": 3.05, "sharpe": 1.37, "mdd": -26.60, "wr": 90, "pf": 133.61, "tax": "STCG"},
    "Iter73": {"mo": 2.79, "sharpe": 1.27, "mdd": -26.05, "wr": 90, "pf": 50.00,  "tax": "STCG"},
    "Iter78": {"mo": 2.75, "sharpe": 1.24, "mdd": -24.58, "wr": 85, "pf": 56.98,  "tax": "STCG"},
}

# ─────────────────────────────────────────────────────────────────────────────
# DATA FETCHING
# ─────────────────────────────────────────────────────────────────────────────

def fetch_coinmetrics(coin: str, cols: list) -> pd.DataFrame:
    url = COINMETRICS.format(coin)
    with urllib.request.urlopen(url, timeout=25) as r:
        df = pd.read_csv(io.StringIO(r.read().decode()), low_memory=False)
    df["Date"] = pd.to_datetime(df["time"])
    df.set_index("Date", inplace=True)
    result = pd.DataFrame(index=df.index)
    for src, dst in cols:
        if src in df.columns:
            result[dst] = pd.to_numeric(df[src], errors="coerce")
    return result.dropna(subset=["Close"]).sort_index()


def fetch_all_data() -> Tuple[pd.DataFrame, pd.DataFrame]:
    print("  Fetching BTC (Close + AdrActCnt)...")
    btc = fetch_coinmetrics("btc", [("PriceUSD","Close"), ("AdrActCnt","AdrActCnt")])
    print("  Fetching ETH (Close + AdrActCnt + TxCnt)...")
    eth = fetch_coinmetrics("eth", [
        ("PriceUSD","Close"), ("AdrActCnt","AdrActCnt"), ("TxCnt","TxCnt"),
    ])
    eth["Ratio"] = eth["Close"] / btc["Close"].reindex(eth.index).ffill()
    return btc, eth


def fetch_asset_prices() -> Dict[str, pd.Series]:
    assets = {}
    for coin, ticker in [("btc","BTC"),("eth","ETH"),("bnb","BNB"),
                          ("ada","ADA"),("xrp","XRP"),("link","LINK")]:
        df = fetch_coinmetrics(coin, [("PriceUSD","Close")])
        if "Close" in df.columns and df["Close"].notna().sum() > 100:
            assets[ticker] = df["Close"]
            print(f"    {ticker}: {len(assets[ticker])} rows  last=${float(assets[ticker].iloc[-1]):,.4f}")
    return assets


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
    return pd.DataFrame(
        {"Open": op.values, "High": hi, "Low": lo, "Close": close.values, "Volume": vv},
        index=close.index,
    )

# ─────────────────────────────────────────────────────────────────────────────
# HELPERS
# ─────────────────────────────────────────────────────────────────────────────

def ema_fn(series: pd.Series, span: int) -> pd.Series:
    return series.ewm(span=span, adjust=False).mean()


def get_cash_yield_daily(date: pd.Timestamp) -> float:
    for start, end, rate in CASH_YIELD_SCHEDULE:
        if start <= date <= end:
            return rate / 365.0
    return 0.0


# ─────────────────────────────────────────────────────────────────────────────
# SIGNAL COMPUTATION (5 strategies)
# ─────────────────────────────────────────────────────────────────────────────

def _build_signals(
    all_dates, coins, regime_bull, entry_ok,
    min_hold_days: int = 365, rebalance_days: int = 7
) -> Dict[str, pd.Series]:
    in_position: Dict[str, pd.Timestamp] = {}
    sig = {t: pd.Series(0, index=all_dates, dtype=int) for t, _ in coins}
    last_reb = None

    for date in all_dates:
        regime_on = bool(regime_bull.get(date, False)) if isinstance(regime_bull, dict) else (
            regime_bull.loc[date] if date in regime_bull.index else False
        )
        entry_on  = bool(entry_ok.get(date, False)) if isinstance(entry_ok, dict) else (
            entry_ok.loc[date] if date in entry_ok.index else False
        )

        for ticker, _ in coins:
            if ticker in in_position:
                held = (date - in_position[ticker]).days
                if not regime_on and held >= min_hold_days:
                    sig[ticker].loc[date] = -1
                    del in_position[ticker]
                    last_reb = None
            else:
                if entry_on:
                    can_enter = (last_reb is None or (date - last_reb).days >= rebalance_days)
                    if can_enter:
                        sig[ticker].loc[date] = 1
                        in_position[ticker] = date
                        last_reb = date

    return sig


def compute_signals(
    btc: pd.DataFrame, eth: pd.DataFrame,
    signal2: str, signal3: str,
    coins: List[Tuple[str, int]],
    ema_period: int = 100, act_short: int = 20, act_long: int = 60,
    vol_threshold: float = 0.60, min_hold_days: int = 365,
) -> Dict[str, pd.Series]:
    """
    Generic signal builder for all 5 strategies.
    signal2/signal3 identify which on-chain signals to use.
    """
    btc_close = btc["Close"]

    # Always: BTC price > EMA
    price_bull = btc_close > ema_fn(btc_close, ema_period)

    def _sig(name: str) -> pd.Series:
        if name == "BTC_ADR":
            s = btc["AdrActCnt"].reindex(btc_close.index).ffill()
            return (ema_fn(s, act_short) > ema_fn(s, act_long)).fillna(False)
        elif name == "ETH_TXCNT":
            s = eth["TxCnt"].reindex(btc_close.index).ffill()
            return (ema_fn(s, act_short) > ema_fn(s, act_long)).fillna(False)
        elif name == "ETH_ADR":
            s = eth["AdrActCnt"].reindex(btc_close.index).ffill()
            return (ema_fn(s, act_short) > ema_fn(s, act_long)).fillna(False)
        elif name == "ETH_BTC_RATIO":
            ratio = eth["Ratio"].reindex(btc_close.index).ffill()
            return (ema_fn(ratio, act_short) > ema_fn(ratio, act_long)).fillna(False)
        else:
            raise ValueError(f"Unknown signal: {name}")

    s2 = _sig(signal2)
    s3 = _sig(signal3)
    regime_bull = price_bull & s2 & s3

    vol30    = btc_close.pct_change().rolling(30).std() * np.sqrt(252)
    entry_ok = regime_bull & (vol30 < vol_threshold).fillna(False)

    return _build_signals(btc_close.index, coins, regime_bull, entry_ok, min_hold_days)

# ─────────────────────────────────────────────────────────────────────────────
# EXECUTION ENGINE (identical to run_realistic_production_backtest.py)
# ─────────────────────────────────────────────────────────────────────────────

@dataclass
class ClosedTrade:
    ticker:      str
    entry_date:  pd.Timestamp
    exit_date:   pd.Timestamp
    entry_price: float
    exit_price:  float
    shares:      float
    gross_pnl:   float
    tax_paid:    float
    net_pnl:     float
    hold_days:   int
    cost_basis:  float


@dataclass
class OpenPosition:
    ticker:      str
    entry_date:  pd.Timestamp
    entry_price: float
    shares:      float
    cost_basis:  float


def run_realistic(
    signals: Dict[str, pd.Series],
    ohlcv:   Dict[str, pd.DataFrame],
    start:   str,
    end:     str,
    rng:     np.random.Generator,
    label:   str = "",
) -> Tuple[pd.DataFrame, List[ClosedTrade], Dict]:
    cash      = INITIAL_CAPITAL
    positions: Dict[str, OpenPosition] = {}
    closed:    List[ClosedTrade]  = []
    equity_rows = []
    pending: Dict[str, Tuple[str, pd.Timestamp]] = {}

    if not ohlcv:
        return pd.DataFrame(columns=["equity"]), [], {}

    all_sets = [set(ohlcv[t].index) for t in ohlcv]
    dates = sorted(all_sets[0].intersection(*all_sets[1:]))
    dates = [d for d in dates if pd.Timestamp(start) <= d <= pd.Timestamp(end)]

    friction: Dict[str, float] = {
        "commission_paid": 0.0, "spread_slippage_paid": 0.0,
        "execution_noise_impact": 0.0, "cash_yield_earned": 0.0,
        "tax_paid": 0.0, "positions_blocked_min_size": 0,
    }

    for i, date in enumerate(dates):
        daily_yield = get_cash_yield_daily(date)
        yield_amt = cash * daily_yield
        cash += yield_amt
        friction["cash_yield_earned"] += yield_amt

        for ticker, (direction, _) in list(pending.items()):
            if ticker not in ohlcv:
                del pending[ticker]; continue
            df = ohlcv[ticker]
            if date not in df.index:
                continue

            open_px    = float(df.loc[date, "Open"])
            noise_frac = rng.uniform(-EXEC_NOISE_PCT, EXEC_NOISE_PCT)
            slip       = SLIPPAGE.get(ticker, 0.002)

            if direction == "BUY":
                exec_price = open_px * (1 + noise_frac + slip)
                pos_target = (cash + sum(
                    p.shares * float(ohlcv[p.ticker].loc[date, "Close"])
                    for p in positions.values() if date in ohlcv[p.ticker].index
                )) * POSITION_PCT

                if pos_target < MIN_POSITION_USD:
                    friction["positions_blocked_min_size"] += 1
                    del pending[ticker]; continue

                comm = pos_target * COMMISSION_RATE
                friction["commission_paid"]         += comm
                friction["spread_slippage_paid"]    += pos_target * slip
                friction["execution_noise_impact"]  += abs(pos_target * noise_frac)

                cash_needed = pos_target + comm
                if cash_needed > cash:
                    cash_needed = cash
                    pos_target  = cash_needed / (1 + COMMISSION_RATE)

                if pos_target < MIN_POSITION_USD:
                    friction["positions_blocked_min_size"] += 1
                    del pending[ticker]; continue

                shares = pos_target / exec_price
                cash  -= (pos_target + comm)
                positions[ticker] = OpenPosition(
                    ticker=ticker, entry_date=date, entry_price=exec_price,
                    shares=shares, cost_basis=pos_target + comm,
                )

            elif direction == "SELL" and ticker in positions:
                pos        = positions[ticker]
                exec_price = open_px * (1 + noise_frac - slip)
                proceeds   = pos.shares * exec_price

                comm = proceeds * COMMISSION_RATE
                friction["commission_paid"]        += comm
                friction["spread_slippage_paid"]   += proceeds * slip
                friction["execution_noise_impact"] += abs(proceeds * noise_frac)

                net_proceeds = proceeds - comm
                gross_pnl    = net_proceeds - pos.cost_basis
                hold_days    = (date - pos.entry_date).days

                tax = 0.0
                if gross_pnl > 0:
                    rate = TAX_LTCG if hold_days >= LTCG_DAYS else TAX_STCG
                    tax  = gross_pnl * rate

                friction["tax_paid"] += tax
                cash += net_proceeds - tax
                closed.append(ClosedTrade(
                    ticker=ticker, entry_date=pos.entry_date, exit_date=date,
                    entry_price=pos.entry_price, exit_price=exec_price,
                    shares=pos.shares, gross_pnl=gross_pnl, tax_paid=tax,
                    net_pnl=gross_pnl - tax, hold_days=hold_days,
                    cost_basis=pos.cost_basis,
                ))
                del positions[ticker]

            del pending[ticker]

        if i + 1 < len(dates):
            for ticker, sig_series in signals.items():
                if date in sig_series.index:
                    sv = int(sig_series.loc[date])
                    if sv == 1 and ticker not in positions and ticker not in pending:
                        pending[ticker] = ("BUY", date)
                    elif sv == -1 and ticker in positions and ticker not in pending:
                        pending[ticker] = ("SELL", date)

        # Mark-to-market
        port_val = cash
        for ticker, pos in positions.items():
            if ticker in ohlcv and date in ohlcv[ticker].index:
                port_val += pos.shares * float(ohlcv[ticker].loc[date, "Close"])
        equity_rows.append({"date": date, "equity": port_val})

    eq_df = pd.DataFrame(equity_rows).set_index("date")
    return eq_df, closed, friction


def compute_metrics(eq_df: pd.DataFrame, closed: List[ClosedTrade]) -> Dict:
    if eq_df.empty or len(eq_df) < 2:
        return {}
    eq = eq_df["equity"]

    # Monthly returns (resampled) for Sharpe
    monthly = eq.resample("ME").last().pct_change().dropna()
    n_months = max(len(monthly), 1)
    total_ret = (eq.iloc[-1] / eq.iloc[0]) - 1

    # Correct monthly/annual CAGR formulas
    mo     = ((1 + total_ret) ** (1 / n_months) - 1) * 100
    ann    = ((1 + total_ret) ** (12 / n_months) - 1) * 100

    vol_mo = monthly.std()
    sr     = (monthly.mean() / vol_mo * np.sqrt(12)) if vol_mo > 0 else 0.0

    roll = eq.cummax()
    dd   = ((eq - roll) / roll).min() * 100
    calmar = ann / abs(dd) if dd < 0 else 0.0

    n    = len(closed)
    wins = [t for t in closed if t.net_pnl > 0]
    loss = [t for t in closed if t.net_pnl <= 0]
    wr   = 100 * len(wins) / n if n else 0.0
    gross_w = sum(t.gross_pnl for t in wins)
    gross_l = abs(sum(t.gross_pnl for t in loss))
    pf   = (gross_w / gross_l) if gross_l > 0 else float("inf")
    avg_hold = np.mean([t.hold_days for t in closed]) if closed else 0
    avg_win  = np.mean([t.net_pnl / t.cost_basis * 100 for t in wins]) if wins else 0.0
    avg_loss = np.mean([t.net_pnl / t.cost_basis * 100 for t in loss]) if loss else 0.0
    return {
        "mo": mo, "ann": ann, "sr": sr, "dd": dd, "calmar": calmar,
        "wr": wr, "pf": pf, "n": n, "avg_hold": avg_hold,
        "avg_win": avg_win, "avg_loss": avg_loss,
        "final_eq": float(eq.iloc[-1]),
    }


def print_result(label: str, m: Dict, friction: Dict, closed: List[ClosedTrade], ideal: Dict) -> None:
    if not m:
        print(f"\n  {label}: NO DATA\n")
        return

    print(f"\n{'─'*66}")
    print(f"  {label}")
    print(f"{'─'*66}")
    print(f"  Final equity    ${m['final_eq']:>9,.2f}  (started $1,000)")
    print(f"  Monthly return    {m['mo']:>+7.2f}%/mo")
    print(f"  Sharpe ratio      {m['sr']:>7.2f}")
    print(f"  Max drawdown      {m['dd']:>7.2f}%")
    print(f"  Calmar ratio      {m['calmar']:>7.2f}")
    print(f"  Win rate          {m['wr']:>7.1f}%")
    print(f"  Profit factor     {m['pf']:>7.2f}")
    print(f"  N trades          {m['n']:>7d}")
    print(f"  Avg hold          {m['avg_hold']:>7.0f} days")

    net_fr = (friction.get("commission_paid",0) + friction.get("spread_slippage_paid",0)
              + friction.get("tax_paid",0) - friction.get("cash_yield_earned",0))
    print(f"\n  ── Friction ──────────────────────────────────────────")
    print(f"  Commission        ${friction.get('commission_paid',0):>9.2f}")
    print(f"  Spread slippage   ${friction.get('spread_slippage_paid',0):>9.2f}")
    print(f"  Tax paid          ${friction.get('tax_paid',0):>9.2f}")
    print(f"  Cash yield earned ${friction.get('cash_yield_earned',0):>9.2f}")
    print(f"  Net friction      ${net_fr:>9.2f}  ({net_fr/10:.1f}% of bankroll)")

    if closed:
        print(f"\n  ── Trades ────────────────────────────────────────────")
        print(f"  {'Ticker':<6} {'Entry':>12} {'Exit':>12} {'Hold':>5}  {'Net$':>8}  {'Tax$':>6}  {'%':>7}")
        for t in closed:
            tax_type = "LTCG" if t.hold_days >= LTCG_DAYS else "STCG"
            pct = t.net_pnl / t.cost_basis * 100
            sign = "+" if t.net_pnl >= 0 else ""
            print(f"  {t.ticker:<6} {str(t.entry_date.date()):>12} {str(t.exit_date.date()):>12} "
                  f"{t.hold_days:>4}d  ${t.net_pnl:>7.1f}  ${t.tax_paid:>5.1f}  {sign}{pct:.1f}% ({tax_type})")

    # vs idealized
    if ideal:
        print(f"\n  ── vs Idealized ──────────────────────────────────────")
        print(f"  {'Metric':<18} {'Idealized':>12} {'Realistic':>12}")
        print(f"  {'Monthly %':<18} {ideal['mo']:>+11.2f}% {m['mo']:>+11.2f}%")
        print(f"  {'Sharpe':<18} {ideal['sharpe']:>12.2f} {m['sr']:>12.2f}")
        print(f"  {'MaxDD %':<18} {ideal['mdd']:>12.2f}% {m['dd']:>12.2f}%")
        print(f"  {'Win Rate %':<18} {ideal['wr']:>12.1f}% {m['wr']:>12.1f}%")
        print(f"  {'Profit Factor':<18} {ideal['pf']:>12.2f} {m['pf']:>12.2f}")
        print(f"  {'Tax treatment':<18} {'('+ideal['tax']+')':>12} {'(realized)':>12}")


def print_verdict(results: List[Tuple[str, Dict, Dict]]) -> None:
    print(f"\n{'═'*70}")
    print("  OOS REALISTIC VERDICT — ALL STRATEGIES ($1,000 bankroll)")
    print(f"{'═'*70}")
    print(f"  {'Strategy':<10} {'Mo%':>7} {'Sharpe':>7} {'MaxDD':>8} {'Calmar':>7} {'WR':>6} {'N':>4} {'FinalEq':>9}")
    print(f"  {'-'*70}")
    for label, m, _ in results:
        if not m:
            print(f"  {label:<10}  NO DATA")
            continue
        flags = []
        if m["mo"] >= 2.0:    flags.append("mo✓")
        if m["sr"] >= 1.0:    flags.append("sr✓")
        if m["dd"] > -40:     flags.append("dd✓")
        if m["calmar"] >= 0.8: flags.append("cal✓")
        if m["wr"] >= 40:     flags.append("wr✓")
        if m["n"] >= 5:       flags.append("n✓")
        n_pass = len(flags)
        verdict = "PASS" if n_pass == 6 else f"{n_pass}/6"
        print(f"  {label:<10} {m['mo']:>+7.2f} {m['sr']:>7.2f} {m['dd']:>7.1f}% {m['calmar']:>7.2f} "
              f"{m['wr']:>5.1f}% {m['n']:>4d} ${m['final_eq']:>8,.0f}  [{verdict}]")

    print(f"\n  Criteria: Mo≥2% | Sharpe≥1.0 | MaxDD>-40% | Calmar≥0.8 | WR≥40% | N≥5")

# ─────────────────────────────────────────────────────────────────────────────
# MAIN
# ─────────────────────────────────────────────────────────────────────────────

def main():
    print("═" * 70)
    print("  REALISTIC PRODUCTION BACKTEST — ITERS 62 / 69 / 71 / 73 / 78")
    print("  $1,000 bankroll | 7 production realism variables")
    print("═" * 70)

    print("\n  Fetching on-chain data...")
    btc, eth = fetch_all_data()
    print("  Fetching asset price data...")
    asset_prices = fetch_asset_prices()

    seeds = {"BTC":42,"ETH":11,"BNB":77,"ADA":99,"XRP":17,"LINK":23}
    ohlcv_full = {t: synthesize_ohlcv(p, seed=seeds[t]) for t, p in asset_prices.items()}

    COINS_XRP  = [("BTC",42),("ETH",11),("BNB",77),("ADA",99),("XRP",17)]
    COINS_LINK = [("BTC",42),("ETH",11),("BNB",77),("ADA",99),("LINK",23)]

    # Strategy definitions: (label, signal2, signal3, coins, ideal_key)
    strategies = [
        ("Iter62", "BTC_ADR",       "ETH_TXCNT",    COINS_XRP,  "Iter62"),
        ("Iter69", "BTC_ADR",       "ETH_BTC_RATIO", COINS_XRP,  "Iter69"),
        ("Iter71", "BTC_ADR",       "ETH_ADR",       COINS_XRP,  "Iter71"),
        ("Iter73", "ETH_TXCNT",     "ETH_ADR",       COINS_XRP,  "Iter73"),
        ("Iter78", "BTC_ADR",       "ETH_ADR",       COINS_LINK, "Iter78"),
    ]

    print("\n  Computing signals...")
    signals = {}
    for label, s2, s3, coins, _ in strategies:
        signals[label] = compute_signals(btc, eth, s2, s3, coins)
        print(f"    {label}: signals computed ({s2} + {s3})")

    rng = np.random.default_rng(2024)

    # OOS period
    ohlcv_oos = {t: df.loc[OOS_START:OOS_END] for t, df in ohlcv_full.items()
                 if len(df.loc[OOS_START:OOS_END]) >= 60}

    print(f"\n  Running OOS period ({OOS_START} to {OOS_END})...")
    oos_results = []
    for label, s2, s3, coins, ideal_key in strategies:
        # Filter ohlcv to only the coins this strategy uses
        tickers = [t for t, _ in coins]
        ohlcv_strat = {t: df for t, df in ohlcv_oos.items() if t in tickers}
        eq, closed, fric = run_realistic(signals[label], ohlcv_strat, OOS_START, OOS_END, rng, label)
        m = compute_metrics(eq, closed)
        oos_results.append((label, m, fric, closed, ideal_key))
        print(f"    {label}: {m.get('n',0)} trades, final=${m.get('final_eq',1000):,.0f}, "
              f"Mo={m.get('mo',0):+.2f}%, Sharpe={m.get('sr',0):.2f}, MaxDD={m.get('dd',0):.1f}%")

    # IS period (for context)
    print(f"\n  Running IS period ({IS_START} to {IS_END}) for context...")
    ohlcv_is = {t: df.loc[IS_START:IS_END] for t, df in ohlcv_full.items()
                if len(df.loc[IS_START:IS_END]) >= 60}
    is_results = []
    for label, s2, s3, coins, _ in strategies:
        tickers = [t for t, _ in coins]
        ohlcv_strat = {t: df for t, df in ohlcv_is.items() if t in tickers}
        eq, closed, fric = run_realistic(signals[label], ohlcv_strat, IS_START, IS_END, rng, label)
        m = compute_metrics(eq, closed)
        is_results.append((label, m, fric))
        print(f"    {label} IS: final=${m.get('final_eq',1000):,.0f}, Mo={m.get('mo',0):+.2f}%")

    # Print detailed OOS results
    print(f"\n{'═'*70}")
    print("  OOS DETAILED RESULTS (2021-2024)")
    print(f"{'═'*70}")
    for label, m, fric, closed, ideal_key in oos_results:
        print_result(
            f"{label} OOS — {_label_desc(label)}",
            m, fric, closed, IDEAL.get(ideal_key, {})
        )

    # Summary verdict table
    print_verdict([(label, m, fric) for label, m, fric, _, _ in oos_results])

    # IS summary
    print(f"\n{'═'*70}")
    print("  IS SUMMARY (2018-2020) — open-position mark-to-market at period end")
    print(f"{'═'*70}")
    print(f"  {'Strategy':<10} {'Mo%':>7} {'Sharpe':>7} {'MaxDD':>8} {'FinalEq':>9} {'N closed':>9}")
    for label, m, _ in is_results:
        if m:
            print(f"  {label:<10} {m['mo']:>+7.2f} {m['sr']:>7.2f} {m['dd']:>7.1f}% "
                  f"${m['final_eq']:>8,.0f} {m['n']:>9d}")


def _label_desc(label: str) -> str:
    return {
        "Iter62": "BTC AdrActCnt + ETH TxCnt",
        "Iter69": "BTC AdrActCnt + ETH/BTC Ratio",
        "Iter71": "BTC AdrActCnt + ETH AdrActCnt (XRP)",
        "Iter73": "ETH TxCnt + ETH AdrActCnt",
        "Iter78": "BTC AdrActCnt + ETH AdrActCnt (LINK)",
    }.get(label, label)


if __name__ == "__main__":
    main()
