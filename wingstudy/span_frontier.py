"""Resumable, matched span-flex evaluation of an exported atlas frontier.
Plan first; execute explicitly with --run. No source studies are modified.
"""
import argparse, hashlib, json, os, re, time, math, sqlite3
from pathlib import Path
from concurrent.futures import ProcessPoolExecutor, wait, FIRST_COMPLETED
from . import span_atlas as A

HERE=Path(__file__).resolve().parent
ROOT=HERE.parent

def fingerprint():
    from . import identity
    return identity.structural_fingerprint()

def atomic(path,data):
    tmp=path.with_suffix(path.suffix+'.tmp');tmp.write_text(json.dumps(data,indent=1,allow_nan=False),encoding='utf8');os.replace(tmp,path)

def frontier(indices,c):
    best=float('-inf');out=[]
    for i in sorted(indices,key=lambda i:(c['Q'][i],-c['T'][i],i)):
        if c['T'][i]>best:out.append(i);best=c['T'][i]
    return out

def make_plan(scope):
    page=(A.ATLAS/'index.html').read_text(encoding='utf8')
    d=json.loads(re.search(r'<script[^>]*type="application/json"[^>]*>(.*?)</script>',page,re.S)[1]);c=d['cols']
    groups={};end=d.get('catalog',{}).get('first',len(c['s']))
    for i in range(end):
        mid=d['models'][c['m'][i]]['id']
        if scope=='bare' and mid!='t0.50':continue
        if d['statuses'][c['S'][i]] not in ('ok','verified'):continue
        if c['T'][i] is None or c['Q'][i] is None:continue
        groups.setdefault((mid,c['f'][i]),[]).append(i)
    records={};counts={}
    for (mid,fi),ix in groups.items():
        selected=frontier(ix,c);counts[mid+' / '+str(d['freqs'][fi])+' Hz']=len(selected)
        for i in selected:
            chords=c['C'][8*i:8*i+8];positive=[x for x in chords if x>0]
            if len(positive)<2 or chords[:len(positive)]!=positive:raise ValueError('Unsupported disconnected outline')
            active_span=c['H'][i]*(len(positive)-1)/7
            # Physical active geometry, not source ID, identifies reuse.
            physical={'chords_mm':positive,'active_span_mm':round(active_span,9),'freq_hz':d['freqs'][fi]}
            key=hashlib.sha256(json.dumps(physical,sort_keys=True).encode()).hexdigest()[:24]
            origin={'study':d['studies'][c['s'][i]]['id'],'model':mid,'key':c['k'][i],'row':i,'thrust':c['T'][i],'torque':c['Q'][i]}
            if key in records:records[key]['origins'].append(origin);continue
            records[key]={'key':'frontier-'+key,'study':origin['study'],'freq':physical['freq_hz'],'chords':chords,'half_span':c['H'][i],
                'thrust':c['T'][i],'torque':c['Q'][i],'_steps':100,'origins':[origin],'batch':'span-frontier-'+scope}
    return {'version':1,'scope':scope,'created':time.strftime('%Y-%m-%d %H:%M:%S'),'source_build':d.get('build_id'),
        'structural_fingerprint':fingerprint(),'frontier_counts':counts,'cases':list(records.values()),
        'target':'0.5 mm bare sheet, finite span bending + chordwise elasticity',
        'numerics':{'span_panels':8,'chord_panels':4,'steps_per_cycle':100,'cycles':4,'baseline_factors':[.5,.7],'span_factors':[.7,1.]},
        'selection':'Exact nondominated verified/settled points per source model and frequency, no torque cutoff; merged across studies.',
        'geometry_precision':'Exported atlas chords/spans rounded to 0.1 mm. This is a reconstruction, not full-precision source geometry.',
        'conditions':'Template 7657: shared original campaign motion at 0.5 m/s, source frequency. Earlier rigid catalog excluded because its conditions vary.'}


def band_frontier(indices,c,width):
    bands={}
    for i in frontier(indices,c):
        b=math.floor(c['Q'][i]/width+1e-9)
        old=bands.get(b)
        if old is None or (c['T'][i],-c['Q'][i])>(c['T'][old],-c['Q'][old]):bands[b]=i
    return list(bands.values())

def preserved_plan(width,source_root=None):
    if not math.isfinite(width) or width<=0:raise ValueError('Torque band must be positive')
    page=(A.ATLAS/'index.html').read_text(encoding='utf8')
    d=json.loads(re.search(r'<script[^>]*type="application/json"[^>]*>(.*?)</script>',page,re.S)[1]);c=d['cols']
    groups={}
    for i in range(d['catalog']['first']):
        if d['statuses'][c['S'][i]] not in ('verified','ok'):continue
        if c['T'][i] is None or c['Q'][i] is None:continue
        groups.setdefault(c['f'][i],[]).append(i)
    cases=[];references=[];counts={};missing=[]
    for fi,ix in groups.items():
        selected=band_frontier(ix,c,width)
        for i in selected:
            m=d['models'][c['m'][i]];st=d['studies'][c['s'][i]]['id'];f=d['freqs'][fi]
            counts[m['id']+' / '+str(f)+' Hz']=counts.get(m['id']+' / '+str(f)+' Hz',0)+1
            origin={'study':st,'model':m['id'],'key':c['k'][i],'row':i,'thrust':c['T'][i],'torque':c['Q'][i]}
            if m['thickness'] is None:references.append(origin);continue
            w={'key':'preserved-'+hashlib.sha256((st+':'+c['k'][i]).encode()).hexdigest()[:24],'study':st,'freq':f,'chords':c['C'][8*i:8*i+8],
               'half_span':c['H'][i],'thrust':c['T'][i],'torque':c['Q'][i],'origins':[origin], 'source_model':m['id'],
               'material_label':m['label'],'thickness_mm':m['thickness'],'has_rod':m['rod'],'batch':'preserved-frontier',
               'needs_source_settings':True,'torque_band_nm':width,'comparison_note':'Awaiting exact original case settings'}
            dbpath=Path(source_root)/st/'campaign.sqlite' if source_root else None
            if dbpath and dbpath.is_file():
                con=sqlite3.connect('file:'+dbpath.resolve().as_posix()+'?mode=ro',uri=True);con.row_factory=sqlite3.Row
                row=con.execute('select * from designs where key=?',(c['k'][i],)).fetchone()
                if row:
                    plan=json.loads(con.execute("select v from meta where k='plan'").fetchone()[0]);lv=next(v for v in plan['levels'] if v['id']==row['level'])
                    if row['dt'] is None or row['cycles'] is None:raise ValueError('Original actual dt/cycles missing: '+row['key'])
                    w.update(chords=[1000*v for v in json.loads(row['chords'])],half_span=1000*row['half_span'],freq=row['freq'],
                        thickness_mm=lv['thickness_mm'],rod=lv.get('rod') or {},material=plan['material'],template_case=plan['template_case'],
                        _steps=1/(row['dt']*row['freq']),numerics={'dt_s':row['dt'],'cycles':row['cycles'],'span_panels':plan['span_panels'],'chord_panels':plan['chord_panels']},
                        needs_source_settings=False,comparison_note='Exact source geometry and actual run settings restored',source_database=str(dbpath))
                con.close()
            if w['needs_source_settings']:missing.append(origin)
            cases.append(w)
    return {'version':2,'scope':'preserved','structural_fingerprint':fingerprint(),'source_build':d.get('build_id'),'torque_band_nm':width,
        'frontier_counts':counts,'cases':cases,'rigid_references':references,'missing_source_settings':missing,
        'numerics':'Per-case actual source dt/cycles and source-plan mesh; no automatic refinement',
        'target':'Preserve original thickness, material and rod; add finite span bending',
        'selection':'Across all models per frequency: nondominated frontier, then maximum thrust per 0.01 N m band (editable). No torque ceiling.',
        'created':time.strftime('%Y-%m-%d %H:%M:%S')}


def allow_nominal_settings(plan):
    """Fill only missing source records using documented original campaign defaults."""
    for w in plan['cases']:
        if not w.get('needs_source_settings'):continue
        rod={'diameter_m':.005,'hollow_inner_diameter_m':.003,'shear_modulus_pa':4.5e9,'density_kg_m3':1550.0} if w['has_rod'] else {}
        w.update(rod=rod,material={'name':'plain_weave_cf','shear_modulus_pa':4.5e9,'density_kg_m3':1550.0,'youngs_modulus_pa':50e9},
            template_case=7657,_steps=50,numerics={'dt_s':1/(50*w['freq']),'cycles':4,'span_panels':8,'chord_panels':4},
            needs_source_settings=False,settings_provenance='documented nominal campaign settings; original per-case settings unavailable',
            comparison_note='Nominal settings: 8 × 4 panels, 50 steps/cycle, 4 cycles; atlas geometry rounded to 0.1 mm')
        # Cache by physical inputs and numerics, never merely the original atlas key.
        spec={k:w[k] for k in ('chords','half_span','freq','thickness_mm','rod','material','template_case','numerics')}
        w['key']='nominal-'+hashlib.sha256(json.dumps(spec,sort_keys=True).encode()).hexdigest()[:24]
    plan['missing_source_settings']=[]
    plan['nominal_fallback_authorized']=True
    plan['numerics']='Per-case recorded settings when available; otherwise 8x4 panels, 50 steps/cycle, 4 cycles. No automatic refinement.'
    return plan

def evaluate(w):
    try:return A.evaluate(w)
    except Exception as exc:return {'source':w,'baseline':{'status':'failed','error':str(exc)},'spanwise':{'status':'failed','error':str(exc)}}

def publish_batch(folder):
    existing={}
    for p in A.OUT.glob('*.json'):
        r=json.loads(p.read_text(encoding='utf8'));existing[r['source']['key']]=r
    for p in (ROOT/'outputs/elastic/frontiers').glob('*/results/*.json'):
        r=json.loads(p.read_text(encoding='utf8'));existing[r['source']['key']]=r
    A.publish(list(existing.values()))

def main():
    ap=argparse.ArgumentParser(description=__doc__);ap.add_argument('--scope',choices=['bare','all','preserved'],default='preserved');ap.add_argument('--run',action='store_true');ap.add_argument('--workers',type=int,default=4);ap.add_argument('--limit',type=int);ap.add_argument('--publish-only',action='store_true');ap.add_argument('--torque-band',type=float,default=.01);ap.add_argument('--source-root',type=Path);ap.add_argument('--allow-nominal',action='store_true',help='use documented nominal settings only for missing source records');args=ap.parse_args()
    if args.workers<1:ap.error('workers must be positive')
    folder=ROOT/'outputs/elastic/frontiers'/(args.scope+('-'+str(args.torque_band).replace('.','p') if args.scope=='preserved' else ''));folder.mkdir(parents=True,exist_ok=True);(folder/'results').mkdir(exist_ok=True)
    pp=folder/'plan.json'
    if args.scope=='preserved' and (not pp.exists() or args.source_root):
        plan=preserved_plan(args.torque_band,args.source_root);atomic(pp,plan)
    elif pp.exists():plan=json.loads(pp.read_text(encoding='utf8'))
    else:plan=make_plan(args.scope);atomic(pp,plan)
    if plan['structural_fingerprint']!=fingerprint():raise RuntimeError('Structural code changed since plan. Create a new versioned plan before running.')
    if args.allow_nominal:
        plan=allow_nominal_settings(plan);atomic(pp,plan)
    keys={w['key'] for w in plan['cases']};done=set()
    for saved in (ROOT/'outputs/elastic/frontiers').glob('*/results/*.json'):
        r=json.loads(saved.read_text(encoding='utf8'));pr=r.get('provenance',{})
        if pr.get('structural_fingerprint')==plan['structural_fingerprint'] and pr.get('numerics')==plan['numerics'] and r['source']['key'] in keys:done.add(r['source']['key'])
    pending=[w for w in plan['cases'] if w['key'] not in done]
    print(json.dumps({'total_unique':len(plan['cases']),'completed':len(done),'pending':len(pending),'groups':plan['frontier_counts'],'plan':str(pp),'missing_original_settings':len(plan.get('missing_source_settings',[])),'rigid_references':len(plan.get('rigid_references',[]))},indent=2),flush=True)
    if args.publish_only:publish_batch(folder);return
    if not args.run:return
    if plan.get('missing_source_settings'):raise SystemExit('Run blocked: original per-case dt/cycles and precise geometry are absent from atlas. Supply --source-root pointing to the original campaign folders.')
    if (folder/'STOP').exists():raise RuntimeError('STOP file exists; remove it to resume.')
    if args.limit is not None:pending=pending[:max(0,args.limit)]
    atomic(folder/'progress.json',{'completed':len(done),'total':len(plan['cases']),'running':True,'pid':os.getpid(),'workers':args.workers,'started':time.strftime('%Y-%m-%d %H:%M:%S')})
    start=time.monotonic();finished=0;it=iter(pending);active={}
    with ProcessPoolExecutor(max_workers=args.workers) as pool:
        def submit():
            if (folder/'STOP').exists():return
            w=next(it,None)
            if w is not None:active[pool.submit(evaluate,w)]=w
        for _ in range(args.workers):submit()
        while active:
            ready,_=wait(active,timeout=2,return_when=FIRST_COMPLETED)
            for fut in ready:
                w=active.pop(fut);r=fut.result();r['provenance']={'structural_fingerprint':plan['structural_fingerprint'],'batch':plan['scope'],'numerics':plan['numerics']}
                atomic(folder/'results'/(w['key']+'.json'),r);finished+=1;done.add(w['key']);elapsed=time.monotonic()-start
                atomic(folder/'progress.json',{'completed':len(done),'total':len(plan['cases']),'elapsed_s':elapsed,'remaining_estimate_s':(len(plan['cases'])-len(done))*elapsed/finished,'last_key':w['key'],'running':True})
                print(w['key'],r['baseline']['status'],r['spanwise']['status'],f'{len(done)}/{len(plan["cases"])}',flush=True)
                if finished%10==0:publish_batch(folder)
                submit()
    publish_batch(folder)
    atomic(folder/'progress.json',{'completed':len(done),'total':len(plan['cases']),'running':False,'stopped':(folder/'STOP').exists()})
    print('Saved results and updated atlas.',flush=True)

if __name__=='__main__':main()
