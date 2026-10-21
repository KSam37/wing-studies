const $ = id => document.getElementById(id);
const esc = s => String(s ?? '').replace(/[&<>"']/g, c => ({'&':'&amp;','<':'&lt;','>':'&gt;','"':'&quot;',"'":'&#39;'}[c]));
let defaults, fields, familyNames, planData, studyData = [], currentStudy = '';
function profileLinks(r,base){
  if(r.has_paired_profiles){const label=r.profile_is_cutting_pattern?'cutting SVG':'projection SVG';return `<a href="${base}wing_left.svg" download>Left ${label}</a> · <a href="${base}wing_right.svg" download>Right ${label}</a> · `;}
  return r.has_profile_svg?`<a href="${base}wing_profile.svg" download>1:1 SVG outline</a> · `:'';
}
let selected = new Map(), lastOverlay = [], defaultsRoot = '', previewSerial = 0, timer;
const geometryKeys = ['span_m','root_chord_m','tip_ratio','mid_ratio','sweep_deg','incidence_deg'];
const motionKeys = ['frequency_hz','amplitude_deg','speed_mps'];
const fixedKeys = [...motionKeys,'waveform_signature','rho','nu','dt_s','cycles','span_panels','chord_panels','wake_model','wake_cycles','tail_signature'];
const captions = {
  span_m:'Tip-to-tip, including the hinge gap. No imposed maximum.',
  root_chord_m:'Root chord. No imposed maximum.',
  tip_ratio:'Tip chord ÷ root chord; an independent sweep input.',
  mid_ratio:'Midspan chord ÷ root chord; an independent sweep input.',
  sweep_deg:'Positive leading-edge sweep moves the tip aft.',
  incidence_deg:'Whole-wing pitch, shown in the side view.',
  frequency_hz:'One constant frequency for all geometries. Period = 1 / f.',
  amplitude_deg:'Half the peak-to-peak stroke for all geometries. Sine: ± this angle. Custom: check the preview range.',
  speed_mps:'One prescribed speed through still water. Stock Ptera requires > 0.'
};

async function api(path, body) {
  const response = await fetch('/api/'+path, body === undefined ? {} : {
    method:'POST', headers:{'Content-Type':'application/json'}, body:JSON.stringify(body)
  });
  const data = await response.json();
  if (!response.ok) throw Error(data.error || 'Request failed');
  return data;
}
function notify(text) {
  $('toast').textContent = text; $('toast').classList.remove('hidden');
  setTimeout(() => $('toast').classList.add('hidden'), 6500);
}
function tab(name) {
  for (const n of ['setup','results','method','catalog']) $(n).classList.toggle('hidden', n !== name);
  document.querySelectorAll('.nav').forEach(b => b.classList.toggle('active', b.dataset.tab === name));
  if (name === 'results') refresh();
  if(name==='catalog'){if(!location.hash.startsWith('#catalog'))history.replaceState(null,'','#catalog');loadMaster();}else if(location.hash.startsWith('#catalog'))history.replaceState(null,'',location.pathname);
  window.scrollTo(0,0);
}
document.querySelectorAll('.nav').forEach(b => b.onclick = () => tab(b.dataset.tab));
function field(id, label, value, help='', type='text') {
  return `<label>${esc(label)}<input id="${id}" type="${type}" value="${esc(value)}" ${type==='number'?'step="any"':''}><div class="help">${esc(help)}</div></label>`;
}
function normalizeConfig(original) {
  const c = structuredClone(original);
  c.settings = {...defaults.settings, ...c.settings};
  if (c.schema_version !== 2) {
    let changed = [];
    for (const key of motionKeys) {
      if (c.sweep?.[key] !== undefined) {
        const first = String(c.sweep[key]).split(/[,:]/)[0].trim();
        c.settings[key] = Number(first);
        if (/[,:]/.test(String(c.sweep[key]))) changed.push(fields[key][0]);
      }
    }
    const family = c.families?.[0];
    if (family === 'rectangular') c.sweep.tip_ratio = c.sweep.mid_ratio = '1';
    if (family === 'shoulder') c.sweep.mid_ratio = '1';
    if (family === 'tapered') {
      const tips = parseList(c.sweep.tip_ratio);
      c.sweep.mid_ratio = [...new Set(tips.map(x => (1+x)/2))].join(', ');
    }
    c.migration_note = 'Legacy study imported as independent geometry inputs. '+
      (changed.length ? `First value retained for fixed ${changed.join(', ')}. ` : '')+
      'Review the geometry grid before running.';
  }
  if(c.mode!=='custom'&&c.mode!=='shape_sweep')c.migration_note='Legacy geometry grid replaced by chord-node search. Review node ranges before running.';
  c.schema_version = 2;
  c.limits = {min_chord_m:c.limits?.min_chord_m ?? '',max_chord_m:c.limits?.max_chord_m ?? ''};
  c.sweep = Object.fromEntries(geometryKeys.map(k => [k,c.sweep?.[k] ?? defaults.sweep[k]]));
  return c;
}
function parseList(value) {
  const text = String(value);
  if (!text.includes(':')) return text.split(',').map(Number);
  const [start,stop,step] = text.split(':').map(Number);
  if (!(step>0) || stop<start) return [];
  const result=[];
  for (let i=0; start+i*step <= stop+step*1e-9 && i<100000; i++) result.push(start+i*step);
  return result;
}
function fill(original) {
  const c = normalizeConfig(original), s = c.settings;
  customDesigns=structuredClone(c.designs||[]); editingDesign=-1;
  $('studyMode').value=c.mode==='custom'?'custom':'shape_sweep';
  fillShape(c.shape_sweep||defaults.shape_sweep);
  draft=structuredClone(customDesigns[0]||defaultWing()); renderEditor(); modeChanged(false);
  $('name').value = c.name;
  $('migrationNotice').textContent = c.migration_note || '';
  $('migrationNotice').classList.toggle('hidden', !c.migration_note);
  $('geometryFields').innerHTML = geometryKeys.map(k => field(k,fields[k][0]+(fields[k][1]?` (${fields[k][1]})`:''),c.sweep[k],captions[k])).join('');
  $('motionFields').innerHTML = motionKeys.map(k => field(k,fields[k][0]+` (${fields[k][1]})`,s[k],captions[k],'number')).join('');
  fillWaveform(c.waveform||defaults.waveform);
  $('fluidFields').innerHTML = field('rho','Water density ρ (kg/m³)',s.rho,'Constant across the study.','number')+
    field('nu','Kinematic viscosity ν (m²/s)',s.nu,'Constant across the study.','number');
  $('limitFields').innerHTML = field('min_chord_m','Optional minimum chord (m)',c.limits.min_chord_m,'Blank means no lower fabrication bound.','number')+
    field('max_chord_m','Optional maximum chord (m)',c.limits.max_chord_m,'Blank means no upper fabrication bound.','number');
  $('solverFields').innerHTML = field('gap_m','Root hinge gap (m)',s.gap_m,'Reference only: single-wing span = (reference total span − gap) / 2. The simulated root is at the origin.','number')+
    field('dt_s','Delta time Δt (s)',s.dt_s,'Fixed for every case; at least 30 steps per flap.','number')+
    field('cycles','Number of cycles',s.cycles,'Fixed; at least 3 for the two-cycle check.','number')+
    field('span_panels','Span panels per wing',s.span_panels,'Fixed spanwise resolution.','number')+
    field('chord_panels','Chordwise panels',s.chord_panels,'Fixed chordwise resolution.','number')+
    field('cycle_tolerance_pct','Cycle tolerance (%)',s.cycle_tolerance_pct,'Fixed settling criterion.','number')+
    field('case_budget','Case budget',s.case_budget,'Raise this for larger grids; it is a run-size control, not a geometry bound.','number');
  $('solverFields').insertAdjacentHTML('beforeend',`<label>Wake model<select id="wake_model"><option value="free" ${s.wake_model==='free'?'selected':''}>Free wake · includes roll-up · slower</option><option value="prescribed" ${s.wake_model==='prescribed'?'selected':''}>Prescribed wake · faster screening</option></select><div class="help">Prescribed wake convects with the inflow, omitting induced wake roll-up. Forces can change.</div></label>`+
    field('wake_cycles','Retain wake history (cycles)',s.wake_cycles,'0 = full history. Positive whole number keeps only that many cycles. Try 2 for screening; check finalists with longer/full wake.','number')+
    `<div class="full note"><button class="btn" id="fastWake">Use faster wake settings</button><span class="help"> Prescribed wake + 2 retained cycles. Motion, time step, mesh and total cycles stay as entered.</span></div>`);
  $('fastWake').onclick=()=>{$('wake_model').value='prescribed';$('wake_cycles').value='2';preview();};
  fillTail(c.tail||defaults.tail);

  preview();
}
function config() {
  const c = {schema_version:2,name:$('name').value,sweep:{},limits:{},settings:{}};
  c.mode=$('studyMode').value; c.designs=structuredClone(customDesigns);
  geometryKeys.forEach(k => c.sweep[k] = $(k).value);
  Object.keys(defaults.limits).forEach(k => c.limits[k] = $(k).value);
  Object.keys(defaults.settings).filter(k => k !== 'save_solver').forEach(k => c.settings[k] = $(k).value);
  c.settings.save_solver = false;
  c.tail={...tailConfig(),enabled:false};
  c.shape_sweep=readShape();
  c.waveform={mode:$('waveformMode').value,points:$('waveformPoints').value};
  return c;
}
$('setup').addEventListener('input', e => {if(e.target.id==='previewCase')return;clearTimeout(timer);timer=setTimeout(preview,350);});
$('setup').addEventListener('change', e => {
  if (e.target.id === 'previewCase') return;
  clearTimeout(timer); timer=setTimeout(preview,100);
});
async function preview() {
  const serial = ++previewSerial;
  try {
    const p = await api('preview', config());
    if (serial !== previewSerial) return;
    const previous = Number($('previewCase').value || 0);
    planData=p;
    drawMotion(p.motion_preview);
    const est=p.runtime_estimate,secs=est?.case_seconds*(p.new_simulation_count??p.case_count)+(p.cached_case_count||0);
    $('runtimeEstimate').textContent=secs?`Estimated runtime: ${duration(secs*.5)}–${duration(secs*2)} · ${est.timing_samples} similar local case timings; updates during the run.`:'Runtime ETA calibrates after the first case. No matching local timings yet.';
    $('validation').innerHTML = `<div class="note">${p.shape_grid?`${p.shape_grid.count.toLocaleString()} admissible combinations · ${p.shape_grid.pruned_count.toLocaleString()} pruned by zero-tail and optional taper rules.`:''}${p.skipped?` ${p.skipped} excluded by optional chord bounds.`:''}</div>`;
    $('run').disabled=false;
    $('run').textContent=p.cached_case_count?`Run ${p.new_simulation_count} new · reuse ${p.cached_case_count} cached`:`Run ${p.case_count.toLocaleString()} ${p.case_count===1?'case':'cases'}`;
    $('count').textContent=p.case_count.toLocaleString();
    $('previewDetails').textContent=`${p.duplicate_geometry_count?`${p.duplicate_geometry_count} repeated geometries merged · `:''}${p.cached_case_count?`${p.cached_case_count} exact completed matches will be reused · `:''}${p.panels_per_case} total surface panels · ${p.max_steps} time steps per case · identical motion and numerical settings`;
    $('previewCase').innerHTML=p.cases.map((c,i)=>`<option value="${i}">${esc(c.design_name||c.id)} · span ${c.span_m} m · incidence ${c.incidence_deg}° · sweep ${c.sweep_deg}°</option>`).join('');
    $('previewCase').value=Math.min(previous,p.cases.length-1);
    drawCandidate();
  } catch(e) {
    if (serial !== previewSerial) return;
    planData=null; $('validation').innerHTML=`<div class="error">${esc(e.message)}</div>`;
    $('motionPreview').innerHTML='';$('motionDetails').textContent=e.message;
    $('run').disabled=true; $('run').textContent='Review study settings'; $('count').textContent='—';
    $('previewCase').innerHTML='';$('wingSvg').innerHTML='';$('sideSvg').innerHTML='';$('area').textContent='—';$('ar').textContent='—';$('candidateDetails').textContent='';$('previewDetails').textContent='Add saved designs or review the inputs.';
  }
}
$('previewCase').onchange=drawCandidate;
function drawCandidate() {
  if (!planData) return;
  const c=planData.cases[Number($('previewCase').value)||0], s=planData.settings;
  $('area').textContent=(c.geometry.area_m2/2).toFixed(3); $('ar').textContent=(c.single_wing_span_m**2/(c.geometry.area_m2/2)).toFixed(2);
  drawWing(c,s); drawSide(c);
  drawTailLayout(c,s,planData.tail);
  $('candidateDetails').textContent=c.sections?`${c.design_name} · ${c.sections.length} sections. Top and front show the actual neutral shape. Single-wing root-to-tip span ${c.single_wing_span_m.toPrecision(4)} m; area uses nominal unpitched leading-edge positions.`:`Root / mid / tip chords: ${[1,c.mid_ratio,c.tip_ratio].map(r=>(r*c.root_chord_m).toFixed(3)).join(' / ')} m. Incidence ${c.incidence_deg}°, sweep ${c.sweep_deg}°.`;
}
function drawWing(c,s,target='wingSvg') {
  if(c.sections){drawSectionView(c,s,target,'top');return;}
  const pts=c.geometry.stations, span=(c.span_m-s.gap_m)/2, gridId=target+'Grid';
  const xs=pts.flatMap(p=>[p.x_m,p.x_m+p.chord_m]),min=Math.min(...xs),max=Math.max(...xs);
  const scale=Math.min(360/span,155/(max-min)),cx=220-span*scale/2,top=30;
  const X=y=>cx+y*scale,Y=x=>top+(x-min)*scale;
  let out=`<defs><pattern id="${gridId}" width="20" height="20" patternUnits="userSpaceOnUse"><path d="M20 0H0V20" fill="none" stroke="#e8eef0" stroke-width=".6"/></pattern></defs><rect width="440" height="235" fill="url(#${gridId})"/><text x="18" y="18" font-size="10" fill="#6d8591">TOP · FORWARD ↑</text>`;
  for (const side of [1]) {
    const front=pts.map(p=>[X(side*p.y_m),Y(p.x_m)]);
    const back=pts.map(p=>[X(side*p.y_m),Y(p.x_m+p.chord_m)]);
    out+=`<polygon points="${[...front,...back.reverse()].map(p=>p.join(',')).join(' ')}" fill="#c6e6df" stroke="#007f78" stroke-width="1.6"/>`;
    for (const p of pts) {
      const x=X(side*p.y_m);
      out+=`<line x1="${x}" y1="${Y(p.x_m)}" x2="${x}" y2="${Y(p.x_m+p.chord_m)}" stroke="#6a9f99" stroke-dasharray="3 3"/>`;
    }
  }
  out+=`<line x1="${X(0)}" y1="207" x2="${X(span)}" y2="207" stroke="#7b929d"/><text x="220" y="225" text-anchor="middle" font-size="11" fill="#516b79">Single-wing span ${span.toPrecision(4)} m</text>`;
  $(target).innerHTML=out;
}
function drawSide(c,target='sideSvg') {
  if(c.sections){drawSectionView(c,{gap_m:Number($('gap_m').value)},target,'front');return;}
  const angle=c.incidence_deg*Math.PI/180, length=Math.min(210,56/Math.max(Math.abs(Math.sin(angle)),1e-9)), x=95, y=83;
  const tx=x+length*Math.cos(angle),ty=y+length*Math.sin(angle),r=46;
  const arc=`M ${x+r} ${y} A ${r} ${r} 0 0 ${angle>=0?1:0} ${x+r*Math.cos(angle)} ${y+r*Math.sin(angle)}`;
  $(target).innerHTML=`<text x="18" y="19" font-size="10" fill="#6d8591">SIDE · ROOT SECTION AT NEUTRAL FLAP</text>
    <line x1="35" y1="${y}" x2="395" y2="${y}" stroke="#9eafb7" stroke-dasharray="5 4"/>
    <line x1="${x}" y1="${y}" x2="${tx}" y2="${ty}" stroke="#007f78" stroke-width="4"/>
    <circle cx="${x}" cy="${y}" r="4" fill="#172b3b"/>
    <path d="${arc}" fill="none" stroke="#d07a28" stroke-width="1.5"/>
    <text x="178" y="48" font-size="16" fill="#a35d20">${c.incidence_deg}° incidence</text>
    <text x="${x-8}" y="${y-10}" text-anchor="end" font-size="10" fill="#526b78">LE</text>
    <text x="${tx+10}" y="${ty+3}" font-size="10" fill="#526b78">TE</text>
    <text x="18" y="153" font-size="11" fill="#647787">Forward ← · dashed: zero-incidence reference · chord ${c.root_chord_m} m</text>`;
}
$('run').onclick=async()=>{
  try {
    $('run').disabled=true; const r=await api('start',config());
    currentStudy=r.id; selected.clear(); tab('results');
    notify('Geometry study started. Motion, water and numerical settings are constant.');
  } catch(e) {notify(e.message);preview();}
};
$('exportConfig').onclick=()=>{
  const blob=new Blob([JSON.stringify(config(),null,2)],{type:'application/json'}),a=document.createElement('a');
  a.href=URL.createObjectURL(blob);a.download='wing-study-settings.json';a.click();URL.revokeObjectURL(a.href);
};
$('importConfig').onclick=()=>$('configFile').click();
$('configFile').onchange=async e=>{
  try {const c=normalizeConfig(JSON.parse(await e.target.files[0].text()));await api('preview',c);fill(c);notify('Settings loaded. Review the preview before running.');}
  catch(err){notify(err.message);}e.target.value='';
};

function chosenStudy(){return studyData.find(s=>s.id===currentStudy);}
function refs(){return [...selected.values()].map(r=>({study:r._study,id:r.id}));}
let rendering=false;
async function refresh(){if(rendering)return;rendering=true;try{studyData=await api('studies');if(!currentStudy&&studyData.length)currentStudy=studyData[0].id;$('studySelect').innerHTML='<option value="all">All studies · ranking only</option>'+studyData.map(s=>`<option value="${s.id}">${esc(s.name)} · ${esc(s.created.slice(0,16).replace('T',' '))}</option>`).join('');$('studySelect').value=currentStudy||'all';renderResults();}catch(e){notify(e.message);}finally{rendering=false;}}
function activeRows(){let set=currentStudy==='all'?studyData:studyData.filter(s=>s.id===currentStudy);return set.flatMap(s=>s.rows.map(r=>({...r,_study:s.id,_studyName:s.name})));}
const shapeObjective='single_wing_thrust_roll_ratio_1pm';
function shapeEligible(r){return r.status==='ok'&&r.shape_ratio_valid&&Number.isFinite(r[shapeObjective]);}
function duration(seconds){if(seconds<60)return Math.ceil(seconds)+' s';if(seconds<3600)return Math.ceil(seconds/60)+' min';return (seconds/3600).toFixed(1)+' h';}
function rankWingPreview(r){
 const study=studyData.find(s=>s.id===r._study),gap=Number(study?.config.settings.gap_m??.04),half=(r.span_m-gap)/2;
 const ss=r.geometry?.stations||[0,.5,1].map((fraction,i)=>({le:[Math.tan(r.sweep_deg*Math.PI/180)*half*fraction,half*fraction,0],te:[Math.tan(r.sweep_deg*Math.PI/180)*half*fraction+r.root_chord_m*[1,r.mid_ratio,r.tip_ratio][i],half*fraction,0]}));
 const isolated=r.simulation_mode==='isolated_single_wing_v1',offset=isolated?0:gap/2;
 const polys=(isolated?[1]:[-1,1]).map(side=>[...ss.map(p=>[side*(p.le[1]+offset),p.le[0]]),...ss.toReversed().map(p=>[side*(p.te[1]+offset),p.te[0]])]);
 const all=polys.flat(),lo=[0,1].map(i=>Math.min(...all.map(p=>p[i]))),hi=[0,1].map(i=>Math.max(...all.map(p=>p[i]))),scale=Math.min(150/(hi[0]-lo[0]||1),65/(hi[1]-lo[1]||1));
 return `<svg viewBox="0 0 170 85" role="img" aria-label="Wing outline for ${esc(r.id)}"><title>${esc(r.id)} neutral wing planform</title>${polys.map(poly=>`<polygon points="${poly.map(p=>[85+(p[0]-(lo[0]+hi[0])/2)*scale,42.5+(p[1]-(lo[1]+hi[1])/2)*scale].join(',')).join(' ')}" fill="#b8ddd5" stroke="#007f78" stroke-width="1.3"/>`).join('')}</svg>`;
}
function renderResults(){
 const study=chosenStudy();$('loadConfig').disabled=!study;$('makeHeat').disabled=!study;$('stop').classList.toggle('hidden',!study||study.status.state!=='running');$('outputPath').textContent=study?defaultsRoot+'\\'+study.id:defaultsRoot;
 if(study){const q=study.status,pct=100*q.completed/Math.max(q.total,1);$('progressArea').innerHTML=`<p class="note">${(study.rows.some(r=>r.simulation_mode==='isolated_single_wing_v1')||study.simulation_mode==='isolated_single_wing_v1')?'Single-wing run: native plots show one wing. Estimated pair thrust = 2 × single-wing thrust.':'Existing paired-wing results have cancelling native roll moments. New studies simulate one wing.'}</p><div class="split status-line"><span>${esc(q.message||q.state)}</span><strong>${q.completed} / ${q.total}</strong></div><div class="progress"><div style="width:${pct}%"></div></div><p class="caption">${q.state==='running'?(q.eta_remaining_s===null?'ETA: calibrating first case':`Estimated remaining: ${duration(q.eta_remaining_s)} · ${esc(q.eta_basis||'')}`):esc(q.state)} · includes saving native plots and animation.</p>`;
 $('studyLinks').innerHTML=`<a class="btn" href="/files/${study.id}/manifest.json" target="_blank">Study settings</a><a class="btn" href="/files/${study.id}/run.log" target="_blank">Solver log</a>`+(study.rows.length?`<a class="btn" href="/files/${study.id}/summary.csv" download>Summary CSV</a><a class="btn" href="/files/${study.id}/comparisons/time_histories.csv" download>Raw histories CSV</a>`:'');
 }else{$('progressArea').innerHTML='<p class="caption">Select a study to compare shapes under fixed conditions.</p>';$('studyLinks').innerHTML='';}
 let rows=activeRows(),metric=$('rankMetric').value;if($('repeatOnly').checked)rows=rows.filter(r=>r.cycle_repeatable);
 rows.sort((a,b)=>Number(shapeEligible(b))-Number(shapeEligible(a))||(metric==='cycle_error_pct'?(a[metric]??Infinity)-(b[metric]??Infinity):(b[metric]??-Infinity)-(a[metric]??-Infinity)));
 $('noResults').classList.toggle('hidden',rows.length>0);
 $('ranking').innerHTML=rows.map((r,i)=>{const key=r._study+'/'+r.id,base='/files/'+key+'/',valid=shapeEligible(r),fmt=v=>Number.isFinite(v)?v.toPrecision(5):'—';return `<article class="wing-rank" data-ranked-case="${esc(r.id)}"><div class="wing-rank-number">${valid?i+1:'—'}</div>${rankWingPreview(r)}<div><div class="split"><strong>${r.global_case_no?'Case #'+r.global_case_no+' · ':''}${esc(r.design_name||r.id)} · ${esc(r.id)}</strong><span class="wing-rank-score">${fmt(r[shapeObjective])}<small style="font-size:10px"> 1/m</small></span></div><div class="wing-rank-values"><span>Single-wing thrust <strong>${fmt(r.single_wing_mean_thrust_N)} N</strong></span><span>${r.simulation_mode==='isolated_single_wing_v1'?`Est. pair thrust <strong>${fmt(r.estimated_two_wing_mean_thrust_N)} N</strong></span><span>`:''}Peak |roll| <strong>${fmt(r.single_wing_peak_abs_roll_moment_Nm)} N m</strong></span><span>${r.status==='failed'?'Failed':valid?(r.cycle_repeatable?'Repeatable':'Unsettled'):'Rerun / invalid ratio'}</span></div><div class="help">${esc(r._studyName)} · ${r.simulation_mode==='isolated_single_wing_v1'?'Isolated single wing':'Legacy paired-wing run — native roll cancels; rerun'} · wing span ${Number((r.single_wing_span_m??(r.span_m-(studyData.find(s=>s.id===r._study)?.config.settings.gap_m??.04))/2).toPrecision(5))} m · chords ${esc((r.requested_sections||r.sections)?(r.requested_sections||r.sections).map(s=>Number(s.chord_m.toPrecision(4))).join(' / '):'legacy geometry')} m</div><div class="wing-rank-links"><label style="display:inline"><input aria-label="Compare ${r.id}" data-ref="${key}" type="checkbox" ${selected.has(key)?'checked':''} ${r.status==='ok'?'':'disabled'}> Compare</label> · ${r.status==='ok'?`<a href="${base}water_wing_forces.png" target="_blank">Forces</a> · <a href="${base}water_wing_moments.png" target="_blank">Moments</a> · <a href="${base}animation.webp" target="_blank">Animation</a> · `:''}${profileLinks(r,base)}<a href="/api/case/${key}" target="_blank">Full values</a></div></div></article>`;}).join('');
 $('saveRanking').disabled=!study||study.status.state==='running';
 document.querySelectorAll('[data-ref]').forEach(box=>box.onchange=()=>{const key=box.dataset.ref,r=rows.find(r=>r._study+'/'+r.id===key);if(box.checked){if(selected.size>=4){box.checked=false;notify('Choose up to four cases.');return;}selected.set(key,r);}else selected.delete(key);drawOverlay();});
 $('topSummary').innerHTML='<p class="caption">Highest single-wing mean thrust / peak absolute hinge roll moment first. Each preview shows the neutral top-view shape; sizes are normalized for comparison.</p>';
 if(study?.rows.some(shapeEligible))$('studyLinks').insertAdjacentHTML('beforeend',`<a class="btn" href="/files/${study.id}/comparisons/top_performers.csv" download>Top shapes CSV</a>`+(study.status.state.startsWith('complete')?`<a class="btn" href="/files/${study.id}/comparisons/shape_comparison.png" target="_blank">Shape comparison PNG</a><a class="btn" href="/files/${study.id}/comparisons/shape_comparison.csv" download>Comparison CSV</a>`:''));
 renderBestDesign(rows,study);updateHeatAxes(study);updateHeatFilters();syncLandscape(study);
}

function renderBestDesign(rows,study) {
  const host=$('bestDesignBody'),metric=$('bestMetric').value;
  if(!study){host.innerHTML='<p class="caption">Select one study to inspect its best thrust / roll-moment shape.</p>';return;}
  const eligible=rows.filter(r=>shapeEligible(r) && Number.isFinite(r[metric]));
  if(!eligible.length){host.innerHTML='<p class="caption">No valid ratios meet this filter. Rerun legacy cases for single-wing loads, or allow unsettled cases for inspection.</p>';return;}
  const r=eligible.reduce((best,c)=>c[metric]>best[metric]?c:best);
  const s={...study.config.settings,...r,tail:r.tail_definition||study.config.tail||{enabled:false}},gap=Number(s.gap_m),half=(r.span_m-gap)/2;
  const c={...r,geometry:r.geometry||{stations:[0,.5,1].map((fraction,i)=>({
    y_m:half*fraction,x_m:Math.tan(r.sweep_deg*Math.PI/180)*half*fraction,
    chord_m:r.root_chord_m*[1,r.mid_ratio,r.tip_ratio][i]}))}};
  const value=v=>v===null||v===undefined?'—':typeof v==='number'?
    (v!==0&&Math.abs(v)<.001?v.toExponential(3):v.toLocaleString('en-US',{maximumSignificantDigits:5})):esc(v);
  const values=items=>'<dl class="best-values">'+items.map(([label,v])=>`<dt>${esc(label)}</dt><dd>${value(v)}</dd>`).join('')+'</dl>';
  const base=`/files/${study.id}/${r.id}/`;
  host.innerHTML=`<div class="split" style="margin:14px 0"><div><strong>${esc(r.id)}</strong> · ${esc(familyNames[r.family]||r.family)}<div class="caption">${eligible.length} eligible completed cases · ${$('repeatOnly').checked?'repeatable cycles only':'includes unsettled cases'} · ${esc(study.name)}</div></div><span class="pill ${r.cycle_repeatable?'':'warn'}">${r.cycle_repeatable?'Repeatable cycles':'Unsettled cycles'}</span></div>
    <div class="best-design-grid"><div><svg id="bestWingSvg" viewBox="0 0 440 235" role="img" aria-label="Highest-thrust wing top view"></svg><svg id="bestSideSvg" viewBox="0 0 440 165" role="img" aria-label="Highest-thrust wing side view and incidence"></svg><p class="caption">Neutral shape shown above; custom wings use top and front views. Single-wing preview scales to fit.</p></div>
    <div><h3>Design inputs</h3>${values([
      ['Single-wing root-to-tip span (m)',half],['Reference total span (m)',r.span_m],['Root chord (m)',r.root_chord_m],['Midspan chord (m)',r.root_chord_m*r.mid_ratio],
      ['Tip chord (m)',r.root_chord_m*r.tip_ratio],['Mid / root ratio',r.mid_ratio],['Tip / root ratio',r.tip_ratio],
      ['Sweep (°)',r.sweep_deg],['Incidence (°)',r.incidence_deg],['Hinge gap (m)',gap]])}
      <h3>Motion & water</h3>${values([['Flapping frequency (Hz)',r.frequency_hz],['Half-stroke amplitude (°)',r.amplitude_deg],['Flapping waveform',r.waveform_signature||'sine'],
      ['Forward speed (m/s)',r.speed_mps],['Density (kg/m³)',s.rho],['Kinematic viscosity (m²/s)',s.nu]])}</div>
    <div><h3>Force outputs · complete model</h3>${values([
      ['Mean thrust (N)',r.mean_thrust_N],['Estimated two-wing mean thrust (N)',r.estimated_two_wing_mean_thrust_N],['Peak forward thrust (N)',r.peak_thrust_N],['RMS thrust (N)',r.rms_thrust_N],
      ['Mean lift (N)',r.mean_lift_N],['Peak lift (N)',r.peak_lift_N],['RMS lift (N)',r.rms_lift_N],
      ['Wing area (m²)',r.area_m2],['Aspect ratio',r.aspect_ratio],['Cycle difference (%)',r.cycle_error_pct]])}
      <h3>Single-wing objective</h3>${values([['Mean thrust / peak |roll| (1/m)',r[shapeObjective]],['Single-wing mean thrust (N)',r.single_wing_mean_thrust_N],['Peak |hinge roll moment| (N m)',r.single_wing_peak_abs_roll_moment_Nm],['RMS hinge roll moment (N m)',r.single_wing_rms_roll_moment_Nm],['Size-normalized score L·T/M',r.dimensionless_thrust_roll_score],['Reference half-span L (m)',r.reference_half_span_m],['Root-moment cycle difference (%)',r.root_moment_cycle_error_pct]])}
      <h3>Numerical inputs</h3>${values([['Delta time (s)',s.dt_s],['Cycles',s.cycles],['Span panels / half-wing',s.span_panels],
      ['Chordwise panels',s.chord_panels],['Cycle tolerance (%)',s.cycle_tolerance_pct],
      ['Wake model',s.wake_model||'free'],['Retained wake cycles',Number(s.wake_cycles||0)||'Full history'],
      ['Static tail enabled',s.tail?.enabled?'Yes':'No'],['Overall tail pitch (°)',s.tail?.enabled?s.tail.pitch_deg:'—'],['Averaging window start (s)',r.window_start_s],['Averaging window end (s)',r.window_end_s]])}</div></div>
    <div class="actions" style="margin-top:14px"><a href="${base}water_wing_forces.png" target="_blank">Ptera force plot</a><a href="${base}water_wing_moments.png" target="_blank">Ptera moment plot</a>${study.lean_outputs?`<a href="${base}animation.webp" target="_blank">Animation</a>`:''}${profileLinks(r,base)}<a href="/api/case/${study.id}/${r.id}" target="_blank">Full case data</a></div>
    <p class="caption">Winner maximizes single-wing final-cycle mean thrust divided by sampled peak absolute roll moment about that wing's hinge. No shared-motor screening. Physical scaling is conditional on similarity; L·T/M removes the ratio's length units. Converge mesh, wake and delta time before selecting a build.</p>`;
  if(s.tail?.enabled){
    host.insertAdjacentHTML('beforeend',`<h3>Fixed static tail</h3><p class="caption">Tail geometry and overall pitch are identical for every case. Reported total forces include main wings plus tail. Positive total pitch rotates about the tail root leading edge; servo actuation and servo torque are not modeled.</p>${values([['Overall pitch (°)',s.tail.pitch_deg],['Tail span (m)',2*s.tail.sections.at(-1).y_m],['Root aft position x (m)',s.tail.x_m],['Root height z (m)',s.tail.z_m],['Tail span panels / half',s.tail.span_panels],['Tail chordwise panels',s.tail.chord_panels],['Main-wing mean thrust (N)',r.main_wing_mean_thrust_N],['Tail mean thrust (N)',r.tail_mean_thrust_N],['Main-wing mean lift (N)',r.main_wing_mean_lift_N],['Tail mean lift (N)',r.tail_mean_lift_N]])}<div style="overflow:auto"><table><thead><tr><th>Tail section</th><th>Position (m)</th><th>Aft offset (m)</th><th>Width (m)</th><th>Local pitch (°)</th><th>Roll (°)</th></tr></thead><tbody>${s.tail.sections.map((section,i)=>`<tr><td>${i+1}</td>${sectionKeys.map(k=>`<td>${section[k]}</td>`).join('')}</tr>`).join('')}</tbody></table></div><svg id="bestTailLayout" viewBox="0 0 560 360" style="width:100%;max-width:650px" aria-label="Winning wing with its fixed tail"></svg>`);
    if(study.tail)drawTailLayout(c,s,study.tail,'bestTailLayout');
  }
  drawWing(c,{gap_m:gap},'bestWingSvg');
  if(c.sections){drawSectionView(c,{gap_m:gap},'bestSideSvg','front');
    host.insertAdjacentHTML('beforeend',`<h3>${esc(r.design_name)} · section inputs</h3><div style="overflow:auto"><table><thead><tr><th>Section</th><th>Position (m)</th><th>Aft offset (m)</th><th>Width (m)</th><th>Pitch (°)</th><th>Roll (°)</th></tr></thead><tbody>${c.sections.map((s,i)=>`<tr><td>${i+1}</td>${['y_m','x_m','chord_m','pitch_deg','roll_deg'].map(k=>`<td>${s[k]}</td>`).join('')}</tr>`).join('')}</tbody></table></div>`);
  }else drawSide(c,'bestSideSvg');
}
$('bestMetric').onchange=renderResults;
$('refresh').onclick=refresh;$('studySelect').onchange=e=>{currentStudy=e.target.value;$('heatResult').innerHTML='';renderResults();};$('rankMetric').onchange=renderResults;$('repeatOnly').onchange=renderResults;
$('loadConfig').onclick=()=>{let s=chosenStudy();if(s){fill(s.config);tab('setup');notify('Copied study settings. Running creates a separate study.');}};
$('stop').onclick=async()=>{try{await api('stop',{id:currentStudy});refresh();}catch(e){notify(e.message);}};
const colors=['#0072B2','#D55E00','#009E73','#8C5A9E'];
async function drawOverlay(){let chosen=[...selected.values()];$('overlayEmpty').classList.toggle('hidden',chosen.length>0);$('overlaySvg').classList.toggle('hidden',!chosen.length);$('exportOverlay').classList.toggle('hidden',!chosen.length);if(!chosen.length){$('overlayLegend').innerHTML='';return;}try{if(new Set(chosen.map(r=>r.simulation_mode||'legacy_paired')).size>1)throw new Error('Select cases from the same simulation mode. Single-wing and legacy paired loads cannot be overlaid.');lastOverlay=await Promise.all(chosen.map(async(r,i)=>{let saved=await api(`case/${r._study}/${r.id}`);let data=saved.history.filter(a=>a[0]>=r.window_start_s-1e-9&&a[0]<=r.window_end_s+1e-9);return {r,color:colors[i],data};}));let out='';for(let [panel,col,label] of [[0,1,'Thrust (N)'],[1,2,'Lift (N)']]){let vals=lastOverlay.flatMap(s=>s.data.map(p=>p[col])),lo=Math.min(0,...vals),hi=Math.max(0,...vals),pad=(hi-lo||.01)*.12;lo-=pad;hi+=pad;let y=v=>25+panel*135+100*(hi-v)/(hi-lo),x=p=>55+540*p;out+=`<line x1="55" y1="${y(0)}" x2="595" y2="${y(0)}" stroke="#ccd8dd" stroke-dasharray="3 3"/><line x1="55" y1="${25+panel*135}" x2="55" y2="${125+panel*135}" stroke="#9aadb5"/><text x="12" y="${75+panel*135}" transform="rotate(-90 12 ${75+panel*135})" text-anchor="middle" font-size="12" fill="#496373">${label}</text>`;for(let s of lastOverlay){let d=s.data.map(p=>[x((p[0]-s.r.window_start_s)*s.r.frequency_hz),y(p[col])]);out+=`<polyline fill="none" stroke="${s.color}" stroke-width="1.5" points="${d.map(p=>p.join(',')).join(' ')}"/>`;}out+=`<text x="50" y="${y(hi-pad)}" text-anchor="end" font-size="10" fill="#657c86">${(hi-pad).toPrecision(3)}</text><text x="50" y="${y(lo+pad)}" text-anchor="end" font-size="10" fill="#657c86">${(lo+pad).toPrecision(3)}</text>`;}out+='<text x="55" y="281" font-size="10" fill="#657c86">0</text><text x="595" y="281" font-size="10" fill="#657c86">1</text><text x="325" y="281" text-anchor="middle" font-size="11" fill="#496373">Cycle phase</text>';$('overlaySvg').innerHTML=out;$('overlayLegend').innerHTML=lastOverlay.map(s=>`<div><span class="swatch" style="background:${s.color}"></span>${esc(s.r._studyName)} / ${s.r.id} · Δt ${s.r.dt_s} s · ${s.r.span_panels} × ${s.r.chord_panels} per wing</div>`).join('');}catch(e){notify(e.message);}}
$('exportOverlay').onclick=async()=>{try{let r=await api('overlay',{cases:refs()});notify('Comparison saved with case references and raw data.');$('overlayExports').innerHTML=`<a href="/files/${r.file}" download>PNG</a><a href="/files/${r.file.replace(/\.png$/,'.csv')}" download>CSV</a>`;}catch(e){notify(e.message);}};


let designData=null;
function checkedAxes(){return [...document.querySelectorAll('[data-axis]:checked')].map(e=>e.dataset.axis);}
function clearDesign(){designData=null;$('heatResult').innerHTML='';$('heatError').innerHTML='';}
function updateHeatFilters() {
  const study=chosenStudy(),rows=study?study.rows.filter(r=>r.status==='ok').map(r=>({...r,wake_model:r.wake_model||'free',wake_cycles:r.wake_cycles||0,waveform_signature:r.waveform_signature||'sine'})):[];
  const axes=checkedAxes(),mode=$('heatMode').value,old={};
  $('designCard').classList.toggle('wide',axes.length===3);
  document.querySelectorAll('[data-slice]').forEach(e=>old[e.dataset.slice]=e.value);
  let html='';
  const filterKeys=[...(mode==='slice'?resultGeometryKeys():[]),...fixedKeys];
  for (const key of filterKeys) {
    if (axes.includes(key)) continue;
    const vs=[...new Set(rows.map(r=>r[key]).filter(v=>v!==undefined))].sort((a,b)=>a-b);
    if (vs.length<2) continue;
    const value=vs.some(v=>String(v)===old[key])?old[key]:String(vs[0]);
    const [label,unit]=fields[key]||[key,''];
    html+=`<label>${esc(label)}${unit?' ('+esc(unit)+')':''}<select data-slice="${key}">${vs.map(v=>`<option value="${v}" ${String(v)===value?'selected':''}>${v}</option>`).join('')}</select></label>`;
  }
  $('sliceFilters').innerHTML=html;
  document.querySelectorAll('[data-slice]').forEach(e=>e.onchange=clearDesign);
  $('axisCount').textContent=`${axes.length} selected · choose 2 or 3`;
}
$('heatMode').onchange=()=>{clearDesign();updateHeatFilters();};
$('heatMetric').onchange=clearDesign;
$('repeatHeat').onchange=clearDesign;
$('makeHeat').onclick=async()=>{
  const axes=checkedAxes(),filters={};
  document.querySelectorAll('[data-slice]').forEach(e=>filters[e.dataset.slice]=e.value);
  $('heatError').innerHTML='';
  if(axes.length<2||axes.length>3){$('heatError').innerHTML='<div class="error">Select two or three geometry axes.</div>';return;}
  $('makeHeat').disabled=true;
  try {
    const d=await api('heatmap',{study:currentStudy,axes,metric:$('heatMetric').value,
      mode:$('heatMode').value,filters,repeat_only:$('repeatHeat').checked});
    designData=d; renderDesign(d);
  } catch(e){$('heatError').innerHTML=`<div class="error">${esc(e.message)}</div>`;}
  finally{$('makeHeat').disabled=!chosenStudy();}
};
function renderDesign(d) {
  const reduced=d.reduced_over.map(k=>fields[k][0]).join(', ');
  const summary=`${d.source_case_count.toLocaleString()} cases → ${d.points.length.toLocaleString()} plotted ${d.axes.length===2?'cells':'points'}. `+
    (d.mode==='max'?`Color is the maximum ${d.label[0].toLowerCase()+d.label.slice(1)}${reduced?' over '+reduced:''}.`:'Exact slice; every cell identifies a single case.');
  const base='/files/'+d.file;
  let html=`<div class="note" style="margin:14px 0">${esc(summary)}</div>`;
  if(d.axes.length===3){
    html+=`<svg id="space3d" viewBox="0 0 700 430" role="img" aria-label="Rotatable three-axis geometry study colored by thrust"></svg>
      <div class="actions"><button class="btn" id="reset3d">Reset view</button><span class="caption">Drag to rotate · wheel to zoom · click a point for the winning geometry</span></div><div id="pointInfo" class="note" style="margin:12px 0">Choose a point to inspect its winning case.</div>`;
  }else html+=`<img class="result-image" alt="Two-axis geometry study heatmap" src="${base}">`;
  html+=`<div class="actions" style="margin:12px 0"><a href="${base}" download>600-dpi PNG</a>
    <a href="${base.replace(/\.png$/,'.csv')}" download>Winning geometries CSV</a>
</div>`;
  html+=`<details><summary>Inspect winning cases (${d.points.length})</summary><div class="table-wrap"><table><thead><tr>${d.axes.map(k=>`<th>${esc(fields[k][0])}</th>`).join('')}<th>${esc(d.label)}</th><th>WINNER</th><th>CASES COMPARED</th></tr></thead><tbody>`;
  html+=d.points.slice(0,300).map(p=>`<tr>${p.coords.map(v=>`<td>${v}</td>`).join('')}<td>${p.value.toPrecision(5)}</td><td><a href="/api/case/${p.source_study||currentStudy}/${p.source_case||p.case_id}" target="_blank">${p.case_id}</a></td><td>${p.count}</td></tr>`).join('');
  html+='</tbody></table></div><p class="caption">First 300 winners shown here; the CSV contains every point and all six winning geometry inputs.</p></details>';
  $('heatResult').innerHTML=html;
  if(d.axes.length===3) setup3d(d);
}
function setup3d(data) {
  const svg=$('space3d'),points=data.points;
  let yaw=-.7,pitch=.48,zoom=1,drag=null,moved=false,screen=[];
  const ranges=data.axes.map((key,i)=>points.reduce((r,p)=>[Math.min(r[0],p.coords[i]),Math.max(r[1],p.coords[i])],[Infinity,-Infinity]));
  const [vmin,vmax]=points.reduce((r,p)=>[Math.min(r[0],p.value),Math.max(r[1],p.value)],[Infinity,-Infinity]);
  const palette=[[0,34,78],[65,78,108],[125,124,120],[188,174,108],[254,232,56]];
  function color(value){
    const t=(vmax===vmin?.5:(value-vmin)/(vmax-vmin))*4,i=Math.min(3,Math.floor(t)),f=t-i;
    return `rgb(${palette[i].map((v,k)=>Math.round(v+(palette[i+1][k]-v)*f)).join(',')})`;
  }
  function norm(c){return c.map((v,i)=>ranges[i][0]===ranges[i][1]?0:(v-ranges[i][0])/(ranges[i][1]-ranges[i][0])-.5);}
  function project(v){
    const a=Math.cos(yaw)*v[0]-Math.sin(yaw)*v[1],b=Math.sin(yaw)*v[0]+Math.cos(yaw)*v[1];
    return [300+220*zoom*a,205+190*zoom*(Math.sin(pitch)*b-Math.cos(pitch)*v[2]),Math.cos(pitch)*b+Math.sin(pitch)*v[2]];
  }
  function draw(){
    let h='<defs><linearGradient id="heatScale" x1="0" x2="0" y1="1" y2="0">'+palette.map((c,i)=>`<stop offset="${i*25}%" stop-color="rgb(${c})"/>`).join('')+'</linearGradient></defs>';
    const origin=[-.58,-.58,-.58],o=project(origin);
    data.axes.forEach((key,i)=>{
      const end=[...origin];end[i]=.68;const p=project(end);
      h+=`<line x1="${o[0]}" y1="${o[1]}" x2="${p[0]}" y2="${p[1]}" stroke="#74929f" stroke-width="1.2"/>`;
      const label=[...origin];label[i]=.87;const q=project(label);
      h+=`<text x="${q[0]}" y="${q[1]}" font-size="12" text-anchor="middle" fill="#264b5d">${esc(fields[key][0])}${fields[key][1]?' ('+esc(fields[key][1])+')':''}</text>`;
      for(let t=0;t<3;t++){
        const at=[...origin];at[i]=-.5+t*.5;const v=project(at),value=ranges[i][0]+t*(ranges[i][1]-ranges[i][0])/2;
        h+=`<text x="${v[0]+4}" y="${v[1]+13}" font-size="11" fill="#607b88">${Number(value.toPrecision(4))}</text>`;
      }
    });
    screen=points.map((p,i)=>({p,i,s:project(norm(p.coords))})).sort((a,b)=>a.s[2]-b.s[2]);
    for(const {p,s} of screen){
      h+=`<circle cx="${s[0]}" cy="${s[1]}" r="5.5" fill="${color(p.value)}" stroke="#28414f" stroke-width=".6"><title>${esc(p.case_id)}: ${p.value.toPrecision(5)} N</title></circle>`;
      if(!p.repeatable)h+=`<path d="M${s[0]-3} ${s[1]-3}l6 6m-6 0l6-6" stroke="white" stroke-width="1"/>`;
    }
    h+=`<rect x="626" y="92" width="16" height="200" fill="url(#heatScale)" stroke="#78909a"/><text x="651" y="99" font-size="11" fill="#425f6e">${vmax.toPrecision(4)}</text><text x="651" y="294" font-size="11" fill="#425f6e">${vmin.toPrecision(4)}</text><text x="627" y="70" font-size="11" fill="#425f6e">Force (N)</text>`;
    svg.innerHTML=h;
  }
  svg.onpointerdown=e=>{drag=[e.clientX,e.clientY];moved=false;svg.setPointerCapture(e.pointerId);};
  svg.onpointermove=e=>{
    if(!drag)return;const dx=e.clientX-drag[0],dy=e.clientY-drag[1];
    if(Math.abs(dx)+Math.abs(dy)>2)moved=true;
    yaw+=dx*.008;pitch=Math.max(-1.3,Math.min(1.3,pitch+dy*.008));drag=[e.clientX,e.clientY];draw();
  };
  svg.onpointerup=e=>{
    drag=null;if(moved)return;
    const b=svg.getBoundingClientRect(),x=(e.clientX-b.left)*700/b.width,y=(e.clientY-b.top)*430/b.height;
    const pick=screen.map(a=>({...a,d:Math.hypot(a.s[0]-x,a.s[1]-y)})).sort((a,b)=>a.d-b.d)[0];
    if(!pick||pick.d>22)return;
    const p=pick.p;
    $('pointInfo').innerHTML=`<strong>${p.case_id} · ${p.value.toPrecision(5)} N</strong> · best of ${p.count} cases<br>`+
      geometryKeys.map(k=>`${esc(fields[k][0])}: ${p.inputs[k]}`).join(' · ')+
      `<br><a href="/api/case/${p.source_study||currentStudy}/${p.source_case||p.case_id}" target="_blank">Full inputs</a> · <a href="/files/${currentStudy}/${p.case_id}/water_wing_forces.png" target="_blank">Ptera force plot</a>`;
  };
  svg.onpointercancel=()=>drag=null;
  svg.addEventListener('wheel',e=>{e.preventDefault();zoom=Math.max(.6,Math.min(1.5,zoom*Math.exp(-e.deltaY*.001)));draw();},{passive:false});
  $('reset3d').onclick=()=>{yaw=-.7;pitch=.48;zoom=1;draw();};draw();
}

async function init() {
  try {
    const d=await api('defaults');defaults=d.config;fields=d.fields;familyNames=d.families;defaultsRoot=d.output_root;
    $('methodPath').textContent=defaultsRoot;
    updateHeatAxes(null);
    fill(defaults);await refresh();
    setInterval(()=>{if(!$('results').classList.contains('hidden'))refresh();},3500);
  } catch(e){notify('Could not connect to local server: '+e.message);}
}
let customDesigns=[], editingDesign=-1, draft;
const sectionKeys=['y_m','x_m','chord_m','pitch_deg','roll_deg'];
function defaultWing(){return {name:'Gull wing',sections:[
  {y_m:0,x_m:0,chord_m:.15,pitch_deg:5,roll_deg:20},
  {y_m:.15,x_m:.02,chord_m:.13,pitch_deg:3,roll_deg:-15},
  {y_m:.3,x_m:.05,chord_m:.07,pitch_deg:0,roll_deg:0}]};}
function installCustomUI(){
  const fieldsHost=$('geometryFields'), card=fieldsHost.parentElement;
  const divider=card.querySelector('hr');
  const sweep=document.createElement('div');sweep.id='sweepEditor';
  while(divider.nextSibling)sweep.appendChild(divider.nextSibling);
  card.appendChild(sweep);
  divider.insertAdjacentHTML('beforebegin',`<label style="margin-top:15px">Design mode<select id="studyMode"><option value="shape_sweep">Search chord-length combinations</option><option value="custom">Build individual custom wings</option></select></label>`);
  card.insertAdjacentHTML('beforeend',`<div id="customEditor" class="hidden">
    <div class="split"><h3>Design one half-wing</h3><button class="btn" id="newWing">New wing</button></div>
    <p class="help">Sections run from root to tip. Edit widths and angles below, or drag the numbered chord endpoints in the editor. One wing is simulated; left/right cutting templates are exported.</p>
    <div class="fields" style="margin-top:12px"><label>Wing name<input id="wingName" maxlength="80"></label><label>Number of chord sections<input id="sectionCount" type="number" min="2" step="1"><button class="btn" id="applySections" style="margin-top:7px">Apply section count</button></label></div>
    <div style="overflow:auto;margin-top:15px"><table id="sectionTable"><thead><tr><th>Section</th><th>Position<br>m</th><th>Aft offset<br>m</th><th>Chord width<br>m</th><th>Pitch<br>°</th><th>Roll<br>°</th><th>Leading-edge<br>sweep °</th></tr></thead><tbody id="sectionRows"></tbody></table></div>
    <p class="help">Leading-edge sweep is the top-view angle from the previous section to this section, measured from the span direction. Positive sweeps aft; negative sweeps forward. Changing an angle moves this section and all sections farther out, preserving their sweep angles. Aft offsets and angles stay linked. The root has no incoming interval.</p>
    <p class="help">Position is horizontal distance from the root leading edge. Pitch is absolute section twist. Roll is absolute dihedral: positive rises toward the next section, negative falls. Tip roll sets its section frame only. Angles do not accumulate. Root position and aft offset are zero.</p>
    <svg id="chordEditor" viewBox="0 0 560 245" style="width:100%;background:#f3f8f8;border:1px solid #dce5e9;border-radius:8px;touch-action:none" aria-label="Drag chord endpoints to adjust widths"></svg>
    <svg id="custom3d" viewBox="0 0 560 260" style="width:100%;background:#f3f8f8;border:1px solid #dce5e9;border-radius:8px;touch-action:none;cursor:grab;margin-top:8px" aria-label="Rotatable three dimensional custom wing preview"></svg>
    <p class="caption">Drag the 3D view to rotate. Draft previews update immediately; add or update the wing to include it in the study.</p>
    <p id="draftError" class="error hidden"></p>
    <div class="actions" style="margin:16px 0"><button class="btn primary" id="saveWing">Add wing to study</button><button class="btn" id="copyWing">Add as a copy</button></div>
    <h3>Wings in this study</h3><div id="designQueue"></div>
    <p class="help">One simulation per saved wing. Sections 2 and 3 are shared constants. No Cartesian sweep runs in this mode. Separate left/right SVGs unfold planar section strips, including untwisted bent wings. Nonplanar twist or overlapping layouts export labeled projections instead.</p>
  </div>`);
  const style=document.createElement('style');style.textContent='#sectionTable input{padding:7px 4px;min-width:54px}#sectionTable th,#sectionTable td{padding:7px 4px}#sectionTable td:first-child{font-weight:600}';document.head.appendChild(style);
  $('studyMode').onchange=()=>modeChanged(true);
  $('newWing').onclick=()=>{editingDesign=-1;draft=defaultWing();draft.name='Wing '+(customDesigns.length+1);renderEditor();};
  $('wingName').oninput=e=>draft.name=e.target.value;
  $('applySections').onclick=()=>{
    readDraft();const n=Number($('sectionCount').value);if(!Number.isInteger(n)||n<2||n>1000){notify('Use at least two sections; resolution must include every interval.');return;}
    const old=draft.sections,tip=old.at(-1).y_m;
    draft.sections=Array.from({length:n},(_,i)=>{const y=tip*i/(n-1),j=Math.max(0,old.findIndex(s=>s.y_m>=y)-1),a=old[j],b=old[Math.min(j+1,old.length-1)],t=(y-a.y_m)/(b.y_m-a.y_m||1);return Object.fromEntries(sectionKeys.map(k=>[k,k==='y_m'?y:a[k]+t*(b[k]-a[k]) ]));});renderEditor();
  };
  $('saveWing').onclick=()=>saveDraft(false);$('copyWing').onclick=()=>saveDraft(true);
}
function modeChanged(update){
  const custom=$('studyMode').value==='custom';$('customEditor').classList.toggle('hidden',!custom);$('sweepEditor').classList.toggle('hidden',custom);if(update)preview();
}
function installShapeUI(){
  $('sweepEditor').innerHTML=`<div id="migrationNotice" class="note hidden"></div><div id="geometryFields" class="hidden"></div><p class="help">Search every admissible combination of chord lengths at equally spaced root-to-tip nodes. The reference grid span and motion stay fixed. Trailing zeros shorten the active wing. Min/max endpoints are included.</p><div class="fields"><label>Reference total span (m)<input id="shapeSpan" type="number" step="any"></label><label>Number of chord nodes<input id="shapeNodes" type="number" min="2" max="64" step="1"><button type="button" class="btn" id="applyShapeNodes" style="margin-top:8px">Apply node count</button></label><label>Fixed leading-edge sweep (°)<input id="shapeSweep" type="number" step="any" value="0"></label><label>Fixed wing incidence (°)<input id="shapePitch" type="number" step="any" value="0"></label></div><label style="margin:16px 0"><input type="checkbox" id="decreasingChords"> Require non-increasing chords from root to tip</label><p class="help">When checked, every next chord must be shorter or equal. Equal chords allow rectangular regions. Rejected branches are pruned before building cases.</p><div style="overflow:auto"><table><thead><tr><th>Chord node</th><th>Span fraction</th><th>Minimum (m)</th><th>Maximum (m)</th><th>Linspace samples</th></tr></thead><tbody id="shapeRanges"></tbody></table></div><p class="help">Zero omits a section: all chords after it must also be zero. The wing ends at the last positive section; at least two positive sections are required. One sample holds a chord fixed: use equal min/max. Use coarse grids to find promising regions, then narrow ranges and refine. There is no automatic claim of a continuous optimum.</p>`;
  $('previewDetails').insertAdjacentHTML('afterend','<p class="note" id="runtimeEstimate">Runtime ETA calibrates from local cases.</p>');
  $('applyShapeNodes').onclick=()=>{const n=Number($('shapeNodes').value);if(!Number.isInteger(n)||n<2||n>64){notify('Use 2–64 chord nodes.');return;}const old=readShape().ranges;renderShapeRanges(Array.from({length:n},(_,i)=>old[i]||{min_m:.06,max_m:.14,count:3}));preview();};
}
function renderShapeRanges(ranges){
  $('shapeRanges').innerHTML=ranges.map((r,i)=>`<tr><td><strong>${i+1}${i===0?' · root':i===ranges.length-1?' · tip':''}</strong></td><td>${(i/(ranges.length-1)).toFixed(3)}</td>${['min_m','max_m','count'].map(k=>`<td><input type="number" step="${k==='count'?'1':'any'}" data-shape-row="${i}" data-shape-key="${k}" value="${esc(r[k])}" style="min-width:85px"></td>`).join('')}</tr>`).join('');
}
function fillShape(raw){const s={...defaults.shape_sweep,...raw};$('shapeSpan').value=s.span_m;$('shapeNodes').value=s.chord_count;$('shapeSweep').value=s.sweep_deg||0;$('shapePitch').value=s.incidence_deg||0;$('decreasingChords').checked=!!s.decreasing;renderShapeRanges(s.ranges);}
function readShape(){const ranges=[];document.querySelectorAll('[data-shape-row]').forEach(e=>{const i=Number(e.dataset.shapeRow);ranges[i]??={};ranges[i][e.dataset.shapeKey]=Number(e.value);});return {span_m:Number($('shapeSpan').value),chord_count:Number($('shapeNodes').value),decreasing:$('decreasingChords').checked,sweep_deg:Number($('shapeSweep').value),incidence_deg:Number($('shapePitch').value),ranges};}
let heatAxisKey='';
function resultGeometryKeys(){const study=chosenStudy(),nodes=[...new Set((study?.rows||[]).flatMap(r=>Object.keys(r).filter(k=>/^chord_\d+_m$/.test(k))))].sort((a,b)=>Number(a.split('_')[1])-Number(b.split('_')[1]));if(nodes.length)return nodes;if(study?.config.mode==='shape_sweep')return Array.from({length:study.config.shape_sweep.chord_count},(_,i)=>`chord_${i+1}_m`);return geometryKeys;}
function updateHeatAxes(){const keys=resultGeometryKeys(),key=keys.join(',');if(key===heatAxisKey)return;heatAxisKey=key;$('axisChoices').innerHTML=keys.map((k,i)=>`<label class="axis-choice"><input type="checkbox" data-axis="${k}" ${i<2?'checked':''}>${esc(fields[k]?.[0]||k)}</label>`).join('');document.querySelectorAll('[data-axis]').forEach(box=>box.onchange=()=>{if(checkedAxes().length>3){box.checked=false;notify('Choose up to three axes.');return;}clearDesign();updateHeatFilters();});clearDesign();}
function renderEditor(){
  $('wingName').value=draft.name;$('sectionCount').value=draft.sections.length;
  $('sectionRows').innerHTML=draft.sections.map((s,i)=>`<tr><td>${i===0?'Root':i===draft.sections.length-1?'Tip':i+1}</td>${sectionKeys.map(k=>`<td><input type="number" step="any" data-section="${i}" data-key="${k}" aria-label="Section ${i+1} ${k}" value="${s[k]}" ${i===0&&['y_m','x_m'].includes(k)?'disabled':''}></td>`).join('')}<td>${i?`<input type="number" step="any" data-edge-angle="${i}" aria-label="Section ${i+1} leading-edge sweep" value="${edgeAngle(i)}">`:'—'}</td></tr>`).join('');
  document.querySelectorAll('[data-section]').forEach(input=>input.oninput=e=>{draft.sections[Number(input.dataset.section)][input.dataset.key]=Number(input.value);syncEdgeAngles();drawDraft();});
  document.querySelectorAll('[data-edge-angle]').forEach(input=>input.oninput=()=>{
    const i=Number(input.dataset.edgeAngle),angle=Number(input.value),a=draft.sections[i-1],b=draft.sections[i];
    input.setCustomValidity('');
    if(input.value===''||!Number.isFinite(angle)||Math.abs(angle)>=90||b.y_m<=a.y_m){input.setCustomValidity('Use an angle strictly between -90° and 90° and increasing section positions.');return;}
    const shift=a.x_m+(b.y_m-a.y_m)*Math.tan(angle*Math.PI/180)-b.x_m;
    for(let j=i;j<draft.sections.length;j++){
      draft.sections[j].x_m+=shift;
      document.querySelector(`[data-section="${j}"][data-key="x_m"]`).value=draft.sections[j].x_m;
    }
    drawDraft();
  });
  $('saveWing').textContent=editingDesign<0?'Add wing to study':'Update wing in study';
  renderQueue();drawDraft();
}
function renderQueue(){
  $('designQueue').innerHTML=customDesigns.length?customDesigns.map((d,i)=>`<div class="split" style="padding:10px 0;border-bottom:1px solid #dce5e9"><span><strong>${esc(d.name)}</strong> · ${d.sections.length} sections</span><div class="actions"><button class="btn" data-edit-wing="${i}">Edit</button><button class="btn danger" data-remove-wing="${i}">Remove</button></div></div>`).join(''):'<p class="caption">No wings added yet.</p>';
  document.querySelectorAll('[data-edit-wing]').forEach(b=>b.onclick=()=>{editingDesign=Number(b.dataset.editWing);draft=structuredClone(customDesigns[editingDesign]);renderEditor();});
  document.querySelectorAll('[data-remove-wing]').forEach(b=>b.onclick=()=>{const i=Number(b.dataset.removeWing);customDesigns.splice(i,1);if(editingDesign===i)editingDesign=-1;else if(editingDesign>i)editingDesign--;renderEditor();preview();});
}
async function saveDraft(copy){
  try{readDraft();const c=config();c.mode='custom';c.designs=[structuredClone(draft)];await api('preview',c);
    if(copy||editingDesign<0){customDesigns.push(structuredClone(draft));editingDesign=customDesigns.length-1;}
    else customDesigns[editingDesign]=structuredClone(draft);
    renderEditor();preview();notify('Wing saved to this study.');
  }catch(e){$('draftError').textContent=e.message;$('draftError').classList.remove('hidden');}
}
function readDraft(){
  for(const input of document.querySelectorAll('[data-edge-angle]'))if(!input.checkValidity())throw Error('Leading-edge sweep must be strictly between -90° and 90° with increasing section positions.');
  draft.name=$('wingName').value;
  document.querySelectorAll('[data-section]').forEach(input=>draft.sections[Number(input.dataset.section)][input.dataset.key]=Number(input.value));
}
function edgeAngle(i){const a=draft.sections[i-1],b=draft.sections[i];return Number((Math.atan2(b.x_m-a.x_m,b.y_m-a.y_m)*180/Math.PI).toPrecision(8));}
function syncEdgeAngles(){document.querySelectorAll('[data-edge-angle]').forEach(input=>{input.value=edgeAngle(Number(input.dataset.edgeAngle));input.setCustomValidity('');});}
function draftCase(){
  const stop=draft.sections.findIndex(s=>s.chord_m===0),active=draft.sections.slice(0,stop<0?draft.sections.length:stop);
  let z=0;const pts=active.map((s,i)=>{
    if(i)z+=(s.y_m-draft.sections[i-1].y_m)*Math.tan(draft.sections[i-1].roll_deg*Math.PI/180);
    const r=s.roll_deg*Math.PI/180,p=s.pitch_deg*Math.PI/180;
    return {...s,z_m:z,le:[s.x_m,s.y_m,z],te:[s.x_m+s.chord_m*Math.cos(p),s.y_m+s.chord_m*Math.sin(r)*Math.sin(p),z-s.chord_m*Math.cos(r)*Math.sin(p)]};
  });return {sections:active,geometry:{stations:pts}};
}
let editorScale=1, editorMin=0, draggedChord=null, viewYaw=-.55, viewElevation=.5;
function drawDraft(){
  $('draftError').classList.add('hidden');
  const ss=draft.sections;if(ss.some(s=>sectionKeys.some(k=>!Number.isFinite(s[k])))||ss.at(-1).y_m<=0)return;
  const min=Math.min(...ss.map(s=>s.x_m)),max=Math.max(...ss.map(s=>s.x_m+s.chord_m));
  editorMin=min;editorScale=Math.min(460/ss.at(-1).y_m,165/(max-min||.1));
  const stop=ss.findIndex(s=>s.chord_m===0),outline=ss.slice(0,stop<0?ss.length:stop);
  const X=y=>50+y*editorScale,Y=x=>40+(x-min)*editorScale;
  $('chordEditor').innerHTML=`<text x="16" y="20" font-size="11" fill="#647787">UNPITCHED HALF-WING · DRAG THE NUMBERED ENDPOINTS</text><polygon points="${[...outline.map(s=>[X(s.y_m),Y(s.x_m)]),...outline.toReversed().map(s=>[X(s.y_m),Y(s.x_m+s.chord_m)])].map(p=>p.join(',')).join(' ')}" fill="#c6e6df" stroke="#007f78"/>`+ss.map((s,i)=>`<line x1="${X(s.y_m)}" y1="${Y(s.x_m)}" x2="${X(s.y_m)}" y2="${Y(s.x_m+s.chord_m)}" stroke="#5bafa2"/><circle data-chord-handle="${i}" cx="${X(s.y_m)}" cy="${Y(s.x_m+s.chord_m)}" r="9" fill="#007f78" style="cursor:ns-resize"/><text pointer-events="none" x="${X(s.y_m)}" y="${Y(s.x_m+s.chord_m)+3}" text-anchor="middle" fill="white" font-size="9">${i+1}</text>`).join('');
  document.querySelectorAll('[data-chord-handle]').forEach(h=>h.onpointerdown=e=>{e.preventDefault();draggedChord=Number(h.dataset.chordHandle);$('chordEditor').setPointerCapture(e.pointerId);});
  drawCustom3d();
}
function drawSectionView(c,s,target,view){
  const pts=c.geometry.stations,svg=$(target),front=view==='front',height=front?165:235;
  const project=(p,side)=>[side*p[1],front?-p[2]:p[0]];
  const polys=[1].map(side=>[...pts.map(p=>project(p.le,side)),...pts.toReversed().map(p=>project(p.te,side))]);
  const all=polys.flat(),lo=Math.min(...all.map(p=>p[0])),hi=Math.max(...all.map(p=>p[0])),bottom=Math.min(...all.map(p=>p[1])),top=Math.max(...all.map(p=>p[1]));
  const scale=Math.min(385/(hi-lo||1),(height-60)/(top-bottom||.1));
  const P=p=>[220+(p[0]-(hi+lo)/2)*scale,35+(p[1]-bottom)*scale];
  svg.innerHTML=`<text x="18" y="18" font-size="10" fill="#647787">${front?'FRONT · GULL-WING / DIHEDRAL':'TOP · ACTUAL NEUTRAL PROJECTION'}</text>`+polys.map(poly=>`<polygon points="${poly.map(P).map(p=>p.join(',')).join(' ')}" fill="#c6e6df" stroke="#007f78" stroke-width="1.6"/>`).join('')+[1].flatMap(side=>pts.map(p=>{const a=P(project(p.le,side)),b=P(project(p.te,side));return `<line x1="${a[0]}" y1="${a[1]}" x2="${b[0]}" y2="${b[1]}" stroke="#507e7a" stroke-dasharray="3 3"/>`;})).join('');
}
function drawCustom3d(){
  const c=draftCase(),pts=c.geometry.stations,gap=Number($('gap_m')?.value||.04),polys=[];
  const project=p=>{const x=p[1]*Math.cos(viewYaw)-p[0]*Math.sin(viewYaw),depth=p[1]*Math.sin(viewYaw)+p[0]*Math.cos(viewYaw);return [x,depth*Math.sin(viewElevation)-p[2]*Math.cos(viewElevation)];};
  for(const side of [1])for(let i=0;i<pts.length-1;i++)polys.push([pts[i].le,pts[i].te,pts[i+1].te,pts[i+1].le].map(p=>project([p[0],side*p[1],p[2]])));
  const all=polys.flat();if(!all.length){$('custom3d').innerHTML='';return;}if(all.some(p=>p.some(v=>!Number.isFinite(v))))return;
  const lo=Math.min(...all.map(p=>p[0])),hi=Math.max(...all.map(p=>p[0])),bot=Math.min(...all.map(p=>p[1])),top=Math.max(...all.map(p=>p[1])),scale=Math.min(480/(hi-lo||1),190/(top-bot||.1));
  $('custom3d').innerHTML='<text x="16" y="20" font-size="11" fill="#647787">3D · NEUTRAL FLAP · DRAG TO ROTATE</text>'+polys.map(p=>`<polygon points="${p.map(a=>[280+(a[0]-(hi+lo)/2)*scale,45+(a[1]-bot)*scale].join(',')).join(' ')}" fill="#b6dcd5" fill-opacity=".75" stroke="#007f78"/>`).join('');
}
let tailDraft;
function installTailUI(){
  const card=document.createElement('div');card.className='card';card.id='tailCard';
  card.innerHTML=`<div class="section-title"><span class="num">04</span><h2>Optional static tail · fixed for this study</h2></div>
    <label><input id="tailEnabled" type="checkbox"> Include a symmetric static tail</label>
    <p class="help">One tail design and overall pitch for every case. Main wings flap; the tail stays fixed. Total forces include both surfaces and their flow interaction. Servo motion is a future feature.</p>
    <div id="tailControls" class="hidden">
      <div class="fields" id="tailFields" style="margin-top:16px"></div>
      <p class="help">Overall pitch rotates the whole tail about its root leading edge. Local pitch and roll below define its shape. Positions use the main-wing root origin: x aft, z up. Place the tail clear of the moving wings.</p>
      <label>Number of tail chord sections<input id="tailSectionCount" type="number" min="2" step="1"></label>
      <button class="btn" id="applyTailSections" style="margin:8px 0">Apply tail section count</button>
      <div style="overflow:auto"><table id="tailSectionTable"><thead><tr><th>Section</th><th>Position<br>m</th><th>Aft offset<br>m</th><th>Width<br>m</th><th>Local pitch<br>°</th><th>Roll<br>°</th><th>LE sweep<br>°</th></tr></thead><tbody id="tailSectionRows"></tbody></table></div>
      <p class="help">Edit the single simulated wing. Leading-edge sweep is the incoming interval angle. Drag numbered endpoints below to change chord widths.</p>
      <svg id="tailChordEditor" viewBox="0 0 560 230" style="width:100%;background:#fff8f0;border:1px solid #eadac6;border-radius:8px;touch-action:none" aria-label="Editable half-tail chord widths"></svg>
      <svg id="tailLayout" viewBox="0 0 560 360" style="width:100%;margin-top:12px;background:#f7fafb;border:1px solid #dce5e9;border-radius:8px" aria-label="Top and side views of flapping wings and fixed tail"></svg>
      <p class="caption">Neutral configuration: main wings teal, static tail orange. The side view shows the overall tail pitch. This preview does not certify motion clearance.</p>
      <div id="tailInfo" class="help"></div>
    </div>`;
  $('solverFields').closest('.card').after(card);
  const style=document.createElement('style');style.textContent='#tailSectionTable td,#tailSectionTable th{padding:6px 3px}#tailSectionTable input{padding:7px 4px;min-width:54px}';document.head.appendChild(style);
  $('tailEnabled').onchange=()=>{$('tailControls').classList.toggle('hidden',!$('tailEnabled').checked);preview();};
  $('applyTailSections').onclick=()=>{
    readTailRows();const n=Number($('tailSectionCount').value);
    if(!Number.isInteger(n)||n<2||n>1000){notify('Use at least two tail sections.');return;}
    const old=tailDraft.sections,tip=old.at(-1).y_m;
    tailDraft.sections=Array.from({length:n},(_,i)=>{const y=tip*i/(n-1),j=Math.max(0,old.findIndex(s=>s.y_m>=y)-1),a=old[j],b=old[Math.min(j+1,old.length-1)],t=(y-a.y_m)/(b.y_m-a.y_m||1);return Object.fromEntries(sectionKeys.map(k=>[k,k==='y_m'?y:a[k]+t*(b[k]-a[k])]));});
    renderTailRows();preview();
  };
}
function fillTail(t){
  tailDraft=structuredClone({...defaults.tail,...t,sections:t.sections||defaults.tail.sections});
  $('tailEnabled').checked=!!tailDraft.enabled;$('tailControls').classList.toggle('hidden',!tailDraft.enabled);
  $('tailFields').innerHTML=field('tail_pitch_deg','Overall tail pitch (°)',tailDraft.pitch_deg,'Constant across the study; independent of local twist.','number')+
    field('tail_x_m','Tail root aft position x (m)',tailDraft.x_m,'Measured from the main-wing root leading edge.','number')+
    field('tail_z_m','Tail root height z (m)',tailDraft.z_m,'Positive above the main-wing root.','number')+
    field('tail_span_panels','Tail span panels per half',tailDraft.span_panels,'At least one per section interval. Adds to total mesh cost.','number')+
    field('tail_chord_panels','Tail chordwise panels',tailDraft.chord_panels,'Separate fixed tail mesh resolution.','number');
  renderTailRows();
}
function readTailRows(){document.querySelectorAll('[data-tail-section]').forEach(input=>tailDraft.sections[Number(input.dataset.tailSection)][input.dataset.key]=Number(input.value));}
function tailConfig(){
  readTailRows();
  if($('tailEnabled').checked)for(const input of document.querySelectorAll('[data-tail-edge]'))if(!input.checkValidity())throw Error('Tail sweep must lie strictly between -90° and 90° with increasing section positions.');
  return {enabled:$('tailEnabled').checked,sections:structuredClone(tailDraft.sections),
    ...Object.fromEntries(['pitch_deg','x_m','z_m','span_panels','chord_panels'].map(k=>[k,$('tail_'+k).value]))};
}
function tailEdgeAngle(i){const a=tailDraft.sections[i-1],b=tailDraft.sections[i];return Number((Math.atan2(b.x_m-a.x_m,b.y_m-a.y_m)*180/Math.PI).toPrecision(8));}
function renderTailRows(){
  $('tailSectionCount').value=tailDraft.sections.length;
  $('tailSectionRows').innerHTML=tailDraft.sections.map((s,i)=>`<tr><td>${i===0?'Root':i===tailDraft.sections.length-1?'Tip':i+1}</td>${sectionKeys.map(k=>`<td><input type="number" step="any" data-tail-section="${i}" data-key="${k}" value="${s[k]}" aria-label="Tail section ${i+1} ${k}" ${!i&&['y_m','x_m'].includes(k)?'disabled':''}></td>`).join('')}<td>${i?`<input type="number" step="any" data-tail-edge="${i}" value="${tailEdgeAngle(i)}" aria-label="Tail section ${i+1} leading-edge sweep">`:'—'}</td></tr>`).join('');
  document.querySelectorAll('[data-tail-section]').forEach(input=>input.oninput=()=>{readTailRows();document.querySelectorAll('[data-tail-edge]').forEach(a=>{a.value=tailEdgeAngle(Number(a.dataset.tailEdge));a.setCustomValidity('');});drawTailEditor();});
  document.querySelectorAll('[data-tail-edge]').forEach(input=>input.oninput=()=>{
    const i=Number(input.dataset.tailEdge),angle=Number(input.value),a=tailDraft.sections[i-1],b=tailDraft.sections[i];
    input.setCustomValidity('');if(input.value===''||!Number.isFinite(angle)||Math.abs(angle)>=90||b.y_m<=a.y_m){input.setCustomValidity('Use -90° < sweep < 90° with increasing positions.');return;}
    const shift=a.x_m+(b.y_m-a.y_m)*Math.tan(angle*Math.PI/180)-b.x_m;
    for(let j=i;j<tailDraft.sections.length;j++){tailDraft.sections[j].x_m+=shift;document.querySelector(`[data-tail-section="${j}"][data-key="x_m"]`).value=tailDraft.sections[j].x_m;}
    drawTailEditor();
  });
  drawTailEditor();
}
let tailEditorScale=1,tailEditorMin=0,tailDragged=null;
function drawTailEditor(){
  const ss=tailDraft.sections;if(ss.length<2||ss.at(-1).y_m<=0)return;
  const min=Math.min(...ss.map(s=>s.x_m)),max=Math.max(...ss.map(s=>s.x_m+s.chord_m));
  tailEditorMin=min;tailEditorScale=Math.min(460/ss.at(-1).y_m,160/(max-min||.1));
  const X=y=>50+y*tailEditorScale,Y=x=>35+(x-min)*tailEditorScale;
  $('tailChordEditor').innerHTML='<text x="16" y="18" font-size="11" fill="#8c663e">UNPITCHED HALF-TAIL · DRAG CHORD ENDPOINTS</text>'+`<polygon points="${[...ss.map(s=>[X(s.y_m),Y(s.x_m)]),...ss.toReversed().map(s=>[X(s.y_m),Y(s.x_m+s.chord_m)])].map(p=>p.join(',')).join(' ')}" fill="#f5d6b4" stroke="#a76525"/>`+ss.map((s,i)=>`<line x1="${X(s.y_m)}" y1="${Y(s.x_m)}" x2="${X(s.y_m)}" y2="${Y(s.x_m+s.chord_m)}" stroke="#c09562"/><circle data-tail-handle="${i}" cx="${X(s.y_m)}" cy="${Y(s.x_m+s.chord_m)}" r="9" fill="#a76525" style="cursor:ns-resize"/><text pointer-events="none" x="${X(s.y_m)}" y="${Y(s.x_m+s.chord_m)+3}" text-anchor="middle" fill="white" font-size="9">${i+1}</text>`).join('');
  document.querySelectorAll('[data-tail-handle]').forEach(h=>h.onpointerdown=e=>{e.preventDefault();tailDragged=Number(h.dataset.tailHandle);$('tailChordEditor').setPointerCapture(e.pointerId);});
}
function neutralSurfaces(c,gap){
  const a=c.incidence_deg*Math.PI/180;
  const pts=c.geometry.stations.map(s=>s.le?{le:[...s.le],te:[...s.te]}:{le:[s.x_m*Math.cos(a),s.y_m,-s.x_m*Math.sin(a)],te:[(s.x_m+s.chord_m)*Math.cos(a),s.y_m,-(s.x_m+s.chord_m)*Math.sin(a)]});
  return [-1,1].map(side=>[...pts.map(p=>[p.le[0],side*(p.le[1]+gap/2),p.le[2]]),...pts.toReversed().map(p=>[p.te[0],side*(p.te[1]+gap/2),p.te[2]])]);
}
function drawTailLayout(c,s,t,target='tailLayout'){
  if(!s.tail?.enabled||!t){$(target).innerHTML='';if(target==='tailLayout')$('tailInfo').textContent='';return;}
  const sets=[{polys:neutralSurfaces(c,s.gap_m),fill:'#c6e6df',stroke:'#007f78'},
    {polys:neutralSurfaces(t,0),fill:'#f5d6b4',stroke:'#a76525'}];
  let out='';
  for(const [index,label,projection] of [[0,'TOP · WINGS + STATIC TAIL',p=>[p[1],p[0]]],[1,'SIDE · OVERALL TAIL PITCH',p=>[p[0],-p[2]]]]){
    const all=sets.flatMap(set=>set.polys.flat().map(projection)),lo=Math.min(...all.map(p=>p[0])),hi=Math.max(...all.map(p=>p[0])),bot=Math.min(...all.map(p=>p[1])),top=Math.max(...all.map(p=>p[1]));
    const scale=Math.min(485/(hi-lo||1),125/(top-bot||.1)),P=p=>[280+(p[0]-(lo+hi)/2)*scale,30+index*180+(p[1]-bot)*scale];
    out+=`<text x="16" y="${17+index*180}" font-size="11" fill="#647787">${label}</text>`;
    for(const set of sets)out+=set.polys.map(poly=>`<polygon points="${poly.map(projection).map(P).map(p=>p.join(',')).join(' ')}" fill="${set.fill}" stroke="${set.stroke}" stroke-width="1.4"/>`).join('');
  }
  $(target).innerHTML=out;
  if(target==='tailLayout')$('tailInfo').textContent=`Tail total span ${t.span_m.toPrecision(4)} m · overall pitch ${s.tail.pitch_deg}° · root x ${s.tail.x_m} m, z ${s.tail.z_m} m · ${2*s.tail.span_panels*s.tail.chord_panels} tail panels. Tail files are saved once per study.`;
}

function installWaveformUI(){
  $('motionFields').insertAdjacentHTML('afterend',`<div id="waveformControls" style="margin-top:18px"><label>Flapping waveform<select id="waveformMode"><option value="sine">Sine · default constant-phase drive</option><option value="custom">Custom · periodic phase/angle points</option></select></label><div id="waveformEditor" class="hidden"><p class="help">One phase, relative-angle pair per line. Phase runs from 0 to 1 cycle. Start with 0,0 and end with 1,0. A smooth periodic cubic curve joins the points and is scaled to the selected half-stroke amplitude. The preview shows any overshoot or offset.</p><label>Phase, relative flap angle<textarea id="waveformPoints" rows="7" style="width:100%;font-family:monospace"></textarea></label><div class="actions"><button type="button" class="btn" id="waveSymmetric">Symmetric stroke points</button><button type="button" class="btn" id="waveAsymmetric">Faster first half-stroke</button></div></div><svg id="motionPreview" viewBox="0 0 600 235" role="img" aria-label="Flapping angle over one cycle" style="width:100%;margin-top:14px"></svg><p id="motionDetails" class="caption"></p><p class="help">The single simulated wing follows this angle. One waveform is held fixed across the study. This prescribes wing motion, not motor speed for the pictured linkage. Physical wing hinge moments are used directly for the shape objective; drivetrain torque is outside this study.</p></div>`);
  $('waveformMode').onchange=()=>{$('waveformEditor').classList.toggle('hidden',$('waveformMode').value!=='custom');};
  $('waveSymmetric').onclick=()=>{$('waveformPoints').value='0, 0\n0.25, 1\n0.5, 0\n0.75, -1\n1, 0';preview();};
  $('waveAsymmetric').onclick=()=>{$('waveformPoints').value='0, 0\n0.15, 1\n0.35, 0\n0.65, -1\n1, 0';preview();};
}
function fillWaveform(w){
  $('waveformMode').value=w.mode||'sine';
  $('waveformPoints').value=Array.isArray(w.points)?w.points.map(p=>p.join(', ')).join('\n'):(w.points||defaults.waveform.points);
  $('waveformEditor').classList.toggle('hidden',$('waveformMode').value!=='custom');
}
function drawMotion(p){
  if(!p)return;
  const half=Math.max(Math.abs(p.minimum_deg),Math.abs(p.maximum_deg),1)*1.15;
  const X=x=>65+510*x,Y=y=>110-80*y/half;
  let out=`<line x1="65" y1="110" x2="575" y2="110" stroke="#a6b7bf" stroke-dasharray="3 3"/><line x1="65" y1="25" x2="65" y2="195" stroke="#82949c"/><line x1="65" y1="195" x2="575" y2="195" stroke="#82949c"/>`;
  out+=`<polyline points="${p.points.map(([phase,angle])=>`${X(phase)},${Y(angle)}`).join(' ')}" fill="none" stroke="#007f78" stroke-width="2.5"/>`;
  for(const phase of [0,.25,.5,.75,1])out+=`<text x="${X(phase)}" y="211" text-anchor="middle" font-size="11" fill="#526b78">${phase}</text>`;
  out+=`<text x="52" y="${Y(p.maximum_deg)+3}" text-anchor="end" font-size="11">${p.maximum_deg.toFixed(1)}°</text><text x="52" y="${Y(p.minimum_deg)+3}" text-anchor="end" font-size="11">${p.minimum_deg.toFixed(1)}°</text><text x="320" y="231" text-anchor="middle" font-size="12">Cycle phase · right wing flap angle</text>`;
  $('motionPreview').innerHTML=out;
  $('motionDetails').textContent=`Range ${p.minimum_deg.toFixed(2)}° to ${p.maximum_deg.toFixed(2)}° · period ${p.period_s.toPrecision(4)} s · ${p.signature==='sine'?'sine default':'smooth custom waveform'}. Refine delta time to resolve fast strokes and reversals.`;
}
let landscapeStudy='',landscapeData=null;
function installLandscapeUI(){
  $('rankingCard').insertAdjacentHTML('afterend',`<details class="card" id="landscapeCard"><summary>Optional 3D wing-shape comparison</summary><div style="margin-top:16px"><div class="toolbar"><div><h2>Wing shapes · area, aspect ratio & thrust/moment</h2><p class="caption">Each wing thumbnail is a simulated case at its measured coordinates. The mesh/curve interpolates between samples.</p></div><button class="btn primary" id="makeLandscape">Generate 3D plot + PNG/CSV</button></div><label><input type="checkbox" id="landscapeRepeat" checked> Only repeatable cycles</label><div id="landscapeStatus" class="caption" style="margin:12px 0">Choose a study, then generate the 3D comparison.</div><div id="landscapeResult"></div></div></details>`);
  $('makeLandscape').onclick=async()=>{try{const study=chosenStudy();if(!study)return;$('makeLandscape').disabled=true;$('landscapeStatus').textContent='Building wing thumbnails and interpolated mesh…';const d=await api('shape-landscape',{study:study.id,repeat_only:$('landscapeRepeat').checked});if(currentStudy!==study.id)return;landscapeData=d;renderLandscape(d);$('landscapeStatus').textContent=d.note;}catch(e){$('landscapeStatus').textContent=e.message;}finally{$('makeLandscape').disabled=!chosenStudy()||chosenStudy().status.state==='running';}};
  $('landscapeRepeat').onchange=()=>{landscapeData=null;$('landscapeResult').innerHTML='';$('landscapeStatus').textContent='Filter changed. Generate the plot to update it.';};
}
function syncLandscape(study){$('makeLandscape').disabled=!study||study.status.state==='running';if(landscapeStudy!==(study?.id||'')){landscapeStudy=study?.id||'';landscapeData=null;$('landscapeResult').innerHTML='';$('landscapeStatus').textContent='Choose a study, then generate the 3D comparison.';}}
function renderLandscape(d,host="landscapeResult",prefix=""){
  const target=document.getElementById(host),$=id=>document.getElementById(prefix+id);
  target.innerHTML=`<svg id="landscape3d" viewBox="0 0 760 490" style="width:100%;background:#f5f9fa;border:1px solid #dce5e9;border-radius:8px;touch-action:none;cursor:grab" role="img" aria-label="Rotatable wing thumbnails: wing area, aspect ratio and thrust to roll moment"></svg><div class="actions" style="margin:12px 0"><button class="btn" id="resetLandscape">Reset view</button><label>Wing thumbnail size<input id="landscapeSize" type="range" min="12" max="65" value="45"></label><label><input id="landscapeMesh" type="checkbox" checked> Show interpolated mesh/curve</label></div><p class="caption">Drag to rotate · wheel to zoom · click a wing to inspect. Thumbnail size is normalized; coordinates carry the actual values. Overlapping samples can be selected below.</p><div id="landscapePoint" class="note" style="margin:12px 0">${d.points.length} simulated wings · ${d.vertices.length} distinct area/aspect-ratio locations · ${d.triangles.length?'triangulated surface':d.curve.length?'interpolated curve':'points only'}.</div><div class="actions"><a href="/files/${d.file}" download>600-dpi PNG</a><a href="/files/${d.file.replace(/\.png$/,'.csv')}" download>Measured cases CSV</a></div>`.replace(/id="([^"]+)"/g,(_,id)=>`id="${prefix}${id}"`);
  const svg=$('landscape3d'),points=d.points;
  let yaw=.6,pitch=.5,zoom=1,drag=null,moved=false,screen=[],frame=null;
  const ranges=[0,1,2].map(i=>{const v=points.map(p=>p.coords[i]);return [Math.min(...v),Math.max(...v)];});
  const normal=c=>c.map((v,i)=>ranges[i][1]===ranges[i][0]?0:(v-ranges[i][0])/(ranges[i][1]-ranges[i][0])-.5);
  const project=v=>{const a=Math.cos(yaw)*v[0]-Math.sin(yaw)*v[1],b=Math.sin(yaw)*v[0]+Math.cos(yaw)*v[1];return [355+245*zoom*a,237+205*zoom*(Math.sin(pitch)*b-Math.cos(pitch)*v[2]),Math.cos(pitch)*b+Math.sin(pitch)*v[2]];};
  const color=v=>{const f=ranges[2][0]===ranges[2][1]?.5:(v-ranges[2][0])/(ranges[2][1]-ranges[2][0]);return `rgb(${Math.round(20+215*f)},${Math.round(78+125*f)},${Math.round(110-35*f)})`;};
  function inspect(p){const near=points.filter(q=>Math.hypot(...normal(q.coords).map((v,i)=>v-normal(p.coords)[i]))<1e-8);$('landscapePoint').innerHTML=`<strong>${esc(p.case_id)} · thrust / roll ${p.value.toPrecision(6)} 1/m</strong><br>Area ${p.coords[0].toPrecision(5)} m² · aspect ratio ${p.coords[1].toPrecision(5)} · single-wing thrust ${p.single_wing_mean_thrust_N.toPrecision(5)} N · peak |roll| ${p.single_wing_peak_abs_roll_moment_Nm.toPrecision(5)} N m<br>Chords: ${p.chords_m.map(v=>Number(v.toPrecision(5))).join(' / ')} m<br><a href="/api/case/${p.source_study||currentStudy}/${p.source_case||p.case_id}" target="_blank">Full case inputs and outputs</a>`+(near.length>1?`<br>Coincident samples: ${near.map(q=>`<button class="btn" data-landscape-case="${q.case_id}">${esc(q.case_id)}</button>`).join('')}`:'');target.querySelectorAll('[data-landscape-case]').forEach(b=>b.onclick=()=>inspect(points.find(p=>p.case_id===b.dataset.landscapeCase)));}
  function draw(){frame=null;let h='';const objects=[];
    if($('landscapeMesh').checked){
      for(const tri of d.triangles){const vv=tri.map(i=>d.vertices[i]),s=vv.map(v=>project(normal(v)));objects.push({depth:s.reduce((a,b)=>a+b[2],0)/3,html:`<polygon points="${s.map(p=>p.slice(0,2).join(',')).join(' ')}" fill="${color(vv.reduce((a,b)=>a+b[2],0)/3)}" fill-opacity=".23" stroke="#6c929e" stroke-opacity=".6" stroke-width=".7"/>`});}
      for(let i=1;i<d.curve.length;i++){const a=project(normal(d.curve[i-1])),b=project(normal(d.curve[i]));objects.push({depth:(a[2]+b[2])/2,html:`<line x1="${a[0]}" y1="${a[1]}" x2="${b[0]}" y2="${b[1]}" stroke="#6e9aa8" stroke-width="1.8"/>`});}
    }
    const origin=[-.6,-.6,-.6],o=project(origin);
    d.axis_labels.forEach((label,i)=>{const end=[...origin];end[i]=.69;const at=project(end);h+=`<line x1="${o[0]}" y1="${o[1]}" x2="${at[0]}" y2="${at[1]}" stroke="#78939e"/>`;const lp=[...origin];lp[i]=.84;const l=project(lp);h+=`<text x="${l[0]}" y="${i===2?Math.max(55,l[1]-8):l[1]+15}" text-anchor="middle" font-size="12" fill="#284e61">${esc(label)}</text>`;for(const t of [0,.5,1]){const v=[...origin];v[i]=t-.5;const p=project(v),value=ranges[i][0]+t*(ranges[i][1]-ranges[i][0]);h+=`<text x="${p[0]+5}" y="${p[1]+13}" font-size="10" fill="#67818c">${Number(value.toPrecision(4))}</text>`;}});
    const size=Number($('landscapeSize').value);
    screen=points.map(p=>({p,s:project(normal(p.coords))}));
    for(const {p,s} of screen){const paths=p.thumbnail.map(poly=>`M${poly.map(v=>`${s[0]+size*v[0]},${s[1]+size*v[1]}`).join('L')}Z`).join('');objects.push({depth:s[2],html:`<g data-wing-point="${p.case_id}"><title>${esc(p.case_id)} · A ${p.coords[0].toPrecision(4)} m² · AR ${p.coords[1].toPrecision(4)} · T/M ${p.value.toPrecision(5)} 1/m</title><path d="${paths}" fill="${color(p.value)}" fill-opacity=".93" stroke="#254c5b" stroke-width=".9"/>${!p.repeatable?`<text x="${s[0]}" y="${s[1]+4}" fill="white" font-size="12">×</text>`:''}</g>`});}
    h+=objects.sort((a,b)=>a.depth-b.depth).map(o=>o.html).join('');
    h+=`<text x="16" y="23" font-size="12" fill="#526f7c">${points.length} measured wing shapes · ${d.triangles.length?'interpolated mesh':d.curve.length?'interpolated curve':'no interpolation yet'}</text><text x="16" y="472" font-size="11" fill="#526f7c">Measured thumbnails · translucent/wire geometry is interpolated</text>`;
    svg.innerHTML=h;
  }
  const schedule=()=>{if(frame===null)frame=requestAnimationFrame(draw);};
  svg.onpointerdown=e=>{drag=[e.clientX,e.clientY];moved=false;svg.setPointerCapture(e.pointerId);};
  svg.onpointermove=e=>{if(!drag)return;const dx=e.clientX-drag[0],dy=e.clientY-drag[1];if(Math.abs(dx)+Math.abs(dy)>2)moved=true;yaw+=dx*.008;pitch=Math.max(-1.2,Math.min(1.2,pitch+dy*.008));drag=[e.clientX,e.clientY];schedule();};
  svg.onpointerup=e=>{drag=null;if(moved)return;const rect=svg.getBoundingClientRect(),x=(e.clientX-rect.left)*760/rect.width,y=(e.clientY-rect.top)*490/rect.height;const pick=screen.map(p=>({...p,d:Math.hypot(p.s[0]-x,p.s[1]-y)})).sort((a,b)=>a.d-b.d||b.s[2]-a.s[2])[0];if(pick&&pick.d<35)inspect(pick.p);};
  svg.onpointercancel=()=>drag=null;
  svg.addEventListener('wheel',e=>{e.preventDefault();zoom=Math.max(.55,Math.min(1.5,zoom*Math.exp(-e.deltaY*.001)));schedule();},{passive:false});
  $('resetLandscape').onclick=()=>{yaw=.6;pitch=.5;zoom=1;draw();};$('landscapeSize').oninput=schedule;$('landscapeMesh').onchange=draw;draw();
}
installCustomUI();installShapeUI();installTailUI();installWaveformUI();
$('bestDesign').before($('rankingCard'));
const winnerDetails=document.createElement('details');winnerDetails.className='card';winnerDetails.innerHTML='<summary>Winning wing details</summary>';$('bestDesign').before(winnerDetails);winnerDetails.append($('bestDesign'));$('bestDesign').classList.remove('card');
installLandscapeUI();
$('saveRanking').onclick=async()=>{try{$('saveRanking').disabled=true;const d=await api('shape-comparison',{study:currentStudy,export:true,repeat_only:$('repeatOnly').checked});$('rankingExports').innerHTML=(d.files||[d.file]).map((file,i)=>`<a href="/files/${file}" download>PNG${d.files?.length>1?' '+(i+1):''}</a>`).join(' · ')+` · <a href="/files/${d.file.replace(/\.png$/,'.csv')}" download>CSV</a>`;notify('Ranked wing list saved.');}catch(e){notify(e.message);}finally{$('saveRanking').disabled=!chosenStudy()||chosenStudy().status.state==='running';}};
$('tailChordEditor').onpointermove=e=>{if(tailDragged===null)return;const rect=$('tailChordEditor').getBoundingClientRect(),y=(e.clientY-rect.top)*230/rect.height,s=tailDraft.sections[tailDragged];s.chord_m=Math.max(0,Math.round(((y-35)/tailEditorScale+tailEditorMin-s.x_m)*10000)/10000);document.querySelector(`[data-tail-section="${tailDragged}"][data-key="chord_m"]`).value=s.chord_m;drawTailEditor();clearTimeout(timer);timer=setTimeout(preview,350);};
$('tailChordEditor').onpointerup=$('tailChordEditor').onpointercancel=()=>tailDragged=null;
$('chordEditor').onpointermove=e=>{if(draggedChord===null)return;const rect=$('chordEditor').getBoundingClientRect(),y=(e.clientY-rect.top)*245/rect.height,s=draft.sections[draggedChord];s.chord_m=Math.max(0,Math.round(((y-40)/editorScale+editorMin-s.x_m)*10000)/10000);document.querySelector(`[data-section="${draggedChord}"][data-key="chord_m"]`).value=s.chord_m;drawDraft();};
$('chordEditor').onpointerup=$('chordEditor').onpointercancel=()=>draggedChord=null;
let rotateFrom=null;
$('custom3d').onpointerdown=e=>{rotateFrom=[e.clientX,e.clientY];$('custom3d').setPointerCapture(e.pointerId);};
$('custom3d').onpointermove=e=>{if(!rotateFrom)return;viewYaw+=(e.clientX-rotateFrom[0])*.01;viewElevation=Math.max(-1.4,Math.min(1.4,viewElevation+(e.clientY-rotateFrom[1])*.01));rotateFrom=[e.clientX,e.clientY];drawCustom3d();};
$('custom3d').onpointerup=$('custom3d').onpointercancel=()=>rotateFrom=null;
$('tailCard').classList.add('hidden');
init();
