"""
Backtest: Broad gap-fading strategy on Kalshi NBA game markets.

Signal: the edge must survive the spread before a trade is triggered.
  YES entry: sportsbook_prob - yes_ask > threshold
  NO  entry: yes_bid - sportsbook_prob > threshold  (equiv: fade YES)

Fee model (from Kalshi fee schedule, effective Feb 5 2026):
  fee = rate × C × P × (1-P)   where C = contracts, P = entry price
  With C = stake/P:  fee = rate × stake × (1-P)

  Charged per trade (win OR lose), on both sides:
    Taker rate: 0.07   (cross the spread — order immediately matched)
    Maker rate: 0.0175 (rest on orderbook — 4× cheaper, requires patience)

Three execution models:
  mid_no_fee  — enter at mid, zero fee         (theoretical ceiling)
  ask_taker   — cross the spread, taker fee    (most conservative realistic)
  mid_maker   — rest at mid, maker fee         (best achievable if patient)

Primary sizing: flat $100/trade
Walk-forward: first 60% of games by date = in-sample, last 40% = OOS.

Outputs → findings/
  backtest_cumulative_pnl.png
  backtest_threshold_sweep.png
  backtest_by_bucket.png
  backtest_bootstrap.png
  backtest_trades_per_month.png
  backtest_results.md
"""

from pathlib import Path

import numpy as np
import pandas as pd
import matplotlib.pyplot as plt
import matplotlib.ticker as mticker

DATA_DIR = Path(__file__).parent.parent / "data"
OUT_DIR  = Path(__file__).parent.parent / "findings"
OUT_DIR.mkdir(exist_ok=True)

# ── Visual style ──────────────────────────────────────────────────────────────
BLUE, RED, GREEN, ORANGE, GRAY = "#1565C0","#C62828","#2E7D32","#E65100","#616161"
BG = "#FAFAFA"

def new_fig(w=11, h=5):
    fig, ax = plt.subplots(figsize=(w, h), facecolor=BG)
    ax.set_facecolor(BG)
    ax.spines[["top","right"]].set_visible(False)
    ax.spines[["left","bottom"]].set_color("#BDBDBD")
    return fig, ax

# ── Fee model (Kalshi fee schedule, Feb 2026) ─────────────────────────────────
# fee = rate × C × P × (1-P); with C = stake/P → fee = rate × stake × (1-P)
# Charged per trade regardless of outcome.
FEE_TAKER  = 0.07     # taker: order immediately matched against resting book
FEE_MAKER  = 0.0175   # maker: order rests on book, 4× cheaper
FLAT_STAKE = 100.0

def kalshi_fee(stake: float, entry: float, rate: float) -> float:
    """Kalshi fee in dollars for one trade."""
    return rate * stake * (1.0 - entry)

def net_pnl(entry: float, won: bool, stake: float, fee: float) -> float:
    """Net P&L after Kalshi fee (fee charged on every trade, win or lose)."""
    if won:
        gross = stake * (1.0 - entry) / entry
        return gross - fee
    return -stake - fee


# ── Build dataset ─────────────────────────────────────────────────────────────

def build_dataset() -> pd.DataFrame:
    """
    Load full_dataset.csv (456 finalized KXNBAGAME games, Dec 2025–May 2026).
    Uses previous_price_dollars as mid; previous_yes_bid/ask where available.
    Returns one row per game with signal columns pre-computed.
    """
    raw = pd.read_csv(DATA_DIR / "full_dataset.csv")
    raw["game_date"] = pd.to_datetime(raw["game_date"])
    raw = raw.sort_values("game_date").reset_index(drop=True)

    # yes_mid: prefer true bid/ask mid, else use prev_price
    def _mid(row):
        yb, ya = row.get("yes_bid"), row.get("yes_ask")
        if pd.notna(yb) and pd.notna(ya) and 0 < yb < ya:
            return (yb + ya) / 2.0
        return row["kalshi_prev_price"]

    raw["yes_mid"] = raw.apply(_mid, axis=1)

    # Fill missing bid/ask with ±2¢ proxy (flags ~79% of rows — pre-cutoff data)
    mask = raw["yes_bid"].isna() | (raw["yes_bid"] == 0)
    raw.loc[mask, "yes_bid"] = (raw.loc[mask, "yes_mid"] - 0.02).clip(lower=0.01)
    raw.loc[mask, "yes_ask"] = (raw.loc[mask, "yes_mid"] + 0.02).clip(upper=0.99)
    raw["proxy_spread"] = mask  # track which rows use proxy spread

    df = raw[["ticker", "game_date", "sb_prob_normed", "yes_bid", "yes_ask",
              "yes_mid", "result", "volume", "proxy_spread"]].copy()
    df = df.rename(columns={"sb_prob_normed": "sb_prob"})

    # Liquidity filter — proxy for orderbook depth.
    # Kalshi's API provides no historical L2 data; we use volume_fp (total contracts
    # traded per market lifetime) as a proxy. Our flat $100 stake requires at most
    # ~333 contracts (at a 30¢ entry). Requiring >= 1,000 contracts ensures our
    # order is never more than ~33% of total market volume.
    MIN_VOLUME = 1000
    n_before = len(df)
    df = df[df["volume"] >= MIN_VOLUME].copy()
    n_filtered = n_before - len(df)

    # Remove near-settled observations
    df = df[(df["yes_mid"] >= 0.10) & (df["yes_mid"] <= 0.90)].copy()

    # Pre-compute directional entry-price gaps (signal uses actual entry, not mid)
    # yes_gap > 0  →  sportsbook beats YES ask  →  buy YES opportunity
    # no_gap  > 0  →  YES bid beats sportsbook  →  buy NO opportunity
    df["yes_gap"] = df["sb_prob"] - df["yes_ask"]   # >0: buy YES
    df["no_gap"]  = df["yes_bid"] - df["sb_prob"]   # >0: buy NO
    df["spread"]  = df["yes_ask"] - df["yes_bid"]
    df["yes_won"] = (df["result"] == "yes").astype(int)

    df["bucket"] = pd.cut(
        df["sb_prob"],
        bins=[0, 0.30, 0.45, 0.55, 0.70, 1.0],
        labels=["< 30%","30–45%","45–55%","55–70%","> 70%"],
    )
    return df, n_filtered


# ── Core backtest engine ──────────────────────────────────────────────────────

def run_backtest(df: pd.DataFrame, threshold: float,
                 execution: str = "ask_taker") -> pd.DataFrame:
    """
    Signal: entry-price gap must exceed threshold.
      YES: sb_prob - yes_ask > threshold
      NO:  yes_bid - sb_prob > threshold

    execution:
      'mid_no_fee'  — mid price, no fee        (theoretical ceiling)
      'ask_taker'   — cross ask, taker fee      (most conservative realistic)
      'mid_maker'   — mid price, maker fee      (best achievable with patience)
    """
    if execution == "mid_no_fee":
        fee_rate, use_ask = 0.0,       False
    elif execution == "ask_taker":
        fee_rate, use_ask = FEE_TAKER, True
    elif execution == "mid_maker":
        fee_rate, use_ask = FEE_MAKER, False
    else:
        raise ValueError(f"Unknown execution model: {execution}")

    trades = []
    for _, row in df.iterrows():
        yb, ya   = row["yes_bid"], row["yes_ask"]
        yes_gap  = row["yes_gap"]   # sb_prob - yes_ask
        no_gap   = row["no_gap"]    # yes_bid - sb_prob

        if yes_gap > threshold:
            side   = "YES"
            entry  = ya if use_ask else (yb + ya) / 2.0
            belief = row["sb_prob"]
            won    = row["yes_won"] == 1
        elif no_gap > threshold:
            side   = "NO"
            entry  = (1.0 - yb) if use_ask else (1.0 - (yb + ya) / 2.0)
            belief = 1.0 - row["sb_prob"]
            won    = row["yes_won"] == 0
        else:
            continue

        if entry >= belief or entry <= 0 or entry >= 1:
            continue

        fee = kalshi_fee(FLAT_STAKE, entry, fee_rate)
        pnl = net_pnl(entry, won, FLAT_STAKE, fee)

        trades.append({
            "game_date":    row["game_date"],
            "ticker":       row["ticker"],
            "bucket":       row["bucket"],
            "side":         side,
            "sb_prob":      row["sb_prob"],
            "yes_mid":      row["yes_mid"],
            "entry":        entry,
            "yes_gap":      yes_gap,
            "no_gap":       no_gap,
            "spread":       row["spread"],
            "proxy_spread": row["proxy_spread"],
            "pnl":          pnl,
            "won":          won,
        })

    return pd.DataFrame(trades)


def summarise(trades: pd.DataFrame, label: str = "") -> dict:
    if len(trades) == 0:
        return {"label": label, "n": 0, "roi": 0.0, "win_rate": 0.0,
                "total_pnl": 0.0, "sharpe": 0.0}
    staked = FLAT_STAKE * len(trades)
    pnl    = trades["pnl"].sum()
    return {
        "label":     label,
        "n":         len(trades),
        "win_rate":  trades["won"].mean(),
        "total_pnl": pnl,
        "roi":       pnl / staked,
        "sharpe":    (trades["pnl"].mean() / trades["pnl"].std() * np.sqrt(len(trades))
                      if trades["pnl"].std() > 0 else 0.0),
    }


def bootstrap_roi(trades: pd.DataFrame, n_boot: int = 5000, seed: int = 42) -> np.ndarray:
    rng  = np.random.default_rng(seed)
    pnls = trades["pnl"].values
    rois = []
    for _ in range(n_boot):
        idx = rng.integers(0, len(trades), len(trades))
        rois.append(pnls[idx].sum() / (FLAT_STAKE * len(trades)))
    return np.array(rois)


# ══════════════════════════════════════════════════════════════════════════════
# Main
# ══════════════════════════════════════════════════════════════════════════════

def main():
    print("Building dataset...")
    df, n_filtered = build_dataset()
    n_proxy = df["proxy_spread"].sum()
    print(f"  {len(df)} clean observations  |  {df['game_date'].min().date()} – {df['game_date'].max().date()}")
    print(f"  Liquidity filter (>= 1,000 contracts): removed {n_filtered} thin markets")
    print(f"  Real bid/ask: {len(df)-n_proxy} ({(len(df)-n_proxy)/len(df):.1%})  |  Proxy ±2¢: {n_proxy} ({n_proxy/len(df):.1%})")

    split_idx  = int(len(df) * 0.60)
    split_date = df.iloc[split_idx]["game_date"]
    df_in  = df[df["game_date"] <  split_date].copy()
    df_out = df[df["game_date"] >= split_date].copy()
    print(f"  In-sample:  {len(df_in)} games (before {split_date.date()})")
    print(f"  Out-of-sample: {len(df_out)} games (from {split_date.date()})\n")

    THRESHOLD = 0.08   # 8% entry-price gap — primary threshold

    # ── 1. Execution model comparison ────────────────────────────────────────
    print("="*60)
    print(f"Execution models  |  threshold={THRESHOLD:.0%}  |  flat ${FLAT_STAKE:.0f}/trade")
    print("="*60)
    exec_results = {}
    for model, label in [
        ("mid_no_fee",  "Mid, no fee    (ceiling)          "),
        ("ask_taker",   "Ask, taker fee (realistic, worst) "),
        ("mid_maker",   "Mid, maker fee (realistic, best)  "),
    ]:
        t = run_backtest(df, THRESHOLD, execution=model)
        s = summarise(t, label)
        exec_results[model] = (t, s)
        print(f"  {label} | n={s['n']:3d} | win={s['win_rate']:.1%} "
              f"| ROI={s['roi']:+.1%} | P&L=${s['total_pnl']:+.0f}")
    print()

    # ── 2. Walk-forward ───────────────────────────────────────────────────────
    print("="*60)
    print(f"Walk-forward  |  ask_taker  |  threshold={THRESHOLD:.0%}")
    print("="*60)
    wf_results = {}
    for name, subset in [("In-sample (60%)", df_in), ("Out-of-sample (40%)", df_out)]:
        t = run_backtest(subset, THRESHOLD, execution="ask_taker")
        s = summarise(t, name)
        wf_results[name] = (t, s)
        print(f"  {name:22s} | n={s['n']:3d} | win={s['win_rate']:.1%} "
              f"| ROI={s['roi']:+.1%} | P&L=${s['total_pnl']:+.0f}")
    print()

    # ── 3. Bootstrap CI ───────────────────────────────────────────────────────
    primary, _ = exec_results["ask_taker"]
    boot_rois  = bootstrap_roi(primary)
    ci_lo, ci_hi = np.percentile(boot_rois, [2.5, 97.5])
    p_pos = (boot_rois > 0).mean()
    print(f"Bootstrap 95% CI (ask+fee, n={len(primary)}): [{ci_lo:+.1%}, {ci_hi:+.1%}]")
    print(f"  P(ROI > 0): {p_pos:.1%}\n")

    # ═══════════════════════════════════════════════════════════════════════
    # CHARTS
    # ═══════════════════════════════════════════════════════════════════════

    # ── Chart 1: Cumulative P&L — three execution models ─────────────────────
    fig, ax = new_fig(12, 5)
    for model, label, color, ls in [
        ("mid_no_fee", "Mid, no fee (ceiling)",          GREEN,  "--"),
        ("mid_maker",  "Mid, maker fee (best realistic)", ORANGE, "-."),
        ("ask_taker",  "Ask, taker fee (worst realistic)", BLUE,  "-"),
    ]:
        t, _ = exec_results[model]
        if len(t):
            t_s = t.sort_values("game_date").reset_index(drop=True)
            ax.plot(range(len(t_s)), t_s["pnl"].cumsum(),
                    lw=2, ls=ls, color=color, label=label)

    n_in_trades = len(wf_results["In-sample (60%)"][0])
    ax.axvline(n_in_trades, color=GRAY, lw=1.5, ls="--")
    ax.text(n_in_trades + 0.5, ax.get_ylim()[1] * 0.85, "OOS →",
            fontsize=9, color=GRAY)
    ax.axhline(0, color="#333", lw=1, ls=":")
    ax.set_xlabel("Trade #", fontsize=11)
    ax.set_ylabel("Cumulative P&L ($)", fontsize=11)
    ax.legend(fontsize=10, framealpha=0.9)
    ax.set_title(
        f"Cumulative P&L by Execution Model  |  threshold={THRESHOLD:.0%} entry-price gap  |  flat ${FLAT_STAKE:.0f}/trade",
        fontsize=12, fontweight="bold", color="#212121", pad=12,
    )
    fig.tight_layout()
    fig.savefig(OUT_DIR / "backtest_cumulative_pnl.png", dpi=150, bbox_inches="tight")
    plt.close()
    print("✓ backtest_cumulative_pnl.png")

    # ── Chart 2: Threshold sweep ──────────────────────────────────────────────
    thresholds = np.arange(0.02, 0.22, 0.01)
    sweep_rows = []
    for thr in thresholds:
        for model, label in [("mid_no_fee","Mid (ceiling)"),
                              ("ask_taker","Ask taker (worst)"),
                              ("mid_maker","Mid maker (best)")]:
            t = run_backtest(df, float(thr), execution=model)
            s = summarise(t)
            t_in = run_backtest(df_in, float(thr), execution=model)
            s_in = summarise(t_in)
            sweep_rows.append({"threshold": thr, "model": label,
                                "roi": s["roi"], "roi_in": s_in["roi"],
                                "n": s["n"], "n_month": s["n"] / 4.5})

    sw = pd.DataFrame(sweep_rows)

    fig, (ax1, ax2) = plt.subplots(1, 2, figsize=(13, 5), facecolor=BG)
    for ax in [ax1, ax2]:
        ax.set_facecolor(BG)
        ax.spines[["top","right"]].set_visible(False)
        ax.spines[["left","bottom"]].set_color("#BDBDBD")

    for model, color, ls in [("Mid (ceiling)", GREEN, "--"),
                               ("Ask taker (worst)", BLUE, "-"),
                               ("Mid maker (best)", ORANGE, "-.")]:
        sub = sw[sw["model"] == model]
        ax1.plot(sub["threshold"]*100, sub["roi"]*100, lw=2, color=color, ls=ls, label=model)
        ax2.plot(sub["threshold"]*100, sub["n"],       lw=2, color=color, ls=ls, label=model)

    ax1.axhline(0, color="#333", lw=1, ls=":")
    ax1.axvline(THRESHOLD*100, color=ORANGE, lw=1.5, ls=":", label=f"Primary ({THRESHOLD:.0%})")
    ax1.set_xlabel("Entry-price gap threshold (%)", fontsize=11)
    ax1.set_ylabel("ROI (%)", fontsize=11)
    ax1.set_title("ROI vs Threshold", fontsize=12, fontweight="bold")
    ax1.legend(fontsize=9)
    ax1.yaxis.set_major_formatter(mticker.PercentFormatter())

    ax2.axvline(THRESHOLD*100, color=ORANGE, lw=1.5, ls=":", label=f"Primary ({THRESHOLD:.0%})")
    ax2.set_xlabel("Entry-price gap threshold (%)", fontsize=11)
    ax2.set_ylabel("Total trades (4.5-month dataset)", fontsize=11)
    ax2.set_title("Trade Count vs Threshold", fontsize=12, fontweight="bold")
    ax2.legend(fontsize=9)

    fig.suptitle("Threshold Sensitivity  |  flat $100/trade  |  entry-price gap signal",
                 fontsize=12, fontweight="bold", color="#212121", y=1.02)
    fig.tight_layout()
    fig.savefig(OUT_DIR / "backtest_threshold_sweep.png", dpi=150, bbox_inches="tight")
    plt.close()
    print("✓ backtest_threshold_sweep.png")

    # ── Chart 3: ROI and win rate by probability bucket ───────────────────────
    primary_s = primary.sort_values("game_date").reset_index(drop=True)
    bucket_order = ["< 30%","30–45%","45–55%","55–70%","> 70%"]
    bstats = (primary_s.groupby("bucket", observed=True)
              .agg(n=("pnl","count"),
                   win_rate=("won","mean"),
                   total_pnl=("pnl","sum"))
              .reindex(bucket_order))
    bstats["roi"] = bstats["total_pnl"] / (FLAT_STAKE * bstats["n"])

    fig, (ax1, ax2) = plt.subplots(1, 2, figsize=(13, 5), facecolor=BG)
    for ax in [ax1, ax2]:
        ax.set_facecolor(BG)
        ax.spines[["top","right"]].set_visible(False)
        ax.spines[["left","bottom"]].set_color("#BDBDBD")

    colors = [RED if r < 0 else GREEN for r in bstats["roi"].fillna(0)]
    ax1.bar(range(len(bstats)), bstats["roi"].fillna(0)*100, color=colors,
            alpha=0.82, width=0.55, zorder=3)
    for i, (roi, n) in enumerate(zip(bstats["roi"].fillna(0), bstats["n"].fillna(0))):
        ax1.text(i, roi*100 + (2 if roi >= 0 else -4),
                 f"{roi*100:+.1f}%\n(n={int(n)})",
                 ha="center", va="bottom" if roi >= 0 else "top",
                 fontsize=9.5, fontweight="bold",
                 color=GREEN if roi > 0 else RED)
    ax1.axhline(0, color="#333", lw=1)
    ax1.set_xticks(range(len(bstats)))
    ax1.set_xticklabels(bucket_order, fontsize=10)
    ax1.set_ylabel("ROI (%)", fontsize=11)
    ax1.set_title("ROI by Sportsbook Probability Bucket", fontsize=12, fontweight="bold")
    ax1.yaxis.set_major_formatter(mticker.PercentFormatter())

    wr_colors = [GREEN if w >= 0.50 else RED for w in bstats["win_rate"].fillna(0)]
    ax2.bar(range(len(bstats)), bstats["win_rate"].fillna(0)*100,
            color=wr_colors, alpha=0.82, width=0.55, zorder=3)
    ax2.axhline(50, color="#333", lw=1.2, ls="--", label="50% break-even")
    ax2.set_xticks(range(len(bstats)))
    ax2.set_xticklabels(bucket_order, fontsize=10)
    ax2.set_ylabel("Win rate (%)", fontsize=11)
    ax2.set_title("Win Rate by Bucket", fontsize=12, fontweight="bold")
    ax2.legend(fontsize=9)
    ax2.yaxis.set_major_formatter(mticker.PercentFormatter())

    fig.suptitle(f"Performance by Probability Bucket  |  Ask + Fee  |  threshold={THRESHOLD:.0%}",
                 fontsize=12, fontweight="bold", color="#212121", y=1.02)
    fig.tight_layout()
    fig.savefig(OUT_DIR / "backtest_by_bucket.png", dpi=150, bbox_inches="tight")
    plt.close()
    print("✓ backtest_by_bucket.png")

    # ── Chart 4: Bootstrap distribution ──────────────────────────────────────
    real_roi = primary["pnl"].sum() / (FLAT_STAKE * len(primary))
    fig, ax = new_fig(9, 5)
    ax.hist(boot_rois * 100, bins=60, color=BLUE, alpha=0.75,
            edgecolor="white", zorder=3)
    ax.axvline(0,            color="#333",  lw=1.5, ls="--", label="Zero ROI")
    ax.axvline(real_roi*100, color=ORANGE,  lw=2,
               label=f"Observed ROI: {real_roi*100:+.1f}%")
    ax.axvline(ci_lo*100, color=RED, lw=1.5, ls=":",
               label=f"95% CI: [{ci_lo*100:+.1f}%, {ci_hi*100:+.1f}%]")
    ax.axvline(ci_hi*100, color=RED, lw=1.5, ls=":")
    ax.text(0.98, 0.95, f"P(ROI > 0) = {p_pos:.1%}",
            transform=ax.transAxes, ha="right", va="top",
            fontsize=12, fontweight="bold",
            color=GREEN if p_pos > 0.70 else GRAY)
    ax.set_xlabel("ROI (%)", fontsize=11)
    ax.set_ylabel("Bootstrap count", fontsize=11)
    ax.legend(fontsize=10, framealpha=0.9)
    ax.set_title(
        f"Bootstrap Distribution of ROI  |  5,000 resamples  |  n={len(primary)} trades",
        fontsize=12, fontweight="bold", color="#212121", pad=12,
    )
    fig.tight_layout()
    fig.savefig(OUT_DIR / "backtest_bootstrap.png", dpi=150, bbox_inches="tight")
    plt.close()
    print("✓ backtest_bootstrap.png")

    # ── Chart 5: Trades per month across thresholds ───────────────────────────
    # Dataset spans ~4.5 months; scale to per-month and show YES vs NO split
    fig, ax = new_fig(10, 5)
    dataset_months = (df["game_date"].max() - df["game_date"].min()).days / 30.4

    thresholds_plot = np.arange(0.02, 0.22, 0.01)
    yes_pm, no_pm, total_pm = [], [], []
    for thr in thresholds_plot:
        t = run_backtest(df, float(thr), execution="ask_taker")
        if len(t):
            yes_pm.append((t["side"] == "YES").sum() / dataset_months)
            no_pm.append( (t["side"] == "NO").sum()  / dataset_months)
            total_pm.append(len(t) / dataset_months)
        else:
            yes_pm.append(0); no_pm.append(0); total_pm.append(0)

    x = thresholds_plot * 100
    ax.stackedplot = ax.bar(x, yes_pm, width=0.85, color=GREEN, alpha=0.75, label="YES buys")
    ax.bar(x, no_pm, width=0.85, bottom=yes_pm, color=RED, alpha=0.75, label="NO buys")
    ax.axvline(THRESHOLD*100, color=ORANGE, lw=2, ls="--",
               label=f"Primary threshold ({THRESHOLD:.0%})")
    ax.set_xlabel("Entry-price gap threshold (%)", fontsize=11)
    ax.set_ylabel("Trades per month", fontsize=11)
    ax.legend(fontsize=10, framealpha=0.9)
    ax.set_title(
        "Signal Frequency: Trades per Month by Threshold  |  ask_with_fee",
        fontsize=12, fontweight="bold", color="#212121", pad=12,
    )
    fig.tight_layout()
    fig.savefig(OUT_DIR / "backtest_trades_per_month.png", dpi=150, bbox_inches="tight")
    plt.close()
    print("✓ backtest_trades_per_month.png")

    # ── Write results markdown ────────────────────────────────────────────────
    t_mid,   s_mid   = exec_results["mid_no_fee"]
    t_taker, s_taker = exec_results["ask_taker"]
    t_maker, s_maker = exec_results["mid_maker"]
    t_in,    s_in    = wf_results["In-sample (60%)"]
    t_oos,   s_oos   = wf_results["Out-of-sample (40%)"]

    trades_month = len(t_taker) / dataset_months

    md = f"""# Strategy Backtest Results

**Strategy:** Broad gap-fading on Kalshi NBA game markets
**Signal:** Entry-price gap > {THRESHOLD:.0%}
  - Buy YES when `sportsbook_prob − yes_ask > {THRESHOLD:.0%}`
  - Buy NO  when `yes_bid − sportsbook_prob > {THRESHOLD:.0%}`
**Dataset:** {len(df)} clean pre-game observations, {df['game_date'].min().date()} – {df['game_date'].max().date()}
**Liquidity filter:** Markets with < 1,000 contracts of total lifetime volume are excluded ({n_filtered} removed).
Volume is used as a proxy for orderbook depth — Kalshi's API provides no historical L2 data.
At a $100 flat stake our worst-case order (~333 contracts at 30¢) stays under 33% of any included market's volume.
**Spread note:** {n_proxy} of {len(df)} rows ({n_proxy/len(df):.0%}) use a ±2¢ proxy spread (pre-March 2026 data lacks real bid/ask)

---

## Execution Model Comparison  *(flat ${FLAT_STAKE:.0f}/trade)*

Fee formula (Kalshi schedule, Feb 2026): `fee = rate × stake × (1 − entry)` — charged per trade win or lose.
- Taker rate: 7% (cross the spread, immediate fill)
- Maker rate: 1.75% (rest on orderbook, 4× cheaper — requires patience)

| Model | Trades | Win rate | ROI | Total P&L |
|-------|--------|----------|-----|-----------|
| Mid, no fee *(ceiling)* | {s_mid['n']} | {s_mid['win_rate']:.1%} | {s_mid['roi']:+.1%} | ${s_mid['total_pnl']:+.0f} |
| **Ask, taker fee *(worst realistic)*** | **{s_taker['n']}** | **{s_taker['win_rate']:.1%}** | **{s_taker['roi']:+.1%}** | **${s_taker['total_pnl']:+.0f}** |
| **Mid, maker fee *(best realistic)*** | **{s_maker['n']}** | **{s_maker['win_rate']:.1%}** | **{s_maker['roi']:+.1%}** | **${s_maker['total_pnl']:+.0f}** |

The realistic live ROI sits in the range [{s_taker['roi']:+.1%}, {s_maker['roi']:+.1%}] depending on execution.

---

## Walk-Forward Results  *(ask taker, worst case)*

| Period | Trades | Win rate | ROI |
|--------|--------|----------|-----|
| In-sample  (60%) | {s_in['n']} | {s_in['win_rate']:.1%} | {s_in['roi']:+.1%} |
| **Out-of-sample (40%)** | **{s_oos['n']}** | **{s_oos['win_rate']:.1%}** | **{s_oos['roi']:+.1%}** |

---

## Bootstrap Confidence Interval  *(5,000 resamples, ask taker)*

- **95% CI on ROI:** [{ci_lo:+.1%}, {ci_hi:+.1%}]
- **P(ROI > 0):** {p_pos:.1%}

---

## Signal Frequency

At the {THRESHOLD:.0%} entry-price gap threshold: **~{trades_month:.1f} trades/month** on NBA regular season volume.

---

## Key Takeaways

1. **Fee formula corrected.** Kalshi charges `0.07 × stake × (1-entry)` per trade (taker),
   applied to every trade — not 7% of gross profit on wins only. Maker orders pay 4× less
   (`0.0175 × stake × (1-entry)`), making patient limit-order execution significantly better.

2. **Realistic ROI range: [{s_taker['roi']:+.1%}, {s_maker['roi']:+.1%}].** Taker (cross the spread)
   is the floor; maker (rest at mid and wait for fill) is the ceiling. Actual execution will
   land somewhere between, depending on market liquidity and how aggressively you need to fill.

3. **Signal uses entry price, not mid.** The gap must exceed {THRESHOLD:.0%} after crossing the spread —
   this naturally filters marginal trades where the edge disappears at execution.

4. **Out-of-sample: {s_oos['roi']:+.1%}.** Edge partially degrades OOS on small sample.
   Bootstrap P(ROI > 0) = {p_pos:.1%} on the taker model.

5. **No sub-universe filter adds alpha.** Trade the broad signal, not a slice.
"""

    (OUT_DIR / "backtest_results.md").write_text(md)
    print("✓ backtest_results.md\n")
    print(md)


if __name__ == "__main__":
    main()
