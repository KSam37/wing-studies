const fs=require('fs'),vm=require('vm'),assert=require('assert');
const nodes=new Map();const node=id=>{if(!nodes.has(id))nodes.set(id,{value:'',innerHTML:'',textContent:'',classList:{add(){}},querySelectorAll:()=>[]});return nodes.get(id);};
const checked=[{dataset:{study:'a'}},{dataset:{study:'b'}}];
const context={document:{getElementById:node,querySelectorAll:()=>checked},console,setInterval,clearInterval};vm.createContext(context);
vm.runInContext(fs.readFileSync(__dirname+'/lambda_review.js','utf8').replace(/\ninit\(\);\s*$/,''),context);
const data={studies:[{id:'a',lambda_value:.75,color:'#0072B2'},{id:'b',lambda_value:1.75,color:'#009E73'}],comparable:true,rows:[
{id:'seed',study:'a',lambda_value:.75,single_wing_mean_thrust_N:1,single_wing_peak_abs_roll_moment_Nm:.25,is_accepted:true,is_final:false,simulation_id:'same',outline_m:[[0,0],[.2,0],[0,.1]]},
{id:'trial',study:'a',lambda_value:.75,single_wing_mean_thrust_N:3,single_wing_peak_abs_roll_moment_Nm:.4,is_accepted:false,is_final:false,simulation_id:'trial',outline_m:[[0,0],[.2,0],[0,.1]]},
{id:'best',study:'b',lambda_value:1.75,single_wing_mean_thrust_N:3,single_wing_peak_abs_roll_moment_Nm:.38,is_accepted:true,is_final:true,simulation_id:'best',outline_m:[[0,0],[.2,0],[0,.1]]},
{id:'edge',study:'b',lambda_value:1.75,single_wing_mean_thrust_N:4,single_wing_peak_abs_roll_moment_Nm:.5,is_accepted:true,is_final:false,simulation_id:'edge',outline_m:[[0,0],[.2,0],[0,.1]]}]};
context.input=data;vm.runInContext('saved=input;selected={};',context);
for(const [k,v] of Object.entries({scope:'all',minimum:'0',maximum:'.75',bandWidth:'.25',wingSize:'100'}))node(k).value=v;
vm.runInContext('render()',context);assert.equal(vm.runInContext('current.ws.length',context),2);assert.equal(vm.runInContext('current.ws[0].id',context),'best');
assert(node('wingPlot').innerHTML.includes('stroke="#000"'));assert(node('wingPlot').innerHTML.includes('stroke="#b0b0b0"'));
node('bandWidth').value='.5';vm.runInContext('render()',context);assert.equal(vm.runInContext('current.ws.length',context),2);
node('maximum').value='.49';vm.runInContext('render()',context);assert.equal(vm.runInContext('current.ws.length',context),1);
node('scope').value='final';vm.runInContext('render()',context);assert.equal(vm.runInContext('current.rows.length',context),1);
node('bandWidth').value='0';vm.runInContext('render()',context);assert(node('status').textContent.includes('positive band width'));
node('bandWidth').value='.25';node('maximum').value='.75';node('scope').value='all';
vm.runInContext('render()',context);assert.equal(vm.runInContext('current.series.length',context),3);assert.equal(vm.runInContext('current.series.filter(r=>r.study==="a").length',context),1);assert.equal(vm.runInContext('current.series.filter(r=>r.study==="b").length',context),2);
context.paths=[{study:'a',lambda_value:.75,job:1,family:'triangle',starting_total_span_m:.4,steps:1,points:[{id:'seed',thrust:1,torque:.25,outline_m:data.rows[0].outline_m},{id:'trial',thrust:3,torque:.4,outline_m:data.rows[1].outline_m}]},{study:'a',lambda_value:.75,job:2,family:'square',starting_total_span_m:.8,steps:0,points:[{id:'seed',thrust:1,torque:.25,outline_m:data.rows[0].outline_m}]},{study:'b',lambda_value:1.75,job:1,family:'convex',starting_total_span_m:.8,steps:0,points:[{id:'best',thrust:3,torque:.38,outline_m:data.rows[2].outline_m}]}];
vm.runInContext('saved.lineages=paths;',context);node('lineage').value='0';node('evolutionSpan').value='all';node('evolutionStages').value='ends';vm.runInContext('evolution()',context);assert(node('evolutionPlots').innerHTML.includes('2 independent seeds'));assert(node('evolutionPlots').innerHTML.includes('1 independent seeds'));assert.equal((node('evolutionPlots').innerHTML.match(/<polyline/g)||[]).length,3);assert(node('evolutionPlots').innerHTML.includes('Final shapes at a common physical scale'));
node('evolutionSpan').value='0.4';vm.runInContext('evolution()',context);assert.equal((node('evolutionPlots').innerHTML.match(/<polyline/g)||[]).length,1);
console.log('Lambda comparison: live filters, tie-breaking, boundaries, scope, and final/earlier borders passed.');
