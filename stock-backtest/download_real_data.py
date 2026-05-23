"""
Run this script LOCALLY (not in the Claude sandbox) to download real historical
stock data and save it to stock-backtest/data/.

Requirements: pip install yfinance pandas
Usage:        python3 download_real_data.py

Universe design — deliberately sector-diverse to stress-test survivorship/selection bias:
  Tech leaders    : secular winners, high-vol momentum plays
  Energy          : XOM/CVX/COP crashed 2014-2016 with oil, recovered 2021-2022
                    → tests if EMA(50) filter correctly avoids multi-year downtrends
  Financials      : rate-sensitive, sector-rotation candidates
  Healthcare      : defensive, low-momentum (stress-tests low-ADX filter)
  Retail          : WMT defensive, TGT volatile; sector had multi-year chop
  Industrials     : cyclical, earnings-driven momentum bursts
  Indices/ETFs    : broad market exposure reference + counter-cyclical GLD
"""
import os
import sys

try:
    import yfinance as yf
    import pandas as pd
except ImportError:
    print("Install dependencies: pip install yfinance pandas")
    sys.exit(1)

# --- Universe: sector-diverse, includes secular winners AND underperformers ---
TICKERS = [
    # Tech leaders (high CAGR, high-vol momentum)
    "NVDA", "AMD", "AAPL", "MSFT", "META", "GOOGL", "TSLA", "AMZN",
    "SMCI", "AVGO", "PLTR",
    # Energy — crashed 2014-2016, boomed 2021-2022 (genuine cyclical stress test)
    "XOM", "CVX", "COP", "SLB", "XLE",
    # Financials — rate-sensitive, different momentum profile than tech
    "JPM", "BAC", "GS", "V",
    # Healthcare — defensive, low-momentum (tests ADX filter efficacy)
    "JNJ", "PFE", "UNH",
    # Retail — WMT defensive, TGT volatile; tests sector chop
    "WMT", "TGT",
    # Industrials — cyclical, earnings-driven bursts
    "CAT", "BA",
    # Indices and sector ETFs (benchmarks + counter-cyclical GLD)
    "QQQ", "SPY", "GLD", "XLK", "XLE",
]

START = "2015-01-01"   # wider window: includes energy crash 2015-2016
END   = "2025-05-01"

OUT_DIR = os.path.join(os.path.dirname(__file__), "data")


def download(ticker: str, start: str, end: str) -> pd.DataFrame:
    t = yf.Ticker(ticker)
    df = t.history(start=start, end=end, interval="1d", auto_adjust=True)
    if df.empty:
        return df
    df.index = pd.to_datetime(df.index)
    if df.index.tz is not None:
        df.index = df.index.tz_localize(None)
    df = df[["Open", "High", "Low", "Close", "Volume"]].copy()
    df.dropna(inplace=True)
    df.index.name = "Date"
    return df


def main():
    os.makedirs(OUT_DIR, exist_ok=True)
    print(f"Downloading {len(TICKERS)} tickers ({START} → {END})...\n")

    success, failed = [], []
    for ticker in TICKERS:
        try:
            df = download(ticker, START, END)
            if len(df) < 100:
                raise ValueError(f"Only {len(df)} rows — skipping")
            path = os.path.join(OUT_DIR, f"{ticker}.csv")
            df.to_csv(path)
            print(f"  ✓ {ticker:6s}  {len(df)} rows  → {path}")
            success.append(ticker)
        except Exception as e:
            print(f"  ✗ {ticker:6s}  FAILED: {e}")
            failed.append(ticker)

    print(f"\nDone: {len(success)} OK, {len(failed)} failed")
    if failed:
        print(f"Failed: {failed}")
    print(f"\nNow commit the data/ folder and push:")
    print(f"  git add stock-backtest/data/ && git commit -m 'Add real OHLCV data' && git push")


if __name__ == "__main__":
    main()
