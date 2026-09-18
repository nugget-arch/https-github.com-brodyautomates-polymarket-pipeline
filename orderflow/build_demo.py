import re, pathlib
d = pathlib.Path('.')
def rd(p): return (d/p).read_text()

styles = rd('styles.css')
# strip exports from modules
def strip_export(js): return re.sub(r'^export ', '', js, flags=re.M)
mods = "\n".join(strip_export(rd(f)) for f in ['footprint.js','orderbook.js','heatmap.js','alerts.js'])
app = rd('app.js')
app = "\n".join(l for l in app.splitlines() if not l.strip().startswith('import '))

# body inner from index.html
html = rd('index.html')
body = html.split('<body>',1)[1].split('</body>',1)[0]
body = body.replace('<script type="module" src="app.js"></script>','')
# DEMO note in status bar
body = body.replace(
  'Binance L2 + trades en vivo · v<span id="st-ver">1.0.0</span>',
  '<b style="color:var(--poc)">DEMO</b> · datos simulados · versión real = Binance en vivo (localhost)')

SIM = r'''
/* ===== Market simulator (self-contained, no network) ===== */
const SYMBOL='BTCUSDT', TICK=1, IVMS=4000, WIN=26;
let price=68000+Math.random()*300, mom=0, uid=1;
let placed=new Set(), candles=[], cur=null;
const r4=(x)=>Math.round(x*1e4)/1e4;
function tsize(){ const r=Math.random(); return r>0.99?+(2+Math.random()*7).toFixed(2):r>0.9?+(0.2+Math.random()*0.9).toFixed(3):+(0.001+Math.random()*0.05).toFixed(3); }
function mkCandle(t){ return {t,o:price,h:price,l:price,c:price,v:0,taker:0,levels:new Map()}; }
function feed(c,p,q,isSell){ c.c=p; if(p>c.h)c.h=p; if(p<c.l)c.l=p; c.v+=q; if(!isSell)c.taker+=q; const idx=Math.round(p/TICK); let cell=c.levels.get(idx); if(!cell){cell={bid:0,ask:0};c.levels.set(idx,cell);} if(isSell)cell.bid+=q; else cell.ask+=q; }
function stepPrice(){ mom+=(Math.random()-0.5)*0.5; mom*=0.9; price+=mom*0.5+(Math.random()-0.5)*1.2; }
function genTrade(now){ stepPrice(); const isSell=Math.random()<(0.5-mom*0.12); return {p:Math.round(price),q:tsize(),m:isSell,T:now}; }
(function history(n){ const t0=Math.floor(Date.now()/IVMS)*IVMS-n*IVMS;
  for(let i=0;i<n;i++){ const bt=t0+i*IVMS; cur=mkCandle(bt); const N=60+Math.floor(Math.random()*60);
    for(let j=0;j<N;j++){ const tr=genTrade(bt+Math.floor(j/N*IVMS)); feed(cur,tr.p,tr.q,tr.m); } candles.push(cur); }
  cur=mkCandle(Math.floor(Date.now()/IVMS)*IVMS); candles.push(cur);
})(45);
function valueArea(prof,share){ if(!prof.length)return{vpoc:0,vah:0,val:0}; const tot=prof.reduce((s,p)=>s+p.vol,0); let poc=0; prof.forEach((p,i)=>{if(p.vol>prof[poc].vol)poc=i;}); let lo=poc,hi=poc,acc=prof[poc].vol,tg=tot*share;
  while(acc<tg&&(lo>0||hi<prof.length-1)){ const up=hi<prof.length-1?prof[hi+1].vol:-1, dn=lo>0?prof[lo-1].vol:-1; if(up>=dn){hi++;acc+=prof[hi].vol;}else{lo--;acc+=prof[lo].vol;} }
  return {vpoc:prof[poc].price,vah:prof[hi].price,val:prof[lo].price}; }
function seed(){ const cs=candles.map(c=>({t:c.t,o:c.o,h:c.h,l:c.l,c:c.c,v:r4(c.v),delta:r4(2*c.taker-c.v)}));
  const agg=new Map(); for(const c of candles)for(const[idx,cell]of c.levels){let a=agg.get(idx);if(!a){a={bid:0,ask:0};agg.set(idx,a);}a.bid+=cell.bid;a.ask+=cell.ask;}
  const profile=[...agg.entries()].sort((x,y)=>x[0]-y[0]).map(([idx,a])=>({price:idx*TICK,buy:r4(a.ask),sell:r4(a.bid),vol:r4(a.ask+a.bid)}));
  const va=valueArea(profile,0.7), fpN=Math.min(18,candles.length);
  const footprints=candles.slice(-fpN).map(c=>{ const rows=[...c.levels.entries()].sort((a,b)=>a[0]-b[0]).map(([idx,cell])=>[idx,r4(cell.bid),r4(cell.ask)]); let buy=0,sell=0; for(const cell of c.levels.values()){buy+=cell.ask;sell+=cell.bid;} return {t:c.t,o:c.o,h:c.h,l:c.l,c:c.c,rows,buy:r4(buy),sell:r4(sell),delta:r4(buy-sell),poc:0,trades:0}; });
  const prices=profile.map(p=>p.price);
  return {symbol:SYMBOL,interval:'5s',intervalMs:IVMS,basetick:TICK,candles:cs,footprints,vpoc:va.vpoc,vah:va.vah,val:va.val,profile,priceLow:Math.min(...prices),priceHigh:Math.max(...prices),lastPrice:cs[cs.length-1].c,cumDelta:0,totalVol:0,serverTime:Date.now()}; }
function bsize(i){ return +((i<6?1+Math.random()*4:0.05+Math.random()*1.5)).toFixed(2); }
function bookSnap(){ const mid=Math.round(price); placed=new Set(); const bids=[],asks=[]; for(let i=1;i<=WIN;i++){ const bp=mid-i,ap=mid+i; bids.push([bp,bsize(i)]); asks.push([ap,bsize(i)]); placed.add(bp); placed.add(ap);} return {lastUpdateId:uid,bids,asks}; }
function tradesSeed(){ const arr=[],tt=Date.now(); for(let i=0;i<80;i++)arr.push({p:Math.round(price+(Math.random()-0.5)*6),q:tsize(),m:Math.random()<0.5,T:tt-i*300}); return {trades:arr}; }
function depthDiff(){ const mid=Math.round(price); const b=[],a=[]; for(let p=mid-80;p<=mid+80;p++){ if(p<mid){b.push([p,(mid-p)<=WIN?bsize(mid-p):0]);a.push([p,0]);} else if(p>mid){a.push([p,(p-mid)<=WIN?bsize(p-mid):0]);b.push([p,0]);} } const U=uid+1,u=uid+1;uid=u; return {e:'depthUpdate',U,u,b,a}; }
function klineMsg(c,x){ return {e:'kline',k:{t:c.t,o:c.o,h:c.h,l:c.l,c:c.c,v:c.v,V:c.taker,x}}; }
/* fetch shim */
const _fetch = window.fetch ? window.fetch.bind(window) : null;
window.fetch = async(url)=>{ const s=String(url), j=(o)=>({ok:true,status:200,json:async()=>o});
  if(s.includes('/api/seed'))return j(seed()); if(s.includes('/api/depth'))return j(bookSnap());
  if(s.includes('/api/trades'))return j(tradesSeed()); if(s.includes('/api/config'))return j({version:'1.0.0-demo',symbols:[SYMBOL],intervals:['5s']});
  if(s.includes('/api/health'))return j({status:'ok'}); return _fetch?_fetch(url):j({}); };
/* fake websocket */
class FakeWS{ constructor(){ this.readyState=0; setTimeout(()=>{this.readyState=1;this.onopen&&this.onopen();this._start();},60);}
  send(){} close(){this.readyState=3;this._stop();this.onclose&&this.onclose();}
  _emit(m){ this.onmessage&&this.onmessage({data:JSON.stringify({data:m})}); }
  _start(){ const s=this;
    this.ti=setInterval(()=>{ const now=Date.now(),bt=Math.floor(now/IVMS)*IVMS; if(!cur||cur.t!==bt){ if(cur)s._emit(klineMsg(cur,true)); cur=mkCandle(bt);} const k=1+Math.floor(Math.random()*3); for(let i=0;i<k;i++){const tr=genTrade(now);feed(cur,tr.p,tr.q,tr.m);s._emit({e:'aggTrade',p:tr.p,q:tr.q,m:tr.m,T:now});} },140);
    this.tk=setInterval(()=>{cur&&s._emit(klineMsg(cur,false));},260);
    this.td=setInterval(()=>{s._emit(depthDiff());},220); }
  _stop(){ clearInterval(this.ti);clearInterval(this.tk);clearInterval(this.td); } }
window.WebSocket=FakeWS;
'''

resp = "\n@media (max-width:860px){.rail{display:none}.dock{display:none}.toolbar{flex-wrap:wrap;height:auto}.app{grid-template-rows:auto 1fr 24px}}\n"

out = ("<title>OrderFlow Pro</title>\n<style>\n"+styles+resp+"</style>\n"+body+
       '\n<script type="module">\n'+mods+"\n"+SIM+"\n"+app+"\n</script>\n")
pathlib.Path('demo.html').write_text(out)
print("demo.html bytes:", len(out))
