"""
Fetch or generate historical OHLCV data.
Tries yfinance first; falls back to synthetic GBM data if network is blocked.
"""
import numpy as np
import pandas as pd
import os

CACHE_DIR = os.path.join(os.path.dirname(__file__), "cache")


# Realistic parameters per ticker: (annual_drift, annual_vol, start_price, avg_volume)
TICKER_PARAMS = {
    "NVDA":  (1.20, 0.65, 140.0,   40_000_000),
    "AMD":   (0.45, 0.58, 100.0,   30_000_000),
    "AAPL":  (0.25, 0.28, 170.0,   80_000_000),
    "MSFT":  (0.30, 0.27, 290.0,   25_000_000),
    "META":  (0.55, 0.48, 200.0,   18_000_000),
    "GOOGL": (0.28, 0.30, 100.0,   22_000_000),
    "TSLA":  (0.40, 0.75, 120.0,   80_000_000),
    "AMZN":  (0.30, 0.35,  95.0,   35_000_000),
    "SMCI":  (1.80, 1.20,  80.0,   10_000_000),
    "ARM":   (0.70, 0.65,  60.0,    8_000_000),
    "AVGO":  (0.45, 0.38, 500.0,    7_000_000),
    "MRVL":  (0.38, 0.52,  45.0,   12_000_000),
    "QQQ":   (0.22, 0.22, 360.0,   45_000_000),
    "SOXX":  (0.28, 0.30, 420.0,    2_500_000),
    "ARKK":  (-0.10, 0.55, 70.0,   10_000_000),
    "XLK":   (0.25, 0.24, 155.0,    5_000_000),
    "XLY":   (0.15, 0.26, 160.0,    4_000_000),
    "MRNA":  (-0.30, 0.70, 200.0,   5_000_000),
    "BIIB":  (0.05, 0.35, 250.0,    1_200_000),
    "COIN":  (0.80, 1.10,  90.0,   12_000_000),
    "MSTR":  (1.50, 1.20, 200.0,    4_000_000),
    "PLTR":  (0.35, 0.65,  10.0,   40_000_000),
}

DEFAULT_PARAMS = (0.20, 0.35, 50.0, 5_000_000)


def _trading_days(start: str, end: str) -> pd.DatetimeIndex:
    dates = pd.bdate_range(start=start, end=end, freq="B")
    return dates


def generate_synthetic_ohlcv(ticker: str, start: str, end: str,
                              seed: int = None) -> pd.DataFrame:
    """
    Generate realistic OHLCV data using Geometric Brownian Motion with regime switching
    and realistic intraday bar structure.
    """
    drift, vol, s0, avg_vol = TICKER_PARAMS.get(ticker, DEFAULT_PARAMS)
    dates = _trading_days(start, end)
    n = len(dates)
    if n == 0:
        return pd.DataFrame()

    rng = np.random.default_rng(seed if seed is not None else hash(ticker) % (2**31))

    dt = 1 / 252
    # Regime switching: bull/bear/neutral
    regime_len = rng.integers(20, 60, size=n // 10 + 5)
    regimes = []
    for rl in regime_len:
        r = rng.choice([1, -1, 0], p=[0.5, 0.25, 0.25])
        regimes.extend([r] * rl)
    regime_arr = np.array(regimes[:n])

    regime_drift = regime_arr * 0.30  # extra drift in trending regime

    # Volatility clustering (GARCH-like): vol mean-reverts, shocks persist
    vols = np.zeros(n)
    vols[0] = vol
    shock_persistence = 0.85
    for i in range(1, n):
        innovation = abs(rng.standard_normal()) * 0.10
        vols[i] = shock_persistence * vols[i-1] + (1 - shock_persistence) * vol + innovation * vol * 0.15
    vols = np.clip(vols, vol * 0.4, vol * 3.0)

    # Daily returns
    daily_drift = (drift + regime_drift) * dt
    daily_vol = vols * np.sqrt(dt)
    z = rng.standard_normal(n)
    log_returns = daily_drift - 0.5 * daily_vol**2 + daily_vol * z

    # Price path
    log_prices = np.log(s0) + np.cumsum(log_returns)
    closes = np.exp(log_prices)

    # Realistic OHLC from close
    intraday_vol = vols * np.sqrt(dt) * 0.6
    z2 = rng.standard_normal((n, 4))
    opens  = closes * np.exp(intraday_vol * z2[:, 0] * 0.3)
    highs  = np.maximum(opens, closes) * np.exp(abs(intraday_vol * z2[:, 1]) * 0.8)
    lows   = np.minimum(opens, closes) * np.exp(-abs(intraday_vol * z2[:, 2]) * 0.8)
    # Ensure OHLC consistency
    highs  = np.maximum(highs, np.maximum(opens, closes))
    lows   = np.minimum(lows, np.minimum(opens, closes))

    # Volume: log-normal, higher on volatile days
    vol_factor = vols / vol
    base_vol = avg_vol * vol_factor * rng.lognormal(0, 0.4, n)
    volumes = base_vol.astype(int)

    df = pd.DataFrame({
        "Open":   opens,
        "High":   highs,
        "Low":    lows,
        "Close":  closes,
        "Volume": volumes,
    }, index=dates)
    df.index.name = "Date"
    return df


def fetch_ohlcv(ticker: str, start: str, end: str, interval: str = "1d",
                use_cache: bool = True) -> pd.DataFrame:
    os.makedirs(CACHE_DIR, exist_ok=True)
    cache_key = f"{ticker}_{start}_{end}_{interval}.csv"
    cache_path = os.path.join(CACHE_DIR, cache_key)

    if use_cache and os.path.exists(cache_path):
        df = pd.read_csv(cache_path, index_col=0, parse_dates=True)
        return df

    # Try yfinance
    df = None
    try:
        import yfinance as yf
        t = yf.Ticker(ticker)
        raw = t.history(start=start, end=end, interval=interval, auto_adjust=True)
        if raw is not None and len(raw) > 50:
            raw.index = pd.to_datetime(raw.index)
            if raw.index.tz is not None:
                raw.index = raw.index.tz_localize(None)
            df = raw[["Open", "High", "Low", "Close", "Volume"]].copy()
            df.dropna(inplace=True)
    except Exception:
        pass

    # Fall back to synthetic data
    if df is None or len(df) < 50:
        df = generate_synthetic_ohlcv(ticker, start, end)

    if use_cache and df is not None and len(df) > 0:
        df.to_csv(cache_path)

    return df


def fetch_multiple(tickers: list, start: str, end: str,
                   interval: str = "1d") -> dict:
    data = {}
    for ticker in tickers:
        try:
            df = fetch_ohlcv(ticker, start, end, interval)
            if len(df) > 50:
                data[ticker] = df
        except Exception as e:
            print(f"  [warn] Failed to fetch/generate {ticker}: {e}")
    return data
