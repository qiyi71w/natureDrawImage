import asyncio
import unittest

import app


class FakeWebSocket:
    def __init__(self):
        self.messages = []

    async def send_json(self, msg):
        self.messages.append(msg)


class RunModeTests(unittest.IsolatedAsyncioTestCase):
    async def asyncSetUp(self):
        self.orig_get_workflow = app.get_workflow
        self.orig_workflow_to_prompt_api = app.workflow_to_prompt_api
        self.orig_translate_prompt = app.translate_prompt
        self.orig_submit_prompt = app.submit_prompt
        self.orig_wait_for = app._wait_for
        self.orig_push_status = app._push_status
        self.orig_broadcast = app._broadcast
        self.orig_active_cancel_event = app._active_cancel_event

    async def asyncTearDown(self):
        app.get_workflow = self.orig_get_workflow
        app.workflow_to_prompt_api = self.orig_workflow_to_prompt_api
        app.translate_prompt = self.orig_translate_prompt
        app.submit_prompt = self.orig_submit_prompt
        app._wait_for = self.orig_wait_for
        app._push_status = self.orig_push_status
        app._broadcast = self.orig_broadcast
        app._active_cancel_event = self.orig_active_cancel_event

    async def _run_case(self, req, translated_text="translated tags", builtin_text="builtin tags"):
        translate_calls = []
        submitted_prompts = []

        async def fake_get_workflow(path):
            return {}

        def fake_workflow_to_prompt_api(data):
            prompt_dict = {
                "1": {"inputs": {"text": builtin_text}, "class_type": "CLIPTextEncode"},
                "2": {"inputs": {"seed": 1}, "class_type": "KSampler"},
            }
            return prompt_dict, ("1", "text")

        async def fake_translate_prompt(prompt, original_prompt=None, on_chunk=None, cancel_event=None):
            translate_calls.append({
                "prompt": prompt,
                "original_prompt": original_prompt,
                "has_on_chunk": on_chunk is not None,
                "cancel_event": cancel_event,
            })
            return translated_text

        async def fake_submit_prompt(prompt):
            submitted_prompts.append(prompt)
            return "prompt-id"

        async def fake_wait_for(prompt_id, ws, prompt_dict, timeout=600):
            return {
                "outputs": {
                    "save": {
                        "images": [{"filename": "x.png", "subfolder": "", "type": "output"}]
                    }
                }
            }

        async def noop_async(*args, **kwargs):
            return None

        app.get_workflow = fake_get_workflow
        app.workflow_to_prompt_api = fake_workflow_to_prompt_api
        app.translate_prompt = fake_translate_prompt
        app.submit_prompt = fake_submit_prompt
        app._wait_for = fake_wait_for
        app._push_status = noop_async
        app._broadcast = noop_async
        app._active_cancel_event = asyncio.Event()

        ws = FakeWebSocket()
        await app._run_task(ws, req)
        return ws, translate_calls, submitted_prompts

    async def test_rewrite_mode_uses_base_as_original_prompt(self):
        req = app.RunRequest(
            workflow_path="wf.json",
            direct_prompt="direct tags",
            nl_prompt="重写这个",
            rewrite=True,
            translate=False,
        )

        ws, translate_calls, submitted_prompts = await self._run_case(req, translated_text="rewritten")

        self.assertEqual(len(translate_calls), 1)
        self.assertEqual(translate_calls[0]["original_prompt"], "builtin tags, direct tags")
        self.assertEqual(submitted_prompts[0]["1"]["inputs"]["text"], "rewritten")
        self.assertTrue(any(m.get("type") == "prompt_id" and m.get("final_prompt") == "rewritten" for m in ws.messages))

    async def test_translate_mode_appends_translated_text_to_base(self):
        req = app.RunRequest(
            workflow_path="wf.json",
            direct_prompt="direct tags",
            nl_prompt="翻译这个",
            rewrite=False,
            translate=True,
        )

        ws, translate_calls, submitted_prompts = await self._run_case(req, translated_text="translated")

        self.assertEqual(len(translate_calls), 1)
        self.assertIsNone(translate_calls[0]["original_prompt"])
        self.assertEqual(submitted_prompts[0]["1"]["inputs"]["text"], "builtin tags, direct tags, translated")
        self.assertTrue(any(m.get("type") == "prompt_id" and m.get("final_prompt") == "builtin tags, direct tags, translated" for m in ws.messages))

    async def test_disabling_both_modes_skips_llm_and_uses_direct_prompt_only(self):
        req = app.RunRequest(
            workflow_path="wf.json",
            direct_prompt="direct tags",
            nl_prompt="这段应该被忽略",
            rewrite=False,
            translate=False,
        )

        ws, translate_calls, submitted_prompts = await self._run_case(req)

        self.assertEqual(translate_calls, [])
        self.assertEqual(submitted_prompts[0]["1"]["inputs"]["text"], "direct tags")
        self.assertTrue(any(m.get("type") == "log" and "跳过 LLM" in m.get("message", "") for m in ws.messages))

    async def test_disabling_both_modes_requires_direct_prompt(self):
        req = app.RunRequest(
            workflow_path="wf.json",
            direct_prompt="",
            nl_prompt="这段应该被忽略",
            rewrite=False,
            translate=False,
        )

        ws, translate_calls, submitted_prompts = await self._run_case(req, builtin_text="")

        self.assertEqual(translate_calls, [])
        self.assertEqual(submitted_prompts, [])
        self.assertTrue(any(
            m.get("type") == "error" and "直接 Tag" in m.get("message", "")
            for m in ws.messages
        ))


if __name__ == "__main__":
    unittest.main()
