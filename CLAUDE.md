Index:
- Spec: .claude/docs/spec.md
- Important Kalshi API docs: .claude/docs/kalshi


Plan:

Market: NBA game winner markets on the Kalshi sandbox. Chosen because they have the highest liquidity of anything on the sandbox — real depth, tight spreads, tradeable books.

External signal: The-Odds-API historical data (you have access). Sportsbook moneylines converted to implied probabilities serve as our "fair value" anchor.

Core research question: When sportsbook lines move, does Kalshi lag in repricing? And more broadly — is there a persistent gap between the sharpest sportsbook implied probability and the Kalshi mid-price, and does that gap have a direction or pattern?


Project structure (5-8 hours):

Hour 1-2 — Data alignment. Pull historical odds for NBA games from the-odds-api, pull corresponding Kalshi markets via the sandbox API, and join them by game. The hard part is ticker matching — making sure you're linking the right Kalshi market to the right game.

Hour 3-4 — Core analysis. For each game at each timestamp where both data sources overlap, compute the gap between sportsbook implied prob and Kalshi mid-price. Measure direction, magnitude, and whether it narrows over time as tip-off approaches.

Hour 5-6 — Strategy layer and simulated trade log. If a pattern exists, codify it into a simple rule and generate entry/exit signals with hypothetical P&L.

Hour 7-8 — Writeup, README, charts, polish.
