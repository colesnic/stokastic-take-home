"""
Relative Strength Momentum strategy:
- Rank all tickers by multi-period relative strength
- Go long the top N ranked tickers when they satisfy entry filters
- Rotate weekly: sell losers, buy new leaders
This is the classic momentum factor strategy (Jegadeesh & Titman, 1993).
"""
import pandas as pd
import numpy as np
from indicators import ema, rsi, macd, atr, adx


class RSMomentumStrategy:
    """
    Pure relative strength rotation: always hold the top-N momentum stocks.
    Momentum score = blended return over 20/60/120 day windows (with recency weighting).
    Enter when score is in top-N AND price > 50 EMA AND ADX > 20.
    Rotate every `rebalance_days`.
    """
    def __init__(self, top_n: int = 2, rebalance_days: int = 5,
                 lookback_short: int = 20, lookback_mid: int = 60, lookback_long: int = 120,
                 adx_min: float = 18.0, rsi_min: float = 45.0, rsi_max: float = 82.0,
                 ema_trend_period: int = 50, regime_ticker: str = ""):
        self.top_n = top_n
        self.rebalance_days = rebalance_days
        self.lookback_short = lookback_short
        self.lookback_mid = lookback_mid
        self.lookback_long = lookback_long
        self.adx_min = adx_min
        self.rsi_min = rsi_min
        self.rsi_max = rsi_max
        self.ema_trend_period = ema_trend_period
        self.regime_ticker = regime_ticker  # if set, only enter when this ticker > EMA
        self.signals: dict = {}

    def prepare(self, data: dict):
        """
        Compute a daily rank for each ticker and generate entry/exit signals.
        """
        all_dates = sorted(set(d for df in data.values() for d in df.index))

        # Pre-compute momentum scores and filter flags per ticker per date
        ticker_scores = {}
        ticker_filters = {}

        for ticker, df in data.items():
            close = df["Close"]
            high  = df["High"]
            low   = df["Low"]

            ret_short = close.pct_change(self.lookback_short)
            ret_mid   = close.pct_change(self.lookback_mid)
            ret_long  = close.pct_change(self.lookback_long)

            # Blended score with more weight to shorter lookback
            score = 0.5 * ret_short + 0.3 * ret_mid + 0.2 * ret_long

            trend = ema(close, self.ema_trend_period)
            adx_v = adx(high, low, close, 14)
            rsi_v = rsi(close, 14)

            # Qualify filter: must be in uptrend, trending, within RSI bounds
            qualify = (
                (close > trend) &
                (adx_v >= self.adx_min) &
                (rsi_v >= self.rsi_min) &
                (rsi_v <= self.rsi_max)
            )

            ticker_scores[ticker]  = score.reindex(all_dates)
            ticker_filters[ticker] = qualify.reindex(all_dates).fillna(False)

        # Market regime filter: only enter when regime_ticker > its EMA
        if self.regime_ticker and self.regime_ticker in data:
            reg_close = data[self.regime_ticker]["Close"]
            reg_ema   = ema(reg_close, self.ema_trend_period)
            regime_bull = (reg_close > reg_ema).reindex(all_dates, fill_value=False)
        else:
            regime_bull = pd.Series(True, index=all_dates)

        # For each date, rank tickers and assign signals
        scores_df  = pd.DataFrame(ticker_scores, index=all_dates)
        filters_df = pd.DataFrame(ticker_filters, index=all_dates)

        # Initialize signal series
        sig_dict = {t: pd.Series(0, index=all_dates) for t in data}
        in_position = set()

        for i, date in enumerate(all_dates):
            # Only rebalance on schedule
            if i % self.rebalance_days != 0:
                continue

            # When BTC (regime ticker) crosses below its EMA → exit all, no new entries
            if not regime_bull.get(date, True):
                for t in list(in_position):
                    sig_dict[t].loc[date] = -1
                    in_position.discard(t)
                continue

            day_scores   = scores_df.loc[date].dropna()
            day_filters  = filters_df.loc[date]

            # Apply quality filter
            qualified = day_scores[day_filters.reindex(day_scores.index, fill_value=False)]
            top_n_tickers = set(qualified.nlargest(self.top_n).index) if len(qualified) >= 1 else set()

            # Exit positions not in top-N anymore
            for t in list(in_position):
                if t not in top_n_tickers:
                    sig_dict[t].loc[date] = -1  # exit signal
                    in_position.discard(t)

            # Enter new top-N
            for t in top_n_tickers:
                if t not in in_position:
                    sig_dict[t].loc[date] = 1   # entry signal
                    in_position.add(t)

        for ticker in data:
            self.signals[ticker] = sig_dict[ticker]


class DualMomentumStrategy:
    """
    Absolute + Relative momentum filter (Gary Antonacci's Dual Momentum).
    - Absolute momentum: ticker return > risk-free rate (3mo t-bill proxy ~1.5%)
    - Relative momentum: ticker outperforms QQQ/SPY benchmark
    - Enter top-N tickers that pass both filters
    """
    def __init__(self, top_n: int = 3, rebalance_days: int = 21,
                 momentum_period: int = 120, rf_monthly: float = 0.004):
        self.top_n = top_n
        self.rebalance_days = rebalance_days
        self.momentum_period = momentum_period
        self.rf_monthly = rf_monthly
        self.signals: dict = {}

    def prepare(self, data: dict):
        all_dates = sorted(set(d for df in data.values() for d in df.index))

        abs_mom = {}
        rel_mom = {}

        # Use QQQ as benchmark if available
        bench_close = None
        if "QQQ" in data:
            bench_close = data["QQQ"]["Close"]

        for ticker, df in data.items():
            close = df["Close"]
            mom = close.pct_change(self.momentum_period)
            abs_mom[ticker] = mom.reindex(all_dates)
            if bench_close is not None:
                bench_mom = bench_close.pct_change(self.momentum_period).reindex(all_dates)
                rel_mom[ticker] = mom.reindex(all_dates) - bench_mom
            else:
                rel_mom[ticker] = mom.reindex(all_dates)

        abs_df = pd.DataFrame(abs_mom, index=all_dates)
        rel_df = pd.DataFrame(rel_mom, index=all_dates)

        sig_dict = {t: pd.Series(0, index=all_dates) for t in data}
        in_position = set()

        for i, date in enumerate(all_dates):
            if i % self.rebalance_days != 0:
                continue

            # Absolute momentum filter
            abs_row = abs_df.loc[date].dropna()
            rf_total = (1 + self.rf_monthly) ** (self.momentum_period / 21) - 1
            pass_abs = abs_row[abs_row > rf_total]

            if len(pass_abs) == 0:
                for t in list(in_position):
                    sig_dict[t].loc[date] = -1
                    in_position.discard(t)
                continue

            # Relative momentum rank among passing tickers
            rel_row = rel_df.loc[date].reindex(pass_abs.index).dropna()
            top_n_tickers = set(rel_row.nlargest(self.top_n).index)

            for t in list(in_position):
                if t not in top_n_tickers:
                    sig_dict[t].loc[date] = -1
                    in_position.discard(t)

            for t in top_n_tickers:
                if t not in in_position:
                    sig_dict[t].loc[date] = 1
                    in_position.add(t)

        for ticker in data:
            self.signals[ticker] = sig_dict[ticker]


class HybridMomentumStrategy:
    """
    Combines technical breakout entry with RS momentum ranking.
    - RS Momentum selects top-N candidates
    - Breakout conditions (Donchian + ADX) confirm entry timing
    - Trailing ATR stop for exits
    """
    def __init__(self, top_n: int = 2, rebalance_days: int = 5,
                 dc_period: int = 15, adx_min: float = 25.0,
                 rsi_lo: float = 50.0, vol_mult: float = 1.0):
        self.top_n = top_n
        self.rebalance_days = rebalance_days
        self.dc_period = dc_period
        self.adx_min = adx_min
        self.rsi_lo = rsi_lo
        self.vol_mult = vol_mult
        self.signals: dict = {}

    def prepare(self, data: dict):
        all_dates = sorted(set(d for df in data.values() for d in df.index))

        # Compute RS scores
        rs_scores = {}
        tech_entry = {}
        tech_exit  = {}

        for ticker, df in data.items():
            c, h, l, v = df["Close"], df["High"], df["Low"], df["Volume"]
            ret20  = c.pct_change(20)
            ret60  = c.pct_change(60)
            ret120 = c.pct_change(120)
            score  = 0.5 * ret20 + 0.3 * ret60 + 0.2 * ret120
            rs_scores[ticker] = score.reindex(all_dates)

            dc_upper = h.rolling(self.dc_period).max().shift(1)
            dc_exit  = l.rolling(10).min().shift(1)
            trend50  = ema(c, 50)
            trend200 = ema(c, 200)
            adx_v    = adx(h, l, c, 14)
            rsi_v    = rsi(c, 14)
            avg_v    = v.rolling(20).mean()
            ml, ms, mh = macd(c)

            enter = (
                (c > dc_upper) &
                (c > trend50) & (c > trend200) &
                (adx_v >= self.adx_min) &
                (rsi_v >= self.rsi_lo) & (rsi_v <= 80) &
                (v >= avg_v * self.vol_mult) &
                (ml > ms)
            )
            exit_ = (c < dc_exit) | (rsi_v > 83) | (ml < ms)

            tech_entry[ticker] = enter.reindex(all_dates, fill_value=False)
            tech_exit[ticker]  = exit_.reindex(all_dates, fill_value=False)

        scores_df = pd.DataFrame(rs_scores, index=all_dates)
        sig_dict = {t: pd.Series(0, index=all_dates) for t in data}
        in_position = set()

        for i, date in enumerate(all_dates):
            # Process exits first
            for t in list(in_position):
                if tech_exit[t].get(date, False):
                    sig_dict[t].loc[date] = -1
                    in_position.discard(t)

            # Rebalance: look for new entries
            if i % self.rebalance_days != 0:
                continue
            if len(in_position) >= self.top_n:
                continue

            day_scores = scores_df.loc[date].dropna()
            ranked = day_scores.nlargest(self.top_n * 3)  # top 3× candidates

            for t in ranked.index:
                if len(in_position) >= self.top_n:
                    break
                if t in in_position:
                    continue
                if tech_entry[t].get(date, False):
                    sig_dict[t].loc[date] = 1
                    in_position.add(t)

        for ticker in data:
            self.signals[ticker] = sig_dict[ticker]
