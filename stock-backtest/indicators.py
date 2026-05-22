"""
Technical indicators implemented from scratch using only pandas/numpy.
"""
import numpy as np
import pandas as pd


def sma(series: pd.Series, period: int) -> pd.Series:
    return series.rolling(window=period).mean()


def ema(series: pd.Series, period: int) -> pd.Series:
    return series.ewm(span=period, adjust=False).mean()


def rsi(series: pd.Series, period: int = 14) -> pd.Series:
    delta = series.diff()
    gain = delta.clip(lower=0)
    loss = -delta.clip(upper=0)
    avg_gain = gain.ewm(com=period - 1, min_periods=period).mean()
    avg_loss = loss.ewm(com=period - 1, min_periods=period).mean()
    rs = avg_gain / avg_loss.replace(0, np.nan)
    return 100 - (100 / (1 + rs))


def macd(series: pd.Series, fast: int = 12, slow: int = 26, signal: int = 9):
    fast_ema = ema(series, fast)
    slow_ema = ema(series, slow)
    macd_line = fast_ema - slow_ema
    signal_line = ema(macd_line, signal)
    histogram = macd_line - signal_line
    return macd_line, signal_line, histogram


def bollinger_bands(series: pd.Series, period: int = 20, std_dev: float = 2.0):
    mid = sma(series, period)
    std = series.rolling(window=period).std()
    upper = mid + std_dev * std
    lower = mid - std_dev * std
    return upper, mid, lower


def atr(high: pd.Series, low: pd.Series, close: pd.Series, period: int = 14) -> pd.Series:
    tr = pd.concat([
        high - low,
        (high - close.shift()).abs(),
        (low - close.shift()).abs()
    ], axis=1).max(axis=1)
    return tr.ewm(com=period - 1, min_periods=period).mean()


def adx(high: pd.Series, low: pd.Series, close: pd.Series, period: int = 14) -> pd.Series:
    plus_dm = high.diff()
    minus_dm = -low.diff()
    plus_dm[plus_dm < 0] = 0
    minus_dm[minus_dm < 0] = 0
    cond = plus_dm < minus_dm
    plus_dm[cond] = 0
    cond2 = minus_dm < plus_dm
    minus_dm[cond2] = 0

    atr_val = atr(high, low, close, period)
    plus_di = 100 * ema(plus_dm, period) / atr_val
    minus_di = 100 * ema(minus_dm, period) / atr_val
    dx = 100 * (plus_di - minus_di).abs() / (plus_di + minus_di).replace(0, np.nan)
    return ema(dx, period)


def stochastic(high: pd.Series, low: pd.Series, close: pd.Series,
               k_period: int = 14, d_period: int = 3):
    lowest_low = low.rolling(window=k_period).min()
    highest_high = high.rolling(window=k_period).max()
    k = 100 * (close - lowest_low) / (highest_high - lowest_low).replace(0, np.nan)
    d = sma(k, d_period)
    return k, d


def vwap(high: pd.Series, low: pd.Series, close: pd.Series, volume: pd.Series) -> pd.Series:
    typical_price = (high + low + close) / 3
    return (typical_price * volume).cumsum() / volume.cumsum()


def obv(close: pd.Series, volume: pd.Series) -> pd.Series:
    direction = np.sign(close.diff()).fillna(0)
    return (direction * volume).cumsum()


def donchian(high: pd.Series, low: pd.Series, period: int = 20):
    upper = high.rolling(window=period).max()
    lower = low.rolling(window=period).min()
    mid = (upper + lower) / 2
    return upper, mid, lower


def keltner_channel(high: pd.Series, low: pd.Series, close: pd.Series,
                    period: int = 20, multiplier: float = 2.0):
    mid = ema(close, period)
    atr_val = atr(high, low, close, period)
    upper = mid + multiplier * atr_val
    lower = mid - multiplier * atr_val
    return upper, mid, lower


def squeeze_momentum(high: pd.Series, low: pd.Series, close: pd.Series,
                     bb_period: int = 20, bb_std: float = 2.0,
                     kc_period: int = 20, kc_mult: float = 1.5):
    """Squeeze momentum indicator: fires when Bollinger Bands are inside Keltner Channels."""
    bb_upper, _, bb_lower = bollinger_bands(close, bb_period, bb_std)
    kc_upper, _, kc_lower = keltner_channel(high, low, close, kc_period, kc_mult)
    squeeze_on = (bb_lower > kc_lower) & (bb_upper < kc_upper)
    delta = close - (high.rolling(kc_period).max() + low.rolling(kc_period).min()) / 2
    momentum = ema(delta, kc_period)
    return squeeze_on, momentum
