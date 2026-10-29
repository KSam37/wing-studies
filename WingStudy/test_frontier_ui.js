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
