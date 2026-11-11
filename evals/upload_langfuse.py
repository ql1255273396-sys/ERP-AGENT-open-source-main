"""Explicit replay of fixed synthetic reports. Default: local dry run, no network.

Imported spans describe historical results, NOT new model executions. No arbitrary
file upload and no business conversation bodies are supported.
"""
import argparse
import json
from pathlib import Path
from src.agent import env_utils
from src.agent.observability import client

ROOT=Path(__file__).parent

def records(suite):
    paths=[ROOT/'business/results'/x/'results.jsonl' for x in ('test-v1','extended-v1')] if suite=='business' else [ROOT/'review_routing/results/paired-v1/results.jsonl']
    for path in paths:
        for line in path.read_text().splitlines():
            r=json.loads(line)
            if suite=='business':
                yield r['id'], {'suite':suite,'batch':path.parent.name,'historical_import':True,'seconds':r['seconds']},r['checks']
            else:
                yield r['id']+'-'+r['provider'], {'suite':suite,'split':r['split'],'provider':r['provider'],'ambiguous':r['ambiguous'],'elapsed_ms':r['elapsed_ms'],'historical_import':True}, {
                    'label_match':r['label']==r['prediction'],
                    'false_negative':r['label']=='review' and r['prediction']=='skip',
                    'false_positive':r['label']=='skip' and r['prediction']=='review'}

def main():
    p=argparse.ArgumentParser();p.add_argument('--suite',choices=['business','routing'],required=True);p.add_argument('--send',action='store_true');a=p.parse_args()
    rows=list(records(a.suite)); print(f'{len(rows)} historical evaluation records; send={a.send}')
    if not a.send:return
    c=client()
    if c is None:raise SystemExit('Tracing configuration unavailable')
    if not c.auth_check():raise SystemExit('Authentication failed')
    for case,meta,checks in rows:
        span=c.start_observation(name='eval.historical',metadata={**meta,'case_id':case})
        for name,value in checks.items():
            c.create_score(trace_id=span.trace_id,name=name,value=int(bool(value)),data_type='BOOLEAN')
        span.end()
    c.flush()
    print('Submitted; check Langfuse for ingestion. Repeated sends create a separate import.')

if __name__=='__main__':main()
