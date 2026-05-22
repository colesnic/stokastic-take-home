"""
Parameter optimizer: grid-search over strategy/backtester params,
targeting maximum monthly return. Saves best params and runs final backtest.
"""
import sys, os
sys.path.insert(0, os.path.dirname(__file__))

import pandas as pd
import numpy as np
import itertools
import warnings
warnings.filterwarnings("ignore")

from data_fetcher import fetch_multiple
from indicators import ema, rsi, macd, bollinger_bands, atr, adx, donchian, stochastic
from backtester_advanced import AdvancedBacktester
from strategies import MomentumBreakoutStrategy, BollingerMomentumStrategy, TrendFollowingStrategy


TICKERS = [
    "NVDA", "AMD", "AAPL", "MSFT", "META", "GOOGL", "TSLA", "AMZN",
    "SMCI", "ARM", "AVGO", "MRVL", "QQQ", "SOXX", "ARKK", "XLK", "XLY",
    "MRNA", "BIIB", "COIN", "MSTR", "PLTR",
]

BACKTEST_START = "2022-01-01"
BACKTEST_END   = "2024-12-31"
INITIAL_CAPITAL = 100_000


def add_indicators(data: dict) -> dict:
    enriched = {}
    for ticker, df in data.items():
        d = df.copy()
        c, h, l, v = d["Close"], d["High"], d["Low"], d["Volume"]
        d["ema10"]  = ema(c, 10)
        d["ema20"]  = ema(c, 20)
        d["ema50"]  = ema(c, 50)
        d["ema100"] = ema(c, 100)
        d["ema200"] = ema(c, 200)
        d["rsi14"]  = rsi(c, 14)
        d["atr14"]  = atr(h, l, c, 14)
        d["adx14"]  = adx(h, l, c, 14)
        macd_line, sig_line, hist = macd(c)
        d["macd"], d["macd_signal"], d["macd_hist"] = macd_line, sig_line, hist
        d["bb_upper"], d["bb_mid"], d["bb_lower"] = bollinger_bands(c, 20, 2.0)
        d["dc_upper"], d["dc_mid"], d["dc_lower"] = donchian(h, l, 20)
        d["vol_sma20"] = v.rolling(20).mean()
        d.dropna(inplace=True)
        if len(d) > 50:
            enriched[ticker] = d
    return enriched


class HighMomentumStrategy:
    """
    Aggressive momentum strategy optimized for high monthly returns.
    Combines breakout + trend confirmation with tight entry filters.
    """
    def __init__(self, dc_period=20, ema_fast=10, ema_slow=50, ema_trend=200,
                 rsi_lo=45, rsi_hi=75, adx_min=25, vol_mult=1.2, macd_confirm=True):
        self.dc_period   = dc_period
        self.ema_fast    = ema_fast
        self.ema_slow    = ema_slow
        self.ema_trend   = ema_trend
        self.rsi_lo      = rsi_lo
        self.rsi_hi      = rsi_hi
        self.adx_min     = adx_min
        self.vol_mult    = vol_mult
        self.macd_confirm = macd_confirm
        self.signals: dict = {}

    def prepare(self, data: dict):
        for ticker, df in data.items():
            self.signals[ticker] = self.generate_signals(df)

    def generate_signals(self, df: pd.DataFrame) -> pd.Series:
        c, h, l, v = df["Close"], df["High"], df["Low"], df["Volume"]

        dc_upper = h.rolling(self.dc_period).max().shift(1)
        dc_exit  = l.rolling(10).min().shift(1)

        fast  = ema(c, self.ema_fast)
        slow  = ema(c, self.ema_slow)
        trend = ema(c, self.ema_trend)

        rsi_v = df.get("rsi14") if "rsi14" in df else rsi(c, 14)
        adx_v = df.get("adx14") if "adx14" in df else adx(h, l, c, 14)
        avg_v = df.get("vol_sma20") if "vol_sma20" in df else v.rolling(20).mean()

        if isinstance(rsi_v, pd.Series) and rsi_v.dtype == object:
            rsi_v = rsi(c, 14)
        if isinstance(adx_v, pd.Series) and adx_v.dtype == object:
            adx_v = adx(h, l, c, 14)

        macd_l, macd_s, macd_h = macd(c)

        # Entry: breakout above Donchian + trend stack + momentum confirmation
        enter = (
            (c > dc_upper) &                      # breakout above 20-day high
            (fast > slow) &                        # short-term trend up
            (c > trend) &                          # long-term trend up
            (rsi_v >= self.rsi_lo) &
            (rsi_v <= self.rsi_hi) &
            (adx_v >= self.adx_min) &              # strong trend
            (v > avg_v * self.vol_mult)             # volume confirmation
        )
        if self.macd_confirm:
            enter = enter & (macd_l > macd_s)      # MACD bullish

        # Exit: price closes below 10-day low, EMA cross, or RSI extended
        exit_ = (
            (c < dc_exit) |
            (fast < slow) |
            (rsi_v > 82) |
            (macd_l < macd_s)
        )

        signals = pd.Series(0, index=df.index)
        signals[enter] = 1
        signals[exit_]  = -1
        return signals


def grid_search(data: dict, param_grid: dict) -> pd.DataFrame:
    """Run all combinations and return sorted results."""
    keys = list(param_grid.keys())
    values = list(param_grid.values())
    combos = list(itertools.product(*values))
    print(f"  Running {len(combos)} parameter combinations...")

    results = []
    for combo in combos:
        params = dict(zip(keys, combo))
        try:
            strat = HighMomentumStrategy(
                dc_period   = params.get("dc_period", 20),
                ema_fast    = params.get("ema_fast", 10),
                ema_slow    = params.get("ema_slow", 50),
                ema_trend   = params.get("ema_trend", 200),
                rsi_lo      = params.get("rsi_lo", 45),
                rsi_hi      = params.get("rsi_hi", 75),
                adx_min     = params.get("adx_min", 25),
                vol_mult    = params.get("vol_mult", 1.2),
            )
            strat.prepare(data)

            bt = AdvancedBacktester(
                initial_capital     = INITIAL_CAPITAL,
                max_positions       = params.get("max_positions", 3),
                position_size_pct   = params.get("position_size_pct", 0.30),
                atr_stop_multiplier = params.get("atr_stop", 2.5),
                atr_trail_multiplier= params.get("atr_trail", 2.0),
                risk_per_trade_pct  = params.get("risk_pct", 0.02),
            )
            result = bt.run(data, strat)
            m = result.metrics()
            if m:
                row = {**params, **m}
                results.append(row)
        except Exception as e:
            pass

    df = pd.DataFrame(results)
    if len(df) > 0 and "monthly_return_pct" in df.columns:
        df = df.sort_values("monthly_return_pct", ascending=False)
    return df


def main():
    print("\n" + "="*60)
    print("  PARAMETER OPTIMIZER")
    print("="*60)

    print("\n[Loading data]...")
    raw_data = fetch_multiple(TICKERS, BACKTEST_START, BACKTEST_END, "1d")
    data = add_indicators(raw_data)
    print(f"  {len(data)} tickers loaded")

    # Focused grid: ~1000 combinations
    param_grid = {
        "dc_period":        [15, 20, 25],
        "ema_fast":         [8, 10],
        "ema_slow":         [30, 50],
        "ema_trend":        [100, 200],
        "rsi_lo":           [40, 50],
        "rsi_hi":           [72, 78],
        "adx_min":          [20, 25],
        "vol_mult":         [1.0, 1.2],
        "max_positions":    [3, 5],
        "position_size_pct":[0.25, 0.33],
        "atr_stop":         [2.0, 3.0],
        "atr_trail":        [1.5, 2.5],
        "risk_pct":         [0.02],
    }

    results_df = grid_search(data, param_grid)

    if len(results_df) == 0:
        print("[!] No results from grid search")
        return

    print(f"\n  Top 10 parameter sets by monthly return:")
    cols = ["monthly_return_pct", "annualized_return_pct", "sharpe_ratio",
            "max_drawdown_pct", "win_rate_pct", "profit_factor", "n_trades",
            "dc_period", "ema_fast", "ema_slow", "adx_min", "max_positions",
            "position_size_pct", "atr_stop"]
    cols = [c for c in cols if c in results_df.columns]
    print(results_df[cols].head(10).to_string())

    # Save all results
    os.makedirs(os.path.join(os.path.dirname(__file__), "output"), exist_ok=True)
    results_df.to_csv(os.path.join(os.path.dirname(__file__), "output", "optimizer_results.csv"), index=False)
    print(f"\n  [Saved optimizer results]")

    # Run final backtest with best params
    best = results_df.iloc[0].to_dict()
    print(f"\n  [Final backtest with best params]")
    print(f"  Monthly return: {best.get('monthly_return_pct', 0):.2f}%")

    strat = HighMomentumStrategy(
        dc_period   = int(best.get("dc_period", 20)),
        ema_fast    = int(best.get("ema_fast", 10)),
        ema_slow    = int(best.get("ema_slow", 50)),
        ema_trend   = int(best.get("ema_trend", 200)),
        rsi_lo      = int(best.get("rsi_lo", 45)),
        rsi_hi      = int(best.get("rsi_hi", 75)),
        adx_min     = int(best.get("adx_min", 25)),
        vol_mult    = float(best.get("vol_mult", 1.2)),
    )
    strat.prepare(data)

    bt = AdvancedBacktester(
        initial_capital     = INITIAL_CAPITAL,
        max_positions       = int(best.get("max_positions", 3)),
        position_size_pct   = float(best.get("position_size_pct", 0.30)),
        atr_stop_multiplier = float(best.get("atr_stop", 2.5)),
        atr_trail_multiplier= float(best.get("atr_trail", 2.0)),
        risk_per_trade_pct  = float(best.get("risk_pct", 0.02)),
    )
    result = bt.run(data, strat)
    result.print_summary("Optimized HighMomentum")

    trades = result.trades_df
    trades.to_csv(os.path.join(os.path.dirname(__file__), "output", "optimized_trades.csv"), index=False)

    return result, best


if __name__ == "__main__":
    main()
