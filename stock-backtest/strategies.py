"""
Trading strategies. Signals: pd.Series with values 1 (enter long), -1 (exit), 0 (no action).
All strategies are long-only for clean backtesting.
"""
import pandas as pd
import numpy as np
from indicators import (
    ema, sma, rsi, macd, bollinger_bands, atr, adx,
    stochastic, donchian, squeeze_momentum, keltner_channel, obv
)


class BaseStrategy:
    def __init__(self):
        self.signals: dict = {}
        self.portfolio = None

    def prepare(self, data: dict):
        for ticker, df in data.items():
            self.signals[ticker] = self.generate_signals(df)

    def generate_signals(self, df: pd.DataFrame) -> pd.Series:
        raise NotImplementedError


class MomentumBreakoutStrategy(BaseStrategy):
    """
    Donchian channel breakout (longs only).
    Enter:  Close breaks above the PRIOR period's 20-day Donchian upper band
            AND price > 50 EMA (uptrend)
            AND RSI 40-78 (momentum not yet exhausted)
            AND ADX > 20 (trending market)
    Exit:   Close drops below 10-day Donchian lower band (trailing stop)
    """
    def __init__(self, dc_entry=20, dc_exit=10, ema_period=50,
                 rsi_lo=40, rsi_hi=78, adx_min=20):
        super().__init__()
        self.dc_entry = dc_entry
        self.dc_exit = dc_exit
        self.ema_period = ema_period
        self.rsi_lo = rsi_lo
        self.rsi_hi = rsi_hi
        self.adx_min = adx_min

    def generate_signals(self, df: pd.DataFrame) -> pd.Series:
        close = df["Close"]
        high  = df["High"]
        low   = df["Low"]

        # Use shifted Donchian so today's close compares against YESTERDAY's channel
        dc_upper = high.rolling(self.dc_entry).max().shift(1)
        dc_exit_lower = low.rolling(self.dc_exit).min().shift(1)

        trend = ema(close, self.ema_period)
        rsi_v = rsi(close, 14)
        adx_v = adx(high, low, close, 14)

        enter = (
            (close > dc_upper) &
            (close > trend) &
            (rsi_v >= self.rsi_lo) & (rsi_v <= self.rsi_hi) &
            (adx_v >= self.adx_min)
        )
        exit_ = (close < dc_exit_lower)

        signals = pd.Series(0, index=df.index)
        signals[enter] = 1
        signals[exit_] = -1
        return signals


class MACDMomentumStrategy(BaseStrategy):
    """
    MACD bullish crossover with 200 EMA trend filter and RSI confirmation.
    Enter:  MACD line crosses above signal AND price > 200 EMA AND RSI 45-75
    Exit:   MACD crosses back below signal OR RSI > 80 (overbought)
    """
    def __init__(self, fast=12, slow=26, signal_p=9, ema_long=200):
        super().__init__()
        self.fast = fast
        self.slow = slow
        self.signal_p = signal_p
        self.ema_long = ema_long

    def generate_signals(self, df: pd.DataFrame) -> pd.Series:
        close = df["Close"]
        macd_line, sig_line, _ = macd(close, self.fast, self.slow, self.signal_p)
        long_ema = ema(close, self.ema_long)
        rsi_v = rsi(close, 14)

        bullish_cross = (macd_line > sig_line) & (macd_line.shift(1) <= sig_line.shift(1))
        bearish_cross = (macd_line < sig_line) & (macd_line.shift(1) >= sig_line.shift(1))

        enter = bullish_cross & (close > long_ema) & (rsi_v >= 45) & (rsi_v <= 75)
        exit_ = bearish_cross | (rsi_v > 82)

        signals = pd.Series(0, index=df.index)
        signals[enter] = 1
        signals[exit_] = -1
        return signals


class RSIMeanReversionStrategy(BaseStrategy):
    """
    RSI dip-buying: enter oversold bounces in uptrends.
    Enter:  RSI drops below 32 then ticks back up, price > 200 EMA, price touches lower BB
    Exit:   RSI > 65 (mean reversion complete) OR price hits middle BB
    """
    def __init__(self, rsi_oversold=32, rsi_exit=65, bb_period=20, ema_long=200):
        super().__init__()
        self.rsi_oversold = rsi_oversold
        self.rsi_exit = rsi_exit
        self.bb_period = bb_period
        self.ema_long = ema_long

    def generate_signals(self, df: pd.DataFrame) -> pd.Series:
        close = df["Close"]
        rsi_v = rsi(close, 14)
        _, bb_mid, bb_lower = bollinger_bands(close, self.bb_period, 2.0)
        long_ema = ema(close, self.ema_long)

        was_oversold = rsi_v.shift(1) < self.rsi_oversold
        rsi_turning_up = rsi_v > rsi_v.shift(1)
        near_lower_bb = close <= bb_lower * 1.02

        enter = was_oversold & rsi_turning_up & near_lower_bb & (close > long_ema * 0.95)
        exit_ = (rsi_v > self.rsi_exit) | (close >= bb_mid)

        signals = pd.Series(0, index=df.index)
        signals[enter] = 1
        signals[exit_] = -1
        return signals


class SqueezeBreakoutStrategy(BaseStrategy):
    """
    Squeeze momentum: enter when BB expands beyond KC with rising positive momentum.
    Enter:  Squeeze just released (BB > KC) AND momentum > 0 AND momentum rising
    Exit:   Momentum turns negative
    """
    def __init__(self, bb_period=20, kc_period=20, kc_mult=1.5):
        super().__init__()
        self.bb_period = bb_period
        self.kc_period = kc_period
        self.kc_mult = kc_mult

    def generate_signals(self, df: pd.DataFrame) -> pd.Series:
        close = df["Close"]
        high  = df["High"]
        low   = df["Low"]

        squeeze_on, momentum = squeeze_momentum(
            high, low, close,
            bb_period=self.bb_period, kc_period=self.kc_period, kc_mult=self.kc_mult
        )

        squeeze_released = (~squeeze_on) & (squeeze_on.shift(1).fillna(True))
        enter = squeeze_released & (momentum > 0) & (momentum > momentum.shift(1))
        exit_ = (momentum < 0) & (momentum < momentum.shift(1))

        signals = pd.Series(0, index=df.index)
        signals[enter] = 1
        signals[exit_] = -1
        return signals


class TrendFollowingStrategy(BaseStrategy):
    """
    Triple EMA trend system with volume and ADX filters.
    Enter:  EMA(10) crosses above EMA(30) AND price > EMA(100)
            AND ADX > 25 AND volume > 1.1× 20-day average
    Exit:   EMA(10) crosses below EMA(30) OR price closes below EMA(100)
    """
    def __init__(self, ema_fast=10, ema_mid=30, ema_slow=100,
                 adx_min=25, vol_mult=1.1):
        super().__init__()
        self.ema_fast = ema_fast
        self.ema_mid = ema_mid
        self.ema_slow = ema_slow
        self.adx_min = adx_min
        self.vol_mult = vol_mult

    def generate_signals(self, df: pd.DataFrame) -> pd.Series:
        close  = df["Close"]
        volume = df["Volume"]
        high   = df["High"]
        low    = df["Low"]

        fast = ema(close, self.ema_fast)
        mid  = ema(close, self.ema_mid)
        slow = ema(close, self.ema_slow)
        adx_v   = adx(high, low, close, 14)
        avg_vol = volume.rolling(20).mean()

        golden = (fast > mid) & (fast.shift(1) <= mid.shift(1))
        death  = (fast < mid) & (fast.shift(1) >= mid.shift(1))

        enter = golden & (close > slow) & (adx_v > self.adx_min) & (volume > avg_vol * self.vol_mult)
        exit_ = death | (close < slow * 0.99)

        signals = pd.Series(0, index=df.index)
        signals[enter] = 1
        signals[exit_] = -1
        return signals


class BollingerMomentumStrategy(BaseStrategy):
    """
    Bollinger Band + RSI momentum: buy breakouts above upper BB in strong trends.
    Enter:  Price breaks above upper BB AND RSI 55-75 (strong momentum, not extreme)
            AND price > 50 EMA AND MACD histogram positive and rising
    Exit:   Price closes back inside BB OR RSI > 80
    """
    def generate_signals(self, df: pd.DataFrame) -> pd.Series:
        close = df["Close"]
        high  = df["High"]
        low   = df["Low"]

        bb_u, bb_m, _ = bollinger_bands(close, 20, 2.0)
        rsi_v = rsi(close, 14)
        trend = ema(close, 50)
        _, _, hist = macd(close)

        enter = (
            (close > bb_u) & (close.shift(1) <= bb_u.shift(1)) &
            (rsi_v >= 55) & (rsi_v <= 76) &
            (close > trend) &
            (hist > 0) & (hist > hist.shift(1))
        )
        exit_ = (close < bb_m) | (rsi_v > 82)

        signals = pd.Series(0, index=df.index)
        signals[enter] = 1
        signals[exit_] = -1
        return signals


class ComboStrategy(BaseStrategy):
    """
    Ensemble vote: enter when ≥2 of 4 sub-strategies agree.
    Exit when ≥2 agree on exit.
    """
    def __init__(self):
        super().__init__()
        self.sub = [
            MomentumBreakoutStrategy(),
            MACDMomentumStrategy(),
            TrendFollowingStrategy(),
            BollingerMomentumStrategy(),
        ]

    def prepare(self, data: dict):
        for s in self.sub:
            s.prepare(data)
        for ticker in data:
            idx = data[ticker].index
            entries = pd.DataFrame({
                f"s{i}": s.signals.get(ticker, pd.Series(0, index=idx)).reindex(idx, fill_value=0)
                for i, s in enumerate(self.sub)
            })
            entry_votes = (entries == 1).sum(axis=1)
            exit_votes  = (entries == -1).sum(axis=1)

            sig = pd.Series(0, index=idx)
            sig[entry_votes >= 2] = 1
            sig[exit_votes  >= 2] = -1
            self.signals[ticker] = sig

    def generate_signals(self, df):
        return pd.Series(0, index=df.index)
