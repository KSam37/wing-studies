"""Isolated native case processes; one coordinator owns all shared study files."""
import copy
import csv
import multiprocessing
import os
from pathlib import Path
import re
import shutil
import tempfile
import time
import traceback
from concurrent.futures import ProcessPoolExecutor, as_completed


def run_isolated(case,settings,study):
    """Keep native graphics and its shared-history convention process-local."""
    import model
    study=Path(study).resolve();case_id=case['id']
    if not re.fullmatch(r'case_\d{4,}',case_id):raise ValueError('Invalid case identifier.')
    started=time.time()
    from vtkmodules.vtkCommonCore import vtkMultiThreader, vtkSMPTools
    vtkMultiThreader.SetGlobalMaximumNumberOfThreads(1)
    vtkMultiThreader.SetGlobalDefaultNumberOfThreads(1)
    vtkSMPTools.Initialize(1)
    # Native plotting libraries can fail beyond Windows' 260-character path
    # limit. Stage in the short OS temp directory, then copy to the study.
    with tempfile.TemporaryDirectory(prefix='wing-'+case_id+'-') as temp:
        directory=Path(temp)/case_id;directory.mkdir()
        try:
            metrics=model.run_case(case,settings,directory)
            with (Path(temp)/'comparisons/time_histories.csv').open(newline='',encoding='utf-8') as f:
                reader=csv.reader(f);header=next(reader);history=list(reader)
            target=study/case_id;target.mkdir(exist_ok=True)
            for file in directory.iterdir():
                if file.is_file():shutil.copy2(file,target/file.name)
            return {'metrics':metrics,'history_header':header,'history':history,
                'execution':{'pid':os.getpid(),'started':started,'finished':time.time()}}
        except Exception as exc:
            return {'error':str(exc),'traceback':traceback.format_exc(),
                'execution':{'pid':os.getpid(),'started':started,'finished':time.time()}}


class CasePipeline:
    def __init__(self,model,study,manifest):
        self.model=model;self.study=Path(study);self.manifest=manifest;self.r=manifest['adaptive_search']
        self.rows=[];self.lookup={};self.events=[]
        self.simulations=0;self.finished=0;self.requests=0;self.cache_hits=0
        self.stop_reason=None;self.pool=None;self.pending_count=0

    def __enter__(self):
        workers=self.r.get('parallel_workers',1)
        if workers>1:
            # Set before Windows spawns/imports numerical libraries. Avoid each
            # case starting a full-machine BLAS pool inside the process pool.
            for key in ('OMP_NUM_THREADS','OPENBLAS_NUM_THREADS','MKL_NUM_THREADS','NUMBA_NUM_THREADS','NUMEXPR_NUM_THREADS'):
                os.environ[key]='1'
            self.pool=ProcessPoolExecutor(max_workers=workers,mp_context=multiprocessing.get_context('spawn'))
        return self

    def __exit__(self,*args):
        if self.pool:self.pool.shutdown(wait=True,cancel_futures=True)

    def state(self,message):
        self.model.write_json(self.study/'status.json',{'state':'running','total':self.r['simulation_budget'],
            'completed':self.finished,'launched_simulations':self.simulations,'evaluated_cases':len(self.rows),
            'candidate_requests':self.requests,'cache_hits':self.cache_hits,'accepted_count':len(self.events),
            'parallel_workers':self.r.get('parallel_workers',1),'active_cases':min(self.pending_count,self.r.get('parallel_workers',1)),
            'pending_cases':self.pending_count,'message':message})

    def log_trial(self,chords,meta,row,reuse,request):
        import adaptive
        path=self.study/'comparisons/adaptive_trials.csv';path.parent.mkdir(exist_ok=True)
        fresh=not path.exists()
        with path.open('a',newline='',encoding='utf-8') as f:
            w=csv.writer(f)
            if fresh:w.writerow(['request','case','global_case_no','job','span_m','thrust_to_peak_torque_1pm','pass','nodes','step_m','parent_case','reuse','status','mean_thrust_N','peak_root_torque_Nm','chords_m'])
            w.writerow([request,row['id'],row.get('global_case_no'),meta['job'],meta['span_m'],adaptive.score(row),meta['pass'],meta['node'],meta['step_m'],meta['parent_case'],reuse,row['status'],row.get('single_wing_mean_thrust_N'),row.get('single_wing_peak_abs_roll_moment_Nm'),chords])

    def accept(self,event):
        from pareto_poll import refresh_hypervolume
        self.events.append({**event,'evaluation':len(self.rows),'simulations':self.finished})
        if event.get('search_algorithm') not in ('torque_envelope_search_v5','independent_coordinate_v1'):
            reference=refresh_hypervolume(self.events)
            self.model.write_json(self.study/'adaptive_hypervolume.json',reference)
        self.model.write_json(self.study/'evolution.json',self.events)

    def commit(self,case,sig,result,started,chords,meta,request,reuse):
        import catalog
        row={**case};directory=self.study/case['id']
        if 'error' in result:
            row.update(status='failed',error=result['error'])
            self.model.write_json(directory/'error.json',result)
        else:
            if result.get('history'):
                path=self.study/'comparisons/time_histories.csv';path.parent.mkdir(exist_ok=True)
                header=result['history_header']
                if path.exists():
                    with path.open(newline='',encoding='utf-8') as f:
                        if next(csv.reader(f))!=header:raise ValueError('Parallel case history columns differ.')
                fresh=not path.exists()
                with path.open('a',newline='',encoding='utf-8') as f:
                    writer=csv.writer(f)
                    if fresh:writer.writerow(header)
                    writer.writerows(result['history'])
            row.update(result['metrics'],status='ok')
        for key in ('seed_family','geometry_id','simulation_id'):
            row[key]=case[key]
        row['seed_families']=[case['seed_family']]
        if result.get('execution'):row['parallel_execution']=result['execution']
        row['elapsed_s']=round(result['execution']['finished']-result['execution']['started'],3) if result.get('execution') else round(time.time()-started,3)
        if result.get('execution'):row['queue_elapsed_s']=round(result['execution']['started']-started,3)
        catalog.record(self.model,self.manifest,self.study.name,row)
        self.rows.append(row);self.rows.sort(key=lambda x:int(x['id'].split('_')[1]));self.lookup[sig]=row
        self.log_trial(chords,meta,row,reuse,request)
        self.model.write_summary(self.study,self.rows)
        self.state('Saved '+case['id']+'; exploring thrust–torque frontier')
        return row

    def finish_future(self,future,job):
        case,sig,started,chords,meta,request=job
        try:result=future.result()
        except Exception as exc:result={'error':str(exc),'traceback':traceback.format_exc()}
        self.finished+=1;self.pending_count-=1
        self.commit(case,sig,result,started,chords,meta,request,'new solve')

    def evaluate_many(self,inputs):
        """Reserve IDs/budgets and deduplicate before dispatch. Commit on arrival.

        Returned responses retain request order, independent of completion order.
        Every completed case is saved before a poll waits for its other cases.
        """
        import adaptive,catalog
        assignments=[];pending={};planned=set();fatal=None
        try:
            for chords,meta in inputs:
                for future in list(pending):
                    if future.done():self.finish_future(future,pending.pop(future))
                if self.r.get('evaluation_budget') is not None and self.requests>=self.r['evaluation_budget']:
                    self.stop_reason='Candidate-request budget reached';break
                self.requests+=1;request=self.requests
                cfg=copy.deepcopy(self.manifest['config']);cfg.pop('adaptive_search',None)
                cfg['mode']='custom';cfg['designs']=[adaptive.design(self.r,meta['span_m'],self.manifest['settings']['gap_m'],chords,'Adaptive wing')]
                case=self.model.plan(cfg)['cases'][0];sig=catalog.signature(self.model,case,self.manifest['settings'])
                if sig in self.lookup or sig in planned:
                    assignments.append((sig,chords,meta,request,'within study'));continue
                existing=catalog.cache_entries(self.model,{sig}).get(sig)
                if existing is None and self.simulations>=self.r['simulation_budget']:
                    self.stop_reason='New-simulation budget reached';break
                case['id']=f"case_{len(self.manifest['cases'])+1:04d}";case['design_name']=f"Adaptive {len(self.manifest['cases'])+1:04d}"
                case['adaptive_trial']=meta
                from case_identity import geometry_id
                case.update(seed_family=meta.get('seed_family','triangle'),geometry_id=geometry_id(case),simulation_id='SIM-'+sig)
                directory=self.study/case['id'];directory.mkdir(exist_ok=True)
                try:cached=catalog.reuse(self.model,case,self.manifest['settings'],directory) if existing is not None else None
                except (OSError,ValueError,KeyError):cached=None
                if cached is None and self.simulations>=self.r['simulation_budget']:
                    self.stop_reason='New-simulation budget reached';break
                self.manifest['cases'].append(case);self.manifest['case_count']=len(self.manifest['cases'])
                self.model.write_json(self.study/'manifest.json',self.manifest)
                planned.add(sig);assignments.append((sig,chords,meta,request,None));started=time.time()
                if cached is not None:
                    self.cache_hits+=1
                    self.commit(case,sig,{'metrics':cached},started,chords,meta,request,'catalog')
                elif self.pool:
                    self.simulations+=1;self.pending_count+=1
                    future=self.pool.submit(run_isolated,case,self.manifest['settings'],str(self.study))
                    pending[future]=(case,sig,started,chords,meta,request)
                    self.state(f"{min(self.pending_count,self.r['parallel_workers'])} parallel cases active; {self.pending_count} pending")
                else:
                    self.simulations+=1;self.pending_count=1;self.state('Solving '+case['id'])
                    try:result={'metrics':self.model.run_case(case,self.manifest['settings'],directory)}
                    except Exception as exc:result={'error':str(exc),'traceback':traceback.format_exc()}
                    self.finished+=1;self.pending_count=0
                    self.commit(case,sig,result,started,chords,meta,request,'new solve')
        except Exception as exc:fatal=exc
        # Even on a preparation error, collect/save work already dispatched.
        for future in as_completed(pending):self.finish_future(future,pending[future])
        if fatal:raise fatal
        output=[]
        for sig,chords,meta,request,reuse in assignments:
            row=self.lookup[sig];output.append(row)
            family=meta.get('seed_family','triangle')
            members=row.get('seed_families',[row.get('seed_family',family)])
            if family not in members:
                members=[*members,family]
                row['seed_families']=members
                catalog.record(self.model,self.manifest,self.study.name,row)
            row['seed_families']=members
            if reuse:self.log_trial(chords,meta,row,reuse,request)
        if assignments:self.model.write_summary(self.study,self.rows)
        return output

    def evaluate(self,chords,meta):
        import adaptive
        rows=self.evaluate_many([(chords,meta)])
        if not rows:raise adaptive.BudgetReached(self.stop_reason)
        return rows[0]


def parallel_search(r,pipeline):
    """Batch independent requests across span jobs and within each native poll."""
    import adaptive
    jobs=[]
    for span,family in adaptive.search_jobs(r):
        g=adaptive.climb(r,span,len(jobs)+1,family);jobs.append((g,next(g)))
    while jobs:
        # Interleave requests from each span before submitting to the pool.
        groups=[p[1] if p[0]=='batch' else [p] for g,p in jobs]
        combined=[];indices=[[] for _ in groups]
        for i in range(max(map(len,groups),default=0)):
            for j,group in enumerate(groups):
                if i<len(group):indices[j].append(len(combined));combined.append(group[i])
        rows=pipeline.evaluate_many(combined);active=[]
        for j,(g,pending) in enumerate(jobs):
            response=[rows[i] for i in indices[j] if i<len(rows)]
            if not response:continue
            try:
                pending=g.send(response if pending[0]=='batch' else response[0])
                while pending[0]=='accepted':pipeline.accept(pending[1]);pending=next(g)
                active.append((g,pending))
            except StopIteration:pass
        if pipeline.stop_reason:raise adaptive.BudgetReached(pipeline.stop_reason)
        jobs=active


def run_worker(model,study):
    import adaptive,catalog
    study=Path(study);manifest=model.read_json(study/'manifest.json');r=manifest['adaptive_search']
    manifest['catalog_engine']=catalog.engine(model,manifest['settings']);manifest['cases']=[];manifest['case_count']=0
    model.write_json(study/'manifest.json',manifest)
    reason=('Independent seeds completed one half-step refinement per chord'
        if r.get('acceptance_rule')=='coordinate' else 'Pareto searches reached their stopping condition')
    with CasePipeline(model,study,manifest) as pipeline:
        try:
            pipeline.state('Preparing native Ptera cases')
            if r.get('acceptance_rule')=='coordinate':
                import coordinate_search
                coordinate_search.run(r,pipeline)
            elif r.get('acceptance_rule')=='torque_curve':
                import torque_search
                torque_search.run(r,pipeline)
            elif r.get('parallel_workers',1)>1:parallel_search(r,pipeline)
            else:adaptive.run_search(r,pipeline.evaluate,pipeline.accept)
        except adaptive.BudgetReached as exc:reason=str(exc)
        except Exception as exc:
            model.write_json(study/'status.json',{'state':'failed','completed':pipeline.finished,'total':r['simulation_budget'],'message':str(exc)})
            raise
        finally:model.write_json(study/'evolution.json',pipeline.events)
    events=pipeline.events;rows=pipeline.rows
    model.write_json(study/'adaptive_summary.json',{'new_simulations':pipeline.simulations,'cache_hits':pipeline.cache_hits,
        'candidate_requests':pipeline.requests,'unique_cases':len(rows),'accepted_changes':len(events),'parallel_workers':r.get('parallel_workers',1),
        'objective':r['objective'],'search_algorithm':r['search_algorithm'],
        'hypervolume':model.read_json(study/'adaptive_hypervolume.json') if (study/'adaptive_hypervolume.json').exists() else None,
        'frontier_case_ids':{str(job):next(e['frontier_case_ids'] for e in reversed(events) if e['job']==job) for job in {e['job'] for e in events}},'stop_reason':reason})
    adaptive.artifacts(model,study,events);adaptive.export_master(model,manifest.get('browser_url','http://127.0.0.1:8766'))
    if any(row.get('status')=='ok' for row in rows):
        import torque_frontier
        try:model.write_json(study/'frontier.json',torque_frontier.generate(model,{'study':study.name,
            'comparison_mode':'evolution' if r.get('acceptance_rule') in ('coordinate','strict_thrust_nonincreasing_torque','torque_curve') else 'frontier'}))
        except ValueError:pass
    model.write_json(study/'status.json',{'state':'complete' if not any(x['status']=='failed' for x in rows) else 'complete_with_errors',
        'total':pipeline.simulations,'completed':pipeline.finished,'evaluated_cases':len(rows),
        'parallel_workers':r.get('parallel_workers',1),'active_cases':0,'pending_cases':0,
        'message':reason+f'; {len(rows)} unique cases, {pipeline.simulations} new simulations, {pipeline.cache_hits} reused.'})
