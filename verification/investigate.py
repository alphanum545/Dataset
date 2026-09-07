"""Diagnostic only: no changes to frozen inputs, policies, or primary results.
Development witness schedules are verified separately and never used in search.
"""
from __future__ import annotations
import argparse
from collections import Counter, defaultdict
from fractions import Fraction
import gzip
from hashlib import sha256
import json
import math
from pathlib import Path
import shutil
import time
import zipfile

from generator.canonical import canonical_json_bytes, content_sha256
from generator.schedule import build_schedule, evaluate_schedule
from generator.network import resource_route_metrics
from algorithms.registry import stage8_registry
import algorithms.bddc_bdc.scheduler as bc
from experiment.dataset_binding import CURRENT_PILOT_BINDING as BIND
from experiment.dataset_loader import FrozenPilotDataset
from experiment.evaluator_adapter import evaluate_decision
from execution.dispatcher import build_dispatch_messages

BENCHMARK = 'e9115b795576be720862f0cb8ff755a4c75db249'
OUTCOME_SHA = 'b057b8caeb89c0729a8a392f5afac9915698ae1ef9e51c8dc7ffe63650d426a9'
MESSAGE_SHA = '8ecaa5ac92d515e2aeff052ce3ce7910737b4ca984f789c614cd9a4e464f4f4f'
DIMS = ('qos_profile', 'family', 'target_task_count', 'scenario_profile', 'resource_scale', 'replicate_id')


def digest(value):
    return sha256(canonical_json_bytes(value)).hexdigest()


def write(path, value):
    Path(path).write_text(json.dumps(value, sort_keys=True, indent=2, allow_nan=False) + '\n')


def stats(values):
    values = sorted(Fraction(x) for x in values)
    if not values:
        return {'n': 0}
    n = len(values)
    med = values[n//2] if n % 2 else (values[n//2-1] + values[n//2]) / 2
    # Floating point is display-only for dimensionless ratios, never cost/feasibility.
    return {'n': n, 'min': float(values[0]), 'median': float(med), 'max': float(values[-1]),
            'mean': float(sum(values) / n), 'median_exact': str(med)}


def prepare(archive_path, root, shard, shards):
    BIND.verify_artifact_archive(archive_path)
    root.mkdir(parents=True, exist_ok=True)
    with zipfile.ZipFile(archive_path) as z:
        raw = z.read('pilot-materialization-v1.json')
        manifest = json.loads(raw)
        BIND.validate_manifest(manifest)
        (root / 'pilot-materialization-v1.json').write_bytes(raw)
        dev = sorted((e for e in manifest['entries'] if e['split'] == 'development'), key=lambda e: e['instance_id'])
        selected = dev[shard::shards]
        bids = {e['base_instance_id'] for e in selected}
        for e in selected + [b for b in manifest['base_entries'] if b['base_instance_id'] in bids]:
            member = 'pilot/' + e['path']
            assert member.startswith(('pilot/base/', 'pilot/instances/development/'))
            raw = z.read(member)
            assert sha256(raw).hexdigest() == e['sha256']
            path = root / member
            path.parent.mkdir(parents=True, exist_ok=True)
            path.write_bytes(raw)
    dataset = FrozenPilotDataset.open(root)
    messages = build_dispatch_messages(dataset, experiment_id='ifc-primary-development-v1')
    assert len(messages) == len(set(messages)) == 1120
    assert digest([json.loads(s) for s in messages]) == MESSAGE_SHA
    metadata = []
    for e in selected:
        q = json.loads((root / 'pilot' / e['path']).read_text())
        base = dataset.load_development_input(e['instance_id']).instance
        assert content_sha256(q) == q['content_sha256']
        assert content_sha256(dict(base)) == base['content_sha256']
        d, b = q['deadline'], q['budget']
        D, B = d['deadline_us'], b['budget_ncu']
        a = Fraction(d['interpolation_numerator'], d['interpolation_denominator'])
        f = Fraction(b['factor_numerator'], b['factor_denominator'])
        assert a == {'tight': Fraction(1,100), 'moderate': Fraction(1,4), 'relaxed': Fraction(3,4)}[e['qos_profile']]
        assert f == {'tight': Fraction(1,10), 'moderate': Fraction(1,2), 'relaxed': Fraction(9,10)}[e['qos_profile']]
        assert D == d['t_fast_us'] + math.ceil(a * (d['t_economical_us'] - d['t_fast_us']))
        assert B == b['cost_floor_ref_ncu'] + math.floor(f * (b['cost_fast_ncu'] - b['cost_floor_ref_ncu']))
        witness = evaluate_schedule(base, q['joint_feasibility_witness'], deadline_us=D, budget_ncu=B)
        assert witness.joint_feasible
        info = {k: e[k] for k in DIMS}
        info.update(instance_id=e['instance_id'], base_instance_id=e['base_instance_id'], source_sha256=e['source_sha256'],
                    actual_task_count=len(base['tasks']), resource_count=len(base['resources']),
                    deadline_us=D, budget_ncu=B, t_fast_us=d['t_fast_us'], t_economical_us=d['t_economical_us'],
                    cost_fast_ncu=b['cost_fast_ncu'], cost_floor_ref_ncu=b['cost_floor_ref_ncu'],
                    fast_schedule_id=d['fast_schedule_id'], budget_degenerate=b['budget_range_degenerate'],
                    witness_validated=True, free_resources=sum(r['price_ncu_per_second']==0 for r in base['resources']))
        metadata.append(info)
        del q, witness
    return dataset, metadata, manifest


def path_diagnostics(base, ev):
    aa = {a['task_id']: a for a in ev.schedule['assignments']}
    order = sorted(aa, key=lambda t: (aa[t]['end_us'], aa[t]['start_us'], t))
    incoming, outgoing = {t: [] for t in aa}, {t: [] for t in aa}
    for e in base['dependencies']:
        p, t = e['parent'], e['child']
        lag = ev.dependency_arrival_us[p + '->' + t] - aa[p]['end_us']
        incoming[t].append((p, lag, 'dependency'))
        outgoing[p].append((t, lag))
    machines = defaultdict(list)
    for t in order:
        machines[aa[t]['resource_id']].append(t)
    for tasks in machines.values():
        for p, t in zip(tasks, tasks[1:]):
            incoming[t].append((p, 0, 'resource'))
            outgoing[p].append((t, 0))
    duration = {t: aa[t]['end_us'] - aa[t]['start_us'] for t in aa}

    def longest(network=True, resource=True):
        end, pred = {}, {}
        for t in order:
            options = [(end[p] + (lag if network else 0), p, lag if network else 0, kind)
                       for p, lag, kind in incoming[t] if resource or kind != 'resource']
            choice = max(options, default=(0, None, 0, 'source'), key=lambda x: (x[0], str(x[1]), x[3]))
            end[t] = choice[0] + duration[t]
            pred[t] = choice
        return end, pred

    end, pred = longest()
    M = ev.schedule['makespan_us']
    assert all(end[t] == aa[t]['end_us'] for t in aa), 'constraint graph must reconstruct every task finish'
    assert max(end.values()) == M
    tail = {}
    for t in reversed(order):
        tail[t] = duration[t] + max((lag + tail[c] for c, lag in outgoing[t]), default=0)
    slack = {t: M - aa[t]['start_us'] - tail[t] for t in aa}
    assert all(v >= 0 for v in slack.values())
    critical = [t for t in aa if slack[t] == 0]
    chain, communication, resource_edges = [], 0, 0
    t = max(aa, key=lambda t: (end[t], t))
    while t is not None:
        chain.append(t)
        _, p, lag, kind = pred[t]
        communication += lag
        resource_edges += kind == 'resource'
        t = p
    compute = sum(duration[t] for t in chain)
    assert compute + communication == M
    tiers = {r['resource_id']: r['tier'] for r in base['resources']}
    load = {r: sum(duration[t] for t in ts) for r, ts in machines.items()}
    wait = {t: aa[t]['start_us'] - ev.task_dependency_ready_us[t] for t in aa}
    no_resource = max(longest(resource=False)[0].values())
    diag = {
        'critical_task_count': len(critical), 'critical_path_compute_us': compute,
        'critical_path_communication_us': communication, 'critical_path_resource_edges': resource_edges,
        'fixed_machine_order_no_network_makespan_us': max(longest(network=False)[0].values()),
        'unlimited_resources_fixed_mapping_makespan_us': no_resource,
        'no_network_no_contention_makespan_us': max(longest(False, False)[0].values()),
        'contention_extension_us': M-no_resource, 'used_resource_count': len(machines),
        'max_resource_load_us': max(load.values()), 'busiest_resource': max(load, key=load.get),
        'sum_task_resource_wait_us': sum(wait.values()), 'task_count': len(aa),
        'tier_task_counts': dict(Counter(tiers[a['resource_id']] for a in aa.values())),
        'critical_path_compute_by_tier_us': {k: sum(duration[t] for t in chain if tiers[aa[t]['resource_id']]==k) for k in ('iot','fog','cloud')},
        'tier_cost_ncu': {k: sum(base['compute_cost_ncu'][t][aa[t]['resource_id']] for t in aa if tiers[aa[t]['resource_id']]==k) for k in ('iot','fog','cloud')},
        'critical_task_cost_ncu': sum(base['compute_cost_ncu'][t][aa[t]['resource_id']] for t in critical),
    }
    return diag, {'assignments': aa, 'critical': critical, 'slack': slack, 'duration': duration, 'wait': wait, 'load': load}


def traced_policy(scheduler, inp):
    trace, tracker = [], {'spent': 0, 'candidates': {}}
    originals = (bc._deadline_distribution, bc._candidate_assignment, bc._commit_assignment)

    def distribution(state, unscheduled, *, deadline_us):
        answer = originals[0](state, unscheduled, deadline_us=deadline_us)
        tracker['subdeadlines'], tracker['state'] = answer, state
        return answer

    def candidate(instance, graph, *, task_id, resource_id, assignments, intervals_by_resource):
        answer = originals[1](instance, graph, task_id=task_id, resource_id=resource_id,
                              assignments=assignments, intervals_by_resource=intervals_by_resource)
        tracker['candidates'].setdefault(task_id, {})[resource_id] = answer
        return answer

    def commit(assignments, intervals, selected):
        t, rid = selected['task_id'], selected['resource_id']
        costs = inp.instance['compute_cost_ncu'][t]
        remaining = inp.budget_ncu - tracker['spent']
        candidates = tracker['candidates'].pop(t)
        sd = tracker['subdeadlines'][tracker['state'].bottom_depth[t]]
        affordable = [r for r in candidates if costs[r] <= remaining]
        fastest = min(affordable, key=lambda r: (candidates[r]['end_us'], costs[r], r)) if affordable else None
        trace.append({'task_id': t, 'resource_id': rid, 'start_us': selected['start_us'], 'end_us': selected['end_us'],
                      'cost_ncu': costs[rid], 'remaining_before_ncu': remaining, 'subdeadline_fraction': str(sd),
                      'selected_misses_subdeadline': selected['end_us'] > sd,
                      'locally_avoidable_subdeadline_miss': bool(fastest and selected['end_us'] > sd and candidates[fastest]['end_us'] <= sd),
                      'chose_slower_than_affordable': bool(fastest and selected['end_us'] > candidates[fastest]['end_us'])})
        tracker['spent'] += costs[rid]
        return originals[2](assignments, intervals, selected)

    bc._deadline_distribution, bc._candidate_assignment, bc._commit_assignment = distribution, candidate, commit
    try:
        decision = scheduler.schedule(inp, seed=None)
    finally:
        bc._deadline_distribution, bc._candidate_assignment, bc._commit_assignment = originals
    return decision, trace


def eval_map(inp, order, mapping):
    return build_schedule(inp.instance, task_order=order, resource_assignments=mapping,
                          deadline_us=inp.deadline_us, budget_ncu=inp.budget_ncu)


def counterfactual(inp, original, ev, decisions):
    # Bounded diagnostic search, NOT a comparator or an optimality claim.
    base, budget, original_cost = inp.instance, inp.budget_ncu, ev.schedule['compute_cost_ncu']
    order_tests, seen_orders = [], {original.task_order}
    for aid, decision in sorted(decisions.items()):
        if decision.task_order in seen_orders:
            continue
        seen_orders.add(decision.task_order)
        trial = eval_map(inp, decision.task_order, original.resource_assignments)
        assert trial.schedule['compute_cost_ncu'] == original_cost
        order_tests.append({'source_order': aid, 'makespan_us': trial.schedule['makespan_us'], 'joint_feasible': trial.joint_feasible,
                            'schedule': trial.schedule if trial.joint_feasible else None})
    resources = sorted(r['resource_id'] for r in base['resources'])
    tiers = {r['resource_id']: r['tier'] for r in base['resources']}
    parents = defaultdict(list)
    for e in base['dependencies']:
        parents[e['child']].append(e)
    current, mapping = ev, dict(original.resource_assignments)
    steps, evaluations, pair_evaluations, single_rescues, no_extra_rescues = [], 0, 0, 0, 0
    for iteration in range(3):
        if current.joint_feasible:
            break
        _, aux = path_diagnostics(base, current)
        aa = aux['assignments']
        cost, M = current.schedule['compute_cost_ncu'], current.schedule['makespan_us']
        selected = sorted(aux['critical'], key=lambda t: (-aux['duration'][t], t))[:12]
        targets = []
        for t in selected:
            choices = []
            for r in resources:
                if r == mapping[t]:
                    continue
                ready = max((aa[e['parent']]['end_us'] + resource_route_metrics(base['network'], tiers,
                            source_resource_id=mapping[e['parent']], target_resource_id=r, data_bits=e['data_bits'])['communication_time_us']
                            for e in parents[t]), default=0)
                gain = aa[t]['end_us'] - ready - base['execution_time_us'][t][r]
                delta = base['compute_cost_ncu'][t][r] - base['compute_cost_ncu'][t][mapping[t]]
                if gain > 0:
                    choices.append((gain, delta, t, r))
            targets.extend(sorted(choices, key=lambda x: (-x[0], x[1], x[3]))[:4])
        singles = sorted([x for x in targets if cost+x[1] <= budget], key=lambda x: (-x[0],x[1],x[2],x[3]))[:32]
        trials = [('single', [(t,r)], cost+delta) for gain,delta,t,r in singles]
        donors = sorted([t for t in mapping if aux['slack'][t] > 0 and base['compute_cost_ncu'][t][mapping[t]] > 0],
                        key=lambda t: (-base['compute_cost_ncu'][t][mapping[t]],t))[:8]
        pairs = []
        for gain,delta,t,r in sorted(targets,key=lambda x:(-x[0],x[1],x[2],x[3]))[:12]:
            for donor in donors:
                if donor == t:
                    continue
                cheap = min(resources,key=lambda rr:(base['compute_cost_ncu'][donor][rr],base['execution_time_us'][donor][rr],rr))
                saving = base['compute_cost_ncu'][donor][mapping[donor]] - base['compute_cost_ncu'][donor][cheap]
                if saving>0 and cost+delta-saving<=budget:
                    pairs.append((gain,delta-saving,t,r,donor,cheap))
        for gain,delta,t,r,donor,cheap in sorted(pairs,key=lambda x:(-x[0],x[1],x[2:]))[:16]:
            trials.append(('pair',[(t,r),(donor,cheap)],cost+delta))
        best,seen = None,set()
        for kind,moves,projected in trials:
            if tuple(moves) in seen:
                continue
            seen.add(tuple(moves))
            trial_mapping = dict(mapping)
            trial_mapping.update(moves)
            trial = eval_map(inp,original.task_order,trial_mapping)
            evaluations += 1
            pair_evaluations += kind=='pair'
            assert trial.schedule['compute_cost_ncu'] == projected <= budget
            if iteration==0:
                single_rescues += kind=='single' and trial.joint_feasible
                no_extra_rescues += trial.joint_feasible and projected<=original_cost
            key = (trial.schedule['makespan_us'],projected,tuple(moves))
            if best is None or key<best[0]:
                best=(key,trial,trial_mapping,kind,moves)
        if best is None or best[1].schedule['makespan_us']>=M:
            break
        _,current,mapping,kind,moves=best
        steps.append({'kind':kind,'moves':moves,'makespan_us':current.schedule['makespan_us'],
                      'cost_ncu':current.schedule['compute_cost_ncu'],'joint_feasible':current.joint_feasible})
    return {'order_tests':order_tests,'order_only_rescued':any(t['joint_feasible'] for t in order_tests),
            'evaluations':evaluations,'pair_evaluations':pair_evaluations,'initial_single_rescue_candidates':single_rescues,
            'initial_no_extra_cost_rescue_candidates':no_extra_rescues,'steps':steps,
            'final_makespan_us':current.schedule['makespan_us'],'final_cost_ncu':current.schedule['compute_cost_ncu'],
            'final_joint_feasible':current.joint_feasible,'final_schedule':current.schedule if steps else None}


def run_instance(dataset,info):
    inp=dataset.load_development_input(info['instance_id'])
    base,registry=inp.instance,stage8_registry()
    before=content_sha256(dict(base))
    rows,diagnostics,schedules,decisions,evaluations,traces=[],[],[],{},{},{}
    for aid in registry.ids():
        scheduler=registry.get(aid)
        if aid in ('bdc_ifc_w05','bddc_ifc_w05'):
            decision,trace=traced_policy(scheduler,inp)
            traces[aid]=trace
        else:
            decision=scheduler.schedule(inp,seed=None)
        ev=evaluate_decision(inp,decision)
        assert before==content_sha256(dict(base)), 'policy changed immutable input'
        decisions[aid],evaluations[aid]=decision,ev
        r={k:ev.schedule[k] for k in ('schedule_id','makespan_us','compute_cost_ncu','compute_energy_nj','network_energy_pj')}
        r.update(instance_id=inp.instance_id,algorithm_id=aid,algorithm_version=scheduler.algorithm_version,
                 deadline_us=inp.deadline_us,budget_ncu=inp.budget_ncu,deadline_met=ev.deadline_feasible,budget_met=ev.budget_feasible,
                 joint_feasible=ev.joint_feasible,algorithm_internal_statistics=dict(decision.internal_statistics))
        rows.append(r)
        diag,_=path_diagnostics(base,ev)
        diagnostics.append({'instance_id':inp.instance_id,'algorithm_id':aid,**diag})
        schedules.append({'instance_id':inp.instance_id,'algorithm_id':aid,'task_order':list(decision.task_order),'schedule':ev.schedule})
    byid={r['algorithm_id']:r for r in rows}
    bdc=byid['bdc_ifc_w05']
    info['heft_matches_fast_anchor']=byid['deterministic_heft_ifc']['schedule_id']==info['fast_schedule_id']
    failure=None
    if not bdc['deadline_met']:
        ev=evaluations['bdc_ifc_w05']
        diag,aux=path_diagnostics(base,ev)
        trace=traces['bdc_ifc_w05']
        children=defaultdict(list)
        for edge in base['dependencies']:
            children[edge['parent']].append(edge['child'])
        tail={}
        for t in reversed(decisions['bdc_ifc_w05'].task_order):
            tail[t]=max((min(base['execution_time_us'][c].values())+tail[c] for c in children[t]),default=0)
        first_impossible=None
        for position,t in enumerate(trace,1):
            if t['end_us']+tail[t['task_id']]>inp.deadline_us:
                first_impossible={'position':position,'task_id':t['task_id'],'scheduled_tasks':len(trace),
                                  'spent_ncu':inp.budget_ncu-t['remaining_before_ncu']+t['cost_ncu'],
                                  'optimistic_completion_us':t['end_us']+tail[t['task_id']]}
                break
        failure={**info,'makespan_us':bdc['makespan_us'],'compute_cost_ncu':bdc['compute_cost_ncu'],
                 'unused_budget_ncu':inp.budget_ncu-bdc['compute_cost_ncu'],'deadline_deficit_us':bdc['makespan_us']-inp.deadline_us,
                 'joint_feasible_alternatives':[a for a,r in byid.items() if r['joint_feasible']],
                 'alternatives_no_more_cost':[a for a,r in byid.items() if r['joint_feasible'] and r['compute_cost_ncu']<=bdc['compute_cost_ncu']],
                 'all_comparator_outcomes':{a:{k:r[k] for k in ('makespan_us','compute_cost_ncu','joint_feasible')} for a,r in byid.items()},
                 'diag':diag,'first_irrecoverable_fixed_prefix':first_impossible,
                 'locally_avoidable_subdeadline_misses':sum(t['locally_avoidable_subdeadline_miss'] for t in trace),
                 'negative_remaining_before_count':sum(t['remaining_before_ncu']<0 for t in trace),
                 'overspend_decisions':[{**t,'position':i+1} for i,t in enumerate(trace) if t['cost_ncu']>t['remaining_before_ncu']],
                 'prefix_cost_ncu':{str(p):sum(t['cost_ncu'] for t in trace[:math.ceil(len(trace)*p/100)]) for p in (25,50,75,90)},
                 'critical_tasks':[{'task_id':t,**aux['assignments'][t],'duration_us':aux['duration'][t],
                                   'wait_us':aux['wait'][t]} for t in sorted(aux['critical'],key=lambda t:(-aux['duration'][t],t))[:12]],
                 'counterfactual':counterfactual(inp,decisions['bdc_ifc_w05'],ev,decisions)}
    return rows,diagnostics,schedules,traces,failure


def run(args):
    args.output.mkdir(parents=True,exist_ok=True)
    dataset,metadata,manifest=prepare(args.archive,args.output.parent/('dev-'+str(args.shard)),args.shard,args.shards)
    rows,diagnostics,failures=[],[],[]
    started=time.time()
    with gzip.open(args.output/'schedules.jsonl.gz','wt') as sf, gzip.open(args.output/'traces.jsonl.gz','wt') as tf:
        for index,info in enumerate(metadata,1):
            outcomes,diags,schedules,traces,failure=run_instance(dataset,info)
            rows.extend(outcomes);diagnostics.extend(diags)
            for s in schedules:
                sf.write(json.dumps(s,separators=(',',':'),sort_keys=True)+'\n')
            for aid,trace in traces.items():
                tf.write(json.dumps({'instance_id':info['instance_id'],'algorithm_id':aid,'trace':trace},separators=(',',':'),sort_keys=True)+'\n')
            if failure:
                failures.append(failure)
            print(json.dumps({'shard':args.shard,'completed_instances':index,'bdc_failures':len(failures),'elapsed_s':round(time.time()-started)}),flush=True)
    for name,value in (('outcomes.json',rows),('metadata.json',metadata),('diagnostics.json',diagnostics),('failures.json',failures)):
        write(args.output/name,value)
    devsources={e['source_sha256'] for e in manifest['entries'] if e['split']=='development'}
    holdsources={e['source_sha256'] for e in manifest['entries'] if e['split']=='holdout'}
    write(args.output/'integrity.json',{'shard':args.shard,'instances_verified':len(metadata),'holdout_payloads_read':0,'calibration_files_read':0,
          'archive_sha256':BIND.dataset_artifact_sha256,'manifest_sha256':BIND.materialization_manifest_content_sha256,
          'benchmark_commit':BENCHMARK,'dataset_commit':BIND.dataset_code_commit_sha,
          'shared_source_workflows_across_splits':len(devsources&holdsources),'dev_unique_sources':len(devsources),'holdout_unique_sources':len(holdsources)})


def aggregate(args):
    args.output.mkdir(parents=True,exist_ok=True)
    rows,metadata,diagnostics,failures,integrity=[],[],[],[],[]
    folders=sorted(p for p in args.aggregate.iterdir() if p.is_dir())
    for folder in folders:
        for name,target in (('outcomes.json',rows),('metadata.json',metadata),('diagnostics.json',diagnostics),('failures.json',failures)):
            target.extend(json.loads((folder/name).read_text()))
        integrity.append(json.loads((folder/'integrity.json').read_text()))
    rows.sort(key=lambda r:(r['instance_id'],r['algorithm_id']))
    assert len(rows)==len({(r['instance_id'],r['algorithm_id']) for r in rows})==1120
    assert digest(rows)==OUTCOME_SHA, ('replay differs from original AWS outcomes',digest(rows))
    assert len(metadata)==len({m['instance_id'] for m in metadata})==160
    assert len(failures)==40
    aids=sorted({r['algorithm_id'] for r in rows});meta={m['instance_id']:m for m in metadata}
    def count(rr):
        return {'n':len(rr),'deadline_met':sum(r['deadline_met'] for r in rr),'budget_met':sum(r['budget_met'] for r in rr),
                'joint_feasible':sum(r['joint_feasible'] for r in rr),'both_fail':sum(not r['deadline_met'] and not r['budget_met'] for r in rr)}
    groups={d:{str(v):{a:count([r for r in rows if r['algorithm_id']==a and meta[r['instance_id']][d]==v]) for a in aids}
               for v in sorted({m[d] for m in metadata})} for d in DIMS}
    portfolio={m['instance_id']:[r['algorithm_id'] for r in rows if r['instance_id']==m['instance_id'] and r['joint_feasible']] for m in metadata}
    counts=Counter()
    for f in failures:
        d,cf,D=f['diag'],f['counterfactual'],f['deadline_us']
        for k,v in {'no_network_deadline_rescue':d['fixed_machine_order_no_network_makespan_us']<=D,
                    'no_contention_deadline_rescue':d['unlimited_resources_fixed_mapping_makespan_us']<=D,
                    'no_network_no_contention_deadline_rescue':d['no_network_no_contention_makespan_us']<=D,
                    'order_only_rescue':cf['order_only_rescued'],'remapping_rescue':cf['final_joint_feasible'],
                    'initial_single_rescue':cf['initial_single_rescue_candidates']>0,
                    'initial_no_extra_cost_rescue':cf['initial_no_extra_cost_rescue_candidates']>0,
                    'either_search_rescue':cf['order_only_rescued'] or cf['final_joint_feasible']}.items():
            counts[k]+=bool(v)
    summary={'original_aws_normalized_sha256':OUTCOME_SHA,'replay_normalized_sha256':digest(rows),'replayed_exact_matches':1120,
             'verified_critical_graphs':len(diagnostics),'development_witnesses_verified':160,'holdout_payloads_read':0,'calibration_files_read':0,
             'algorithms':{a:count([r for r in rows if r['algorithm_id']==a]) for a in aids},
             'portfolio_feasible_instances':sum(bool(v) for v in portfolio.values()),'no_comparator_feasible_ids':[i for i,v in portfolio.items() if not v],
             'bdc_failures_by_dimension':{d:dict(Counter(str(f[d]) for f in failures)) for d in DIMS},
             'bdc_spare_budget_pct_under_budget':stats(Fraction(100*f['unused_budget_ncu'],f['budget_ncu']) for f in failures if f['unused_budget_ncu']>=0),
             'bdc_deadline_excess_pct':stats(Fraction(100*f['deadline_deficit_us'],f['deadline_us']) for f in failures),
             'bdc_other_comparator_feasible':sum(bool(f['joint_feasible_alternatives']) for f in failures),
             'bdc_other_comparator_feasible_no_more_cost':sum(bool(f['alternatives_no_more_cost']) for f in failures),
             'bdc_cp_communication_pct':stats(Fraction(100*f['diag']['critical_path_communication_us'],f['makespan_us']) for f in failures),
             'bdc_contention_extension_pct':stats(Fraction(100*f['diag']['contention_extension_us'],f['makespan_us']) for f in failures),
             'bdc_avoidable_local_subdeadline_instances':sum(f['locally_avoidable_subdeadline_misses']>0 for f in failures),
             'bdc_negative_budget_instances':sum(f['negative_remaining_before_count']>0 for f in failures),
             'bdc_prefix_impossible_position_pct':stats(Fraction(100*f['first_irrecoverable_fixed_prefix']['position'],f['actual_task_count']) for f in failures if f['first_irrecoverable_fixed_prefix']),
             'bdc_prefix_impossible_budget_spent_pct':stats(Fraction(100*f['first_irrecoverable_fixed_prefix']['spent_ncu'],f['budget_ncu']) for f in failures if f['first_irrecoverable_fixed_prefix']),
             'bounded_counterfactuals':dict(counts),'counterfactual_mapping_evaluations':sum(f['counterfactual']['evaluations'] for f in failures),
             'heft_matches_fast_anchor':sum(m['heft_matches_fast_anchor'] for m in metadata),
             'budget_degenerate_development':sum(m['budget_degenerate'] for m in metadata),
             'free_resource_instances':sum(m['free_resources']>0 for m in metadata),
             'source_split_audit':{k:integrity[0][k] for k in ('shared_source_workflows_across_splits','dev_unique_sources','holdout_unique_sources')},
             'qos_anchor_ratios':{p:{'n':sum(m['qos_profile']==p for m in metadata),
                                    'deadline_over_fast':stats(Fraction(m['deadline_us'],m['t_fast_us']) for m in metadata if m['qos_profile']==p),
                                    'budget_over_fast_cost':stats(Fraction(m['budget_ncu'],m['cost_fast_ncu']) for m in metadata if m['qos_profile']==p)} for p in ('tight','moderate','relaxed')}}
    for name,value in (('summary.json',summary),('groups.json',groups),('metadata.json',metadata),('outcomes.json',rows),
                        ('diagnostics.json',diagnostics),('bdc_failures.json',failures),('integrity.json',integrity)):
        write(args.output/name,value)
    for name in ('schedules.jsonl.gz','traces.jsonl.gz'):
        with gzip.open(args.output/name,'wb') as out:
            for folder in folders:
                with gzip.open(folder/name,'rb') as src:
                    shutil.copyfileobj(src,out)
    shutil.copyfile(__file__,args.output/'investigate.py')
    write(args.output/'artifact_index.json',{p.name:{'bytes':p.stat().st_size,'sha256':sha256(p.read_bytes()).hexdigest()} for p in args.output.iterdir() if p.is_file()})
    print(json.dumps(summary,sort_keys=True,indent=2),flush=True)


if __name__=='__main__':
    p=argparse.ArgumentParser();p.add_argument('--archive',type=Path);p.add_argument('--shard',type=int,default=0)
    p.add_argument('--shards',type=int,default=8);p.add_argument('--aggregate',type=Path);p.add_argument('--output',type=Path,required=True)
    args=p.parse_args()
    if args.aggregate:aggregate(args)
    else:run(args)
