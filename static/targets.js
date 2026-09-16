(() => {
 const state={ranking:"balanced",limit:15,running:false,targets:[],custom:[]};
 const box=document.querySelector('#benchmarkResults'),status=document.querySelector('#benchmarkState'),progress=document.querySelector('#benchmarkProgress');
 const esc=v=>String(v??'').replaceAll('&','&amp;').replaceAll('<','&lt;').replaceAll('>','&gt;').replaceAll('"','&quot;');
 const tr=(key,fallback)=>window.IDONT_T?window.IDONT_T(key,fallback):fallback;
 const icon=(name)=>{const icons={check:'<svg viewBox="0 0 24 24" aria-hidden="true"><path d="m5 12 4 4L19 6"/></svg>',close:'<svg viewBox="0 0 24 24" aria-hidden="true"><path d="m7 7 10 10M17 7 7 17"/></svg>',sni:'<svg viewBox="0 0 24 24" aria-hidden="true"><circle cx="12" cy="12" r="8"/><path d="M4 12h16M12 4c2.2 2.3 3.2 4.9 3.2 8S14.2 17.7 12 20M12 4c-2.2 2.3-3.2 4.9-3.2 8S9.8 17.7 12 20"/></svg>'};return icons[name]||''};
 const hostIcon=icon('check'); const sniIcon=icon('sni');
 const moreIcon='<svg viewBox="0 0 24 24" aria-hidden="true"><circle cx="5" cy="12" r="1.7"/><circle cx="12" cy="12" r="1.7"/><circle cx="19" cy="12" r="1.7"/></svg>';

 function setCatalogState(count,source,customCount=0){
   const badge=document.querySelector('#targetCountBadge');
   const dot=document.querySelector('.catalog-dot');
   const custom=document.querySelector('#customCount');
   badge.textContent=`${count.toLocaleString()} / 3,000`;
   custom.textContent=`${customCount}/20`;
   if(count>=3000){dot.classList.add('ready');status.textContent=source==='fallback'?'3,000 benchmark targets ready · automatic snapshot':'3,000 benchmark targets ready · automatic catalog';}
   else {dot.classList.remove('ready');status.textContent=`Benchmark catalog unavailable (${count}/3,000).`}
 }

 document.querySelectorAll('.custom-select').forEach(root=>{
   const t=root.querySelector('.select-trigger'),m=root.querySelector('.select-menu');
   t?.addEventListener('click',e=>{e.stopPropagation();document.querySelectorAll('.custom-select.open').forEach(x=>x!==root&&x.classList.remove('open'));root.classList.toggle('open')});
   m?.querySelectorAll('[data-value]').forEach(o=>o.addEventListener('click',()=>{
     state[root.dataset.select]=root.dataset.select==='limit'?Number(o.dataset.value):o.dataset.value;
     t.querySelector('span').textContent=o.textContent.replace('✓','').trim();
     m.querySelectorAll('button').forEach(x=>x.classList.remove('selected'));o.classList.add('selected');root.classList.remove('open');
   }));
 });
 document.addEventListener('click',()=>document.querySelectorAll('.custom-select.open').forEach(x=>x.classList.remove('open')));

 function render(data){
   if(!data.results?.length){box.innerHTML=`<div class="empty">${tr('noHealthyTargets','No healthy targets were found before the 30-second deadline.')}</div>`;return;}
   box.innerHTML=data.results.map((r,i)=>{
     const sni=r.sni||r.domain||'—';
     return `<article class="target-result ok" data-domain="${esc(r.domain)}">
       <div class="target-rank">${i+1}</div>
       <div class="target-main">
         <div class="target-title-row"><strong dir="ltr">${esc(r.endpoint)}</strong><span class="target-score">${esc(r.score)}<small>/100</small></span></div>
         <div class="target-compact-meta">
           <span class="target-pill ${r.host_ok?'good':'bad'}" title="${tr('hostStatus','Host status')}">${hostIcon}<span>${tr('host','Host')}</span></span>
           <span class="target-pill ${r.sni_ok?'good':'bad'}" title="${tr('sniStatus','SNI status')}">${sniIcon}<span>${tr('sni','SNI')}</span></span>
           <span class="target-latency">${r.latency_ms!=null?esc(r.latency_ms)+' ms':'—'}</span>
         </div>
         <div class="target-sni-line"><span>${sniIcon}</span><b dir="ltr">${esc(sni)}</b></div>
       </div>
       <button class="target-more" type="button" aria-label="${tr('targetDetails','Target details')}" title="${tr('deepDiagnostics','Deep diagnostics')}" data-domain="${esc(r.domain)}" data-sni="${esc(sni)}" data-score="${esc(r.score)}" data-isp="${esc(r.isp||'')}">${moreIcon}</button>
     </article>`;
   }).join('');
   window.IDONT_TRANSLATE?.(box);
 }
 async function openDetails(domain,sni,score,isp){
   const modal=document.querySelector('#targetDetailsModal'),body=document.querySelector('#targetDetailsBody');
   modal.classList.add('open');modal.setAttribute('aria-hidden','false');
   body.innerHTML='<div class="target-detail-loading"><div class="diagnostic-orbit"><span></span><span></span><span></span></div><b>'+tr('runningDiagnostics','Running Deep Diagnostics…')+'</b><small>'+tr('diagnosticsMeasured','VPS path + Iranian probes + TLS/SNI. Results are measured, not estimated.')+'</small></div>';
   try{const response=await fetch(`${ID.base}/api/target-details`,{method:'POST',headers:{'Content-Type':'application/json'},body:JSON.stringify({csrf:ID.csrf,domain,sni,score,isp})});const data=await response.json();if(!response.ok)throw new Error(data.error||'Unable to load target details');renderDetails(data);}catch(e){body.innerHTML=`<div class="message error">${esc(e.message)}</div>`;}
 }
 function metric(label,value,unit=''){if(value==null||value==='')return '';return `<div class="target-detail-metric"><span>${esc(label)}</span><b>${esc(value)}${unit?` <small>${esc(unit)}</small>`:''}</b></div>`;}
 function statusPill(ok,label){return `<span class="target-status ${ok?'good':'bad'}">${ok?'✓':'×'} ${esc(label)}</span>`;}
 function renderDetails(d){
   const t=d.target||{},v=d.vps||{},ir=d.iran||{},s=d.sni||{},ping=ir.ping||[],http=ir.http||[],snis=d.sni_candidates||[];
   const iranLoss=ir.average_loss_percent;
   const sniRows=snis.map((x,i)=>`<div class="target-sni-result ${i===0?'best':''}"><span class="sni-rank">${i+1}</span><b dir="ltr">${esc(x.sni)}</b><span>${x.sni_latency_ms!=null?esc(x.sni_latency_ms)+' ms':'—'}</span><em>${esc(x.sni_tls_version||'—')} · ${esc(x.sni_alpn||'—')}</em></div>`).join('');
   document.querySelector('#targetDetailsBody').innerHTML=`
   <div class="target-detail-head"><div><span class="eyebrow">${tr('deepDiagnostics','DEEP DIAGNOSTICS')}</span><h3 dir="ltr">${esc(d.endpoint)}</h3><p>SNI: <b dir="ltr">${esc(d.best_sni||d.domain)}</b></p></div><span class="target-detail-time">${esc(d.duration_ms)} ms</span></div>
   <div class="target-detail-badges">${statusPill(t.status==='ok',tr('tlsReachable','TLS reachable'))}${statusPill(s.sni_verified,tr('sniVerified','SNI verified'))}${statusPill(t.alpn==='h2'||t.alpn==='http/1.1',tr('alpn','ALPN'))}</div>
   <div class="target-detail-grid">${metric(tr('deepScore','Deep score'),d.deep_score,'/100')}${metric(tr('benchmarkScore','Benchmark score'),d.score,'/100')}${metric(tr('isp','ISP'),d.isp)}${metric(tr('targetIp','Target IP'),t.ip||v.ip)}${metric(tr('tls','TLS'),t.tls_version||v.tls_version)}${metric(tr('alpn','ALPN'),t.alpn||v.alpn)}</div>
   ${d.score_breakdown ? `<section class="target-detail-section"><h4>Why this score?</h4><div class="score-breakdown">${Object.entries(d.score_breakdown).map(([key,value])=>{const max={san_quality:40,latency:15,stability:12,tls13:10,http2_alpn:7,certificate:6,certificate_lifetime:4,x25519:3,http3:2,post_quantum:1}[key]||100;return `<div class="score-breakdown-row"><span>${esc(key.replaceAll('_',' '))}</span><b>${esc(value)} / ${max}</b></div>`;}).join('')}</div></section>` : ''}
   <section class="target-detail-section"><h4>${tr('bestSni','Best SNI candidates')}</h4>${sniRows?`<div class="target-sni-results">${sniRows}</div>`:`<div class="detail-note">${tr('noSniCandidates','No verified alternate SNI was found.')}</div>`}</section>
   <section class="target-detail-section"><h4>${tr('vpsTargetSection','VPS → Target / SNI')}</h4><div class="target-detail-grid">${metric(tr('tcpLatency','TCP latency'),v.tcp_latency_ms,'ms')}${metric(tr('tcpJitter','TCP jitter'),v.jitter_ms,'ms')}${metric(tr('tcpLoss','TCP loss'),v.tcp_loss_percent,'%')}${metric(tr('download','Download'),v.download_mbps,'Mbps')}${metric(tr('downloaded','Downloaded'),v.download_bytes?Math.round(v.download_bytes/1024):null,'KB')}${metric(tr('sniLatency','SNI latency'),s.sni_latency_ms,'ms')}</div><div class="target-detail-inline">${statusPill(v.download_confidence==='good',tr('downloadMeasured','Download measured'))}${statusPill(v.download_confidence!=='insufficient',tr('enoughBytes','Enough bytes'))}${statusPill(v.upload_mbps!=null,tr('uploadMeasured','Upload measured'))}</div><small class="detail-note">${tr('downloadNote','Download is measured from the target HTTPS response. Upload is omitted when the target has no safe upload endpoint.')}</small></section>
   <section class="target-detail-section"><h4>${tr('iranTargetSection','Iran → Target')}</h4><div class="target-detail-grid">${metric(tr('iranAvgPing','Iran avg ping'),ir.average_ping_ms,'ms')}${metric(tr('iranJitter','Iran jitter'),ir.jitter_ms,'ms')}${metric(tr('avgPacketLoss','Avg packet loss'),iranLoss,'%')}${metric(tr('httpAvg','HTTP avg'),ir.http_average_ms,'ms')}${metric(tr('onlineProbes','Online probes'),ir.online_nodes!=null?`${ir.online_nodes}/${ir.total_nodes}`:null)}${metric(tr('sni','SNI'),d.best_sni||d.domain)}</div><div class="target-iran-list">${ping.map(x=>`<div><b>${esc(x.id)}</b><span>${x.avg_ms!=null?esc(x.avg_ms)+' ms':'—'} · loss ${x.loss_percent!=null?esc(x.loss_percent)+'%':'—'}</span><em>${x.status==='online'?'✓':'×'}</em></div>`).join('')||'<div class="detail-note">Iran probe data unavailable.</div>'}</div><div class="target-http-list">${http.map(x=>`<div><b>${esc(x.id)}</b><span>${x.latency_ms!=null?esc(x.latency_ms)+' ms':'—'}</span><em>${esc(x.http_status||x.message||'—')}</em></div>`).join('')||''}</div><small class="detail-note">${tr('iranNote','Iran measurements represent node-side reachability and HTTP response timing, not arbitrary-target bandwidth.')}</small></section>
   <section class="target-detail-section"><h4>${tr('interpretation','Interpretation')}</h4><p class="detail-note">${tr('scoreNote','Deep score uses only observed metrics. Missing measurements are excluded rather than treated as zero.')}</p><p class="detail-note">${tr('baselineNote','For a VPS upload/download baseline, use the dedicated Speed Test page instead of labeling arbitrary target traffic as upload.')}</p></section>`;
 }

 box.addEventListener('click',e=>{const btn=e.target.closest('.target-more');if(btn)openDetails(btn.dataset.domain,btn.dataset.sni,btn.dataset.score,btn.dataset.isp);});
 document.querySelector('#closeTargetDetails')?.addEventListener('click',()=>{const m=document.querySelector('#targetDetailsModal');m.classList.remove('open');m.setAttribute('aria-hidden','true');});
 document.querySelector('#targetDetailsModal')?.addEventListener('click',e=>{if(e.target.id==='targetDetailsModal'){e.currentTarget.classList.remove('open');e.currentTarget.setAttribute('aria-hidden','true');}});

 async function loadCatalog(){
   status.textContent=tr('loadingCatalog','Loading 3,000 benchmark targets…');
   try{
     const r=await fetch(`${ID.base}/api/benchmark-targets`,{cache:'no-store'});
     const d=await r.json();
     if(!r.ok) throw new Error(d.error||'Unable to load benchmark catalog');
     state.targets=d.base.map(x=>x.domain);
     state.custom=(d.custom||[]).map(x=>x.domain);
     setCatalogState(d.base_count,d.source,d.custom_count||0);
     const editor=document.querySelector('#customTargetList');
     if(editor) editor.value=state.custom.join('\n');
     return d.base_count>=3000;
   }catch(e){
     setCatalogState(0,'error',0);status.textContent=e.message;return false;
   }
 }

 document.querySelector('#runBenchmark')?.addEventListener('click',async()=>{
   if(state.running)return;
   if(state.targets.length<3000){const ok=await loadCatalog();if(!ok){box.innerHTML=`<div class="message error">${tr('catalogUnavailable','The 3,000-target catalog is not available yet. Check VPS DNS/outbound HTTPS and refresh.')}</div>`;return;}}
   state.running=true;const btn=document.querySelector('#runBenchmark');btn.disabled=true;progress.style.width='0%';const started=performance.now();const timer=setInterval(()=>{const p=Math.min(100,((performance.now()-started)/30000)*100);progress.style.width=p+'%';status.textContent=`${tr('benchmarking','Benchmarking…')} ${Math.max(0,30-(performance.now()-started)/1000).toFixed(1)}s ${tr('secondsRemaining','seconds remaining')}`;},100);
   try{const response=await fetch(`${ID.base}/api/target-benchmark`,{method:'POST',headers:{'Content-Type':'application/json'},body:JSON.stringify({csrf:ID.csrf,ranking:state.ranking,limit:state.limit,targets:state.targets})});const data=await response.json();if(!response.ok)throw new Error(data.error||'Benchmark failed.');status.textContent=`${tr('completedIn','Completed in')} ${data.duration_ms} ms · ${data.tested} ${tr('tested','tested')} · ${data.ok} ${tr('healthy','healthy')}`;render(data);}catch(e){status.textContent=e.message;box.innerHTML=`<div class="message error">${esc(e.message)}</div>`;}finally{clearInterval(timer);progress.style.width='100%';btn.disabled=false;state.running=false;}
 });

 document.querySelector('#addCustomTargets')?.addEventListener('click',async()=>{const raw=prompt(tr('addCustomPrompt','Add up to 20 custom domains, one per line. The 3,000 automatic targets remain unchanged.'));if(!raw)return;const domains=raw.split(/\n|,|\s+/).map(x=>x.trim()).filter(Boolean);try{const r=await fetch(`${ID.base}/api/benchmark-targets/custom`,{method:'POST',headers:{'Content-Type':'application/json'},body:JSON.stringify({csrf:ID.csrf,domains})});const d=await r.json();if(!r.ok)throw new Error(d.error||'Unable to add custom targets');status.textContent=`${tr('added','Added')} ${d.added.length} ${tr('customTargetsShort','custom target(s)')}.`;await loadCatalog();}catch(e){status.textContent=e.message;}});
 document.querySelector('#saveCustomList')?.addEventListener('click',async()=>{const editor=document.querySelector('#customTargetList');const domains=editor.value.split(/\n|,|\s+/).map(x=>x.trim()).filter(Boolean);try{const r=await fetch(`${ID.base}/api/benchmark-targets/custom`,{method:'POST',headers:{'Content-Type':'application/json'},body:JSON.stringify({csrf:ID.csrf,domains})});const d=await r.json();if(!r.ok)throw new Error(d.error||'Unable to save custom targets');status.textContent=`${tr('saved','Saved')} ${d.added.length} ${tr('customTargetsShort','custom target(s)')}.`;await loadCatalog();}catch(e){status.textContent=e.message;}});

 loadCatalog();
})();
