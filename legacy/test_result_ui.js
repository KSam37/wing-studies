const fs=require('fs'),vm=require('vm'),assert=require('assert');
const source=fs.readFileSync(__dirname+'/workflow.js','utf8');
const ctx={currentStudy:'selected',studies:[{id:'adaptive-old',config:{adaptive_search:{enabled:true}}},{id:'adaptive-new',config:{adaptive_search:{enabled:true}}}]};
vm.createContext(ctx);vm.runInContext(source.slice(source.indexOf('function evolutionSource('),source.indexOf('function renderResults(')),ctx);
assert.equal(ctx.evolutionSource({id:'case_0001'}),null);
assert.equal(ctx.evolutionSource({id:'case_0001',adaptive_trial:{}}).study,'selected');
const selected=ctx.evolutionSource({id:'case_0001',_study:'original-grid',occurrences:[{study:'adaptive-old',local_case:'case_0003'},{study:'adaptive-new',local_case:'case_0007'}]});
assert.equal(selected.study,'adaptive-old');assert.equal(selected.case,'case_0003');
console.log('Recorded evolution source and reused-case provenance checks passed.');
