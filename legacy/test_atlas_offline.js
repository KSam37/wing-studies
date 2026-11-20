// Execute the actual exported HTML's embedded scripts with no network available.
const fs=require('fs'),vm=require('vm'),assert=require('assert');
async function main(){
 const page=fs.readFileSync(process.argv[2],'utf8');
 const payload=page.match(/<script type="application\/json" id="atlasData">([\s\S]*?)<\/script>/)[1];
 const script=page.match(/<script>globalThis.WING_ATLAS_OFFLINE=true;([\s\S]*?)<\/script>/)[1];
 const expected=JSON.parse(payload),nodes=new Map(),downloads=[],blobs=new Map();let networkCalls=0;
 const paint=new Proxy({},{get:(o,k)=>o[k]||(()=>{})});
 function node(id){if(!nodes.has(id))nodes.set(id,{value:'',checked:true,innerHTML:'',textContent:'',clientWidth:1000,style:{},classList:{add(){},remove(){},toggle(){}},events:{},querySelectorAll:()=>[],getContext:()=>paint,addEventListener(k,fn){this.events[k]=fn;},getBoundingClientRect:()=>({left:0,top:0}),focus(){},setPointerCapture(){},hasPointerCapture:()=>true,releasePointerCapture(){}});return nodes.get(id);}
 node('atlasData').textContent=payload;
 for(const [k,v] of Object.entries({cohort:'all_single',study:'',mode:'points',silhouettes:'24',normalized:'false'}))node(k).value=v;
 const sandbox={WING_ATLAS_OFFLINE:true,document:{getElementById:node,querySelectorAll:()=>[],createElement:()=>({click(){downloads.push({name:this.download,blob:blobs.get(this.href)});}})},window:{devicePixelRatio:1,addEventListener(){}},console,Blob,setTimeout(){},URL:{createObjectURL(blob){let key='blob:'+blobs.size;blobs.set(key,blob);return key;},revokeObjectURL(){}},fetch(){networkCalls++;throw Error('Network is unavailable in the portable viewer');}};
 vm.createContext(sandbox);vm.runInContext(script,sandbox);await new Promise(setImmediate);
 assert.equal(networkCalls,0);assert.equal(vm.runInContext('atlas.rows.length',sandbox),expected.rows.length);
 assert.equal(vm.runInContext('positions.length',sandbox),expected.single_count);
 assert.equal(node('export').textContent,'Export current view · CSV');
 vm.runInContext('detail(atlas.rows[0])',sandbox);
 assert(node('detail').innerHTML.includes('Offline snapshot'));
 assert(!node('detail').innerHTML.includes('/files/'));assert(!node('detail').innerHTML.includes('href="/?refine'));
 const width=vm.runInContext('viewport.hi-viewport.lo',sandbox);
 node('zoomIn').onclick();assert(vm.runInContext('viewport.hi-viewport.lo',sandbox)<width);
 node('resetView').onclick();assert.equal(vm.runInContext('positions.length',sandbox),expected.single_count);
 node('export').onclick();const csv=await downloads[0].blob.text();assert.equal(downloads[0].name,'wing_results_current_view.csv');
 assert.equal(csv.trim().split('\r\n').length,expected.single_count+1);assert(csv.includes('sections'));assert(csv.includes('saved_conditions'));assert(csv.includes('rho'));
 node('offlineJson').onclick();const data=JSON.parse(await downloads[1].blob.text());
 assert.equal(data.rows.length,expected.rows.length);assert.deepEqual(data.rows[0].sections,expected.rows[0].sections);
 node('span_min').value='.3';vm.runInContext('render()',sandbox);
 assert(vm.runInContext('visible.every(r=>r.span>=.3)',sandbox));
 assert.equal(networkCalls,0);
 assert.equal(vm.runInContext('csvCell("=1+1")',sandbox),'"\'=1+1"');
 console.log(`Offline HTML passed: ${expected.rows.length} cases, no network calls, zoom/reset, filters, wing inspection, complete CSV and JSON downloads.`);
}
main().catch(e=>{console.error(e);process.exitCode=1;});
