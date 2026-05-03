# Kalshi NBA Game Markets

A project that compares Kalshi's NBA game-winner prices to sportsbook moneylines and tests whether the gap between them is a tradeable signal.

The core idea: Kalshi runs prediction markets where you buy YES or NO on a team to win a game. Sportsbooks (DraftKings, FanDuel) price the same outcomes through moneylines. If you convert the moneyline to an implied probability and compare it to the Kalshi price in cents, you can see when the two markets disagree. That gap is what I'm measuring.

The full writeup with charts and findings is in [findings/writeup.md](findings/writeup.md).

---

## Setup

```bash
python3 -m venv .venv
source .venv/bin/activate
pip install requests pandas matplotlib seaborn cryptography python-dotenv scipy
```

Make a `.env` file in the project root:

```
KALSHI_DEMO_API_KEY=<your-sandbox-key>
KALSHI_REAL_API_KEY=<your-live-read-only-key>   # optional, only for live paper trading
ODDS_API_KEY=<your-odds-api-key>
```

Add the RSA key files:
- `rsa_private_key.pem` — for the Kalshi sandbox
- `live_rsa_private_key.pem` — for live (read-only) production access, if you want it

---

## How to run

There are three things you can run, in order.

### 1. Build the dataset

```bash
python src/fetch_full_dataset.py
```

Pulls every finalized `KXNBAGAME` market from Kalshi, then for each game looks up the historical sportsbook moneyline at T-2h before tipoff via The-Odds-API. Joins them and writes `data/full_dataset.csv` (about 456 rows). Takes around 5 minutes the first time because of API rate limits. Odds responses are cached in `data/odds_cache.json` so re-runs are fast.

### 2. Run the backtest

```bash
python src/backtest.py
```

Reads the dataset, applies filters (liquidity floor, removes near-settled prices), and tests a gap-fading strategy at an 8% threshold across three execution scenarios. Outputs charts and a summary into `findings/`.

### 3. Run the paper trader

```bash
KALSHI_ENV=live python src/paper_trade.py             # continuous loop, 5-min poll
KALSHI_ENV=live python src/paper_trade.py --once      # single scan
KALSHI_ENV=live python src/paper_trade.py --status    # show current positions and P&L
```

This polls real Kalshi production prices and tracks trades locally against a $1,000 virtual bankroll. No real orders get placed. Drop the `KALSHI_ENV=live` flag to use the sandbox instead.

---

## Project layout

```
src/
  kalshi_client.py        Auth + endpoints. KALSHI_ENV picks demo vs live.
  odds_client.py          The-Odds-API wrapper + American-to-probability conversion.
  fetch_full_dataset.py   Builds the joined Kalshi + sportsbook dataset.
  backtest.py             Strategy backtest with three execution models.
  paper_trade.py          Live polling daemon, virtual bankroll.

data/
  full_dataset.csv        The 456-row joined dataset.
  paper_trades.csv        Paper trade log.
  paper_trade_state.json  Open positions and current bankroll.
  odds_cache.json         Cached sportsbook responses.

findings/
  writeup.md              Full writeup.
  backtest_results.md     Backtest summary table.
  *.png                   Charts.
```

---

## What I focused on

`KXNBAGAME` markets specifically — these are the simplest and most liquid NBA markets on Kalshi. Binary, settle clean, lots of history to work with.

The hypothesis I started with: maybe Kalshi lags sportsbooks when the line moves. That turned out to need much higher-frequency data than I had, so I pivoted to the cross-sectional question — across many games, is there a directional gap between Kalshi and sportsbooks, and if so does it depend on how lopsided the game is?

The answer is yes, in a really clean way: Kalshi systematically overprices underdogs and underprices favorites. The full pattern, magnitudes, and a backtest of the obvious trading strategy are in the writeup.

---

## What I cut / would do next

Things I left for later:

- **Sharper sportsbook baseline.** I'm using DraftKings/FanDuel because that's what The-Odds-API gives me. Pinnacle would be sharper.
- **Real intraday data.** Sandbox doesn't expose order book depth historically, so I used total volume as a liquidity proxy. A live strategy needs the actual book.
- **The lag hypothesis.** Couldn't test it directly because I didn't have synced minute-resolution data on both sides.
- **Other NBA markets.** Same favorite-longshot test on point-spread and totals markets would be a good follow-up.

---

## Notes for the reviewer

A few honest disclaimers:

- I went over the 3-5 hour budget. The data alignment alone took longer than I expected (ticker matching across two team-naming conventions is annoying), and once I had a clean dataset I wanted to actually trade the signal, which led to the live paper trader. The core analysis and backtest is what's load-bearing for the spec; the paper trader is bonus.
- The backtest's out-of-sample ROI is +0.8%, not +14.7%. The +14.7% is the in-sample number. I'm being explicit about this in the writeup because the difference matters.
