/* Compiled results use stable master case numbers and original output paths. */
let masterData=null,masterPage=0;
const masterSize=40;
const masterRanges=[['area_m2','Wing area (m²)'],['aspect_ratio','Aspect ratio'],['single_wing_span_m','Single-wing span (m)'],['single_wing_mean_thrust_N','Single-wing thrust (N)'],['single_wing_peak_abs_roll_moment_Nm','Peak |roll| (N m)'],[shapeObjective,'Thrust / moment (1/m)'],['frequency_hz','Flapping frequency (Hz)'],['amplitude_deg','Flapping amplitude (°)'],['speed_mps','Forward speed (m/s)'],['dt_s','Time step (s)'],['cycles','Cycles'],['span_panels','Span panels'],['chord_panels','Chord panels'],['rho','Water density (kg/m³)'],['nu','Kinematic viscosity (m²/s)'],['wake_cycles','Wake retention (cycles)']];
let masterVisible=[],masterSelection="";
function masterValue(r,key){return r[key]??r._settings?.[key];}
function masterEligible(r){return r.status==='ok'&&r.shape_ratio_valid===true&&Number.isFinite(r[shapeObjective])&&r[shapeObjective]>0&&r.area_m2>0&&r.aspect_ratio>0;}
function masterInvalidate(){
 $('masterLandscapeResult').innerHTML='';
 $('masterLandscapeStatus').textContent='Selection changed. Generate the 3D plot to update its PNG and CSV.';
}
function masterMatches(r,f){
 const studies=[r._study,...r.occurrences.map(o=>o.study)];
 if(f.studies.length&&!f.studies.some(s=>studies.includes(s)))return false;
 if(f.ids.length&&!f.ids.includes(r.global_case_no))return false;
 if(f.isolated&&r.simulation_mode!=='isolated_single_wing_v1')return false;
 if(f.repeat&&!r.cycle_repeatable||f.valid&&!masterEligible(r))return false;
 if(f.query&&String(r.global_case_no)!==f.query&&!`${r._study} ${r.design_name||''} ${studies.join(' ')}`.toLowerCase().includes(f.query))return false;
 if(f.waveform&&JSON.stringify(r._settings.waveform||{mode:'sine'})!==f.waveform)return false;
 if(f.wake&&(r._settings.wake_model||'free')!==f.wake)return false;
 if(f.verified&&!r._verified)return false;
 return f.ranges.every(([key,lo,hi])=>{const v=masterValue(r,key);return lo===null&&hi===null||Number.isFinite(v)&&(lo===null||v>=lo)&&(hi===null||v<=hi);});
}
function masterFilters(){
 const ranges=masterRanges.map(([key])=>{const lo=$('masterMin_'+key).value,hi=$('masterMax_'+key).value;return [key,lo===''?null:Number(lo),hi===''?null:Number(hi)];});
 if(ranges.some(([,lo,hi])=>lo!==null&&!Number.isFinite(lo)||hi!==null&&!Number.isFinite(hi)||lo!==null&&hi!==null&&lo>hi))throw Error('Each minimum must be no greater than its maximum.');
 const text=$('masterIds').value.trim();
 if(text&&!/^\d+(?:[\s,]+\d+)*$/.test(text))throw Error('Enter case numbers separated by commas or spaces.');
 return {studies:Array.from($('masterStudies').selectedOptions).map(o=>o.value),ids:text?text.split(/[\s,]+/).map(Number):[],query:$('masterSearch').value.trim().toLowerCase(),isolated:$('masterMode').value==='isolated',repeat:$('masterRepeat').checked,valid:$('masterValid').checked,verified:$('masterVerified').checked,waveform:$('masterWaveform').value,wake:$('masterWake').value,ranges};
}
function masterOptions(){
 const study=$('masterStudies'),old=Array.from(study.selectedOptions).map(o=>o.value),names=[...new Set(masterData.rows.flatMap(r=>[r._study,...r.occurrences.map(o=>o.study)]))].sort().reverse();
 study.innerHTML=names.map(n=>`<option value="${esc(n)}">${esc(n)}</option>`).join('');for(const o of study.options)o.selected=old.includes(o.value);
 const wave=$('masterWaveform'),value=wave.value,values=[...new Set(masterData.rows.map(r=>JSON.stringify(r._settings.waveform||{mode:'sine'})))];
 wave.innerHTML='<option value="">All waveforms</option>'+values.map((v,i)=>`<option value="${esc(v)}">${esc(JSON.parse(v).mode||'sine')} · profile ${i+1}</option>`).join('');wave.value=values.includes(value)?value:'';
}

function installMasterCatalog(){
 const button=document.createElement('button');button.className='nav';button.dataset.tab='catalog';button.textContent='04   Master runs';
 document.querySelector('.aside-foot').before(button);button.onclick=()=>tab('catalog');
 const section=document.createElement('section');section.id='catalog';section.className='hidden';
 section.innerHTML=`<div class="top"><div><h1>All wings. One run catalog.</h1><p class="sub">Permanent case numbers connect geometry, driving conditions and saved results across studies.</p></div><span class="badge">MASTER CATALOG</span></div>
 <div class="card"><div class="actions"><button class="btn" id="refreshMaster">Refresh catalog</button><button class="btn primary" id="exportMaster">Update master Excel</button><a class="btn" href="/master_runs.xlsx" download="master_runs.xlsx">Download master Excel</a></div><p id="masterStatus" class="caption"></p><p class="caption" id="masterPath"></p><p class="help">The workbook has Wing parameters and Ranked results sheets. In Excel, choose the metric and direction, then sort Rank ascending. The app reorders immediately. Opening Excel does not block simulation records.</p></div>
 <div class="card"><div class="fields"><label>Rank by<select id="masterMetric"></select></label><label>Order<select id="masterOrder"><option value="high">Highest first</option><option value="low">Lowest first</option></select></label><label>Simulation mode<select id="masterMode"><option value="isolated">Isolated single wing</option><option value="all">All historical models</option></select></label><label>Find a case<input id="masterSearch" placeholder="Case number, study or wing name"></label></div><label style="margin:15px 0"><input type="checkbox" id="masterRepeat"> Only repeatable cycles</label><p class="note">Driving conditions and solver settings can differ across this catalog. Inspect a case's settings before comparing it with another wing.</p><div id="masterRows"></div><div class="split" style="margin-top:15px"><button class="btn" id="masterPrevious">Previous</button><span id="masterPage" class="caption"></span><button class="btn" id="masterNext">Next</button></div></div>`;
 document.querySelector('main').append(section);
 $('masterRows').insertAdjacentHTML('beforebegin',`<details open><summary>Filter compiled results</summary><p class="help">Leave ranges blank for no limit. Study selection includes reused cases. Use Ctrl-click to select several studies.</p><div class="fields"><label>Studies (none selected = all)<select id="masterStudies" multiple size="5"></select></label><label>Only these global case numbers<input id="masterIds" placeholder="108, 109, 140"></label><label>Waveform<select id="masterWaveform"></select></label><label>Wake model<select id="masterWake"><option value="">All wake models</option><option value="free">Free</option><option value="prescribed">Prescribed</option></select></label><label>Show top matching cases<select id="masterLimit"><option value="25">25</option><option value="50" selected>50</option><option value="100">100</option><option value="0">All matching cases</option></select></label></div><div class="actions" style="margin:12px 0"><label><input type="checkbox" id="masterValid" checked> Valid 3D results only</label><label><input type="checkbox" id="masterVerified"> Verified solver identity only</label><button class="btn" id="masterClear">Clear filters</button></div><div class="fields">${masterRanges.slice(0,6).map(([key,label])=>`<label>${label}<div style="display:flex;gap:6px"><input type="number" step="any" id="masterMin_${key}" aria-label="${label} minimum" placeholder="Minimum"><input type="number" step="any" id="masterMax_${key}" aria-label="${label} maximum" placeholder="Maximum"></div></label>`).join('')}</div><details style="margin:12px 0"><summary>Driving and solver ranges</summary><div class="fields" style="margin-top:12px">${masterRanges.slice(6).map(([key,label])=>`<label>${label}<div style="display:flex;gap:6px"><input type="number" step="any" id="masterMin_${key}" aria-label="${label} minimum" placeholder="Minimum"><input type="number" step="any" id="masterMax_${key}" aria-label="${label} maximum" placeholder="Maximum"></div></label>`).join('')}</div></details><div></div></details><p class="caption" id="masterFilterCount" aria-live="polite"></p><div class="actions"><button class="btn primary" id="masterMakeLandscape">Generate filtered 3D plot + PNG/CSV</button></div><p id="masterLandscapeStatus" class="caption">Choose your filters, then generate the 3D plot.</p><div id="masterLandscapeResult"></div>`);
 for(const id of ['masterStudies','masterIds','masterWaveform','masterWake','masterLimit','masterValid','masterVerified',...masterRanges.flatMap(([key])=>['masterMin_'+key,'masterMax_'+key])])$(id).oninput=()=>{masterPage=0;renderMaster();};
 $('masterClear').onclick=()=>{for(const o of $('masterStudies').options)o.selected=false;for(const [key] of masterRanges){$('masterMin_'+key).value='';$('masterMax_'+key).value='';}for(const id of ['masterIds','masterSearch','masterWaveform','masterWake'])$(id).value='';$('masterRepeat').checked=$('masterVerified').checked=false;$('masterValid').checked=true;$('masterMode').value='isolated';$('masterLimit').value='50';masterPage=0;renderMaster();};
 $('masterMakeLandscape').onclick=async()=>{
  const ids=masterVisible.filter(masterEligible).map(r=>r.global_case_no),selection=JSON.stringify(ids);
  try{$('masterMakeLandscape').disabled=true;$('masterLandscapeStatus').textContent='Building selected wing shapes and PNG/CSV…';const d=await api('catalog-landscape',{case_numbers:ids});if(selection!==JSON.stringify(masterVisible.filter(masterEligible).map(r=>r.global_case_no)))return;renderLandscape(d,'masterLandscapeResult','master_');$('masterLandscapeStatus').textContent=d.note;}
  catch(e){$('masterLandscapeStatus').textContent=e.message;}finally{$('masterMakeLandscape').disabled=!masterVisible.some(masterEligible);}
 };

 $('refreshMaster').onclick=()=>loadMaster(true);$('exportMaster').onclick=()=>loadMaster(true,true);
 $('masterMetric').onchange=$('masterOrder').onchange=()=>{masterPage=0;loadMaster(true);};
 for(const id of ['masterMode','masterSearch','masterRepeat'])$(id).oninput=()=>{masterPage=0;renderMaster();};
 $('masterPrevious').onclick=()=>{masterPage--;renderMaster();};$('masterNext').onclick=()=>{masterPage++;renderMaster();};
}
async function loadMaster(refresh=false,exportExcel=false){
 try{
  $('refreshMaster').disabled=$('exportMaster').disabled=true;
  const metric=$('masterMetric').value||shapeObjective,descending=$('masterOrder').value!=='low';
  masterData=await api('catalog',{metric,descending,export:exportExcel});
  $('masterMetric').innerHTML=Object.entries(masterData.metrics).map(([key,label])=>`<option value="${key}">${esc(label)}</option>`).join('');$('masterMetric').value=masterData.metric;
  $('masterStatus').textContent=`${masterData.case_count} parameter sets · ${masterData.occurrence_count} study/case occurrences · Excel refreshed ${masterData.excel_updated||'not yet'}. ${masterData.excel_pending||''}`;
  $('masterPath').textContent=masterData.workbook_path;masterOptions();renderMaster();
  if(exportExcel)notify(masterData.excel_pending||'Master workbook updated.');
 }catch(e){$('masterStatus').textContent=e.message;}finally{$('refreshMaster').disabled=$('exportMaster').disabled=false;}
}
function renderMaster(){
 if(!masterData)return;
 let rows;
 try{const filters=masterFilters(),matching=masterData.rows.filter(r=>masterMatches(r,filters)),limit=Number($('masterLimit').value);rows=limit?matching.slice(0,limit):matching;
 $('masterFilterCount').textContent=`${matching.length} matching of ${masterData.rows.length} catalog cases · ${rows.length} selected for list and plot${limit?' (top '+limit+' by chosen ranking)':''}. Master Excel retains all runs.`;
 }catch(e){rows=[];$('masterFilterCount').textContent=e.message;}
 const selection=JSON.stringify(rows.map(r=>[r.global_case_no,r[shapeObjective],r.catalog_state]));
 if(selection!==masterSelection){masterSelection=selection;masterInvalidate();}
 masterVisible=rows;$('masterMakeLandscape').disabled=!rows.some(masterEligible);
 masterPage=Math.max(0,Math.min(masterPage,Math.ceil(rows.length/masterSize)-1));
 const shown=rows.slice(masterPage*masterSize,(masterPage+1)*masterSize),fmt=v=>Number.isFinite(v)?Number(v.toPrecision(5)):'—';
 $('masterRows').innerHTML=shown.map(r=>{const base=`/files/${r._study}/${r.id}/`,s=r._settings;return `<article class="wing-rank"><div class="wing-rank-number">${r.catalog_rank??'—'}</div>${rankWingPreview(r)}<div><div class="split"><strong>Case #${r.global_case_no} · ${esc(r.design_name||r.id)}</strong><span class="wing-rank-score">${fmt(r[masterData.metric])}</span></div><p class="help">${esc(masterData.metrics[masterData.metric])} · ${s.aeroelastic_enabled?'Native aeroelastic':'Rigid'} · ${r.catalog_state==='ok'?(r.cycle_repeatable?'Repeatable':'Unsettled'):esc(r.catalog_state)} · ${r._verified?'Verified solver identity':'Historical provenance: rerun required'}</p><div class="wing-rank-values"><span>Single-wing thrust <strong>${fmt(r.single_wing_mean_thrust_N)} N</strong></span><span>Peak |roll| <strong>${fmt(r.single_wing_peak_abs_roll_moment_Nm)} N m</strong></span></div><p class="help">${esc(r._study)} / ${esc(r.id)} · ${r.occurrences.length} run occurrence${r.occurrences.length===1?'':'s'}</p><div class="actions"><button class="btn" data-master-open="${r.global_case_no}">Open original study</button>${r.outputs_available?`<a href="${base}water_wing_forces.png" target="_blank">Forces</a><a href="${base}water_wing_moments.png" target="_blank">Moments</a><a href="${base}animation.webp" target="_blank">Animation</a><a href="${base}wing_right.svg" download>Right SVG</a>`:'<span class="help">Original files unavailable; this case will be simulated again if requested.</span>'}</div>${caseFailure(r)}<details style="margin-top:10px"><summary>Parameters and run locations</summary><p class="help">f ${s.frequency_hz} Hz · amplitude ${s.amplitude_deg}° · speed ${s.speed_mps} m/s · density ${s.rho} kg/m³ · ν ${s.nu} m²/s · Δt ${s.dt_s} s · ${s.cycles} cycles · mesh ${s.span_panels} × ${s.chord_panels} · ${esc(s.wake_model||'free')} wake, retention ${s.wake_cycles||'full'} · waveform ${esc(s.waveform?.mode||'sine')} · ${s.aeroelastic_enabled?`native springs: ${s.spring_constant_rad} N m/rad, damping ${s.damping_constant_rad} N m s/rad, mass/area ${s.wing_density} kg/m², startup hold ${s.step_discards} steps`:'rigid wing'}</p><pre style="white-space:pre-wrap;font-size:11px">${esc(JSON.stringify(r.sections||r.geometry,null,2))}</pre>${r.occurrences.map(o=>`<p class="help">${esc(o.study)} / ${esc(o.local_case)} · ${esc(o.state)}${o.reused?' · reused':''}</p>`).join('')}</details></div></article>`;}).join('')||'<p class="caption">No cases match this view.</p>';
 document.querySelectorAll('[data-master-open]').forEach(b=>b.onclick=()=>{const r=masterData.rows.find(r=>r.global_case_no===Number(b.dataset.masterOpen));currentStudy=r._study;tab('results');});
 $('masterPage').textContent=`${rows.length} matching cases · page ${masterPage+1} of ${Math.max(1,Math.ceil(rows.length/masterSize))}`;
 $('masterPrevious').disabled=masterPage<=0;$('masterNext').disabled=(masterPage+1)*masterSize>=rows.length;
}
installMasterCatalog();
function showCatalogHash(){
 if(!location.hash.startsWith('#catalog'))return;
 const query=new URLSearchParams(location.hash.slice('#catalog'.length).replace(/^&/,''));
 if(query.has('case'))$('masterSearch').value=query.get('case');
 tab('catalog');
}
window.addEventListener('hashchange',showCatalogHash);
if(location.hash.startsWith('#catalog'))showCatalogHash();
