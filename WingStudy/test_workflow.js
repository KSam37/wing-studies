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
const requests=[];context.api=()=>new Promise(resolve=>requests.push(resolve));let renders=0;context.renderResults=()=>renders++;
context.esc=String;vm.runInContext("let currentStudy='a',resultSerial=0,report=null,exportBusy=false;"+source.slice(source.indexOf('async function evaluate('),source.indexOf('function links(')),context);
(async()=>{
 const first=context.evaluate();vm.runInContext("currentStudy='b'",context);const second=context.evaluate();
 requests[1]({winner:{id:'b'}});await second;requests[0]({winner:{id:'a'}});await first;
 assert.equal(vm.runInContext('report.winner.id',context),'b');assert.equal(renders,1);
 assert.equal(requests.length,2);
 console.log('12 focused-workflow configuration and stale-response checks passed.');
})().catch(error=>{console.error(error);process.exitCode=1;});
