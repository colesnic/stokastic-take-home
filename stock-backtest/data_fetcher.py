"""
Load real OHLCV data from stock-backtest/data/<TICKER>.csv
(committed after running download_real_data.py locally).

Falls back to yfinance if a live network is available.
Raises clearly if neither source works.
"""
import os
import pandas as pd

DATA_DIR  = os.path.join(os.path.dirname(__file__), "data")
CACHE_DIR = os.path.join(os.path.dirname(__file__), "cache")


def _load_from_csv(ticker: str) -> pd.DataFrame:
    path = os.path.join(DATA_DIR, f"{ticker}.csv")
    if not os.path.exists(path):
        return None
    df = pd.read_csv(path, index_col=0, parse_dates=True)
    df.index = pd.to_datetime(df.index)
    if df.index.tz is not None:
        df.index = df.index.tz_localize(None)
    df = df[["Open", "High", "Low", "Close", "Volume"]].copy()
    df.dropna(inplace=True)
    return df


def _load_from_yfinance(ticker: str, start: str, end: str) -> pd.DataFrame:
    try:
        import yfinance as yf
        t = yf.Ticker(ticker)
        df = t.history(start=start, end=end, interval="1d", auto_adjust=True)
        if df is None or len(df) < 10:
            return None
        df.index = pd.to_datetime(df.index)
        if df.index.tz is not None:
            df.index = df.index.tz_localize(None)
        df = df[["Open", "High", "Low", "Close", "Volume"]].copy()
        df.dropna(inplace=True)
        # Cache it for next run
        os.makedirs(CACHE_DIR, exist_ok=True)
        df.to_csv(os.path.join(CACHE_DIR, f"{ticker}_{start}_{end}_1d.csv"))
        return df
    except Exception:
        return None


def _load_from_cache(ticker: str, start: str, end: str) -> pd.DataFrame:
    path = os.path.join(CACHE_DIR, f"{ticker}_{start}_{end}_1d.csv")
    if not os.path.exists(path):
        return None
    df = pd.read_csv(path, index_col=0, parse_dates=True)
    if df.index.tz is not None:
        df.index = df.index.tz_localize(None)
    return df


def fetch_ohlcv(ticker: str, start: str, end: str, interval: str = "1d") -> pd.DataFrame:
    # 1. Real committed data (highest priority)
    df = _load_from_csv(ticker)
    if df is not None and len(df) > 50:
        # Slice to requested date range
        df = df.loc[start:end]
        if len(df) > 50:
            return df

    # 2. yfinance (works when network is available)
    df = _load_from_yfinance(ticker, start, end)
    if df is not None and len(df) > 50:
        return df

    # 3. Local run cache
    df = _load_from_cache(ticker, start, end)
    if df is not None and len(df) > 50:
        return df

    raise RuntimeError(
        f"No real data for {ticker}. "
        "Run `python3 download_real_data.py` locally, commit the data/ folder, and push."
    )


def fetch_multiple(tickers: list, start: str, end: str, interval: str = "1d",
                   allow_missing: bool = True) -> dict:
    data = {}
    missing = []
    for ticker in tickers:
        try:
            df = fetch_ohlcv(ticker, start, end, interval)
            data[ticker] = df
        except RuntimeError as e:
            missing.append(ticker)
            if not allow_missing:
                raise
        except Exception as e:
            print(f"  [warn] {ticker}: {e}")
            missing.append(ticker)

    if missing:
        print(f"\n  ⚠  Missing real data for: {missing}")
        print(f"     Run `python3 stock-backtest/download_real_data.py` locally,")
        print(f"     commit stock-backtest/data/, and push.\n")

    return data
