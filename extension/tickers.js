// Deliberately narrow: only known provider URL conventions, never scrape private page content.
const IQ_TICKER_RX=/^[A-Z][A-Z0-9.\-]{0,11}$/;
function iqTicker(href){
 let url;try{url=new URL(href)}catch{return null}
 const h=url.hostname.toLowerCase(),p=url.pathname;
 let m=null;
 if(h==='finance.yahoo.com'||h.endsWith('.finance.yahoo.com')) m=p.match(/^\/quote\/([A-Za-z][A-Za-z0-9.\-]{0,11})(?:\/|$)/);
 else if(h==='www.google.com'&&p.startsWith('/finance/'))m=p.match(/^\/finance\/quote\/([A-Za-z][A-Za-z0-9.\-]{0,11})(?::[^/]+)?/);
 else if(h==='www.tradingview.com'||h.endsWith('.tradingview.com')){
   m=p.match(/^\/symbols\/(?:[A-Za-z0-9]+-)?([A-Za-z][A-Za-z0-9.\-]{0,11})(?:\/|$)/);
   if(!m){ const s=url.searchParams.get('symbol');if(s){const sym=s.split(':').at(-1)?.toUpperCase();return IQ_TICKER_RX.test(sym)?sym:null} }
 }
 else if(h==='www.marketwatch.com')m=p.match(/^\/investing\/stock\/([A-Za-z][A-Za-z0-9.\-]{0,11})(?:\/|$)/);
 else if(h==='www.nasdaq.com')m=p.match(/^\/market-activity\/stocks\/([A-Za-z][A-Za-z0-9.\-]{0,11})(?:\/|$)/);
 const sym=m?.[1]?.toUpperCase()||null;
 return sym&&IQ_TICKER_RX.test(sym)?sym:null;
}
