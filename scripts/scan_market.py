"""Autonomous public-data scanner for liquid Bybit USDT perpetual markets."""
from __future__ import annotations
import asyncio, json, os, statistics
from datetime import datetime, timezone
from pathlib import Path
from typing import Any
import httpx

BASE=os.getenv("BYBIT_BASE_URL","https://api.bybit.com")
TOP_N=max(10,min(int(os.getenv("SCAN_TOP_N","50")),100))
MIN_TURNOVER=float(os.getenv("MIN_TURNOVER_USDT","5000000"))
CONCURRENCY=max(2,min(int(os.getenv("SCAN_CONCURRENCY","6")),10))
OUT=Path("scan-output")
TFS={"5m":"5","15m":"15","1h":"60","4h":"240"}
MS={"5m":300000,"15m":900000,"1h":3600000,"4h":14400000}

def now(): return datetime.now(timezone.utc).isoformat()
def num(x):
    try:
        n=float(x or 0)
        return n if n==n and abs(n)!=float("inf") else 0.0
    except (TypeError,ValueError): return 0.0
def avg(xs): return statistics.fmean(xs) if xs else 0.0
def ema(xs,p):
    if not xs:return 0.0
    k=2/(p+1); e=xs[0]
    for x in xs[1:]:e=k*x+(1-k)*e
    return e
def candles(raw,tf):
    out=[]
    for r in reversed(raw):
        try:
            c={"t":int(r[0]),"o":float(r[1]),"h":float(r[2]),"l":float(r[3]),"c":float(r[4]),"v":float(r[5])}
            if c["c"]>0 and c["h"]>=c["l"] and c["v"]>=0:out.append(c)
        except (TypeError,ValueError,IndexError):pass
    if out and out[-1]["t"]+MS[tf]>int(datetime.now(timezone.utc).timestamp()*1000):out.pop()
    return out
def analyze(cs):
    if len(cs)<30:return {"trend":"UNKNOWN","sweep":"UNKNOWN","volume_ratio":0.0,"atr":0.0}
    closes=[c["c"] for c in cs]; last=cs[-1]
    fast,slow=ema(closes[-60:],20),ema(closes[-60:],50)
    trend="BULLISH" if closes[-1]>fast>slow else "BEARISH" if closes[-1]<fast<slow else "MIXED"
    prior=cs[-13:-1]; hi=max(c["h"] for c in prior); lo=min(c["l"] for c in prior)
    sweep="SELL_SIDE_SWEEP_RECLAIM" if last["l"]<lo and last["c"]>lo else "BUY_SIDE_SWEEP_REJECTION" if last["h"]>hi and last["c"]<hi else "NONE"
    tr=[]
    for i in range(max(1,len(cs)-14),len(cs)):
        c,p=cs[i],cs[i-1];tr.append(max(c["h"]-c["l"],abs(c["h"]-p["c"]),abs(c["l"]-p["c"])))
    return {"trend":trend,"sweep":sweep,"volume_ratio":last["v"]/max(avg([c["v"] for c in cs[-21:-1]]),1e-12),"atr":avg(tr),"close":last["c"]}
async def get(client,path,params):
    r=await client.get(BASE+path,params=params);r.raise_for_status();j=r.json()
    if j.get("retCode")!=0:raise ValueError(j.get("retMsg","Bybit API error"))
    return j.get("result",{})
async def scan(client,sem,ticker):
    symbol=ticker["symbol"]; price=num(ticker.get("lastPrice"))
    out={"symbol":symbol,"price":price,"turnover24h":num(ticker.get("turnover24h")),"change24hPct":num(ticker.get("price24hPcnt"))*100,"direction":"WAIT","score":0,"quality":"LOW","status":"WAIT","reasons":[],"scanned_at":now(),"error":None}
    try:
        async with sem:
            async def kl(tf):return tf,candles((await get(client,"/v5/market/kline",{"category":"linear","symbol":symbol,"interval":TFS[tf],"limit":"100"})).get("list",[]),tf)
            async def book():return await get(client,"/v5/market/orderbook",{"category":"linear","symbol":symbol,"limit":"50"})
            async def fund():return await get(client,"/v5/market/funding/history",{"category":"linear","symbol":symbol,"limit":"1"})
            async def oi():return await get(client,"/v5/market/open-interest",{"category":"linear","symbol":symbol,"intervalTime":"1h","limit":"2"})
            data=await asyncio.gather(*(kl(tf) for tf in TFS),book(),fund(),oi(),return_exceptions=True)
        tfdata={}
        for item in data[:4]:
            if isinstance(item,Exception):raise item
            label,cs=item;tfdata[label]=analyze(cs)
        book,funding,oi=data[4:]
        book={} if isinstance(book,Exception) else book
        funding={} if isinstance(funding,Exception) else funding
        oi={} if isinstance(oi,Exception) else oi
        bids=sum(num(x[1]) for x in book.get("b",[])[:20] if len(x)>1);asks=sum(num(x[1]) for x in book.get("a",[])[:20] if len(x)>1)
        imbalance=(bids-asks)/(bids+asks) if bids+asks else 0
        fr=(funding.get("list") or [{}])[0];funding_rate=num(fr.get("fundingRate"))
        oirows=list(reversed(oi.get("list",[])))
        oi_change=(num(oirows[-1].get("openInterest"))-num(oirows[0].get("openInterest")))/max(num(oirows[0].get("openInterest")),1e-12) if len(oirows)>1 else 0
        t5,t15,t1,t4=(tfdata[x] for x in ("5m","15m","1h","4h"));score=0;reasons=[]
        if t15["trend"]==t1["trend"]=="BULLISH" and t4["trend"]!="BEARISH":score+=2;reasons.append("15m/1h bullish alignment")
        if t15["trend"]==t1["trend"]=="BEARISH" and t4["trend"]!="BULLISH":score-=2;reasons.append("15m/1h bearish alignment")
        if t5["sweep"]=="SELL_SIDE_SWEEP_RECLAIM":score+=2;reasons.append("5m sell-side sweep and reclaim")
        elif t5["sweep"]=="BUY_SIDE_SWEEP_REJECTION":score-=2;reasons.append("5m buy-side sweep and rejection")
        if imbalance>=.15:score+=1;reasons.append("bid-side order-book imbalance")
        elif imbalance<=-.15:score-=1;reasons.append("ask-side order-book imbalance")
        if t5["volume_ratio"]>=1.5:score+=1 if t5.get("close",price)>=price else -1;reasons.append("5m volume expansion")
        if funding_rate>.0005 and score>0:score-=1;reasons.append("positive funding crowding penalty")
        elif funding_rate<-.0005 and score<0:score+=1;reasons.append("negative funding crowding adjustment")
        if oi_change>.02 and abs(score)>=2:reasons.append("open interest up over 2% in hourly samples")
        direction="LONG" if score>=4 else "SHORT" if score<=-4 else "WAIT"
        atr=t5.get("atr",0);stop=(price-1.5*atr if direction=="LONG" else price+1.5*atr) if direction!="WAIT" and atr>0 else None
        risk=abs(price-stop) if stop is not None else 0
        targets=([price+risk*x for x in (1.5,2,3)] if direction=="LONG" else [price-risk*x for x in (1.5,2,3)] if direction=="SHORT" else [])
        out.update({"direction":direction,"score":score,"quality":"HIGH_CONFLUENCE" if abs(score)>=5 else "MEDIUM_CONFLUENCE" if abs(score)>=3 else "LOW","status":"CANDIDATE" if direction!="WAIT" else "WAIT","timeframes":tfdata,"orderbookImbalance":round(imbalance,5),"fundingRate":funding_rate,"openInterestChange":oi_change,"entryReference":price if direction!="WAIT" else None,"stopPreview":stop,"targetPreview":targets,"reasons":reasons,"scanned_at":now()})
    except Exception as e:out.update({"status":"DATA_ERROR","quality":"UNKNOWN","error":type(e).__name__+": "+str(e)})
    return out

async def main():
    started=now();OUT.mkdir(exist_ok=True)
    async with httpx.AsyncClient(timeout=httpx.Timeout(18),headers={"User-Agent":"ZENVRA-Autonomous-Research/1.0"}) as client:
        universe=(await get(client,"/v5/market/tickers",{"category":"linear"})).get("list",[])
        universe=[x for x in universe if x.get("symbol","").endswith("USDT") and num(x.get("lastPrice"))>0 and num(x.get("turnover24h"))>=MIN_TURNOVER]
        universe.sort(key=lambda x:num(x.get("turnover24h")),reverse=True);selected=universe[:TOP_N]
        sem=asyncio.Semaphore(CONCURRENCY)
        results=await asyncio.gather(*(scan(client,sem,x) for x in selected))
    results.sort(key=lambda x:(x["direction"]!="WAIT",abs(x["score"]),x["turnover24h"]),reverse=True)
    candidates=[x for x in results if x["status"]=="CANDIDATE"]
    report={"started_at":started,"finished_at":now(),"source":"Bybit public linear USDT perpetual API","eligible_universe_count":len(universe),"scanned_count":len(results),"selection":"Top "+str(TOP_N)+" by turnover; min 24h turnover USDT "+str(MIN_TURNOVER),"mode":"research-only; no orders placed","model":"multi-factor confluence rules v1; not trained ML","results":results}
    (OUT/"scan-report.json").write_text(json.dumps(report,indent=2),encoding="utf-8")
    lines=["# ZENVRA AI — Autonomous Market Scan","",f"- Started UTC: {started}",f"- Finished UTC: {report['finished_at']}",f"- Eligible USDT perpetual universe: {len(universe)}",f"- Analyzed: {len(results)}",f"- Candidates passing rules: {len(candidates)}","- Source: Bybit public linear Futures API","- Engines: multi-timeframe trend, liquidity sweeps, order-book imbalance, funding, volume and open interest","- Confluence labels are NOT calibrated probabilities; not trained AI; no orders are placed.","","## Highest-confluence candidates","","| Symbol | Direction | Score | Quality | Price | Turnover USDT | Evidence |","|---|---|---:|---|---:|---:|---|"]
    for x in candidates[:25]:lines.append(f"| {x['symbol']} | {x['direction']} | {x['score']}/8 | {x['quality']} | {x['price']:.8g} | {x['turnover24h']:.0f} | {'; '.join(x['reasons'])} |")
    if not candidates:lines.append("| — | WAIT | — | No candidates passed the confluence gate | — | — | No trade is a valid outcome |")
    lines += ["","## Full coverage","","| Symbol | Direction | Score | Status | Error |","|---|---|---:|---|---|"]
    for x in results:lines.append(f"| {x['symbol']} | {x['direction']} | {x['score']} | {x['status']} | {(x['error'] or '').replace('|','/')} |")
    lines += ["","## Limits","","- Scans the most liquid eligible Bybit USDT perpetuals; does not analyze every exchange or every asset.","- Backtesting, fee/slippage modelling, calibrated probability, durable online learning and walk-forward validation are not implemented.","- Paper-test and validate independently before relying on a signal.",""]
    (OUT/"scan-report.md").write_text("\n".join(lines),encoding="utf-8")
    print(f"eligible={len(universe)} scanned={len(results)} candidates={len(candidates)}")
    print("\n".join(lines[:24]))
if __name__=="__main__":asyncio.run(main())
