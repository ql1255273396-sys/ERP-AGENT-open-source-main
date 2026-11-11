"""Verify current live evaluation traces, never print callback payloads."""
import json
from pathlib import Path
from concurrent.futures import ThreadPoolExecutor
from src.agent import env_utils
from src.agent.observability import client
from evals.business.run import summarize


def main():
    base=Path('evals/business/results')
    dirs=[base/'langfuse-live-base-20261023',base/'langfuse-live-extended-20261023']
    rows=[json.loads(line) for d in dirs for line in (d/'results.jsonl').read_text().splitlines()]
    c=client()
    def verify(row):
        try:
            observations=c.api.observations.get_many(trace_id=row['trace_id'],limit=1000,fields='basic,io,usage,model')
            data=observations.data
            return {'id':row['id'],'trace_id':row['trace_id'],'observations':len(data),
                    'root_found':any(x.name=='erp.request' for x in data),
                    'generations':sum(x.type=='GENERATION' for x in data),
                    'payloads_empty':all(x.input in (None,'',{},[]) and x.output in (None,'',{},[]) for x in data),
                    'has_more':bool(observations.meta.cursor)}
        except Exception as exc:
            return {'id':row['id'],'error':type(exc).__name__}
    with ThreadPoolExecutor(max_workers=4) as pool:checks=list(pool.map(verify,rows))
    (base/'langfuse-live-cloud-checks-20261023.json').write_text(json.dumps(checks,indent=2))
    scores=c.api.scores.get_many(name='task_acceptance',limit=100,fields='subject')
    trace_ids={r.get('trace_id') for r in rows}
    matched=[s for s in scores.data if s.subject and s.subject.kind=='trace' and s.subject.id in trace_ids]
    report={'scope':'real model + production graph + simulated ERP; no real ERP writes',
            'summary':summarize(rows),'cloud_verification':checks,
            'acceptance_scores_verified':len(matched),
            'example_trace_url':c.get_trace_url(trace_id=rows[0]['trace_id'])}
    output=base/'langfuse-live-report-20261023.json'
    output.write_text(json.dumps(report,ensure_ascii=False,indent=2))
    print(json.dumps({'summary':report['summary'],'cloud_verified':sum(r.get('root_found',False) for r in checks),
        'payloads_empty':all(r.get('payloads_empty',False) for r in checks),
        'observations':sum(r.get('observations',0) for r in checks),
        'generations':sum(r.get('generations',0) for r in checks),
        'scores_verified':len(matched),'trace_url':report['example_trace_url'],'report':str(output)},ensure_ascii=False))


if __name__=='__main__':main()
