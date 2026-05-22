"""
Load real OHLCV data. Priority order:
  1. stock-backtest/data/<TICKER>.csv  (committed locally)
  2. yfinance (works when running locally)
  3. GitHub raw (works in sandbox after data is pushed to the repo)
  4. Clear error with instructions
"""
import os
import io
import pandas as pd

DATA_DIR  = os.path.join(os.path.dirname(__file__), "data")
CACHE_DIR = os.path.join(os.path.dirname(__file__), "cache")

GITHUB_RAW_BASE = (
    "https://raw.githubusercontent.com/colesnic/stokastic-take-home/"
    "claude%2Fstock-backtesting-algo-IVqoW/stock-backtest/data"
)


def _parse_df(df: pd.DataFrame) -> pd.DataFrame:
    df.index = pd.to_datetime(df.index)
    if df.index.tz is not None:
        df.index = df.index.tz_localize(None)
    cols = [c for c in ["Open", "High", "Low", "Close", "Volume"] if c in df.columns]
    return df[cols].dropna()


def _load_from_csv(ticker: str) -> pd.DataFrame | None:
    path = os.path.join(DATA_DIR, f"{ticker}.csv")
    if not os.path.exists(path):
        return None
    df = pd.read_csv(path, index_col=0, parse_dates=True)
    return _parse_df(df)


def _load_from_yfinance(ticker: str, start: str, end: str) -> pd.DataFrame | None:
    try:
        import yfinance as yf
        t = yf.Ticker(ticker)
        df = t.history(start=start, end=end, interval="1d", auto_adjust=True)
        if df is None or len(df) < 10:
            return None
        df = _parse_df(df)
        os.makedirs(CACHE_DIR, exist_ok=True)
        df.to_csv(os.path.join(CACHE_DIR, f"{ticker}_{start}_{end}_1d.csv"))
        return df
    except Exception:
        return None


def _load_from_github(ticker: str) -> pd.DataFrame | None:
    """Pull from our own repo's raw GitHub content — works in the Claude sandbox."""
    try:
        import urllib.request
        url = f"{GITHUB_RAW_BASE}/{ticker}.csv"
        with urllib.request.urlopen(url, timeout=8) as resp:
            content = resp.read().decode("utf-8")
        df = pd.read_csv(io.StringIO(content), index_col=0, parse_dates=True)
        parsed = _parse_df(df)
        if len(parsed) > 50:
            # Cache locally so next run is instant
            os.makedirs(CACHE_DIR, exist_ok=True)
            parsed.to_csv(os.path.join(CACHE_DIR, f"{ticker}_github.csv"))
            return parsed
    except Exception:
        pass
    return None


def _load_from_cache(ticker: str) -> pd.DataFrame | None:
    for fname in [f"{ticker}_github.csv"]:
        path = os.path.join(CACHE_DIR, fname)
        if os.path.exists(path):
            df = pd.read_csv(path, index_col=0, parse_dates=True)
            return _parse_df(df)
    # Try any cache file for this ticker
    if os.path.exists(CACHE_DIR):
        for fname in os.listdir(CACHE_DIR):
            if fname.startswith(ticker + "_") and fname.endswith(".csv"):
                df = pd.read_csv(os.path.join(CACHE_DIR, fname), index_col=0, parse_dates=True)
                return _parse_df(df)
    return None


def fetch_ohlcv(ticker: str, start: str, end: str, interval: str = "1d") -> pd.DataFrame:
    # 1. Local committed CSV
    df = _load_from_csv(ticker)
    if df is not None and len(df) > 50:
        return df.loc[start:end] if len(df.loc[start:end]) > 50 else df

    # 2. yfinance (works locally)
    df = _load_from_yfinance(ticker, start, end)
    if df is not None and len(df) > 50:
        return df

    # 3. GitHub raw (works in sandbox after data is pushed)
    df = _load_from_github(ticker)
    if df is not None and len(df) > 50:
        sliced = df.loc[start:end]
        return sliced if len(sliced) > 50 else df

    # 4. Local cache (previously fetched)
    df = _load_from_cache(ticker)
    if df is not None and len(df) > 50:
        sliced = df.loc[start:end]
        return sliced if len(sliced) > 50 else df

    raise RuntimeError(
        f"No real data for {ticker}.\n"
        "  To fix: run `python3 stock-backtest/download_real_data.py` locally,\n"
        "  then: git add stock-backtest/data/ && git commit -m 'real data' && git push"
    )


def fetch_multiple(tickers: list, start: str, end: str, interval: str = "1d",
                   allow_missing: bool = True) -> dict:
    data = {}
    missing = []
    sources_used = set()

    for ticker in tickers:
        try:
            # Track which source
            if _load_from_csv(ticker) is not None:
                sources_used.add("local CSV")
            elif _load_from_yfinance(ticker, start, end) is not None:
                sources_used.add("yfinance")
            else:
                sources_used.add("GitHub raw / cache")

            df = fetch_ohlcv(ticker, start, end, interval)
            data[ticker] = df
        except RuntimeError:
            missing.append(ticker)
            if not allow_missing:
                raise
        except Exception as e:
            missing.append(ticker)

    if data:
        print(f"  Loaded {len(data)} tickers (sources: {', '.join(sources_used)})")
    if missing:
        print(f"\n  ⚠  No real data for {len(missing)} tickers: {missing}")
        print(f"     Run `python3 stock-backtest/download_real_data.py` locally,")
        print(f"     commit stock-backtest/data/, and push to the repo.\n")

    return data

