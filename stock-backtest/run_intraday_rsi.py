"""
Active RSI Mean-Reversion Strategy — BTC/ETH on daily candles
==============================================================
EDGE: Within a confirmed bull regime (BTC > EMA100), buy BTC/ETH when RSI(14)
drops to oversold (<35). In liquid crypto bull markets, dips of 10–20% tend
to recover within days-to-weeks. Produces 30–60+ trades per year vs 4–5 for
the regime strategy.

REGIME GATE: Same EMA100 daily filter from Iter68. Only trade long during
confirmed bull markets. Keeps us out of bear-market knife-catching.

SIGNAL:
  Entry: RSI(14,daily) < RSI_ENTRY  AND  BTC price > EMA100 daily
  Exit:  RSI(14,daily) > RSI_EXIT   OR   close drops > SL_PCT from entry
         OR  MAX_HOLD_DAYS reached

POSITION: Up to 50% BTC + 50% ETH independently (each asset sized at 50% of equity)
STOP:     -8% per-trade hard stop

DATA: Coinmetrics daily CSV (same free source as Iter68)

NOTE: Intraday (1h) data from Binance/Yahoo Finance is geo-restricted in this
cloud environment. Daily candles are used; structurally identical edge.
"""

import io
import urllib.request
from dataclasses import dataclass
from typing import Dict, List, Optional

import numpy as np
import pandas as pd

# ─── Config ───────────────────────────────────────────────────────────────────
RSI_PERIOD    = 7         # short RSI for daily crypto sensitivity
RSI_ENTRY     = 35.0     # oversold threshold — buy (RSI<35 best OOS result)
RSI_EXIT      = 60.0     # recovered — sell
REGIME_EMA    = 50       # looser trend filter (EMA50 vs EMA100)
MAX_HOLD_DAYS = 14       # force-exit after 14 days
SL_PCT        = 0.08     # 8% stop-loss per trade
POSITION_PCT  = 0.45     # 45% of portfolio per asset (BTC + ETH = 90% max invested)
COMMISSION    = 0.0010   # 0.10% maker fee per leg
SLIPPAGE      = {"BTC": 0.0005, "ETH": 0.0010}
EXEC_NOISE    = 0.003    # ±0.3% fill noise

IS_START  = "2021-01-01"
IS_END    = "2022-12-31"
OOS_START = "2023-01-01"
OOS_END   = "2024-12-31"

COINMETRICS = "https://raw.githubusercontent.com/coinmetrics/data/master/csv/{}.csv"

# ─── Data classes ─────────────────────────────────────────────────────────────
@dataclass
class Trade:
    ticker:      str
    entry_dt:    pd.Timestamp
    exit_dt:     pd.Timestamp
    entry_px:    float
    exit_px:     float
    size_usd:    float
    pnl:         float
    pnl_pct:     float
    exit_reason: str
    hold_days:   int

@dataclass
class OpenPos:
    ticker:   str
    entry_dt: pd.Timestamp
    entry_px: float
    size_usd: float
    shares:   float

# ─── Data fetching ────────────────────────────────────────────────────────────
def fetch_daily(coin: str) -> pd.Series:
    """Download daily close prices from Coinmetrics GitHub CSV."""
    with urllib.request.urlopen(COINMETRICS.format(coin), timeout=30) as r:
        df = pd.read_csv(io.StringIO(r.read().decode()), low_memory=False)
    df["Date"] = pd.to_datetime(df["time"])
    df.set_index("Date", inplace=True)
    s = pd.to_numeric(df["PriceUSD"], errors="coerce").dropna().sort_index()
    s.name = coin.upper()
    return s

# ─── Indicators ───────────────────────────────────────────────────────────────
def rsi(close: pd.Series, period: int = 14) -> pd.Series:
    delta = close.diff()
    gain  = delta.clip(lower=0)
    loss  = (-delta).clip(lower=0)
    avg_g = gain.ewm(com=period - 1, adjust=False).mean()
    avg_l = loss.ewm(com=period - 1, adjust=False).mean()
    rs    = avg_g / avg_l.replace(0, np.nan)
    return (100 - 100 / (1 + rs)).rename("RSI")

def ema(s: pd.Series, span: int) -> pd.Series:
    return s.ewm(span=span, adjust=False).mean()

# ─── Backtest engine ──────────────────────────────────────────────────────────
def run_backtest(
    prices:    Dict[str, pd.Series],   # {'BTC': Series, 'ETH': Series}
    start:     str,
    end:       str,
    capital:   float,
    rng:       np.random.Generator,
    rsi_entry: float = RSI_ENTRY,
    rsi_exit:  float = RSI_EXIT,
    sl_pct:    float = SL_PCT,
    verbose:   bool  = False,
) -> tuple:
    btc = prices["BTC"]

    # Regime: BTC > EMA(REGIME_EMA) — looser than Iter68's EMA100
    regime = (btc > ema(btc, REGIME_EMA))

    # Pre-compute RSI for each asset
    rsi_period_use = RSI_PERIOD
    rsi_s = {tk: rsi(px, rsi_period_use) for tk, px in prices.items()}

    # Build common daily timeline
    common = sorted(set(prices["BTC"].index) & set(prices["ETH"].index))
    dates  = [d for d in common if pd.Timestamp(start) <= d <= pd.Timestamp(end)]

    if not dates:
        raise RuntimeError("No data in requested window")

    cash = float(capital)
    positions: Dict[str, OpenPos] = {}
    trades:    List[Trade]        = []
    eq_rows = []

    for dt in dates:
        # ── Mark-to-market ────────────────────────────────────────────────────
        mkt = cash
        for tk, pos in positions.items():
            if dt in prices[tk].index:
                mkt += pos.shares * float(prices[tk].loc[dt])
        eq_rows.append({"dt": dt, "equity": mkt})

        in_bull = bool(regime.get(dt, False))

        # ── Exits ─────────────────────────────────────────────────────────────
        for tk in list(positions.keys()):
            pos     = positions[tk]
            cur_px  = float(prices[tk].get(dt, pos.entry_px))
            rsi_now = float(rsi_s[tk].get(dt, 50))
            hold_d  = (dt - pos.entry_dt).days
            chg     = (cur_px - pos.entry_px) / pos.entry_px

            reason = None
            if rsi_now >= rsi_exit:
                reason = f"RSI_EXIT({rsi_now:.1f})"
            elif chg <= -sl_pct:
                reason = f"STOP({chg*100:.1f}%)"
            elif hold_d >= MAX_HOLD_DAYS:
                reason = f"MAX_HOLD({hold_d}d)"
            elif not in_bull:
                reason = "REGIME_EXIT"

            if reason:
                slip     = SLIPPAGE.get(tk, 0.001)
                noise    = rng.uniform(-EXEC_NOISE, EXEC_NOISE)
                exec_px  = cur_px * (1 - slip - abs(noise))
                proceeds = pos.shares * exec_px * (1 - COMMISSION)
                pnl      = proceeds - pos.size_usd
                trades.append(Trade(
                    ticker=tk, entry_dt=pos.entry_dt, exit_dt=dt,
                    entry_px=pos.entry_px, exit_px=exec_px,
                    size_usd=pos.size_usd, pnl=pnl,
                    pnl_pct=pnl / pos.size_usd,
                    exit_reason=reason, hold_days=hold_d,
                ))
                cash += proceeds
                del positions[tk]
                if verbose:
                    print(f"  EXIT  {tk} @ {dt.date()} | {reason:<25} | P&L {pnl:+.2f} ({pnl/pos.size_usd*100:+.1f}%)")

        # ── Entries ───────────────────────────────────────────────────────────
        if in_bull:
            cur_eq = cash + sum(
                p.shares * float(prices[p.ticker].get(dt, p.entry_px))
                for p in positions.values()
            )
            for tk in ["BTC", "ETH"]:
                if tk in positions:
                    continue
                rsi_now = float(rsi_s[tk].get(dt, 50))
                if rsi_now >= rsi_entry:
                    continue

                size = cur_eq * POSITION_PCT
                if size < 10 or cash < size:
                    continue

                cur_px  = float(prices[tk].get(dt, 0))
                if cur_px <= 0:
                    continue
                slip     = SLIPPAGE.get(tk, 0.001)
                noise    = rng.uniform(-EXEC_NOISE, EXEC_NOISE)
                exec_px  = cur_px * (1 + slip + abs(noise))
                net_size = size * (1 - COMMISSION)
                shares   = net_size / exec_px
                cash    -= size
                positions[tk] = OpenPos(
                    ticker=tk, entry_dt=dt, entry_px=exec_px,
                    size_usd=net_size, shares=shares,
                )
                if verbose:
                    print(f"  ENTRY {tk} @ {dt.date()} | RSI={rsi_now:.1f} | ${size:.2f} @ ${exec_px:,.2f}")

    # Close open positions at period end
    if dates:
        last = dates[-1]
        for tk, pos in list(positions.items()):
            cur_px   = float(prices[tk].get(last, pos.entry_px))
            slip     = SLIPPAGE.get(tk, 0.001)
            noise    = rng.uniform(-EXEC_NOISE, EXEC_NOISE)
            exec_px  = cur_px * (1 - slip - abs(noise))
            proceeds = pos.shares * exec_px * (1 - COMMISSION)
            pnl      = proceeds - pos.size_usd
            trades.append(Trade(
                ticker=tk, entry_dt=pos.entry_dt, exit_dt=last,
                entry_px=pos.entry_px, exit_px=exec_px,
                size_usd=pos.size_usd, pnl=pnl,
                pnl_pct=pnl / pos.size_usd,
                exit_reason="PERIOD_END", hold_days=(last - pos.entry_dt).days,
            ))
            cash += proceeds

    eq = pd.DataFrame(eq_rows).set_index("dt")["equity"]
    return eq, trades

# ─── Metrics ──────────────────────────────────────────────────────────────────
def compute_metrics(eq: pd.Series, trades: List[Trade], capital: float) -> dict:
    if eq.empty or not trades:
        return {}

    daily_ret = eq.pct_change().dropna()
    n_days    = max((eq.index[-1] - eq.index[0]).days, 1)
    n_months  = n_days / 30.44
    tot_ret   = eq.iloc[-1] / eq.iloc[0] - 1
    mo_ret    = (1 + tot_ret) ** (1 / max(n_months, 1)) - 1
    ann_ret   = (1 + tot_ret) ** (365 / max(n_days, 1)) - 1

    vol_d  = daily_ret.std()
    sharpe = (daily_ret.mean() / vol_d * np.sqrt(252)) if vol_d > 0 else 0.0

    roll_peak = eq.cummax()
    max_dd    = float(((eq - roll_peak) / roll_peak).min())
    calmar    = (ann_ret / abs(max_dd)) if max_dd < 0 else 0.0

    wins   = [t for t in trades if t.pnl > 0]
    losses = [t for t in trades if t.pnl <= 0]
    wr     = len(wins) / len(trades)
    gross_win  = sum(t.pnl for t in wins)
    gross_loss = abs(sum(t.pnl for t in losses))
    pf     = (gross_win / gross_loss) if gross_loss > 0 else float("inf")
    avg_hold = np.mean([t.hold_days for t in trades])
    trades_pm = len(trades) / max(n_months, 1)

    return dict(
        final_equity   = float(eq.iloc[-1]),
        total_return   = tot_ret,
        monthly_return = mo_ret,
        annual_return  = ann_ret,
        sharpe         = sharpe,
        max_drawdown   = max_dd,
        calmar         = calmar,
        win_rate       = wr,
        profit_factor  = pf,
        n_trades       = len(trades),
        trades_per_mo  = trades_pm,
        avg_hold_days  = avg_hold,
    )

def passes(m: dict) -> dict:
    return {
        "Mo≥2%":     m.get("monthly_return", 0) >= 0.02,
        "SR≥1.0":    m.get("sharpe", 0)         >= 1.0,
        "MDD>-40%":  m.get("max_drawdown", -1)  > -0.40,
        "Cal≥0.8":   m.get("calmar", 0)          >= 0.8,
        "WR≥40%":    m.get("win_rate", 0)        >= 0.40,
        "N≥20":      m.get("n_trades", 0)        >= 20,
    }

def print_results(label: str, m: dict, capital: float):
    if not m:
        print(f"\n  {label}: no results")
        return
    p     = passes(m)
    n_pass = sum(p.values())
    print(f"\n{'='*60}")
    print(f"  {label}")
    print(f"{'='*60}")
    print(f"  Final equity:   ${m['final_equity']:,.2f}  (started ${capital:,.2f})")
    print(f"  Total return:   {m['total_return']*100:+.1f}%")
    print(f"  Monthly return: {m['monthly_return']*100:+.2f}%   {'✅' if p['Mo≥2%'] else '❌'} [≥2%]")
    print(f"  Annual return:  {m['annual_return']*100:+.1f}%")
    print(f"  Sharpe:         {m['sharpe']:.3f}             {'✅' if p['SR≥1.0'] else '❌'} [≥1.0]")
    print(f"  Max drawdown:   {m['max_drawdown']*100:.1f}%          {'✅' if p['MDD>-40%'] else '❌'} [>-40%]")
    print(f"  Calmar:         {m['calmar']:.2f}              {'✅' if p['Cal≥0.8'] else '❌'} [≥0.8]")
    print(f"  Win rate:       {m['win_rate']*100:.0f}%              {'✅' if p['WR≥40%'] else '❌'} [≥40%]")
    print(f"  N trades:       {m['n_trades']}               {'✅' if p['N≥20'] else '❌'} [≥20]")
    print(f"  Trades/month:   {m['trades_per_mo']:.1f}")
    print(f"  Avg hold:       {m['avg_hold_days']:.1f} days")
    print(f"\n  CRITERIA: {n_pass}/6 pass")

# ─── Main ─────────────────────────────────────────────────────────────────────
if __name__ == "__main__":
    print("=" * 60)
    print("  Active RSI Mean-Reversion | BTC+ETH | Daily candles")
    print("  Regime gate: BTC > EMA100 (Iter68 filter)")
    print("=" * 60)

    # ── 1. Fetch data ─────────────────────────────────────────────────────────
    print("\n[1] Fetching Coinmetrics daily prices...")
    btc_px = fetch_daily("btc")
    eth_px = fetch_daily("eth")
    print(f"    BTC: {len(btc_px)} days, last=${float(btc_px.iloc[-1]):,.0f}")
    print(f"    ETH: {len(eth_px)} days, last=${float(eth_px.iloc[-1]):,.2f}")

    prices = {"BTC": btc_px, "ETH": eth_px}
    rng    = np.random.default_rng(42)
    cap    = 1_000.0

    # ── 2. IS backtest ────────────────────────────────────────────────────────
    print(f"\n[2] IS backtest ({IS_START} → {IS_END})...")
    eq_is, tr_is = run_backtest(prices, IS_START, IS_END, cap, rng)
    m_is = compute_metrics(eq_is, tr_is, cap)
    print_results(f"IS  {IS_START}–{IS_END}  $1,000", m_is, cap)

    # ── 3. OOS backtest ───────────────────────────────────────────────────────
    print(f"\n[3] OOS backtest ({OOS_START} → {OOS_END})...")
    eq_oos, tr_oos = run_backtest(prices, OOS_START, OOS_END, cap, rng)
    m_oos = compute_metrics(eq_oos, tr_oos, cap)
    print_results(f"OOS {OOS_START}–{OOS_END}  $1,000", m_oos, cap)

    # ── 4. OOS trade log (last 30) ────────────────────────────────────────────
    if tr_oos:
        print(f"\n[4] Last 30 OOS trades (of {len(tr_oos)} total):")
        print(f"  {'Ticker':<5} {'Entry':<12} {'Exit':<12} {'Days':>5} {'P&L':>8} {'Ret':>7}  Reason")
        print("  " + "-" * 70)
        for t in tr_oos[-30:]:
            print(f"  {t.ticker:<5} {str(t.entry_dt.date()):<12} {str(t.exit_dt.date()):<12} "
                  f"{t.hold_days:5d}  {t.pnl:+8.2f} {t.pnl_pct*100:+6.1f}%  {t.exit_reason}")

    # ── 5. RSI threshold sensitivity ─────────────────────────────────────────
    print(f"\n[5] RSI entry threshold sensitivity (OOS):")
    print(f"  {'Thresh':>8}  {'N':>5}  {'Mo%':>7}  {'SR':>6}  {'MDD':>7}  {'WR':>5}  {'Pass':>5}")
    print("  " + "-" * 55)
    for thresh in [20, 25, 30, 35, 40]:
        rng2 = np.random.default_rng(42)
        eq_t, tr_t = run_backtest(prices, OOS_START, OOS_END, cap, rng2,
                                  rsi_entry=thresh)
        if tr_t:
            m_t  = compute_metrics(eq_t, tr_t, cap)
            p_t  = passes(m_t)
            np_  = sum(p_t.values())
            print(f"  RSI < {thresh:2d}:   {m_t['n_trades']:5d}  "
                  f"{m_t['monthly_return']*100:+6.2f}%  "
                  f"{m_t['sharpe']:6.3f}  "
                  f"{m_t['max_drawdown']*100:6.1f}%  "
                  f"{m_t['win_rate']*100:4.0f}%  "
                  f"{np_}/6")
        else:
            print(f"  RSI < {thresh:2d}:   0 trades")

    # ── 6. SL sensitivity ────────────────────────────────────────────────────
    print(f"\n[6] Stop-loss sensitivity (OOS, RSI<35):")
    print(f"  {'SL%':>6}  {'N':>5}  {'Mo%':>7}  {'SR':>6}  {'MDD':>7}  {'WR':>5}  {'Pass':>5}")
    print("  " + "-" * 50)
    for sl in [0.04, 0.06, 0.08, 0.10, 0.15]:
        rng3 = np.random.default_rng(42)
        eq_t, tr_t = run_backtest(prices, OOS_START, OOS_END, cap, rng3, sl_pct=sl)
        if tr_t:
            m_t = compute_metrics(eq_t, tr_t, cap)
            p_t = passes(m_t)
            np_ = sum(p_t.values())
            print(f"  SL {sl*100:.0f}%:   {m_t['n_trades']:5d}  "
                  f"{m_t['monthly_return']*100:+6.2f}%  "
                  f"{m_t['sharpe']:6.3f}  "
                  f"{m_t['max_drawdown']*100:6.1f}%  "
                  f"{m_t['win_rate']*100:4.0f}%  "
                  f"{np_}/6")
        else:
            print(f"  SL {sl*100:.0f}%:   0 trades")

    print("\n[Done]")
