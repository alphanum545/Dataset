"""Post-execution verification only. Does not tune or rerun scheduling policy."""
from __future__ import annotations
from collections import Counter, defaultdict
from concurrent.futures import ThreadPoolExecutor
from dataclasses import asdict
from fractions import Fraction
from hashlib import sha256
import gzip
import json
import math
from pathlib import Path
import shutil
import statistics
import sys
import zipfile
import boto3
from generator.canonical import canonical_json_bytes
from generator.schedule import evaluate_schedule, build_schedule
from algorithms.dcr_ifc import DCRScheduler
from algorithms.bddc_bdc import BDCScheduler
from experiment.dcr_execution import extract_development, make_job, PRIMARY_EXPERIMENT, RUNTIME_EXPERIMENT
from experiment.result_schema import ExperimentResult
from experiment.development_runner import build_primary_development_jobs

BUCKET='ifc-primary-development-ap-south-2-datasetbucket-pkewbeuaaqzx'
COMMIT='7bcefcf02642b2a69b2f03f02ca6aaeee3e28f1f'
PREFIX='results/ifc-dcr-v0-development-v1/'+COMMIT+'/'
DATAKEY='dataset/frozen/pilot-materialization-v1-5266acbfb246a7354929330f1329227609ec1c06-sha256-1cc0f68376d0ad09f9eae89a24a4d45c626922665b061b82d4cf8d50dabb53e6.zip'
SCIENTIFIC=('algorithm_id','algorithm_version','instance_id','split','seed','deadline_us','budget_ncu','schedule_id','makespan_us','compute_cost_ncu','compute_energy_nj','network_energy_pj','deadline_met','budget_met','joint_feasible')
OUT=Path('/tmp/dcr-evidence')
OUT.mkdir(exist_ok=True)
s3=boto3.client('s3',region_name='ap-south-2')

def put(name,value):
    (OUT/name).write_text(json.dumps(value,sort_keys=True,indent=2,allow_nan=False)+'\n')

def lines(name,rows):
    (OUT/name).write_bytes(b''.join(canonical_json_bytes(r)+b'\n' for r in rows))

def quant(values):
    values=sorted(Fraction(x) for x in values)
    return {'n':len(values),'min':float(values[0]),'median':float(statistics.median(values)),
            'p95_nearest_rank':float(values[math.ceil(.95*len(values))-1]),'max':float(values[-1]),
            'median_exact':str(statistics.median(values)),
            'p95_exact':str(values[math.ceil(.95*len(values))-1])} if values else {'n':0}

def count(rows):
    return {'n':len(rows),'success':sum(r['status']=='success' for r in rows),
            'deadline_met':sum(r['deadline_met'] is True for r in rows),
            'budget_met':sum(r['budget_met'] is True for r in rows),
            'joint_feasible':sum(r['joint_feasible'] is True for r in rows)}

s3.download_file(BUCKET,DATAKEY,'/tmp/frozen.zip')
dataset=extract_development(Path('/tmp/frozen.zip'),Path('/tmp/development-only'))
ids=dataset.development_instance_ids()
assert len(ids)==160
entries={e['instance_id']:e for e in dataset.manifest['entries'] if e['split']=='development'}
listing=[]
for page in s3.get_paginator('list_objects_v2').paginate(Bucket=BUCKET,Prefix=PREFIX+'instances/'):
    listing.extend(page.get('Contents',[]))
assert len(listing)==160, ('missing or extra instance results',len(listing))

def read_object(item):
    raw=s3.get_object(Bucket=BUCKET,Key=item['Key'])['Body'].read()
    return json.loads(raw),{'key':item['Key'],'sha256':sha256(raw).hexdigest(),'bytes':len(raw)}

with ThreadPoolExecutor(max_workers=8) as pool:
    loaded=list(pool.map(read_object,sorted(listing,key=lambda o:o['Key'])))
payloads=sorted([x[0] for x in loaded],key=lambda x:x['instance_id'])
assert [x['instance_id'] for x in payloads]==list(ids)
original_raw=s3.get_object(Bucket=BUCKET,Key='results/ifc-primary-development-v1/results.jsonl')['Body'].read()
original=[json.loads(line) for line in original_raw.splitlines() if line]
assert len(original)==1120
original_jobs=build_primary_development_jobs(dataset,experiment_id='ifc-primary-development-v1')
assert {r['job_id'] for r in original}=={j.job_id for j in original_jobs}
original_by={(r['instance_id'],r['algorithm_id']):r for r in original}
primary,runtime,comparisons=[],[],[]
replay_matches=0
source_root=Path('/tmp/benchmark')
for value in payloads:
    iid=value['instance_id']
    assert value['split']=='development' and value['build']['benchmark_commit']==COMMIT
    assert value['holdout_payloads_opened']==value['calibration_files_opened']==0
    for filename,expected in value['build']['files_sha256'].items():
        assert sha256((source_root/filename).read_bytes()).hexdigest()==expected,filename
    env=value['environment']
    assert env['region']=='ap-south-2' and env['architecture']=='x86_64' and env['memory_mb']=='2048'
    inp=dataset.load_development_input(iid)
    r=value['primary']
    ExperimentResult(**r)
    assert r['job_id']==make_job(iid,DCRScheduler(),PRIMARY_EXPERIMENT).job_id
    assert r['deadline_us']==inp.deadline_us and r['budget_ncu']==inp.budget_ncu
    assert r['dataset_artifact_sha256']==dataset.binding.dataset_artifact_sha256
    if r['status']=='success':
        rawschedule=value['primary_schedule']['schedule']
        e=evaluate_schedule(inp.instance,rawschedule,deadline_us=inp.deadline_us,budget_ncu=inp.budget_ncu)
        rebuilt=build_schedule(inp.instance,task_order=value['primary_schedule']['task_order'],
                              resource_assignments={a['task_id']:a['resource_id'] for a in rawschedule['assignments']},
                              deadline_us=inp.deadline_us,budget_ncu=inp.budget_ncu)
        assert rebuilt.schedule==e.schedule
        for field in ('schedule_id','makespan_us','compute_cost_ncu','compute_energy_nj','network_energy_pj'):
            assert r[field]==e.schedule[field]
        assert (r['deadline_met'],r['budget_met'],r['joint_feasible'])==(e.deadline_feasible,e.budget_feasible,e.joint_feasible)
        assert r['budget_met'] is True
        st=r['algorithm_internal_statistics']
        assert st['planned_assignments_sha256']==sha256(canonical_json_bytes(rawschedule['assignments'])).hexdigest()
        assert st['internal_makespan_us']==r['makespan_us'] and st['internal_compute_cost_ncu']==r['compute_cost_ncu']
        assert st['price_refresh_count']<=4 and st['full_schedule_rebuilds_inside_policy']==0
        if st['fallback_task_count']==0:assert r['joint_feasible']
    primary.append(r)
    samples=value['runtime_records']
    assert len(samples)==6
    assert {(x['algorithm_id'],x['repetition']) for x in samples}=={(a,k) for a in ('dcr_ifc_v0','bdc_ifc_w05') for k in range(3)}
    for x in samples:
        ExperimentResult(**x)
        scheduler=DCRScheduler() if x['algorithm_id']=='dcr_ifc_v0' else BDCScheduler()
        assert x['job_id']==make_job(iid,scheduler,RUNTIME_EXPERIMENT,x['repetition']).job_id
        assert x['status']=='success',('runtime sample failed',iid,x['error_type'])
        target=r if x['algorithm_id']=='dcr_ifc_v0' else original_by[iid,'bdc_ifc_w05']
        assert all(x[k]==target[k] for k in SCIENTIFIC),('determinism mismatch',iid,x['algorithm_id'])
        assert x['algorithm_internal_statistics']==target['algorithm_internal_statistics']
        replay_matches+=1
    runtime.extend(samples)
    dcr_med=statistics.median(x['algorithm_runtime_ns'] for x in samples if x['algorithm_id']=='dcr_ifc_v0')
    bdc_med=statistics.median(x['algorithm_runtime_ns'] for x in samples if x['algorithm_id']=='bdc_ifc_w05')
    ratio=Fraction(dcr_med,bdc_med)
    base=original_by[iid,'bdc_ifc_w05']
    comparisons.append({'instance_id':iid,**{k:entries[iid][k] for k in ('family','target_task_count','qos_profile','scenario_profile','resource_scale','replicate_id')},
        'dcr_joint':r['joint_feasible'],'bdc_joint':base['joint_feasible'],
        'dcr_makespan_us':r['makespan_us'],'bdc_makespan_us':base['makespan_us'],
        'dcr_cost_ncu':r['compute_cost_ncu'],'bdc_cost_ncu':base['compute_cost_ncu'],
        'deadline_us':inp.deadline_us,'budget_ncu':inp.budget_ncu,
        'dcr_median_runtime_ns':dcr_med,'bdc_median_runtime_ns':bdc_med,
        'paired_runtime_ratio':float(ratio),'paired_runtime_ratio_exact':str(ratio),
        'fallback_step':r['algorithm_internal_statistics'].get('first_fallback_step'),
        'fallback_reason':r['algorithm_internal_statistics'].get('first_fallback_reason')})
assert len(primary)==len({r['job_id'] for r in primary})==160
assert len(runtime)==len({r['job_id'] for r in runtime})==960
ratios=[Fraction(r['paired_runtime_ratio_exact']) for r in comparisons]
q=quant(ratios)
byq={p:count([r for r in primary if entries[r['instance_id']]['qos_profile']==p]) for p in ('tight','moderate','relaxed')}
wins=[r['instance_id'] for r in comparisons if r['dcr_joint'] and not r['bdc_joint']]
losses=[r['instance_id'] for r in comparisons if not r['dcr_joint'] and r['bdc_joint']]
summary={'schema_version':1,'implementation_commit':COMMIT,'algorithm_version':DCRScheduler.algorithm_version,
    'dataset_code_commit':dataset.binding.dataset_code_commit_sha,'dataset_artifact_sha256':dataset.binding.dataset_artifact_sha256,
    'execution_region':'ap-south-2','primary':count(primary),'primary_statuses':dict(Counter(r['status'] for r in primary)),
    'runtime_records':len(runtime),'runtime_statuses':dict(Counter(r['status'] for r in runtime)),
    'verified_deterministic_runtime_matches':replay_matches,'verified_primary_schedules':sum(r['status']=='success' for r in primary),
    'by_qos':byq,'baseline_counts':{a:count([r for r in original if r['algorithm_id']==a]) for a in sorted({r['algorithm_id'] for r in original})},
    'comparison_with_bdc':{'dcr_only_feasible':len(wins),'bdc_only_feasible':len(losses),
        'both_feasible':sum(r['dcr_joint'] and r['bdc_joint'] for r in comparisons),
        'neither_feasible':sum(not r['dcr_joint'] and not r['bdc_joint'] for r in comparisons),
        'dcr_wins_ids':wins,'dcr_losses_ids':losses},
    'paired_runtime_ratio':q,'dcr_per_instance_median_runtime_seconds':quant(Fraction(r['dcr_median_runtime_ns'],10**9) for r in comparisons),
    'bdc_per_instance_median_runtime_seconds':quant(Fraction(r['bdc_median_runtime_ns'],10**9) for r in comparisons),
    'runtime_gate_passed':Fraction(q['median_exact'])<=2 and Fraction(q['p95_exact'])<=3,
    'joint_feasibility_improvement_gate_passed':sum(r['joint_feasible'] is True for r in primary)>120,
    'fallback_instances':sum(r['fallback_step'] is not None for r in comparisons),
    'fallback_reasons':dict(Counter(r['fallback_reason'] for r in comparisons if r['fallback_reason'] is not None)),
    'fallback_jointly_feasible':sum(r['fallback_step'] is not None and r['dcr_joint'] for r in comparisons),
    'never_fallback_instances':sum(r['fallback_step'] is None for r in comparisons),
    'positive_capacity_price_uplift_instances':sum(r['algorithm_internal_statistics']['largest_reserve_uplift_scaled_ncu']>0 for r in primary),
    'candidate_counters':{k:sum(r['algorithm_internal_statistics'][k] for r in primary) for k in ('candidate_count','reject_raw_budget','reject_current_domain_or_tail','reject_future_empty_domain','reject_child_arrival','reject_reserve_bound','screened_candidate_count')},
    'runtime_methodology':'Within each same Lambda invocation: primary DCR, then 3 alternating-order DCR/BDC timing pairs. Ratios use per-instance medians; p95 uses nearest rank. Preprocessing timed; I/O and final evaluator excluded. DCR-only primary warm-up precedes pairs, a caveat to publication timing.',
    'holdout_payloads_opened':0,'calibration_files_opened':0,'source_freeze':payloads[0]['build'],
    'original_results_sha256':sha256(original_raw).hexdigest(),'environment_python_versions':sorted({p['environment']['python'] for p in payloads})}
summary['by_dimension']={dim:{str(v):count([r for r in primary if entries[r['instance_id']][dim]==v]) for v in sorted({e[dim] for e in entries.values()})} for dim in ('family','target_task_count','scenario_profile','resource_scale')}
lines('results.jsonl',primary);lines('runtime_results.jsonl',runtime)
with gzip.open(OUT/'schedules.jsonl.gz','wb') as f:
    for value in payloads:
        f.write(canonical_json_bytes({'instance_id':value['instance_id'],**value['primary_schedule']})+b'\n')
put('summary.json',summary);put('instance_comparisons.json',comparisons);put('object_checksums.json',[x[1] for x in loaded])
(OUT/'original_comparator_results.jsonl').write_bytes(original_raw)
for name in ('RUN_PLAN.json','DISPATCH_PLAN.json','DISPATCH_RECEIPT.json'):
    s3.download_file(BUCKET,PREFIX+name,str(OUT/name))
shutil.copyfile(__file__,OUT/'collect_dcr_v0.py')
if Path('/tmp/tests.xml').exists():shutil.copyfile('/tmp/tests.xml',OUT/'tests.xml')
put('SHA256_INDEX.json',{p.name:{'bytes':p.stat().st_size,'sha256':sha256(p.read_bytes()).hexdigest()} for p in sorted(OUT.iterdir()) if p.is_file()})
for p in OUT.iterdir():
    if p.is_file():s3.put_object(Bucket=BUCKET,Key=PREFIX+'export/'+p.name,Body=p.read_bytes(),ChecksumAlgorithm='SHA256')
with zipfile.ZipFile('/tmp/DCR_V0_EXECUTION_EVIDENCE_2026-09-07.zip','w',zipfile.ZIP_DEFLATED) as archive:
    for p in sorted(OUT.iterdir()):
        if p.is_file():archive.write(p,p.name)
s3.put_object(Bucket=BUCKET,Key=PREFIX+'export/DCR_V0_EXECUTION_EVIDENCE_2026-09-07.zip',Body=Path('/tmp/DCR_V0_EXECUTION_EVIDENCE_2026-09-07.zip').read_bytes(),ChecksumAlgorithm='SHA256')
print(json.dumps(summary,sort_keys=True,indent=2),flush=True)
