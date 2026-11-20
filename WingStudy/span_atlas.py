"""Rerun the exported atlas's 0.5 mm bare-sheet category winners; publish compact comparisons."""
import json,re,hashlib,argparse
from pathlib import Path
from concurrent.futures import ProcessPoolExecutor,as_completed

ROOT=Path(__file__).resolve().parent.parent
ATLAS=ROOT.parent/'Elastic_Wing_Atlas/Elastic_Wing_Atlas'
OUT=ROOT/'outputs/elastic/span_atlas'

def evaluate(w):
    import elastic,elastic_runner as R
    c,s=R.load_catalog_case(w.get('template_case',7657))
    chords=w['chords']; active=[x/1000 for x in chords if x>0]
    span=w['half_span']/1000*(len(active)-1)/(len(chords)-1)
    c=R.sections_case(c,s,active,span,w['key']);c['frequency_hz']=w['freq']
    ov=w.get('numerics') or {'dt_s':1/(w.get('_steps',50)*w['freq']),'cycles':4,'span_panels':8,'chord_panels':4}
    physical={'thickness_m':w.get('thickness_mm',.5)*.001,'rod':w.get('rod',{}),'material':w.get('material',{})}
    baseline=R._run_verified_at_dt(c,s,elastic.ElasticConfig.from_dict(physical),ov,ladder=(.5,.7))
    cfg=elastic.ElasticConfig.from_dict(dict(physical,spanwise_bending=True,large_deflection=True,max_bend_deg=75,max_tip_deflection_fraction=.95))
    spanresult=R._run_verified_at_dt(c,s,cfg,ov,ladder=(.7,1.))
    return {'source':w,'case':c,'settings':dict(s,**ov),'baseline':baseline,'spanwise':spanresult}

def publish(rows):
    compact=[]
    for r in rows:
        v={'source':dict(r['source'])}
        if r.get('case'):
            v['source']['motion']={k:r['case'].get(k) for k in ('speed_mps','frequency_hz','amplitude_deg','incidence_deg','waveform_signature')}
        if r.get('settings'):
            v['source']['fluid']={k:r['settings'].get(k) for k in ('rho','nu')}
        for name in ('baseline','spanwise'):
            v[name]={k:x for k,x in r[name].items() if k not in ('history','span_history','strips','elastic')}
        compact.append(v)
    p=ATLAS/'index.html'
    old=p.read_text(encoding='utf8')
    data=json.loads(re.search(r'<script[^>]*type="application/json"[^>]*>(.*?)</script>',old,re.S)[1])
    combined={r['source']['key']:r for r in data.get('span_comparisons',[])}
    combined.update({r['source']['key']:r for r in compact})
    compact=list(combined.values())
    data['span_comparisons']=compact
    template=(ROOT/'WingStudy/elastic_atlas.html').read_text(encoding='utf8')
    page=template.replace('/*__ATLAS_DATA__*/',json.dumps(data,separators=(',',':'),allow_nan=False).replace('</','<\\/'))
    p.write_text(page,encoding='utf8')
    (ATLAS/'files/span_comparison.json').write_text(json.dumps(compact,separators=(',',':')),encoding='utf8')
    (ATLAS/'span_comparison.html').write_text('<!doctype html><meta http-equiv="refresh" content="0;url=index.html#span"><a href="index.html#span">Open Elastic Wing Atlas</a>',encoding='utf8')
    import zipfile
    with zipfile.ZipFile(ATLAS/'Spanwise_Comparison.zip','w',compression=zipfile.ZIP_DEFLATED) as z:
        z.writestr('index.html',page)
        z.writestr('README.txt','Open index.html and select Spanwise elasticity. This is the integrated atlas with all embedded data. Media and external report links require the full atlas folder; plots, filters and data inspection work offline.')

def main():
    ap=argparse.ArgumentParser(description=__doc__);ap.add_argument('--publish-only',action='store_true')
    ap.add_argument('--campaign',type=Path,help='import a saved span-flex GUI campaign into the lightweight atlas')
    ap.add_argument('--recheck',action='store_true',help='retry unresolved comparisons once at 100 steps per cycle')
    args=ap.parse_args()
    OUT.mkdir(parents=True,exist_ok=True)
    if args.campaign:
        import sqlite3
        db=sqlite3.connect(f'file:{(args.campaign/"campaign.sqlite").resolve().as_posix()}?mode=ro',uri=True)
        plan=json.loads(db.execute("select v from meta where k='plan'").fetchone()[0])
        if not plan.get('elastic_options',{}).get('spanwise_bending'):
            raise ValueError('This importer requires a span-flex campaign.')
        for key,freq,chords,hs,status,t,q,tw in db.execute("select key,freq,chords,half_span,status,thrust,torque,tip_twist from designs where numerics='base'"):
            cyc=db.execute('select data from cycles where key=?',(key,)).fetchone()
            r={'source':{'key':key,'study':plan['name'],'freq':freq,'chords':[1000*x for x in json.loads(chords)],'half_span':1000*hs,'thrust':0.,'torque':0.,'comparison_note':'No matched baseline imported'},
               'baseline':{'status':'not compared'},'spanwise':{'status':status,'mean_thrust_N':t,'peak_abs_root_torque_Nm':q,'tip_twist_amplitude_deg':tw,'final_cycle':json.loads(cyc[0]) if cyc else None}}
            (OUT/('campaign-'+key+'.json')).write_text(json.dumps(r))
        db.close();args.publish_only=True
    s=(ATLAS/'index.html').read_text(encoding='utf8')
    d=json.loads(re.search(r'<script[^>]*type="application/json"[^>]*>(.*?)</script>',s,re.S)[1])
    winners={w['key']:w for w in d['winners'] if w.get('model')=='t0.50' and w.get('key')}
    rows=[json.loads(p.read_text()) for p in OUT.glob('*.json')]
    done={r['source']['key'] for r in rows}
    if args.recheck:
        retry={r['source']['key'] for r in rows if r['spanwise']['status']=='unresolved' or r['baseline']['status']=='unresolved'}
        for key in retry:
            if key in winners:winners[key]['_steps']=100
        done-=retry
        rows=[r for r in rows if r['source']['key'] not in retry]
    if not args.publish_only:
        with ProcessPoolExecutor(max_workers=2) as pool:
            futures=[pool.submit(evaluate,w) for k,w in winners.items() if k not in done]
            for fu in as_completed(futures):
                r=fu.result();rows.append(r);(OUT/(r['source']['key']+'.json')).write_text(json.dumps(r,indent=1))
                publish(rows);print(r['source']['key'],r['baseline']['status'],r['spanwise']['status'],flush=True)
    publish(rows);print('Published',len(rows),'matched comparisons to',ATLAS,flush=True)

if __name__=='__main__':main()
