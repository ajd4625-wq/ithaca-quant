(function(){
'use strict';
// Content script loads only on explicitly supported finance domains.
// No pixel/screen recording; read ticker from URL and request local analysis.
const RX=/^[A-Z][A-Z0-9.\-]{0,11}$/;
function getTicker(){
  let u;try{u=new URL(location.href)}catch{return null}
  const h=u.hostname,p=u.pathname;
  let m=null;
  if(h.endsWith('finance.yahoo.com'))m=p.match(/^\/quote\/([A-Za-z][A-Za-z0-9.\-]{0,11})(?:\/|$)/);
  else if(h==='www.google.com')m=p.match(/^\/finance\/quote\/([A-Za-z][A-Za-z0-9.\-]{0,11})/);
  else if(h.endsWith('tradingview.com')){
    m=p.match(/^\/symbols\/(?:[A-Za-z0-9]+-)?([A-Za-z][A-Za-z0-9.\-]{0,11})(?:\/|$)/);
    if(!m){const s=u.searchParams.get('symbol');if(s){const a=s.split(':').at(-1)?.toUpperCase();return RX.test(a)?a:null}}
  }
  else if(h==='www.marketwatch.com')m=p.match(/^\/investing\/stock\/([A-Za-z][A-Za-z0-9.\-]{0,11})/);
  else if(h==='www.nasdaq.com')m=p.match(/^\/market-activity\/stocks\/([A-Za-z][A-Za-z0-9.\-]{0,11})/);
  const s=m?.[1]?.toUpperCase();return RX.test(s)?s:null;
}
const uid='iq-quant-shadow-host';
let root=null,host=null, enabled=false,visible=true,priorUrl='',lastAnalyze=0,working=false;
function create(){
  if(host)return;
  host=document.createElement('div');host.id=uid;
  host.style.cssText='all:initial;position:fixed;right:20px;bottom:20px;z-index:2147483645;font-family:system-ui,sans-serif;';
  root=host.attachShadow({mode:'closed'});
  const sheet=document.createElement('style');sheet.textContent=`
    :host{all:initial} .card{box-sizing:border-box;width:266px;padding:15px 16px;background:#0b172e;color:#eaf3ff;border:1px solid #375078;box-shadow:0 10px 35px #030a1d99;border-radius:17px;font:13px system-ui,sans-serif;}
    .top{display:flex;gap:8px;align-items:center;justify-content:space-between}.logo{letter-spacing:1px;color:#87bdff;font-size:10px;font-weight:800}.close{color:#89a5c4;background:transparent;border:0;font-size:18px;cursor:pointer}
    .sym{font-size:23px;font-weight:800;margin-top:10px}.signal{font-size:12px;font-weight:800;background:#223554;padding:7px 8px;border-radius:8px;margin-top:10px}
    .signal.up{background:#113d39;color:#63e2bb}.signal.down{background:#512936;color:#ffa5b9}.signal.neutral{background:#2c3651;color:#d3e1ff}
    .price{color:#afc6e3;margin-top:7px}.muted{color:#849fbe;font-size:10px;margin-top:7px;line-height:1.45}
    .btn{width:100%;background:#3488f3;color:white;border:0;border-radius:10px;padding:10px;font-weight:700;cursor:pointer;margin-top:12px}
    .loading{opacity:.65}
  `;
  const c=document.createElement('div');c.className='card';
  c.innerHTML=`<div class="top"><span class="logo">◈ ITHACA QUANT · v3.2</span><button class="close" title="Hide overlay">×</button></div><div class="sym">—</div><div class="price">Opt-in research</div><div class="signal neutral">Checking model…</div><div class="muted">Historical daily research • not live quotes</div><button class="btn">Open full analysis</button>`;
  root.append(sheet,c);
  root.querySelector('.close').addEventListener('click',()=>{visible=false;host.remove();host=null;root=null;chrome.storage.local.set({overlayVisible:false});});
  root.querySelector('.btn').addEventListener('click',()=>chrome.runtime.sendMessage({type:'OPEN_PANEL'},()=>void chrome.runtime.lastError));
  (document.body||document.documentElement).appendChild(host);
}
function update(data){
 if(!root)return;
 root.querySelector('.sym').textContent=data.ticker||'—';
 root.querySelector('.price').textContent=data.price?`Last completed close $${Number(data.price).toFixed(2)} · ${data.asof}`:'No verified price';
 const label=root.querySelector('.signal');label.textContent=data.signal?.label||'NO SIGNAL';
 label.className='signal '+(/ENTRY WATCH/.test(label.textContent)?'up':/EXIT RISK|UNDERPERFORMANCE/.test(label.textContent)?'down':'neutral');
 root.querySelector('.muted').textContent=`${data.signal?.signal_strength==null?'Signal strength withheld':`Signal strength ${data.signal.signal_strength}/100 (not probability)`} · source: ${data.data_integrity?.mode==='current_feed_research_only'?'current feed, NOT PIT':'unverified'} · 3 agents · 2 retries · ${data.cache_hit?'cached':'refreshed'}`;
}
function error(msg){if(!root)return;root.querySelector('.signal').textContent='DATA UNAVAILABLE';root.querySelector('.signal').className='signal down';root.querySelector('.muted').textContent=(msg||'Start the local server').slice(0,125);}
function scan(force=false){
 if(!enabled||!visible || document.visibilityState==='hidden'){if(host){host.remove();host=null;root=null}return}
 const ticker=getTicker();if(!ticker){if(host){host.remove();host=null;root=null}return}
 const changed=location.href!==priorUrl;
 if(!force&&!changed&&Date.now()-lastAnalyze<45000)return;
 if(working)return;
 priorUrl=location.href;lastAnalyze=Date.now();working=true;
 create();root.querySelector('.sym').textContent=ticker;
 chrome.runtime.sendMessage({type:'ANALYZE',ticker},res=>{
   working=false;if(chrome.runtime.lastError)return error(chrome.runtime.lastError.message);
   if(ticker!==getTicker())return;
   if(!res||res.error)return error(res?.error);
   update(res.data);
 });
}
chrome.storage.local.get({monitor:false,overlayVisible:true}).then(x=>{enabled=x.monitor;visible=x.overlayVisible;scan(true)});
chrome.storage.onChanged.addListener((changes,area)=>{
 if(area!=='local')return;
 if(changes.monitor)enabled=Boolean(changes.monitor.newValue);
 if(changes.overlayVisible)visible=Boolean(changes.overlayVisible.newValue);
 scan(true);
});
document.addEventListener('visibilitychange',()=>scan(true));
setInterval(()=>scan(false),3000); // very cheap URL check; network max once /45s per active tab
})();
