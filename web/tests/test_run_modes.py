import asyncio
import copy
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
                "2": {"inputs": {"seed": 1, "steps": 20}, "class_type": "KSampler"},
            }
            return prompt_dict, ("1", "text")

        async def fake_translate_prompt(prompt, original_prompt=None, mode="translate", on_chunk=None, cancel_event=None):
            translate_calls.append({
                "prompt": prompt,
                "original_prompt": original_prompt,
                "mode": mode,
                "has_on_chunk": on_chunk is not None,
                "cancel_event": cancel_event,
            })
            if isinstance(translated_text, list):
                return translated_text[len(translate_calls) - 1]
            return translated_text

        async def fake_submit_prompt(prompt):
            submitted_prompts.append(copy.deepcopy(prompt))
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
        )

        ws, translate_calls, submitted_prompts = await self._run_case(req, translated_text="rewritten")

        self.assertEqual(len(translate_calls), 1)
        self.assertEqual(translate_calls[0]["original_prompt"], "direct tags")
        self.assertEqual(translate_calls[0]["mode"], "translate")
        self.assertEqual(submitted_prompts[0]["1"]["inputs"]["text"], "rewritten")
        self.assertTrue(any(m.get("type") == "prompt_id" and m.get("final_prompt") == "rewritten" for m in ws.messages))

    async def test_rewrite_mode_uses_builtin_when_direct_prompt_is_empty(self):
        req = app.RunRequest(
            workflow_path="wf.json",
            direct_prompt="",
            nl_prompt="重写这个",
            rewrite=True,
        )

        ws, translate_calls, submitted_prompts = await self._run_case(req, translated_text="rewritten")

        self.assertEqual(len(translate_calls), 1)
        self.assertEqual(translate_calls[0]["original_prompt"], "builtin tags")
        self.assertEqual(translate_calls[0]["mode"], "translate")
        self.assertEqual(submitted_prompts[0]["1"]["inputs"]["text"], "rewritten")
        self.assertTrue(any(m.get("type") == "prompt_id" and m.get("final_prompt") == "rewritten" for m in ws.messages))

    async def test_nl_prompt_without_rewrite_appends_translated_text_to_base(self):
        req = app.RunRequest(
            workflow_path="wf.json",
            direct_prompt="direct tags",
            nl_prompt="翻译这个",
            rewrite=False,
        )

        ws, translate_calls, submitted_prompts = await self._run_case(req, translated_text="translated")

        self.assertEqual(len(translate_calls), 1)
        self.assertIsNone(translate_calls[0]["original_prompt"])
        self.assertEqual(translate_calls[0]["mode"], "translate")
        self.assertEqual(submitted_prompts[0]["1"]["inputs"]["text"], "builtin tags, direct tags, translated")
        self.assertTrue(any(m.get("type") == "prompt_id" and m.get("final_prompt") == "builtin tags, direct tags, translated" for m in ws.messages))

    async def test_expand_mode_appends_expanded_text_to_base(self):
        req = app.RunRequest(
            workflow_path="wf.json",
            direct_prompt="direct tags",
            nl_prompt="海边夏天",
            llm_mode="expand",
        )

        ws, translate_calls, submitted_prompts = await self._run_case(req, translated_text="expanded tags")

        self.assertEqual(len(translate_calls), 1)
        self.assertIsNone(translate_calls[0]["original_prompt"])
        self.assertEqual(translate_calls[0]["mode"], "expand")
        self.assertEqual(submitted_prompts[0]["1"]["inputs"]["text"], "builtin tags, direct tags, expanded tags")
        self.assertTrue(any(m.get("type") == "log" and "LLM 联想中" in m.get("message", "") for m in ws.messages))

    async def test_brainstorm_mode_appends_brainstorm_text_to_base(self):
        req = app.RunRequest(
            workflow_path="wf.json",
            direct_prompt="direct tags",
            nl_prompt="running, beach, sunset, sword",
            llm_mode="brainstorm",
        )

        ws, translate_calls, submitted_prompts = await self._run_case(req, translated_text="brainstorm tags")

        self.assertEqual(len(translate_calls), 1)
        self.assertIsNone(translate_calls[0]["original_prompt"])
        self.assertEqual(translate_calls[0]["mode"], "brainstorm")
        self.assertEqual(submitted_prompts[0]["1"]["inputs"]["text"], "builtin tags, direct tags, brainstorm tags")
        self.assertTrue(any(m.get("type") == "log" and "LLM 脑洞中" in m.get("message", "") for m in ws.messages))

    async def test_batch_can_rerun_llm_for_each_round(self):
        req = app.RunRequest(
            workflow_path="wf.json",
            direct_prompt="direct tags",
            nl_prompt="海边夏天",
            llm_mode="expand",
            batch=2,
            rerun_llm_each_batch=True,
        )

        ws, translate_calls, submitted_prompts = await self._run_case(req, translated_text=["expanded one", "expanded two"])

        self.assertEqual(len(translate_calls), 2)
        self.assertEqual(len(submitted_prompts), 2)
        self.assertEqual(submitted_prompts[0]["1"]["inputs"]["text"], "builtin tags, direct tags, expanded one")
        self.assertEqual(submitted_prompts[1]["1"]["inputs"]["text"], "builtin tags, direct tags, expanded two")
        llm_done = [m for m in ws.messages if m.get("type") == "llm_done"]
        self.assertEqual([m.get("text") for m in llm_done], ["expanded one", "expanded two"])
        image_events = [m for m in ws.messages if m.get("type") == "image"]
        self.assertEqual([m.get("round") for m in image_events], [1, 2])

    async def test_empty_nl_prompt_skips_llm_and_uses_base(self):
        req = app.RunRequest(
            workflow_path="wf.json",
            direct_prompt="direct tags",
            nl_prompt="",
            rewrite=False,
        )

        ws, translate_calls, submitted_prompts = await self._run_case(req)

        self.assertEqual(translate_calls, [])
        self.assertEqual(submitted_prompts[0]["1"]["inputs"]["text"], "builtin tags, direct tags")
        self.assertTrue(any(m.get("type") == "log" and "跳过 LLM" in m.get("message", "") for m in ws.messages))

    async def test_override_excludes_builtin_from_base(self):
        req = app.RunRequest(
            workflow_path="wf.json",
            direct_prompt="direct tags",
            nl_prompt="",
            rewrite=False,
            override=True,
        )

        ws, translate_calls, submitted_prompts = await self._run_case(req)

        self.assertEqual(translate_calls, [])
        self.assertEqual(submitted_prompts[0]["1"]["inputs"]["text"], "direct tags")
        self.assertTrue(any(
            m.get("type") == "log" and "覆写模式" in m.get("message", "")
            for m in ws.messages
        ))

    async def test_steps_override_updates_sampler_steps(self):
        req = app.RunRequest(
            workflow_path="wf.json",
            direct_prompt="direct tags",
            steps=30,
        )

        ws, translate_calls, submitted_prompts = await self._run_case(req)

        self.assertEqual(translate_calls, [])
        self.assertEqual(submitted_prompts[0]["2"]["inputs"]["steps"], 30)
        self.assertTrue(any(
            m.get("type") == "log" and "步数覆盖为 30" in m.get("message", "")
            for m in ws.messages
        ))


if __name__ == "__main__":
    unittest.main()
