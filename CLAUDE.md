# CLAUDE.md

This file provides guidance to Claude Code (claude.ai/code) when working with code in this repository.

## 运行 / 开发

```bash
pip install -r web/requirements.txt
python -m web.app                       # 默认 127.0.0.1:8080
python -m web.app --host 0.0.0.0        # 监听所有地址
python -m web.app --reload              # 热重载（保存 .py 自动重启）
uv run web/app.py --reload              # uv 等价
```

无构建步骤、无测试套件、无 lint 配置。前端是 `web/static/index.html` 单文件 + Tailwind CDN，改完直接刷新页面。

## 配置（硬编码在 `web/app.py` 顶部，没有 env 注入）

- `COMFYUI_HOST/PORT`（默认 `127.0.0.1:8000`）— 后端连的 ComfyUI 实例
- `LMS_HOST/PORT`（默认 `127.0.0.1:1234`）— LM Studio OpenAI 兼容服务
- `WEB_HOST/PORT` — Web 监听地址
- `OUTPUT_DIR_STR` — ComfyUI output 目录绝对路径（用于 `/api/output/*` 只读浏览）

改这些值要直接编辑文件顶部，不要新增 env/配置层除非用户要求。

## 架构要点

**单文件 FastAPI 后端 (`web/app.py`, ~935 行)**，前端是 `web/static/index.html`。后端不持有"当前工作流"状态——选择由前端 localStorage 维护，后端 `/api/workflows/select` 仅作向后兼容存根，运行时通过 `ws/run` 的 `workflow_path` 字段传入。

**关键转换：`workflow_to_prompt_api(workflow)`**（约 140–300 行）
把 ComfyUI 前端保存的"工作流 JSON"（含 nodes/links/definitions/subgraphs）转成 ComfyUI `/api/prompt` 接收的 "prompt API" 字典。注意点：
- 展开 `definitions.subgraphs`：subgraph 内部节点用 `f"{sg_id}:{node_id}"` 作为 prompt id；通过 `proxyWidgets` 把外层实例的 widget 值覆盖回内部节点
- 跳过非执行节点：`MarkdownNote / Note / Reroute / PrimitiveNode`
- seed widget 处理：`seed/noise_seed` 后的 `fixed/increment/decrement/randomize` 字符串要额外消耗一个 widget 槽位，否则后续 widgets 全错位
- 找正向 prompt 节点的优先级：CLIPTextEncode 的 title 含 `positive`/`[pos]`/`[prompt]` → 兜底从 KSampler 系节点的 `positive` 输入回溯
- 与 `dev/comfyui.py`（NoneBot Telegram 插件）保持同步实现

**任务并发**
全局 `_run_lock = asyncio.Lock()` 保证只有一个生图任务在跑。第二个 `/ws/run` 客户端会被立即拒绝并附带 `busy: True`。

**双 WebSocket**
- `/ws/run` — 发起任务 + 接收本任务事件流
- `/ws/status` — 只读订阅，新连入会先收到 `_active_status` 快照，再收到 `_event_log` 中已发生事件的 `mirror` 包重建 UI。所有 `emit()` 调用同时写入回放日志并 `_broadcast()` 给订阅者。

**生成流程**（`_run_task` → `_wait_for`）
1. `get_workflow(path)` → `workflow_to_prompt_api` → 拿到 `(prompt_dict, positive_ref)`
2. 依据 `nl_prompt` / `rewrite` / `direct_prompt` 组合最终 prompt 字符串，写回 `prompt_dict[node_id]["inputs"][input_name]`
3. 若前端给了 `width/height`，`apply_resolution` 会改写所有同时含 `width` 和 `height` 输入的节点（不仅 `EmptyLatentImage`）
4. 给所有 `KSampler` 重新随机化 `seed`
5. `submit_prompt` → 拿 `prompt_id` → 连 ComfyUI 自身的 WS（`/ws?clientId=CLIENT_ID`）转发 `progress_state` / `executing` / `execution_success|error`
6. `get_history` 兜底轮询拿最终 outputs

**LLM 集成 (`translate_prompt`)**
直接打 LM Studio 的 `/v1/chat/completions` 流式接口，逐 chunk 通过 `on_chunk` 回调向 WS 发 `llm_chunk`。两套 system prompt：有 `original_prompt` 走"改写"，否则走"翻译成英文 tag"。

**缩略图 (`find_thumbnail`)**
`web/thumbnails/` 下按工作流路径同名查找，支持保留子目录（`flux/x.json` → `thumbnails/flux/x.png`）或仅 basename。`.resolve()` + `startswith(THUMB_DIR.resolve())` 防路径穿越。`_resolve_output_path` 同样防穿越。

## 改代码注意

- 后端**不再**持有"当前工作流"状态（旧接口已废弃但保留），不要重新引入服务端 state；用 `workflow_path` 在请求里传
- `workflow_to_prompt_api` 是从外部 `dev/comfyui.py` 移植，改逻辑前先在 README "来源" 段确认有没有上游变更
- 任何新事件类型要同时考虑：发起者 ws、`_event_log` 回放、`/ws/status` 订阅者三方都要看得到 → 始终走 `emit()` 而不是直接 `ws.send_json`
- `_run_lock` 模型假设单进程；不要在没有外部协调的前提下加 `--workers > 1`
