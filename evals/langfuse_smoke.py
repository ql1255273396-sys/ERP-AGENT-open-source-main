"""Synthetic live SDK smoke: no real ERP or external model invocation."""
import asyncio
from langchain.agents import create_agent
from langchain_core.language_models.fake_chat_models import FakeListChatModel
from src.agent import env_utils
from src.agent.observability import Trace, client

async def main():
    c=client()
    if c is None or not c.auth_check():raise SystemExit('Langfuse configuration/auth unavailable')
    t=Trace('synthetic-sdk-test','synthetic-sdk-session')
    graph=create_agent(model=FakeListChatModel(responses=['Synthetic response']))
    try:
        await graph.ainvoke({'messages':[('user','Synthetic private text must not be exported')]},
                            config={'callbacks':[t.callback]})
        t.finish('completed')
    except BaseException:
        t.finish('failed');raise
    c.flush()
    print('trace_id',t.root.trace_id)
    print('graph completed with scripted model; verify ingestion separately')

if __name__=='__main__':asyncio.run(main())
