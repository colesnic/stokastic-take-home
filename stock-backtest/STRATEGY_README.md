# Crypto Momentum Strategy — Plain-English Guide

## What This Strategy Does

This strategy tries to buy a basket of major cryptocurrencies when the market is in a healthy, growing phase and stay out when it isn't. It uses three signals — one based on price, two based on on-chain network data — to decide when conditions are good enough to enter. When those conditions turn negative, it exits. The goal is to ride bull market legs while avoiding the worst drawdowns.

It's a slow, patient strategy. It doesn't trade often. Over four years of backtesting it made 18 trades, which averages to about four or five per year. You check it once a day, it takes about five minutes, and then you leave it alone.

---

## The Three Entry Signals

All three signals must be true at the same time before the strategy buys anything.

**Signal 1 — Bitcoin's price trend.** Bitcoin's current price needs to be above its 100-day exponential moving average. This is the broad market trend filter. If BTC is below that line, the strategy stays in cash regardless of what the other signals say. Think of it as: "is the market generally going up over the past few months?"

**Signal 2 — Bitcoin network activity.** This uses the number of unique Bitcoin addresses that are active each day. Specifically, it computes two moving averages of that number — a 30-day and a 90-day. When the shorter one is above the longer one, it means network usage is growing, not shrinking. More people actually using the Bitcoin network tends to precede price appreciation.

**Signal 3 — Ethereum gas demand.** This uses Ethereum's average gas price — essentially the fee people pay to do things on Ethereum (swaps, lending, NFTs, anything DeFi-related). Same approach: 30-day moving average above the 90-day moving average means on-chain demand is accelerating. When people are willing to pay higher fees, it's a sign real economic activity is happening on-chain.

---

## What You Buy

When all three signals are green, you buy five coins in equal 20% allocations: BTC, ETH, BNB, ADA, and XRP. No overweighting, no picking favorites. Each coin gets the same slice.

---

## When You Sell

You exit the full position when any one of the three signals flips bearish. However, there's a minimum holding period of 30 days — if you've been in for less than a month, you wait until the 30 days are up before exiting. This prevents getting whipsawed in and out during choppy sideways periods.

---

## The Stop-Loss

If the portfolio falls 25% from its recent peak, everything is sold immediately. No waiting for signals, no exceptions. This is the circuit breaker that limits catastrophic losses.

---

## Results

Backtested over four years (roughly 2020–2024), with realistic assumptions for trading fees and short-term capital gains taxes:

- Monthly return: +4.31% average
- Sharpe ratio: 0.84 (risk-adjusted return)
- Max drawdown: -29.6%
- Win rate: 83% of trades were profitable
- 18 total trades
- $1,000 invested grew to approximately $4,730

If held in a tax-advantaged account like a Roth IRA (where gains aren't taxed annually), the Sharpe ratio improves to 1.002, which is meaningfully better.

---

## Data You Need

Two free daily CSV files from Coinmetrics' public GitHub: btc.csv and eth.csv. These contain Bitcoin's active address counts and Ethereum's average gas prices going back years. No paid data subscription required.

---

## How Often You Check It

Once per day. The script runs in under five minutes. Most days nothing changes and you do nothing.

---

## The Honest Risks

Three things you should think hard about before using this strategy with real money.

**Thin sample size.** Eighteen trades over four years is not a lot of data. With that few observations, it's hard to know with statistical confidence whether the edge is real or just lucky. A strategy needs hundreds of trades before you can be truly confident the backtest isn't a coincidence.

**The 2021 BNB trade.** One trade — BNB in 2021 — returned roughly 770%. That single trade accounts for a large portion of the total profits. If you remove it, the results look much more modest. The question worth asking is: was that a structural opportunity that will repeat, or was it a once-in-a-cycle event tied to the Binance Smart Chain boom? Strategies that depend heavily on one outlier trade are fragile.

**The gas signal changed in August 2021.** Ethereum implemented a major upgrade called EIP-1559 that fundamentally changed how gas fees are calculated and burned. Before that date, average gas price was a clean measure of demand. After it, the number means something slightly different. The signal may still work, but it hasn't been the same measurement throughout the entire backtest period.

---

## Who This Is For

This strategy works best in a tax-advantaged account — a Roth IRA, a self-directed IRA, or an offshore account where you're not paying taxes on each trade. The tax drag matters: the difference between a Sharpe of 0.84 and 1.002 is entirely the tax treatment.

Minimum capital: $1,000, though more gives you room to handle fees proportionally better.

Temperament: you need to be genuinely comfortable sitting in cash for months at a time while crypto markets are moving. The strategy will keep you on the sidelines during conditions it doesn't trust. If that feels unbearable, this approach isn't a good fit.
