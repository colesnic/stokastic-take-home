"""
SharpeOptimizedStrategy — institutional-grade momentum with three key fixes:

1. SPY Regime Gate
   Bull  (SPY > EMA200): enter top-N, full size
   Neutral (EMA100 < SPY <= EMA200): hold existing, no new entries
   Bear  (SPY <= EMA100): exit everything, stay cash

2. Skip-last-month momentum (Jegadeesh-Titman classic)
   Score = return[t-120 : t-20]  (skip the most-recent 20 trading days)
   This avoids 1-month reversal while capturing 6-month momentum.

3. Individual stock quality gate
   price > EMA100  AND  ADX > 20  AND  42 < RSI < 76

These three changes convert a 0.93 OOS Sharpe to a target of >1.0
by reducing trades during poor-regime periods.
"""

import pandas as pd
import numpy as np
import warnings
warnings.filterwarnings("ignore")

from indicators import ema, rsi, atr, adx


# ─────────────────────────────────────────────────────────────────────────────
# SharpeOptimizedStrategy
# ─────────────────────────────────────────────────────────────────────────────

class SharpeOptimizedStrategy:
    """
    The academically-grounded momentum rotation with regime gate.
    """

    def __init__(self,
                 top_n: int = 3,
                 rebalance_days: int = 5,
                 lb_mom: int = 120,        # total momentum lookback
                 skip_days: int = 20,      # skip most-recent N days
                 adx_min: float = 20.0,
                 rsi_lo: float = 42.0,
                 rsi_hi: float = 76.0,
                 bench_ticker: str = "SPY"):
        self.top_n         = top_n
        self.rebalance_days = rebalance_days
        self.lb_mom        = lb_mom
        self.skip_days     = skip_days
        self.adx_min       = adx_min
        self.rsi_lo        = rsi_lo
        self.rsi_hi        = rsi_hi
        self.bench_ticker  = bench_ticker
        self.signals: dict = {}

    def prepare(self, data: dict):
        all_dates = sorted(set(d for df in data.values() for d in df.index))

        # ── Regime via SPY / first ticker ──────────────────────────────────
        bench_close = None
        if self.bench_ticker in data:
            bench_close = data[self.bench_ticker]["Close"]
        elif "QQQ" in data:
            bench_close = data["QQQ"]["Close"]
        else:
            bench_close = next(iter(data.values()))["Close"]

        e100 = ema(bench_close, 100).reindex(all_dates)
        e200 = ema(bench_close, 200).reindex(all_dates)
        bp   = bench_close.reindex(all_dates)

        regime = pd.Series(0, index=all_dates, dtype=int)
        regime[bp > e200] = 1           # bull
        regime[(bp > e100) & (bp <= e200)] = 0   # neutral
        regime[bp <= e100] = -1         # bear

        # ── Per-ticker scores and filters ──────────────────────────────────
        tradeable = {k: v for k, v in data.items() if k != self.bench_ticker and k != "QQQ"}

        scores_raw = {}
        adx_s      = {}
        rsi_s      = {}
        ema100_ok  = {}

        for ticker, df in tradeable.items():
            c, h, l = df["Close"], df["High"], df["Low"]

            # Skip-last-month momentum: return from skip_days to lb_mom ago
            skip_price  = c.shift(self.skip_days)
            lb_price    = c.shift(self.lb_mom)
            mom_score   = (skip_price / lb_price - 1).reindex(all_dates)

            scores_raw[ticker]  = mom_score
            adx_s[ticker]       = adx(h, l, c, 14).reindex(all_dates)
            rsi_s[ticker]       = rsi(c, 14).reindex(all_dates)
            ema100_ok[ticker]   = (c > ema(c, 100)).reindex(all_dates).fillna(False)

        scores_df  = pd.DataFrame(scores_raw, index=all_dates)
        adx_df     = pd.DataFrame(adx_s,      index=all_dates)
        rsi_df     = pd.DataFrame(rsi_s,      index=all_dates)
        ema100_df  = pd.DataFrame(ema100_ok,  index=all_dates)

        sig_dict    = {t: pd.Series(0, index=all_dates) for t in tradeable}
        in_position: set = set()

        for i, date in enumerate(all_dates):
            reg = regime.loc[date]

            # ── Bear: exit everything ──────────────────────────────────────
            if reg == -1:
                for t in list(in_position):
                    sig_dict[t].loc[date] = -1
                    in_position.discard(t)
                continue

            # ── Neutral: hold current, no new entries ──────────────────────
            if reg == 0:
                continue

            # ── Bull: rebalance on schedule ────────────────────────────────
            if i % self.rebalance_days != 0:
                continue

            day_scores = scores_df.loc[date].dropna()
            qualify = (
                (adx_df.loc[date]    >= self.adx_min) &
                (rsi_df.loc[date]    >= self.rsi_lo)  &
                (rsi_df.loc[date]    <= self.rsi_hi)  &
                ema100_df.loc[date]
            )
            qualify = qualify.reindex(day_scores.index, fill_value=False)
            qualified = day_scores[qualify]

            top_tickers = set(qualified.nlargest(self.top_n).index) if len(qualified) >= 1 else set()

            for t in list(in_position):
                if t not in top_tickers:
                    sig_dict[t].loc[date] = -1
                    in_position.discard(t)

            for t in top_tickers:
                if t not in in_position:
                    sig_dict[t].loc[date] = 1
                    in_position.add(t)

        for ticker in tradeable:
            self.signals[ticker] = sig_dict[ticker]

        # Also set empty signals for bench/QQQ tickers (not traded)
        for ticker in data:
            if ticker not in self.signals:
                self.signals[ticker] = pd.Series(0, index=all_dates)


# ─────────────────────────────────────────────────────────────────────────────
# TrendFollowStrategy  — CTA-style, few trades, wide stops
# ─────────────────────────────────────────────────────────────────────────────

class TrendFollowStrategy:
    """
    Donchian channel breakout + EMA trend filter.
    Classic CTA/managed-futures approach with very few parameters.
    - Enter when close > 20-day high (previous day) AND price > EMA50 AND EMA50 > EMA200
    - Exit when price drops below EMA50 (trend break)
    """

    def __init__(self,
                 donchian_period: int = 20,
                 rebalance_days: int = 1,
                 bench_ticker: str = "SPY"):
        self.donchian_period = donchian_period
        self.rebalance_days  = rebalance_days
        self.bench_ticker    = bench_ticker
        self.signals: dict   = {}

    def prepare(self, data: dict):
        all_dates  = sorted(set(d for df in data.values() for d in df.index))
        tradeable  = {k: v for k, v in data.items() if k != self.bench_ticker and k != "QQQ"}

        # Regime via bench
        if self.bench_ticker in data:
            bench_c = data[self.bench_ticker]["Close"]
        else:
            bench_c = next(iter(data.values()))["Close"]

        e200_bench = ema(bench_c, 200).reindex(all_dates)
        bp         = bench_c.reindex(all_dates)
        bull_mkt   = (bp > e200_bench)

        sig_dict = {t: pd.Series(0, index=all_dates) for t in tradeable}

        for ticker, df in tradeable.items():
            c, h = df["Close"], df["High"]
            in_pos = False

            dc_upper = h.rolling(self.donchian_period).max().shift(1)
            e50  = ema(c, 50)
            e200 = ema(c, 200)

            entry = (c > dc_upper) & (c > e50) & (e50 > e200)
            exit_ = (c < e50)

            entry_r = entry.reindex(all_dates, fill_value=False)
            exit_r  = exit_.reindex(all_dates, fill_value=False)
            bull_r  = bull_mkt.reindex(all_dates, fill_value=False)

            for date in all_dates:
                if not bull_r.loc[date]:
                    if in_pos:
                        sig_dict[ticker].loc[date] = -1
                        in_pos = False
                    continue
                if in_pos:
                    if exit_r.loc[date]:
                        sig_dict[ticker].loc[date] = -1
                        in_pos = False
                else:
                    if entry_r.loc[date]:
                        sig_dict[ticker].loc[date] = 1
                        in_pos = True

        for ticker in tradeable:
            self.signals[ticker] = sig_dict[ticker]

        for ticker in data:
            if ticker not in self.signals:
                self.signals[ticker] = pd.Series(0, index=all_dates)
