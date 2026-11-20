"""Non-destructive study generations over the existing live result databases.

The solver can keep its existing SQLite connections and case numbers. Only the
catalog views change; both stores remain available to exact-result reuse.
"""
import json
import math
import os
import shutil
import sqlite3
from datetime import datetime, timezone
from pathlib import Path


def settings(model):
    from . import catalog
    with catalog.connect(model) as db:
        row=db.execute("SELECT value FROM meta WHERE key='catalog_partition'").fetchone()
    return json.loads(row[0]) if row else None


def organize(model,first_current_study):
    """Snapshot the old organization, then install an explicit study boundary."""
    from . import catalog
    if not (model.OUTPUTS/first_current_study/'manifest.json').is_file():raise ValueError('Current study was not found.')
    previous=settings(model)
    if previous and previous['first_current_study']==first_current_study:return previous
    backup=catalog.root(model)/'maintenance'/'catalog-backups'/datetime.now(timezone.utc).strftime('%Y%m%dT%H%M%SZ')
    backup.mkdir(parents=True,exist_ok=False)
    known={p.name for p in model.OUTPUTS.iterdir() if (p/'manifest.json').is_file()}
    for filename in ('master_runs.sqlite3','master_runs_old.sqlite3'):
        path=catalog.root(model)/filename
        if not path.exists():continue
        with sqlite3.connect(path,factory=catalog.ClosingConnection) as source,sqlite3.connect(backup/filename,factory=catalog.ClosingConnection) as destination:
            source.backup(destination)
            known.update(r[0] for r in source.execute('SELECT DISTINCT study FROM occurrences'))
    for filename in ('master_runs.xlsx','master_runs_old.xlsx','master_runs_adaptive.xlsx'):
        path=catalog.root(model)/filename
        if path.exists():shutil.copy2(path,backup/filename)
    archived=sorted(s for s in known if s!=first_current_study and (not s[:8].isdigit() or s<first_current_study))
    config={'first_current_study':first_current_study,'archived_studies':archived,
        'backup_directory':str(backup.resolve()),'backup_relative_directory':str(backup.relative_to(catalog.root(model))),
        'organized_utc':catalog.stamp()}
    with catalog.connect(model) as db:
        db.execute("INSERT OR REPLACE INTO meta VALUES('catalog_partition',?)",(catalog.compact(config),))
    return config


def scoped(row,archived,generation):
    occurrences=[o for o in row['occurrences'] if (o['study'] in archived)==(generation=='old')]
    if not occurrences:return None
    result={**row,'occurrences':occurrences}
    # A reused case can originate in Old but appear in New. Show its location
    # in the selected generation, without changing its permanent global ID.
    if not any(o['study']==row['_study'] and o['local_case']==row['id'] for o in occurrences):
        origin=occurrences[-1]
        result.update(_study=origin['study'],id=origin['local_case'],_studyName=origin['study'])
    return result


def views(model,selected,config,metric,descending):
    from . import catalog
    from . import study_organization
    organization=study_organization.read(model)
    archived=set(config['archived_studies']);raw=[];base=None
    membership={'current':set(),'old':set()}
    stores=['current']+(['old'] if (catalog.root(model)/'master_runs_old.sqlite3').exists() else [])
    for store in stores:
        with (catalog.connect(model) if store=='current' else catalog.old_connection(model)) as db:
            locations=list(db.execute('SELECT c.signature,o.study FROM cases c JOIN occurrences o ON o.case_no=c.case_no'))
            wanted=set()
            for location in locations:
                if not study_organization.visible(organization,location['study']):continue
                if location['study'][:8].isdigit() and location['study']<config['first_current_study']:
                    archived.add(location['study'])
                generation='old' if location['study'] in archived else 'current'
                membership[generation].add(location['signature'])
                if generation in selected:wanted.add(location['signature'])
            # Counts need only the small signature/occurrence index. Historical
            # geometry payloads are loaded only when Old is actually selected.
            data=catalog.listing(model,metric,descending,_db=db,check_outputs=False,_signatures=wanted)
            if base is None:base=data
            raw.extend(data['rows'])
    groups={}
    for generation in ('current','old'):
        # Prefer the current database's representation when the same exact
        # simulation occurs in both storage generations; merge all locations.
        chosen={}
        for row in raw:
            row={**row,'occurrences':[o for o in row['occurrences'] if study_organization.visible(organization,o['study'])]}
            item=scoped(row,archived,generation)
            if not item:continue
            item['_studyName']=study_organization.name(organization,item['_study'],item.get('_studyName'))
            key=item['_signature']
            if key not in chosen:chosen[key]=item
            else:
                old=chosen[key];locations={(o['study'],o['local_case']):o for o in old['occurrences']}
                locations.update({(o['study'],o['local_case']):o for o in item['occurrences']})
                old['occurrences']=list(locations.values())
        groups[generation]=list(chosen.values())
    rows=[];seen=set()
    for generation in ('current','old'):
        if generation not in selected:continue
        for row in groups[generation]:
            if row['_signature'] in seen:continue
            seen.add(row['_signature'])
            rows.append({**row,'catalog_generation':generation,'comparison_key':f"{generation}:{row['global_case_no']}",
                'aeroelastic_enabled':row['_settings'].get('aeroelastic_enabled',False)})
    valid=lambda r:isinstance(r.get(metric),(int,float)) and math.isfinite(r[metric]) and r.get('status')=='ok'
    rows.sort(key=lambda r:(not valid(r),(-r[metric] if descending else r[metric]) if valid(r) else 0,r['global_case_no']))
    rank=0;last=None
    for i,row in enumerate(rows,1):
        if valid(row):
            if row[metric]!=last:rank=i;last=row[metric]
            row['catalog_rank']=rank
        else:row['catalog_rank']=None
    return {**base,'rows':rows,'case_count':len(rows),'occurrence_count':sum(len(r['occurrences']) for r in rows),
        'generations':{'current':len(membership['current']),'old':len(membership['old']),'adaptive':0},
        'selected':selected,'partition':config}


def refresh(model,browser_url):
    """Update the live New view; retire exports from already-running old workers."""
    from . import catalog
    config=settings(model)
    if not config:return
    legacy=catalog.root(model)/'master_runs_adaptive.xlsx'
    if legacy.exists():
        backup=catalog.root(model)/config.get('backup_relative_directory','maintenance/catalog-backups/legacy-exports')/'legacy_adaptive_last.xlsx'
        backup.parent.mkdir(parents=True,exist_ok=True)
        try:os.replace(legacy,backup)
        except PermissionError:pass
    current=catalog.root(model)/'master_runs.xlsx'
    modified=[];running=False
    archived=set(config['archived_studies'])
    for directory in model.OUTPUTS.iterdir():
        if directory.name in archived or directory.name[:8].isdigit() and directory.name<config['first_current_study']:continue
        results=directory/'results.json';status=directory/'status.json'
        if results.is_file():modified.append(results.stat().st_mtime)
        if status.is_file():
            try:running|=model.read_json(status).get('state')=='running'
            except (OSError,ValueError):pass
    if modified and (not current.exists() or max(modified)>current.stat().st_mtime):
        catalog.export(model,browser_url=browser_url,force=not running)
