import asyncio
import os
import unittest
from types import SimpleNamespace
from unittest.mock import patch
from src.agent import observability as o

class Span:
    trace_id='a'*32
    id='b'*16
    def __init__(self): self.updates=[];self.ended=False
    def update(self,**kw):self.updates.append(kw)
    def update_trace(self,**kw):self.updates.append(kw)
    def end(self):self.ended=True
class Client:
    def __init__(self):self.spans=[];self.starts=[]
    def start_observation(self,**kw):
        s=Span();self.spans.append(s);self.starts.append(kw);return s

class TraceTests(unittest.TestCase):
    def test_disabled(self):
        with patch.dict(os.environ,{'ERP_LANGFUSE_ENABLED':'false'}):self.assertIsNone(o.client())
    def test_no_payload_leaks_and_parent(self):
        c=Client()
        with patch.object(o,'client',return_value=c),patch.dict(os.environ,{'ERP_TRACE_HASH_KEY':'local-test'}):
            t=o.Trace('PRIVATE-USER','PRIVATE-THREAD')
            t.callback.on_chain_start({}, {'secret':'PRIVATE'},run_id=1)
            t.callback.on_chat_model_start({},[['PRIVATE']],run_id=2,parent_run_id=1)
            t.callback.on_llm_end(SimpleNamespace(generations=[[SimpleNamespace(message=SimpleNamespace(usage_metadata={'input_tokens':5,'output_tokens':2}))]]),run_id=2)
            t.callback.on_chain_end({'answer':'PRIVATE'},run_id=1);t.finish('completed')
        self.assertNotIn('PRIVATE',str(c.starts)+str([s.updates for s in c.spans]))
        self.assertTrue(all(s.ended for s in c.spans))
        self.assertIn('trace_context',c.starts[-1])
    def test_export_failure_does_not_break_business(self):
        c=Client();c.start_observation=lambda **kw: (_ for _ in ()).throw(RuntimeError('secret'))
        with patch.object(o,'client',return_value=c):
            t=o.Trace('u','t');t.event('safe');t.finish('completed')
    def test_stream_status_and_context_isolation(self):
        c=Client()
        @o.traced_stream
        async def stream(user_id,thread_id,resume_data=None):
            await asyncio.sleep(0)
            yield 'event: token\ndata: {"content":"PRIVATE"}\n\n'
            yield 'event: done\ndata: {"interrupted": true}\n\n'
        async def go():
            async def run(u):return [s async for s in stream(u,u)]
            await asyncio.gather(run('u1'),run('u2'))
        with patch.object(o,'client',return_value=c),patch.dict(os.environ,{'ERP_TRACE_HASH_KEY':'test'}): asyncio.run(go())
        roots=[s for s in c.spans if any('session_id' in x.get('metadata',{}) for x in s.updates)]
        self.assertEqual(len(roots),2)
        self.assertNotEqual(roots[0].updates[0]['metadata']['session_id'],roots[1].updates[0]['metadata']['session_id'])
        self.assertTrue(all(s.updates[-1]['metadata']['status']=='interrupted' for s in roots))
        self.assertIsNone(o._current.get())
    def test_measure_preserves_error(self):
        @o.measured('test')
        def fn():raise ValueError('business')
        with self.assertRaises(ValueError):fn()
    def test_stream_exception_not_reported_completed(self):
        c=Client()
        @o.traced_stream
        async def stream(user_id,thread_id,resume_data=None):
            raise ValueError('PRIVATE')
            yield ''
        async def run():
            with self.assertRaises(ValueError):
                async for _ in stream('u','t'):pass
        with patch.object(o,'client',return_value=c),patch.dict(os.environ,{'ERP_TRACE_HASH_KEY':'test'}):asyncio.run(run())
        self.assertEqual(c.spans[0].updates[-1]['metadata']['status'],'failed')
    def test_business_tool_error_status(self):
        c=Client()
        with patch.object(o,'client',return_value=c),patch.dict(os.environ,{'ERP_TRACE_HASH_KEY':'test'}):
            t=o.Trace('u','t');t.callback.on_tool_start({'name':'order_create'},'PRIVATE',run_id=1)
            t.callback.on_tool_end('{"code":500,"message":"PRIVATE"}',run_id=1)
        self.assertTrue(c.spans[-1].updates[-1]['metadata']['failed'])
        self.assertNotIn('PRIVATE',str(c.spans[-1].updates))

if __name__=='__main__': unittest.main()
