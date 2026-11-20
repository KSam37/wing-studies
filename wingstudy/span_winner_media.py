"""Render native animations for the matched, highest-thrust performers at each frequency."""
import json
from pathlib import Path
from concurrent.futures import ProcessPoolExecutor,as_completed
from . import span_atlas as A

FOLDER=A.ROOT/'outputs/elastic/frontiers/preserved-0p01/results'
def selected():
    rows=[(p,json.loads(p.read_text())) for p in FOLDER.glob('*.json')]
    good=[(p,r) for p,r in rows if all(r[k]['status']=='verified' for k in ['baseline','spanwise'])]
    winners={}
    for f in sorted({r['source']['freq'] for p,r in good}):
        for kind in ['baseline','spanwise']:
            p,r=max([(p,r) for p,r in good if r['source']['freq']==f],key=lambda pr:pr[1][kind]['mean_thrust_N'])
            winners[str(p)]=r
    return winners

def render(task):
    path,kind=task;p=Path(path);r=json.loads(p.read_text());v=r[kind]
    dest=A.ATLAS/'media/span'/r['source']['key']/kind
    if (dest/'replay.json').exists():return path,kind,json.loads((dest/'replay.json').read_text())['media']
    from . import elastic, elastic_runner as R
    cfg=elastic.ElasticConfig.from_dict(v['elastic']);cfg.added_mass_factor=v['added_mass_factor']
    result=R.run(r['case'],r['settings'],cfg,output_dir=dest)
    if result['status']!='ok' or not result.get('settled'):raise RuntimeError(str(result.get('error','Replay did not settle')))
    for metric in ['mean_thrust_N','peak_abs_root_torque_Nm']:
        if abs(result[metric]-v[metric])>max(1e-7,abs(v[metric])*1e-5):raise RuntimeError('Replay differs from saved '+metric)
    from PIL import Image
    with Image.open(dest/'animation_front.webp') as im:
        im.seek(max(0,im.n_frames-20));im.convert('RGB').save(dest/'poster.webp')
    prefix=dest.relative_to(A.ATLAS/'media').as_posix()
    media={k:prefix+'/'+name for k,name in [('main','animation.webp'),('front','animation_front.webp'),('top','animation_top.webp'),('poster','poster.webp')]}
    (dest/'replay.json').write_text(json.dumps({'media':media,'mean_thrust_N':result['mean_thrust_N'],'peak_abs_root_torque_Nm':result['peak_abs_root_torque_Nm']}))
    return path,kind,media

def main():
    winners=selected();print('Rendering',len(winners),'designs in both models',flush=True)
    with ProcessPoolExecutor(max_workers=2) as pool:
        jobs=[pool.submit(render,(p,k)) for p in winners for k in ['baseline','spanwise']]
        for job in as_completed(jobs):
            p,k,media=job.result();p=Path(p);r=json.loads(p.read_text());r[k]['media']=media
            tmp=p.with_suffix('.tmp');tmp.write_text(json.dumps(r));tmp.replace(p)
            A.publish([r]);print('Ready',r['source']['key'],k,flush=True)
    print('All winner animations published.',flush=True)
if __name__=='__main__':main()
