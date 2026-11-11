"""Live HTTP/model/MCP/ERP acceptance plus memory and isolation probes.

Only creates uniquely prefixed test data. Never retries an order submission.
Synthetic task descriptions may be uploaded; ERP payloads stay local.
"""
import json
import argparse
import time
import uuid
from pathlib import Path
import httpx
from src.agent import env_utils
from src.agent.observability import client, pseudonym
from src.mcp_server.server_config import ERP_BASE_URL


def main():
    parser=argparse.ArgumentParser()
    parser.add_argument('--orders-only',action='store_true',help='Retest only approval cases after an SSE fix')
    args=parser.parse_args()
    batch='LF'+time.strftime('%Y%m%d%H%M%S')
    out=Path('evals/business/results')/('agent-live-'+batch)
    out.mkdir(parents=True)
    cloud=client()
    if cloud is None or not cloud.auth_check():raise RuntimeError('Langfuse unavailable')
    api=httpx.Client(base_url='http://127.0.0.1:8000',timeout=240,trust_env=False)
    erp=httpx.Client(base_url=ERP_BASE_URL,timeout=30)
    uid=batch+'-A';other=batch+'-B';rows=[]
    def get(path,**params):
        r=erp.get(path,params=params);r.raise_for_status();return r.json()
    def orders(number):
        payload=get('/api/orders/page',orderNumber=number,current=1,size=100)
        if payload.get('code')!=200:raise RuntimeError('ERP query failed')
        return [x for x in payload['data']['records'] if x.get('orderNumber')==number]
    def send(prompt,thread,user=uid,resume=None):
        path='/api/chat/stream' if resume is None else f'/api/chat/{thread}/resume'
        body={'message':prompt,'thread_id':thread,'user_id':user,'username':'Langfuse测试用户'} if resume is None else {'resume':resume}
        events=[];kind=None
        with api.stream('POST',path,json=body) as response:
            if response.status_code!=200:return {'status':response.status_code,'events':[],'text':'','tools':[]}
            for line in response.iter_lines():
                if line.startswith('event:'):kind=line[6:].strip()
                elif line.startswith('data:'):
                    events.append({'type':kind,'data':json.loads(line[5:])})
        text=''.join(x['data'].get('content','') for x in events if x['type']=='token' and x['data'].get('source','main')=='main')
        return {'status':200,'events':events,'text':text,'thread_id':thread,
                'tools':[x['data'].get('name') for x in events if x['type']=='tool_start']}
    def ok(r):return r['status']==200 and any(e['type']=='done' for e in r['events']) and not any(e['type']=='error' for e in r['events'])
    def record(title,description,fn):
        if args.orders_only and title not in ('真实订单审批通过','真实订单审批拒绝'):
            return None
        span=cloud.start_observation(name='实测：'+title,as_type='span',input=description,
            metadata={'suite':'agent-live','batch':batch,'synthetic_input':True,'real_erp':True,
                      'user_session_prefix':pseudonym(uid),'historical_import':False})
        start=time.perf_counter()
        try:
            checks,details=fn();error=None
        except Exception as exc:
            checks={'execution_completed':False};details={};error=type(exc).__name__
        row={'name':title,'description':description,'checks':checks,'passed':all(checks.values()),
             'seconds':round(time.perf_counter()-start,3),'error':error,'trace_id':span.trace_id,'details':details}
        rows.append(row)
        span.update(output={'checks':checks,'passed':row['passed'],'error_type':error})
        cloud.create_score(trace_id=span.trace_id,name='acceptance',value=int(row['passed']),data_type='BOOLEAN')
        span.end()
        (out/'results.json').write_text(json.dumps(rows,ensure_ascii=False,indent=2))
        print(json.dumps({k:v for k,v in row.items() if k!='details'},ensure_ascii=False),flush=True)
        return row

    # Authorized fixture creation, saved before any Agent order request.
    fixture={'partCode':batch,'name':'Langfuse验收专用零件'+batch,'purchasePrice':2.5,'unit':'件','stockWarningValue':0,'description':'自动验收测试数据，保留追溯'}
    response=erp.post('/api/parts/create',json=fixture);response.raise_for_status();created=response.json()
    (out/'fixture.json').write_text(json.dumps({'batch':batch,'fixture':fixture,'created':created},ensure_ascii=False,indent=2))
    if created.get('code')!=200:raise RuntimeError('Test part creation failed')
    found=get('/api/parts/search',name=fixture['name'])['data']
    part=next(x for x in found if x['partCode']==batch);pid=part['id']
    def simple(prompt,thread,assertions,user=uid):
        r=send(prompt,thread,user)
        return {'http_completed':ok(r),**assertions(r)},r
    record('真实零件查询','查询测试零件并返回实际采购单价。',lambda:simple(
        f'查询零件ID={pid}的采购单价，不要写入任何数据，最后明确给出单价。',batch+'-lookup',
        lambda r:{'queried_tool':'part_query' in r['tools'],'correct_price':'2.5' in r['text']}))
    record('Skills按需读取','列出可用Skills，再读取一个技能说明，不执行该技能。',lambda:simple(
        '请调用list_skills列出技能，再选择一个调用read_skill读取说明，告诉我技能名即可；不要执行技能，不要创建文件。',batch+'-skills',
        lambda r:{'listed':'list_skills' in r['tools'],'loaded':'read_skill' in r['tools']}))
    marker='蓝鲸'+uuid.uuid4().hex[:8]
    record('记忆显式写入','通过remember保存合成的用户项目代号。',lambda:simple(
        f'请调用remember工具，key固定为test_project_code，记住我的测试项目代号是{marker}。',batch+'-remember',
        lambda r:{'remember_called':'remember' in r['tools']}))
    record('记忆跨会话召回','在新会话中检索之前保存的项目代号。',lambda:simple(
        '我之前让你记住的测试项目代号是什么？请先用read_memory检索再回答，不要猜测。',batch+'-recall',
        lambda r:{'read_memory_called':'read_memory' in r['tools'],'correct_recall':marker in r['text']}))
    record('不同用户记忆隔离','另一用户检索项目代号，不能得到前一用户的测试标记。',lambda:simple(
        '请用read_memory查询我的测试项目代号。没有记录就说没有，不要猜测。',batch+'-isolation',
        lambda r:{'read_memory_called':'read_memory' in r['tools'],'no_cross_user_marker':marker not in json.dumps(r,ensure_ascii=False)},other))
    record('会话归属检查','另一用户不得向已有会话发送消息。',lambda:(
        {'rejected_403':send('你好',batch+'-lookup',other)['status']==403},{}))

    def approval(kind):
        number=batch+('-YES' if kind=='approve' else '-NO');thread=batch+'-'+kind
        prompt=f'创建测试采购订单：orderNumber={number}，partId={pid}，quantity=1，unitPrice=2.5，totalAmount=2.5，status=0，remark=Langfuse自动验收。信息完整，请推进到order_create的人工审批并等待决定，不要修改其他数据。'
        r=send(prompt,thread)
        # Do not duplicate requests if a network error or missing interrupt occurs.
        actions=[e['data'].get('order_data') for e in r['events'] if e['type']=='interrupt' and e['data'].get('interrupt_type')=='hitl_approval']
        pending=next((a for a in actions if isinstance(a,list) and a),[])
        before=orders(number)
        checks={'http_completed':ok(r),'approval_observed':bool(pending),'no_preapproval_write':not before}
        safe=True
        for a in pending:
            data=a.get('args',{}).get('order_data',{})
            if isinstance(data,str):data=json.loads(data)
            ds=data.get('orderDetail',[])
            safe &= a.get('name')=='order_create' and data.get('orderNumber')==number and len(ds)==1 and ds[0].get('partId')==pid and ds[0].get('quantity')==1 and ds[0].get('unitPrice')==2.5
        checks['approved_payload_in_scope']=bool(pending) and safe
        resumed=None
        if pending and safe and not before:
            resumed=send('',thread,resume={'decisions':[{'type':kind} for _ in pending]})
            checks['resume_completed']=ok(resumed)
        after=orders(number)
        checks['correct_write_count']=len(after)==(1 if kind=='approve' else 0)
        if kind=='approve':
            ds=after[0].get('orderDetail',[]) if len(after)==1 else []
            checks['persisted_order_correct']=len(ds)==1 and ds[0].get('partId')==pid and ds[0].get('quantity')==1 and ds[0].get('unitPrice')==2.5
        return checks,{'thread_id':thread,'order_number':number,'before':before,'after':after,'initial':r,'resumed':resumed}
    record('真实订单审批通过','真实ERP：确认审批前没有订单，批准后应仅创建一张指定测试订单。',lambda:approval('approve'))
    record('真实订单审批拒绝','真实ERP：拒绝审批后不得创建测试订单。',lambda:approval('reject'))
    record('不存在零件的异常处理','查询不存在的零件，不应捏造查到记录。',lambda:simple(
        '请用part_query查询零件ID=999999999，如果不存在或接口报错请如实说明，不要创建数据。',batch+'-missing',
        lambda r:{'queried_tool':'part_query' in r['tools'],'acknowledged_missing':any(x in r['text'] for x in ['不存在','未找到','没有找到','失败','错误','未查询到','无此'])}))
    cloud.flush()
    report={'batch':batch,'total':len(rows),'passed':sum(r['passed'] for r in rows),'fixture_part_id':pid,
            'created_order_numbers':[r['details']['order_number'] for r in rows if r['name']=='真实订单审批通过' and r['details'].get('after')],
            'trace_url':cloud.get_trace_url(trace_id=rows[0]['trace_id'])}
    (out/'summary.json').write_text(json.dumps(report,ensure_ascii=False,indent=2));print(json.dumps(report,ensure_ascii=False),flush=True)


if __name__=='__main__':main()
