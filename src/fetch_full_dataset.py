"""
Build a comprehensive dataset from ALL finalized KXNBAGAME markets.

Loads all 1,700+ finalized markets from kalshi_nba_markets.json,
fetches historical sportsbook odds for each unique game (one API call
per game, T-2h before tip-off), and outputs data/full_dataset.csv.

Uses previous_price_dollars as the Kalshi pre-game price proxy for all
games (already in the JSON for every finalized market).

Caches odds responses in data/odds_cache.json so the script can be
interrupted and resumed without re-fetching.
"""
import json
import re
import time
from pathlib import Path
from datetime import datetime, timezone, timedelta

import pandas as pd

# Add src/ to path when running directly
import sys
sys.path.insert(0, str(Path(__file__).parent))

from odds_client import get_historical_odds, extract_game_probs

DATA_DIR = Path(__file__).parent.parent / "data"

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
    "WAS": "washington", "CHA": "charlotte",
    "DAL": "dallas",
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
    norm_home = _norm(home)
    norm_away = _norm(away)
    if any(w in norm_title for w in norm_home.split()):
        return "home"
    if any(w in norm_title for w in norm_away.split()):
        return "away"
    return None


def load_cache(path: Path) -> dict:
    if path.exists():
        return json.loads(path.read_text())
    return {}


def save_cache(path: Path, cache: dict):
    path.write_text(json.dumps(cache, indent=2))


def build_full_dataset():
    markets_path = DATA_DIR / "kalshi_nba_markets.json"
    cache_path = DATA_DIR / "odds_cache.json"
    out_path = DATA_DIR / "full_dataset.csv"

    all_markets = json.loads(markets_path.read_text())
    odds_cache = load_cache(cache_path)

    finalized = [
        m for m in all_markets
        if m.get("status") == "finalized"
        and "KXNBAGAME-" in m.get("ticker", "")
        and m.get("previous_price_dollars") is not None
        and float(m.get("previous_price_dollars", 0)) > 0
    ]

    # Deduplicate by event_ticker (one observation per game, not per team)
    seen_events = set()
    unique_games = []
    for m in sorted(finalized, key=lambda x: x.get("event_ticker", "")):
        et = m.get("event_ticker", m["ticker"])
        if et not in seen_events:
            seen_events.add(et)
            unique_games.append(m)

    print(f"Unique games to process: {len(unique_games)}")

    rows = []
    api_calls = 0
    skipped_no_odds = 0
    skipped_no_match = 0

    for i, mkt in enumerate(unique_games):
        ticker = mkt["ticker"]
        exp_time = mkt.get("expected_expiration_time") or mkt.get("close_time")
        if not exp_time:
            continue

        game_dt = datetime.fromisoformat(exp_time.replace("Z", "+00:00"))
        snapshot_dt = game_dt - timedelta(hours=2)
        date_iso = snapshot_dt.strftime("%Y-%m-%dT%H:%M:%SZ")

        # Use cache to avoid redundant calls
        if date_iso not in odds_cache:
            try:
                time.sleep(0.5)
                odds_games = get_historical_odds(date_iso)
                odds_cache[date_iso] = odds_games
                api_calls += 1
                if api_calls % 20 == 0:
                    save_cache(cache_path, odds_cache)
                    print(f"  → Cache saved ({api_calls} new calls, {i+1}/{len(unique_games)} games processed)")
            except Exception as e:
                print(f"  [{i+1}] Odds API error for {date_iso}: {e}")
                odds_cache[date_iso] = []
                continue
        else:
            odds_games = odds_cache[date_iso]

        if not odds_games:
            skipped_no_odds += 1
            continue

        title = mkt.get("title", "")
        best_game, best_side = None, None
        for game in odds_games:
            side = find_side(ticker, title, game["home_team"], game["away_team"])
            if not side:
                continue
            g_dt = datetime.fromisoformat(game["commence_time"].replace("Z", "+00:00"))
            if abs((g_dt - game_dt).total_seconds()) > 86400:
                continue
            best_game, best_side = game, side
            break

        if best_game is None:
            skipped_no_match += 1
            continue

        probs = extract_game_probs(best_game)
        if not probs:
            continue

        kalshi_prev = float(mkt["previous_price_dollars"])
        sb_prob = probs["home_prob_normed"] if best_side == "home" else probs["away_prob_normed"]
        gap = sb_prob - kalshi_prev
        result = mkt.get("result", "")
        yes_ask = mkt.get("previous_yes_ask_dollars")
        yes_bid = mkt.get("previous_yes_bid_dollars")

        rows.append({
            "ticker": ticker,
            "title": title,
            "game_date": game_dt.strftime("%Y-%m-%d"),
            "home_team": probs["home_team"],
            "away_team": probs["away_team"],
            "kalshi_team_side": best_side,
            "kalshi_prev_price": kalshi_prev,
            "yes_bid": float(yes_bid) if yes_bid else None,
            "yes_ask": float(yes_ask) if yes_ask else None,
            "sb_prob_normed": sb_prob,
            "gap": gap,
            "result": result,
            "volume": mkt.get("volume_fp"),
            "yes_side_won": 1 if result == "yes" else 0,
        })

    # Final cache save
    save_cache(cache_path, odds_cache)

    df = pd.DataFrame(rows)
    df.sort_values("game_date", inplace=True)
    df.to_csv(out_path, index=False)

    print(f"\nDone.")
    print(f"  Total rows: {len(df)}")
    print(f"  Date range: {df['game_date'].min()} to {df['game_date'].max()}")
    print(f"  API calls made: {api_calls} (cached: {len(odds_cache) - api_calls})")
    print(f"  Skipped (no odds): {skipped_no_odds}")
    print(f"  Skipped (no match): {skipped_no_match}")
    print(f"  Saved to: {out_path}")
    return df


if __name__ == "__main__":
    build_full_dataset()
