"""One-time saved-study curation. Emits checked deletion targets for PowerShell.

Does not delete directories. Rehomes catalog origins before the explicitly
authorized folder cleanup; all retained case numbers/signatures stay unchanged.
"""
import json
import shutil
import sqlite3
from datetime import datetime,timezone
from pathlib import Path
import catalog
import study_organization

LAMBDA_STUDIES=[
 '20261030-184121-588787_independent-seed-wing-search-2',
 '20261030-212946-296634_lower-torque-lambda-1-25',
 '20261101-123817-886638_lambda-1-75']


def plan(model):
    previous=study_organization.read(model);items={};root=model.OUTPUTS.resolve()
    for p in sorted(root.iterdir()):
        if not (p/'manifest.json').is_file():continue
        m=model.read_json(p/'manifest.json');state=model.read_json(p/'status.json').get('state')
        rows=model.read_json(p/'results.json') if (p/'results.json').is_file() else []
        ok=sum(r.get('status')=='ok' for r in rows)
        original=previous.get('studies',{}).get(p.name,{}).get('original_name',m['name'])
        if p.name in LAMBDA_STUDIES:
            weight=model.read_json(p/'coordinate_objective.json')['tradeoff_lambda'];group='current'
            name=f'Lambda {weight:g} — independent seeds — {len(rows)} evaluated designs'
            reason='Retained primary comparison study.'
        else:
            test=any(t in original.lower() for t in ('verification','trial','export failures'))
            keep=not test and (state=='complete' and ok>=25 or ok>=100)
            group='old' if keep else 'retired'
            a=m.get('adaptive_search',{})
            method={'coordinate':'Coordinate pilot','torque_curve':'Torque-target search',
                'strict_thrust_nonincreasing_torque':'Strict dominance search'}.get(a.get('acceptance_rule'),
                'Adaptive search' if a else 'Geometry sweep')
            original=original if original!='Study' else 'General geometry sweep'
            date=f'{p.name[:4]}-{p.name[4:6]}-{p.name[6:8]}'
            name=f'Old — {date} — {original} — {ok} successful cases'+(' (partial)' if state!='complete' else '')
            reason='Substantial historical study retained.' if keep else 'Small test, incomplete small study, or superseded failed run.'
        items[p.name]={'group':group,'name':name,'original_name':original,'state':state,
            'case_count':len(rows),'successful':ok,'reason':reason}
    if any(s not in items for s in LAMBDA_STUDIES):raise ValueError('A primary lambda study is missing; refusing cleanup.')
    targets=[str((root/s).resolve()) for s,v in items.items() if v['group']=='retired']
    if any(Path(p).parent!=root for p in targets):raise ValueError('Cleanup path escaped the study root.')
    return {'version':1,'organized_utc':catalog.stamp(),'lambda_studies':LAMBDA_STUDIES,'studies':items,
        'deletion_targets':targets,'study_root':str(root)}


def apply(model):
    config=plan(model);retired={s for s,v in config['studies'].items() if v['group']=='retired'}
    stamp=datetime.now(timezone.utc).strftime('%Y%m%dT%H%M%SZ')
    backup=model.OUTPUTS.parent/'maintenance'/'organization'/stamp;backup.mkdir(parents=True,exist_ok=False)
    # Small provenance snapshots and consistent DB backups, not copies of deleted run files.
    retained={}
    for study,item in config['studies'].items():
        directory=model.OUTPUTS/study;m=model.read_json(directory/'manifest.json')
        model.write_json(backup/(study+'.manifest.json'),m)
        if study not in retired:
            retained[study]=(m,{r['id']:r for r in model.read_json(directory/'results.json')})
    changes=[]
    for filename in ('master_runs.sqlite3','master_runs_old.sqlite3'):
        path=model.OUTPUTS.parent/filename
        if not path.exists():continue
        with sqlite3.connect(path,factory=catalog.ClosingConnection) as db,sqlite3.connect(backup/filename,factory=catalog.ClosingConnection) as dest:db.backup(dest)
        with sqlite3.connect(path,factory=catalog.ClosingConnection) as db:
            db.row_factory=sqlite3.Row;before={r['case_no']:r['signature'] for r in db.execute('SELECT case_no,signature FROM cases')}
            for row in db.execute('SELECT * FROM cases').fetchall():
                if row['origin_study'] not in retired:continue
                candidates=[o for o in db.execute('SELECT * FROM occurrences WHERE case_no=? ORDER BY study,local_case',(row['case_no'],)) if o['study'] in retained]
                if not candidates:continue  # removed below after occurrence cleanup
                # Prefer a complete copied output set when the original was reusable.
                def usable(o):return catalog.available(model,{**dict(row),'origin_study':o['study'],'origin_case':o['local_case']})
                candidates.sort(key=lambda o:not usable(o));origin=candidates[0]
                manifest,results=retained[origin['study']];case=next(c for c in manifest['cases'] if c['id']==origin['local_case'])
                payload=json.loads(row['payload']);payload.update(case=case,settings=manifest['settings'],study_name=config['studies'][origin['study']]['name'])
                result=results.get(origin['local_case'])
                if row['state']=='ok' and not result:raise ValueError('Retained successful occurrence has no result.')
                db.execute('UPDATE cases SET origin_study=?,origin_case=?,payload=?,result=? WHERE case_no=?',
                    (origin['study'],origin['local_case'],catalog.compact(payload),catalog.compact(result) if result else row['result'],row['case_no']))
                changes.append({'database':filename,'case_no':row['case_no'],'from':row['origin_study'],'to':origin['study'],'case':origin['local_case']})
            for study in retired:
                db.execute('DELETE FROM occurrences WHERE study=?',(study,));db.execute('DELETE FROM imports WHERE study=?',(study,))
            db.execute('DELETE FROM cases WHERE NOT EXISTS (SELECT 1 FROM occurrences o WHERE o.case_no=cases.case_no)')
            after={r['case_no']:r['signature'] for r in db.execute('SELECT case_no,signature FROM cases')}
            if any(before[k]!=v for k,v in after.items()):raise ValueError('A retained signature changed.')
            partition=db.execute("SELECT value FROM meta WHERE key='catalog_partition'").fetchone()
            if partition:
                value=json.loads(partition[0]);value['archived_studies']=[s for s,i in config['studies'].items() if i['group']=='old']
                db.execute("UPDATE meta SET value=? WHERE key='catalog_partition'",(catalog.compact(value),))
            if db.execute('PRAGMA integrity_check').fetchone()[0]!='ok':raise ValueError('Catalog integrity check failed.')
    for study,(m,results) in retained.items():
        m['name']=config['studies'][study]['name'];m['study_label']={**m.get('study_label',{}),
            'group':config['studies'][study]['group'],'preserve':True}
        model.write_json(model.OUTPUTS/study/'manifest.json',m)
    config['catalog_origin_changes']=changes;config['metadata_backup']=str(backup)
    model.write_json(model.OUTPUTS.parent/'study_organization.json',config)
    model.write_json(backup/'cleanup_plan.json',config)
    return config


if __name__=='__main__':
    import sys,model
    result=apply(model) if '--apply' in sys.argv else plan(model)
    print(json.dumps({'groups':{k:sum(v['group']==k for v in result['studies'].values()) for k in ('current','old','retired')},
        'deletion_targets':result['deletion_targets'],'catalog_origin_changes':len(result.get('catalog_origin_changes',[]))},indent=2))
