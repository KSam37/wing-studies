'use strict';
const OFFLINE=globalThis.WING_ATLAS_OFFLINE===true;
const $=id=>document.getElementById(id), esc=s=>String(s??'').replace(/[&<>"']/g,c=>({'&':'&amp;','<':'&lt;','>':'&gt;','"':'&quot;',"'":'&#39;'}[c])), finite=Number.isFinite;
let atlas=null,visible=[],positions=[],chosen=[],version=0;
let viewport=null,autoView=null,plotArea=null,viewRows=[],viewKey='',drag=null,suppressClick=false;
const bounds=['span_min','span_max','root_min','root_max','xmin','xmax','ymin','ymax'];
function params(){return {cohort:$('cohort').value,study:$('study').value,x:$('x').value,y:$('y').value,color:$('color').value,generations:['current','old'].filter(g=>$(g).checked),mode:$('mode').value,silhouettes:Number($('silhouettes').value),normalized:$('normalized').value==='true',...Object.fromEntries(bounds.map(k=>[k,$(k).value]))};}
function filtered(b,p){let rows=b.rows.filter(r=>(p.cohort==='all_single'?r.load_scope==='single':r.cohort===p.cohort)&&p.generations.some(g=>r.generations.includes(g))&&(!p.study||r.studies.includes(p.study)));for(const [f,lo,hi] of [['span','span_min','span_max'],['root','root_min','root_max'],[p.x,'xmin','xmax'],[p.y,'ymin','ymax']]){const a=p[lo]===''?null:Number(p[lo]),z=p[hi]===''?null:Number(p[hi]);if((a!==null&&!finite(a))||(z!==null&&!finite(z))||(a!==null&&z!==null&&z<a))throw Error('Check the filter minimum and maximum.');rows=rows.filter(r=>finite(r[f])&&(a===null||r[f]>=a)&&(z===null||r[f]<=z));}return rows;}
function sample(rows,x,y,limit){if(!rows.length||!limit)return [];let xs=rows.map(r=>r[x]),ys=rows.map(r=>r[y]),a=Math.min(...xs),b=Math.max(...xs),c=Math.min(...ys),d=Math.max(...ys),cells=new Map;for(const r of rows){let u=(r[x]-a)/(b-a||1),v=(r[y]-c)/(d-c||1),i=Math.min(7,Math.floor(u*8)),j=Math.min(5,Math.floor(v*6)),dist=(u-(i+.5)/8)**2+(v-(j+.5)/6)**2,k=i*6+j;if(!cells.has(k)||dist<cells.get(k).dist)cells.set(k,{r,dist});}let all=[...cells].sort((a,b)=>a[0]-b[0]).map(e=>e[1].r);if(all.length<=limit)return all;let out=[all[0]],dist=(r,q)=>((r[x]-q[x])/(b-a||1))**2+((r[y]-q[y])/(d-c||1))**2;while(out.length<limit){let remaining=all.filter(r=>!out.includes(r));remaining.sort((r,q)=>Math.min(...out.map(z=>dist(q,z)))-Math.min(...out.map(z=>dist(r,z))));out.push(remaining[0]);}return out;}
function palette(t){const stops=[[68,1,84],[59,82,139],[33,145,140],[94,201,98],[253,231,37]];t=Math.max(0,Math.min(1,t))*4;let i=Math.min(3,Math.floor(t));return `rgb(${stops[i].map((v,k)=>Math.round(v+(stops[i+1][k]-v)*(t-i))).join(',')})`;}
function svg(r,extent=null){let ps=r.outline,x=Math.min(...ps.map(p=>p[0])),y=Math.min(...ps.map(p=>p[1])),w=Math.max(...ps.map(p=>p[0]))-x,h=Math.max(...ps.map(p=>p[1]))-y,e=extent||Math.max(w,h),s=120/(e||1);return `<svg viewBox="0 0 150 150" role="img" aria-label="Wing outline"><polygon points="${ps.map(p=>`${10+(p[0]-x)*s},${10+(p[1]-y)*s}`).join(' ')}" fill="#a9d9d4" stroke="#237a7b" stroke-width="1"/></svg>`;}
function metric(r,k){return finite(r[k])?r[k].toPrecision(5):'Unavailable';}
function detail(r){let g=atlas.cohorts.find(g=>g.id===r.cohort);$('detail').innerHTML=`<h2>Case ${esc(r.number)}</h2>${svg(r)}<p>${esc(r.name)}</p>${['thrust','torque','span','area','root','aspect','fullness','taper','ratio'].map(k=>`<div><small>${esc(atlas.metrics[k])}</small><br><strong>${metric(r,k)}</strong></div>`).join('')}<p class="help">Chord widths (m): ${r.chords.map(v=>Number(v).toPrecision(3)).join(', ')}</p><details><summary>Saved conditions</summary><pre style="font-size:10px;white-space:pre-wrap">${esc(JSON.stringify(g.conditions,null,2))}</pre></details><p class="help">${r.locations.map(o=>`${esc(atlas.studies.find(s=>s.id===o.study)?.name||o.study)} / ${esc(o.case)}`).join('<br>')}</p>${OFFLINE?'<p class="help">Offline snapshot: original simulation files, animations and refinement require the full app.</p>':`<p><a href="/?refineStudy=${encodeURIComponent(r.study)}&refineCase=${encodeURIComponent(r.id)}">Refine this wing · finer coordinate search</a></p><a href="/#catalog">Open study results</a><p>${[['water_wing_forces.png','Ptera forces'],['water_wing_moments.png','Ptera moments'],['animation.webp','Animation'],['wing_right.svg','Fabric SVG']].map(([f,label])=>`<a target="_blank" href="/files/${encodeURIComponent(r.study)}/${encodeURIComponent(r.id)}/${f}">${label}</a>`).join(' · ')}</p>`}`;}
function render(){if(!atlas)return;version++;try{const p=params();let group=atlas.cohorts.find(g=>g.id===p.cohort);if(group?.conditions.load_scope==='paired'&&['torque','ratio'].includes(p.x)){$('x').value='span';p.x='span';}if(group?.conditions.load_scope==='paired'&&['torque','ratio'].includes(p.y)){$('y').value='thrust';p.y='thrust';}visible=filtered(atlas,p);if(!Number.isInteger(p.silhouettes)||p.silhouettes<0||p.silhouettes>60)throw Error('Choose 0 to 60 silhouettes.');$('exports').innerHTML='';let groups=new Set(visible.map(r=>r.cohort));$('warning').textContent=groups.size>1?'Mixed conditions overview: changes in motion, time step or mesh can affect the loads. Choose one conditions group to isolate shape comparisons.':group?.conditions.load_scope==='paired'?'Legacy paired-wing thrust. Canceled paired roll moments are not used as single-wing root torque.':'Saved conditions match within this selection. Shape and size can still vary together.';$('conditions').textContent=group?JSON.stringify(group.conditions,null,2):`${groups.size} saved conditions groups. Select a group above to inspect its settings.`;const key=JSON.stringify([p.cohort,p.study,p.x,p.y,p.generations,...bounds.map(k=>p[k])]);if(key!==viewKey){viewport=null;viewKey=key;}draw(p);chosen=sample(viewRows,p.x,p.y,p.silhouettes);let extent=p.normalized?null:Math.max(...visible.flatMap(r=>[0,1].map(k=>Math.max(...r.outline.map(q=>q[k]))-Math.min(...r.outline.map(q=>q[k])))),.01);$('gallery').innerHTML=chosen.map((r,i)=>`<button data-case="${i}">${svg(r,extent)}<strong>Case ${esc(r.number)}</strong><br>${metric(r,'span')} m · ${metric(r,'thrust')} N</button>`).join('');$('gallery').querySelectorAll('button').forEach((b,i)=>b.onclick=()=>detail(chosen[i]));}catch(e){$('warning').textContent=e.message;}}
function draw(p){
 const canvas=$('plot'),w=canvas.clientWidth||900,h=570,dpr=window.devicePixelRatio||1;
 canvas.width=w*dpr;canvas.height=h*dpr;
 const ctx=canvas.getContext('2d');ctx.scale(dpr,dpr);ctx.clearRect(0,0,w,h);positions=[];viewRows=[];
 plotArea={left:70,right:w-30,top:35,bottom:h-65};
 if(!visible.length){autoView=null;viewport=null;ctx.fillText('No matching simulations.',30,40);$('viewStatus').textContent='No matching simulations.';return;}
 const xs=visible.map(r=>r[p.x]),ys=visible.map(r=>r[p.y]);
 let lo=Math.min(...xs),hi=Math.max(...xs),bottom=Math.min(...ys),top=Math.max(...ys);
 const dx=(hi-lo||1)*.05,dy=(top-bottom||1)*.08;
 autoView={lo:lo-dx,hi:hi+dx,bottom:bottom-dy,top:top+dy};
 if(!viewport)viewport={...autoView};
 ({lo,hi,bottom,top}=viewport);
 const X=v=>plotArea.left+(v-lo)/(hi-lo)*(plotArea.right-plotArea.left),Y=v=>plotArea.bottom-(v-bottom)/(top-bottom)*(plotArea.bottom-plotArea.top);
 const vals=visible.map(r=>r[p.color]).filter(finite),cmin=Math.min(...vals),cmax=Math.max(...vals),color=r=>finite(r[p.color])?palette((r[p.color]-cmin)/(cmax-cmin||1)):'#999';
 ctx.font='12px Segoe UI';ctx.textAlign='center';
 for(let i=0;i<=5;i++){
  let x=X(lo+i*(hi-lo)/5),y=Y(bottom+i*(top-bottom)/5);
  ctx.strokeStyle='#e3e9ed';ctx.beginPath();ctx.moveTo(x,plotArea.top);ctx.lineTo(x,plotArea.bottom);ctx.moveTo(plotArea.left,y);ctx.lineTo(plotArea.right,y);ctx.stroke();
  ctx.fillStyle='#526a76';ctx.fillText((lo+i*(hi-lo)/5).toPrecision(3),x,h-42);ctx.textAlign='right';ctx.fillText((bottom+i*(top-bottom)/5).toPrecision(3),64,y+4);ctx.textAlign='center';
 }
 ctx.fillStyle='#19343f';ctx.fillText(atlas.metrics[p.x],w/2,h-12);ctx.save();ctx.translate(16,h/2);ctx.rotate(-Math.PI/2);ctx.fillText(atlas.metrics[p.y],0,0);ctx.restore();
 viewRows=visible.filter(r=>r[p.x]>=lo&&r[p.x]<=hi&&r[p.y]>=bottom&&r[p.y]<=top);
 positions=viewRows.map(r=>({r,x:X(r[p.x]),y:Y(r[p.y])}));
 ctx.save();ctx.beginPath();ctx.rect(plotArea.left,plotArea.top,plotArea.right-plotArea.left,plotArea.bottom-plotArea.top);ctx.clip();
 if(p.mode==='density'){
  const cells=new Map;
  for(const q of positions){const k=`${Math.floor(q.x/9)},${Math.floor(q.y/9)}`,c=cells.get(k)||{x:Math.floor(q.x/9)*9,y:Math.floor(q.y/9)*9,n:0};c.n++;cells.set(k,c);}
  const max=Math.max(1,...[...cells.values()].map(c=>c.n));
  for(const c of cells.values()){ctx.fillStyle=`rgba(25,52,63,${.1+.9*Math.log1p(c.n)/Math.log1p(max)})`;ctx.fillRect(c.x,c.y,8,8);}
 }else{
  ctx.globalAlpha=.38;for(const q of positions){ctx.fillStyle=color(q.r);ctx.beginPath();ctx.arc(q.x,q.y,2.2,0,Math.PI*2);ctx.fill();}ctx.globalAlpha=1;
 }
 const extent=Math.max(...visible.flatMap(r=>[0,1].map(k=>Math.max(...r.outline.map(q=>q[k]))-Math.min(...r.outline.map(q=>q[k])))),.01);
 for(const r of sample(viewRows,p.x,p.y,p.silhouettes)){
  const ps=r.outline,l=ps.map(q=>q[0]),v=ps.map(q=>q[1]),a=Math.min(...l),b=Math.min(...v),width=Math.max(...l)-a,height=Math.max(...v)-b,s=42/(p.normalized?Math.max(width,height):extent);
  ctx.beginPath();ps.forEach((q,i)=>{const x=X(r[p.x])+(q[0]-a-width/2)*s,y=Y(r[p.y])+(q[1]-b-height/2)*s;i?ctx.lineTo(x,y):ctx.moveTo(x,y);});ctx.closePath();ctx.fillStyle=color(r);ctx.fill();ctx.strokeStyle='#536874';ctx.lineWidth=.7;ctx.stroke();
 }
 ctx.restore();
 $('plotTitle').textContent=`${viewRows.length.toLocaleString()} in view / ${visible.length.toLocaleString()} simulations · ${atlas.metrics[p.y]} vs ${atlas.metrics[p.x]}`;
 $('viewStatus').textContent=`X ${lo.toPrecision(4)}–${hi.toPrecision(4)} · Y ${bottom.toPrecision(4)}–${top.toPrecision(4)} · ${viewRows.length.toLocaleString()} cases in view`;
 $('legendText').textContent=`${atlas.metrics[p.color]}: ${finite(cmin)?cmin.toPrecision(4):'unavailable'} → ${finite(cmax)?cmax.toPrecision(4):'unavailable'}${p.mode==='density'?' · darker cells contain more simulations; silhouettes use this color scale':''}${p.normalized?' · normalized silhouettes':' · common physical silhouette scale'}`;
}
function localPoint(e){const r=$('plot').getBoundingClientRect();return {x:e.clientX-r.left,y:e.clientY-r.top};}
function inside(q){return plotArea&&q.x>=plotArea.left&&q.x<=plotArea.right&&q.y>=plotArea.top&&q.y<=plotArea.bottom;}
function changedView(){version++;$('exports').innerHTML='';$('hover').classList.add('hidden');render();}
function zoomAt(factor,q){
 if(!viewport||!autoView||!inside(q))return;
 const u=(q.x-plotArea.left)/(plotArea.right-plotArea.left),v=(plotArea.bottom-q.y)/(plotArea.bottom-plotArea.top),oldX=viewport.hi-viewport.lo,oldY=viewport.top-viewport.bottom;
 const limit=Math.max(1e-6*(autoView.hi-autoView.lo)/oldX,1e-6*(autoView.top-autoView.bottom)/oldY),cap=Math.min(100*(autoView.hi-autoView.lo)/oldX,100*(autoView.top-autoView.bottom)/oldY);
 factor=Math.max(limit,Math.min(cap,factor));
 const x=viewport.lo+u*oldX,y=viewport.bottom+v*oldY;
 viewport={lo:x-u*oldX*factor,hi:x+(1-u)*oldX*factor,bottom:y-v*oldY*factor,top:y+(1-v)*oldY*factor};changedView();
}
function zoomCenter(factor){if(plotArea)zoomAt(factor,{x:(plotArea.left+plotArea.right)/2,y:(plotArea.top+plotArea.bottom)/2});}
function resetView(){viewport=null;changedView();}
function exportParams(){const p=params();return viewport?{...p,xmin:viewport.lo,xmax:viewport.hi,ymin:viewport.bottom,ymax:viewport.top}:p;}

function nearest(e){const q=localPoint(e);if(!inside(q))return null;let {x,y}=q,best=null,d=144;for(let q of positions){let n=(q.x-x)**2+(q.y-y)**2;if(n<d){best=q.r;d=n;}}return best;}
$('plot').onmousemove=e=>{if(drag?.moved)return;let r=nearest(e),h=$('hover');h.classList.toggle('hidden',!r);if(r){h.innerHTML=`${svg(r)}<strong>Case ${esc(r.number)}</strong><br>Span ${metric(r,'span')} m<br>Thrust ${metric(r,'thrust')} N<br>Peak root torque ${metric(r,'torque')} N m`;h.style.left=Math.min(e.clientX+15,window.innerWidth-280)+'px';h.style.top=Math.min(e.clientY+10,window.innerHeight-230)+'px';}};$('plot').onmouseleave=()=>$('hover').classList.add('hidden');$('plot').onclick=e=>{if(suppressClick){suppressClick=false;return;}let r=nearest(e);if(r)detail(r);};
const canvas=$('plot');
canvas.addEventListener('wheel',e=>{const q=localPoint(e);if(!inside(q))return;e.preventDefault();const delta=e.deltaY*(e.deltaMode===1?16:e.deltaMode===2?570:1);zoomAt(Math.exp(Math.max(-300,Math.min(300,delta))*.002),q);},{passive:false});
canvas.onpointerdown=e=>{if(e.button!==0||!viewport||!inside(localPoint(e)))return;canvas.focus();suppressClick=false;drag={id:e.pointerId,start:localPoint(e),view:{...viewport},moved:false};canvas.setPointerCapture(e.pointerId);};
canvas.onpointermove=e=>{if(!drag||drag.id!==e.pointerId)return;const q=localPoint(e),dx=q.x-drag.start.x,dy=q.y-drag.start.y;if(!drag.moved&&Math.hypot(dx,dy)<4)return;drag.moved=true;canvas.style.cursor='grabbing';const a=drag.view,sx=(a.hi-a.lo)/(plotArea.right-plotArea.left),sy=(a.top-a.bottom)/(plotArea.bottom-plotArea.top);viewport={lo:a.lo-dx*sx,hi:a.hi-dx*sx,bottom:a.bottom+dy*sy,top:a.top+dy*sy};changedView();};
function endPan(e){if(!drag||drag.id!==e.pointerId)return;suppressClick=drag.moved;drag=null;canvas.style.cursor='grab';if(canvas.hasPointerCapture(e.pointerId))canvas.releasePointerCapture(e.pointerId);}
canvas.onpointerup=endPan;canvas.onpointercancel=endPan;canvas.onlostpointercapture=e=>{if(drag?.id===e.pointerId){suppressClick=drag.moved;drag=null;canvas.style.cursor='grab';}};
canvas.ondblclick=e=>{if(inside(localPoint(e))){e.preventDefault();resetView();}};
canvas.onkeydown=e=>{if(!viewport)return;if(['+','=','-','0','Home','ArrowLeft','ArrowRight','ArrowUp','ArrowDown'].includes(e.key))e.preventDefault();if(e.key==='+'||e.key==='=')zoomCenter(.75);else if(e.key==='-')zoomCenter(1/.75);else if(e.key==='0'||e.key==='Home')resetView();else if(e.key.startsWith('Arrow')){const dx=(viewport.hi-viewport.lo)*.1,dy=(viewport.top-viewport.bottom)*.1,x=e.key==='ArrowRight'?dx:e.key==='ArrowLeft'?-dx:0,y=e.key==='ArrowUp'?dy:e.key==='ArrowDown'?-dy:0;viewport={lo:viewport.lo+x,hi:viewport.hi+x,bottom:viewport.bottom+y,top:viewport.top+y};changedView();}};
$('zoomIn').onclick=()=>zoomCenter(.75);$('zoomOut').onclick=()=>zoomCenter(1/.75);$('resetView').onclick=resetView;
async function load(){try{$('status').textContent='Reading retained catalogs…';let response=OFFLINE?{ok:true,json:async()=>JSON.parse($('atlasData').textContent)}:await fetch('/api/wing-atlas');atlas=await response.json();viewport=null;viewKey='';if(!response.ok)throw Error(atlas.error||'Catalog unavailable');for(let id of ['x','y','color'])$(id).innerHTML=Object.entries(atlas.metrics).map(([k,v])=>`<option value="${k}">${esc(v)}</option>`).join('');$('x').value='torque';$('y').value='thrust';$('color').value='span';$('cohort').innerHTML='<option value="all_single">All single-wing conditions · overview</option>'+atlas.cohorts.map(g=>`<option value="${g.id}">${esc(g.label)}</option>`).join('');$('study').innerHTML='<option value="">All retained studies</option>'+atlas.studies.map(s=>`<option value="${esc(s.id)}">${s.generation==='old'?'Old':'New'} · ${esc(s.name)}</option>`).join('');$('status').textContent=`${atlas.successful.toLocaleString()} successful simulations · ${atlas.single_count.toLocaleString()} single-wing · ${atlas.paired_count} legacy paired-wing · ${atlas.studies.length} retained studies. Exact repeated simulations are merged. ${atlas.snapshot_utc?'Snapshot: '+atlas.snapshot_utc+'. ':''}${atlas.note}`;render();}catch(e){$('status').textContent=e.message;}}
document.querySelectorAll('input,select').forEach(el=>el.addEventListener('change',render));window.addEventListener('resize',render);$('refresh').onclick=load;$('export').onclick=async()=>{if(OFFLINE){exportOfflineCsv();return;}let b=$('export'),exportVersion=version;b.disabled=true;$('exports').textContent='Preparing figure and source data…';try{let response=await fetch('/api/wing-atlas-plot',{method:'POST',headers:{'Content-Type':'application/json'},body:JSON.stringify(exportParams())}),data=await response.json();if(!response.ok)throw Error(data.error||'Export failed');if(exportVersion===version)$('exports').innerHTML=data.files.map(f=>`<a href="/files/${f.split('/').map(encodeURIComponent).join('/')}" download>${f.endsWith('.png')?'PNG figure':'Source CSV'}</a>`).join(' · ');}catch(e){$('exports').textContent=e.message;}finally{b.disabled=false;}};
function downloadBlob(blob,name){const url=URL.createObjectURL(blob),a=document.createElement('a');a.href=url;a.download=name;a.click();setTimeout(()=>URL.revokeObjectURL(url),1000);}
function csvCell(value){
 if(value===null||value===undefined)return '';
 let text=typeof value==='object'?JSON.stringify(value):String(value);
 if(typeof value==='string'&&/^[=+\-@\t\r]/.test(text))text="'"+text;
 return '"'+text.replace(/"/g,'""')+'"';
}
function viewCsv(){
 const p=exportParams(),rows=filtered(atlas,p),groups=new Map(atlas.cohorts.map(g=>[g.id,g.conditions]));
 const fields=['number','study','id','geometry_id','simulation_id','cohort','load_scope','settled',...Object.keys(atlas.metrics),'chords','sections','requested_sections','outline','generations','studies','locations','saved_conditions'];
 return '\ufeff'+[fields.map(csvCell).join(','),...rows.map(r=>fields.map(k=>csvCell(k==='saved_conditions'?groups.get(r.cohort):r[k])).join(','))].join('\r\n');
}
function exportOfflineCsv(){if(!viewRows.length){$('exports').textContent='No cases in the current view. Reset or pan back to the data.';return;}downloadBlob(new Blob([viewCsv()],{type:'text/csv;charset=utf-8'}),'wing_results_current_view.csv');}
function exportOfflinePng(){
 const source=$('plot'),dpr=window.devicePixelRatio||1,out=document.createElement('canvas'),extra=115*dpr;
 out.width=source.width;out.height=source.height+extra;
 const ctx=out.getContext('2d');ctx.fillStyle='#fff';ctx.fillRect(0,0,out.width,out.height);ctx.drawImage(source,0,50*dpr);ctx.scale(dpr,dpr);ctx.fillStyle='#19343f';ctx.font='14px Segoe UI';
 ctx.fillText(`${viewRows.length.toLocaleString()} simulations · offline wing results`,35,24);
 const y=source.height/dpr+70;for(let i=0;i<240;i++){ctx.fillStyle=palette(i/239);ctx.fillRect(70+i,y,1,10);}
 ctx.fillStyle='#19343f';ctx.font='11px Segoe UI';ctx.fillText($('legendText').textContent,70,y+28);
 ctx.fillText(`Snapshot ${atlas.snapshot_utc||'unknown'} · ${new Set(viewRows.map(r=>r.cohort)).size>1?'Mixed conditions overview':'Saved conditions group'}`,70,y+43);
 out.toBlob(blob=>{if(blob)downloadBlob(blob,'wing_results_current_view.png');},'image/png');
}
if(OFFLINE){
 $('export').textContent='Export current view · CSV';
 $('offlinePng').classList.remove('hidden');$('offlinePng').onclick=exportOfflinePng;
 $('offlineJson').classList.remove('hidden');$('offlineJson').onclick=()=>downloadBlob(new Blob([JSON.stringify(atlas)],{type:'application/json'}),'all_wings_data.json');
}
if($('shareAtlas'))$('shareAtlas').onclick=async()=>{
 const button=$('shareAtlas');button.disabled=true;$('shareResult').textContent='Packaging all retained wing results…';
 try{const response=await fetch('/api/wing-atlas-package',{method:'POST',headers:{'Content-Type':'application/json'},body:'{}'}),out=await response.json();if(!response.ok)throw Error(out.error||'Packaging failed');$('shareResult').innerHTML=`<a href="/files/${out.file.split('/').map(encodeURIComponent).join('/')}" download>Download offline ZIP · ${(out.bytes/1e6).toFixed(2)} MB · ${out.cases.toLocaleString()} wings</a>`;}catch(e){$('shareResult').textContent=e.message;}finally{button.disabled=false;}
};

load();
