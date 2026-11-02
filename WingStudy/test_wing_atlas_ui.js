const fs=require('fs'),vm=require('vm'),assert=require('assert');
const nodes=new Map(),ctx=new Proxy({},{get:(o,k)=>o[k]||(()=>{})});
function node(id){if(!nodes.has(id))nodes.set(id,{value:'',checked:true,innerHTML:'',textContent:'',clientWidth:950,style:{},classList:{add(){},toggle(){}},querySelectorAll:()=>[],getContext:()=>ctx,addEventListener(){}});return nodes.get(id);}
const sandbox={document:{getElementById:node,querySelectorAll:()=>[]},window:{devicePixelRatio:1,addEventListener(){}},console};vm.createContext(sandbox);
vm.runInContext(fs.readFileSync(__dirname+'/wing_atlas.js','utf8').replace(/\nload\(\);\s*$/,''),sandbox);
sandbox.fixture={metrics:{torque:'Torque',thrust:'Thrust',span:'Span'},cohorts:[{id:'a',conditions:{load_scope:'single'}}],studies:[],rows:Array.from({length:300},(_,i)=>({number:i,key:String(i),cohort:'a',load_scope:'single',generations:['old','current'],studies:['oldstudy','newstudy'],span:.2,root:.1,torque:i*.01,thrust:Math.sqrt(i),outline:[[0,0],[.2,0],[.2,.01],[0,.1]],chords:[.1,.01],locations:[]}))};
for(const [k,v] of Object.entries({cohort:'all_single',x:'torque',y:'thrust',color:'span',mode:'points',silhouettes:'24',normalized:'false'}))node(k).value=v;
vm.runInContext('atlas=fixture;render()',sandbox);
assert.equal(vm.runInContext('positions.length',sandbox),300);assert(vm.runInContext('chosen.length<=24',sandbox));assert(node('plotTitle').textContent.includes('300'));
node('xmin').value='1';node('xmax').value='2';vm.runInContext('render()',sandbox);assert.equal(vm.runInContext('visible.length',sandbox),101);
node('old').checked=false;vm.runInContext('render()',sandbox);assert.equal(vm.runInContext('visible.length',sandbox),101);
node('current').checked=false;vm.runInContext('render()',sandbox);assert.equal(vm.runInContext('visible.length',sandbox),0);
node('current').checked=true;node('mode').value='density';vm.runInContext('render()',sandbox);assert.equal(vm.runInContext('positions.length',sandbox),101);
node('xmin').value='3';vm.runInContext('render()',sandbox);assert(node('warning').textContent.includes('minimum'));
assert(fs.readFileSync(__dirname+'/wing_atlas.js','utf8').includes('href="/files/'));
console.log('Atlas UI: all points, filters, source aliases, density and export routes passed.');
