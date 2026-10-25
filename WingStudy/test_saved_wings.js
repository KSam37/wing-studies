const fs=require('fs'),vm=require('vm'),assert=require('assert');
const source=fs.readFileSync(__dirname+'/ui.js','utf8');
const inputs={studyMode:{value:'shape_sweep'},customEditor:{scrollIntoView(){}}};
const context={structuredClone,$:key=>inputs[key],renderEditor(){},modeChanged(){},tab(){},preview(){},notify(){}};
vm.createContext(context);
vm.runInContext('let customDesigns=[{name:"Keep existing wing"}],editingDesign=-1,draft;'+source.slice(source.indexOf('function savedWingDesign('),source.indexOf('function savedWingOptions(')),context);
const row={design_name:'Bent wing',sections:[
 {y_m:0,x_m:0,chord_m:.2,pitch_deg:8,roll_deg:20},
 {y_m:.3,x_m:.04,chord_m:.1,pitch_deg:-3,roll_deg:-10}]};
const original=JSON.stringify(row),design=context.savedWingDesign(row);
assert.equal(JSON.stringify(design.sections),JSON.stringify(row.sections));
assert.equal(design.name,'Bent wing copy');
design.sections[1].chord_m=.08;assert.equal(JSON.stringify(row),original);
const legacy=context.savedWingDesign({id:'case_0001',incidence_deg:6,geometry:{stations:[
 {y_m:0,x_m:0,chord_m:.2},{y_m:.4,x_m:.1,chord_m:.05}]}});
assert.equal(legacy.sections[1].y_m,.4);assert.equal(legacy.sections[1].x_m,.1);
assert.equal(legacy.sections[1].pitch_deg,6);assert.equal(legacy.sections[1].roll_deg,0);
context.copySavedWing(row);
assert.equal(vm.runInContext('customDesigns.length',context),2);
assert.equal(vm.runInContext('customDesigns[0].name',context),'Keep existing wing');
assert.equal(vm.runInContext('editingDesign',context),1);assert.equal(inputs.studyMode.value,'custom');
vm.runInContext('draft.sections[0].chord_m=.9',context);
assert.equal(vm.runInContext('customDesigns[1].sections[0].chord_m',context),.2);
context.copySavedWing({sections:[]});assert.equal(vm.runInContext('customDesigns.length',context),2);
assert.throws(()=>context.savedWingDesign({sections:[{y_m:0},{y_m:1}]}),/incomplete/);
console.log('14 saved-wing geometry and copy checks passed.');
const wing={name:'Custom gull',sections:row.sections},template=context.wingSweepTemplate(wing,.04);
assert.equal(template.span_m,.64);assert.equal(template.chord_count,2);
assert.equal(JSON.stringify(template.baseline.sections),JSON.stringify(wing.sections));
assert.equal(JSON.stringify(template.ranges),JSON.stringify([{min_m:.2,max_m:.2,count:1},{min_m:.1,max_m:.1,count:1}]));
template.baseline.sections[0].roll_deg=0;assert.equal(wing.sections[0].roll_deg,20);
assert.equal(context.wingSweepTemplate({name:'Increasing',sections:[{y_m:0,chord_m:.1},{y_m:.2,chord_m:.2}]},.04).decreasing,false);
console.log('6 custom-wing sweep template checks passed.');
