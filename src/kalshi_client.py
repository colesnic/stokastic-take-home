"""Kalshi API client — supports demo sandbox and live production environments.

Set KALSHI_ENV=live in your environment (or .env) to use the production API
with real market data. Defaults to the demo sandbox.
"""
import base64
import time
import os
from pathlib import Path
from cryptography.hazmat.primitives import hashes, serialization
from cryptography.hazmat.primitives.asymmetric import padding
from cryptography.hazmat.backends import default_backend
import requests
from dotenv import load_dotenv

load_dotenv(Path(__file__).parent.parent / ".env")

_ENV = os.environ.get("KALSHI_ENV", "demo").lower()

if _ENV == "live":
    BASE_URL         = "https://api.elections.kalshi.com/trade-api/v2"
    KEY_ID           = os.environ["KALSHI_REAL_API_KEY"]
    PRIVATE_KEY_PATH = Path(__file__).parent.parent / "live_rsa_private_key.pem"
else:
    BASE_URL         = "https://demo-api.kalshi.co/trade-api/v2"
    KEY_ID           = os.environ["KALSHI_DEMO_API_KEY"]
    PRIVATE_KEY_PATH = Path(__file__).parent.parent / "rsa_private_key.pem"

_API_PREFIX = "/trade-api/v2"


def _load_private_key():
    with open(PRIVATE_KEY_PATH, "rb") as f:
        return serialization.load_pem_private_key(f.read(), password=None, backend=default_backend())


_PRIVATE_KEY = _load_private_key()


def _sign(method: str, path: str) -> dict:
    ts = str(int(time.time() * 1000))
    message = (ts + method.upper() + _API_PREFIX + path).encode("utf-8")
    sig = _PRIVATE_KEY.sign(message, padding.PSS(mgf=padding.MGF1(hashes.SHA256()), salt_length=padding.PSS.DIGEST_LENGTH), hashes.SHA256())
    return {
        "KALSHI-ACCESS-KEY": KEY_ID,
        "KALSHI-ACCESS-TIMESTAMP": ts,
        "KALSHI-ACCESS-SIGNATURE": base64.b64encode(sig).decode("utf-8"),
    }


def _post(path: str, body: dict) -> dict:
    headers = _sign("POST", path)
    headers["Content-Type"] = "application/json"
    resp = requests.post(BASE_URL + path, headers=headers, json=body, timeout=30)
    resp.raise_for_status()
    return resp.json()


def _delete(path: str) -> dict:
    headers = _sign("DELETE", path)
    headers["Content-Type"] = "application/json"
    resp = requests.delete(BASE_URL + path, headers=headers, timeout=30)
    resp.raise_for_status()
    return resp.json()


def _get(path: str, params: dict = None) -> dict:
    headers = _sign("GET", path)
    headers["Content-Type"] = "application/json"
    resp = requests.get(BASE_URL + path, headers=headers, params=params, timeout=30)
    resp.raise_for_status()
    return resp.json()


def get_markets(series_ticker: str = None, status: str = "open", limit: int = 200, cursor: str = None) -> dict:
    params = {"limit": limit, "status": status}
    if series_ticker:
        params["series_ticker"] = series_ticker
    if cursor:
        params["cursor"] = cursor
    return _get("/markets", params)


def get_all_markets(series_ticker: str = None, status: str = None) -> list:
    """Paginate through all markets for a series."""
    markets = []
    cursor = None
    while True:
        resp = get_markets(series_ticker=series_ticker, status=status, limit=1000, cursor=cursor)
        markets.extend(resp.get("markets", []))
        cursor = resp.get("cursor")
        if not cursor:
            break
    return markets


def get_market(ticker: str) -> dict:
    return _get(f"/markets/{ticker}")


def get_orderbook(ticker: str, depth: int = 10) -> dict:
    return _get(f"/markets/{ticker}/orderbook", {"depth": depth})


def get_trades(ticker: str, min_ts: int = None, max_ts: int = None, limit: int = 1000) -> list:
    """Fetch all trades for a market, paginating as needed."""
    trades = []
    cursor = None
    while True:
        params = {"ticker": ticker, "limit": limit}
        if min_ts:
            params["min_ts"] = min_ts
        if max_ts:
            params["max_ts"] = max_ts
        if cursor:
            params["cursor"] = cursor
        resp = _get("/markets/trades", params)
        batch = resp.get("trades", [])
        trades.extend(batch)
        cursor = resp.get("cursor")
        if not cursor or not batch:
            break
    return trades


def get_series_list(limit: int = 200) -> list:
    resp = _get("/series", {"limit": limit})
    return resp.get("series", [])


def get_events(series_ticker: str = None, status: str = None, limit: int = 200) -> list:
    params = {"limit": limit}
    if series_ticker:
        params["series_ticker"] = series_ticker
    if status:
        params["status"] = status
    resp = _get("/events", params)
    return resp.get("events", [])


# ── Historical API endpoints ──────────────────────────────────────────────────

def get_historical_cutoff() -> dict:
    return _get("/historical/cutoff")


def get_historical_markets(series_ticker: str = None, status: str = None,
                           limit: int = 200, cursor: str = None) -> dict:
    params = {"limit": limit}
    if series_ticker:
        params["series_ticker"] = series_ticker
    if status:
        params["status"] = status
    if cursor:
        params["cursor"] = cursor
    return _get("/historical/markets", params)


def get_all_historical_markets(series_ticker: str = None) -> list:
    markets = []
    cursor = None
    while True:
        resp = get_historical_markets(series_ticker=series_ticker, limit=1000, cursor=cursor)
        markets.extend(resp.get("markets", []))
        cursor = resp.get("cursor")
        if not cursor:
            break
    return markets


def get_historical_market(ticker: str) -> dict:
    return _get(f"/historical/markets/{ticker}")


def get_historical_candlesticks(ticker: str, start_ts: int, end_ts: int,
                                period_interval: int = 60) -> list:
    resp = _get(f"/historical/markets/{ticker}/candlesticks", {
        "start_ts": start_ts,
        "end_ts": end_ts,
        "period_interval": period_interval,
    })
    return resp.get("candlesticks", [])


def get_historical_trades(ticker: str = None, min_ts: int = None,
                          max_ts: int = None, limit: int = 1000) -> list:
    trades = []
    cursor = None
    while True:
        params = {"limit": limit}
        if ticker:
            params["ticker"] = ticker
        if min_ts:
            params["min_ts"] = min_ts
        if max_ts:
            params["max_ts"] = max_ts
        if cursor:
            params["cursor"] = cursor
        resp = _get("/historical/trades", params)
        batch = resp.get("trades", [])
        trades.extend(batch)
        cursor = resp.get("cursor")
        if not cursor or not batch:
            break
    return trades


# ── Portfolio endpoints (demo only — live key is read-only) ───────────────────

def get_balance() -> dict:
    return _get("/portfolio/balance")


def get_positions(ticker: str = None) -> list:
    params = {}
    if ticker:
        params["ticker"] = ticker
    resp = _get("/portfolio/positions", params)
    return resp.get("market_positions", [])


def get_orders(ticker: str = None, status: str = None) -> list:
    params = {"limit": 200}
    if ticker:
        params["ticker"] = ticker
    if status:
        params["status"] = status
    resp = _get("/portfolio/orders", params)
    return resp.get("orders", [])


def place_order(ticker: str, side: str, count: int, yes_price_cents: int,
                order_type: str = "limit", client_order_id: str = None) -> dict:
    import uuid
    body = {
        "ticker":           ticker,
        "client_order_id":  client_order_id or str(uuid.uuid4()),
        "type":             order_type,
        "action":           "buy",
        "side":             side,
        "count":            count,
        "yes_price":        yes_price_cents,
    }
    return _post("/portfolio/orders", body)


def sell_position(ticker: str, side: str, count: int, yes_price_cents: int,
                  order_type: str = "limit", client_order_id: str = None) -> dict:
    import uuid
    body = {
        "ticker":           ticker,
        "client_order_id":  client_order_id or str(uuid.uuid4()),
        "type":             order_type,
        "action":           "sell",
        "side":             side,
        "count":            count,
        "yes_price":        yes_price_cents,
    }
    return _post("/portfolio/orders", body)


def cancel_order(order_id: str) -> dict:
    return _delete(f"/portfolio/orders/{order_id}")
