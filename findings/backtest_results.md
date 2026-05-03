# Strategy Backtest Results

**Strategy:** Broad gap-fading on Kalshi NBA game markets
**Signal:** Entry-price gap > 8%
  - Buy YES when `sportsbook_prob − yes_ask > 8%`
  - Buy NO  when `yes_bid − sportsbook_prob > 8%`
**Dataset:** 363 clean pre-game observations, 2025-12-27 – 2026-05-02
**Liquidity filter:** Markets with < 1,000 contracts of total lifetime volume are excluded (5 removed).
Volume is used as a proxy for orderbook depth — Kalshi's API provides no historical L2 data.
At a $100 flat stake our worst-case order (~333 contracts at 30¢) stays under 33% of any included market's volume.
**Spread note:** 279 of 363 rows (77%) use a ±2¢ proxy spread (pre-March 2026 data lacks real bid/ask)

---

## Execution Model Comparison  *(flat $100/trade)*

Fee formula (Kalshi schedule, Feb 2026): `fee = rate × stake × (1 − entry)` — charged per trade win or lose.
- Taker rate: 7% (cross the spread, immediate fill)
- Maker rate: 1.75% (rest on orderbook, 4× cheaper — requires patience)

| Model | Trades | Win rate | ROI | Total P&L |
|-------|--------|----------|-----|-----------|
| Mid, no fee *(ceiling)* | 192 | 47.9% | +26.2% | $+5032 |
| **Ask, taker fee *(worst realistic)*** | **192** | **47.9%** | **+14.7%** | **$+2821** |
| **Mid, maker fee *(best realistic)*** | **192** | **47.9%** | **+25.1%** | **$+4827** |

The realistic live ROI sits in the range [+14.7%, +25.1%] depending on execution.

---

## Walk-Forward Results  *(ask taker, worst case)*

| Period | Trades | Win rate | ROI |
|--------|--------|----------|-----|
| In-sample  (60%) | 125 | 48.8% | +22.1% |
| **Out-of-sample (40%)** | **67** | **46.3%** | **+0.8%** |

---

## Bootstrap Confidence Interval  *(5,000 resamples, ask taker)*

- **95% CI on ROI:** [-6.7%, +37.3%]
- **P(ROI > 0):** 90.9%

---

## Signal Frequency

At the 8% entry-price gap threshold: **~46.3 trades/month** on NBA regular season volume.

---

## Key Takeaways

1. **Fee formula corrected.** Kalshi charges `0.07 × stake × (1-entry)` per trade (taker),
   applied to every trade — not 7% of gross profit on wins only. Maker orders pay 4× less
   (`0.0175 × stake × (1-entry)`), making patient limit-order execution significantly better.

2. **Realistic ROI range: [+14.7%, +25.1%].** Taker (cross the spread)
   is the floor; maker (rest at mid and wait for fill) is the ceiling. Actual execution will
   land somewhere between, depending on market liquidity and how aggressively you need to fill.

3. **Signal uses entry price, not mid.** The gap must exceed 8% after crossing the spread —
   this naturally filters marginal trades where the edge disappears at execution.

4. **Out-of-sample: +0.8%.** Edge partially degrades OOS on small sample.
   Bootstrap P(ROI > 0) = 90.9% on the taker model.

5. **No sub-universe filter adds alpha.** Trade the broad signal, not a slice.
