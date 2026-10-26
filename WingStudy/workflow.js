const $=id=>document.getElementById(id);
const esc=value=>String(value??'').replace(/[&<>"']/g,c=>({'&':'&amp;','<':'&lt;','>':'&gt;','"':'&quot;',"'":'&#39;'}[c]));
const fmt=value=>Number.isFinite(value)?Number(value.toPrecision(5)):'—';
let defaults,baseConfig,baseline=null,planData=null,studies=[],report=null,currentStudy='',page=0;
let previewSerial=0,resultSerial=0,timer,indexBusy=false,exportBusy=false,toastTimer;
const numerical={hingeGap:'gap_m',density:'rho',viscosity:'nu',timeStep:'dt_s',cycleCount:'cycles',spanPanels:'span_panels',chordPanels:'chord_panels',settlingTolerance:'cycle_tolerance_pct',caseBudget:'case_budget',wake:'wake_model',wakeCycles:'wake_cycles'};
async function api(path,data){
 const response=await fetch('/api/'+path,data===undefined?{}:{method:'POST',headers:{'Content-Type':'application/json'},body:JSON.stringify(data)});
 const result=await response.json();if(!response.ok)throw Error(result.error||'Request failed');return result;
}
function notify(message){$('toast').textContent=message;$('toast').classList.remove('hidden');clearTimeout(toastTimer);toastTimer=setTimeout(()=>$('toast').classList.add('hidden'),6500);}
function show(name){$('setup').classList.toggle('hidden',name!=='setup');$('results').classList.toggle('hidden',name!=='results');window.scrollTo(0,0);if(name==='results')refreshIndex();}
function readRanges(){return [...$('ranges').querySelectorAll('tr')].map(row=>Object.fromEntries([...row.querySelectorAll('input')].map(input=>[input.dataset.key,Number(input.value)])));}
function renderRanges(ranges){
 const half=baseline?.sections.at(-1).y_m??(Number($('totalSpan').value)-Number($('hingeGap').value))/2;
 $('ranges').innerHTML=ranges.map((r,i)=>`<tr><td>${i+1}${i===0?' · root':i===ranges.length-1?' · tip':''}</td><td>${fmt(baseline?baseline.sections[i].y_m:half*i/(ranges.length-1))}</td>${['min_m','max_m','count'].map(key=>`<td><input aria-label="Chord ${i+1} ${key}" data-key="${key}" type="number" step="${key==='count'?'1':'any'}" min="${key==='count'?'1':'0'}" value="${esc(r[key])}"></td>`).join('')}</tr>`).join('');
}
function updateBaseline(){
 for(const id of ['totalSpan','nodeCount','applyNodes'])$(id).disabled=!!baseline;
 $('regularGrid').classList.toggle('hidden',!baseline);
 $('baselineNote').textContent=baseline?`Baseline: ${baseline.name}. Section positions and angles remain fixed; edit chord ranges to search around this shape.`:'Equally spaced root-to-tip nodes. Leading-edge sweep and incidence are zero.';
}
function configuration(){
 const c=structuredClone(baseConfig||defaults);c.workflow='root_torque';c.mode='shape_sweep';c.name=$('studyName').value;
 c.limits={};c.designs=[];
 c.optimization={max_root_moment_nm:Number($('maximumMoment').value)};
 c.motion_range={minimum_deg:Number($('flapMinimum').value),maximum_deg:Number($('flapMaximum').value)};
 c.settings={...defaults.settings,...c.settings};
 for(const [id,key] of Object.entries(numerical))c.settings[key]=id==='wake'?$(id).value:Number($(id).value);
 Object.assign(c.settings,{frequency_hz:Number($('frequency').value),speed_mps:Number($('speed').value),aeroelastic_enabled:false,save_solver:false});
 c.tail={enabled:false};c.shape_sweep={span_m:Number($('totalSpan').value),chord_count:Number($('nodeCount').value),decreasing:$('decreasing').checked,
  sweep_deg:0,incidence_deg:0,ranges:readRanges(),baseline:baseline?structuredClone(baseline):null};
 return c;
}
function fill(c,initial=false){
 baseConfig=structuredClone(c);const settings={...defaults.settings,...c.settings};
 const shape=c.shape_sweep||defaults.shape_sweep;baseline=shape.baseline?structuredClone(shape.baseline):null;
 if(c.mode==='custom'&&c.designs?.length){baseline=structuredClone(c.designs[0]);}
 $('studyName').value=initial?'Thrust under root moment limit':c.name||'Thrust under root moment limit';
 $('maximumMoment').value=c.optimization?.max_root_moment_nm??$('maximumMoment').value;
 $('totalSpan').value=baseline?2*baseline.sections.at(-1).y_m+Number(settings.gap_m):shape.span_m;
 $('nodeCount').value=baseline?.sections.length||shape.chord_count;$('decreasing').checked=!!shape.decreasing;
 for(const [id,key] of Object.entries(numerical))$(id).value=settings[key];
 $('frequency').value=initial?1:settings.frequency_hz;$('speed').value=settings.speed_mps;
 $('flapMinimum').value=c.motion_range?.minimum_deg??(initial?-26:-Number(settings.amplitude_deg));
 $('flapMaximum').value=c.motion_range?.maximum_deg??(initial?34:Number(settings.amplitude_deg));
 if(initial){$('wake').value='prescribed';$('wakeCycles').value='2';}
 renderRanges(c.mode==='custom'&&baseline?baseline.sections.map(s=>({min_m:s.chord_m,max_m:s.chord_m,count:1})):shape.ranges);
 updateBaseline();preview();
}
function outline(row,large=false){
 const stations=row.geometry?.stations;
 if(!stations?.length)return '<p class="help">Geometry preview unavailable</p>';
 const lead=stations.map(s=>s.le?[s.le[1],s.le[0]]:[s.y_m,s.x_m]);
 const trail=stations.toReversed().map(s=>s.te?[s.te[1],s.te[0]]:[s.y_m,s.x_m+s.chord_m]);
 const points=[...lead,...trail],lo=[0,1].map(i=>Math.min(...points.map(p=>p[i]))),hi=[0,1].map(i=>Math.max(...points.map(p=>p[i])));
 const scale=Math.min(390/Math.max(hi[0]-lo[0],1e-9),185/Math.max(hi[1]-lo[1],1e-9));
 return `<svg ${large?'class="preview"':''} viewBox="0 0 440 240" role="img" aria-label="${esc(row.design_name||row.id||'Wing shape')}"><polygon points="${points.map(p=>[220+(p[0]-(hi[0]+lo[0])/2)*scale,120+(p[1]-(hi[1]+lo[1])/2)*scale].join(',')).join(' ')}" fill="#c6e6df" stroke="#007d72" stroke-width="2"/></svg>`;
}
function drawPreview(){
 const row=planData?.cases[Number($('previewCase').value)||0];if(!row)return;
 $('previewWing').innerHTML=outline(row).replace(/^<svg[^>]*>|<\/svg>$/g,'');
 $('wingArea').textContent=fmt(row.geometry.area_m2/2);$('wingSpan').textContent=fmt(row.single_wing_span_m);
}
async function preview(){
 const serial=++previewSerial;$('runStudy').disabled=true;
 if(!$('maximumMoment').value){$('validation').innerHTML='';$('previewStatus').textContent='Enter your maximum wing-root moment to preview and run.';return;}
 try{
  const p=await api('preview',configuration());if(serial!==previewSerial)return;planData=p;
  const previous=Number($('previewCase').value)||0;
  $('previewCase').innerHTML=p.cases.map((row,i)=>`<option value="${i}">${esc(row.design_name||row.id)}</option>`).join('');$('previewCase').value=Math.min(previous,p.cases.length-1);
  $('caseCount').textContent=p.case_count;$('validation').innerHTML='';$('runStudy').disabled=false;
  $('runStudy').textContent=p.cached_case_count?`Run ${p.new_simulation_count} new · reuse ${p.cached_case_count}`:`Run ${p.case_count} case${p.case_count===1?'':'s'}`;
  $('previewStatus').textContent=`${p.case_count} unique geometries · ${p.shape_grid?.pruned_count||0} pruned combinations · ${p.cached_case_count||0} exact cached results · ${p.max_steps} time steps per case.`;
  const seconds=p.runtime_estimate?.case_seconds*(p.new_simulation_count??p.case_count)+(p.cached_case_count||0);
  $('runtime').textContent=seconds?`Runtime estimate: ${Math.max(1,Math.round(seconds*.5/60))}–${Math.max(1,Math.ceil(seconds*2/60))} min; updates from completed cases.`:'Runtime estimate calibrates from completed cases.';
  drawPreview();
 }catch(error){if(serial!==previewSerial)return;planData=null;$('validation').innerHTML=`<p class="error">${esc(error.message)}</p>`;$('caseCount').textContent='—';}
}
async function refreshIndex(){
 if(indexBusy||exportBusy)return;indexBusy=true;
 try{
  const list=await api('sweep-studies');studies=list;
  if(!currentStudy||!list.some(s=>s.id===currentStudy))currentStudy=(list.find(s=>s.rigid&&s.isolated)||list[0])?.id||'';
  $('studySelect').innerHTML=list.map(s=>`<option value="${esc(s.id)}">${esc(s.name)} · ${esc(s.created.slice(0,16).replace('T',' '))}${s.rigid?'':' · historical aeroelastic'}</option>`).join('');$('studySelect').value=currentStudy;
  const study=list.find(s=>s.id===currentStudy);
  if(!$('resultsLimit').value)$('resultsLimit').value=study?.config.optimization?.max_root_moment_nm??$('maximumMoment').value;
  renderProgress(study);await evaluate();
 }catch(error){notify(error.message);}finally{indexBusy=false;}
}
function renderProgress(study){
 if(!study){$('progress').textContent='No saved studies yet.';return;}
 const s=study.status;$('progress').innerHTML=`<p>${esc(s.message||s.state)} · ${s.completed||0} / ${s.total||study.case_count}</p><div class="progress"><div style="width:${100*(s.completed||0)/Math.max(1,s.total||study.case_count)}%"></div></div>`;
 $('stopStudy').classList.toggle('hidden',s.state!=='running');
}
async function evaluate(exportFiles=false){
 const serial=++resultSerial,id=currentStudy,limit=Number($('resultsLimit').value);
 if(!id||!Number.isFinite(limit)||limit<=0){report=null;$('winnerBody').textContent='Enter your maximum wing-root moment to rank these results.';$('rankedRows').innerHTML='';$('exportComparison').disabled=true;return;}
 try{
  if(exportFiles){exportBusy=true;$('exportComparison').disabled=true;}
  const result=await api('torque-results',{study:id,maximum_root_moment_nm:limit,export:exportFiles});
  if(serial!==resultSerial||id!==currentStudy)return;
  report=result;$('exportComparison').disabled=false;renderResults();
  if(result.files)$('exportLinks').innerHTML=result.files.map(file=>`<a class="button" href="/files/${file}" download>${file.endsWith('.png')?'Comparison PNG':'Ranked results CSV'}</a>`).join('');
 }catch(error){if(serial!==resultSerial)return;report=null;$('winnerBody').innerHTML=`<p class="error">${esc(error.message)}</p>`;$('rankedRows').innerHTML='';}
 finally{if(exportFiles){exportBusy=false;$('exportComparison').disabled=!report;}}
}
function links(row){
 if(row.status!=='ok')return '';
 const base='/files/'+currentStudy+'/'+row.id+'/';
 return `<a href="${base}water_wing_forces.png" target="_blank">Ptera forces</a> · <a href="${base}water_wing_moments.png" target="_blank">Ptera moments</a> · <a href="${base}animation.webp" target="_blank">Animation</a> · <a href="${base}wing_left.svg" download>Left SVG</a> · <a href="${base}wing_right.svg" download>Right SVG</a>`;
}
function values(row){return `<p>Mean single-wing thrust <strong>${fmt(row.single_wing_mean_thrust_N)} N</strong> · estimated pair <strong>${fmt(row.estimated_two_wing_mean_thrust_N)} N</strong></p><p>Peak |root moment| <strong>${fmt(row.single_wing_peak_abs_roll_moment_Nm)} N m</strong> · remaining margin ${fmt(row.root_moment_margin_Nm)} N m</p>`;}
function renderResults(){
 if(!report)return;
 const winner=report.winner;
 $('winnerBody').innerHTML=winner?`${outline(winner,true)}<h3>${esc(winner.design_name||winner.id)} · ${esc(winner.id)}</h3>${values(winner)}<div class="actions"><button data-refine="${esc(winner.id)}">Refine this shape</button>${links(winner)}</div>`:'<p class="note">No feasible design meets the root-moment limit and settling requirement. No winner is selected. Review rejected cases, change the geometry ranges, or enter a different allowable root moment.</p>';
 const rows=report.rows.filter(r=>$('showRejected').checked||r.torque_status==='Within limit');
 $('resultSummary').textContent=`${report.feasible_count} feasible of ${report.total_count} cases · limit ${report.maximum_root_moment_nm} N m per wing · ordered by single-wing mean thrust.`;
 const study=studies.find(s=>s.id===currentStudy),s=study?.config.settings;
 if(s)$('resultSummary').textContent+=` Study motion: ${s.frequency_hz} Hz, speed ${s.speed_mps} m/s; ${study.config.motion_range?study.config.motion_range.minimum_deg+'° to '+study.config.motion_range.maximum_deg+'°':'half-stroke '+s.amplitude_deg+'°'}.`;
 page=Math.max(0,Math.min(page,Math.ceil(rows.length/25)-1));
 $('rankedRows').innerHTML=rows.slice(page*25,(page+1)*25).map(r=>`<article class="wing-row"><div class="rank">${r.thrust_rank??'—'}</div>${outline(r)}<div><div class="row-top"><strong>${esc(r.design_name||r.id)} · ${esc(r.id)}</strong><span class="badge ${r.thrust_rank?'':'bad'}">${esc(r.torque_status)}</span></div>${values(r)}${r.error?`<details><summary>Solver error</summary><pre>${esc(r.error)}</pre></details>`:''}<div class="actions"><button data-refine="${esc(r.id)}">Refine this shape</button>${links(r)}</div></div></article>`).join('')||'<p class="help">No cases in this view. Check “Show rejected cases” to inspect exclusions.</p>';
 document.querySelectorAll('[data-refine]').forEach(button=>button.onclick=()=>refine(report.rows.find(r=>r.id===button.dataset.refine)));
 $('pageLabel').textContent=`Page ${page+1} of ${Math.max(1,Math.ceil(rows.length/25))}`;$('previousPage').disabled=page===0;$('nextPage').disabled=(page+1)*25>=rows.length;
}
function refine(row){
 const sections=row.requested_sections||row.sections;if(!sections?.length){notify('This historical case lacks editable section geometry.');return;}
 baseline={name:row.design_name||row.id,sections:structuredClone(sections)};
 if(row.outline_function)baseline.outline_function=structuredClone(row.outline_function);
 $('totalSpan').value=2*sections.at(-1).y_m+Number($('hingeGap').value);$('nodeCount').value=sections.length;
 $('decreasing').checked=sections.every((s,i)=>!i||s.chord_m<=sections[i-1].chord_m);
 renderRanges(sections.map(s=>({min_m:s.chord_m,max_m:s.chord_m,count:1})));updateBaseline();
 if($('resultsLimit').value)$('maximumMoment').value=$('resultsLimit').value;
 $('studyName').value=(baseline.name+' refinement').slice(0,80);show('setup');preview();notify('Baseline loaded. Widen selected chord ranges and increase samples to search around it. Current motion stays as entered.');
}
$('setupTab').onclick=()=>show('setup');$('resultsTab').onclick=()=>show('results');
$('setup').oninput=event=>{if(event.target.id==='previewCase')return;if(['totalSpan','hingeGap'].includes(event.target.id)){if(baseline)$('totalSpan').value=2*baseline.sections.at(-1).y_m+Number($('hingeGap').value);renderRanges(readRanges());}clearTimeout(timer);timer=setTimeout(preview,350);};
$('previewCase').onchange=drawPreview;
$('applyNodes').onclick=()=>{const n=Number($('nodeCount').value);if(!Number.isInteger(n)||n<2||n>64){notify('Use 2–64 chord nodes.');return;}const old=readRanges();renderRanges(Array.from({length:n},(_,i)=>old[i]||{min_m:.06,max_m:.14,count:3}));preview();};
$('regularGrid').onclick=()=>{baseline=null;updateBaseline();renderRanges(readRanges());preview();};
$('runStudy').onclick=async()=>{try{$('runStudy').disabled=true;const r=await api('start',configuration());currentStudy=r.id;$('resultsLimit').value=$('maximumMoment').value;show('results');}catch(error){notify(error.message);preview();}};
$('studySelect').onchange=()=>{currentStudy=$('studySelect').value;page=0;report=null;$('exportLinks').innerHTML='';const study=studies.find(s=>s.id===currentStudy);if(!$('resultsLimit').value)$('resultsLimit').value=study?.config.optimization?.max_root_moment_nm??$('maximumMoment').value;renderProgress(study);evaluate();};
$('resultsLimit').oninput=()=>{page=0;$('exportLinks').innerHTML='';clearTimeout(timer);timer=setTimeout(evaluate,350);};
$('refreshResults').onclick=refreshIndex;$('exportComparison').onclick=()=>evaluate(true);$('showRejected').onchange=()=>{page=0;renderResults();};
$('previousPage').onclick=()=>{page--;renderResults();};$('nextPage').onclick=()=>{page++;renderResults();};
$('useStudy').onclick=()=>{const s=studies.find(s=>s.id===currentStudy);if(s){fill(s.config);if($('resultsLimit').value)$('maximumMoment').value=$('resultsLimit').value;show('setup');preview();notify('Study settings loaded for a new rigid sweep. Review the motion range.');}};
$('stopStudy').onclick=async()=>{try{await api('stop',{id:currentStudy});refreshIndex();}catch(error){notify(error.message);}};
$('exportSettings').onclick=async()=>{try{const prepared=await api('preview',configuration());const url=URL.createObjectURL(new Blob([JSON.stringify(prepared.config,null,2)],{type:'application/json'}));const a=document.createElement('a');a.href=url;a.download='wing-study-settings.json';a.click();setTimeout(()=>URL.revokeObjectURL(url),1000);}catch(error){notify(error.message);}};
$('importSettings').onclick=()=>$('settingsFile').click();$('settingsFile').onchange=async()=>{try{fill(JSON.parse(await $('settingsFile').files[0].text()));notify('Settings loaded. This workflow runs rigid geometry sweeps.');}catch(error){notify(error.message);}finally{$('settingsFile').value='';}};
async function init(){try{const d=await api('defaults');defaults=d.config;fill(defaults,true);$('resultsLimit').value=$('maximumMoment').value;await refreshIndex();if(location.hash.startsWith('#catalog')||location.hash==='#results')show('results');setInterval(()=>{if(!$('results').classList.contains('hidden')&&studies.find(s=>s.id===currentStudy)?.status.state==='running')refreshIndex();},4000);}catch(error){notify(error.message);}}
init();
