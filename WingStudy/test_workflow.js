const fs=require('fs'),vm=require('vm'),assert=require('assert');
const source=fs.readFileSync(__dirname+'/workflow.js','utf8');
const values={studyName:'Screen',maximumMoment:'.5',flapMinimum:'-26',flapMaximum:'34',frequency:'1',speed:'.5',totalSpan:'.6',nodeCount:'2',decreasing:''};
const inputs=Object.fromEntries(Object.entries(values).map(([id,value])=>[id,{value,checked:id==='decreasing'}]));
Object.assign(inputs,{resultsLimit:{value:'.5'},exportComparison:{},winnerBody:{},rankedRows:{},exportLinks:{}});
const context={structuredClone,$:id=>inputs[id],defaults:{settings:{}},baseConfig:{settings:{aeroelastic_enabled:true},tail:{enabled:true}},numerical:{},baseline:null,
 readRanges:()=>[{min_m:.1,max_m:.1,count:1},{min_m:.05,max_m:.05,count:1}]};
vm.createContext(context);vm.runInContext(source.slice(source.indexOf('function configuration('),source.indexOf('function fill(')),context);
const c=context.configuration();assert.equal(c.workflow,'root_torque');assert.equal(c.optimization.max_root_moment_nm,.5);
assert.equal(c.settings.aeroelastic_enabled,false);assert.equal(c.tail.enabled,false);assert.equal(c.settings.max_root_moment_nm,undefined);
assert.equal(c.motion_range.minimum_deg,-26);assert.equal(c.motion_range.maximum_deg,34);assert.equal(c.settings.frequency_hz,1);
assert.equal(context.baseConfig.settings.aeroelastic_enabled,true);
const requests=[],payloads=[];context.api=(path,data)=>new Promise(resolve=>{payloads.push({path,data});requests.push(resolve);});let renders=0;context.renderResults=()=>renders++;
context.esc=String;vm.runInContext("let currentStudy='a',resultSerial=0,report=null,exportBusy=false;"+source.slice(source.indexOf('async function evaluate('),source.indexOf('function links(')),context);
(async()=>{
 const first=context.evaluate();vm.runInContext("currentStudy='b'",context);const second=context.evaluate();
 requests[1]({winner:{id:'b'}});await second;requests[0]({winner:{id:'a'}});await first;
 assert.equal(vm.runInContext('report.winner.id',context),'b');assert.equal(renders,1);
 assert.equal(requests.length,2);
 Object.assign(inputs,{currentMaster:{checked:true},oldMaster:{checked:false},currentCount:{},oldCount:{}});
 vm.runInContext("currentStudy='master'",context);
 const current=context.evaluate();assert.equal(payloads[2].path,'master-results');assert.deepEqual(Array.from(payloads[2].data.generations),['current']);
 requests[2]({generations:{current:0,old:12}});await current;assert.equal(inputs.oldCount.textContent,'(12 cases)');
 inputs.oldMaster.checked=true;const both=context.evaluate();assert.deepEqual(Array.from(payloads[3].data.generations),['current','old']);requests[3]({});await both;
 inputs.currentMaster.checked=false;inputs.oldMaster.checked=false;const neither=context.evaluate();assert.equal(payloads[4].data.generations.length,0);requests[4]({});await neither;
 vm.runInContext(source.slice(source.indexOf('function links('),source.indexOf('function values(')),context);
 assert(context.links({status:'ok',id:'case_0001',_study:'original-study'}).includes('/files/original-study/case_0001/'));
 console.log('19 workflow configuration, master toggles, source links and stale-response checks passed.');
})().catch(error=>{console.error(error);process.exitCode=1;});
