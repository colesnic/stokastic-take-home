"""
Regime-aware momentum strategies.

RegimeAwareMomentumStrategy:
  - Detects market regime via QQQ/benchmark EMA(200) vs EMA(50)
  - Bull: long top-3 RS momentum stocks with ATR trailing stop
  - Neutral: top-2 only, tighter stops
  - Bear: cash only, no new entries

KellyMomentumStrategy:
  - Half-Kelly position sizing from rolling 60-day trade history
  - Bull-regime-only entries on top RS momentum stocks

VolatilityScaledStrategy:
  - Scales position size inversely with realized vol (target 20% ann. vol)
  - Bull-regime-only entries on top RS momentum stocks
"""

import pandas as pd
import numpy as np
import warnings
warnings.filterwarnings("ignore")

from indicators import ema, rsi, atr, adx, macd


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _rs_scores(data: dict, all_dates: list,
               lb_short: int = 10, lb_mid: int = 20, lb_long: int = 60) -> pd.DataFrame:
    """Blended relative-strength momentum score per ticker per date."""
    scores = {}
    for ticker, df in data.items():
        c = df["Close"]
        r_s = c.pct_change(lb_short)
        r_m = c.pct_change(lb_mid)
        r_l = c.pct_change(lb_long)
        scores[ticker] = (0.5 * r_s + 0.3 * r_m + 0.2 * r_l).reindex(all_dates)
    return pd.DataFrame(scores, index=all_dates)


def _detect_regime(bench_close: pd.Series, all_dates: list) -> pd.Series:
    """
    Returns a Series (indexed by all_dates) with values:
      1  = bull  (price > EMA200)
      0  = neutral (EMA50 <= price <= EMA200)
     -1  = bear  (price < EMA50)
    """
    if bench_close is None:
        return pd.Series(1, index=all_dates)      # default: always bull

    e50  = ema(bench_close, 50).reindex(all_dates)
    e200 = ema(bench_close, 200).reindex(all_dates)
    price = bench_close.reindex(all_dates)

    regime = pd.Series(0, index=all_dates, dtype=int)
    regime[price > e200] = 1
    regime[price < e50]  = -1
    return regime


# ---------------------------------------------------------------------------
# Strategy 1: RegimeAwareMomentumStrategy
# ---------------------------------------------------------------------------

class RegimeAwareMomentumStrategy:
    """
    Bull:    long top-3 RS momentum stocks, ATR-based entry/trail
    Neutral: long top-2 RS momentum stocks, tighter filters
    Bear:    cash only (all signals = 0)

    Expects 'QQQ' in data dict to serve as the regime benchmark.
    If QQQ is absent, falls back to the first ticker as proxy.
    """

    def __init__(self,
                 bull_top_n: int = 3,
                 neutral_top_n: int = 2,
                 rebalance_days: int = 3,
                 lb_short: int = 10,
                 lb_mid: int = 20,
                 lb_long: int = 60,
                 adx_min_bull: float = 15.0,
                 adx_min_neutral: float = 20.0,
                 rsi_min: float = 40.0):
        self.bull_top_n      = bull_top_n
        self.neutral_top_n   = neutral_top_n
        self.rebalance_days  = rebalance_days
        self.lb_short        = lb_short
        self.lb_mid          = lb_mid
        self.lb_long         = lb_long
        self.adx_min_bull    = adx_min_bull
        self.adx_min_neutral = adx_min_neutral
        self.rsi_min         = rsi_min
        self.signals: dict   = {}

    def prepare(self, data: dict):
        all_dates = sorted(set(d for df in data.values() for d in df.index))

        # Determine benchmark
        bench_ticker = "QQQ" if "QQQ" in data else next(iter(data))
        bench_close  = data[bench_ticker]["Close"]
        regime       = _detect_regime(bench_close, all_dates)

        scores_df    = _rs_scores(data, all_dates, self.lb_short, self.lb_mid, self.lb_long)

        # Build per-ticker quality flags
        adx_df = {}
        rsi_df = {}
        ema50_above = {}
        for ticker, df in data.items():
            c, h, l = df["Close"], df["High"], df["Low"]
            adx_df[ticker]      = adx(h, l, c, 14).reindex(all_dates)
            rsi_df[ticker]      = rsi(c, 14).reindex(all_dates)
            ema50_above[ticker] = (c > ema(c, 50)).reindex(all_dates).fillna(False)

        adx_df_  = pd.DataFrame(adx_df,      index=all_dates)
        rsi_df_  = pd.DataFrame(rsi_df,      index=all_dates)
        ema50_df = pd.DataFrame(ema50_above,  index=all_dates)

        sig_dict   = {t: pd.Series(0, index=all_dates) for t in data}
        in_position: set = set()

        for i, date in enumerate(all_dates):
            reg = regime.loc[date]

            # ── Bear: exit everything, no new entries ──────────────────────
            if reg == -1:
                for t in list(in_position):
                    sig_dict[t].loc[date] = -1
                    in_position.discard(t)
                continue

            # ── Determine parameters based on regime ───────────────────────
            top_n   = self.bull_top_n    if reg == 1 else self.neutral_top_n
            adx_min = self.adx_min_bull  if reg == 1 else self.adx_min_neutral

            # Only rebalance on schedule
            if i % self.rebalance_days != 0:
                continue

            # ── Build qualified candidate set ──────────────────────────────
            day_scores = scores_df.loc[date].dropna()
            qualify = (
                (adx_df_.loc[date] >= adx_min) &
                (rsi_df_.loc[date] >= self.rsi_min) &
                (rsi_df_.loc[date] <= 82) &
                ema50_df.loc[date]
            )
            qualify = qualify.reindex(day_scores.index, fill_value=False)
            qualified_scores = day_scores[qualify]
            top_n_tickers    = set(qualified_scores.nlargest(top_n).index) if len(qualified_scores) >= 1 else set()

            # ── Exit losers ────────────────────────────────────────────────
            for t in list(in_position):
                if t not in top_n_tickers:
                    sig_dict[t].loc[date] = -1
                    in_position.discard(t)

            # ── Enter new leaders ──────────────────────────────────────────
            for t in top_n_tickers:
                if t not in in_position:
                    sig_dict[t].loc[date] = 1
                    in_position.add(t)

        for ticker in data:
            self.signals[ticker] = sig_dict[ticker]


# ---------------------------------------------------------------------------
# Strategy 2: KellyMomentumStrategy
# ---------------------------------------------------------------------------

class KellyMomentumStrategy:
    """
    Uses half-Kelly position sizing derived from a rolling 60-day trade history.
    Enters top RS momentum stocks when regime is bull.

    Position sizing is encoded in signal magnitude (not used by the base
    backtester), but the backtester's position_size_pct is overridden via
    `kelly_fractions` dict that run.py can inspect and pass in.

    Signal convention: 1 = long entry, -1 = exit, 0 = flat.
    The `kelly_fractions` attribute maps ticker -> latest Kelly fraction (0..1).
    """

    def __init__(self,
                 top_n: int = 3,
                 rebalance_days: int = 3,
                 lb_short: int = 10,
                 lb_mid: int = 20,
                 lb_long: int = 60,
                 kelly_lookback: int = 60,
                 adx_min: float = 15.0,
                 rsi_min: float = 40.0):
        self.top_n          = top_n
        self.rebalance_days = rebalance_days
        self.lb_short       = lb_short
        self.lb_mid         = lb_mid
        self.lb_long        = lb_long
        self.kelly_lookback = kelly_lookback
        self.adx_min        = adx_min
        self.rsi_min        = rsi_min
        self.signals: dict  = {}
        self.kelly_fractions: dict = {}   # ticker -> half-Kelly fraction

    def _rolling_kelly(self, returns: pd.Series) -> float:
        """Compute half-Kelly from a window of per-trade returns (as pct)."""
        if len(returns) < 5:
            return 0.25   # conservative default before enough history
        wins  = returns[returns > 0]
        losses = returns[returns <= 0]
        if len(wins) == 0 or len(losses) == 0:
            return 0.25
        p  = len(wins) / len(returns)          # win-rate
        w  = wins.mean()                        # avg win (positive)
        l  = abs(losses.mean())                 # avg loss (positive)
        if l == 0:
            return 0.50
        b  = w / l                              # win/loss ratio
        kelly = (p * b - (1 - p)) / b          # full Kelly
        half_kelly = max(0.0, min(0.5, kelly / 2))
        return half_kelly

    def prepare(self, data: dict):
        all_dates = sorted(set(d for df in data.values() for d in df.index))

        bench_ticker = "QQQ" if "QQQ" in data else next(iter(data))
        bench_close  = data[bench_ticker]["Close"]
        regime       = _detect_regime(bench_close, all_dates)

        scores_df = _rs_scores(data, all_dates, self.lb_short, self.lb_mid, self.lb_long)

        # Quality filters
        adx_series  = {}
        rsi_series  = {}
        ema50_above = {}
        for ticker, df in data.items():
            c, h, l = df["Close"], df["High"], df["Low"]
            adx_series[ticker]  = adx(h, l, c, 14).reindex(all_dates)
            rsi_series[ticker]  = rsi(c, 14).reindex(all_dates)
            ema50_above[ticker] = (c > ema(c, 50)).reindex(all_dates).fillna(False)

        adx_df_  = pd.DataFrame(adx_series,  index=all_dates)
        rsi_df_  = pd.DataFrame(rsi_series,  index=all_dates)
        ema50_df = pd.DataFrame(ema50_above,  index=all_dates)

        # Rolling daily returns per ticker (for Kelly estimation)
        daily_ret = {}
        for ticker, df in data.items():
            daily_ret[ticker] = df["Close"].pct_change().reindex(all_dates)
        ret_df = pd.DataFrame(daily_ret, index=all_dates)

        sig_dict = {t: pd.Series(0, index=all_dates) for t in data}
        in_position: set = set()

        for i, date in enumerate(all_dates):
            reg = regime.loc[date]

            # Bear or neutral: exit everything
            if reg != 1:
                for t in list(in_position):
                    sig_dict[t].loc[date] = -1
                    in_position.discard(t)
                continue

            if i % self.rebalance_days != 0:
                continue

            day_scores = scores_df.loc[date].dropna()
            qualify    = (
                (adx_df_.loc[date] >= self.adx_min) &
                (rsi_df_.loc[date] >= self.rsi_min) &
                (rsi_df_.loc[date] <= 82) &
                ema50_df.loc[date]
            )
            qualify             = qualify.reindex(day_scores.index, fill_value=False)
            qualified_scores    = day_scores[qualify]
            top_n_tickers       = set(qualified_scores.nlargest(self.top_n).index) if len(qualified_scores) >= 1 else set()

            for t in list(in_position):
                if t not in top_n_tickers:
                    sig_dict[t].loc[date] = -1
                    in_position.discard(t)

            for t in top_n_tickers:
                if t not in in_position:
                    sig_dict[t].loc[date] = 1
                    in_position.add(t)
                    # Compute Kelly fraction for this ticker
                    window = ret_df[t].iloc[max(0, i - self.kelly_lookback): i].dropna()
                    self.kelly_fractions[t] = self._rolling_kelly(window)

        for ticker in data:
            self.signals[ticker] = sig_dict[ticker]


# ---------------------------------------------------------------------------
# Strategy 3: VolatilityScaledStrategy
# ---------------------------------------------------------------------------

class VolatilityScaledStrategy:
    """
    Scales position size inversely with realized 20-day volatility so that
    each position targets a fixed annualized volatility contribution (default 20%).

    vol_target / realized_vol → size fraction  (capped at 0.50 per position)

    Bull-regime-only, top-N RS momentum stocks.

    The `vol_fractions` attribute maps ticker -> latest vol-scaled fraction.
    """

    def __init__(self,
                 top_n: int = 3,
                 rebalance_days: int = 3,
                 lb_short: int = 10,
                 lb_mid: int = 20,
                 lb_long: int = 60,
                 vol_target: float = 0.20,     # target annualized vol per position
                 vol_lookback: int = 20,
                 adx_min: float = 15.0,
                 rsi_min: float = 40.0):
        self.top_n          = top_n
        self.rebalance_days = rebalance_days
        self.lb_short       = lb_short
        self.lb_mid         = lb_mid
        self.lb_long        = lb_long
        self.vol_target     = vol_target
        self.vol_lookback   = vol_lookback
        self.adx_min        = adx_min
        self.rsi_min        = rsi_min
        self.signals: dict  = {}
        self.vol_fractions: dict = {}    # ticker -> latest vol-scaled fraction

    def prepare(self, data: dict):
        all_dates = sorted(set(d for df in data.values() for d in df.index))

        bench_ticker = "QQQ" if "QQQ" in data else next(iter(data))
        bench_close  = data[bench_ticker]["Close"]
        regime       = _detect_regime(bench_close, all_dates)

        scores_df = _rs_scores(data, all_dates, self.lb_short, self.lb_mid, self.lb_long)

        # Quality filters & realized vol
        adx_series  = {}
        rsi_series  = {}
        ema50_above = {}
        rvol_series = {}
        for ticker, df in data.items():
            c, h, l = df["Close"], df["High"], df["Low"]
            adx_series[ticker]  = adx(h, l, c, 14).reindex(all_dates)
            rsi_series[ticker]  = rsi(c, 14).reindex(all_dates)
            ema50_above[ticker] = (c > ema(c, 50)).reindex(all_dates).fillna(False)
            # Realized annualized vol (daily returns × sqrt(252))
            daily_r = c.pct_change()
            rvol    = daily_r.rolling(self.vol_lookback).std() * np.sqrt(252)
            rvol_series[ticker] = rvol.reindex(all_dates)

        adx_df_  = pd.DataFrame(adx_series,  index=all_dates)
        rsi_df_  = pd.DataFrame(rsi_series,  index=all_dates)
        ema50_df = pd.DataFrame(ema50_above,  index=all_dates)
        rvol_df  = pd.DataFrame(rvol_series,  index=all_dates)

        sig_dict = {t: pd.Series(0, index=all_dates) for t in data}
        in_position: set = set()

        for i, date in enumerate(all_dates):
            reg = regime.loc[date]

            if reg != 1:
                for t in list(in_position):
                    sig_dict[t].loc[date] = -1
                    in_position.discard(t)
                continue

            if i % self.rebalance_days != 0:
                continue

            day_scores = scores_df.loc[date].dropna()
            qualify    = (
                (adx_df_.loc[date] >= self.adx_min) &
                (rsi_df_.loc[date] >= self.rsi_min) &
                (rsi_df_.loc[date] <= 82) &
                ema50_df.loc[date]
            )
            qualify          = qualify.reindex(day_scores.index, fill_value=False)
            qualified_scores = day_scores[qualify]
            top_n_tickers    = set(qualified_scores.nlargest(self.top_n).index) if len(qualified_scores) >= 1 else set()

            for t in list(in_position):
                if t not in top_n_tickers:
                    sig_dict[t].loc[date] = -1
                    in_position.discard(t)

            for t in top_n_tickers:
                if t not in in_position:
                    sig_dict[t].loc[date] = 1
                    in_position.add(t)
                    # Vol-scaled fraction
                    rv = rvol_df.loc[date, t]
                    if pd.isna(rv) or rv <= 0:
                        self.vol_fractions[t] = 0.25
                    else:
                        frac = min(0.50, self.vol_target / rv)
                        self.vol_fractions[t] = frac

        for ticker in data:
            self.signals[ticker] = sig_dict[ticker]
