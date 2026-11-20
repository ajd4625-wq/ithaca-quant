const $=id=>document.getElementById(id),BASE='http://127.0.0.1:8765';
let timer=null,busy=false,lastTicker=null,lastFetch=0;
const text=(id,v)=>$(id).textContent=v;
function status(v){text('status',v)}
function valid(s){return IQ_TICKER_RX.test(s)}
function detected(){return chrome.tabs.query({active:true,currentWindow:true}).then(t=>t[0]?iqTicker(t[0].url):null)}
function list(node,rows){node.replaceChildren(...(rows||[]).map(v=>{const el=document.createElement('li');el.textContent=String(v);return el}))}
function render(data){
 $('result').hidden=false;lastTicker=data.ticker;
 text('symbol',data.ticker);text('price',`$${Number(data.price).toFixed(2)}`);
 text('signal',data.signal.label);text('reason',data.signal.reason);
 const strength=data.signal.signal_strength;
 text('strength',strength==null?'Signal strength withheld · insufficient model evidence':`Composite signal strength ${strength}/100 · this is NOT a probability of profit`);
 const card=document.querySelector('.signal-card');
 card.className='signal-card '+(/ENTRY WATCH/.test(data.signal.label)?'up':/EXIT RISK|UNDERPERFORMANCE/.test(data.signal.label)?'down':'neutral');
 const a=data.signal.agents;
 text('forecast-score',a[0].score==null?'—':`${a[0].score}`);
 text('momentum-score',a[1].score==null?'—':`${a[1].score}`);
 text('risk-score',a[2].score==null?'—':`${a[2].score}`);
 const ex=data.forecast.expected_excess_return;
 text('outlook',ex==null?'Unavailable':`${ex>=0?'+':''}${(ex*100).toFixed(2)}% expected excess`);
 text('forecast-note',data.forecast.explanation+' '+(data.forecast.model_note||''));
 const v=data.forecast.validation;
 text('validation',v?`Predeployment holdout ${v.holdout_start} to ${v.validation_end} · ${v.independent_anchors} nonoverlapping validation anchors · ${v.skill_gate_passed?'passed fixed baseline gate':'DID NOT beat both baseline tests: abstain'}. Return forecast MAE ${((v.forecast_mae||0)*100).toFixed(2)}% versus zero-excess ${((v.zero_baseline_mae||0)*100).toFixed(2)}%; downside Brier ${v.risk_brier?.toFixed(4)??'—'} versus base rate ${v.risk_base_rate_brier?.toFixed(4)??'—'}. These are historical diagnostics, NOT forward accuracy.`:'Unavailable: the independent learners could not complete historical validation.');
 $('agent-detail').replaceChildren(...(data.forecast.agents||[]).map(x=>{
   const d=document.createElement('p');const value=x.name==='Risk'?`${(100*x.prediction).toFixed(1)}% *uncalibrated* estimated downside event`:`${x.prediction>=0?'+':''}${(x.prediction*100).toFixed(2)}% relative`;d.textContent=`${x.name}: ${x.algorithm} · ${value}`;return d
 }));
 list($('entry'),data.signal.entry_checks);list($('exit'),data.signal.risk_checks);
 const m=data.metrics;
 text('range',`${(m.range_position*100).toFixed(0)}% between observed 52-week closing low $${m.range_low.toFixed(2)} and closing high $${m.range_high.toFixed(2)} · relative 20-session return ${(m.rel20_vs_spy*100).toFixed(1)} percentage points.`);
 const n=data.news||{};
 text('newsstatus',n.status==='loading'?'Checking dated news events…':`${n.label||'News status: '+n.status}. ${n.event_count==null?'Event count unavailable':n.event_count+' distinct events'} · ${n.errors?.length?'Provider errors: '+n.errors.join(', '):'best-effort coverage'}.`);
 $('news').replaceChildren(...(n.events||[]).map(e=>{
   const item=document.createElement('div');item.className='event';
   const a=document.createElement('a');a.textContent=e.title;a.href=e.url;a.target='_blank';a.rel='noopener noreferrer';
   const meta=document.createElement('small');meta.textContent=`${e.publisher} · ${e.coverage_count} reports covering this event · ${e.date_utc.slice(0,10)}`;
   item.append(a,meta);return item;
 }));
 text('freshness',`Daily adjusted data through ${data.asof} · ${data.model_source} · ${data.data_integrity?.point_in_time_universe_verified?'PIT certified':'Yahoo/current feed: NOT a PIT archive'} · ${data.data_integrity?.warnings?.length?data.data_integrity.warnings.join('; '):'No basic feed warnings'} · ${data.elapsed_ms} ms calculation (${data.cache_hit?'cache hit':'fresh request'}). Signals/forecasts can be wrong and do not include intraday price reactions. News changes do not secretly alter the forecast.`);
}
async function ask(ticker,manual=false){
 ticker=String(ticker||'').trim().toUpperCase();
 if(!valid(ticker)){status('Enter a valid ticker (AAPL, RKLB, BRK-B).');return}
 if(busy)return;
 busy=true;lastFetch=Date.now();text('source',manual?`Manual lookup: ${ticker}`:`Detected on active page: ${ticker}`);
 status(`Evaluating ${ticker} with three fitted ML agents…`);
 try{
   const response=await chrome.runtime.sendMessage({type:'ANALYZE',ticker});
   if(!response||response.error)throw Error(response?.error||'No response from research bridge');
   render(response.data);
   status(response.data.news?.status==='loading'?'Price/model loaded; current news is checking…':`Analysis loaded · ${response.data.asof} close`);
 }catch(e){status('No verified results: '+e.message+' — check that the local server is running.');}
 finally{busy=false}
}
async function checkTab(){
 if(!$('monitor').checked)return;
 const symbol=await detected();
 if(symbol){
   text('source',`Detected on current tab: ${symbol}`);
   if(lastTicker!==symbol||Date.now()-lastFetch>45000){$('ticker').value=symbol;await ask(symbol)}
 }else{text('source','No supported ticker URL in the current tab.')}
}
async function refreshReport(){
 try{
   const r=await fetch(BASE+'/report/latest',{cache:'no-store'}).then(x=>{if(!x.ok)throw Error('Bridge unavailable');return x.json()});
   const accuracy=r.accuracy_pct==null?'Not graded yet':r.accuracy_pct+'%';
   $('weekly').replaceChildren();
   const title=document.createElement('strong');title.textContent=`${accuracy} · ${r.correct}/${r.graded} correct · week ending ${r.week_end}`;
   const detail=document.createElement('p');detail.textContent=`${r.issued} logged this week · ${r.resolved_this_week} matured · ${r.pending_total} pending. ${r.minimum_sample_warning?'Small sample: accuracy is unstable.':''}`;
   const lifetime=document.createElement('p');const lt=r.lifetime||{};
   lifetime.textContent=`Forward evidence: ${lt.graded??0} graded predictions across ${lt.independent_issue_dates??0} issue dates. ${lt.accuracy_pct==null?'No verified forward record yet':`Lifetime direction ${lt.accuracy_pct}% (95% Wilson ${lt.wilson95_pct?.join('–')}%, before clustering correction)`}. MAE ${lt.forecast_mae_pct??'—'}% versus no-alpha ${lt.zero_baseline_mae_pct??'—'}%. Status: ${lt.evidence_state||'unknown'}.`;
   $('weekly').append(title,detail,lifetime);
 }catch(e){text('weekly','Local audit unavailable. Start the Python bridge; empty reports are not invented.')}
}
$('analyze').onclick=()=>ask($('ticker').value,true);
$('ticker').addEventListener('keydown',e=>{if(e.key==='Enter')$('analyze').click()});
$('monitor').onchange=async()=>{await chrome.storage.local.set({monitor:$('monitor').checked});if($('monitor').checked)checkTab();else text('source','Monitoring disabled. Manual ticker lookup remains available.');};
$('overlay').onchange=async()=>{await chrome.storage.local.set({overlayVisible:$('overlay').checked});};
$('capture').onclick=async()=>{
 try{const res=await chrome.runtime.sendMessage({type:'SCREENSHOT'});if(res.error)throw Error(res.error);
   const img=new Image();img.src=res.image;img.alt='User-requested screenshot preview';$('preview').replaceChildren(img);
   status('Visible-tab screenshot captured for local preview only. No AI image interpretation or upload.');
 }catch(e){status('Screenshot not available: '+e.message)}
};
$('refresh-report').onclick=refreshReport;
$('open-report').onclick=()=>chrome.tabs.create({url:BASE+'/report/html'});
$('export-csv').onclick=()=>chrome.tabs.create({url:BASE+'/report/csv'});
chrome.storage.local.get({monitor:false,overlayVisible:true}).then(async r=>{
 $('monitor').checked=r.monitor;$('overlay').checked=r.overlayVisible;
 if(r.monitor)await checkTab();await refreshReport();
 timer=setInterval(async()=>{await checkTab();},5000);
 setInterval(refreshReport,120000);
});

// v0.6: all expanded research is opt-in; normal overlay stays on 3 fitted models with v3.1 features.
// Deep-model forecasts and research ranking scores never silently modify the
// frozen 5-session accuracy ledger. No HTML from market/news/SEC sources is injected.
async function readLocal(path){
 const ctrl=new AbortController(),timeout=setTimeout(()=>ctrl.abort(),180000);
 try{const res=await fetch(BASE+path,{signal:ctrl.signal,cache:'no-store'});
   const value=await res.json();if(!res.ok)throw new Error(value.error||'Local server error');return value;
 }finally{clearTimeout(timeout)}
}
function clearAndText(el,value){el.replaceChildren();const p=document.createElement('p');p.textContent=value;el.append(p)}
function addParagraph(el,value,emphasis=false){const p=document.createElement('p');p.textContent=String(value);if(emphasis)p.style.fontWeight='700';el.append(p)}
function researchTable(el,rows,columns){
 if(!rows||!rows.length)return;
 const table=document.createElement('table');table.className='research-table';
 const head=document.createElement('tr');columns.forEach(([field,label])=>{const h=document.createElement('th');h.textContent=label;head.append(h)});table.append(head);
 rows.slice(0,18).forEach(item=>{const tr=document.createElement('tr');columns.forEach(([field])=>{const td=document.createElement('td');let value=item[field];td.textContent=typeof value==='number'&&Number.isFinite(value)?value.toFixed(4):String(value??'—');tr.append(td)});table.append(tr)});
 el.append(table);
}
function activeTicker(){return String($('ticker').value||lastTicker||'').trim().toUpperCase()}
function pctOrDash(value){return typeof value==='number'&&Number.isFinite(value)?`${value>=0?'+':''}${(value*100).toFixed(2)}%`:'Not available'}
$('run-lab').onclick=async()=>{
 const ticker=activeTicker(),out=$('lab-result');
 if(!valid(ticker)){clearAndText(out,'Enter a valid ticker first.');return}
 $('run-lab').disabled=true;clearAndText(out,`Running independent v3.2 return-model comparison for ${ticker}…`);
 try{
   const response=await chrome.runtime.sendMessage({type:'ANALYZE',ticker,mode:'lab'});
   if(!response||response.error)throw Error(response?.error||'Deep model unavailable');
   const result=response.data,model=result.forecast,lab=model.model_lab;
   out.replaceChildren();
   addParagraph(out,`${ticker} • ${result.asof} completed close • v3.2 ${model.selected_model}`,true);
   addParagraph(out,`Expected 5-session SPY-relative excess: ${pctOrDash(model.expected_excess_return)}`);
   if(lab){
      addParagraph(out,`Independent held-out sample: ${lab.calibration_n||0} stock-date observations. MAE: ${pctOrDash(lab.holdout_mae)}; zero-forecast MAE: ${pctOrDash(lab.zero_forecast_mae)}.`);
      addParagraph(out,`Asymmetric residual interval: ${pctOrDash(lab.lower_excess_return)} to ${pctOrDash(lab.upper_excess_return)} (not guaranteed coverage).`);
      addParagraph(out,`Candidate promoted by comparison: ${lab.promoted_challenger?'yes':'no — retained existing ensemble'}`);
      if(lab.feature_sensitivities)addParagraph(out,`Feature sensitivities (not causal): ${lab.feature_sensitivities}`);
      if(lab.diagnostic)addParagraph(out,`Audit / candidates: ${lab.diagnostic}`);
   }else addParagraph(out,model.explanation||'Forecast unavailable.');
   addParagraph(out,'This on-demand analysis is separate from the weekly fast-model accuracy ledger.');
 }catch(e){clearAndText(out,'No validated deep result: '+e.message)}
 finally{$('run-lab').disabled=false}
};
$('catalog').onclick=async()=>{
 const out=$('lab-result');clearAndText(out,'Loading model catalog…');
 try{const d=await readLocal('/models/catalog');out.replaceChildren();
  addParagraph(out,'v3.2 advanced model candidates • normal monitoring already uses 3 separate fitted ML agents.',true);
  researchTable(out,d.catalog,[['Model','Model'],['Availability','Availability']]);
  addParagraph(out,d.note);
 }catch(e){clearAndText(out,'Model catalog unavailable: '+e.message)}
};
let rankPoll=null;
async function checkRanks(){
 const out=$('rank-result');try{
  const r=await readLocal('/research/ranking/status');
  if(r.status==='running'){clearAndText(out,`Ranking contest running for ${r.ticker||'the stock universe'}; historical validation can be slow. It never changes your regular signals.`);return false}
  if(r.status==='idle'){clearAndText(out,'No ranking research running.');return true}
  if(r.status==='error'){clearAndText(out,`Ranking research unavailable: ${r.error}. No model promoted.`);return true}
  out.replaceChildren();
  addParagraph(out,`Historical contest through ${r.asof||'unknown date'} • ${r.tickers?.length||0} stocks`,true);
  addParagraph(out,`Selection candidate: ${r.selected_candidate}. Independent promotion gate: ${r.qualified?'passed (research-only)':'not passed'}.`);
  addParagraph(out,r.evidence||'Insufficient history to judge models.');
  addParagraph(out,'SURVIVORSHIP WARNING: these currently selected stocks do not constitute a verified historical market universe. No research model is promoted from this test.',true);
  addParagraph(out,'Purged historical selection');
  researchTable(out,r.selection,[['Model','Model'],['mean_rank_ic','Rank IC'],['top20_excess_lift','Top-quintile lift'],['Status','Status']]);
  if(r.audit?.length){addParagraph(out,'Independent historical audit');researchTable(out,r.audit,[['Model','Model'],['mean_rank_ic','Rank IC'],['top20_excess_lift','Lift']])}
  if(r.ranks?.length){addParagraph(out,'Research-only latest-date ordering');researchTable(out,r.ranks.slice(0,12),[['research_rank','Rank'],['ticker','Ticker'],['rank_score','Score']])}
  addParagraph(out,r.disclaimer||'Ranking scores are not calibrated profit odds.');return true;
 }catch(e){clearAndText(out,'Ranking status unavailable: '+e.message);return true}
}
$('check-ranks').onclick=()=>checkRanks();
$('run-ranks').onclick=async()=>{
 const ticker=activeTicker();if(!valid(ticker)){clearAndText($('rank-result'),'Enter a valid ticker first.');return}
 $('run-ranks').disabled=true;
 try{
  const r=await readLocal('/research/ranking/start?ticker='+encodeURIComponent(ticker)+($('optional-rank').checked?'&optional=1':''));
  clearAndText($('rank-result'),r.message||'Ranking research started.');
  if(rankPoll)clearInterval(rankPoll);
  rankPoll=setInterval(async()=>{const done=await checkRanks();if(done){clearInterval(rankPoll);rankPoll=null;$('run-ranks').disabled=false}},5000);
 }catch(e){clearAndText($('rank-result'),'Cannot begin ranking contest: '+e.message);$('run-ranks').disabled=false}
};
$('insiders').onclick=async()=>{
 const ticker=activeTicker(),out=$('insider-result');
 if(!valid(ticker)){clearAndText(out,'Enter a valid ticker first.');return}
 $('insiders').disabled=true;clearAndText(out,'Checking publicly filed SEC Form 4 data…');
 try{
  const r=await readLocal('/insiders?ticker='+encodeURIComponent(ticker));out.replaceChildren();
  if(r.status!=='available'){addParagraph(out,`${r.status}: ${r.reason||'No verified SEC result'}`);return}
  addParagraph(out,`${ticker} • ${r.summary?.signal||'Public filings reviewed'}`,true);
  addParagraph(out,`${r.summary?.purchases??0} purchases · ${r.summary?.sales??0} sales in the last 30 days (among queried filings).`);
  (r.transactions||[]).slice(0,10).forEach(x=>{
    const p=document.createElement('p');p.textContent=`${x.filed_date||'Unknown date'} · ${x.owner||'Undisclosed owner'} · ${x.type} · ${x.shares??'?'} shares`;
    if(/^https:\/\/www\.sec\.gov\//.test(x.filing_url||'')){
      const a=document.createElement('a');a.href=x.filing_url;a.target='_blank';a.rel='noopener noreferrer';a.textContent=' · SEC filing';p.append(a);
    }out.append(p);
  });
  if(!r.transactions?.length)addParagraph(out,'No eligible disclosed purchases or sales in the queried filings.');
  addParagraph(out,r.disclaimer||'Public disclosure only; not an automatic recommendation.');
 }catch(e){clearAndText(out,'SEC filings unavailable: '+e.message)}
 finally{$('insiders').disabled=false}
};
// A previous panel instance can close while the server research continues.
// Upon reopening the user can select "Show status" to retrieve its results.


// v0.6: No PIN/archive data is silently loaded into live browsing.
let archivePoll=null;
async function integrityStatus(){
 const el=$('integrity-status');
 try{
   const r=await readLocal('/historical/status');el.replaceChildren();
   $('run-archive-audit').disabled=r.status!=='loaded';
   if(r.status==='not_configured'){
      addParagraph(el,'Not configured — no authenticated point-in-time market dataset is included.',true);
      addParagraph(el,'To enable: set ITHACA_HISTORICAL_ARCHIVE to a v3.1 vendor-history ZIP before starting the backend. This is NOT the v3.1 source ZIP.');
   }else if(r.status==='rejected'){
      addParagraph(el,'Archive rejected by integrity validator.',true);
      addParagraph(el,r.error||'Archive could not be verified.');
   }else if(r.status==='loaded'){
      const q=r.quality||{};
      addParagraph(el,`Checksums verified · declared provider ${q.provider_declared||'unknown'}`,true);
      addParagraph(el,`${q.security_id_count??0} permanent stock IDs · ${q.membership_snapshot_dates??0} membership dates · ${q.terminal_payoff_rows??0} documented terminal payoff rows · ${q.date_first} to ${q.date_last}.`);
      addParagraph(el,`Internal missing volume: ${q.missing_volume_cells??'—'}; extreme adjusted jumps: ${q.large_adjusted_move_count_over_75pct??'—'}. Source authenticity and historical completeness are NOT verified.`,true);
      (q.warnings||[]).slice(0,3).forEach(w=>addParagraph(el,w));
   }
   return r.status;
 }catch(err){clearAndText(el,'Archive status unavailable: '+err.message);return 'unavailable'}
}
async function archiveAuditStatus(){
 const out=$('audit-status');
 try{
  const d=await readLocal('/historical/audit/status');
  if(d.status==='running'){clearAndText(out,'Archival three-agent audit in progress. Live monitoring continues independently.');return false}
  if(d.status==='idle'){clearAndText(out,'No separate historical audit has run.');return true}
  if(d.status==='error'){clearAndText(out,`Historical audit refused: ${d.error}. No missing stocks or delisting outcomes were invented.`);return true}
  out.replaceChildren();
  addParagraph(out,`Retrospective archive research · ${d.windows??0} distinct historical dates · ${d.historical_eligible_forecasts??0} constituent predictions`,true);
  addParagraph(out,`${d.qualified_forecasts??0} passed the internal gate · ${d.abstained_forecasts??0} abstained · directional accuracy: ${d.direction_accuracy_pct==null?'not measurable':d.direction_accuracy_pct+'%'} · forecast MAE: ${d.mae_pct??'—'}% versus zero-forecast baseline ${d.zero_baseline_mae_pct??'—'}%.`);
  addParagraph(out,d.warning||'This is not verified live performance.');
  return true;
 }catch(err){clearAndText(out,'Historical audit status unavailable: '+err.message);return true}
}
$('refresh-integrity').onclick=async()=>{await integrityStatus();await archiveAuditStatus()};
$('run-archive-audit').onclick=async()=>{
 $('run-archive-audit').disabled=true;
 const out=$('audit-status');clearAndText(out,'Requesting on-demand local historical audit…');
 try{
  const res=await fetch(BASE+'/historical/audit/start',{method:'POST',cache:'no-store'});
  const val=await res.json();if(!res.ok)throw Error(val.error||'Audit unavailable');
  clearAndText(out,val.message||'Audit running');
  if(archivePoll)clearInterval(archivePoll);
  archivePoll=setInterval(async()=>{if(await archiveAuditStatus()){
    clearInterval(archivePoll);archivePoll=null;await integrityStatus();
  }},5000);
 }catch(err){clearAndText(out,'Cannot run archival audit: '+err.message);await integrityStatus();}
};
integrityStatus().then(()=>archiveAuditStatus());

// v0.6: opt-in and read-only analyst / holdings research. This does not add a
// fourth ML agent, alter the forecast ledger, or place investment orders.
let latestPortfolio = null;
function safeMoney(x){return typeof x==='number'&&Number.isFinite(x)?'$'+x.toLocaleString('en-US',{minimumFractionDigits:2,maximumFractionDigits:2}):'unavailable'}
function tinyPct(x){return typeof x==='number'&&Number.isFinite(x)?(100*x).toFixed(1)+'%':'—'}
async function postLocal(path,payload){
 const ctrl=new AbortController(),t=setTimeout(()=>ctrl.abort(),150000);
 try{const response=await fetch(BASE+path,{method:'POST',headers:{'Content-Type':'application/json'},body:JSON.stringify(payload),signal:ctrl.signal,cache:'no-store'});
  const obj=await response.json();if(!response.ok)throw Error(obj.error||'Local API unavailable');return obj;
 }finally{clearTimeout(t)}
}
function currentHoldings(){
 const raw=$('holdings-input').value.trim().split(/\r?\n/).map(x=>x.trim()).filter(Boolean);
 if(raw.length<1||raw.length>20)throw Error('Provide 1–20 actual holdings');
 const seen=new Set();return raw.map((line,i)=>{
  const parts=line.split(',').map(x=>x.trim());
  if(parts.length<2||parts.length>3)throw Error(`Line ${i+1}: use TICKER,shares,optional current price`);
  const ticker=parts[0].toUpperCase();if(!valid(ticker)||ticker==='SPY')throw Error(`Line ${i+1}: invalid stock ticker`);
  if(seen.has(ticker))throw Error('Repeated symbol '+ticker);seen.add(ticker);
  const shares=Number(parts[1]);if(!Number.isFinite(shares)||shares<=0||shares>1e8)throw Error(`Line ${i+1}: shares must be positive`);
  const p=parts.length===3&&parts[2]!==''?Number(parts[2]):null;
  if(p!==null&&(!Number.isFinite(p)||p<=0||p>1e7))throw Error(`Line ${i+1}: invalid unadjusted share price`);
  return {ticker,shares,price:p};
 });
}
$('save-holdings').onclick=async()=>{
 try{currentHoldings();await chrome.storage.local.set({v32PortfolioText:$('holdings-input').value});
  clearAndText($('portfolio-status'),'Saved locally in Chrome. No stock research or network request was performed.');
 }catch(e){clearAndText($('portfolio-status'),e.message)}
};
chrome.storage.local.get({v32PortfolioText:''}).then(o=>{$('holdings-input').value=o.v32PortfolioText||''});
$('load-analysts').onclick=async()=>{
 const t=activeTicker(),out=$('analyst-result');if(!valid(t)){clearAndText(out,'Enter a ticker before checking analysts.');return}
 $('load-analysts').disabled=true;clearAndText(out,`Checking provider analyst opinions for ${t}…`);
 try{
  const d=await readLocal('/analysts?ticker='+encodeURIComponent(t)+'&provider='+encodeURIComponent($('analyst-provider').value)+'&actions=1');
  out.replaceChildren();
  if(d.status!=='available'){addParagraph(out,'Data unavailable; no consensus inferred: '+(d.reason||'No provider result'));return}
  const s=d.consensus||{},c=s.rating_counts||{},pt=s.price_targets||{};
  addParagraph(out,`${t}: ${s.coverage} analyst recommendations · ${s.source}`,true);
  addParagraph(out,`Strong buy ${c.strongBuy??0} · Buy ${c.buy??0} · Hold ${c.hold??0} · Sell ${c.sell??0} · Strong sell ${c.strongSell??0}`);
  addParagraph(out,`Mean target ${safeMoney(pt.mean)} · Range ${safeMoney(pt.low)} to ${safeMoney(pt.high)} (provider target horizon not matched to the ML model)`);
  addParagraph(out,`Provider period: ${s.rating_period}; observed: ${s.observed_at}; fresh for research: ${d.fresh_for_research?'yes':'NO — stale rating'}; shrunk exploratory analyst score: ${s.shrunk_sentiment==null?'unavailable':s.shrunk_sentiment.toFixed(3)}.`);
  addParagraph(out,'Analyst ratings are third-party opinions, not verified predictive success.');
  addParagraph(out,'Attributed upgrades / downgrades',true);
  researchTable(out,d.actions||[],[['Date','Date'],['Analyst firm','Firm'],['Change','Change'],['Prior grade','From'],['New grade','To']]);
  if(!d.actions?.length)addParagraph(out,'Firm actions '+(d.actions_status||'unavailable'));
 }catch(e){clearAndText(out,'Analyst research unavailable: '+e.message)}
 finally{$('load-analysts').disabled=false}
};
$('run-portfolio').onclick=async()=>{
 const out=$('portfolio-status');let holdings;
 try{holdings=currentHoldings()}catch(e){clearAndText(out,e.message);return}
 const cash=Number($('cash-reserve').value),cap=Number($('position-cap').value);
 if(!Number.isFinite(cash)||cash<0||cash>=100||!Number.isFinite(cap)||cap<5||cap>100){clearAndText(out,'Invalid cash reserve or per-stock cap');return}
 $('run-portfolio').disabled=true;$('export-portfolio').disabled=true;latestPortfolio=null;
 clearAndText(out,'Retrieving current analyst snapshots and synchronized adjusted history. Missing data will stop the study. Nothing is traded.');
 try{
  const d=await postLocal('/portfolio/study',{holdings,provider:$('analyst-provider').value,cash_reserve:cash/100,max_position:cap/100});
  latestPortfolio=d;out.replaceChildren();
  addParagraph(out,`ILLUSTRATIVE ONLY · ${d.positions.length} existing stocks · market value ${safeMoney(d.portfolio_value)}`,true);
  addParagraph(out,`Annualized historical covariance-volatility: current ${tinyPct(d.annualized_vol_current)} / hypothetical ${tinyPct(d.annualized_vol_hypothetical)}. This is NOT a forecast of risk reduction.`);
  addParagraph(out,`Research exposure ${tinyPct(d.target_exposure)} · effective unallocated cash ${tinyPct(d.cash_effective)} · illustrative turnover ${tinyPct(d.illustrative_turnover_fraction)} · ${d.sessions} synchronized sessions · ${d.elapsed_ms} ms elapsed · ${d.forecast_tilt_qualified_count||0} recent validated Ithaca forecast inputs.`);
  const table=document.createElement('table');table.className='research-table';
  const hr=document.createElement('tr');['Holding','Valuation','Current','Study','Analysts'].forEach(k=>{const th=document.createElement('th');th.textContent=k;hr.append(th)});table.append(hr);
  (d.positions||[]).forEach(p=>{
   const tr=document.createElement('tr');
   [p.ticker,safeMoney(p.market_value),tinyPct(p.current_weight),tinyPct(p.research_weight),p.analyst_status==='available'?String(p.analyst_coverage??'—'):'unavailable'].forEach(v=>{const td=document.createElement('td');td.textContent=v;tr.append(td)});
   table.append(tr);
  });out.append(table);
  addParagraph(out,`Historical source: ${d.data_source}. Quotes can be delayed or user-entered. The adjusted history is NOT used as the current valuation quote.`);
  (d.positions||[]).forEach(p=>addParagraph(out,`${p.ticker}: ${p.shares} shares at ${safeMoney(p.price)} (${p.quote_source}${p.quote_time_utc?' at '+p.quote_time_utc:'; timestamp supplied manually'}) · ${p.analyst_status==='available'?'analyst snapshot available':'no analyst coverage retrieved'}.`));
  (d.warnings||[]).forEach(w=>addParagraph(out,'• '+w));
  addParagraph(out,'No trades placed. No forward accuracy uplift established. Analyst snapshots are NOT historical point-in-time data.',true);
  $('export-portfolio').disabled=false;
 }catch(e){clearAndText(out,'Cannot calculate credible portfolio weights: '+e.message)}
 finally{$('run-portfolio').disabled=false}
};
$('export-portfolio').onclick=()=>{
 if(!latestPortfolio)return;
 const rows=[['Ticker','Shares','Quote','Quote Source','Current Market Value','Current Weight','Research Weight','Analyst Status','Source As Of UTC']];
 latestPortfolio.positions.forEach(x=>rows.push([x.ticker,x.shares,x.price,x.quote_source,x.market_value,x.current_weight,x.research_weight,x.analyst_status,x.quote_time_utc||'manual']));
 // Quote and prevent CSV spreadsheet formula injection, even for provider strings.
 const escapeCSV=x=>{let v=String(x??'');if(/^[\s]*[=+@-]/.test(v))v="'"+v;return '"'+v.replace(/"/g,'""')+'"'};
 const textData=rows.map(r=>r.map(escapeCSV).join(',')).join('\r\n');
 const url=URL.createObjectURL(new Blob([textData],{type:'text/csv;charset=utf-8'}));
 const a=document.createElement('a');a.href=url;a.download='Ithaca_v32_portfolio_research.csv';document.body.append(a);a.click();a.remove();setTimeout(()=>URL.revokeObjectURL(url),5000);
};
