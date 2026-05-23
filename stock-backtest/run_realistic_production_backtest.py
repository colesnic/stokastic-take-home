"""
Realistic Production Backtest — Iter 68 + Iter 74
==================================================
$1,000 bankroll with 7 production-grade execution variables:

  1. BANKROLL:         $1,000 starting capital (vs $100k idealized tests)
  2. LATENCY:         1-trading-day execution delay (EOD signal → next-day Open)
  3. COMMISSION:      0.25% taker fee per leg (Coinbase Advanced / Binance equivalent)
  4. SPREAD SLIPPAGE: Asset-specific bid-ask slippage (5-30 bps by liquidity tier)
  5. CASH YIELD:      Fed Funds rate on idle cash (0.1%→5% APY, time-varying)
  6. EXECUTION NOISE: ±0.3% random open-price uncertainty (fill vs expected open)
  7. MIN POSITION:    $10 minimum order size (exchange minimums at $1k bankroll)

Strategies:
  ITER 68 — BTC price + BTC AdrActCnt + ETH AvgGasPrice
            IS champion: EMA100, act=30/90, vol<0.80, mhd=365

  ITER 74 — BTC price + ETH/BTC Ratio + ETH AdrActCnt
            IS champion: EMA150, act=20/60, vol<0.60, mhd=365

OOS period: 2021-01-01 to 2024-12-31
"""

import urllib.request
import io
import os
import sys
import numpy as np
import pandas as pd
import warnings
from dataclasses import dataclass, field
from typing import Dict, List, Optional, Tuple
warnings.filterwarnings("ignore")

sys.path.insert(0, os.path.dirname(__file__))
from indicators import ema as ema_fn, atr as atr_fn, adx as adx_fn

# ─────────────────────────────────────────────────────────────────────────────
# PRODUCTION REALISM PARAMETERS
# ─────────────────────────────────────────────────────────────────────────────

INITIAL_CAPITAL  = 1_000.0    # Variable 1: $1,000 bankroll
EXEC_DELAY_DAYS  = 1          # Variable 2: 1-day execution latency
COMMISSION_RATE  = 0.0025     # Variable 3: 0.25% taker fee per leg
EXEC_NOISE_PCT   = 0.003      # Variable 6: ±0.3% open-price uncertainty
MIN_POSITION_USD = 10.0       # Variable 7: $10 minimum position size

# Variable 4: Bid-ask spread slippage (one-way, fraction)
SLIPPAGE: Dict[str, float] = {
    "BTC":  0.0005,   # 5 bps — deepest liquidity on earth
    "ETH":  0.0010,   # 10 bps
    "BNB":  0.0020,   # 20 bps
    "ADA":  0.0030,   # 30 bps — smaller-cap altcoin
    "XRP":  0.0025,   # 25 bps
    "LINK": 0.0025,   # 25 bps
}

# Variable 5: Fed Funds rate proxy for cash yield (annualized)
CASH_YIELD_SCHEDULE = [
    (pd.Timestamp("2018-01-01"), pd.Timestamp("2022-03-15"), 0.0010),  # ZIRP era
    (pd.Timestamp("2022-03-16"), pd.Timestamp("2022-06-30"), 0.0100),  # First hikes
    (pd.Timestamp("2022-07-01"), pd.Timestamp("2022-12-31"), 0.0300),  # Rapid hikes
    (pd.Timestamp("2023-01-01"), pd.Timestamp("2023-12-31"), 0.0525),  # Peak (5.25%)
    (pd.Timestamp("2024-01-01"), pd.Timestamp("2024-12-31"), 0.0525),  # Held at peak
]

TAX_STCG    = 0.35
TAX_LTCG    = 0.20
LTCG_DAYS   = 365
POSITION_PCT = 0.20  # 20% of portfolio per position
MAX_POS      = 5

COINMETRICS = "https://raw.githubusercontent.com/coinmetrics/data/master/csv/{}.csv"
IS_START  = "2018-01-01"
IS_END    = "2020-12-31"
OOS_START = "2021-01-01"
OOS_END   = "2024-12-31"


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
    print("  Fetching BTC (price + AdrActCnt)...")
    btc = fetch_coinmetrics("btc", [("PriceUSD","Close"), ("AdrActCnt","AdrActCnt")])
    print("  Fetching ETH (price + AdrActCnt + FeeTotNtv + TxCnt)...")
    eth = fetch_coinmetrics("eth", [
        ("PriceUSD","Close"), ("AdrActCnt","AdrActCnt"),
        ("FeeTotNtv","FeeTotNtv"), ("TxCnt","TxCnt"),
    ])
    eth["AvgGasPrice"] = eth["FeeTotNtv"] / eth["TxCnt"]
    eth["Ratio"] = eth["Close"] / btc["Close"].reindex(eth.index).ffill()
    return btc, eth


def fetch_asset_prices() -> Dict[str, pd.Series]:
    assets = {}
    for coin in ("btc", "eth", "bnb", "ada", "xrp", "link"):
        ticker = coin.upper()
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
# SIGNAL COMPUTATION
# ─────────────────────────────────────────────────────────────────────────────

def compute_iter68_signals(
    btc: pd.DataFrame, eth: pd.DataFrame,
    ema_period: int = 100, act_short: int = 30, act_long: int = 90,
    vol_lookback: int = 30, vol_threshold: float = 0.80, min_hold_days: int = 365,
    rebalance_days: int = 7,
) -> Dict[str, pd.Series]:
    """
    ITER 68: BTC price > EMA + BTC AdrActCnt trend + ETH AvgGasPrice trend.
    IS champion: EMA100, act=30/90, vol<0.80, mhd=365
    """
    btc_close = btc["Close"]

    price_bull  = btc_close > ema_fn(btc_close, ema_period)

    btc_adr     = btc["AdrActCnt"].reindex(btc_close.index).ffill()
    adr_bull    = (ema_fn(btc_adr, act_short) > ema_fn(btc_adr, act_long)).fillna(False)

    gas         = eth["AvgGasPrice"].reindex(btc_close.index).ffill()
    gas_bull    = (ema_fn(gas, act_short) > ema_fn(gas, act_long)).fillna(False)

    regime_bull = price_bull & adr_bull & gas_bull

    vol30   = btc_close.pct_change().rolling(vol_lookback).std() * np.sqrt(252)
    vol_ok  = (vol30 < vol_threshold).fillna(False)
    entry_ok = regime_bull & vol_ok

    COINS = [("BTC",42), ("ETH",11), ("BNB",77), ("ADA",99), ("XRP",17)]
    return _build_signals(btc_close.index, COINS, regime_bull, entry_ok, min_hold_days, rebalance_days)


def compute_iter74_signals(
    btc: pd.DataFrame, eth: pd.DataFrame,
    ema_period: int = 150, act_short: int = 20, act_long: int = 60,
    vol_lookback: int = 30, vol_threshold: float = 0.60, min_hold_days: int = 365,
    rebalance_days: int = 7,
) -> Dict[str, pd.Series]:
    """
    ITER 74: BTC price > EMA + ETH/BTC Ratio trend + ETH AdrActCnt trend.
    IS champion: EMA150, act=20/60, vol<0.60, mhd=365
    """
    btc_close = btc["Close"]

    price_bull  = btc_close > ema_fn(btc_close, ema_period)

    ratio       = eth["Ratio"].reindex(btc_close.index).ffill()
    ratio_bull  = (ema_fn(ratio, act_short) > ema_fn(ratio, act_long)).fillna(False)

    eth_adr     = eth["AdrActCnt"].reindex(btc_close.index).ffill()
    adr_bull    = (ema_fn(eth_adr, act_short) > ema_fn(eth_adr, act_long)).fillna(False)

    regime_bull = price_bull & ratio_bull & adr_bull

    vol30   = btc_close.pct_change().rolling(vol_lookback).std() * np.sqrt(252)
    vol_ok  = (vol30 < vol_threshold).fillna(False)
    entry_ok = regime_bull & vol_ok

    COINS = [("BTC",42), ("ETH",11), ("BNB",77), ("ADA",99), ("XRP",17)]
    return _build_signals(btc_close.index, COINS, regime_bull, entry_ok, min_hold_days, rebalance_days)


def _build_signals(
    all_dates, coins, regime_bull, entry_ok, min_hold_days, rebalance_days
) -> Dict[str, pd.Series]:
    in_position = {}
    sig = {t: pd.Series(0, index=all_dates, dtype=int) for t, _ in coins}
    last_reb = None

    for date in all_dates:
        if last_reb is not None and (date - last_reb).days < rebalance_days:
            continue
        last_reb = date

        exit_now  = not regime_bull.get(date, True)
        enter_now = bool(entry_ok.get(date, False))

        if exit_now:
            for t in list(in_position):
                held = (date - in_position[t]).days
                if held >= min_hold_days:
                    sig[t].loc[date] = -1
                    del in_position[t]
        elif enter_now:
            for t, _ in coins:
                if t not in in_position:
                    sig[t].loc[date] = 1
                    in_position[t] = date

    return sig


# ─────────────────────────────────────────────────────────────────────────────
# REALISTIC EXECUTION ENGINE
# ─────────────────────────────────────────────────────────────────────────────

def get_cash_yield_daily(date: pd.Timestamp) -> float:
    """Time-varying daily cash yield (Fed Funds rate proxy)."""
    for start, end, annual in CASH_YIELD_SCHEDULE:
        if start <= date <= end:
            return (1 + annual) ** (1 / 365) - 1
    return 0.0


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
    cost_basis:  float   # total cost including all frictions


@dataclass
class OpenPosition:
    ticker:       str
    entry_date:   pd.Timestamp
    entry_price:  float   # actual execution price (after slippage + noise)
    shares:       float
    cost_basis:   float   # amount of cash actually deployed


def run_realistic(
    signals:   Dict[str, pd.Series],
    ohlcv:     Dict[str, pd.DataFrame],
    start:     str,
    end:       str,
    rng:       np.random.Generator,
    label:     str = "",
) -> Tuple[pd.DataFrame, List[ClosedTrade], Dict]:
    """
    Realistic execution engine.
    All 7 production variables applied:
      1. $1,000 bankroll
      2. 1-day execution latency
      3. 0.25% commission per leg
      4. Asset-specific bid-ask slippage
      5. Time-varying cash yield
      6. ±0.3% execution noise
      7. $10 minimum position size
    """
    cash      = INITIAL_CAPITAL
    positions: Dict[str, OpenPosition] = {}
    closed:    List[ClosedTrade] = []
    equity_rows = []

    # pending_orders: {ticker: ("BUY"|"SELL", signal_date)}
    pending: Dict[str, Tuple[str, pd.Timestamp]] = {}

    dates = sorted(set.intersection(
        *[set(ohlcv[t].index) for t in ohlcv]
    ))
    dates = [d for d in dates if pd.Timestamp(start) <= d <= pd.Timestamp(end)]

    friction_log: Dict[str, float] = {
        "commission_paid": 0.0,
        "spread_slippage_paid": 0.0,
        "execution_noise_impact": 0.0,
        "cash_yield_earned": 0.0,
        "tax_paid": 0.0,
        "positions_blocked_min_size": 0,
    }

    for i, date in enumerate(dates):
        # ── Variable 5: Credit daily cash yield on idle cash ──────────────────
        daily_yield = get_cash_yield_daily(date)
        yield_amount = cash * daily_yield
        cash += yield_amount
        friction_log["cash_yield_earned"] += yield_amount

        # ── Variable 2: Execute orders pending from previous day ──────────────
        for ticker, (direction, sig_date) in list(pending.items()):
            if ticker not in ohlcv:
                del pending[ticker]
                continue

            df = ohlcv[ticker]
            if date not in df.index:
                continue

            # Variable 6: execution price = Open ± noise
            open_px = float(df.loc[date, "Open"])
            noise_frac = rng.uniform(-EXEC_NOISE_PCT, EXEC_NOISE_PCT)

            slip = SLIPPAGE.get(ticker, 0.002)

            if direction == "BUY":
                # Variable 4: spread slippage on buy (pay the ask)
                exec_price = open_px * (1 + noise_frac + slip)

                # Variable 3: commission on entry
                position_target = (cash + sum(
                    pos.shares * float(ohlcv[pos.ticker].loc[date, "Close"])
                    for pos in positions.values() if date in ohlcv[pos.ticker].index
                )) * POSITION_PCT

                # Variable 7: enforce minimum position
                if position_target < MIN_POSITION_USD:
                    friction_log["positions_blocked_min_size"] += 1
                    del pending[ticker]
                    continue

                commission_entry = position_target * COMMISSION_RATE
                friction_log["commission_paid"] += commission_entry
                friction_log["spread_slippage_paid"] += position_target * slip
                # Variable 6: noise impact measured on position dollar value
                friction_log["execution_noise_impact"] += abs(position_target * noise_frac)

                cash_needed = position_target + commission_entry
                if cash_needed > cash:
                    cash_needed = cash  # use all available cash
                    position_target = cash_needed / (1 + COMMISSION_RATE)

                if position_target < MIN_POSITION_USD:
                    friction_log["positions_blocked_min_size"] += 1
                    del pending[ticker]
                    continue

                shares = position_target / exec_price
                cash  -= (position_target + commission_entry)
                positions[ticker] = OpenPosition(
                    ticker=ticker,
                    entry_date=date,
                    entry_price=exec_price,
                    shares=shares,
                    cost_basis=position_target + commission_entry,
                )

            elif direction == "SELL" and ticker in positions:
                pos = positions[ticker]
                # Variable 4: spread slippage on sell (hit the bid)
                exec_price = open_px * (1 + noise_frac - slip)
                proceeds   = pos.shares * exec_price

                # Variable 3: commission on exit
                commission_exit = proceeds * COMMISSION_RATE
                friction_log["commission_paid"] += commission_exit
                friction_log["spread_slippage_paid"] += proceeds * slip
                # Variable 6: noise impact on exit proceeds
                friction_log["execution_noise_impact"] += abs(proceeds * noise_frac)

                net_proceeds = proceeds - commission_exit
                gross_pnl    = net_proceeds - pos.cost_basis
                hold_days    = (date - pos.entry_date).days

                # Tax: STCG or LTCG depending on hold duration
                if gross_pnl > 0:
                    tax_rate = TAX_LTCG if hold_days >= LTCG_DAYS else TAX_STCG
                    tax = gross_pnl * tax_rate
                else:
                    tax = 0.0  # capital losses reduce future gains (simplified: no benefit)

                friction_log["tax_paid"] += tax
                net_pnl = gross_pnl - tax
                cash += net_proceeds - tax

                closed.append(ClosedTrade(
                    ticker=ticker,
                    entry_date=pos.entry_date,
                    exit_date=date,
                    entry_price=pos.entry_price,
                    exit_price=exec_price,
                    shares=pos.shares,
                    gross_pnl=gross_pnl,
                    tax_paid=tax,
                    net_pnl=net_pnl,
                    hold_days=hold_days,
                    cost_basis=pos.cost_basis,
                ))
                del positions[ticker]

            del pending[ticker]

        # ── Read signals for today (execute tomorrow) ─────────────────────────
        if i + 1 < len(dates):
            for ticker, sig_series in signals.items():
                if date in sig_series.index:
                    sig_val = int(sig_series.loc[date])
                    if sig_val == 1 and ticker not in positions and ticker not in pending:
                        pending[ticker] = ("BUY", date)
                    elif sig_val == -1 and ticker in positions and ticker not in pending:
                        pending[ticker] = ("SELL", date)

        # ── Mark-to-market portfolio value ────────────────────────────────────
        portfolio_value = cash
        for ticker, pos in positions.items():
            if ticker in ohlcv and date in ohlcv[ticker].index:
                mkt_price = float(ohlcv[ticker].loc[date, "Close"])
                portfolio_value += pos.shares * mkt_price

        equity_rows.append({"date": date, "equity": portfolio_value, "cash": cash,
                             "n_positions": len(positions)})

    eq_df = pd.DataFrame(equity_rows).set_index("date")
    return eq_df, closed, friction_log


# ─────────────────────────────────────────────────────────────────────────────
# METRICS
# ─────────────────────────────────────────────────────────────────────────────

def compute_metrics(eq_df: pd.DataFrame, closed: List[ClosedTrade]) -> Dict:
    eq = eq_df["equity"]
    if len(eq) < 2:
        return {}

    monthly = eq.resample("ME").last().pct_change().dropna()
    total_ret = (eq.iloc[-1] / eq.iloc[0]) - 1
    n_months  = len(monthly)
    ann_ret   = (1 + total_ret) ** (12 / max(n_months, 1)) - 1
    monthly_ret = (1 + total_ret) ** (1 / max(n_months, 1)) - 1

    vol_monthly = monthly.std()
    sharpe = (monthly.mean() / vol_monthly * np.sqrt(12)) if vol_monthly > 0 else 0.0

    roll_max = eq.cummax()
    drawdown = (eq - roll_max) / roll_max
    max_dd   = float(drawdown.min())
    calmar   = ann_ret / abs(max_dd) if max_dd != 0 else 0.0

    wins    = [t for t in closed if t.net_pnl > 0]
    losses  = [t for t in closed if t.net_pnl <= 0]
    win_rate = len(wins) / len(closed) if closed else 0.0
    gross_wins   = sum(t.gross_pnl for t in wins)
    gross_losses = sum(abs(t.gross_pnl) for t in losses)
    pf = gross_wins / gross_losses if gross_losses > 0 else float("inf")
    avg_hold = np.mean([t.hold_days for t in closed]) if closed else 0.0

    avg_win  = np.mean([t.net_pnl / t.cost_basis * 100 for t in wins]) if wins else 0.0
    avg_loss = np.mean([t.net_pnl / t.cost_basis * 100 for t in losses]) if losses else 0.0

    return dict(
        total_return_pct   = total_ret * 100,
        monthly_return_pct = monthly_ret * 100,
        annual_return_pct  = ann_ret * 100,
        sharpe             = sharpe,
        max_drawdown_pct   = max_dd * 100,
        calmar             = calmar,
        n_trades           = len(closed),
        win_rate_pct       = win_rate * 100,
        profit_factor      = pf,
        avg_hold_days      = avg_hold,
        avg_win_pct        = avg_win,
        avg_loss_pct       = avg_loss,
        final_equity       = float(eq.iloc[-1]),
    )


def print_metrics(label: str, m: Dict, friction: Dict, closed: List[ClosedTrade]):
    sep = "─" * 62
    print(f"\n{sep}")
    print(f"  {label}")
    print(sep)
    print(f"  Final equity    ${m['final_equity']:>10,.2f}  (started $1,000)")
    print(f"  Total return    {m['total_return_pct']:>+9.1f}%")
    print(f"  Monthly return  {m['monthly_return_pct']:>+9.2f}%/mo")
    print(f"  Annual return   {m['annual_return_pct']:>+9.1f}%/yr")
    print(f"  Sharpe ratio    {m['sharpe']:>9.2f}")
    print(f"  Max drawdown    {m['max_drawdown_pct']:>+9.2f}%")
    print(f"  Calmar ratio    {m['calmar']:>9.2f}")
    print(f"  N trades        {m['n_trades']:>9}")
    print(f"  Win rate        {m['win_rate_pct']:>9.1f}%")
    print(f"  Profit factor   {m['profit_factor']:>9.2f}" if m['profit_factor'] != float("inf")
          else f"  Profit factor   {'∞':>9}")
    print(f"  Avg hold        {m['avg_hold_days']:>9.0f} days")
    print(f"  Avg win         {m['avg_win_pct']:>+9.1f}%")
    print(f"  Avg loss        {m['avg_loss_pct']:>+9.1f}%")

    print(f"\n  ── Friction Breakdown ─────────────────────────────────")
    print(f"  Commission paid         ${friction['commission_paid']:>8.2f}")
    print(f"  Spread slippage paid    ${friction['spread_slippage_paid']:>8.2f}")
    print(f"  Execution noise impact  ${friction['execution_noise_impact']:>8.2f}")
    print(f"  Tax paid                ${friction['tax_paid']:>8.2f}")
    print(f"  Cash yield earned       ${friction['cash_yield_earned']:>8.2f}")
    print(f"  Orders blocked (min sz) {friction['positions_blocked_min_size']:>8}")

    total_friction = (friction['commission_paid'] + friction['spread_slippage_paid']
                      + friction['tax_paid'] - friction['cash_yield_earned'])
    print(f"  Net friction cost       ${total_friction:>8.2f}  "
          f"({total_friction/INITIAL_CAPITAL*100:.1f}% of bankroll)")

    if closed:
        print(f"\n  ── Individual Trades ──────────────────────────────────")
        print(f"  {'Ticker':>6}  {'Entry':>10}  {'Exit':>10}  {'Hold':>5}  {'PnL$':>7}  {'Tax$':>6}  {'Net%':>6}")
        for t in sorted(closed, key=lambda x: x.entry_date):
            pct = t.net_pnl / t.cost_basis * 100
            tag = "LTCG" if t.hold_days >= LTCG_DAYS else "STCG"
            print(f"  {t.ticker:>6}  {str(t.entry_date.date()):>10}  "
                  f"{str(t.exit_date.date()):>10}  {t.hold_days:>4}d  "
                  f"${t.net_pnl:>+6.1f}  ${t.tax_paid:>5.1f}  "
                  f"{pct:>+5.1f}% ({tag})")


def compare_to_idealized(label_68: str, m_68: Dict, label_74: str, m_74: Dict):
    """Side-by-side comparison: realistic vs idealized backtest."""
    # Idealized results (from original backtests, scaled to $1,000 bankroll)
    IDEAL_68 = dict(monthly_pct=3.14, sharpe=1.25, max_dd=-31.81, wr=70.0, pf=7.62)
    IDEAL_74 = dict(monthly_pct=2.90, sharpe=1.19, max_dd=-25.33, wr=70.0, pf=18.84)

    print(f"\n{'═'*72}")
    print(f"  IDEALIZED vs REALISTIC COMPARISON")
    print(f"{'═'*72}")
    print(f"  {'Metric':<22} {'Ideal 68':>10} {'Real 68':>10} {'Ideal 74':>10} {'Real 74':>10}")
    print(f"  {'-'*62}")

    metrics = [
        ("Monthly %/mo",   "monthly_return_pct", "monthly_pct", "+.2f"),
        ("Sharpe",         "sharpe",             "sharpe",      ".2f"),
        ("MaxDD %",        "max_drawdown_pct",   "max_dd",      "+.1f"),
        ("Win Rate %",     "win_rate_pct",        "wr",          ".0f"),
        ("Profit Factor",  "profit_factor",       "pf",          ".2f"),
    ]
    for label, real_key, ideal_key, fmt in metrics:
        r68 = m_68.get(real_key, 0)
        r74 = m_74.get(real_key, 0)
        i68 = IDEAL_68.get(ideal_key, 0)
        i74 = IDEAL_74.get(ideal_key, 0)
        fstr = f"{{:{fmt}}}"
        print(f"  {label:<22} {fstr.format(i68):>10} {fstr.format(r68):>10} "
              f"{fstr.format(i74):>10} {fstr.format(r74):>10}")

    print(f"\n  Note: $1,000 bankroll realistic results include all 7 friction variables.")
    print(f"  Idealized results used $100,000 bankroll with simplified execution.")


# ─────────────────────────────────────────────────────────────────────────────
# MAIN
# ─────────────────────────────────────────────────────────────────────────────

def main():
    print("\n" + "═" * 72)
    print("  REALISTIC PRODUCTION BACKTEST — Iter 68 + Iter 74")
    print("  $1,000 bankroll | 7 production realism variables")
    print("═" * 72)
    print(f"""
  7 Production Variables Applied:
  ┌─────┬──────────────────────────────────────────────────────────┐
  │  1  │ BANKROLL:       $1,000 starting capital                  │
  │  2  │ LATENCY:        1-day execution delay (EOD → next Open)  │
  │  3  │ COMMISSION:     0.25% taker fee per leg (Coinbase/Binance)│
  │  4  │ SPREAD SLIP:    5-30 bps/asset (BTC 5bps, ADA/LINK 30bps)│
  │  5  │ CASH YIELD:     Fed Funds rate on idle cash (0.1%→5.25%) │
  │  6  │ EXEC NOISE:     ±0.30% open-price fill uncertainty       │
  │  7  │ MIN POSITION:   $10 minimum order enforced               │
  └─────┴──────────────────────────────────────────────────────────┘

  IS champion params:
    Iter 68: EMA100, act=30/90, vol<0.80, mhd=365 (BTC AdrActCnt + ETH GasPrice)
    Iter 74: EMA150, act=20/60, vol<0.60, mhd=365 (ETH/BTC Ratio + ETH AdrActCnt)
""")

    # ── Fetch data ────────────────────────────────────────────────────────────
    btc, eth = fetch_all_data()
    print("  Fetching individual asset price data...")
    asset_prices = fetch_asset_prices()

    # Build OHLCV for all assets
    seeds = {"BTC":42, "ETH":11, "BNB":77, "ADA":99, "XRP":17, "LINK":23}
    ohlcv = {t: synthesize_ohlcv(p, seed=seeds[t]) for t, p in asset_prices.items()}

    # ── Compute signals (full period, then slice) ──────────────────────────────
    print("\n  Computing Iter 68 signals (EMA100, act=30/90, vol<0.80, mhd=365)...")
    sig68 = compute_iter68_signals(btc, eth)

    print("  Computing Iter 74 signals (EMA150, act=20/60, vol<0.60, mhd=365)...")
    sig74 = compute_iter74_signals(btc, eth)

    rng = np.random.default_rng(2024)  # fixed seed for reproducibility

    # ── IS period (2018-2020) ──────────────────────────────────────────────────
    print(f"\n  Running IS period ({IS_START} to {IS_END})...")
    ohlcv_is = {t: df.loc[IS_START:IS_END] for t, df in ohlcv.items() if len(df.loc[IS_START:IS_END]) >= 60}

    eq68_is, closed68_is, fric68_is = run_realistic(sig68, ohlcv_is, IS_START, IS_END, rng, "Iter 68 IS")
    eq74_is, closed74_is, fric74_is = run_realistic(sig74, ohlcv_is, IS_START, IS_END, rng, "Iter 74 IS")

    m68_is = compute_metrics(eq68_is, closed68_is)
    m74_is = compute_metrics(eq74_is, closed74_is)

    # ── OOS period (2021-2024) ─────────────────────────────────────────────────
    print(f"  Running OOS period ({OOS_START} to {OOS_END})...")
    ohlcv_oos = {t: df.loc[OOS_START:OOS_END] for t, df in ohlcv.items() if len(df.loc[OOS_START:OOS_END]) >= 60}

    eq68_oos, closed68_oos, fric68_oos = run_realistic(sig68, ohlcv_oos, OOS_START, OOS_END, rng, "Iter 68 OOS")
    eq74_oos, closed74_oos, fric74_oos = run_realistic(sig74, ohlcv_oos, OOS_START, OOS_END, rng, "Iter 74 OOS")

    m68_oos = compute_metrics(eq68_oos, closed68_oos)
    m74_oos = compute_metrics(eq74_oos, closed74_oos)

    # ── Print results ──────────────────────────────────────────────────────────
    print_metrics("ITER 68 — IS Period (2018-2020) [BTC AdrActCnt + ETH GasPrice]", m68_is, fric68_is, closed68_is)
    print_metrics("ITER 68 — OOS Period (2021-2024) [BTC AdrActCnt + ETH GasPrice]", m68_oos, fric68_oos, closed68_oos)
    print_metrics("ITER 74 — IS Period (2018-2020) [ETH/BTC Ratio + ETH AdrActCnt]", m74_is, fric74_is, closed74_is)
    print_metrics("ITER 74 — OOS Period (2021-2024) [ETH/BTC Ratio + ETH AdrActCnt]", m74_oos, fric74_oos, closed74_oos)

    # ── Comparison ────────────────────────────────────────────────────────────
    compare_to_idealized("Iter 68", m68_oos, "Iter 74", m74_oos)

    # ── Verdict ────────────────────────────────────────────────────────────────
    thresholds = [("Monthly >= 2.0%", "monthly_return_pct", 2.0),
                  ("Sharpe >= 1.0",   "sharpe",             1.0),
                  ("MaxDD > -40%",    "max_drawdown_pct",  -40.0),
                  ("Calmar >= 0.8",   "calmar",             0.8),
                  ("Win Rate >= 40%", "win_rate_pct",       40.0),
                  ("N Trades >= 5",   "n_trades",           5)]

    print(f"\n{'═'*72}")
    print(f"  OOS VERDICT — REALISTIC $1,000 BANKROLL")
    print(f"{'═'*72}")
    for label, key, thr in thresholds:
        v68 = m68_oos.get(key, 0); v74 = m74_oos.get(key, 0)
        ok68 = v68 >= thr; ok74 = v74 >= thr
        s68 = "PASS" if ok68 else "FAIL"
        s74 = "PASS" if ok74 else "FAIL"
        val_fmt = f"{v68:+.2f}" if isinstance(v68, float) else str(int(v68))
        val74_fmt = f"{v74:+.2f}" if isinstance(v74, float) else str(int(v74))
        print(f"  {label:<22}  68:[{s68}] {val_fmt:>8}   74:[{s74}] {val74_fmt:>8}")

    p68 = sum(1 for _, k, t in thresholds if m68_oos.get(k,0) >= t)
    p74 = sum(1 for _, k, t in thresholds if m74_oos.get(k,0) >= t)
    print(f"\n  Iter 68 realistic verdict: {p68}/6 criteria pass")
    print(f"  Iter 74 realistic verdict: {p74}/6 criteria pass")
    print(f"\n  Final equity comparison (started $1,000 each):")
    print(f"    Iter 68 OOS: ${m68_oos.get('final_equity',1000):>10,.2f}")
    print(f"    Iter 74 OOS: ${m74_oos.get('final_equity',1000):>10,.2f}")
    print(f"\n  Key insight: Realistic friction cost at $1,000 bankroll is substantial.")
    print(f"  Commission + spread per round-trip (BTC): ~0.55% | ADA/XRP/LINK: ~0.80%")
    print(f"  At $200/position, cash yield partially offsets friction in cash periods.")


if __name__ == "__main__":
    main()
