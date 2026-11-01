const fs=require('fs'),vm=require('vm'),assert=require('assert');
const nodes=new Map();const node=id=>{if(!nodes.has(id))nodes.set(id,{value:'',innerHTML:'',textContent:'',querySelectorAll:()=>[]});return nodes.get(id);};
const checked=[{dataset:{study:'a'}},{dataset:{study:'b'}}];
const context={document:{getElementById:node,querySelectorAll:()=>checked},console,setInterval,clearInterval};vm.createContext(context);
vm.runInContext(fs.readFileSync(__dirname+'/lambda_review.js','utf8').replace(/\ninit\(\);\s*$/,''),context);
const data={studies:[{id:'a',color:'#0072B2'},{id:'b',color:'#009E73'}],comparable:true,rows:[
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
console.log('Lambda comparison: live filters, tie-breaking, boundaries, scope, and final/earlier borders passed.');
