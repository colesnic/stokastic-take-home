"""
Live trading daemon — broad gap-fading strategy on Kalshi NBA game markets.

Polls Kalshi sandbox + The-Odds-API every POLL_INTERVAL seconds.
When the entry-price gap exceeds THRESHOLD, places a real limit order on
the Kalshi demo sandbox. Tracks fill status and settles positions when
markets finalize.

State:  data/paper_trade_state.json  — open positions + order IDs
Log:    data/paper_trades.csv        — full trade history

Usage:
    python src/paper_trade.py              # run forever (Ctrl-C to stop)
    python src/paper_trade.py --once       # single scan then exit
    python src/paper_trade.py --status     # print current state and exit
"""

import argparse
import json
import math
import re
import sys
import time
from datetime import datetime, timezone
from pathlib import Path

import pandas as pd

sys.path.insert(0, str(Path(__file__).parent))

import kalshi_client as _kc
from kalshi_client import get_all_markets
from odds_client import get_current_odds, extract_game_probs

KALSHI_ENV = _kc._ENV  # "live" or "demo"

DATA_DIR   = Path(__file__).parent.parent / "data"
STATE_FILE = DATA_DIR / "paper_trade_state.json"
LOG_FILE   = DATA_DIR / "paper_trades.csv"

THRESHOLD       = 0.08    # entry-price gap must exceed this to trigger
MIN_VOLUME      = 1000    # minimum total contracts traded (liquidity filter)
FLAT_STAKE      = 100.0   # dollars per paper trade
FEE_TAKER       = 0.07
FEE_MAKER       = 0.0175
POLL_INTERVAL   = 300     # seconds between polls (5 minutes)
MAX_YES_PRICE   = 97      # cents — don't place orders above this
MIN_YES_PRICE   = 3       # cents — don't place orders below this
STARTING_BANKROLL = 1000.0


# ── Team matching ─────────────────────────────────────────────────────────────

TEAM_ALIASES = {
    "76ers": "philadelphia", "sixers": "philadelphia",
    "bucks": "milwaukee", "bulls": "chicago",
    "cavaliers": "cleveland", "cavs": "cleveland",
    "celtics": "boston", "clippers": "clippers",
    "grizzlies": "memphis", "hawks": "atlanta",
    "heat": "miami", "hornets": "charlotte",
    "jazz": "utah", "kings": "sacramento",
    "knicks": "new york", "lakers": "los angeles",
    "magic": "orlando", "mavericks": "dallas", "mavs": "dallas",
    "nets": "brooklyn", "nuggets": "denver",
    "pacers": "indiana", "pelicans": "new orleans",
    "pistons": "detroit", "raptors": "toronto",
    "rockets": "houston", "spurs": "san antonio",
    "suns": "phoenix", "thunder": "oklahoma",
    "timberwolves": "minnesota", "wolves": "minnesota",
    "blazers": "portland", "trail blazers": "portland",
    "warriors": "golden state", "wizards": "washington",
}

TICKER_CODES = {
    "MIA": "miami", "CHI": "chicago", "LAL": "los angeles", "HOU": "houston",
    "ORL": "orlando", "DET": "detroit", "BOS": "boston", "PHI": "philadelphia",
    "CLE": "cleveland", "TOR": "toronto", "SAS": "san antonio", "MIN": "minnesota",
    "OKC": "oklahoma", "LAC": "clippers", "GSW": "golden state",
    "MIL": "milwaukee", "MEM": "memphis", "ATL": "atlanta",
    "NYK": "new york", "BKN": "brooklyn", "DEN": "denver",
    "PHX": "phoenix", "POR": "portland", "SAC": "sacramento",
    "UTA": "utah", "IND": "indiana", "NOP": "new orleans",
    "WAS": "washington", "CHA": "charlotte", "DAL": "dallas",
}


def _norm(s: str) -> str:
    s = re.sub(r"[^a-z0-9 ]", "", s.lower()).strip()
    for alias, city in TEAM_ALIASES.items():
        if alias in s:
            return city
    return s


def find_side(ticker: str, title: str, home: str, away: str) -> str | None:
    m = re.search(r"-([A-Z]{2,3})$", ticker)
    if m:
        code = m.group(1)
        if code in TICKER_CODES:
            city = TICKER_CODES[code]
            if city in _norm(home):
                return "home"
            if city in _norm(away):
                return "away"
    norm_title = _norm(title)
    if any(w in norm_title for w in _norm(home).split()):
        return "home"
    if any(w in norm_title for w in _norm(away).split()):
        return "away"
    return None


# ── State management ──────────────────────────────────────────────────────────

def load_state() -> dict:
    if STATE_FILE.exists():
        return json.loads(STATE_FILE.read_text())
    return {"open_positions": {}, "bankroll": STARTING_BANKROLL}


def save_state(state: dict):
    STATE_FILE.write_text(json.dumps(state, indent=2))


def load_log() -> pd.DataFrame:
    if LOG_FILE.exists():
        return pd.read_csv(LOG_FILE)
    cols = ["trade_id", "ticker", "side", "entry_price", "sb_prob",
            "yes_gap", "no_gap", "stake", "fee_taker", "fee_maker",
            "entry_time", "settle_time", "result", "pnl_taker", "pnl_maker",
            "status"]
    return pd.DataFrame(columns=cols)


def append_log(row: dict):
    df = load_log()
    new_row = pd.DataFrame([row])
    df = pd.concat([df, new_row], ignore_index=True)
    df.to_csv(LOG_FILE, index=False)


def update_log(trade_id: str, updates: dict):
    df = load_log()
    mask = df["trade_id"] == trade_id
    for k, v in updates.items():
        df.loc[mask, k] = v
    df.to_csv(LOG_FILE, index=False)


# ── Fee + P&L ─────────────────────────────────────────────────────────────────

def calc_pnl(entry: float, won: bool, stake: float, fee_rate: float) -> float:
    fee = fee_rate * stake * (1.0 - entry)
    if won:
        gross = stake * (1.0 - entry) / entry
        return gross - fee
    return -stake - fee


# ── Order helpers ─────────────────────────────────────────────────────────────

def _check_order_fill(order_id: str) -> str:
    """Return fill status: 'filled', 'resting', 'canceled', or 'unknown'."""
    try:
        orders = get_orders()
        for o in orders:
            if o.get("order_id") == order_id:
                status = o.get("status", "")
                remaining = o.get("remaining_count", 0)
                placed = o.get("count", 1)
                if status == "canceled":
                    return "canceled"
                if remaining == 0:
                    return "filled"
                if remaining < placed:
                    return "partial"
                return "resting"
        return "unknown"
    except Exception:
        return "unknown"


# ── Core scan ─────────────────────────────────────────────────────────────────

def scan(state: dict, verbose: bool = True) -> dict:
    now = datetime.now(timezone.utc).isoformat()
    print(f"\n{'='*60}")
    print(f"Scan at {now[:19]}Z  [market data: {KALSHI_ENV}]")
    print(f"{'='*60}")

    # ── 1. Fetch live Kalshi markets ──────────────────────────────────────────
    try:
        open_markets   = get_all_markets(series_ticker="KXNBAGAME", status="open")
        closed_markets = get_all_markets(series_ticker="KXNBAGAME", status="closed")
    except Exception as e:
        print(f"  [ERROR] Kalshi fetch failed: {e}")
        return state

    all_markets = open_markets + closed_markets
    mkt_map = {m["ticker"]: m for m in all_markets}

    # ── 2. Settle any open positions ──────────────────────────────────────────
    open_pos = state.get("open_positions", {})
    bankroll = state.get("bankroll", STARTING_BANKROLL)
    to_remove = []

    for ticker, pos in open_pos.items():
        mkt = mkt_map.get(ticker)
        if not mkt:
            settled = get_all_markets(series_ticker="KXNBAGAME", status="settled")
            mkt = next((m for m in settled if m["ticker"] == ticker), None)

        if not mkt:
            continue

        mkt_status = mkt.get("status", "")
        result = mkt.get("result", "")

        if mkt_status == "finalized" or (mkt_status in ("settled",) and result in ("yes", "no")):
            won = (result == "yes" and pos["side"] == "YES") or \
                  (result == "no"  and pos["side"] == "NO")
            entry = pos["entry_price"]

            pnl_taker = calc_pnl(entry, won, FLAT_STAKE, FEE_TAKER)
            pnl_maker = calc_pnl(entry, won, FLAT_STAKE, FEE_MAKER)

            bankroll += FLAT_STAKE + pnl_taker  # return stake + winnings (or minus loss)

            update_log(pos["trade_id"], {
                "settle_time": now,
                "result":      result,
                "pnl_taker":   round(pnl_taker, 2),
                "pnl_maker":   round(pnl_maker, 2),
                "status":      "settled",
            })
            to_remove.append(ticker)

            outcome = "WON ✓" if won else "LOST ✗"
            print(f"  SETTLED  {ticker} | {pos['side']} @ {entry:.2f} | {outcome} "
                  f"| taker P&L: ${pnl_taker:+.2f} | bankroll now: ${bankroll:.2f}")

    for t in to_remove:
        del open_pos[t]


    # ── 3. Fetch sportsbook odds ──────────────────────────────────────────────
    try:
        sb_games = get_current_odds()
    except Exception as e:
        print(f"  [ERROR] Odds API fetch failed: {e}")
        state["open_positions"] = open_pos
        return state

    # ── 4. Scan open markets for signals ─────────────────────────────────────
    signals_found = 0

    for mkt in open_markets:
        ticker = mkt["ticker"]
        if "KXNBAGAME-" not in ticker:
            continue

        if ticker in open_pos:
            continue

        yb = mkt.get("yes_bid_dollars")
        ya = mkt.get("yes_ask_dollars")
        vol = mkt.get("volume_fp", 0) or 0

        if yb is None or ya is None:
            continue
        yb, ya = float(yb), float(ya)

        if ya >= 0.90 or yb <= 0.10 or ya <= yb:
            continue

        try:
            vol = float(vol)
        except (TypeError, ValueError):
            vol = 0
        if vol < MIN_VOLUME:
            continue

        title    = mkt.get("title", "")
        best_game, best_side = None, None
        for game in sb_games:
            side = find_side(ticker, title, game["home_team"], game["away_team"])
            if side:
                best_game, best_side = game, side
                break

        if best_game is None:
            continue

        probs = extract_game_probs(best_game)
        if not probs:
            continue

        sb_prob = probs["home_prob_normed"] if best_side == "home" else probs["away_prob_normed"]

        yes_gap = sb_prob - ya
        no_gap  = yb - sb_prob

        trade_side  = None
        entry_price = None
        yes_price_cents = None

        if yes_gap > THRESHOLD:
            trade_side      = "YES"
            entry_price     = ya
            yes_price_cents = math.ceil(ya * 100)
            yes_price_cents = min(yes_price_cents, MAX_YES_PRICE)
        elif no_gap > THRESHOLD:
            trade_side      = "NO"
            entry_price     = 1.0 - yb
            # For NO orders, yes_price is the YES price of this NO buy = (1 - no_ask)
            # NO taker buys NO at (1 - yes_bid), so yes_price for the order = yes_bid cents
            yes_price_cents = math.floor(yb * 100)
            yes_price_cents = max(yes_price_cents, MIN_YES_PRICE)

        if trade_side is None:
            best_gap = max(yes_gap, no_gap)
            if best_gap > 0.04:
                print(f"  near-miss  {ticker} | best gap={best_gap:+.3f} (threshold={THRESHOLD:.0%})")
            continue

        # ── Log paper trade (no real order placed) ────────────────────────────
        if bankroll < FLAT_STAKE:
            print(f"  [SKIP] {ticker} — bankroll ${bankroll:.2f} below stake ${FLAT_STAKE:.0f}")
            continue

        signals_found += 1
        trade_id = f"{ticker}_{trade_side}_{now[:19].replace(':','-')}"

        fee_taker_amt = FEE_TAKER * FLAT_STAKE * (1.0 - entry_price)
        fee_maker_amt = FEE_MAKER * FLAT_STAKE * (1.0 - entry_price)

        bankroll -= FLAT_STAKE  # reserve stake

        row = {
            "trade_id":    trade_id,
            "ticker":      ticker,
            "side":        trade_side,
            "entry_price": round(entry_price, 4),
            "sb_prob":     round(sb_prob, 4),
            "yes_gap":     round(yes_gap, 4),
            "no_gap":      round(no_gap, 4),
            "stake":       FLAT_STAKE,
            "fee_taker":   round(fee_taker_amt, 2),
            "fee_maker":   round(fee_maker_amt, 2),
            "entry_time":  now,
            "settle_time": None,
            "result":      None,
            "pnl_taker":   None,
            "pnl_maker":   None,
            "status":      "open",
        }
        append_log(row)

        open_pos[ticker] = {
            "trade_id":    trade_id,
            "side":        trade_side,
            "entry_price": round(entry_price, 4),
            "sb_prob":     round(sb_prob, 4),
        }

        dir_gap = yes_gap if trade_side == "YES" else no_gap
        print(f"  *** SIGNAL *** {ticker}")
        print(f"    Side:       {trade_side}")
        print(f"    Entry:      {entry_price:.3f}  (sb_prob={sb_prob:.3f}, gap={dir_gap:+.3f})")
        print(f"    Fees:       taker=${fee_taker_amt:.2f}  maker=${fee_maker_amt:.2f}  (per ${FLAT_STAKE:.0f} stake)")
        print(f"    Game:       {probs['away_team']} @ {probs['home_team']}")
        print(f"    Bankroll:   ${bankroll:.2f} remaining ({len(open_pos)} open)")

    deployed = len(open_pos) * FLAT_STAKE
    print(f"\n  Bankroll: ${bankroll:.2f} cash  |  ${deployed:.2f} deployed  |  ${bankroll + deployed:.2f} total")
    if signals_found == 0:
        print(f"  No new signals (threshold={THRESHOLD:.0%}). Open positions: {len(open_pos)}")

    state["open_positions"] = open_pos
    state["bankroll"] = round(bankroll, 2)
    return state


# ── Status display ────────────────────────────────────────────────────────────

def show_status():
    state = load_state()
    log   = load_log()

    bankroll = state.get("bankroll", STARTING_BANKROLL)
    open_pos = state.get("open_positions", {})
    cost_basis = len(open_pos) * FLAT_STAKE

    print(f"\n=== Paper Trade Status  [market data: {KALSHI_ENV}] ===")
    # Fetch current market prices for mark-to-market
    try:
        live_mkts = get_all_markets(series_ticker="KXNBAGAME", status="open")
        live_map  = {m["ticker"]: m for m in live_mkts}
    except Exception:
        live_map = {}

    print(f"\nOpen positions: {len(open_pos)}")
    total_mkt_value = 0.0
    for ticker, pos in open_pos.items():
        mkt = live_map.get(ticker, {})
        side = pos["side"]
        entry = pos["entry_price"]
        if side == "YES":
            cur_price = float(mkt.get("yes_bid_dollars", entry))  # can exit at bid
        else:
            yes_ask = float(mkt.get("yes_ask_dollars", 1 - entry))
            cur_price = 1.0 - yes_ask  # NO value = 1 - yes_ask
        mkt_value = FLAT_STAKE * cur_price / entry
        total_mkt_value += mkt_value
        unreal_pnl = mkt_value - FLAT_STAKE
        print(f"  {ticker} | {side} @ {entry:.2f} → now {cur_price:.2f} | "
              f"value: ${mkt_value:.2f} ({unreal_pnl:+.2f})")

    total = bankroll + total_mkt_value
    print(f"\nBankroll:  ${bankroll:.2f} cash  |  ${total_mkt_value:.2f} mkt value  |  ${total:.2f} total")
    print(f"Return:    ${total - STARTING_BANKROLL:+.2f}  ({(total - STARTING_BANKROLL) / STARTING_BANKROLL:+.1%})")

    if len(log):
        settled = log[log["status"] == "settled"]
        print(f"\nSettled trades: {len(settled)}")
        if len(settled):
            print(f"  Taker P&L:  ${settled['pnl_taker'].sum():+.2f}  "
                  f"(ROI: {settled['pnl_taker'].sum() / (FLAT_STAKE * len(settled)):+.1%})")
            print(f"  Maker P&L:  ${settled['pnl_maker'].sum():+.2f}  "
                  f"(ROI: {settled['pnl_maker'].sum() / (FLAT_STAKE * len(settled)):+.1%})")
            print(f"  Win rate:   {(settled['pnl_taker'] > 0).mean():.1%}")
            print()
            print(settled[["ticker","side","entry_price","sb_prob","result",
                            "pnl_taker","pnl_maker"]].to_string(index=False))
    else:
        print("No settled trades yet.")


# ── Main loop ─────────────────────────────────────────────────────────────────

def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--once",   action="store_true", help="Single scan then exit")
    parser.add_argument("--status", action="store_true", help="Print status and exit")
    args = parser.parse_args()

    if args.status:
        show_status()
        return

    print(f"Paper trader started | env={KALSHI_ENV} | threshold={THRESHOLD:.0%} | stake=${FLAT_STAKE:.0f} | poll={POLL_INTERVAL}s")
    print(f"State: {STATE_FILE}")
    print(f"Log:   {LOG_FILE}")

    state = load_state()

    if args.once:
        state = scan(state)
        save_state(state)
        show_status()
        return

    try:
        while True:
            state = scan(state)
            save_state(state)
            print(f"\n  Next scan in {POLL_INTERVAL//60}m {POLL_INTERVAL%60}s "
                  f"(Ctrl-C to stop)")
            time.sleep(POLL_INTERVAL)
    except KeyboardInterrupt:
        print("\nStopped.")
        save_state(state)
        show_status()


if __name__ == "__main__":
    main()
