const $=id=>document.getElementById(id);
const esc=value=>String(value??'').replace(/[&<>"']/g,c=>({'&':'&amp;','<':'&lt;','>':'&gt;','"':'&quot;',"'":'&#39;'}[c]));
const fmt=value=>Number.isFinite(value)?Number(value.toPrecision(5)):'—';
let defaults,baseConfig,baseline=null,planData=null,studies=[],report=null,currentStudy='',page=0;
let previewSerial=0,resultSerial=0,timer,indexBusy=false,exportBusy=false,toastTimer;
let selectedSpanClass='all';
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
const adaptiveFields={adaptiveSpanMin:'span_min_m',adaptiveSpanMax:'span_max_m',adaptiveSpanCount:'span_count',adaptiveNodes:'node_count',adaptiveRoot:'root_chord_m',adaptiveRootMax:'maximum_root_chord_m',adaptiveTip:'tip_chord_m',adaptiveChordMin:'minimum_chord_m',adaptiveChordMax:'maximum_chord_m',adaptiveStep:'initial_step_m',adaptiveMinStep:'minimum_step_m',adaptiveShrink:'shrink_factor',adaptiveImprovement:'improvement_pct',adaptiveBudget:'simulation_budget',adaptiveEvaluations:'evaluation_budget',adaptivePasses:'max_passes',adaptiveParents:'frontier_parents'};
function adaptiveConfiguration(c){
 c.adaptive_search={enabled:true,...Object.fromEntries(Object.entries(adaptiveFields).map(([id,key])=>[key,key==='maximum_chord_m'&&$(id).value===''?null:Number($(id).value)])),decreasing:$('adaptiveDecreasing').checked,paired_moves:$('adaptivePaired').checked,coordinated_moves:$('adaptiveCoordinated').checked,bounds:[...$('adaptiveBounds').querySelectorAll('tr')].map(row=>Object.fromEntries([...row.querySelectorAll('input')].map(input=>[input.dataset.key,input.dataset.key==='max_m'&&input.value===''?null:Number(input.value)])))};
 if($('adaptiveElastic')?.checked)Object.assign(c.settings,{aeroelastic_enabled:true,spring_constant_rad:Number($('nativeStiffness').value),damping_constant_rad:Number($('nativeDamping').value),wing_density:Number($('nativeMass').value),step_discards:Number($('nativeHold').value)});
 if(c.adaptive_search.bounds.length!==c.adaptive_search.node_count)throw Error('Build the per-chord rows after changing adaptive node count.');
 delete c.refinement;delete c.span_search;c.mode='custom';c.workflow='adaptive_pareto';c.optimization={objective:'pareto_mean_thrust_peak_root_torque_v1',constraint:'none'};return c;
}
function renderAdaptiveBounds(bounds){
 const n=Number($('adaptiveNodes').value);if(!Number.isInteger(n)||n<2||n>64)throw Error('Use 2–64 chord nodes.');
 $('adaptiveBounds').innerHTML=Array.from({length:n},(_,i)=>{const r=bounds?.[i]||{min_m:i<2?Number($('adaptiveChordMin').value):0,max_m:$('adaptiveChordMax').value===''?null:Number($('adaptiveChordMax').value),step_m:Number($('adaptiveStep').value)};return `<tr><td>${i+1}${i===0?' · root':i===n-1?' · tip':''}</td>${['min_m','max_m','step_m'].map(key=>`<td><input type="number" min="${key==='step_m'||i>=2?'0':'0.01'}" step="any" data-key="${key}" aria-label="Adaptive chord ${i+1} ${key}" value="${esc(r[key])}"></td>`).join('')}</tr>`;}).join('');
}
function updateSearchMode(){
 const adaptive=$('searchMode').value==='adaptive';$('adaptiveControls').classList.toggle('hidden',!adaptive);$('geometryCard').classList.toggle('hidden',adaptive);
 $('nativeElasticFields').classList.toggle('hidden',!adaptive||!$('adaptiveElastic').checked);
 $('maximumMoment').closest('label').classList.toggle('hidden',adaptive);
 $('constraintTitle').textContent=adaptive?'1. Name the study':'1. Set the constraint';
 $('constraintHelp').textContent=adaptive?'Set a linspace of spans below. Each search starts from one triangle and explores the thrust–torque Pareto frontier, with no torque ceiling.':'Limit on the final settled cycle’s peak absolute roll moment at one wing root, after your own drivetrain calculation.';
 $('constraintNote').textContent=adaptive?'Objectives: increase mean thrust and reduce peak root torque. Keep useful tradeoffs across the frontier; no ratio-only winner or torque ceiling.':'Maximize mean forward thrust among rigid wings that stay within this limit. Thrust/moment ratio is not the ranking objective.';
}
function configuration(allowPendingNodes=false){
 const adaptiveMode=$('searchMode')?.value==='adaptive';
 if(!adaptiveMode&&!$('spanSearch').checked&&refinementActive&&baseline&&!allowPendingNodes&&Number($('nodeCount').value)!==baseline.sections.length)throw Error('Apply node count to interpolate the wing before previewing or running.');
 if(!adaptiveMode&&!$('spanSearch').checked&&baseline&&!allowPendingNodes&&Math.abs(Number($('totalSpan').value)-(2*baseline.sections.at(-1).y_m+Number($('hingeGap').value)))>1e-10)throw Error('Apply span to resize the saved wing before previewing or running. Chord lengths will stay unchanged.');
 const c=structuredClone(baseConfig||defaults);c.workflow='root_torque';c.mode='shape_sweep';c.name=$('studyName').value;
 c.limits={};c.designs=[];
 c.optimization={max_root_moment_nm:Number($('maximumMoment').value)};
 c.motion_range={minimum_deg:Number($('flapMinimum').value),maximum_deg:Number($('flapMaximum').value)};
 c.settings={...defaults.settings,...c.settings};
 for(const [id,key] of Object.entries(numerical))c.settings[key]=id==='wake'?$(id).value:Number($(id).value);
 Object.assign(c.settings,{frequency_hz:Number($('frequency').value),speed_mps:Number($('speed').value),aeroelastic_enabled:false,save_solver:false});
 c.tail={enabled:false};if(adaptiveMode)return adaptiveConfiguration(c);delete c.adaptive_search;
 c.shape_sweep={span_m:Number($('totalSpan').value),chord_count:Number($('nodeCount').value),decreasing:$('decreasing').checked,
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
 $('studyName').value=initial?'Pareto thrust–torque search':c.name||'Thrust under root moment limit';
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
 $('searchMode').value=initial||c.adaptive_search?.enabled?'adaptive':'grid';
 for(const [id,key] of Object.entries(adaptiveFields))if(c.adaptive_search?.[key]!==undefined)$(id).value=c.adaptive_search[key];
 $('adaptiveDecreasing').checked=c.adaptive_search?.decreasing??true;$('adaptivePaired').checked=c.adaptive_search?.paired_moves??true;$('adaptiveCoordinated').checked=c.adaptive_search?.coordinated_moves??true;
 $('adaptiveElastic').checked=!!c.adaptive_search?.enabled&&!!settings.aeroelastic_enabled;
 for(const [id,key] of Object.entries({nativeStiffness:'spring_constant_rad',nativeDamping:'damping_constant_rad',nativeMass:'wing_density',nativeHold:'step_discards'}))$(id).value=settings[key];
 renderAdaptiveBounds(c.adaptive_search?.bounds);updateSearchMode();updateBaseline();preview();
}
function wingPoints(row){
 if(row.outline_m)return row.outline_m;
 const stations=row.geometry?.stations||[];
 return [...stations.map(s=>s.le?[s.le[1],s.le[0]]:[s.y_m,s.x_m]),...stations.toReversed().map(s=>s.te?[s.te[1],s.te[0]]:[s.y_m,s.x_m+s.chord_m])];
}
function inspectWing(row){
 let dialog=$('wingInspector');
 if(!dialog){dialog=document.createElement('dialog');dialog.id='wingInspector';document.body.append(dialog);}
 dialog.innerHTML=`<button autofocus id="closeWingInspector">Close</button><h2>${esc(row.design_name||row.id)} · ${esc(row.id)}</h2>${outline(row,true)}${values(row)}${row.torque_band_count?`<p>Highest observed mean thrust in ${fmt(row.torque_band_min_nm)}–${fmt(row.torque_band_max_nm)} N m · ${row.torque_band_count} evaluated designs in this band.</p>`:''}<p class="help">${esc(row._study||currentStudy)} / ${esc(row.id)} · enlarged inspection view</p><h3>Chord widths (m), root to tip</h3><p>${(row.sections||[]).map(s=>fmt(s.chord_m)).join(' · ')}</p>`;
 $('closeWingInspector').onclick=()=>dialog.close();dialog.showModal();
}
function outline(row,large=false,physical=false){
 const points=wingPoints(row);
 if(!points.length)return '<p class="help">Geometry preview unavailable</p>';
 const lo=[0,1].map(i=>Math.min(...points.map(p=>p[i]))),hi=[0,1].map(i=>Math.max(...points.map(p=>p[i])));
 const scale=physical?resultWingScale:Math.min(390/Math.max(hi[0]-lo[0],1e-9),185/Math.max(hi[1]-lo[1],1e-9));
 return `<svg ${large?'class="preview"':''} viewBox="0 0 440 240" role="img" aria-label="${esc(row.design_name||row.id||'Wing shape')}"><polygon points="${points.map(p=>[220+(p[0]-(hi[0]+lo[0])/2)*scale,110+(p[1]-(hi[1]+lo[1])/2)*scale].join(',')).join(' ')}" fill="#c6e6df" stroke="#007d72" stroke-width="2"/>${physical?`<path d="M20 220h${scale*.1}" stroke="#17313d" stroke-width="3"/><text x="20" y="208" font-size="24">0.10 m</text>`:''}</svg>`;
}
let resultWingScale=800;

function mountFrontierPlot(data){
 const rows=data.displayed||[],W=900,H=520,L=72,R=865,T=35,B=450;
 const min=data.minimum_torque_nm,max=data.plot_maximum_torque_nm??data.slider_maximum_torque_nm;
 const ymax=Math.max(...rows.map(r=>r.single_wing_mean_thrust_N),1)*1.15;
 const extents=rows.map(r=>[0,1].map(k=>Math.max(...r.outline_m.map(p=>p[k]))-Math.min(...r.outline_m.map(p=>p[k]))));
 const scale=65/Math.max(.01,...extents.flat())*(data.wing_size_percent||100)/100;
 const ratios=rows.filter(r=>r.single_wing_peak_abs_roll_moment_Nm>0).map(r=>r.single_wing_mean_thrust_N/r.single_wing_peak_abs_roll_moment_Nm),loRatio=Math.min(...ratios),hiRatio=Math.max(...ratios);
 const color=r=>{if(!(r.single_wing_peak_abs_roll_moment_Nm>0))return '#aaa';const v=(r.single_wing_mean_thrust_N/r.single_wing_peak_abs_roll_moment_Nm-loRatio)/(hiRatio-loRatio||1);return `hsl(${260-200*v} 65% 42%)`;};
 const ticks=Array.from({length:6},(_,i)=>{const x=L+(R-L)*i/5,y=B-(B-T)*i/5;return `<path d="M${x} ${T}V${B}M${L} ${y}H${R}" stroke="#e3ebeb"/><text x="${x}" y="${B+22}" text-anchor="middle">${fmt(min+(max-min)*i/5)}</text><text x="${L-12}" y="${y+5}" text-anchor="end">${fmt(ymax*i/5)}</text>`;}).join('');
 const glyphs=rows.map((r,i)=>{const pts=r.outline_m,lo=[0,1].map(k=>Math.min(...pts.map(p=>p[k]))),hi=[0,1].map(k=>Math.max(...pts.map(p=>p[k])));const x=L+(r.single_wing_peak_abs_roll_moment_Nm-min)/(max-min||1)*(R-L),y=B-r.single_wing_mean_thrust_N/ymax*(B-T);return `<g transform="translate(${x} ${y})"><g class="plot-wing" data-plot-wing="${i}" tabindex="0" role="button" aria-label="Inspect ${esc(r.design_name||r.id)}"><title>${esc(r.design_name||r.id)} · span ${fmt(r.single_wing_span_m)} m · click for metrics</title><circle r="12" fill="transparent"/><polygon points="${pts.map(p=>[(p[0]-(lo[0]+hi[0])/2)*scale,(p[1]-(lo[1]+hi[1])/2)*scale].join(',')).join(' ')}" fill="${color(r)}" stroke="${r.is_frontier||r.is_representative?'#102f3c':'#9aa'}" stroke-width="${r.is_frontier||r.is_representative?2:0.7}"/></g></g>`;}).join('');
 $('interactiveFrontier').innerHTML=`<svg viewBox="0 0 ${W} ${H}" style="width:100%;min-width:550px" aria-label="Interactive torque thrust wings with shared physical scale">${ticks}<path d="M${L} ${T}V${B}H${R}" fill="none" stroke="#17313d"/><text x="460" y="503" text-anchor="middle">Peak wing-root torque (N m)</text><text transform="translate(18 250) rotate(-90)" text-anchor="middle">Mean single-wing thrust (N)</text><path d="M${L} 16h${scale*.1}" stroke="#17313d" stroke-width="3"/><text x="${L+scale*.1+10}" y="21">0.10 m · common wing scale</text>${glyphs}</svg><p class="help">Color: purple → green = increasing thrust / torque. ${data.comparison_mode==='bands'?'One highest-thrust observed wing per occupied torque band.':'Dark outline: frontier.'} Hover temporarily magnifies; click or press Enter for metrics.</p>`;
 document.querySelectorAll('[data-plot-wing]').forEach(g=>{g.onclick=()=>inspectWing(rows[Number(g.dataset.plotWing)]);g.onkeydown=e=>{if(e.key==='Enter'||e.key===' '){e.preventDefault();g.onclick();}};g.onmouseenter=()=>{const anchor=g.parentElement,svg=anchor.parentElement;if(svg.lastElementChild!==anchor)svg.append(anchor);};});
}
function drawPreview(){
 const row=planData?.cases[Number($('previewCase').value)||0];if(!row)return;
 $('previewWing').innerHTML=outline(row).replace(/^<svg[^>]*>|<\/svg>$/g,'');
 $('wingArea').textContent=fmt(row.geometry.area_m2/2);$('wingSpan').textContent=fmt(row.single_wing_span_m);
}
async function preview(){
 const serial=++previewSerial;$('runStudy').disabled=true;
 if($('searchMode').value!=='adaptive'&&!$('maximumMoment').value){$('validation').innerHTML='';$('previewStatus').textContent='Enter your maximum wing-root moment to preview and run.';return;}
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
  if(p.adaptive_search){$('spanPanels').value=p.settings.span_panels;$('runStudy').textContent='Run Pareto search';$('caseCount').textContent=p.simulation_budget+' max';$('previewStatus').textContent=`${p.cases.length} span seeds · ${p.search_job_count} span searches · actual per-chord steps ${fmt(Math.min(...p.adaptive_search.bounds.map(b=>b.step_m)))}–${fmt(Math.max(...p.adaptive_search.bounds.map(b=>b.step_m)))} m · objectives: higher thrust and lower peak root torque (no torque ceiling) · ${p.simulation_budget} new-simulation budget. ${p.settings.aeroelastic_enabled?'Native aeroelastic springs; damping '+fmt(p.settings.damping_constant_rad)+' N m s/rad. ':'Rigid UVLM. '}Candidate geometries are generated adaptively; exact cache hits do not use this budget.`;const upper=p.runtime_estimate?.case_seconds*p.simulation_budget;$('runtime').textContent=upper?`Budget runtime estimate: about ${Math.ceil(upper/60)} min at recent case speed; may stop earlier.`:'Runtime estimate calibrates from completed cases.';}
  drawPreview();
 }catch(error){if(serial!==previewSerial)return;planData=null;$('validation').innerHTML=`<p class="error">${esc(error.message)}</p>`;$('caseCount').textContent='—';}
}
async function refreshIndex(){
 if(indexBusy||exportBusy)return;indexBusy=true;
 try{
  const list=await api('sweep-studies');studies=list;
  if(!currentStudy||(currentStudy!=='master'&&!list.some(s=>s.id===currentStudy)))currentStudy='master';
  $('studySelect').innerHTML='<option value="master">Master comparison</option>'+list.map(s=>`<option value="${esc(s.id)}">${esc(s.name)} · ${esc(s.created.slice(0,16).replace('T',' '))}${s.rigid?'':s.config.adaptive_search?.enabled?' · native aeroelastic':' · historical aeroelastic'}</option>`).join('');$('studySelect').value=currentStudy;
  const study=list.find(s=>s.id===currentStudy);
  $('resultsModel').disabled=currentStudy!=='master';if(study)$('resultsModel').value=study.config.settings.aeroelastic_enabled?'aeroelastic':'rigid';
  $('evolutionCard').classList.toggle('hidden',!study?.config.adaptive_search?.enabled);
  renderProgress(study);await evaluate();
 }catch(error){notify(error.message);}finally{indexBusy=false;}
}
function renderProgress(study){
 $('masterSources').classList.toggle('hidden',currentStudy!=='master');$('useStudy').disabled=currentStudy==='master';
 $('stopStudy').classList.add('hidden');
 if(currentStudy==='master'){$('progress').textContent='Select Current, Old, and/or Adaptive. Identical physical cases appear once when combined. This selection does not affect cached-result reuse.';return;}
 if(!study){$('progress').textContent='No saved studies yet.';return;}
 const s=study.status;$('progress').innerHTML=`<p>${esc(s.message||s.state)} · ${s.completed||0} / ${s.total||study.case_count}</p><div class="progress"><div style="width:${100*(s.completed||0)/Math.max(1,s.total||study.case_count)}%"></div></div>`;
 $('stopStudy').classList.toggle('hidden',s.state!=='running');
}
async function evaluate(exportFiles=false){
 const serial=++resultSerial,id=currentStudy;
 if(typeof invalidateLandscape==='function')invalidateLandscape();
 if(typeof checkFrontierSelection==='function')checkFrontierSelection();
 if(!id){report=null;$('rankedRows').innerHTML='';$('exportComparison').disabled=true;return;}
 try{
  if(exportFiles){exportBusy=true;$('exportComparison').disabled=true;}
  const result=await api('tradeoff-results',{study:id,span_class:selectedSpanClass,export:exportFiles,model_mode:$('resultsModel')?.value||'rigid',
   ...(id==='master'?{generations:['current','old','adaptive'].filter(g=>$(g+'Master')?.checked)}:{})});
  if(serial!==resultSerial||id!==currentStudy)return;
  report=result;selectedSpanClass=result.span_class||'all';$('exportComparison').disabled=false;renderResults();
  if(typeof syncLandscapeSources==='function')syncLandscapeSources();
  const study=studies.find(s=>s.id===id);
  if(result.generations)for(const g of ['current','old','adaptive'])if($(g+'Count'))$(g+'Count').textContent=`(${result.generations[g]} cases)`;
  if(result.files)$('exportLinks').innerHTML=result.files.map(file=>`<a class="button" href="/files/${file}" download>${file.endsWith('.png')?'Torque–thrust PNG':'All eligible designs CSV'}</a>`).join('');
  if(study?.retention){if(!result.files)$('exportLinks').innerHTML='';$('exportLinks').innerHTML+=`<a class="button" href="/files/${esc(id)}/best_wing_settings.json" download>Saved best wing settings</a>`;}
 }catch(error){if(serial!==resultSerial)return;report=null;$('resultSummary').textContent=error.message;$('rankedRows').innerHTML='';}
 finally{if(exportFiles){exportBusy=false;$('exportComparison').disabled=!report;}}
}
function links(row){
 if(row.status!=='ok')return '';
 const base='/files/'+(row._study||currentStudy)+'/'+row.id+'/';
 const smooth=row.sections?.length?smoothExports.get(`${row._study||currentStudy}/${row.id}`)||[]:[];
 return `<a href="${base}water_wing_forces.png" target="_blank">Ptera forces</a> · <a href="${base}water_wing_moments.png" target="_blank">Ptera moments</a> · <a href="${base}animation.webp" target="_blank">Animation</a> · <a href="${base}wing_left.svg" download>Left SVG</a> · <a href="${base}wing_right.svg" download>Right SVG</a>${row.sections?.length?`<button data-smooth-svg="${esc(rowKey(row))}">Convert to smooth SVG</button><span class="smooth-links">${smooth.map((file,i)=>`<a href="/files/${esc(file)}" download>Smooth ${i?'right':'left'} SVG</a>`).join(' · ')}</span>`:''}`;
}
function values(row){return `${row.aeroelastic_enabled?`<p class="help">Native aeroelastic · peak twist ${fmt(row.peak_abs_native_twist_deg)}° · damping ${fmt(row.damping_constant_rad)} N m s/rad</p>`:''}<p>Actual span: <strong>${fmt(row.single_wing_span_m)} m per wing</strong> (root to tip) · <strong>${fmt(row.effective_total_span_m??row.span_m)} m total</strong> (both wings + hinge gap)</p>${row.span_shortened_by_zero_chords?`<p class="help">Shortened from ${fmt(row.reference_total_span_m)} m reference total span: ${row.omitted_zero_chord_count} trailing zero-chord nodes removed.</p>`:''}<p>Mean single-wing thrust <strong>${fmt(row.single_wing_mean_thrust_N)} N</strong> · estimated pair <strong>${fmt(row.estimated_two_wing_mean_thrust_N)} N</strong></p><p>Peak |root moment| <strong>${fmt(row.single_wing_peak_abs_roll_moment_Nm)} N m</strong></p><p>Thrust / peak root torque: <strong>${fmt(row.single_wing_peak_abs_roll_moment_Nm>0?row.single_wing_mean_thrust_N/row.single_wing_peak_abs_roll_moment_Nm:null)} 1/m</strong></p>`;}
function rowKey(row){return row.comparison_key||row.id;}
function sourceNote(row){return row.catalog_generation?`<p class="help">${esc(row.catalog_generation==='old'?'Old':row.catalog_generation==='adaptive'?'Adaptive':'Current')} · case #${esc(row.global_case_no)} · ${esc(row._studyName)} / ${esc(row.id)} · ${esc(row._settings.frequency_hz)} Hz · ${esc(row._settings.speed_mps)} m/s</p>`:'';}
function evolutionSource(row){
 const study=row._study||currentStudy;
 if(row.adaptive_trial||studies.find(s=>s.id===study)?.config.adaptive_search?.enabled)return {study,case:row.id};
 const occurrence=row.occurrences?.filter(o=>studies.find(s=>s.id===o.study)?.config.adaptive_search?.enabled).sort((a,b)=>b.study.localeCompare(a.study))[0];
 return occurrence?{study:occurrence.study,case:occurrence.local_case}:null;
}
function renderResults(){
 if(!report)return;
 $('spanTabs').innerHTML=[{key:'all'},...(report.span_classes||[])].map(c=>`<button role="tab" aria-selected="${selectedSpanClass===c.key}" data-span="${esc(c.key)}" class="${selectedSpanClass===c.key?'primary':''}" style="flex-shrink:0">${c.key==='all'?'All spans':c.key==='unknown'?'Unknown span':fmt(Number(c.key))+' m total'}</button>`).join('');
 document.querySelectorAll('[data-span]').forEach(b=>b.onclick=()=>{if(selectedSpanClass===b.dataset.span)return;selectedSpanClass=b.dataset.span;page=0;evaluate();});
 const allPoints=report.rows.flatMap(wingPoints);
 const maxSpan=Math.max(.4,...studies.map(s=>(s.config?.adaptive_search?.span_max_m||0)/2),...allPoints.map(p=>Math.abs(p[0])));
 const maxChord=Math.max(.2,...allPoints.map(p=>Math.abs(p[1])));resultWingScale=Math.min(360/maxSpan,175/maxChord);
 const rows=report.rows.filter(r=>$('showRejected').checked||['Eligible','Frontier'].includes(r.torque_status));
 $('resultSummary').textContent=`${report.frontier_count} frontier designs · ${report.eligible_count} eligible of ${report.total_count} cases · full peak-torque range, with no single cutoff. Ordered by mean thrust / peak root torque${selectedSpanClass==='all'?'':'; span class '+selectedSpanClass+' m total'}.`;
 const study=studies.find(s=>s.id===currentStudy),s=study?.config.settings;
 if(currentStudy==='master')$('resultSummary').textContent+=' Selected masters: '+(report.selected?.join(' + ')||'none')+'. Driving conditions may differ between studies.';
 if(report.model_mode)$('resultSummary').textContent+=` Model: ${report.model_mode==='aeroelastic'?'native aeroelastic':'rigid'}.`;
 if(s)$('resultSummary').textContent+=` Study motion: ${s.frequency_hz} Hz, speed ${s.speed_mps} m/s; ${study.config.motion_range?study.config.motion_range.minimum_deg+'° to '+study.config.motion_range.maximum_deg+'°':'half-stroke '+s.amplitude_deg+'°'}.`;
 page=Math.max(0,Math.min(page,Math.ceil(rows.length/25)-1));
 $('rankedRows').innerHTML=rows.slice(page*25,(page+1)*25).map(r=>`<article class="wing-row"><div class="rank">${r.ratio_rank??'—'}</div><button class="wing-thumb" data-inspect-wing="${esc(rowKey(r))}" aria-label="Inspect ${esc(r.design_name||r.id)}">${outline(r,false,true)}</button><div><div class="row-top"><strong>${esc(r.design_name||r.id)} · ${esc(r.id)}</strong><span class="badge ${r.thrust_rank?'':'bad'}">${esc(r.torque_status)}</span></div>${sourceNote(r)}${values(r)}${r.error?`<details><summary>Solver error</summary><pre>${esc(r.error)}</pre></details>`:''}<div class="actions"><button data-refine="${esc(rowKey(r))}">Refine this shape</button><button data-resize="${esc(rowKey(r))}">Resize span</button>${links(r)}<button data-evolution-gif="${esc(rowKey(r))}" ${evolutionSource(r)?'':'disabled title="No adaptive design history was recorded"'}>Export design evolution GIF</button><span class="gif-links"></span></div></div></article>`).join('')||'<p class="help">No cases in this view. Check “Show rejected cases” to inspect exclusions.</p>';
 document.querySelectorAll('[data-inspect-wing]').forEach(b=>b.onclick=()=>inspectWing(report.rows.find(r=>rowKey(r)===b.dataset.inspectWing)));
 document.querySelectorAll('[data-evolution-gif]').forEach(button=>button.onclick=async()=>{
  const row=report.rows.find(r=>rowKey(r)===button.dataset.evolutionGif);if(!row)return;
  const source=evolutionSource(row);if(!source)return;
  try{button.disabled=true;const result=await api('evolution-gif',source);button.nextElementSibling.innerHTML=`<a href="/files/${esc(result.file)}" download>Download evolution GIF · ${result.frame_count} frames</a>`;notify(result.note);}
  catch(error){notify(error.message);}finally{button.disabled=false;}
 });
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
 $('searchMode').value='grid';updateSearchMode();$('spanSearch').checked=false;
 $('nodeCount').value=Math.max(16,sections.length);$('localVariation').value=5;
 $('decreasing').checked=sections.every((s,i)=>!i||s.chord_m<=sections[i-1].chord_m);
 $('studyName').value=(baseline.name+' refinement').slice(0,80);updateBaseline();show('setup');await applyRefinementNodes();notify('Refinement loaded with all chords fixed. Set min/max/samples only on the chords you want to vary, or select rows and apply the variation preset.');
}
function loadSpanResize(row){
 if(!row?.sections?.length){notify('Choose a saved sectioned wing.');return;}
 const study=studies.find(s=>s.id===(row._study||currentStudy));if(study)fill(study.config);
 refinementSource={name:row.design_name||row.id,sections:structuredClone(row.sections),source_study:row._study||currentStudy,source_case:row.id};
 baseline=structuredClone(refinementSource);refinementActive=true;
 $('searchMode').value='grid';updateSearchMode();$('spanSearch').checked=false;
 $('nodeCount').value=baseline.sections.length;$('totalSpan').value=2*baseline.sections.at(-1).y_m+Number($('hingeGap').value);
 $('spanMinimum').value=$('totalSpan').value;$('spanMaximum').value=$('totalSpan').value;$('spanSamples').value=5;
 $('studyName').value=(baseline.name+' span study').slice(0,80);
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
 const selection=JSON.stringify([currentStudy,selectedSpanClass,$('resultsModel')?.value||'rigid',...['current','old','adaptive'].map(g=>!!$(g+'Master')?.checked)]);
 if(selection!==frontierSelection){invalidateFrontier();frontierSelection=selection;}
}
function invalidateFrontier(){frontierSerial++;frontierData=null;$('frontierResult').innerHTML='';$('frontierStatus').textContent='Generate the wing plot to explore the best observed designs across peak root torque.';$('makeFrontier').disabled=false;}
function inspectFrontier(){
 if(!frontierData)return;
 const cap=Number($('frontierTorque').value),bands=frontierData.comparison_mode==='bands';
 const point=bands?frontierData.points[Number($('frontierPoint').value)]:frontierData.points.findLast(r=>r.single_wing_peak_abs_roll_moment_Nm<=cap+1e-12*Math.max(1,Math.abs(cap)));
 $('frontierTorqueValue').textContent=fmt(cap)+' N m allowable';
 if(point)$('frontierPoint').value=frontierData.points.indexOf(point);
 $('frontierWing').innerHTML=point?`${outline(point,true)}<h3>${esc(point.design_name||point.id)} · ${esc(point.id)}</h3><p>${bands?`Torque band: <strong>${fmt(point.torque_band_min_nm)}–${fmt(point.torque_band_max_nm)} N m</strong> · ${point.torque_band_count} evaluated designs. Highest observed mean thrust:`:'Best available mean thrust:'} <strong>${fmt(point.single_wing_mean_thrust_N)} N</strong> per wing · peak root torque: <strong>${fmt(point.single_wing_peak_abs_roll_moment_Nm)} N m</strong></p><p>Span: ${fmt(point.single_wing_span_m)} m per wing · ${fmt(point.effective_total_span_m)} m total</p><p class="help">${esc(point._study||currentStudy)} / ${esc(point.id)}${point.global_case_no?' · case #'+esc(point.global_case_no):''}</p>`:'No eligible design at this allowable torque.';
}
$('makeFrontier').onclick=async()=>{
 if(!currentStudy){notify('Select a study or master comparison first.');return;}
 const serial=++frontierSerial;
 try{
  $('makeFrontier').disabled=true;$('frontierStatus').textContent='Building the wing comparison…';
  const data=await api('torque-frontier',{study:currentStudy,comparison_mode:$('frontierMode').value,torque_band_width_nm:Number($('frontierBandWidth').value),span_class:selectedSpanClass,model_mode:$('resultsModel')?.value||'rigid',wing_size_percent:Number($('frontierSize').value),minimum_spacing_nm:Number($('frontierSpacing').value),torque_min_nm:$('frontierMin').value,torque_max_nm:$('frontierMax').value,generations:['current','old','adaptive'].filter(g=>$(g+'Master')?.checked)});
  if(serial!==frontierSerial)return;frontierData=data;
  const min=data.minimum_torque_nm,max=data.slider_maximum_torque_nm;
  $('frontierResult').innerHTML=`<div id="interactiveFrontier" style="overflow:auto"></div><div class="actions">${data.files.map(f=>`<a href="/files/${esc(f)}" download>${f.endsWith('.png')?'Wing plot PNG':'Frontier designs CSV'}</a>`).join('')}</div><label class="${data.comparison_mode==='bands'?'hidden':''}">Explore allowable root torque <output id="frontierTorqueValue"></output><input id="frontierTorque" type="range" min="${min}" max="${max}" step="any" value="${min}" style="width:100%"></label><label>${data.comparison_mode==='bands'?'Torque-band winner':'Frontier design'}<select id="frontierPoint">${data.points.map((r,i)=>r.single_wing_peak_abs_roll_moment_Nm<=max?`<option value="${i}">${data.comparison_mode==='bands'?`${fmt(r.torque_band_min_nm)}–${fmt(r.torque_band_max_nm)} N m · `:''}${fmt(r.single_wing_peak_abs_roll_moment_Nm)} N m → ${fmt(r.single_wing_mean_thrust_N)} N · ${esc(r.design_name||r.id)}</option>`:'').join('')}</select></label><div id="frontierWing"></div>`;
  mountFrontierPlot(data);
  $('frontierTorque').oninput=inspectFrontier;
  $('frontierPoint').onchange=()=>{$('frontierTorque').value=data.points[Number($('frontierPoint').value)].single_wing_peak_abs_roll_moment_Nm;inspectFrontier();};
  $('frontierStatus').textContent=`${data.model_mode==='aeroelastic'?'Native aeroelastic':'Rigid'} · ${data.eligible_count} eligible designs · ${data.comparison_mode==='bands'?`${data.plotted_count} band winners from ${data.range_eligible_count} designs in range · ${fmt(data.torque_band_width_nm)} N m bands · highest observed mean thrust in each band`:`${data.plotted_count} frontier wings + ${data.background_count} sampled other designs · minimum spacing ${fmt(data.minimum_spacing_nm)} N m`}. Color: thrust / torque (1/m). Wings share a physical scale; ${data.comparison_mode==='bands'?'each marker is an observed band winner, with no inferred scaling or interpolation.':'dark outlines identify the frontier.'} Hover to enlarge; click for metrics. Plot range affects display only; all eligible data remain available. Mixed study driving conditions may differ.`;
  inspectFrontier();
 }catch(error){if(serial===frontierSerial)$('frontierStatus').textContent=error.message;}
 finally{if(serial===frontierSerial)$('makeFrontier').disabled=false;}
};
function updateFrontierMode(){const bands=$('frontierMode').value==='bands';$('frontierBandWidth').disabled=!bands;$('frontierSpacing').disabled=bands;invalidateFrontier();}
$('frontierMode').onchange=updateFrontierMode;
for(const id of ['frontierMin','frontierMax','frontierSize','frontierSpacing','frontierBandWidth'])$(id).oninput=invalidateFrontier;
let landscapeSerial=0;
function plotAxes(){return ['X','Y','Z'].map(axis=>$('plotAxis'+axis).value);}
function landscapeRows(){
 const axes=plotAxes();
 let rows=(report?.rows||[]).map(r=>({...r,plot_ratio:r.single_wing_peak_abs_roll_moment_Nm>0?r.single_wing_mean_thrust_N/r.single_wing_peak_abs_roll_moment_Nm:null,
  single_wing_thrust_roll_ratio_1pm:r.single_wing_peak_abs_roll_moment_Nm>0?r.single_wing_mean_thrust_N/r.single_wing_peak_abs_roll_moment_Nm:null})).filter(r=>['Eligible','Frontier'].includes(r.torque_status)&&Number.isFinite(r.area_m2)&&r.area_m2>0&&axes.every(key=>Number.isFinite(r[key])));
 if($('plotFrontierOnly').checked)rows=rows.filter(r=>r.is_frontier);
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
  const data=await api('thrust-landscape',{study:currentStudy,span_class:selectedSpanClass,full_range:true,
   model_mode:$('resultsModel')?.value||'rigid',generations:['current','old','adaptive'].filter(g=>$(g+'Master')?.checked),case_keys:rows.map(rowKey),axes:plotAxes()});
  if(serial!==landscapeSerial)return;
  renderLandscape(data);$('landscapeStatus').textContent=data.note;
 }catch(error){if(serial===landscapeSerial)$('landscapeStatus').textContent=error.message;}
 finally{if(serial===landscapeSerial)$('makeLandscape').disabled=false;}
};
for(const id of ['plotStudy','plotFrontierOnly','plotCount','plotAreaMin','plotAreaMax','plotRatioMin','plotRatioMax','plotAxisX','plotAxisY','plotAxisZ'])$(id).onchange=()=>{invalidateLandscape();syncLandscapeSources();};
$('setupTab').onclick=()=>show('setup');$('resultsTab').onclick=()=>show('results');
$('setup').oninput=event=>{if(event.target.id==='previewCase')return;if(event.target.id==='spanSearch')updateBaseline();if(['totalSpan','hingeGap'].includes(event.target.id)){if(baseline&&event.target.id==='hingeGap')$('totalSpan').value=2*baseline.sections.at(-1).y_m+Number($('hingeGap').value);renderRanges(readRanges());updateBaseline();}clearTimeout(timer);timer=setTimeout(preview,350);};
$('previewCase').onchange=drawPreview;
$('applyNodes').onclick=()=>{const n=Number($('nodeCount').value);if(!Number.isInteger(n)||n<2||n>64){notify('Use 2–64 chord nodes.');return;}if(baseline){applyRefinementNodes();return;}const old=readRanges();renderRanges(Array.from({length:n},(_,i)=>old[i]||{min_m:.06,max_m:.14,count:3}));preview();};
$('regularGrid').onclick=()=>{$('spanSearch').checked=false;baseline=null;refinementSource=null;refinementActive=false;renderRanges(readRanges().map(r=>({...r,count:r.min_m===r.max_m?1:3})));updateBaseline();preview();};
$('applyLocalBounds').onclick=()=>{const rows=[...$('ranges').querySelectorAll('tr')],chosen=rows.filter(r=>r.querySelector('[data-vary]')?.checked);if(!chosen.length){notify('Select the chord rows you want to vary first, or edit their min/max/samples directly.');return;}const pct=Number($('localVariation').value)/100;if(!Number.isFinite(pct)||pct<0||pct>1){notify('Use a variation between 0 and 100%.');return;}rows.forEach((row,i)=>{if(!row.querySelector('[data-vary]')?.checked)return;const chord=baseline.sections[i].chord_m;row.querySelector('[data-key="min_m"]').value=Number((chord*(1-pct)).toPrecision(12));row.querySelector('[data-key="max_m"]').value=Number((chord*(1+pct)).toPrecision(12));row.querySelector('[data-key="count"]').value=pct?3:1;});preview();};
$('fixAllChords').onclick=()=>{if(!baseline)return;renderRanges(baseline.sections.map(s=>({min_m:s.chord_m,max_m:s.chord_m,count:1})));updateBaseline();preview();};
$('adaptiveElastic').onchange=()=>{updateSearchMode();preview();};
$('nativeDampingPreset').onclick=()=>{$('nativeDamping').value=10;preview();};
$('searchMode').onchange=()=>{updateSearchMode();preview();};
$('adaptiveApplyBounds').onclick=()=>{try{renderAdaptiveBounds();preview();}catch(error){notify(error.message);}};
$('loadEvolution').onclick=async()=>{
 try{const result=await api('adaptive-evolution',{study:currentStudy});
 $('evolutionResult').innerHTML=`<p class="help">${result.events.length} saved discovery states. ${result.hypervolume?`Normalized hypervolume measures frontier coverage. The complete trace uses the same reference: thrust 0 N, torque ${fmt(result.hypervolume.reference_torque_Nm)} N m. This is a measurement reference, never a search ceiling; the full trace is recalculated when automatic scaling expands.`:''} ${result.objective==='pareto_mean_thrust_peak_root_torque_v1'?'Pareto frontier discoveries form branches. Thrust/torque need not climb; selected-wing GIFs follow actual parent ancestry.':result.objective==='single_wing_mean_thrust_over_peak_root_torque_v1'?'Historical ratio-ascent run. New searches explore the thrust–torque frontier.':'Historical constrained-thrust run. New searches explore the frontier without ceilings.'} ${esc(result.summary.stop_reason||'Search is still running; accepted states remain saved.')}</p>${result.progress_csv?`<p><a href="/files/${esc(result.progress_csv)}" download>Frontier progress CSV</a></p>`:''}${result.files.map(f=>`<div><img src="/files/${esc(f)}?v=${result.events.length}" style="max-width:100%" alt="${f.endsWith('.webp')?'Accepted wing evolution':'Pareto frontier progress'}"><p><a href="/files/${esc(f)}" download>Download ${f.endsWith('.webp')?'animation':'progress PNG'}</a></p></div>`).join('')}`;
 const jobs=[...new Set(result.events.map(e=>e.job))];
 if(jobs.length){$('evolutionResult').insertAdjacentHTML('afterbegin',`<label>Inspect frontier discoveries<select id="evolutionJob">${jobs.map(job=>{const e=result.events.find(e=>e.job===job);return `<option value="${job}">Job ${job} · span ${fmt(e.span_m)} m</option>`;}).join('')}</select></label><label>Discovery<input id="evolutionFrame" type="range" min="0" step="1" value="0" style="width:100%"></label><div id="evolutionWing"></div>`);
 const inspect=()=>{const path=result.events.filter(e=>e.job===Number($('evolutionJob').value));$('evolutionFrame').max=path.length-1;const index=Math.min(Number($('evolutionFrame').value),path.length-1),e=path[index];$('evolutionWing').innerHTML=outline(e.case,true)+`<p>State ${index+1} of ${path.length} · ${esc(e.case.id)} · ${esc(e.case.status)}</p>`+values(e.case);};
 $('evolutionJob').onchange=()=>{$('evolutionFrame').value=0;inspect();};$('evolutionFrame').oninput=inspect;inspect();}
 }catch(error){notify(error.message);}
};
$('runStudy').onclick=async()=>{try{$('runStudy').disabled=true;const r=await api('start',configuration());currentStudy=r.id;show('results');}catch(error){notify(error.message);preview();}};
$('resultsModel').onchange=()=>{page=0;evaluate();};
$('studySelect').onchange=()=>{currentStudy=$('studySelect').value;page=0;report=null;$('exportLinks').innerHTML='';const study=studies.find(s=>s.id===currentStudy);$('resultsModel').disabled=currentStudy!=='master';if(study)$('resultsModel').value=study.config.settings.aeroelastic_enabled?'aeroelastic':'rigid';$('evolutionCard').classList.toggle('hidden',!study?.config.adaptive_search?.enabled);$('evolutionResult').innerHTML='';renderProgress(study);evaluate();};
$('refreshResults').onclick=refreshIndex;$('exportComparison').onclick=()=>evaluate(true);$('showRejected').onchange=()=>{page=0;renderResults();};
for(const g of ['current','old','adaptive'])$(g+'Master').onchange=()=>{page=0;$('exportLinks').innerHTML='';evaluate();};
$('previousPage').onclick=()=>{page--;renderResults();};$('nextPage').onclick=()=>{page++;renderResults();};
$('useStudy').onclick=()=>{const s=studies.find(s=>s.id===currentStudy);if(s){fill(s.config);show('setup');preview();notify('Study settings loaded. Review the selected native model and motion range.');}};
$('stopStudy').onclick=async()=>{try{await api('stop',{id:currentStudy});refreshIndex();}catch(error){notify(error.message);}};
$('exportSettings').onclick=async()=>{try{const prepared=await api('preview',configuration());const url=URL.createObjectURL(new Blob([JSON.stringify(prepared.config,null,2)],{type:'application/json'}));const a=document.createElement('a');a.href=url;a.download='wing-study-settings.json';a.click();setTimeout(()=>URL.revokeObjectURL(url),1000);}catch(error){notify(error.message);}};
$('importSettings').onclick=()=>$('settingsFile').click();$('settingsFile').onchange=async()=>{try{fill(JSON.parse(await $('settingsFile').files[0].text()));notify('Settings loaded. Review the selected native model before starting.');}catch(error){notify(error.message);}finally{$('settingsFile').value='';}};
async function init(){try{const d=await api('defaults');defaults=d.config;updateFrontierMode();fill(defaults,true);await refreshIndex();if(location.hash.startsWith('#catalog')||location.hash==='#results')show('results');setInterval(()=>{if(!$('results').classList.contains('hidden')&&(currentStudy==='master'?studies.some(s=>s.status.state==='running'):studies.find(s=>s.id===currentStudy)?.status.state==='running'))refreshIndex();},4000);}catch(error){notify(error.message);}}
init();
