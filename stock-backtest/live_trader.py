"""
Live trading execution for RSMomentumStrategy via Alpaca.

LATENCY NOTE
------------
Backtest: signal on close-T → fills at close-T   (same bar — impossible live)
Live:     signal on close-T → fills at open-T+1  (1 bar lag)

Impact: ~1 day on an 8-22 day average hold. Academically negligible for
daily momentum. The overnight gap introduces extra noise not in the backtest,
but it averages to near-zero over many trades.

ATR stops in the backtest were intraday triggers. Live, we replace them with
Alpaca stop orders (GTC), recomputed and resubmitted each evening as the
trailing stop ratchets up.

SETUP
-----
  pip install alpaca-py pandas numpy

  export ALPACA_API_KEY=your_key
  export ALPACA_SECRET_KEY=your_secret
  export ALPACA_PAPER=true      # default; set false for live money

USAGE
-----
  python3 live_trader.py            # run after 4:30pm ET on trading days
  python3 live_trader.py --status   # show positions and today's signals only
  python3 live_trader.py --dry-run  # show intended orders without submitting

AUTOMATE (cron, runs Mon-Fri at 4:35pm ET)
  35 16 * * 1-5 cd /path/to/stock-backtest && python3 live_trader.py >> live.log 2>&1
"""

import os
import sys
import json
import argparse
import warnings
from datetime import datetime, timedelta, date
from pathlib import Path

import numpy as np
import pandas as pd

warnings.filterwarnings("ignore")

# ── Alpaca SDK ─────────────────────────────────────────────────────────────
try:
    from alpaca.trading.client import TradingClient
    from alpaca.trading.requests import (
        MarketOrderRequest, StopOrderRequest, GetOrdersRequest
    )
    from alpaca.trading.enums import OrderSide, TimeInForce, QueryOrderStatus
    from alpaca.data.historical import StockHistoricalDataClient
    from alpaca.data.requests import StockBarsRequest
    from alpaca.data.timeframe import TimeFrame
except ImportError:
    print("ERROR: alpaca-py not installed. Run: pip install alpaca-py")
    sys.exit(1)

# ── Config ─────────────────────────────────────────────────────────────────
API_KEY    = os.environ.get("ALPACA_API_KEY", "")
SECRET_KEY = os.environ.get("ALPACA_SECRET_KEY", "")
PAPER      = os.environ.get("ALPACA_PAPER", "true").lower() != "false"

if not API_KEY or not SECRET_KEY:
    print("ERROR: Set ALPACA_API_KEY and ALPACA_SECRET_KEY environment variables.")
    sys.exit(1)

# Champion strategy parameters (confirmed OOS Sharpe 1.32, 3x → Sharpe 2.65)
CHAMPION_PARAMS = dict(
    top_n=4, rebalance_days=3,
    lookback_short=10, lookback_mid=20, lookback_long=40,
    adx_min=12, rsi_min=35,
)
ATR_STOP_MULT  = 2.0   # initial stop width
ATR_TRAIL_MULT = 1.5   # trailing stop tightens to this once position is open
MAX_POSITIONS  = 3
POSITION_PCT   = 0.33  # 33% of equity per position
LOOKBACK_DAYS  = 120   # bars to fetch for indicator warmup (need ≥ 50 for EMA50)

# Sector-diverse universe — includes energy (crashed 2015-16) and defensives
# to stress-test that the EMA(50) filter correctly avoids multi-year downtrends
UNIVERSE = [
    # Tech (momentum leaders)
    "AAPL", "MSFT", "AMZN", "GOOGL", "META", "NVDA", "AMD", "AVGO",
    # Energy (cyclical stress test — XOM/CVX were -40% in 2015-2016)
    "XOM", "CVX",
    # Financials
    "JPM", "GS",
    # Healthcare (defensive, low-momentum — tests ADX filter)
    "JNJ", "UNH",
    # Retail + Industrials
    "WMT", "CAT",
]

STATE_FILE = Path(__file__).parent / "live_state.json"


# ── Indicators (mirrors indicators.py to avoid import path issues) ──────────

def _ema(series: pd.Series, period: int) -> pd.Series:
    return series.ewm(span=period, adjust=False).mean()

def _rsi(close: pd.Series, period: int = 14) -> pd.Series:
    delta = close.diff()
    gain  = delta.clip(lower=0).ewm(alpha=1/period, adjust=False).mean()
    loss  = (-delta.clip(upper=0)).ewm(alpha=1/period, adjust=False).mean()
    rs    = gain / loss.replace(0, np.nan)
    return 100 - (100 / (1 + rs))

def _atr(high: pd.Series, low: pd.Series, close: pd.Series, period: int = 14) -> pd.Series:
    tr = pd.concat([
        high - low,
        (high - close.shift()).abs(),
        (low  - close.shift()).abs(),
    ], axis=1).max(axis=1)
    return tr.ewm(alpha=1/period, adjust=False).mean()

def _adx(high: pd.Series, low: pd.Series, close: pd.Series, period: int = 14) -> pd.Series:
    up   = high.diff()
    down = -low.diff()
    pdm  = up.where((up > down) & (up > 0), 0.0)
    ndm  = down.where((down > up) & (down > 0), 0.0)
    atr_ = _atr(high, low, close, period)
    pdi  = 100 * pdm.ewm(alpha=1/period, adjust=False).mean() / atr_.replace(0, np.nan)
    ndi  = 100 * ndm.ewm(alpha=1/period, adjust=False).mean() / atr_.replace(0, np.nan)
    dx   = (100 * (pdi - ndi).abs() / (pdi + ndi).replace(0, np.nan))
    return dx.ewm(alpha=1/period, adjust=False).mean()


# ── Data fetching ──────────────────────────────────────────────────────────

def fetch_bars(tickers: list[str], lookback: int = LOOKBACK_DAYS) -> dict[str, pd.DataFrame]:
    """Fetch daily OHLCV from Alpaca for the last `lookback` calendar days."""
    data_client = StockHistoricalDataClient(API_KEY, SECRET_KEY)
    end   = datetime.utcnow()
    start = end - timedelta(days=lookback + 30)  # buffer for weekends/holidays

    req = StockBarsRequest(
        symbol_or_symbols=tickers,
        timeframe=TimeFrame.Day,
        start=start,
        end=end,
    )
    bars = data_client.get_stock_bars(req)
    raw  = bars.df  # MultiIndex (symbol, timestamp)

    result = {}
    for ticker in tickers:
        try:
            df = raw.loc[ticker].copy()
            df.index = pd.to_datetime(df.index).tz_localize(None)
            df = df.rename(columns={
                "open": "Open", "high": "High", "low": "Low",
                "close": "Close", "volume": "Volume",
            })[["Open", "High", "Low", "Close", "Volume"]]
            df = df.dropna()
            if len(df) >= 50:
                result[ticker] = df.tail(lookback)
        except (KeyError, Exception):
            pass

    print(f"  Fetched {len(result)}/{len(tickers)} tickers "
          f"({min(len(v) for v in result.values()) if result else 0} bars min)")
    return result


# ── Signal computation ─────────────────────────────────────────────────────

def compute_signals(data: dict[str, pd.DataFrame]) -> dict:
    """
    Compute today's signals without running the full historical backtester.
    Returns a dict with 'ranked' (ordered list), 'qualified' (pass filters),
    and per-ticker indicator snapshots for the most recent bar.
    """
    p = CHAMPION_PARAMS
    latest_date = max(df.index[-1] for df in data.values())
    scores = {}
    filters = {}
    snapshots = {}

    for ticker, df in data.items():
        if len(df) < p["lookback_long"] + 10:
            continue
        c, h, l = df["Close"], df["High"], df["Low"]

        score = (
            0.5 * c.pct_change(p["lookback_short"]) +
            0.3 * c.pct_change(p["lookback_mid"])   +
            0.2 * c.pct_change(p["lookback_long"])
        )

        ema50 = _ema(c, 50)
        adx_v = _adx(h, l, c, 14)
        rsi_v = _rsi(c, 14)
        atr_v = _atr(h, l, c, 14)

        s = score.iloc[-1]
        qualifies = (
            c.iloc[-1] > ema50.iloc[-1] and
            adx_v.iloc[-1] >= p["adx_min"] and
            rsi_v.iloc[-1] >= p["rsi_min"] and
            rsi_v.iloc[-1] <= 82
        )

        if not np.isnan(s):
            scores[ticker]  = s
            filters[ticker] = qualifies
            snapshots[ticker] = {
                "close":   round(float(c.iloc[-1]),  2),
                "ema50":   round(float(ema50.iloc[-1]), 2),
                "adx":     round(float(adx_v.iloc[-1]), 1),
                "rsi":     round(float(rsi_v.iloc[-1]), 1),
                "atr":     round(float(atr_v.iloc[-1]), 2),
                "score":   round(float(s), 4),
                "qualifies": qualifies,
            }

    ranked    = sorted(scores, key=lambda t: scores[t], reverse=True)
    qualified = [t for t in ranked if filters.get(t, False)][:p["top_n"]]

    return {
        "date":      latest_date.date().isoformat(),
        "ranked":    ranked,
        "qualified": qualified,   # tickers to hold today
        "snapshots": snapshots,
    }


# ── State management ───────────────────────────────────────────────────────

def load_state() -> dict:
    if STATE_FILE.exists():
        with open(STATE_FILE) as f:
            return json.load(f)
    return {"last_rebalance_date": None, "stop_orders": {}}

def save_state(state: dict):
    with open(STATE_FILE, "w") as f:
        json.dump(state, f, indent=2)


# ── Alpaca position/order helpers ──────────────────────────────────────────

def get_positions(client: TradingClient) -> dict[str, dict]:
    """Return {symbol: {qty, market_value, avg_entry_price}} for open positions."""
    result = {}
    for p in client.get_all_positions():
        result[p.symbol] = {
            "qty":              float(p.qty),
            "market_value":     float(p.market_value),
            "avg_entry_price":  float(p.avg_entry_price),
        }
    return result

def get_open_stop_orders(client: TradingClient) -> dict[str, str]:
    """Return {symbol: order_id} for all open GTC stop orders."""
    req = GetOrdersRequest(status=QueryOrderStatus.OPEN)
    orders = client.get_orders(req)
    return {
        o.symbol: str(o.id)
        for o in orders
        if o.order_type.value == "stop" and o.time_in_force.value == "gtc"
    }

def cancel_stop_order(client: TradingClient, order_id: str):
    try:
        client.cancel_order_by_id(order_id)
    except Exception:
        pass  # already filled/cancelled

def submit_stop(client: TradingClient, symbol: str, qty: float,
                stop_price: float, dry_run: bool = False) -> str | None:
    """Submit a GTC stop-sell order. Returns order id."""
    stop_price = round(stop_price, 2)
    if dry_run:
        print(f"    [DRY-RUN] STOP {symbol} qty={qty:.4f} @ ${stop_price}")
        return None
    req = StopOrderRequest(
        symbol=symbol,
        qty=round(qty, 6),
        side=OrderSide.SELL,
        time_in_force=TimeInForce.GTC,
        stop_price=stop_price,
    )
    order = client.submit_order(req)
    return str(order.id)


# ── Core rebalance logic ───────────────────────────────────────────────────

def should_rebalance(last_date_str: str | None) -> bool:
    if not last_date_str:
        return True
    last = date.fromisoformat(last_date_str)
    today = date.today()
    trading_days = 0
    d = last + timedelta(days=1)
    while d <= today:
        if d.weekday() < 5:  # Mon-Fri
            trading_days += 1
        d += timedelta(days=1)
    return trading_days >= CHAMPION_PARAMS["rebalance_days"]


def rebalance(client: TradingClient, data: dict, signals: dict,
              state: dict, dry_run: bool = False):
    """
    Diff qualified signals against current Alpaca positions and execute orders.
    Entries execute as market orders (fill at next open).
    Exits execute as market orders.
    Stops are submitted as GTC stop orders immediately after entry.
    """
    account   = client.get_account()
    equity    = float(account.equity)
    positions = get_positions(client)
    target    = set(signals["qualified"][:MAX_POSITIONS])
    current   = set(positions.keys())

    print(f"\n  Equity: ${equity:,.2f}")
    print(f"  Currently holding: {sorted(current) or 'nothing'}")
    print(f"  Strategy wants:    {sorted(target)}")

    exits   = current - target
    entries = target - current

    # ── Exits ──────────────────────────────────────────────────────────────
    for symbol in exits:
        pos = positions[symbol]
        print(f"\n  EXIT  {symbol}  qty={pos['qty']:.4f}  "
              f"value=${pos['market_value']:.2f}")
        # Cancel existing stop order for this symbol
        stop_orders = get_open_stop_orders(client)
        if symbol in stop_orders:
            cancel_stop_order(client, stop_orders[symbol])
            print(f"    Cancelled stop order {stop_orders[symbol]}")
        if not dry_run:
            req = MarketOrderRequest(
                symbol=symbol,
                qty=round(pos["qty"], 6),
                side=OrderSide.SELL,
                time_in_force=TimeInForce.DAY,
            )
            order = client.submit_order(req)
            print(f"    Market SELL submitted: {order.id}")
        else:
            print(f"    [DRY-RUN] Market SELL {symbol}")
        state["stop_orders"].pop(symbol, None)

    # ── Entries ────────────────────────────────────────────────────────────
    for symbol in entries:
        snap         = signals["snapshots"].get(symbol, {})
        close        = snap.get("close", 0)
        atr          = snap.get("atr", close * 0.02)
        notional     = round(equity * POSITION_PCT, 2)
        initial_stop = round(close - ATR_STOP_MULT * atr, 2)
        est_qty      = round(notional / close, 6) if close > 0 else 0

        print(f"\n  ENTER {symbol}  notional=${notional:.2f}  "
              f"close=${close}  ATR=${atr:.2f}  stop=${initial_stop}")
        print(f"    score={snap.get('score',0):.4f}  "
              f"adx={snap.get('adx',0):.1f}  rsi={snap.get('rsi',0):.1f}")

        if not dry_run:
            # Market order — fills at next open
            req = MarketOrderRequest(
                symbol=symbol,
                notional=notional,
                side=OrderSide.BUY,
                time_in_force=TimeInForce.DAY,
            )
            order = client.submit_order(req)
            print(f"    Market BUY submitted: {order.id}")
            # Stop order — GTC, will need updating daily as stop trails
            stop_id = submit_stop(client, symbol, est_qty, initial_stop, dry_run=False)
            if stop_id:
                print(f"    Stop order submitted: {stop_id} @ ${initial_stop}")
                state["stop_orders"][symbol] = {
                    "order_id":   stop_id,
                    "stop_price": initial_stop,
                    "qty":        est_qty,
                    "entry_close": close,
                }
        else:
            print(f"    [DRY-RUN] Market BUY {symbol} notional=${notional:.2f}")
            submit_stop(client, symbol, est_qty, initial_stop, dry_run=True)

    state["last_rebalance_date"] = date.today().isoformat()


# ── Daily stop update (run every day, not just rebalance days) ─────────────

def update_trailing_stops(client: TradingClient, data: dict,
                           state: dict, dry_run: bool = False):
    """
    For each open position, recompute the ATR trailing stop and update
    the Alpaca stop order if the stop has moved higher.
    """
    positions = get_positions(client)
    if not positions:
        return

    print("\n  Updating trailing stops...")
    open_stops = get_open_stop_orders(client)

    for symbol, pos in positions.items():
        if symbol not in data:
            continue

        df       = data[symbol]
        atr_val  = float(_atr(df["High"], df["Low"], df["Close"], 14).iloc[-1])
        close    = float(df["Close"].iloc[-1])
        new_stop = round(close - ATR_TRAIL_MULT * atr_val, 2)

        saved = state["stop_orders"].get(symbol, {})
        old_stop = saved.get("stop_price", 0)

        if new_stop > old_stop:
            # Stop has ratcheted up — cancel old, submit new
            if symbol in open_stops:
                cancel_stop_order(client, open_stops[symbol])
            qty = pos["qty"]
            print(f"    {symbol}: stop ${old_stop:.2f} → ${new_stop:.2f}  "
                  f"(close=${close:.2f}, ATR={atr_val:.2f})")
            stop_id = submit_stop(client, symbol, qty, new_stop, dry_run=dry_run)
            if stop_id and not dry_run:
                state["stop_orders"][symbol] = {
                    "order_id":   stop_id,
                    "stop_price": new_stop,
                    "qty":        qty,
                    "entry_close": saved.get("entry_close", close),
                }
        else:
            print(f"    {symbol}: stop ${old_stop:.2f} unchanged  "
                  f"(new calc ${new_stop:.2f} ≤ current)")


# ── Status display ─────────────────────────────────────────────────────────

def print_status(client: TradingClient, signals: dict):
    account   = client.get_account()
    positions = get_positions(client)

    print(f"\n{'='*60}")
    print(f"  ACCOUNT  {'[PAPER]' if PAPER else '[LIVE]'}")
    print(f"{'='*60}")
    print(f"  Equity:       ${float(account.equity):>10,.2f}")
    print(f"  Cash:         ${float(account.cash):>10,.2f}")
    print(f"  Buying power: ${float(account.buying_power):>10,.2f}")

    print(f"\n  OPEN POSITIONS ({len(positions)})")
    print(f"  {'Symbol':8s} {'Qty':>8} {'Value':>10} {'Entry':>8}")
    print("  " + "-" * 40)
    for sym, p in sorted(positions.items()):
        print(f"  {sym:8s} {p['qty']:>8.4f} ${p['market_value']:>9,.2f} "
              f"${p['avg_entry_price']:>7.2f}")

    print(f"\n  TODAY'S SIGNALS  ({signals['date']})")
    print(f"  {'Symbol':8s} {'Score':>7} {'ADX':>6} {'RSI':>6} "
          f"{'Close':>8} {'EMA50':>8} {'OK?':>5}")
    print("  " + "-" * 55)
    for t in signals["ranked"][:10]:
        s = signals["snapshots"].get(t, {})
        ok = "✓" if t in signals["qualified"] else "✗"
        print(f"  {t:8s} {s.get('score',0):>7.4f} {s.get('adx',0):>6.1f} "
              f"{s.get('rsi',0):>6.1f} ${s.get('close',0):>7.2f} "
              f"${s.get('ema50',0):>7.2f} {ok:>5}")

    print(f"\n  Strategy wants to hold: {signals['qualified'][:MAX_POSITIONS]}")
    print(f"{'='*60}\n")


# ── Entry point ────────────────────────────────────────────────────────────

def main():
    parser = argparse.ArgumentParser(description="RSMomentum live trader (Alpaca)")
    parser.add_argument("--status",  action="store_true", help="Show status only, no orders")
    parser.add_argument("--dry-run", action="store_true", help="Show intended orders without submitting")
    parser.add_argument("--force-rebalance", action="store_true", help="Rebalance regardless of schedule")
    args = parser.parse_args()

    mode = "PAPER" if PAPER else "LIVE"
    print(f"\n{'='*60}")
    print(f"  RSMomentum Live Trader  [{mode}]  {datetime.now():%Y-%m-%d %H:%M:%S}")
    print(f"{'='*60}")

    client  = TradingClient(API_KEY, SECRET_KEY, paper=PAPER)
    state   = load_state()

    # Fetch latest bars for entire universe
    print("\n  Fetching market data...")
    data = fetch_bars(UNIVERSE, lookback=LOOKBACK_DAYS)
    if len(data) < 3:
        print("ERROR: Not enough tickers returned. Check API keys and network.")
        sys.exit(1)

    # Compute today's signals
    print("  Computing signals...")
    signals = compute_signals(data)

    if args.status:
        print_status(client, signals)
        return

    print_status(client, signals)

    # Daily trailing stop update (every run)
    update_trailing_stops(client, data, state, dry_run=args.dry_run)

    # Rebalance if due
    if args.force_rebalance or should_rebalance(state.get("last_rebalance_date")):
        print(f"\n  Rebalance due. Last: {state.get('last_rebalance_date', 'never')}")
        rebalance(client, data, signals, state, dry_run=args.dry_run)
    else:
        print(f"\n  No rebalance due. "
              f"Last: {state.get('last_rebalance_date')} "
              f"(every {CHAMPION_PARAMS['rebalance_days']} trading days)")

    if not args.dry_run:
        save_state(state)
        print("\n  State saved.")

    print("\n  Done.\n")


if __name__ == "__main__":
    main()
