const fs=require('fs'),vm=require('vm'),assert=require('assert');
const source=fs.readFileSync(__dirname+'/workflow.js','utf8');
const values={searchMode:'adaptive',studyName:'Adaptive',maximumMoment:'.625',flapMinimum:'-26',flapMaximum:'34',frequency:'1',speed:'.5',adaptiveSpanMin:'.6',adaptiveSpanMax:'.8',adaptiveSpanCount:'3',adaptiveNodes:'3',adaptiveRoot:'.2',adaptiveRootMax:'.2',adaptiveTip:'.01',adaptiveChordMin:'.01',adaptiveChordMax:'.2',adaptiveStep:'.01',adaptiveMinStep:'.001',adaptiveShrink:'.5',adaptiveImprovement:'.2',adaptiveTorqueMin:'.2',adaptiveTorqueMax:'1.2',adaptiveTorqueCount:'4',adaptiveBudget:'100',adaptiveEvaluations:'500',adaptivePasses:'20',adaptiveParents:'8',adaptiveWorkers:'4',adaptivePollCandidates:'8',curveTorqueMin:'',curveTorqueMax:'',curveTorqueSamples:'12'};
const inputs=Object.fromEntries(Object.entries(values).map(([k,value])=>[k,{value}]));
inputs.adaptiveDecreasing={checked:true};inputs.adaptivePaired={checked:true};inputs.adaptiveCoordinated={checked:true};
const rows=Array.from({length:3},()=>({querySelectorAll:()=>[{dataset:{key:'min_m'},value:'.01'},{dataset:{key:'max_m'},value:'.2'},{dataset:{key:'step_m'},value:'.01'}]}));
inputs.adaptiveBounds={querySelectorAll:()=>rows};
const ctx={$:id=>inputs[id],structuredClone,baseConfig:{settings:{},refinement:{enabled:true},span_search:{enabled:true}},defaults:{settings:{}},numerical:{},baseline:null,refinementActive:false};
vm.createContext(ctx);vm.runInContext(source.slice(source.indexOf('const adaptiveFields='),source.indexOf('function fill(')),ctx);
const c=ctx.configuration();assert.equal(c.mode,'custom');assert.equal(c.adaptive_search.enabled,true);assert.equal(c.adaptive_search.node_count,3);assert.equal(c.adaptive_search.bounds.length,3);assert.equal(c.adaptive_search.simulation_budget,100);assert.equal(c.adaptive_search.span_count,3);assert.equal(c.refinement,undefined);assert.equal(c.span_search,undefined);assert.equal(c.settings.aeroelastic_enabled,false);
inputs.adaptiveElastic={checked:true};inputs.nativeStiffness={value:'4.27'};inputs.nativeDamping={value:'10'};inputs.nativeMass={value:'.5'};inputs.nativeHold={value:'5'};
const elastic=ctx.configuration();assert.equal(elastic.settings.aeroelastic_enabled,true);assert.equal(elastic.settings.damping_constant_rad,10);assert.equal(elastic.settings.spring_constant_rad,4.27);assert.equal(elastic.settings.wing_density,.5);
assert.equal(c.optimization.constraint,'peak_root_torque_le_available_target');assert.equal(c.optimization.max_root_moment_nm,undefined);assert.equal(c.workflow,'adaptive_pareto');assert.equal(c.adaptive_search.torque_max_nm,undefined);
inputs.adaptiveNodes.value='4';assert.throws(()=>ctx.configuration(),/Build/);
console.log('Adaptive configuration, per-node bounds, shared budgets and node-reset checks passed.');

inputs.adaptiveNodes.value='3';inputs.adaptiveChordMax.value='';rows.forEach(r=>r.querySelectorAll=()=>[{dataset:{key:'min_m'},value:'.01'},{dataset:{key:'max_m'},value:''},{dataset:{key:'step_m'},value:'.01'}]);assert.equal(ctx.configuration().adaptive_search.maximum_chord_m,null);assert.equal(ctx.configuration().adaptive_search.bounds[0].max_m,null);assert.equal(ctx.configuration().adaptive_search.maximum_root_chord_m,.2);

assert.equal(ctx.configuration().adaptive_search.coordinated_moves,true);inputs.adaptiveCoordinated.checked=false;assert.equal(ctx.configuration().adaptive_search.coordinated_moves,false);

assert.equal(ctx.configuration().adaptive_search.parallel_workers,4);

assert.equal(c.adaptive_search.budget_only,true);assert.equal(c.adaptive_search.max_passes,undefined);assert.equal(c.adaptive_search.evaluation_budget,undefined);assert.equal(c.adaptive_search.poll_candidates,undefined);

const families=['triangle','square','concave','convex','narrow'].map(value=>({value,checked:true}));
inputs.adaptiveFamilies={querySelectorAll:selector=>selector==='input:checked'?families.filter(f=>f.checked):families};
assert.deepEqual(Array.from(ctx.configuration().adaptive_search.seed_families),families.map(f=>f.value));
families[1].checked=false;
assert.deepEqual(Array.from(ctx.configuration().adaptive_search.seed_families),['triangle','concave','convex','narrow']);
families.forEach(f=>f.checked=false);families[0].checked=true;families[4].checked=true;
assert.deepEqual(Array.from(ctx.configuration().adaptive_search.seed_families),['triangle','narrow']);
families.forEach(f=>f.checked=false);assert.throws(()=>ctx.configuration(),/Select at least one/);
console.log('Independent seed checkboxes preserve multiple families and validate empty selection.');

assert.equal(c.adaptive_search.acceptance_rule,'torque_curve');assert.equal(c.adaptive_search.curve_torque_min_nm,null);assert.equal(c.adaptive_search.curve_torque_samples,12);
