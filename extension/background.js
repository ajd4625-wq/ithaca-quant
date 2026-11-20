importScripts('tickers.js');
const BASE='http://127.0.0.1:8765';
const MAX_RETRIES=0; // Backend owns the global 2-retry budget; do not multiply attempts in Chrome.
async function request(path, timeoutMs=35000){
 // Exactly one browser-to-bridge attempt. The Python model/provider layer
 // owns the 2 retry opportunities; never multiply backend attempts here.
 let last;
 for(let attempt=0;attempt<=MAX_RETRIES;attempt++){
   try{
     const ctrl=new AbortController();
     const timeout=setTimeout(()=>ctrl.abort(),timeoutMs);
     let resp;
     try{resp=await fetch(BASE+path,{signal:ctrl.signal,cache:'no-store'})}
     finally{clearTimeout(timeout)}
     const data=await resp.json();
     if(resp.ok)return data;
     if([400,401,403,404,422,429].includes(resp.status))throw Object.assign(new Error(data.error||'Request rejected'),{fatal:true});
     last=new Error(data.error||`Bridge HTTP ${resp.status}`);
   }catch(e){if(e.fatal)throw e;last=e}
   if(attempt<MAX_RETRIES)await new Promise(r=>setTimeout(r,500*(attempt+1)));
 }
 throw last||new Error('Local research bridge not responding');
}
chrome.runtime.onInstalled.addListener(async()=>{
 await chrome.sidePanel.setPanelBehavior({openPanelOnActionClick:true});
 await chrome.alarms.create('iq_weekly_audit',{periodInMinutes:60,delayInMinutes:2});
});
chrome.runtime.onStartup.addListener(async()=>{
 await chrome.sidePanel.setPanelBehavior({openPanelOnActionClick:true});
 await chrome.alarms.create('iq_weekly_audit',{periodInMinutes:60,delayInMinutes:2});
});
chrome.alarms.onAlarm.addListener(async alarm=>{
 if(alarm.name!=='iq_weekly_audit')return;
 const {monitor=false,lastReportedV32=null}=await chrome.storage.local.get(['monitor','lastReportedV32']);
 if(!monitor)return;
 try{
   const report=await request('/report/latest');
   const reportKey=String(report.model_version||'v3.2')+':'+String(report.week_end);
   if(report.report_ready===true && reportKey!==lastReportedV32){
      await chrome.storage.local.set({lastReportedV32:reportKey});
      chrome.notifications.create('weekly-'+report.week_end,{
        type:'basic',iconUrl:'icons/128.png',title:'Ithaca Quant weekly accuracy report',
        message:report.graded?`${report.week_end}: ${report.correct}/${report.graded} checked signals. View the full audit.`:
          `${report.week_end}: No forecasts matured yet. View audit and pending signals.`,
        priority:1
      });
   }
 }catch(e){/* Backend may be off; retry when it is next available. */}
});
chrome.notifications.onClicked.addListener(async id=>{
 if(!id.startsWith('weekly-'))return;
 const tabs=await chrome.tabs.query({active:true,currentWindow:true});
 if(tabs[0]){try{await chrome.sidePanel.open({tabId:tabs[0].id})}catch(e){}}
});
chrome.runtime.onMessage.addListener((msg,sender,respond)=>{
 if(msg?.type==='ANALYZE'){
   const symbol=String(msg.ticker||'').toUpperCase();
   if(!IQ_TICKER_RX.test(symbol)){respond({error:'Invalid ticker'});return}
   request('/analyze?ticker='+encodeURIComponent(symbol)+(msg.mode==='lab'?'&mode=lab':''),msg.mode==='lab'?180000:45000).then(data=>respond({data})).catch(err=>respond({error:err.message}));
   return true;
 }
 if(msg?.type==='OPEN_PANEL'){
   if(!sender.tab?.id){respond({error:'Missing tab'});return}
   chrome.sidePanel.open({tabId:sender.tab.id}).then(()=>respond({ok:true})).catch(e=>respond({error:e.message}));
   return true;
 }
 if(msg?.type==='SCREENSHOT'){
   // User-initiated button click only. Captures current visible tab locally,
   // displays preview in panel; no image sent to any server/AI API.
   chrome.tabs.captureVisibleTab(undefined,{format:'jpeg',quality:66})
     .then(img=>respond({image:img})).catch(e=>respond({error:e.message}));return true;
 }
});
