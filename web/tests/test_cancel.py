import asyncio
import unittest
from unittest.mock import patch

import app


class FakeWebSocket:
    def __init__(self):
        self.messages = []

    async def send_json(self, msg):
        self.messages.append(msg)


class CancelDuringLlmTests(unittest.IsolatedAsyncioTestCase):
    async def asyncSetUp(self):
        self.orig_get_workflow = app.get_workflow
        self.orig_workflow_to_prompt_api = app.workflow_to_prompt_api
        self.orig_translate_prompt = app.translate_prompt
        self.orig_submit_prompt = app.submit_prompt
        self.orig_interrupt_prompt = app.interrupt_prompt
        self.orig_push_status = app._push_status
        self.orig_broadcast = app._broadcast
        self.orig_current_run_task = app._current_run_task
        self.orig_active_cancel_event = app._active_cancel_event

    async def asyncTearDown(self):
        app.get_workflow = self.orig_get_workflow
        app.workflow_to_prompt_api = self.orig_workflow_to_prompt_api
        app.translate_prompt = self.orig_translate_prompt
        app.submit_prompt = self.orig_submit_prompt
        app.interrupt_prompt = self.orig_interrupt_prompt
        app._push_status = self.orig_push_status
        app._broadcast = self.orig_broadcast
        app._current_run_task = self.orig_current_run_task
        app._active_cancel_event = self.orig_active_cancel_event

    async def test_cancel_during_llm_does_not_submit_after_translation_returns(self):
        translate_started = asyncio.Event()
        allow_translate_return = asyncio.Event()
        submit_called = False

        async def fake_get_workflow(path):
            return {}

        def fake_workflow_to_prompt_api(data):
            return ({"1": {"inputs": {"text": "base"}, "class_type": "CLIPTextEncode"}}, ("1", "text"))

        async def fake_translate_prompt(prompt, original_prompt=None, on_chunk=None, cancel_event=None):
            translate_started.set()
            await allow_translate_return.wait()
            return "translated"

        async def fake_submit_prompt(prompt):
            nonlocal submit_called
            submit_called = True
            return "prompt-id"

        async def noop_async(*args, **kwargs):
            return None

        app.get_workflow = fake_get_workflow
        app.workflow_to_prompt_api = fake_workflow_to_prompt_api
        app.translate_prompt = fake_translate_prompt
        app.submit_prompt = fake_submit_prompt
        app.interrupt_prompt = noop_async
        app._push_status = noop_async
        app._broadcast = noop_async
        app._current_run_task = None
        app._active_cancel_event = asyncio.Event()

        req = app.RunRequest(workflow_path="wf.json", nl_prompt="翻译这个")
        ws = FakeWebSocket()
        run_task = asyncio.create_task(app._run_task(ws, req))
        await translate_started.wait()

        await app.api_interrupt()
        allow_translate_return.set()
        await run_task

        self.assertFalse(submit_called)
        self.assertTrue(any(m.get("type") == "error" and m.get("message") == "已取消" for m in ws.messages))

    async def test_translate_prompt_stops_streaming_when_cancelled(self):
        cancel_event = asyncio.Event()
        chunks_seen = []

        class FakeStreamResponse:
            def raise_for_status(self):
                return None

            async def aiter_lines(self):
                yield 'data: {"choices":[{"delta":{"content":"hello"}}]}'
                cancel_event.set()
                yield 'data: {"choices":[{"delta":{"content":" world"}}]}'
                yield "data: [DONE]"

            async def __aenter__(self):
                return self

            async def __aexit__(self, exc_type, exc, tb):
                return False

        class FakeClient:
            def __init__(self, *args, **kwargs):
                pass

            async def __aenter__(self):
                return self

            async def __aexit__(self, exc_type, exc, tb):
                return False

            def stream(self, *args, **kwargs):
                return FakeStreamResponse()

        async def on_chunk(piece):
            chunks_seen.append(piece)

        with patch("app.httpx.AsyncClient", FakeClient):
            with self.assertRaises(asyncio.CancelledError):
                await app.translate_prompt("abc", on_chunk=on_chunk, cancel_event=cancel_event)

        self.assertEqual(chunks_seen, ["hello"])


if __name__ == "__main__":
    unittest.main()
