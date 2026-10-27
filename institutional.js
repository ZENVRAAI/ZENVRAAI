/* ZENVRA AI Institutional Research Engine — public data only, no execution. */
(()=>{'use strict';
const API='https://api.bybit.com/v5/market/';
const $=id=>document.getElementById(id);
const fmt=(n,d=4)=>Number.isFinite(n)?n.toLocaleString('en-US',{maximumFractionDigits:d}):'—';
const pct=n=>Number.isFinite(n)?(n*100).toFixed(2)+'%':'—';
const esc=s=>String(s).replace(/[&<>"]/g,c=>({'&':'&amp;','<':'&lt;','>':'&gt;','"':'&quot;'}[c]));
const status=(label,cls='partial')=>'<span class="layer-status '+cls+'">'+label+'</span>';
function mean(a){return a.length?a.reduce((x,y)=>x+y,0)/a.length:0}
function candlesFrom(rows){return (rows||[]).slice().reverse().map(r=>({t:+r[0],o:+r[1],h:+r[2],l:+r[3],c:+r[4],v:+r[5]})).filter(x=>[x.o,x.h,x.l,x.c,x.v].every(Number.isFinite)&&x.c>0)}
function ema(a,p){if(!a.length)return 0;let e=a[0],k=2/(p+1);for(let i=1;i<a.length;i++)e=a[i]*k+e*(1-k);return e}
function atr(cs,p=14){if(cs.length<p+1)return 0;return mean(cs.slice(-p).map((c,i)=>{const prev=cs[cs.length-p-1+i].c;return Math.max(c.h-c.l,Math.abs(c.h-prev),Math.abs(c.l-prev))}))}
function swing(cs,look=5){const a=cs.slice(-look-1,-1);return {high:Math.max(...a.map(c=>c.h)),low:Math.min(...a.map(c=>c.l))}}
async function get(path,params){const u=new URL(API+path);Object.entries(params).forEach(([k,v])=>u.searchParams.set(k,v));const res=await fetch(u,{cache:'no-store'});if(!res.ok)throw Error(path+' HTTP '+res.status);const j=await res.json();if(j.retCode!==0)throw Error(j.retMsg||path+' error');return j.result}
async function analyze(symbol){
 const [k5,k15,k60,k240,book,fund,oi,ticker]=await Promise.all([
 get('kline',{category:'linear',symbol,interval:'5',limit:'100'}),
 get('kline',{category:'linear',symbol,interval:'15',limit:'100'}),
 get('kline',{category:'linear',symbol,interval:'60',limit:'100'}),
 get('kline',{category:'linear',symbol,interval:'240',limit:'100'}),
 get('orderbook',{category:'linear',symbol,limit:'50'}),
 get('funding/history',{category:'linear',symbol,limit:'1'}),
 get('open-interest',{category:'linear',symbol,intervalTime:'1h',limit:'2'}),
 get('tickers',{category:'linear'})
 ]);
 const c5=candlesFrom(k5.list),c15=candlesFrom(k15.list),c60=candlesFrom(k60.list),c240=candlesFrom(k240.list);
 if([c5,c15,c60,c240].some(c=>c.length<25))throw Error('Insufficient candles on one or more timeframes');
 const last=c5.at(-1),price=last.c,range=swing(c5,10),a=atr(c5),recent=c5.slice(-20),volRatio=last.v/Math.max(mean(recent.slice(0,-1).map(c=>c.v)),1e-12);
 const tf=(cs)=>{const cl=cs.map(c=>c.c);return {dir:cl.at(-1)>ema(cl.slice(-60),20)&&ema(cl.slice(-60),20)>ema(cl.slice(-60),50)?'BULLISH':cl.at(-1)<ema(cl.slice(-60),20)&&ema(cl.slice(-60),20)<ema(cl.slice(-60),50)?'BEARISH':'MIXED',e20:ema(cl.slice(-60),20),e50:ema(cl.slice(-60),50)}};
 const t15=tf(c15),t60=tf(c60),t240=tf(c240);
 const previous=c5.slice(-12,-1),priorHigh=Math.max(...previous.map(c=>c.h)),priorLow=Math.min(...previous.map(c=>c.l));
 const sweepDown=last.l<priorLow&&last.c>priorLow, sweepUp=last.h>priorHigh&&last.c<priorHigh;
 const bids=(book.b||[]).slice(0,20).reduce((s,r)=>s+(+r[1]||0),0),asks=(book.a||[]).slice(0,20).reduce((s,r)=>s+(+r[1]||0),0);
 const imbalance=(bids+asks)>0?(bids-asks)/(bids+asks):0;
 const funding=+(fund.list?.[0]?.fundingRate||0),oiList=(oi.list||[]).slice().reverse(),oiDelta=oiList.length>1?(+oiList.at(-1).openInterest-(+oiList[0].openInterest))/(+oiList[0].openInterest||1):0;
 const alignedBull=t15.dir==='BULLISH'&&t60.dir==='BULLISH'&&t240.dir!=='BEARISH';
 const alignedBear=t15.dir==='BEARISH'&&t60.dir==='BEARISH'&&t240.dir!=='BULLISH';
 let score=0,reasons=[];
 if(alignedBull){score+=2;reasons.push('15m/1h trend aligned bullish')}
 if(alignedBear){score-=2;reasons.push('15m/1h trend aligned bearish')}
 if(sweepDown){score+=2;reasons.push('5m downside liquidity sweep and reclaim')}
 if(sweepUp){score-=2;reasons.push('5m upside liquidity sweep and rejection')}
 if(imbalance>.12){score+=1;reasons.push('Top-20 book bid imbalance')}
 if(imbalance<-.12){score-=1;reasons.push('Top-20 book ask imbalance')}
 if(volRatio>=1.5){score+=Math.sign(price-last.o);reasons.push('5m volume expansion')}
 if(funding>.0005&&alignedBull){score-=1;reasons.push('Crowded positive funding risk')}
 if(funding<-.0005&&alignedBear){score+=1;reasons.push('Crowded negative funding risk')}
 if(oiDelta>.02&&Math.abs(score)>=2)reasons.push('Open interest rising >2% across returned samples');
 const direction=score>=3?'LONG':score<=-3?'SHORT':'WAIT';
 const entry=price,stop=direction==='LONG'?Math.min(last.l,price-a*1.5):direction==='SHORT'?Math.max(last.h,price+a*1.5):null;
 const risk=stop===null?0:Math.abs(entry-stop),tp=direction==='WAIT'||risk<=0?[]:[1.5,2,3].map(r=>direction==='LONG'?entry+r*risk:entry-r*risk);
 const tickerRow=(ticker.list||[]).find(x=>x.symbol===symbol);
 return {symbol,price:+(tickerRow?.lastPrice||price),score,maximum:8,direction,confidence:Math.min(95,Math.round(Math.abs(score)/8*100)),tf:{'15m':t15.dir,'1h':t60.dir,'4h':t240.dir},sweep:sweepDown?'SELL-SIDE SWEEP':sweepUp?'BUY-SIDE SWEEP':'NO CONFIRMED SWEEP',imbalance,funding,oiDelta,volRatio,atr:a,entry,stop,tp,reasons,asOf:new Date().toISOString(),note:'Rule-based research score; not a trained AI model or validated trading edge.'};
}
function render(a){
 const dirCls=a.direction==='LONG'?'positive':a.direction==='SHORT'?'negative':'muted';
 $('instSymbol').textContent=a.symbol;
 $('instPrice').textContent='$'+fmt(a.price,8);
 $('instSignal').innerHTML=status(a.direction,a.direction==='WAIT'?'partial':'');
 $('instScore').textContent=a.score+' / 8';
 $('instScoreBar').style.width=Math.min(100,Math.abs(a.score)/8*100)+'%';
 $('instScoreBar').style.background=a.direction==='LONG'?'var(--green)':a.direction==='SHORT'?'var(--red)':'var(--cyan)';
 $('instTrend').innerHTML=Object.entries(a.tf).map(([tf,d])=>'<div class="inst-tf"><span>'+tf+'</span>'+status(d,d==='BULLISH'?'':d==='BEARISH'?'offline':'partial')+'</div>').join('');
 $('instSweep').textContent=a.sweep;
 $('instBook').textContent=(a.imbalance*100).toFixed(1)+'%';
 $('instBook').className=a.imbalance>.12?'positive':a.imbalance<-.12?'negative':'';
 $('instFunding').textContent=pct(a.funding);
 $('instOI').textContent=(a.oiDelta*100).toFixed(2)+'%';
 $('instVolume').textContent=a.volRatio.toFixed(2)+'x';
 $('instATR').textContent=fmt(a.atr,8);
 $('instEntry').textContent=a.direction==='WAIT'?'—':'$'+fmt(a.entry,8);
 $('instSL').textContent=a.stop===null?'—':'$'+fmt(a.stop,8);
 $('instTP').textContent=a.tp.length?a.tp.map((p,i)=>'TP'+(i+1)+' $'+fmt(p,8)).join(' · '):'—';
 $('instReasons').innerHTML=(a.reasons.length?a.reasons:['Confluence below threshold; stand aside.']).map(x=>'<li>'+esc(x)+'</li>').join('');
 $('instTime').textContent='Updated '+new Date(a.asOf).toLocaleTimeString();
 $('instNotice').textContent=a.note;
}
async function run(){const symbol=($('instSymbolInput').value||'BTCUSDT').trim().toUpperCase();if(!/^[A-Z0-9]{4,24}$/.test(symbol)){$('instNotice').textContent='Enter a valid Bybit linear symbol such as BTCUSDT.';return}
 $('instRun').disabled=true;$('instRun').textContent='Analyzing…';$('instNotice').textContent='Collecting candles, order book, funding and open interest…';
 try{const a=await analyze(symbol);render(a);save(a)}catch(e){$('instSignal').textContent='DATA ERROR';$('instNotice').textContent='Analysis unavailable: '+e.message+'. Try a valid linear Futures symbol.'}finally{$('instRun').disabled=false;$('instRun').textContent='Run institutional scan'}}
function save(a){try{const key='zenvra-inst-signals-v1',items=JSON.parse(localStorage.getItem(key)||'[]');items.push({time:a.asOf,symbol:a.symbol,direction:a.direction,score:a.score,price:a.price,stop:a.stop,tp:a.tp});localStorage.setItem(key,JSON.stringify(items.slice(-100)));drawHistory()}catch(e){}}
function drawHistory(){try{const items=JSON.parse(localStorage.getItem('zenvra-inst-signals-v1')||'[]').slice().reverse().slice(0,8);$('instHistory').innerHTML=items.map(x=>'<tr><td>'+new Date(x.time).toLocaleTimeString()+'</td><td>'+esc(x.symbol)+'</td><td>'+esc(x.direction)+'</td><td>'+x.score+'/8</td><td>$'+fmt(+x.price,8)+'</td></tr>').join('')||'<tr><td colspan="5">No scans recorded on this device.</td></tr>'}catch(e){}}
function init(){if(!$('instRun'))return;$('instRun').addEventListener('click',run);$('instSymbolInput').addEventListener('keydown',e=>{if(e.key==='Enter')run()});drawHistory();run()}
if(document.readyState==='loading')document.addEventListener('DOMContentLoaded',init);else init();
})();