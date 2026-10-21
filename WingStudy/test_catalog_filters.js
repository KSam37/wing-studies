/* Run with Node for pure catalog-filter regression checks; no browser needed. */
const fs=require('fs'),vm=require('vm'),assert=require('assert');
const context={shapeObjective:'ratio'};vm.createContext(context);
const source=fs.readFileSync(__dirname+'/catalog-ui.js','utf8').split('\ninstallMasterCatalog();')[0];
vm.runInContext(source,context);
const base={global_case_no:7,_study:'original',occurrences:[{study:'reused'}],_settings:{frequency_hz:0},simulation_mode:'isolated_single_wing_v1',status:'ok',shape_ratio_valid:true,ratio:2,area_m2:.1,aspect_ratio:2,_verified:true};
const filters={studies:[],ids:[],isolated:true,repeat:false,valid:true,verified:false,query:'',waveform:'',wake:'',ranges:[]};
const match=(r,f)=>context.masterMatches(r,{...filters,...f});
assert(match(base,{studies:['reused']}));assert(!match(base,{studies:['other']}));
assert(match(base,{ids:[7]}));assert(!match(base,{ids:[8]}));
assert(match(base,{ranges:[['frequency_hz',0,0]]}));assert(!match(base,{ranges:[['frequency_hz',.1,null]]}));
assert(match(base,{ranges:[['area_m2',.1,.1]]}));assert(!match(base,{ranges:[['missing',0,null]]}));
assert(match(base,{ranges:[['missing',null,null]]}));
assert(!match({...base,status:'failed'},{}));assert(!match({...base,ratio:null},{}));
assert(!match({...base,cycle_repeatable:false},{repeat:true}));assert(!match({...base,_verified:false},{verified:true}));
assert(match(base,{query:'reused'}));
console.log('14 catalog filter checks passed.');
