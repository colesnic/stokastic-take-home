"""The-Odds-API client for NBA historical and current odds."""
import os
import time
from pathlib import Path
from datetime import datetime, timezone
from dotenv import load_dotenv
import requests

load_dotenv(Path(__file__).parent.parent / ".env")

BASE_URL = "https://api.the-odds-api.com/v4"
API_KEY = os.environ["ODDS_API_KEY"]
SPORT = "basketball_nba"

# Bookmakers with the sharpest lines (used as reference)
SHARP_BOOKS = ["pinnacle", "draftkings", "fanduel", "betmgm", "bovada"]


def _get(path: str, params: dict = None) -> requests.Response:
    p = {"apiKey": API_KEY}
    if params:
        p.update(params)
    resp = requests.get(BASE_URL + path, params=p, timeout=30)
    remaining = resp.headers.get("x-requests-remaining", "?")
    used = resp.headers.get("x-requests-used", "?")
    print(f"  [odds-api] used={used} remaining={remaining}")
    resp.raise_for_status()
    return resp


def get_current_odds(regions: str = "us", markets: str = "h2h") -> list:
    """Current NBA moneylines from all available books."""
    resp = _get(f"/sports/{SPORT}/odds", {
        "regions": regions,
        "markets": markets,
        "oddsFormat": "decimal",
        "bookmakers": ",".join(SHARP_BOOKS),
    })
    return resp.json()


def get_historical_odds(date_iso: str, regions: str = "us", markets: str = "h2h") -> list:
    """
    Snapshot of NBA odds at a specific UTC datetime.
    date_iso: ISO 8601 string, e.g. '2024-12-01T18:00:00Z'
    """
    resp = _get(f"/historical/sports/{SPORT}/odds", {
        "date": date_iso,
        "regions": regions,
        "markets": markets,
        "oddsFormat": "decimal",
        "bookmakers": ",".join(SHARP_BOOKS),
    })
    data = resp.json()
    # Historical endpoint wraps games in {"data": [...], "timestamp": ...}
    return data.get("data", data) if isinstance(data, dict) else data


def decimal_to_prob(decimal_odds: float) -> float:
    """Convert decimal odds to implied probability (no vig removal)."""
    return 1.0 / decimal_odds


def get_sharpest_prob(outcomes: list, team_name: str) -> float | None:
    """
    Given a list of bookmaker outcomes for one market, return the
    probability implied by the sharpest available book for `team_name`.
    Prefers Pinnacle > DraftKings > FanDuel in that order.
    """
    book_priority = ["pinnacle", "draftkings", "fanduel", "betmgm", "bovada"]
    for book_key in book_priority:
        for outcome in outcomes:
            if outcome.get("name", "").lower() == team_name.lower():
                for book in outcome.get("bookmakers", []):
                    if book["key"] == book_key:
                        for mkt in book.get("markets", []):
                            if mkt["key"] == "h2h":
                                for o in mkt["outcomes"]:
                                    if o["name"].lower() == team_name.lower():
                                        return decimal_to_prob(o["price"])
    return None


def extract_game_probs(game: dict) -> dict | None:
    """
    Extract home/away team names and their sharpest implied probability
    from a raw odds-api game object.
    Returns dict or None if no h2h markets found.
    """
    home = game["home_team"]
    away = game["away_team"]

    # Collect outcomes across all bookmakers
    all_books = game.get("bookmakers", [])
    if not all_books:
        return None

    # Build unified outcome list keyed by book priority
    home_prob = None
    away_prob = None
    for book_key in SHARP_BOOKS:
        for book in all_books:
            if book["key"] != book_key:
                continue
            for mkt in book.get("markets", []):
                if mkt["key"] != "h2h":
                    continue
                for o in mkt["outcomes"]:
                    if o["name"] == home and home_prob is None:
                        home_prob = decimal_to_prob(o["price"])
                    if o["name"] == away and away_prob is None:
                        away_prob = decimal_to_prob(o["price"])
        if home_prob is not None and away_prob is not None:
            break

    if home_prob is None or away_prob is None:
        return None

    # Normalise to remove vig
    total = home_prob + away_prob
    return {
        "game_id": game["id"],
        "commence_time": game["commence_time"],
        "home_team": home,
        "away_team": away,
        "home_prob_raw": home_prob,
        "away_prob_raw": away_prob,
        "home_prob_normed": home_prob / total,
        "away_prob_normed": away_prob / total,
    }
