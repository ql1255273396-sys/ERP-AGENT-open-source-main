"""Read-only synthetic HTTP smoke against an already running local backend."""
import json
import time
import uuid
from pathlib import Path
from urllib.request import Request, urlopen


def main():
    run_id='langfuse-http-'+uuid.uuid4().hex[:12]
    rows=[]
    for prompt in ['你好，请只回复：你好。', '不调用任何工具，请计算 17 加 25，回答结果。']:
        started=time.perf_counter()
        payload={'message':prompt,'user_id':run_id,'username':'合成验收用户','thread_id':run_id}
        request=Request('http://127.0.0.1:8000/api/chat/stream',
                        data=json.dumps(payload).encode(),headers={'Content-Type':'application/json'})
        events=[]
        error=None
        try:
            with urlopen(request,timeout=240) as response:
                for line in response:
                    text=line.decode().strip()
                    if text.startswith('event:'):events.append(text[6:].strip())
        except Exception as exc:
            error=type(exc).__name__
        rows.append({'seconds':round(time.perf_counter()-started,3),'events':events,'error':error,
                     'transport_completed':error is None and 'done' in events and 'error' not in events})
        print(json.dumps(rows[-1]),flush=True)
    output=Path('evals/business/results')/run_id
    output.mkdir(parents=True)
    (output/'http_summary.json').write_text(json.dumps({'run_id':run_id,'rows':rows,
        'scope':'real HTTP/backend/model/MongoDB; benign prompts; no ERP write; transport check, not semantic acceptance'},indent=2))
    print(str(output),flush=True)


if __name__=='__main__':main()
