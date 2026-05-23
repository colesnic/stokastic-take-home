"""
Iteration 50: BTC MVRV + AdrActCnt Dual Regime + Vol Gate — 5-Coin
===================================================================
Replaces the triple regime (price+AdrActCnt+ETH TxCnt) with a dual
BTC-native on-chain signal:
  1. BTC CapMVRVCur EMA(short) > EMA(long)  — appreciation trend
  2. BTC AdrActCnt  EMA(short) > EMA(long)  — network activity trend

No ETH dependency. No price EMA. Pure BTC on-chain regime.

RATIONALE:
  MVRV (Market Value / Realized Value) captures whether coins are
  appreciating above their cost basis — rising MVRV = expansion phase.
  AdrActCnt captures network adoption and usage growth.
  Together: rising MVRV + rising AdrActCnt = on-chain bull regime.
  This removes ETH cross-chain noise and BTC price lag.

Vol Gate (entry-only, same as Iter 41):
  Entry: regime_bull AND btc_vol30 < vol_threshold
  Exit:  regime_bull = False only

Portfolio: BTC, ETH, BNB, ADA, TRX
Walk-forward: IS 2018-2020, OOS 2021-2024
"""
import urllib.request, io, os, sys, numpy as np, pandas as pd, warnings
warnings.filterwarnings("ignore")
sys.path.insert(0, os.path.dirname(__file__))
from backtester_advanced import AdvancedBacktester, AdvancedBacktestResult
from risk_metrics import RiskReport
from indicators import ema as ema_fn, atr as atr_fn, adx as adx_fn

COINMETRICS="https://raw.githubusercontent.com/coinmetrics/data/master/csv/{}.csv"
IS_START="2018-01-01"; IS_END="2020-12-31"
OOS_START="2021-01-01"; OOS_END="2024-12-31"
TAX_RATE=0.35

COINS=[("btc","BTC",42),("eth","ETH",11),("bnb","BNB",77),("ada","ADA",99),("trx","TRX",55)]

def fetch_btc_full():
    url=COINMETRICS.format("btc")
    with urllib.request.urlopen(url,timeout=20) as r:
        df=pd.read_csv(io.StringIO(r.read().decode()),low_memory=False)
    df["Date"]=pd.to_datetime(df["time"])
    df["Close"]=pd.to_numeric(df["PriceUSD"],errors="coerce")
    df["AdrActCnt"]=pd.to_numeric(df["AdrActCnt"],errors="coerce")
    df["MVRV"]=pd.to_numeric(df["CapMVRVCur"],errors="coerce")
    return df[["Date","Close","AdrActCnt","MVRV"]].dropna(subset=["Close"]).set_index("Date").sort_index()

def fetch_eth_full():  # placeholder — not used for signals
    url=COINMETRICS.format("eth")
    with urllib.request.urlopen(url,timeout=20) as r:
        df=pd.read_csv(io.StringIO(r.read().decode()),low_memory=False)
    df["Date"]=pd.to_datetime(df["time"])
    for col in("PriceUSD","ReferenceRateUSD"):
        if col in df.columns:
            df["Close"]=pd.to_numeric(df[col],errors="coerce")
            if df["Close"].notna().sum()>100: break
    return df[["Date","Close"]].dropna().set_index("Date").sort_index()

def fetch_close(coin):
    url=COINMETRICS.format(coin)
    with urllib.request.urlopen(url,timeout=15) as r:
        df=pd.read_csv(io.StringIO(r.read().decode()),low_memory=False)
    df["Date"]=pd.to_datetime(df["time"])
    for col in("PriceUSD","ReferenceRateUSD"):
        if col in df.columns:
            df["Close"]=pd.to_numeric(df[col],errors="coerce")
            if df["Close"].notna().sum()>100: break
    return df[["Date","Close"]].dropna().set_index("Date").sort_index()["Close"]

def synthesize_ohlcv(close,seed=42):
    rng=np.random.default_rng(seed); n=len(close)
    ret=close.pct_change().fillna(0.0); vol=ret.rolling(20).std().fillna(ret.std())
    op=close.shift(1).fillna(close.iloc[0]); rf=np.abs(rng.normal(1.2,0.5,n)).clip(0.2,3.0)
    half=close.values*vol.values*rf; hi=np.maximum(op.values,close.values)+half
    lo=np.maximum(np.minimum(op.values,close.values)-half,close.values*0.3)
    vv=np.abs(rng.normal(1_000_000,300_000,n)).astype(int)
    df=pd.DataFrame({"Open":op.values,"High":hi,"Low":lo,"Close":close.values,"Volume":vv},index=close.index)
    df["atr14"]=atr_fn(df["High"],df["Low"],df["Close"],14)
    df["adx14"]=adx_fn(df["High"],df["Low"],df["Close"],14)
    return df

def slice_data(data,start,end):
    return {t:df.loc[start:end] for t,df in data.items() if len(df.loc[start:end])>=60}

class MVRVAdrVolGateStrategy:
    """
    Dual regime: BTC MVRV EMA trend + BTC AdrActCnt EMA trend.
    Vol gate: BTC realized vol < threshold (entry only).
    """
    def __init__(self,act_short=20,act_long=60,vol_lookback=30,vol_threshold=0.80,min_hold_days=0,rebalance_days=7):
        self.act_short=act_short; self.act_long=act_long
        self.vol_lookback=vol_lookback; self.vol_threshold=vol_threshold
        self.min_hold_days=min_hold_days; self.rebalance_days=rebalance_days; self.signals={}
    def prepare(self,data,btc_full,eth_full):
        btc_close=btc_full["Close"].ffill()
        # 1. BTC MVRV EMA trend
        mvrv=btc_full["MVRV"].ffill()
        mv_s=ema_fn(mvrv,self.act_short); mv_l=ema_fn(mvrv,self.act_long); mvrv_bull=mv_s>mv_l
        # 2. BTC AdrActCnt EMA trend
        adr=btc_full["AdrActCnt"].ffill()
        adr_s=ema_fn(adr,self.act_short); adr_l=ema_fn(adr,self.act_long); adr_bull=adr_s>adr_l
        regime_bull=mvrv_bull&adr_bull; regime_exit=~regime_bull
        # Vol gate
        btc_ret=btc_close.pct_change()
        vol30=btc_ret.rolling(self.vol_lookback).std()*np.sqrt(252)
        vol_ok=(vol30<self.vol_threshold).fillna(False)
        entry_allowed=regime_bull&vol_ok
        all_dates=btc_close.index.sort_values(); in_position={}
        sig_dict={t:pd.Series(0,index=all_dates,dtype=int) for _,t,_ in COINS}
        last_rebalance=None
        for date in all_dates:
            if last_rebalance is not None and (date-last_rebalance).days<self.rebalance_days: continue
            last_rebalance=date
            should_exit=bool(regime_exit.loc[date]) if date in regime_exit.index else True
            can_enter=bool(entry_allowed.loc[date]) if date in entry_allowed.index else False
            if should_exit:
                for t in list(in_position):
                    held=(date-in_position[t]).days
                    if held>=self.min_hold_days:
                        if date in sig_dict[t].index: sig_dict[t].loc[date]=-1
                        del in_position[t]
            elif can_enter:
                for _,t,_ in COINS:
                    if t not in in_position:
                        if date in sig_dict[t].index: sig_dict[t].loc[date]=1
                        in_position[t]=date
        self.signals={t:sig_dict[t] for _,t,_ in COINS}
    def get_signals(self,ticker): return self.signals.get(ticker,pd.Series(dtype=int))

def run_is(full_data,is_data,btc_full,eth_full,sp,bt_fixed):
    strat=MVRVAdrVolGateStrategy(**sp); strat.prepare(full_data,btc_full,eth_full)
    bt=AdvancedBacktester(initial_capital=100_000,**bt_fixed)
    return RiskReport(bt.run(is_data,strat))

def run_oos(full_data,combined_data,btc_full,eth_full,sp,bt_fixed):
    strat=MVRVAdrVolGateStrategy(**sp); strat.prepare(full_data,btc_full,eth_full)
    bt=AdvancedBacktester(initial_capital=100_000,**bt_fixed)
    result=bt.run(combined_data,strat); eq=result.equity_curve; oos_eq=eq.loc[OOS_START:]
    oos_trades=[t for t in result.closed_trades if t.exit_date is not None and t.exit_date>=pd.Timestamp(OOS_START)]
    if len(oos_eq)==0: return None
    return RiskReport(AdvancedBacktestResult(equity_curve=oos_eq.tolist(),dates=oos_eq.index.tolist(),closed_trades=oos_trades,initial_capital=float(oos_eq.iloc[0])))

def main():
    print("\n"+"="*72)
    print("  ITERATION 50 — MVRV+AdrActCnt Dual Regime + Vol Gate + 5-Coin")
    print("  Regime: BTC MVRV trend + BTC AdrActCnt trend (no ETH dependency)")
    print(f"  Tax: STCG {TAX_RATE*100:.0f}%/<365d  |  LTCG 20%/>=365d")
    print("="*72)

    print("\n  Fetching BTC (price + AdrActCnt + MVRV)...")
    btc_full=fetch_btc_full(); eth_full=fetch_eth_full()
    print(f"  BTC: {len(btc_full)} rows  last=${float(btc_full['Close'].iloc[-1]):,.2f}")

    # MVRV diagnostics
    mvrv=btc_full["MVRV"].dropna()
    print("\n  BTC MVRV by year:")
    for yr in[2018,2019,2020,2021,2022,2023,2024]:
        v=mvrv[mvrv.index.year==yr]
        if len(v)>0: print(f"  {yr}: min={v.min():.2f} max={v.max():.2f} mean={v.mean():.2f}")

    full_data={}
    for coin,label,seed in COINS:
        try:
            s=btc_full["Close"] if label=="BTC" else (eth_full["Close"] if label=="ETH" else fetch_close(coin))
            full_data[label]=synthesize_ohlcv(s,seed=seed)
            print(f"  {label}: {len(s)} rows  last=${float(s.iloc[-1]):,.4f}")
        except Exception as e: print(f"  {label}: FAILED ({e})")

    if len(full_data)<4: print("  Insufficient data."); return

    is_data=slice_data(full_data,IS_START,IS_END)
    combined_data=slice_data(full_data,IS_START,OOS_END)
    bt_fixed=dict(max_positions=5,position_size_pct=0.20,atr_stop_multiplier=20.0,
                  atr_trail_multiplier=12.0,risk_per_trade_pct=0.20,short_term_tax_rate=TAX_RATE)

    strat_configs=[
        dict(act_short=as_,act_long=al,vol_lookback=30,vol_threshold=vt,min_hold_days=mhd,rebalance_days=7)
        for(as_,al)in[(20,60),(30,90),(10,30)] for vt in[0.60,0.80,1.00] for mhd in[0,365]
    ]

    print(f"\n  IS grid ({len(strat_configs)} configs, {IS_START}–{IS_END})")
    print(f"  {'act':>7} {'vol':>6} {'mhd':>4}  {'Mo%':>7} {'SR':>6} {'DD%':>8} {'N':>4} {'Hold':>5} {'score':>7}")
    print("  "+"-"*60)
    results_is=[]
    for sp in strat_configs:
        try:
            rpt=run_is(full_data,is_data,btc_full,eth_full,sp,bt_fixed)
            m=rpt.full_metrics()
            mo=m.get("monthly_return_pct",0); sr=m.get("sharpe_ratio",0)
            dd=m.get("max_drawdown_pct",0); nt=m.get("n_trades",0); hld=m.get("avg_holding_days",0) or 0
            if nt<2: continue
            score=sr*3.0+mo*0.5-max(0,-40-dd)*0.5
            results_is.append((score,mo,sr,dd,hld,sp,m))
            print(f"  {sp['act_short']}/{sp['act_long']:>3}  <{sp['vol_threshold']:.2f}  {sp['min_hold_days']:>4}  {mo:>+7.2f}%  {sr:>6.2f}  {dd:>8.2f}%  {nt:>4}  {hld:>4.0f}d  {score:>7.2f}")
        except Exception as ex: print(f"  [skip] {ex}")

    results_is.sort(key=lambda x:x[0],reverse=True)
    if not results_is: print("  No valid IS configs."); return

    best_score,best_mo,best_sr,best_dd,best_hld,best_sp,_=results_is[0]
    print(f"\n  IS Champion: act={best_sp['act_short']}/{best_sp['act_long']} vol<{best_sp['vol_threshold']:.2f} mhd={best_sp['min_hold_days']}  score={best_score:.2f}")

    print(f"\n  OOS grid ({OOS_START}–{OOS_END})")
    print(f"  {'act':>7} {'vol':>6} {'mhd':>4}  {'Mo%':>7} {'SR':>6} {'DD%':>8} {'N':>4} {'Hold':>5} {'Eq$':>12}")
    print("  "+"-"*65)
    results_oos=[]
    for _,_,_,_,_,sp,_ in results_is:
        try:
            rpt=run_oos(full_data,combined_data,btc_full,eth_full,sp,bt_fixed)
            if rpt is None: continue
            m=rpt.full_metrics()
            mo=m.get("monthly_return_pct",0); sr=m.get("sharpe_ratio",0)
            dd=m.get("max_drawdown_pct",0); nt=m.get("n_trades",0)
            hld=m.get("avg_holding_days",0) or 0; eq=m.get("final_equity",0)
            results_oos.append((mo,sr,dd,nt,hld,eq,sp,m))
            print(f"  {sp['act_short']}/{sp['act_long']:>3}  <{sp['vol_threshold']:.2f}  {sp['min_hold_days']:>4}  {mo:>+7.2f}%  {sr:>6.2f}  {dd:>8.2f}%  {nt:>4}  {hld:>4.0f}d  ${eq:>12,.0f}")
        except Exception as ex: print(f"  [skip] {ex}")

    if not results_oos: print("  No OOS results."); return
    is_champ_oos=next((row for row in results_oos if row[6]==best_sp),results_oos[0])
    oos_mo,oos_sr,oos_dd,oos_n,oos_hld,oos_eq,oos_sp,oos_m=is_champ_oos

    if oos_hld>=365:
        net_mo=oos_mo*(1-0.20)/(1-TAX_RATE); tax_note=f"LTCG 20% (hold {oos_hld:.0f}d)"
    else:
        net_mo=oos_mo; tax_note=f"STCG {TAX_RATE*100:.0f}% (hold {oos_hld:.0f}d)"

    oos_wr=oos_m.get("win_rate_pct",0); oos_pf=oos_m.get("profit_factor",0); oos_cal=oos_m.get("calmar_ratio",0)
    print(f"\n  IS-CHAMPION OOS METRICS")
    for k,v in oos_m.items(): print(f"  {k:<30} {v}")

    pass_criteria=[
        ("Monthly >= 2.0%",net_mo>=2.0,net_mo-2.0),("Sharpe >= 1.0",oos_sr>=1.0,oos_sr-1.0),
        ("MaxDD > -40%",oos_dd>-40.0,oos_dd+40.0),("Calmar >= 0.8",oos_cal>=0.8,oos_cal-0.8),
        ("Win Rate >= 40%",oos_wr>=40.0,oos_wr-40.0),("Profit Factor >= 1.3",oos_pf>=1.3,oos_pf-1.3),
        ("N Trades >= 5",oos_n>=5,oos_n-5),
    ]
    n_pass=sum(1 for _,p,_ in pass_criteria if p)

    print(f"\n{'='*72}")
    print(f"  VERDICT  —  OOS {OOS_START}–{OOS_END}, MVRV+AdrActCnt Dual Regime")
    print(f"{'='*72}")
    for label,passed,delta in pass_criteria:
        mark="[PASS]" if passed else "[FAIL]"
        print(f"    {mark}  {label:<25} {delta:>+.2f}")
    print(f"\n  {n_pass}/7 criteria pass")
    print(f"  Model equity: ${oos_eq:,.0f}  (OOS base = $100,000)")
    print(f"  IS-champion OOS: {oos_mo:+.2f}%/mo  Sharpe {oos_sr:.2f}  MaxDD {oos_dd:.2f}%  Hold {oos_hld:.0f}d")
    print(f"  After-tax net ({tax_note}): ~{net_mo:+.2f}%/month")
    print(f"\n  Iter 41 baseline: +3.00%/mo → +3.69%/mo after-LTCG  |  Sharpe 1.22")
    if n_pass>=7: print(f"\n  *** PASS 7/7 ***")
    else: print(f"\n  --- {n_pass}/7 pass ---")

if __name__=="__main__": main()
