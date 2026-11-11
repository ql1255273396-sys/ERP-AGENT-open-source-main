"""Check cloud visibility without repeating real model or ERP operations."""
import json
from pathlib import Path
from concurrent.futures import ThreadPoolExecutor
from src.agent import env_utils
from src.agent.observability import client

def main():
    base=Path('evals/business/results')
    run=sorted(base.glob('agent-live-LF*/results.json'))[-1]
    rows=json.loads(run.read_text())+json.loads((base/'agent-component-20261023.json').read_text())
    c=client()
    def verify(row):
        try:
            observations=c.api.observations.get_many(trace_id=row['trace_id'],limit=100,fields='basic')
            return {'name':row.get('name',row.get('group')),'trace_id':row['trace_id'],
                    'visible':bool(observations.data),'observation_count':len(observations.data)}
        except Exception as exc:
            return {'name':row.get('name',row.get('group')),'trace_id':row['trace_id'],'visible':False,'error':type(exc).__name__}
    with ThreadPoolExecutor(max_workers=4) as pool:results=list(pool.map(verify,rows))
    (run.parent/'cloud_verification.json').write_text(json.dumps(results,ensure_ascii=False,indent=2))
    print(json.dumps(results,ensure_ascii=False),flush=True)

if __name__=='__main__':main()
