"""
Iteration 56: BTC MVRV EMA Trend + Vol Gate (Single On-Chain Signal)
======================================================================
Tests whether MVRV alone (no price EMA, no AdrActCnt) is sufficient to
generate walk-forward validated returns. Simplest possible BTC on-chain regime.

Hypothesis: MVRV EMA(20) > EMA(60) correctly captures:
  - 2018: MVRV declining (3.26→0.69) → EMA bearish → blocks IS entries
  - 2019: MVRV recovering (0.76→2.57) → EMA turns bullish mid-year
  - 2020: MVRV rising strongly (0.88→3.15) → EMA bullish by mid-year
  - 2022: MVRV declining (1.94→0.75) → EMA bearish → exits bear market
  - 2023-2024: MVRV recovering (0.84→2.78) → EMA bullish → captures recovery

Removing price EMA and AdrActCnt may allow earlier OOS entries (higher returns)
at the cost of potentially higher MaxDD (2021 May crash risk).

Walk-forward: IS 2018-2020, OOS 2021-2024
Portfolio: BTC, ETH, BNB, ADA, TRX
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
    df["MVRV"]=pd.to_numeric(df["CapMVRVCur"],errors="coerce")
    return df[["Date","Close","MVRV"]].dropna(subset=["Close"]).set_index("Date").sort_index()

def fetch_eth_full():
    url=COINMETRICS.format("eth")
    with urllib.request.urlopen(url,timeout=20) as r:
        df=pd.read_csv(io.StringIO(r.read().decode()),low_memory=False)
    df["Date"]=pd.to_datetime(df["time"])
    for col in ("PriceUSD","ReferenceRateUSD"):
        if col in df.columns:
            df["Close"]=pd.to_numeric(df[col],errors="coerce")
            if df["Close"].notna().sum()>100: break
    return df[["Date","Close"]].dropna().set_index("Date").sort_index()

def fetch_close(coin):
    url=COINMETRICS.format(coin)
    with urllib.request.urlopen(url,timeout=15) as r:
        df=pd.read_csv(io.StringIO(r.read().decode()),low_memory=False)
    df["Date"]=pd.to_datetime(df["time"])
    for col in ("PriceUSD","ReferenceRateUSD"):
        if col in df.columns:
            df["Close"]=pd.to_numeric(df[col],errors="coerce")
            if df["Close"].notna().sum()>100: break
    return df[["Date","Close"]].dropna().set_index("Date").sort_index()["Close"]

def synthesize_ohlcv(close, seed=42):
    rng=np.random.default_rng(seed); n=len(close)
    ret=close.pct_change().fillna(0.0); vol=ret.rolling(20).std().fillna(ret.std())
    op=close.shift(1).fillna(close.iloc[0]); rf=np.abs(rng.normal(1.2,0.5,n)).clip(0.2,3.0)
    half=close.values*vol.values*rf
    hi=np.maximum(op.values,close.values)+half
    lo=np.maximum(np.minimum(op.values,close.values)-half,close.values*0.3)
    vv=np.abs(rng.normal(1_000_000,300_000,n)).astype(int)
    df=pd.DataFrame({"Open":op.values,"High":hi,"Low":lo,"Close":close.values,"Volume":vv},index=close.index)
    df["atr14"]=atr_fn(df["High"],df["Low"],df["Close"],14)
    df["adx14"]=adx_fn(df["High"],df["Low"],df["Close"],14)
    return df

def slice_data(data, start, end):
    return {t:df.loc[start:end] for t,df in data.items() if len(df.loc[start:end])>=60}

class MVRVOnlyStrategy:
    def __init__(self, act_short=20, act_long=60, vol_lookback=30,
                 vol_threshold=0.80, min_hold_days=0, rebalance_days=7):
        self.act_short=act_short; self.act_long=act_long
        self.vol_lookback=vol_lookback; self.vol_threshold=vol_threshold
        self.min_hold_days=min_hold_days; self.rebalance_days=rebalance_days
        self.signals={}

    def prepare(self, data, btc_full, eth_full):
        btc_close=btc_full["Close"]
        mvrv=btc_full["MVRV"].ffill()
        mv_s=ema_fn(mvrv,self.act_short); mv_l=ema_fn(mvrv,self.act_long)
        mvrv_bull=(mv_s>mv_l)
        regime_bull=mvrv_bull; regime_exit=~regime_bull
        btc_ret=btc_close.pct_change()
        vol30=btc_ret.rolling(self.vol_lookback).std()*np.sqrt(252)
        vol_ok=(vol30<self.vol_threshold).fillna(False)
        entry_allowed=regime_bull & vol_ok
        all_dates=btc_close.index.sort_values()
        in_position={}; sig_dict={t:pd.Series(0,index=all_dates,dtype=int) for _,t,_ in COINS}
        last_rebalance=None
        for date in all_dates:
            if last_rebalance is not None and (date-last_rebalance).days<self.rebalance_days:
                continue
            last_rebalance=date
            should_exit=bool(regime_exit.loc[date]) if date in regime_exit.index else True
            can_enter=bool(entry_allowed.loc[date]) if date in entry_allowed.index else False
            if should_exit:
                for t in list(in_position):
                    if (date-in_position[t]).days>=self.min_hold_days:
                        if date in sig_dict[t].index: sig_dict[t].loc[date]=-1
                        del in_position[t]
            elif can_enter:
                for _,t,_ in COINS:
                    if t not in in_position:
                        if date in sig_dict[t].index: sig_dict[t].loc[date]=1
                        in_position[t]=date
        self.signals={t:sig_dict[t] for _,t,_ in COINS}

    def get_signals(self, ticker):
        return self.signals.get(ticker, pd.Series(dtype=int))

def run_is(full_data, is_data, btc_full, eth_full, sp, bt_fixed):
    strat=MVRVOnlyStrategy(**sp); strat.prepare(full_data,btc_full,eth_full)
    bt=AdvancedBacktester(initial_capital=100_000,**bt_fixed)
    return RiskReport(bt.run(is_data,strat))

def run_oos(full_data, combined_data, btc_full, eth_full, sp, bt_fixed):
    strat=MVRVOnlyStrategy(**sp); strat.prepare(full_data,btc_full,eth_full)
    bt=AdvancedBacktester(initial_capital=100_000,**bt_fixed)
    result=bt.run(combined_data,strat)
    eq=result.equity_curve; oos_eq=eq.loc[OOS_START:]
    oos_trades=[t for t in result.closed_trades if t.exit_date is not None and t.exit_date>=pd.Timestamp(OOS_START)]
    if len(oos_eq)==0: return None
    return RiskReport(AdvancedBacktestResult(equity_curve=oos_eq.tolist(),dates=oos_eq.index.tolist(),closed_trades=oos_trades,initial_capital=float(oos_eq.iloc[0])))

def main():
    print("\n"+"="*72)
    print("  ITERATION 56 — BTC MVRV EMA Trend + Vol Gate (Single On-Chain Signal)")
    print("="*72)
    btc_full=fetch_btc_full(); eth_full=fetch_eth_full()
    print(f"  BTC: {len(btc_full)} rows  last=${float(btc_full['Close'].iloc[-1]):,.2f}")
    
    # MVRV diagnostics
    mvrv=btc_full["MVRV"].ffill()
    mv_bull=ema_fn(mvrv,20)>ema_fn(mvrv,60)
    print("\n  BTC MVRV EMA(20)>EMA(60) trend by year:")
    for yr in range(2018,2025):
        v=mv_bull[mv_bull.index.year==yr]; m=mvrv[mvrv.index.year==yr]
        if len(v)==0: continue
        print(f"  {yr}: bull={100*v.mean():.0f}%  mvrv=[{m.min():.2f},{m.max():.2f}]")

    full_data={}
    for coin,label,seed in COINS:
        try:
            s=btc_full["Close"] if label=="BTC" else (eth_full["Close"] if label=="ETH" else fetch_close(coin))
            full_data[label]=synthesize_ohlcv(s,seed=seed)
            print(f"  {label}: {len(s)} rows")
        except Exception as e: print(f"  {label}: FAILED ({e})")
    if len(full_data)<4: print("  Insufficient data."); return
    
    is_data=slice_data(full_data,IS_START,IS_END)
    combined_data=slice_data(full_data,IS_START,OOS_END)
    bt_fixed=dict(max_positions=5,position_size_pct=0.20,atr_stop_multiplier=20.0,
                  atr_trail_multiplier=12.0,risk_per_trade_pct=0.20,short_term_tax_rate=TAX_RATE)
    
    strat_configs=[dict(act_short=as_,act_long=al,vol_lookback=30,vol_threshold=vt,
                        min_hold_days=mhd,rebalance_days=7)
                   for (as_,al) in [(20,60),(30,90)]
                   for vt in [0.60,0.80,1.00]
                   for mhd in [0,365]]
    
    print(f"\n  IS grid ({len(strat_configs)} configs):")
    print(f"  {'act':>7} {'vol_thr':>8} {'mhd':>4}  {'Mo%':>7} {'SR':>6} {'DD%':>8} {'N':>4} {'Hold':>5} {'score':>7}")
    print("  "+"-"*62)
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
            print(f"  {sp['act_short']}/{sp['act_long']:>3}  <{sp['vol_threshold']:.2f}  {sp.get('min_hold_days',0):>4}"
                  f"  {mo:>+7.2f}%  {sr:>6.2f}  {dd:>8.2f}%  {nt:>4}  {hld:>4.0f}d  {score:>7.2f}")
        except Exception as ex: print(f"  [skip] {ex}")
    
    results_is.sort(key=lambda x: x[0],reverse=True)
    if not results_is: print("  No valid IS configs."); return
    _,_,_,_,_,best_sp,best_m=results_is[0]
    mhd365=[s for s,_,_,_,_,sp,_ in results_is if sp.get('min_hold_days',0)==365]
    mhd0=[s for s,_,_,_,_,sp,_ in results_is if sp.get('min_hold_days',0)==0]
    print(f"\n  IS champion: act={best_sp['act_short']}/{best_sp['act_long']} vol<{best_sp['vol_threshold']} mhd={best_sp.get('min_hold_days',0)}")
    print(f"  IS gap: mhd=365 best={mhd365[0] if mhd365 else 0:.2f}  mhd=0 best={mhd0[0] if mhd0 else 0:.2f}"
          f"  → {'mhd=365 WINS ✓' if (mhd365 and mhd0 and mhd365[0]>mhd0[0]) else 'mhd=0 WINS (problem!)'}")
    
    print(f"\n  OOS results ({OOS_START}–{OOS_END}):")
    print(f"  {'act':>7} {'vol_thr':>8} {'mhd':>4}  {'Mo%':>8} {'SR':>6} {'DD%':>8} {'N':>4} {'Hold':>5} {'Eq$':>12}")
    print("  "+"-"*70)
    oos_results=[]
    for _,_,_,_,_,sp,_ in results_is:
        try:
            rpt=run_oos(full_data,combined_data,btc_full,eth_full,sp,bt_fixed)
            if rpt is None: continue
            m=rpt.full_metrics(); hld=m.get("avg_holding_days",0) or 0; sr=m.get("sharpe_ratio",0)
            oos_results.append((sr,sp,m,rpt))
            flag=" ← LTCG" if hld>=365 else ""
            print(f"  {sp['act_short']}/{sp['act_long']:>3}  <{sp['vol_threshold']:.2f}  {sp.get('min_hold_days',0):>4}"
                  f"  {m.get('monthly_return_pct',0):>+7.2f}%  {sr:>6.2f}  {m.get('max_drawdown_pct',0):>8.2f}%"
                  f"  {m.get('n_trades',0):>4}  {hld:>4.0f}d  ${m.get('final_equity',0):>11,.0f}{flag}")
        except Exception: pass
    
    if not oos_results: print("  No OOS results."); return
    is_champ_oos=next(((sp,m,rpt) for _,sp,m,rpt in oos_results if sp==best_sp),None)
    if is_champ_oos is None: print("  IS champion missing in OOS."); return
    ic_sp,ic_m,ic_rpt=is_champ_oos
    
    mo_is=ic_m.get("monthly_return_pct",0.0); sr_is=ic_m.get("sharpe_ratio",0.0)
    dd_is=ic_m.get("max_drawdown_pct",0.0); nt_is=ic_m.get("n_trades",0)
    hd_is=ic_m.get("avg_holding_days",0) or 0; cal_is=mo_is*12/abs(dd_is+1e-9)
    pass_mo=mo_is>=2.0; pass_sr=sr_is>=1.0; pass_dd=dd_is>-40.0; pass_cal=cal_is>=0.8
    pass_wr=ic_m.get("win_rate_pct",0.0)>=40.0; pass_pf=ic_m.get("profit_factor",0.0)>=1.3; pass_nt=nt_is>=5
    n_pass=sum([pass_mo,pass_sr,pass_dd,pass_cal,pass_wr,pass_pf,pass_nt])
    lbl=lambda ok: f"[{'PASS' if ok else 'FAIL'}]"
    print(f"\n{'='*72}\n  VERDICT — MVRV-Only Regime  OOS 2021-2024\n{'='*72}")
    print(f"    {lbl(pass_mo)}  Monthly >= 2.0%          {mo_is:>+.2f}%")
    print(f"    {lbl(pass_sr)}  Sharpe >= 1.0            {sr_is:.2f}")
    print(f"    {lbl(pass_dd)}  MaxDD > -40%             {dd_is:.2f}%")
    print(f"    {lbl(pass_cal)}  Calmar >= 0.8            {cal_is:.2f}")
    print(f"    {lbl(pass_wr)}  Win Rate >= 40%          {ic_m.get('win_rate_pct',0.0):.1f}%")
    print(f"    {lbl(pass_pf)}  Profit Factor >= 1.3     {ic_m.get('profit_factor',0.0):.2f}")
    print(f"    {lbl(pass_nt)}  N Trades >= 5            {nt_is}")
    print(f"\n  {n_pass}/7 criteria pass")
    tax_note="LTCG 20%" if hd_is>=365 else "STCG 35%"
    ltcg_adj=mo_is*(1-0.20)/(1-0.35) if hd_is>=365 else mo_is*(1-0.35)
    print(f"  Avg hold: {hd_is:.0f}d  ({tax_note})")
    print(f"  After-tax net: ~{ltcg_adj:+.2f}%/month")
    print(f"  IS-champion OOS: {mo_is:+.2f}%/mo  Sharpe {sr_is:.2f}  MaxDD {dd_is:.2f}%")

if __name__=="__main__": main()
