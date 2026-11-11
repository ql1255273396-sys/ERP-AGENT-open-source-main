"""Exercise the actual SSE adapter without Docker, MongoDB or model calls."""
import asyncio
import json
import unittest
from contextlib import ExitStack
from types import SimpleNamespace
from unittest.mock import AsyncMock, patch
from src.api_view.api import chat
from src.agent.backends.sandbox_manager import sandbox_manager


class ChatInterruptTests(unittest.IsolatedAsyncioTestCase):
    async def run_stream(self,key=None,value=None):
        async def stream(**kwargs):
            yield (), 'values', {key:[SimpleNamespace(value=value)]} if key else {}
        session=SimpleNamespace(agent=SimpleNamespace(astream=stream),run_lock=asyncio.Lock())
        with ExitStack() as stack:
            stack.enter_context(patch.object(chat.agent_loader,'get_session',AsyncMock(return_value=session)))
            stack.enter_context(patch.object(chat.agent_loader,'get_display_messages',AsyncMock(return_value=[])))
            for name in ['save_display_messages','save_harness_trace','save_conversation']:
                stack.enter_context(patch.object(chat.agent_loader,name,AsyncMock()))
            stack.enter_context(patch.object(sandbox_manager,'acquire_lease',return_value=False))
            chunks=[x async for x in chat.stream_chat_response.__wrapped__('test','test-thread','test-user')]
        self.assertFalse(session.run_lock.locked())
        return [(c.split('\n')[0][7:],json.loads(c.split('\n')[1][6:])) for c in chunks]

    async def test_modern_approval_interrupt(self):
        actions=[{'name':'order_create','args':{'order_data':'{}'}}]
        events=await self.run_stream('__interrupt__',{'action_requests':actions})
        self.assertEqual([v for k,v in events if k=='interrupt'][0]['order_data'],actions)
        self.assertTrue(events[-1][1]['interrupted'])

    async def test_legacy_interrupt(self):
        events=await self.run_stream('interrupts',{'action_requests':[]})
        self.assertTrue(events[-1][1]['interrupted'])

    async def test_missing_fields_interrupt(self):
        events=await self.run_stream('__interrupt__',{'type':'order_info_request','missing_fields':['quantity']})
        payload=[v for k,v in events if k=='interrupt'][0]
        self.assertEqual(payload['interrupt_type'],'order_info_supplement')
        self.assertEqual(payload['missing_fields'],['quantity'])

    async def test_uninterrupted_completion(self):
        events=await self.run_stream()
        self.assertFalse(events[-1][1]['interrupted'])
        self.assertFalse(any(k=='interrupt' for k,v in events))
