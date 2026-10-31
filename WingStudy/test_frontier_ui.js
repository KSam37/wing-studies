const fs=require('fs'),vm=require('vm'),assert=require('assert');
const source=fs.readFileSync(__dirname+'/workflow.js','utf8');
const inputs={frontierTorque:{value:'.4'},frontierTorqueValue:{},frontierWing:{},frontierPoint:{},frontierResult:{},frontierStatus:{},makeFrontier:{},currentMaster:{checked:true},oldMaster:{checked:false}};
const ctx={$:id=>inputs[id],fmt:String,esc:String,outline:()=>'<svg/>',currentStudy:'master',selectedSpanClass:'all'};
vm.createContext(ctx);
vm.runInContext(source.slice(source.indexOf('let frontierSerial='),source.indexOf("$('makeFrontier').onclick=")),ctx);
vm.runInContext("frontierData={points:[{id:'a',single_wing_peak_abs_roll_moment_Nm:.2,single_wing_mean_thrust_N:1},{id:'b',single_wing_peak_abs_roll_moment_Nm:.6,single_wing_mean_thrust_N:3}]}",ctx);
ctx.inspectFrontier();assert(inputs.frontierWing.innerHTML.includes('a'));assert.equal(inputs.frontierPoint.value,0);
inputs.frontierTorque.value='.6';ctx.inspectFrontier();assert(inputs.frontierWing.innerHTML.includes('b'));assert.equal(inputs.frontierPoint.value,1);
inputs.frontierTorque.value='0.19999999999999998';ctx.inspectFrontier();assert.equal(inputs.frontierPoint.value,0);
inputs.frontierTorque.value='.1';ctx.inspectFrontier();assert(inputs.frontierWing.innerHTML.includes('No eligible'));
ctx.checkFrontierSelection();inputs.frontierResult.innerHTML='keep';ctx.checkFrontierSelection();assert.equal(inputs.frontierResult.innerHTML,'keep');
inputs.oldMaster.checked=true;ctx.checkFrontierSelection();assert.equal(inputs.frontierResult.innerHTML,'');
console.log('Frontier slider, exact boundaries, no-feasible state and source-change checks passed.');

vm.runInContext("frontierData={comparison_mode:'bands',points:[{id:'winner',torque_band_min_nm:0,torque_band_max_nm:1,torque_band_count:12,single_wing_peak_abs_roll_moment_Nm:.8,single_wing_mean_thrust_N:3}]}",ctx);inputs.frontierPoint.value='0';inputs.frontierTorque.value='0';ctx.inspectFrontier();assert(inputs.frontierWing.innerHTML.includes('winner'));assert(inputs.frontierWing.innerHTML.includes('12 evaluated'));assert(inputs.frontierWing.innerHTML.includes('Highest observed'));

const plot={innerHTML:''};const plotCtx={$:()=>plot,fmt:String,esc:String,document:{querySelectorAll:()=>[]}};
vm.createContext(plotCtx);vm.runInContext(source.slice(source.indexOf('function mountFrontierPlot('),source.indexOf('function drawPreview(')),plotCtx);
plotCtx.mountFrontierPlot({minimum_torque_nm:0,plot_maximum_torque_nm:2,comparison_mode:'evolution',displayed:[{id:'wing',outline_m:[[0,0],[.2,0],[.2,.1]],single_wing_mean_thrust_N:1,single_wing_peak_abs_roll_moment_Nm:1}],evolution_paths:[{points:[{torque_Nm:1.5,thrust_N:.5},{torque_Nm:1,thrust_N:1}]}]});
assert(plot.innerHTML.includes('stroke-dasharray="6 4"'));
assert(plot.innerHTML.indexOf('<polyline')<plot.innerHTML.indexOf('class="plot-wing"'));
assert(plot.innerHTML.includes('666.75,')); // First ancestor stays first even with higher torque.
console.log('Dashed ancestry renders behind wings without sorting by torque.');

assert(!plot.innerHTML.includes('stroke="#000000"'));
const shape={outline_m:[[0,0],[.2,0],[.2,.1]],single_wing_mean_thrust_N:1,single_wing_peak_abs_roll_moment_Nm:1,is_frontier:true};
plotCtx.mountFrontierPlot({minimum_torque_nm:0,plot_maximum_torque_nm:2,displayed:[{...shape,id:'earlier'},{...shape,id:'final',is_final_evolution:true}]});
assert.equal((plot.innerHTML.match(/stroke="#000000"/g)||[]).length,1);
assert(plot.innerHTML.includes('stroke="#b0b0b0" stroke-width="1"'));
let scheduled=null,regenerations=0;
ctx.clearTimeout=()=>{scheduled=null;};ctx.setTimeout=callback=>{scheduled=callback;return 1;};
for(const id of ['frontierMin','frontierMax','frontierBandWidth','frontierSize','frontierSpacing','frontierFamily','frontierColor','frontierSeeds'])inputs[id]={value:''};
inputs.frontierMode={value:'bands'};inputs.frontierBandWidth.value='.5';inputs.makeFrontier.onclick=()=>{regenerations++;};
vm.runInContext(source.slice(source.indexOf('function scheduleFrontierUpdate('),source.indexOf('let landscapeSerial=')),ctx);
inputs.frontierResult.innerHTML='existing plot';inputs.frontierBandWidth.oninput();assert.equal(inputs.frontierResult.innerHTML,'existing plot');assert(scheduled);scheduled();assert.equal(regenerations,1);
inputs.frontierBandWidth.value='0';scheduled=null;inputs.frontierBandWidth.oninput();assert.equal(scheduled,null);assert(inputs.frontierStatus.textContent.includes('Previous plot'));
inputs.frontierBandWidth.value='.25';inputs.frontierMin.value='.2';inputs.frontierMax.value='1.2';inputs.frontierMax.oninput();assert(scheduled);scheduled();assert.equal(regenerations,2);
console.log('Final states have black outlines; earlier states have light grey outlines; band width and torque limits regenerate automatically.');
