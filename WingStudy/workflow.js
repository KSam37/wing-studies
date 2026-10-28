const $=id=>document.getElementById(id);
const esc=value=>String(value??'').replace(/[&<>"']/g,c=>({'&':'&amp;','<':'&lt;','>':'&gt;','"':'&quot;',"'":'&#39;'}[c]));
const fmt=value=>Number.isFinite(value)?Number(value.toPrecision(5)):'—';
let defaults,baseConfig,baseline=null,planData=null,studies=[],report=null,currentStudy='',page=0;
let previewSerial=0,resultSerial=0,timer,indexBusy=false,exportBusy=false,toastTimer;
let refinementSource=null,refinementActive=false,nodeSerial=0;
const smoothExports=new Map();
const numerical={hingeGap:'gap_m',density:'rho',viscosity:'nu',timeStep:'dt_s',cycleCount:'cycles',spanPanels:'span_panels',chordPanels:'chord_panels',settlingTolerance:'cycle_tolerance_pct',caseBudget:'case_budget',wake:'wake_model',wakeCycles:'wake_cycles'};
async function api(path,data){
 const response=await fetch('/api/'+path,data===undefined?{}:{method:'POST',headers:{'Content-Type':'application/json'},body:JSON.stringify(data)});
 const result=await response.json();if(!response.ok)throw Error(result.error||'Request failed');return result;
}
function notify(message){$('toast').textContent=message;$('toast').classList.remove('hidden');clearTimeout(toastTimer);toastTimer=setTimeout(()=>$('toast').classList.add('hidden'),6500);}
function show(name){$('setup').classList.toggle('hidden',name!=='setup');$('results').classList.toggle('hidden',name!=='results');window.scrollTo(0,0);if(name==='results')refreshIndex();}
function readRanges(){return [...$('ranges').querySelectorAll('tr')].map(row=>Object.fromEntries([...row.querySelectorAll('input[data-key]')].map(input=>[input.dataset.key,Number(input.value)])));}
function renderRanges(ranges){
 const half=baseline?.sections.at(-1).y_m??(Number($('totalSpan').value)-Number($('hingeGap').value))/2;
 $('ranges').innerHTML=ranges.map((r,i)=>`<tr><td>${refinementActive?`<input type="checkbox" data-vary="${i}" aria-label="Select chord ${i+1} for variation">`:''}${i+1}${i===0?' · root':i===ranges.length-1?' · tip':''}</td><td>${fmt(baseline?baseline.sections[i].y_m:half*i/(ranges.length-1))}</td>${['min_m','max_m','count'].map(key=>`<td><input aria-label="Chord ${i+1} ${key}" data-key="${key}" type="number" step="${key==='count'?'1':'any'}" min="${key==='count'?'1':'0'}" value="${esc(r[key])}"></td>`).join('')}</tr>`).join('');
}
function updateBaseline(){
 const spanSearch=!!baseline&&$('spanSearch').checked;
 $('spanSearchControls').classList.toggle('hidden',!baseline);
 $('spanSearchFields').classList.toggle('hidden',!spanSearch);
 $('totalSpan').disabled=spanSearch;
 $('applySpan').disabled=spanSearch;
 $('ranges').querySelectorAll('input').forEach(input=>input.disabled=spanSearch);
 $('decreasing').disabled=spanSearch;
 $('nodeCount').disabled=spanSearch;$('applyNodes').disabled=spanSearch;
 $('regularGrid').classList.toggle('hidden',!baseline);
 $('applySpan').classList.toggle('hidden',!baseline);
 $('refinementControls').classList.toggle('hidden',!refinementActive||spanSearch);
 $('baselineNote').textContent=spanSearch?`Span search of ${baseline.name}: saved chords remain fixed at every sampled span.`:refinementActive?`Refinement of ${baseline.name}: each chord has its own inclusive linspace. Hold most chords fixed and vary only the region you want to explore.`:baseline?`Baseline: ${baseline.name}. Edit node count to interpolate more sections.`:'Equally spaced root-to-tip nodes. Leading-edge sweep and incidence are zero.';
 $('samplesHeading').classList.remove('hidden');
 $('gridHelp').textContent=spanSearch?'Chord search is disabled. Each sampled span uses the selected wing’s exact chord lengths.':'Each node uses an inclusive linspace. Set min=max and samples=1 to hold it fixed. All admissible combinations are explored, subject to the case budget and optional decreasing-chord constraint. Zeros are allowed only as an outboard suffix; at least two positive sections remain.';
}
function configuration(allowPendingNodes=false){
 if(!$('spanSearch').checked&&refinementActive&&baseline&&!allowPendingNodes&&Number($('nodeCount').value)!==baseline.sections.length)throw Error('Apply node count to interpolate the wing before previewing or running.');
 if(!$('spanSearch').checked&&baseline&&!allowPendingNodes&&Math.abs(Number($('totalSpan').value)-(2*baseline.sections.at(-1).y_m+Number($('hingeGap').value)))>1e-10)throw Error('Apply span to resize the saved wing before previewing or running. Chord lengths will stay unchanged.');
 const c=structuredClone(baseConfig||defaults);c.workflow='root_torque';c.mode='shape_sweep';c.name=$('studyName').value;
 c.limits={};c.designs=[];
 c.optimization={max_root_moment_nm:Number($('maximumMoment').value)};
 c.motion_range={minimum_deg:Number($('flapMinimum').value),maximum_deg:Number($('flapMaximum').value)};
 c.settings={...defaults.settings,...c.settings};
 for(const [id,key] of Object.entries(numerical))c.settings[key]=id==='wake'?$(id).value:Number($(id).value);
 Object.assign(c.settings,{frequency_hz:Number($('frequency').value),speed_mps:Number($('speed').value),aeroelastic_enabled:false,save_solver:false});
 c.tail={enabled:false};c.shape_sweep={span_m:Number($('totalSpan').value),chord_count:Number($('nodeCount').value),decreasing:$('decreasing').checked,
  sweep_deg:0,incidence_deg:0,ranges:readRanges(),baseline:baseline?structuredClone(baseline):null};
 if(refinementActive){c.mode='shape_sweep';c.refinement={enabled:true,search_method:'linspace',variation_pct:Number($('localVariation').value),source:structuredClone(refinementSource)};}
 else delete c.refinement;
 if(baseline&&$('spanSearch').checked)c.span_search={enabled:true,min_m:Number($('spanMinimum').value),max_m:Number($('spanMaximum').value),count:Number($('spanSamples').value)};
 else delete c.span_search;
 return c;
}
function fill(c,initial=false){
 baseConfig=structuredClone(c);const settings={...defaults.settings,...c.settings};
 const shape=c.shape_sweep||defaults.shape_sweep;baseline=shape.baseline?structuredClone(shape.baseline):null;
 if(!c.span_search?.enabled&&c.mode==='custom'&&c.designs?.length){baseline=structuredClone(c.designs[0]);}
 refinementActive=!!c.refinement?.enabled;
 refinementSource=refinementActive?structuredClone(c.refinement.source||shape.baseline):null;
 if(refinementActive)baseline=structuredClone(shape.baseline);
 $('localVariation').value=c.refinement?.variation_pct??5;
 $('studyName').value=initial?'Thrust under root moment limit':c.name||'Thrust under root moment limit';
 $('maximumMoment').value=c.optimization?.max_root_moment_nm??$('maximumMoment').value;
 $('totalSpan').value=baseline?2*baseline.sections.at(-1).y_m+Number(settings.gap_m):shape.span_m;
 $('spanSearch').checked=!!c.span_search?.enabled;
 $('spanMinimum').value=c.span_search?.min_m??$('totalSpan').value;
 $('spanMaximum').value=c.span_search?.max_m??$('totalSpan').value;
 $('spanSamples').value=c.span_search?.count??5;
 $('nodeCount').value=baseline?.sections.length||shape.chord_count;$('decreasing').checked=!!shape.decreasing;
 for(const [id,key] of Object.entries(numerical))$(id).value=settings[key];
 $('frequency').value=initial?1:settings.frequency_hz;$('speed').value=settings.speed_mps;
 $('flapMinimum').value=c.motion_range?.minimum_deg??(initial?-26:-Number(settings.amplitude_deg));
 $('flapMaximum').value=c.motion_range?.maximum_deg??(initial?34:Number(settings.amplitude_deg));
 if(initial){$('wake').value='prescribed';$('wakeCycles').value='2';}
 const legacySample=refinementActive&&c.refinement.search_method!=='linspace';
 renderRanges((c.mode==='custom'&&baseline&&!refinementActive)||legacySample?baseline.sections.map(s=>({min_m:s.chord_m,max_m:s.chord_m,count:1})):shape.ranges);
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
  if($('spanSearch').checked)$('previewStatus').textContent+=' Span-only linspace; saved chord lengths stay fixed.';
  else if(refinementActive)$('previewStatus').textContent+=' Exact per-chord linspace refinement; fixed chords remain unchanged.';
  const seconds=p.runtime_estimate?.case_seconds*(p.new_simulation_count??p.case_count)+(p.cached_case_count||0);
  $('runtime').textContent=seconds?`Runtime estimate: ${Math.max(1,Math.round(seconds*.5/60))}–${Math.max(1,Math.ceil(seconds*2/60))} min; updates from completed cases.`:'Runtime estimate calibrates from completed cases.';
  drawPreview();
 }catch(error){if(serial!==previewSerial)return;planData=null;$('validation').innerHTML=`<p class="error">${esc(error.message)}</p>`;$('caseCount').textContent='—';}
}
async function refreshIndex(){
 if(indexBusy||exportBusy)return;indexBusy=true;
 try{
  const list=await api('sweep-studies');studies=list;
  if(!currentStudy||(currentStudy!=='master'&&!list.some(s=>s.id===currentStudy)))currentStudy='master';
  $('studySelect').innerHTML='<option value="master">Master comparison</option>'+list.map(s=>`<option value="${esc(s.id)}">${esc(s.name)} · ${esc(s.created.slice(0,16).replace('T',' '))}${s.rigid?'':' · historical aeroelastic'}</option>`).join('');$('studySelect').value=currentStudy;
  const study=list.find(s=>s.id===currentStudy);
  if(!$('resultsLimit').value)$('resultsLimit').value=study?.config.optimization?.max_root_moment_nm??$('maximumMoment').value;
  renderProgress(study);await evaluate();
 }catch(error){notify(error.message);}finally{indexBusy=false;}
}
function renderProgress(study){
 $('keepBest').classList.add('hidden');
 $('masterSources').classList.toggle('hidden',currentStudy!=='master');$('useStudy').disabled=currentStudy==='master';
 $('stopStudy').classList.add('hidden');
 if(currentStudy==='master'){$('progress').textContent='Select Current, Old, or both. Identical physical cases appear once when combined. This selection does not affect cached-result reuse.';return;}
 if(!study){$('progress').textContent='No saved studies yet.';return;}
 const s=study.status;$('progress').innerHTML=`<p>${esc(s.message||s.state)} · ${s.completed||0} / ${s.total||study.case_count}</p><div class="progress"><div style="width:${100*(s.completed||0)/Math.max(1,s.total||study.case_count)}%"></div></div>`;
 $('stopStudy').classList.toggle('hidden',s.state!=='running');
}
async function evaluate(exportFiles=false){
 const serial=++resultSerial,id=currentStudy,limit=Number($('resultsLimit').value);
 if(typeof invalidateLandscape==='function')invalidateLandscape();
 if(typeof checkFrontierSelection==='function')checkFrontierSelection();
 if(!id||!Number.isFinite(limit)||limit<=0){report=null;$('winnerBody').textContent='Enter your maximum wing-root moment to rank these results.';$('rankedRows').innerHTML='';$('exportComparison').disabled=true;return;}
 try{
  if(exportFiles){exportBusy=true;$('exportComparison').disabled=true;}
  const result=await api(id==='master'?'master-results':'torque-results',{study:id,maximum_root_moment_nm:limit,export:exportFiles,
   ...(id==='master'?{generations:['current','old'].filter(g=>$(g+'Master').checked)}:{})});
  if(serial!==resultSerial||id!==currentStudy)return;
  report=result;$('exportComparison').disabled=false;renderResults();
  if(typeof syncLandscapeSources==='function')syncLandscapeSources();
  const study=studies.find(s=>s.id===id);
  $('keepBest').classList.toggle('hidden',!(study?.config.refinement?.enabled&&result.winner&&['complete','complete_with_errors'].includes(study.status.state)&&study.case_count>1));
  if(result.generations)for(const g of ['current','old'])$(g+'Count').textContent=`(${result.generations[g]} cases)`;
  if(result.files)$('exportLinks').innerHTML=result.files.map(file=>`<a class="button" href="/files/${file}" download>${file.endsWith('.png')?'Comparison PNG':'Ranked results CSV'}</a>`).join('');
  if(study?.retention){if(!result.files)$('exportLinks').innerHTML='';$('exportLinks').innerHTML+=`<a class="button" href="/files/${esc(id)}/best_wing_settings.json" download>Saved best wing settings</a>`;}
 }catch(error){if(serial!==resultSerial)return;report=null;$('winnerBody').innerHTML=`<p class="error">${esc(error.message)}</p>`;$('rankedRows').innerHTML='';}
 finally{if(exportFiles){exportBusy=false;$('exportComparison').disabled=!report;}}
}
function links(row){
 if(row.status!=='ok')return '';
 const base='/files/'+(row._study||currentStudy)+'/'+row.id+'/';
 const smooth=row.sections?.length?smoothExports.get(`${row._study||currentStudy}/${row.id}`)||[]:[];
 return `<a href="${base}water_wing_forces.png" target="_blank">Ptera forces</a> · <a href="${base}water_wing_moments.png" target="_blank">Ptera moments</a> · <a href="${base}animation.webp" target="_blank">Animation</a> · <a href="${base}wing_left.svg" download>Left SVG</a> · <a href="${base}wing_right.svg" download>Right SVG</a>${row.sections?.length?`<button data-smooth-svg="${esc(rowKey(row))}">Convert to smooth SVG</button><span class="smooth-links">${smooth.map((file,i)=>`<a href="/files/${esc(file)}" download>Smooth ${i?'right':'left'} SVG</a>`).join(' · ')}</span>`:''}`;
}
function values(row){return `<p>Actual span: <strong>${fmt(row.single_wing_span_m)} m per wing</strong> (root to tip) · <strong>${fmt(row.effective_total_span_m??row.span_m)} m total</strong> (both wings + hinge gap)</p>${row.span_shortened_by_zero_chords?`<p class="help">Shortened from ${fmt(row.reference_total_span_m)} m reference total span: ${row.omitted_zero_chord_count} trailing zero-chord nodes removed.</p>`:''}<p>Mean single-wing thrust <strong>${fmt(row.single_wing_mean_thrust_N)} N</strong> · estimated pair <strong>${fmt(row.estimated_two_wing_mean_thrust_N)} N</strong></p><p>Peak |root moment| <strong>${fmt(row.single_wing_peak_abs_roll_moment_Nm)} N m</strong> · remaining margin ${fmt(row.root_moment_margin_Nm)} N m</p><p>Thrust / peak root torque: <strong>${fmt(row.single_wing_peak_abs_roll_moment_Nm>0?row.single_wing_mean_thrust_N/row.single_wing_peak_abs_roll_moment_Nm:null)} 1/m</strong></p>`;}
function rowKey(row){return row.comparison_key||row.id;}
function sourceNote(row){return row.catalog_generation?`<p class="help">${esc(row.catalog_generation==='old'?'Old':'Current')} · case #${esc(row.global_case_no)} · ${esc(row._studyName)} / ${esc(row.id)} · ${esc(row._settings.frequency_hz)} Hz · ${esc(row._settings.speed_mps)} m/s</p>`:'';}
function renderResults(){
 if(!report)return;
 const winner=report.winner;
 $('winnerBody').innerHTML=winner?`${outline(winner,true)}<h3>${esc(winner.design_name||winner.id)} · ${esc(winner.id)}</h3>${sourceNote(winner)}${values(winner)}<div class="actions"><button data-refine="${esc(rowKey(winner))}">Refine this shape</button><button data-resize="${esc(rowKey(winner))}">Resize span</button>${links(winner)}</div>`:'<p class="note">No feasible design meets the root-moment limit and settling requirement. No winner is selected. Review rejected cases, change the geometry ranges, or enter a different allowable root moment.</p>';
 if(currentStudy==='master'&&!report.total_count)$('winnerBody').textContent=report.selected?.length?'This master has no cases yet. New studies will appear in Current; check Old to view previous results.':'No masters selected. Check Current, Old, or both to compare results.';
 const rows=report.rows.filter(r=>$('showRejected').checked||r.torque_status==='Within limit');
 $('resultSummary').textContent=`${report.feasible_count} feasible of ${report.total_count} cases · limit ${report.maximum_root_moment_nm} N m per wing · ordered by single-wing mean thrust.`;
 const study=studies.find(s=>s.id===currentStudy),s=study?.config.settings;
 if(currentStudy==='master')$('resultSummary').textContent+=' Selected masters: '+(report.selected?.join(' + ')||'none')+'. Driving conditions may differ between studies.';
 if(s)$('resultSummary').textContent+=` Study motion: ${s.frequency_hz} Hz, speed ${s.speed_mps} m/s; ${study.config.motion_range?study.config.motion_range.minimum_deg+'° to '+study.config.motion_range.maximum_deg+'°':'half-stroke '+s.amplitude_deg+'°'}.`;
 page=Math.max(0,Math.min(page,Math.ceil(rows.length/25)-1));
 $('rankedRows').innerHTML=rows.slice(page*25,(page+1)*25).map(r=>`<article class="wing-row"><div class="rank">${r.thrust_rank??'—'}</div>${outline(r)}<div><div class="row-top"><strong>${esc(r.design_name||r.id)} · ${esc(r.id)}</strong><span class="badge ${r.thrust_rank?'':'bad'}">${esc(r.torque_status)}</span></div>${sourceNote(r)}${values(r)}${r.error?`<details><summary>Solver error</summary><pre>${esc(r.error)}</pre></details>`:''}<div class="actions"><button data-refine="${esc(rowKey(r))}">Refine this shape</button><button data-resize="${esc(rowKey(r))}">Resize span</button>${links(r)}</div></div></article>`).join('')||'<p class="help">No cases in this view. Check “Show rejected cases” to inspect exclusions.</p>';
 document.querySelectorAll('[data-refine]').forEach(button=>button.onclick=()=>refine(report.rows.find(r=>rowKey(r)===button.dataset.refine)));
 document.querySelectorAll('[data-resize]').forEach(button=>button.onclick=()=>loadSpanResize(report.rows.find(r=>rowKey(r)===button.dataset.resize)));
 document.querySelectorAll('[data-smooth-svg]').forEach(button=>button.onclick=async()=>{
  const row=report.rows.find(r=>rowKey(r)===button.dataset.smoothSvg);if(!row)return;const study=row._study||currentStudy;
  try{button.disabled=true;const result=await api('smooth-svg',{study,case:row.id});
   smoothExports.set(`${study}/${row.id}`,result.files);
   button.nextElementSibling.innerHTML=result.files.map((file,i)=>`<a href="/files/${esc(file)}" download>Smooth ${i?'right':'left'} SVG</a>`).join(' · ');
   notify(result.note);
  }catch(error){notify(error.message);}finally{button.disabled=false;}
 });
 $('pageLabel').textContent=`Page ${page+1} of ${Math.max(1,Math.ceil(rows.length/25))}`;$('previousPage').disabled=page===0;$('nextPage').disabled=(page+1)*25>=rows.length;
}
async function applyRefinementNodes(){
 const serial=++nodeSerial;
 try{
  const design=refinementSource||baseline;
  const result=await api('refinement-nodes',{design,count:Number($('nodeCount').value),variation_pct:Number($('localVariation').value),settings:configuration(true).settings,search_method:'linspace'});
  if(serial!==nodeSerial)return;
  refinementSource=structuredClone(design);refinementActive=true;baseline=result.baseline;
  $('spanPanels').value=result.required_span_panels;
  $('nodeCount').value=baseline.sections.length;
  $('totalSpan').value=2*baseline.sections.at(-1).y_m+Number($('hingeGap').value);
  renderRanges(result.ranges);updateBaseline();preview();
 }catch(error){notify(error.message);}
}
async function refine(row){
 const sections=row.sections||row.requested_sections;if(!sections?.length){notify('This historical case lacks editable section geometry.');return;}
 const sourceStudy=studies.find(s=>s.id===(row._study||currentStudy));
 if(sourceStudy){fill(sourceStudy.config);}
 refinementSource={name:row.design_name||row.id,sections:structuredClone(sections),source_study:row._study||currentStudy,source_case:row.id};
 baseline=structuredClone(refinementSource);refinementActive=true;
 $('spanSearch').checked=false;
 $('nodeCount').value=Math.max(16,sections.length);$('localVariation').value=5;
 $('decreasing').checked=sections.every((s,i)=>!i||s.chord_m<=sections[i-1].chord_m);
 if($('resultsLimit').value)$('maximumMoment').value=$('resultsLimit').value;
 $('studyName').value=(baseline.name+' refinement').slice(0,80);updateBaseline();show('setup');await applyRefinementNodes();notify('Refinement loaded with all chords fixed. Set min/max/samples only on the chords you want to vary, or select rows and apply the variation preset.');
}
function loadSpanResize(row){
 if(!row?.sections?.length){notify('Choose a saved sectioned wing.');return;}
 const study=studies.find(s=>s.id===(row._study||currentStudy));if(study)fill(study.config);
 refinementSource={name:row.design_name||row.id,sections:structuredClone(row.sections),source_study:row._study||currentStudy,source_case:row.id};
 baseline=structuredClone(refinementSource);refinementActive=true;
 $('spanSearch').checked=false;
 $('nodeCount').value=baseline.sections.length;$('totalSpan').value=2*baseline.sections.at(-1).y_m+Number($('hingeGap').value);
 $('spanMinimum').value=$('totalSpan').value;$('spanMaximum').value=$('totalSpan').value;$('spanSamples').value=5;
 $('studyName').value=(baseline.name+' span study').slice(0,80);
 if($('resultsLimit').value)$('maximumMoment').value=$('resultsLimit').value;
 renderRanges(baseline.sections.map(s=>({min_m:s.chord_m,max_m:s.chord_m,count:1})));updateBaseline();show('setup');preview();
 notify('Exact saved chords loaded and fixed. Enable span search and enter minimum, maximum, and samples; or apply one new span. Then Run sweep.');
}
$('applySpan').onclick=async()=>{
 if(!baseline)return;const serial=++nodeSerial;
 try{$('applySpan').disabled=true;
  const ranges=readRanges();const result=await api('resize-span',{design:baseline,source:refinementSource,total_span_m:Number($('totalSpan').value),settings:configuration(true).settings});
  if(serial!==nodeSerial)return;baseline=result.baseline;refinementSource=result.source;
  $('totalSpan').value=result.total_span_m;renderRanges(ranges);updateBaseline();preview();
  notify(`Span updated to ${fmt(result.single_wing_span_m)} m per wing (${fmt(result.total_span_m)} m including both wings and gap). Every chord length is unchanged.`);
 }catch(error){notify(error.message);}finally{$('applySpan').disabled=false;}
};
let frontierSerial=0,frontierData=null,frontierSelection='';
function checkFrontierSelection(){
 const selection=JSON.stringify([currentStudy,...['current','old'].map(g=>$(g+'Master').checked)]);
 if(selection!==frontierSelection){invalidateFrontier();frontierSelection=selection;}
}
function invalidateFrontier(){frontierSerial++;frontierData=null;$('frontierResult').innerHTML='';$('frontierStatus').textContent='Generate the full curve for this comparison; no single torque cutoff is applied.';$('makeFrontier').disabled=false;}
function inspectFrontier(){
 if(!frontierData)return;
 const cap=Number($('frontierTorque').value),point=frontierData.points.findLast(r=>r.single_wing_peak_abs_roll_moment_Nm<=cap+1e-12*Math.max(1,Math.abs(cap)));
 $('frontierTorqueValue').textContent=fmt(cap)+' N m allowable';
 if(point)$('frontierPoint').value=frontierData.points.indexOf(point);
 $('frontierWing').innerHTML=point?`${outline(point,true)}<h3>${esc(point.design_name||point.id)} · ${esc(point.id)}</h3><p>Best available mean thrust: <strong>${fmt(point.single_wing_mean_thrust_N)} N</strong> per wing · peak root torque: <strong>${fmt(point.single_wing_peak_abs_roll_moment_Nm)} N m</strong></p><p>Span: ${fmt(point.single_wing_span_m)} m per wing · ${fmt(point.effective_total_span_m)} m total</p><p class="help">${esc(point._study||currentStudy)} / ${esc(point.id)}${point.global_case_no?' · case #'+esc(point.global_case_no):''}</p>`:'No eligible design at this allowable torque.';
}
$('makeFrontier').onclick=async()=>{
 if(!currentStudy){notify('Select a study or master comparison first.');return;}
 const serial=++frontierSerial;
 try{
  $('makeFrontier').disabled=true;$('frontierStatus').textContent='Building the full torque–thrust frontier…';
  const data=await api('torque-frontier',{study:currentStudy,wing_size_percent:Number($('frontierSize').value),minimum_spacing_nm:Number($('frontierSpacing').value),torque_min_nm:$('frontierMin').value,torque_max_nm:$('frontierMax').value,generations:['current','old'].filter(g=>$(g+'Master').checked)});
  if(serial!==frontierSerial)return;frontierData=data;
  const min=data.minimum_torque_nm,max=data.slider_maximum_torque_nm;
  $('frontierResult').innerHTML=`<img src="/files/${esc(data.files[0])}" alt="Wing silhouettes showing maximum thrust available versus allowable root torque" style="width:100%;max-width:760px"><div class="actions">${data.files.map(f=>`<a href="/files/${esc(f)}" download>${f.endsWith('.png')?'Wing plot PNG':'Frontier designs CSV'}</a>`).join('')}</div><label>Explore allowable root torque <output id="frontierTorqueValue"></output><input id="frontierTorque" type="range" min="${min}" max="${max}" step="any" value="${min}" style="width:100%"></label><label>Frontier design<select id="frontierPoint">${data.points.map((r,i)=>r.single_wing_peak_abs_roll_moment_Nm<=max?`<option value="${i}">${fmt(r.single_wing_peak_abs_roll_moment_Nm)} N m → ${fmt(r.single_wing_mean_thrust_N)} N · ${esc(r.design_name||r.id)}</option>`:'').join('')}</select></label><div id="frontierWing"></div>`;
  $('frontierTorque').oninput=inspectFrontier;
  $('frontierPoint').onchange=()=>{$('frontierTorque').value=data.points[Number($('frontierPoint').value)].single_wing_peak_abs_roll_moment_Nm;inspectFrontier();};
  $('frontierStatus').textContent=`${data.eligible_count} eligible designs · ${data.plotted_count} frontier wings + ${data.background_count} sampled other designs (${data.range_count} frontier designs in range) · minimum spacing ${fmt(data.minimum_spacing_nm)} N m. Color: thrust / torque (1/m). Frontier wings 50% larger; no connecting lines. Plot range is independent of the ranking limit. Mixed study driving conditions may differ.`;
  inspectFrontier();
 }catch(error){if(serial===frontierSerial)$('frontierStatus').textContent=error.message;}
 finally{if(serial===frontierSerial)$('makeFrontier').disabled=false;}
};
for(const id of ['frontierMin','frontierMax','frontierSize','frontierSpacing'])$(id).oninput=invalidateFrontier;
let landscapeSerial=0;
function plotAxes(){return ['X','Y','Z'].map(axis=>$('plotAxis'+axis).value);}
function landscapeRows(){
 const axes=plotAxes();
 let rows=(report?.rows||[]).map(r=>({...r,plot_ratio:r.single_wing_peak_abs_roll_moment_Nm>0?r.single_wing_mean_thrust_N/r.single_wing_peak_abs_roll_moment_Nm:null,
  single_wing_thrust_roll_ratio_1pm:r.single_wing_peak_abs_roll_moment_Nm>0?r.single_wing_mean_thrust_N/r.single_wing_peak_abs_roll_moment_Nm:null})).filter(r=>['Within limit','Over limit','No positive thrust'].includes(r.torque_status)&&Number.isFinite(r.area_m2)&&r.area_m2>0&&axes.every(key=>Number.isFinite(r[key])));
 if($('plotFeasible').checked)rows=rows.filter(r=>r.torque_status==='Within limit');
 if($('plotStudy').value)rows=rows.filter(r=>(r._study||currentStudy)===$('plotStudy').value);
 for(const [key,prefix] of [['area_m2','Area'],['plot_ratio','Ratio']])for(const bound of ['Min','Max']){
  const value=$('plot'+prefix+bound).value;
  if(value!==''){const limit=Number(value);rows=rows.filter(r=>bound==='Min'?r[key]>=limit:r[key]<=limit);}
 }
 rows.sort((a,b)=>b.single_wing_mean_thrust_N-a.single_wing_mean_thrust_N||rowKey(a).localeCompare(rowKey(b)));
 const count=Number($('plotCount').value);return count?rows.slice(0,count):rows;
}
function invalidateLandscape(){
 landscapeSerial++;$('landscapeResult').innerHTML='';$('makeLandscape').disabled=!report;
 $('landscapeStatus').textContent=report?'Selection changed. Generate the 3D comparison to update it.':'Select a study or master catalog, then generate the 3D comparison.';
}
function syncLandscapeSources(){
 const old=$('plotStudy').value,sources=[...new Set((report?.rows||[]).map(r=>r._study||currentStudy))];
 $('plotStudy').innerHTML='<option value="">All included studies</option>'+sources.map(id=>`<option value="${esc(id)}">${esc(studies.find(s=>s.id===id)?.name||id)} · ${esc(id.slice(0,15))}</option>`).join('');
 $('plotStudy').value=sources.includes(old)?old:'';$('makeLandscape').disabled=!landscapeRows().length;
 $('landscapeStatus').textContent=`${landscapeRows().length} matching measured wings. Choose X, Y and Z, then generate. Color follows Z.`;
}
$('makeLandscape').onclick=async()=>{
 const serial=++landscapeSerial,rows=landscapeRows();if(!rows.length){notify('No settled wings match the 3D filters.');return;}
 if(new Set(plotAxes()).size!==3){notify('Choose three different axis parameters.');return;}
 try{
  $('makeLandscape').disabled=true;$('landscapeStatus').textContent=`Building the 3D view and PNG/CSV for ${rows.length} measured wings…`;
  const data=await api('thrust-landscape',{study:currentStudy,maximum_root_moment_nm:Number($('resultsLimit').value),
   generations:['current','old'].filter(g=>$(g+'Master').checked),case_keys:rows.map(rowKey),axes:plotAxes()});
  if(serial!==landscapeSerial)return;
  renderLandscape(data);$('landscapeStatus').textContent=data.note;
 }catch(error){if(serial===landscapeSerial)$('landscapeStatus').textContent=error.message;}
 finally{if(serial===landscapeSerial)$('makeLandscape').disabled=false;}
};
for(const id of ['plotStudy','plotFeasible','plotCount','plotAreaMin','plotAreaMax','plotRatioMin','plotRatioMax','plotAxisX','plotAxisY','plotAxisZ'])$(id).onchange=()=>{invalidateLandscape();syncLandscapeSources();};
$('setupTab').onclick=()=>show('setup');$('resultsTab').onclick=()=>show('results');
$('setup').oninput=event=>{if(event.target.id==='previewCase')return;if(event.target.id==='spanSearch')updateBaseline();if(['totalSpan','hingeGap'].includes(event.target.id)){if(baseline&&event.target.id==='hingeGap')$('totalSpan').value=2*baseline.sections.at(-1).y_m+Number($('hingeGap').value);renderRanges(readRanges());updateBaseline();}clearTimeout(timer);timer=setTimeout(preview,350);};
$('previewCase').onchange=drawPreview;
$('applyNodes').onclick=()=>{const n=Number($('nodeCount').value);if(!Number.isInteger(n)||n<2||n>64){notify('Use 2–64 chord nodes.');return;}if(baseline){applyRefinementNodes();return;}const old=readRanges();renderRanges(Array.from({length:n},(_,i)=>old[i]||{min_m:.06,max_m:.14,count:3}));preview();};
$('regularGrid').onclick=()=>{$('spanSearch').checked=false;baseline=null;refinementSource=null;refinementActive=false;renderRanges(readRanges().map(r=>({...r,count:r.min_m===r.max_m?1:3})));updateBaseline();preview();};
$('applyLocalBounds').onclick=()=>{const rows=[...$('ranges').querySelectorAll('tr')],chosen=rows.filter(r=>r.querySelector('[data-vary]')?.checked);if(!chosen.length){notify('Select the chord rows you want to vary first, or edit their min/max/samples directly.');return;}const pct=Number($('localVariation').value)/100;if(!Number.isFinite(pct)||pct<0||pct>1){notify('Use a variation between 0 and 100%.');return;}rows.forEach((row,i)=>{if(!row.querySelector('[data-vary]')?.checked)return;const chord=baseline.sections[i].chord_m;row.querySelector('[data-key="min_m"]').value=Number((chord*(1-pct)).toPrecision(12));row.querySelector('[data-key="max_m"]').value=Number((chord*(1+pct)).toPrecision(12));row.querySelector('[data-key="count"]').value=pct?3:1;});preview();};
$('fixAllChords').onclick=()=>{if(!baseline)return;renderRanges(baseline.sections.map(s=>({min_m:s.chord_m,max_m:s.chord_m,count:1})));updateBaseline();preview();};
$('keepBest').onclick=async()=>{if(!report?.winner||currentStudy==='master')return;try{$('keepBest').disabled=true;const r=await api('keep-best',{study:currentStudy,maximum_root_moment_nm:Number($('resultsLimit').value),winner_id:report.winner.id});$('exportLinks').innerHTML=`<a class="button" href="/files/${esc(r.settings_file)}" download>Saved best wing settings</a>`;notify(`Saved ${r.kept_case}; discarded ${r.discarded_count} cases. ${r.cleanup}`);await refreshIndex();}catch(error){notify(error.message);}finally{$('keepBest').disabled=false;}};
$('runStudy').onclick=async()=>{try{$('runStudy').disabled=true;const r=await api('start',configuration());currentStudy=r.id;$('resultsLimit').value=$('maximumMoment').value;show('results');}catch(error){notify(error.message);preview();}};
$('studySelect').onchange=()=>{currentStudy=$('studySelect').value;page=0;report=null;$('exportLinks').innerHTML='';const study=studies.find(s=>s.id===currentStudy);if(!$('resultsLimit').value)$('resultsLimit').value=study?.config.optimization?.max_root_moment_nm??$('maximumMoment').value;renderProgress(study);evaluate();};
$('resultsLimit').oninput=()=>{page=0;$('exportLinks').innerHTML='';clearTimeout(timer);timer=setTimeout(evaluate,350);};
$('refreshResults').onclick=refreshIndex;$('exportComparison').onclick=()=>evaluate(true);$('showRejected').onchange=()=>{page=0;renderResults();};
for(const g of ['current','old'])$(g+'Master').onchange=()=>{page=0;$('exportLinks').innerHTML='';evaluate();};
$('previousPage').onclick=()=>{page--;renderResults();};$('nextPage').onclick=()=>{page++;renderResults();};
$('useStudy').onclick=()=>{const s=studies.find(s=>s.id===currentStudy);if(s){fill(s.config);if($('resultsLimit').value)$('maximumMoment').value=$('resultsLimit').value;show('setup');preview();notify('Study settings loaded for a new rigid sweep. Review the motion range.');}};
$('stopStudy').onclick=async()=>{try{await api('stop',{id:currentStudy});refreshIndex();}catch(error){notify(error.message);}};
$('exportSettings').onclick=async()=>{try{const prepared=await api('preview',configuration());const url=URL.createObjectURL(new Blob([JSON.stringify(prepared.config,null,2)],{type:'application/json'}));const a=document.createElement('a');a.href=url;a.download='wing-study-settings.json';a.click();setTimeout(()=>URL.revokeObjectURL(url),1000);}catch(error){notify(error.message);}};
$('importSettings').onclick=()=>$('settingsFile').click();$('settingsFile').onchange=async()=>{try{fill(JSON.parse(await $('settingsFile').files[0].text()));notify('Settings loaded. This workflow runs rigid geometry sweeps.');}catch(error){notify(error.message);}finally{$('settingsFile').value='';}};
async function init(){try{const d=await api('defaults');defaults=d.config;fill(defaults,true);$('resultsLimit').value=$('maximumMoment').value;await refreshIndex();if(location.hash.startsWith('#catalog')||location.hash==='#results')show('results');setInterval(()=>{if(!$('results').classList.contains('hidden')&&(currentStudy==='master'?studies.some(s=>s.status.state==='running'):studies.find(s=>s.id===currentStudy)?.status.state==='running'))refreshIndex();},4000);}catch(error){notify(error.message);}}
init();
