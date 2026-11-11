"""Attach Chinese synthetic case descriptions to existing backend traces.

This is post-run annotation, not another model invocation or ERP write.
"""
import json
from pathlib import Path
from concurrent.futures import ThreadPoolExecutor
from src.agent import env_utils
from src.agent.observability import client,pseudonym

SUFFIX={'真实零件查询':'lookup','Skills按需读取':'skills','记忆显式写入':'remember',
        '记忆跨会话召回':'recall','不同用户记忆隔离':'isolation','真实订单审批通过':'approve',
        '真实订单审批拒绝':'reject','不存在零件的异常处理':'missing'}

def main():
    base=Path('evals/business/results');c=client()
    jobs=[]
    for path in sorted(base.glob('agent-live-LF*/results.json')):
        batch=json.loads((path.parent/'summary.json').read_text())['batch']
        jobs.extend((batch,row) for row in json.loads(path.read_text()))
    def annotate(job):
        batch,row=job;result={'batch':batch,'name':row['name'],'backend_trace_urls':[]}
        try:
            # Repair missing summary export only; preserve original case trace ID.
            visible=c.api.observations.get_many(trace_id=row['trace_id'],limit=1,fields='basic').data
            if not visible:
                s=c.start_observation(name='补传验收报告：'+row['name'],as_type='span',
                    trace_context={'trace_id':row['trace_id']},input=row['description'],
                    metadata={'report_replay':True,'batch':batch,'not_a_new_execution':True})
                s.update(output={'passed':row['passed'],'checks':row['checks']});s.end()
                result['summary_replayed']=True
            if row['name'] in SUFFIX:
                session=pseudonym(batch+'-'+SUFFIX[row['name']])
                roots=c.api.observations.get_many(session_id=session,name='erp.request',limit=100,fields='basic').data
                for root in roots:
                    s=c.start_observation(name='验收说明：'+row['name'],as_type='span',
                        trace_context={'trace_id':root.trace_id,'parent_span_id':root.id},
                        input=row['description'],metadata={'post_run_annotation':True,'batch':batch,
                            'scope':'whole scenario assertion, not individual model response'})
                    s.update(output={'scenario_passed':row['passed'],'checks':row['checks']});s.end()
                    result['backend_trace_urls'].append(c.get_trace_url(trace_id=root.trace_id))
            result['case_trace_url']=c.get_trace_url(trace_id=row['trace_id'])
        except Exception as exc:result['error']=type(exc).__name__
        return result
    with ThreadPoolExecutor(max_workers=4) as pool:results=list(pool.map(annotate,jobs))
    c.flush()
    (base/'agent-live-evidence-links-20261023.json').write_text(json.dumps(results,ensure_ascii=False,indent=2))
    print(json.dumps(results,ensure_ascii=False),flush=True)

if __name__=='__main__':main()
