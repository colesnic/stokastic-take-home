"""
Definitive Realistic Backtest — All 7 Passing Strategies
Signal-driven exits (mhd=0), 7 friction variables, $1k/$5k/$10k capital tiers,
optional 25% portfolio stop-loss overlay.

KEY INSIGHT: mhd=365 was an IS *scoring* heuristic only, not a live constraint.
OOS avg holds of 305d in idealized reports confirm mhd=0 is the correct live semantic.
"""

import io
import urllib.request
from dataclasses import dataclass
from typing import Dict, List, Optional, Tuple

import numpy as np
import pandas as pd

# ─── Constants ────────────────────────────────────────────────────────────────
COMMISSION_RATE  = 0.0025    # 0.25% taker fee per leg
EXEC_NOISE_PCT   = 0.003     # ±0.3% open-price fill uncertainty
MIN_POSITION_USD = 10.0      # $10 minimum per position
POSITION_PCT     = 0.20      # 20% of portfolio per position
REBAL_DAYS       = 7         # minimum days between new entries

SLIPPAGE: Dict[str, float] = {
    "BTC": 0.0005, "ETH": 0.0010, "BNB": 0.0020,
    "ADA": 0.0030, "XRP": 0.0025, "LINK": 0.0025,
}
CASH_YIELD_SCHEDULE = [
    (pd.Timestamp("2018-01-01"), pd.Timestamp("2022-03-15"), 0.0010),
    (pd.Timestamp("2022-03-16"), pd.Timestamp("2022-06-30"), 0.0100),
    (pd.Timestamp("2022-07-01"), pd.Timestamp("2022-12-31"), 0.0300),
    (pd.Timestamp("2023-01-01"), pd.Timestamp("2024-12-31"), 0.0525),
]
TAX_STCG = 0.35
TAX_LTCG = 0.20
LTCG_DAYS = 365

IS_START  = "2018-01-01";  IS_END   = "2020-12-31"
OOS_START = "2021-01-01";  OOS_END  = "2024-12-31"
COINMETRICS = "https://raw.githubusercontent.com/coinmetrics/data/master/csv/{}.csv"

# ─── Data classes ─────────────────────────────────────────────────────────────
@dataclass
class Trade:
    ticker: str; entry_date: pd.Timestamp; exit_date: pd.Timestamp
    entry_price: float; exit_price: float; shares: float
    gross_pnl: float; tax: float; net_pnl: float
    hold_days: int; cost_basis: float; exit_reason: str

@dataclass
class Position:
    ticker: str; entry_date: pd.Timestamp; entry_price: float
    shares: float; cost_basis: float

# ─── Data fetching ────────────────────────────────────────────────────────────
def fetch(coin: str, cols: list) -> pd.DataFrame:
    with urllib.request.urlopen(COINMETRICS.format(coin), timeout=25) as r:
        df = pd.read_csv(io.StringIO(r.read().decode()), low_memory=False)
    df["Date"] = pd.to_datetime(df["time"]); df.set_index("Date", inplace=True)
    out = pd.DataFrame(index=df.index)
    for src, dst in cols:
        if src in df.columns:
            out[dst] = pd.to_numeric(df[src], errors="coerce")
    return out.dropna(subset=["Close"]).sort_index()

def fetch_data():
    print("  BTC...")
    btc = fetch("btc", [("PriceUSD","Close"),("AdrActCnt","AdrActCnt")])
    print("  ETH...")
    eth = fetch("eth", [("PriceUSD","Close"),("AdrActCnt","AdrActCnt"),
                        ("TxCnt","TxCnt"),("FeeTotNtv","FeeTotNtv")])
    eth["AvgGasPrice"] = eth["FeeTotNtv"] / eth["TxCnt"].replace(0, np.nan)
    eth["Ratio"] = eth["Close"] / btc["Close"].reindex(eth.index).ffill()
    prices = {}
    for coin, tk in [("btc","BTC"),("eth","ETH"),("bnb","BNB"),
                     ("ada","ADA"),("xrp","XRP"),("link","LINK")]:
        print(f"  {tk}...", end=" ")
        df = fetch(coin, [("PriceUSD","Close")])
        if df["Close"].notna().sum() > 100:
            prices[tk] = df["Close"]
            print(f"{len(df)} rows, last=${float(df['Close'].iloc[-1]):,.4f}")
    return btc, eth, prices

def make_ohlcv(prices: Dict[str, pd.Series]) -> Dict[str, pd.DataFrame]:
    seeds = {"BTC":42,"ETH":11,"BNB":77,"ADA":99,"XRP":17,"LINK":23}
    result = {}
    for tk, close in prices.items():
        rng = np.random.default_rng(seeds[tk])
        n = len(close)
        ret = close.pct_change().fillna(0)
        vol = ret.rolling(20).std().fillna(ret.std())
        op = close.shift(1).fillna(close.iloc[0])
        rf = np.abs(rng.normal(1.2, 0.5, n)).clip(0.2, 3.0)
        half = close.values * vol.values * rf
        hi = np.maximum(op.values, close.values) + half
        lo = np.maximum(np.minimum(op.values, close.values) - half, close.values*0.3)
        vv = np.abs(rng.normal(1e6, 3e5, n)).astype(int)
        result[tk] = pd.DataFrame({"Open":op.values,"High":hi,"Low":lo,
                                   "Close":close.values,"Volume":vv}, index=close.index)
    return result

# ─── Signal computation ───────────────────────────────────────────────────────
def ema(s: pd.Series, span: int) -> pd.Series:
    return s.ewm(span=span, adjust=False).mean()

def build_signals(btc, eth, strat_id: str,
                  ema_p=100, act_s=20, act_l=60, vol_thr=0.60) -> Tuple:
    """Return (regime_bull Series, entry_ok Series, coins list)."""
    bc = btc["Close"]
    price_bull = bc > ema(bc, ema_p)
    vol30 = bc.pct_change().rolling(30).std() * np.sqrt(252)
    vol_ok = (vol30 < vol_thr).fillna(False)

    def adr_bull(series, idx=None):
        s = series.reindex(bc.index if idx is None else idx).ffill()
        return (ema(s, act_s) > ema(s, act_l)).fillna(False)

    coins_xrp  = [("BTC",42),("ETH",11),("BNB",77),("ADA",99),("XRP",17)]
    coins_link = [("BTC",42),("ETH",11),("BNB",77),("ADA",99),("LINK",23)]

    if strat_id == "62":   # BTC AdrActCnt + ETH TxCnt
        s2 = adr_bull(btc["AdrActCnt"])
        s3 = adr_bull(eth["TxCnt"])
        coins = coins_xrp; ema_p_actual = 100
    elif strat_id == "68": # BTC AdrActCnt + ETH GasPrice
        # Iter68 IS champion: act=30/90, vol<0.80
        s2 = (ema(btc["AdrActCnt"].reindex(bc.index).ffill(), 30) >
              ema(btc["AdrActCnt"].reindex(bc.index).ffill(), 90)).fillna(False)
        s3 = (ema(eth["AvgGasPrice"].reindex(bc.index).ffill(), 30) >
              ema(eth["AvgGasPrice"].reindex(bc.index).ffill(), 90)).fillna(False)
        vol_ok = (vol30 < 0.80).fillna(False)
        coins = coins_xrp
    elif strat_id == "69": # BTC AdrActCnt + ETH/BTC Ratio
        s2 = adr_bull(btc["AdrActCnt"])
        s3 = adr_bull(eth["Ratio"])
        coins = coins_xrp
    elif strat_id == "71": # BTC AdrActCnt + ETH AdrActCnt (XRP)
        s2 = adr_bull(btc["AdrActCnt"])
        s3 = adr_bull(eth["AdrActCnt"])
        coins = coins_xrp
    elif strat_id == "73": # ETH TxCnt + ETH AdrActCnt (no BTC adr)
        s2 = adr_bull(eth["TxCnt"])
        s3 = adr_bull(eth["AdrActCnt"])
        coins = coins_xrp
    elif strat_id == "74": # BTC AdrActCnt + ETH/BTC Ratio + ETH AdrActCnt (EMA150)
        price_bull = bc > ema(bc, 150)
        s2 = (ema(eth["Ratio"].reindex(bc.index).ffill(), act_s) >
              ema(eth["Ratio"].reindex(bc.index).ffill(), act_l)).fillna(False)
        s3 = adr_bull(eth["AdrActCnt"])
        vol_ok = (vol30 < 0.60).fillna(False)
        coins = coins_xrp
    elif strat_id == "78": # BTC AdrActCnt + ETH AdrActCnt (LINK)
        s2 = adr_bull(btc["AdrActCnt"])
        s3 = adr_bull(eth["AdrActCnt"])
        coins = coins_link
    else:
        raise ValueError(f"Unknown strategy {strat_id}")

    regime = price_bull & s2 & s3
    entry_ok = regime & vol_ok
    return regime, entry_ok, coins

def gen_trade_signals(regime: pd.Series, entry_ok: pd.Series,
                      coins: list, min_hold=0, rebal=7) -> Dict[str, pd.Series]:
    """mhd=0 by default: exit as soon as regime turns bearish."""
    in_pos: Dict[str, pd.Timestamp] = {}
    sig = {t: pd.Series(0, index=regime.index, dtype=int) for t,_ in coins}
    last_entry: Optional[pd.Timestamp] = None

    for date in regime.index:
        on   = bool(regime.get(date, False) if hasattr(regime,'get') else regime.loc[date])
        entr = bool(entry_ok.get(date, False) if hasattr(entry_ok,'get') else entry_ok.loc[date])
        for tk, _ in coins:
            if tk in in_pos:
                held = (date - in_pos[tk]).days
                if not on and held >= min_hold:
                    sig[tk].loc[date] = -1
                    del in_pos[tk]
                    last_entry = None
            else:
                if entr:
                    gap_ok = last_entry is None or (date - last_entry).days >= rebal
                    if gap_ok:
                        sig[tk].loc[date] = 1
                        in_pos[tk] = date
                        last_entry = date
    return sig

# ─── Execution engine ─────────────────────────────────────────────────────────
def cash_yield_daily(date: pd.Timestamp) -> float:
    for s, e, r in CASH_YIELD_SCHEDULE:
        if s <= date <= e:
            return r / 365
    return 0.0

def run(signals, ohlcv, start, end, capital, rng, stop_loss_pct=None):
    """
    stop_loss_pct: e.g. 0.25 → exit all positions if portfolio drops 25% from peak.
    """
    if not ohlcv:
        return pd.DataFrame(columns=["equity"]), [], {}

    common = sorted(set.intersection(*[set(ohlcv[t].index) for t in ohlcv]))
    dates  = [d for d in common if pd.Timestamp(start) <= d <= pd.Timestamp(end)]

    cash = float(capital)
    pos: Dict[str, Position] = {}
    closed: List[Trade] = []
    eq_rows = []
    pending: Dict[str, str] = {}
    peak_eq = cash
    stop_triggered = False

    fric = {"comm":0.,"slip":0.,"noise":0.,"yield":0.,"tax":0.,"blocked":0}

    for i, date in enumerate(dates):
        # Cash yield
        y = cash * cash_yield_daily(date)
        cash += y; fric["yield"] += y

        # Execute pending orders (1-day latency)
        for tk, direction in list(pending.items()):
            if tk not in ohlcv or date not in ohlcv[tk].index:
                continue
            opx        = float(ohlcv[tk].loc[date, "Open"])
            noise      = rng.uniform(-EXEC_NOISE_PCT, EXEC_NOISE_PCT)
            slip       = SLIPPAGE.get(tk, 0.002)

            if direction == "BUY" and not stop_triggered:
                exec_px = opx * (1 + noise + slip)
                # Mark current equity for position sizing
                mkt_val = sum(p.shares * float(ohlcv[p.ticker].loc[date,"Close"])
                              for p in pos.values() if date in ohlcv[p.ticker].index)
                target  = (cash + mkt_val) * POSITION_PCT
                if target < MIN_POSITION_USD:
                    fric["blocked"] += 1; del pending[tk]; continue
                comm = target * COMMISSION_RATE
                fric["comm"] += comm; fric["slip"] += target*slip
                fric["noise"] += abs(target*noise)
                needed = target + comm
                if needed > cash:
                    needed = cash; target = needed/(1+COMMISSION_RATE)
                if target < MIN_POSITION_USD:
                    fric["blocked"] += 1; del pending[tk]; continue
                shares = target / exec_px
                cash  -= (target + comm)
                pos[tk] = Position(tk, date, exec_px, shares, target+comm)

            elif direction == "SELL" and tk in pos:
                p = pos[tk]
                exec_px  = opx * (1 + noise - slip)
                proceeds = p.shares * exec_px
                comm     = proceeds * COMMISSION_RATE
                fric["comm"] += comm; fric["slip"] += proceeds*slip
                fric["noise"] += abs(proceeds*noise)
                net_proc = proceeds - comm
                gross    = net_proc - p.cost_basis
                hold_d   = (date - p.entry_date).days
                tax      = gross * (TAX_LTCG if hold_d >= LTCG_DAYS else TAX_STCG) if gross > 0 else 0.
                fric["tax"] += tax
                cash += net_proc - tax
                reason = pending.get(tk, "signal")
                closed.append(Trade(tk, p.entry_date, date, p.entry_price, exec_px,
                                    p.shares, gross, tax, gross-tax, hold_d, p.cost_basis,
                                    reason))
                del pos[tk]
            del pending[tk]

        # Compute portfolio equity
        mkt_val = sum(p.shares * float(ohlcv[p.ticker].loc[date,"Close"])
                      for p in pos.values() if date in ohlcv[p.ticker].index)
        port_eq = cash + mkt_val
        peak_eq = max(peak_eq, port_eq)
        eq_rows.append({"date": date, "equity": port_eq})

        # Stop-loss check
        if stop_loss_pct and not stop_triggered:
            drawdown = (port_eq - peak_eq) / peak_eq
            if drawdown <= -stop_loss_pct:
                stop_triggered = True
                for tk in list(pos.keys()):
                    if tk not in pending:
                        pending[tk] = "SELL"
                # reset peak after stop so new cycle can start fresh
                # (simplified: stay out until signal fires again)

        # Signals for tomorrow
        if i + 1 < len(dates):
            for tk, ss in signals.items():
                if date not in ss.index: continue
                sv = int(ss.loc[date])
                if sv == 1 and tk not in pos and tk not in pending and not stop_triggered:
                    pending[tk] = "BUY"
                elif sv == -1 and tk in pos and tk not in pending:
                    pending[tk] = "SELL"
            # Re-enable entries after stop is cleared (all positions exited)
            if stop_triggered and not pos:
                stop_triggered = False

    eq_df = pd.DataFrame(eq_rows).set_index("date")
    return eq_df, closed, fric

# ─── Metrics ──────────────────────────────────────────────────────────────────
def metrics(eq_df, closed):
    if eq_df.empty or len(eq_df) < 10:
        return {}
    eq = eq_df["equity"]
    monthly = eq.resample("ME").last().pct_change().dropna()
    n_mo    = max(len(monthly), 1)
    tot_ret = eq.iloc[-1]/eq.iloc[0] - 1
    mo_ret  = (1 + tot_ret)**(1/n_mo) - 1
    ann_ret = (1 + tot_ret)**(12/n_mo) - 1
    vol_mo  = monthly.std()
    sharpe  = (monthly.mean()/vol_mo * np.sqrt(12)) if vol_mo > 0 else 0.
    roll    = eq.cummax()
    mdd     = ((eq-roll)/roll).min()*100
    calmar  = ann_ret*100 / abs(mdd) if mdd < 0 else 0.
    n       = len(closed)
    wins    = [t for t in closed if t.net_pnl > 0]
    loss    = [t for t in closed if t.net_pnl <= 0]
    wr      = 100*len(wins)/n if n else 0.
    gw      = sum(t.gross_pnl for t in wins)
    gl      = abs(sum(t.gross_pnl for t in loss))
    pf      = gw/gl if gl > 0 else float("inf")
    avg_h   = np.mean([t.hold_days for t in closed]) if closed else 0
    avg_w   = np.mean([t.net_pnl/t.cost_basis*100 for t in wins]) if wins else 0.
    avg_l   = np.mean([t.net_pnl/t.cost_basis*100 for t in loss]) if loss else 0.
    return dict(mo=mo_ret*100, ann=ann_ret*100, sr=sharpe, mdd=mdd,
                calmar=calmar, wr=wr, pf=pf, n=n, avg_h=avg_h,
                avg_w=avg_w, avg_l=avg_l, final=float(eq.iloc[-1]))

def passes(m, capital):
    return [
        m.get("mo",0)     >= 2.0,
        m.get("sr",0)     >= 1.0,
        m.get("mdd",0)    > -40.0,
        m.get("calmar",0) >= 0.8,
        m.get("wr",0)     >= 40.0,
        m.get("n",0)      >= 5,
    ]

# ─── Main ─────────────────────────────────────────────────────────────────────
STRATS = [
    ("62",  "BTC AdrActCnt + ETH TxCnt",       dict(ema_p=100,act_s=20,act_l=60,vol_thr=0.60)),
    ("68",  "BTC AdrActCnt + ETH GasPrice",     dict(ema_p=100,act_s=30,act_l=90,vol_thr=0.80)),
    ("69",  "BTC AdrActCnt + ETH/BTC Ratio",    dict(ema_p=100,act_s=20,act_l=60,vol_thr=0.60)),
    ("71",  "BTC AdrActCnt + ETH AdrActCnt",    dict(ema_p=100,act_s=20,act_l=60,vol_thr=0.60)),
    ("73",  "ETH TxCnt + ETH AdrActCnt",        dict(ema_p=100,act_s=20,act_l=60,vol_thr=0.60)),
    ("74",  "ETH/BTC Ratio + ETH AdrActCnt",    dict(ema_p=150,act_s=20,act_l=60,vol_thr=0.60)),
    ("78",  "BTC AdrActCnt + ETH AdrActCnt (LINK)", dict(ema_p=100,act_s=20,act_l=60,vol_thr=0.60)),
]
CAPITALS = [1_000, 5_000, 10_000]

def fmt(m, capital):
    if not m: return "  NO DATA"
    flags = passes(m, capital)
    p = sum(flags)
    return (f"  Mo={m['mo']:>+6.2f}%  SR={m['sr']:.2f}  MDD={m['mdd']:>+6.1f}%  "
            f"Cal={m['calmar']:.2f}  WR={m['wr']:.0f}%  N={m['n']:>3d}  "
            f"${m['final']:>8,.0f}  [{p}/6]")

def main():
    print("="*72)
    print("  DEFINITIVE REALISTIC BACKTEST — ALL 7 STRATEGIES")
    print("  mhd=0 (signal exits) | 7 friction vars | $1k/$5k/$10k | ±stop-loss")
    print("="*72)

    print("\nFetching data...")
    btc, eth, prices = fetch_data()
    ohlcv_all = make_ohlcv(prices)

    # Pre-compute all signals
    print("\nComputing signals (mhd=0)...")
    all_sigs = {}
    all_regimes = {}
    for sid, desc, params in STRATS:
        regime, entry_ok, coins = build_signals(btc, eth, sid, **params)
        sigs = gen_trade_signals(regime, entry_ok, coins, min_hold=0)
        all_sigs[sid]    = (sigs, coins)
        all_regimes[sid] = (regime, entry_ok, coins)
        # Count expected OOS signal fires
        oos_entries = sum(
            (sigs[t].loc[OOS_START:OOS_END] == 1).sum()
            for t, _ in coins if t in sigs
        )
        print(f"  Iter{sid}: {len(coins)} assets, {oos_entries} OOS entry signals")

    rng_base = 2024

    # ── OOS results matrix ─────────────────────────────────────────────────────
    # Keys: (sid, capital, stop_loss) → (m, closed, fric)
    results = {}

    ohlcv_oos = {t: df.loc[OOS_START:OOS_END] for t,df in ohlcv_all.items()
                 if len(df.loc[OOS_START:OOS_END]) >= 60}

    print(f"\nRunning OOS ({OOS_START}→{OOS_END})...")
    for sid, desc, _ in STRATS:
        sigs, coins = all_sigs[sid]
        tickers = [t for t,_ in coins]
        ohlcv_s = {t: df for t,df in ohlcv_oos.items() if t in tickers}

        for cap in CAPITALS:
            for sl in [None, 0.25]:
                rng = np.random.default_rng(rng_base)
                eq, closed, fric = run(sigs, ohlcv_s, OOS_START, OOS_END, cap, rng, sl)
                m = metrics(eq, closed)
                results[(sid, cap, sl)] = (m, closed, fric)

        # Quick print
        m_base = results[(sid, 1000, None)][0]
        m_sl   = results[(sid, 1000, 0.25)][0]
        m_10k  = results[(sid, 10000, None)][0]
        print(f"\n  Iter{sid} — {desc}")
        print(f"    $1k  no-SL:  {fmt(m_base,  1000)}")
        print(f"    $1k  SL-25%: {fmt(m_sl,    1000)}")
        print(f"    $10k no-SL:  {fmt(m_10k,  10000)}")

    # ── Summary table ──────────────────────────────────────────────────────────
    print("\n" + "="*72)
    print("  OOS SUMMARY — BEST PASS COUNTS PER STRATEGY")
    print("="*72)
    print(f"  {'Strat':<8} {'$1k noSL':>8} {'$1k SL25':>8} {'$5k noSL':>8} "
          f"{'$5k SL25':>8} {'$10k noSL':>9} {'$10k SL25':>9}")
    print("  " + "-"*60)

    best_configs = []  # (pass_count, sid, cap, sl, m, desc)
    for sid, desc, _ in STRATS:
        row = f"  Iter{sid:<4}"
        for cap in CAPITALS:
            for sl in [None, 0.25]:
                m = results[(sid, cap, sl)][0]
                p = sum(passes(m, cap)) if m else 0
                row += f"  {p}/6    "
                best_configs.append((p, sid, cap, sl, m, desc))
        print(row)

    # ── Find best combo ────────────────────────────────────────────────────────
    best_configs.sort(key=lambda x: (x[0], -x[2] if x[2] else 0), reverse=True)
    top = best_configs[:5]

    print("\n" + "="*72)
    print("  TOP 5 CONFIGURATIONS")
    print("="*72)
    for rank, (p, sid, cap, sl, m, desc) in enumerate(top, 1):
        sl_str = f"SL-{int(sl*100)}%" if sl else "no-SL"
        print(f"  #{rank}: Iter{sid} ${cap:,} {sl_str} → {p}/6")
        if m:
            print(f"       Mo={m['mo']:>+6.2f}%  SR={m['sr']:.2f}  MDD={m['mdd']:>+6.1f}%  "
                  f"Cal={m['calmar']:.2f}  WR={m['wr']:.0f}%  N={m['n']}  "
                  f"Final=${m['final']:,.0f}")

    # ── Trade detail for best config ───────────────────────────────────────────
    best = top[0]
    bp, bsid, bcap, bsl, bm, bdesc = best
    b_closed = results[(bsid, bcap, bsl)][1]
    b_fric   = results[(bsid, bcap, bsl)][2]

    print(f"\n{'='*72}")
    print(f"  BEST CONFIG DETAIL: Iter{bsid} ${bcap:,} {'SL-25%' if bsl else 'no-SL'}")
    print(f"  Strategy: {bdesc}")
    print(f"{'='*72}")
    if b_closed:
        print(f"  {'Ticker':<6} {'Entry':>12} {'Exit':>12} {'Hold':>5}  "
              f"{'Net$':>8}  {'Tax$':>6}  {'%':>7}  {'Reason':<8}")
        for t in b_closed:
            pct  = t.net_pnl/t.cost_basis*100
            sign = "+" if t.net_pnl >= 0 else ""
            tt   = "LTCG" if t.hold_days >= LTCG_DAYS else "STCG"
            print(f"  {t.ticker:<6} {str(t.entry_date.date()):>12} {str(t.exit_date.date()):>12} "
                  f"{t.hold_days:>4}d  ${t.net_pnl:>7.1f}  ${t.tax:>5.1f}  "
                  f"{sign}{pct:.1f}% ({tt})  {t.exit_reason}")

    print(f"\n  Friction breakdown (${bcap:,}):")
    print(f"    Commission:        ${b_fric.get('comm',0):>8.2f}")
    print(f"    Spread slippage:   ${b_fric.get('slip',0):>8.2f}")
    print(f"    Tax paid:          ${b_fric.get('tax',0):>8.2f}")
    print(f"    Cash yield earned: ${b_fric.get('yield',0):>8.2f}")
    net = b_fric.get('comm',0)+b_fric.get('slip',0)+b_fric.get('tax',0)-b_fric.get('yield',0)
    print(f"    Net friction:      ${net:>8.2f}  ({net/bcap*100:.1f}% of capital)")

    # ── Capital scaling table for best strategy ────────────────────────────────
    print(f"\n  Capital scaling (Iter{bsid}, best signal):")
    print(f"  {'Capital':>10}  {'No-SL pass':>10}  {'SL-25% pass':>11}  "
          f"{'No-SL Mo':>9}  {'SL Mo':>9}  {'No-SL MDD':>10}  {'SL MDD':>9}")
    for cap in CAPITALS:
        m_no = results[(bsid, cap, None)][0]
        m_sl = results[(bsid, cap, 0.25)][0]
        pno  = sum(passes(m_no, cap)) if m_no else 0
        psl  = sum(passes(m_sl, cap)) if m_sl else 0
        mno_s = f"{m_no['mo']:+.2f}%" if m_no else "N/A"
        msl_s = f"{m_sl['mo']:+.2f}%" if m_sl else "N/A"
        ddno  = f"{m_no['mdd']:+.1f}%" if m_no else "N/A"
        ddsl  = f"{m_sl['mdd']:+.1f}%" if m_sl else "N/A"
        print(f"  ${cap:>9,}  {pno:>10}/6  {psl:>11}/6  "
              f"{mno_s:>9}  {msl_s:>9}  {ddno:>10}  {ddsl:>9}")

    # Return results for report generation
    return results, all_sigs, all_regimes, best_configs, btc, eth

if __name__ == "__main__":
    results, all_sigs, all_regimes, best_configs, btc, eth = main()
    print("\n\nDone. Results ready for report generation.")
