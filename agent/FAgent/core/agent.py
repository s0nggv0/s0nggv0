"""Agent 核心：模型交互、会话历史、工具调用循环与上下文压缩，不包含任何输入输出。"""

import json

from .config import activate_config, setting_int
from .context import (
    ContextError,
    archive_context,
    context_window_for,
    estimate_messages_tokens,
    render_context,
    warning_ratio,
)
from .session import build_agents_message, is_agents_message, read_agents_guidance
from .tools import TOOLS, run_tool

# 上下文压缩专用 Prompt：把历史对话整理成约 5000 tokens 的工作摘要。
COMPACT_PROMPT = """你是一名 AI Agent 的上下文管理助手。当前会话即将达到上下文窗口限制，需要将历史对话压缩为一份高质量的工作摘要，以便 Agent 在新的上下文中继续执行任务。

请认真阅读提供的历史上下文，提取对后续工作仍然有价值的信息，并生成一份约 5,000 Tokens 的 Markdown 摘要。

摘要应重点保留以下内容：

1. **用户目标与要求**：用户希望完成什么任务？有哪些必须遵守的约束、偏好和验收条件？
2. **已经完成的工作**：哪些任务已经完成？实现了哪些功能？获得了哪些已经验证的结果？
3. **当前工作状态**：Agent 正在处理什么任务？当前进展到哪一步？是否存在尚未解决的问题？
4. **关键技术信息**：保留重要的文件路径、函数名称、接口定义、配置项、执行命令、错误信息和必要的代码片段。
5. **关键决策与原因**：记录用户和 Agent 已经确定的技术方案，以及重要的设计取舍。
6. **下一步任务**：明确接下来应该执行的操作，以及需要继续验证的事项。

请遵守以下要求：

- 优先保留对后续任务有直接影响的信息，删除寒暄、重复讨论、过时的尝试和无关内容。
- 对已经验证的事实与尚未验证的推测作出明确区分。
- 不要将计划完成的任务描述为已经完成。
- 重要的文件路径、函数名称、配置名称和命令应保留准确原文。
- 对失败的尝试，只保留有助于避免重复错误的信息。
- 如果信息存在冲突，应优先保留用户最新确认的要求，并简要说明仍然存在的冲突。
- 如果某些历史细节无法在摘要中完整保留，可简要说明它们已保存到原始上下文归档中，后续可以通过 `recallContext` 工具重新检索。
- 使用清晰的 Markdown 结构输出摘要，不要附加解释或无关内容。

**最终目标：使一个从未阅读过原始对话的 Agent，仅凭这份摘要，就能够理解当前任务、继承关键决策，并继续开展工作。**"""

CONTEXT_PREVIEW_CHARS = 200_000


def _parse_arguments(raw):
    """解析工具参数 JSON，返回 (args, error)"""
    try:
        args = json.loads(raw or "{}")
    except json.JSONDecodeError as e:
        return None, f"Error: 参数不是合法 JSON：{e}"
    if not isinstance(args, dict):
        return None, "Error: 工具参数必须是 JSON 对象"
    return args, None


class Agent:
    """维护历史并完成「请求模型 -> 执行工具 -> 回传结果 -> 再推理」循环。

    UI 通过回调观察执行过程，核心层自身不打印任何内容：
    - on_token(delta)：流式回答的增量文本
    - on_tool_start(name, args)：开始执行某个工具
    - on_tool_result(name, args, result)：工具执行完成
    """

    def __init__(
        self,
        config,
        client=None,
        tools=None,
        tool_runner=None,
        system_prompt="",
    ):
        self.config = activate_config(config)
        self.tools = TOOLS if tools is None else tools
        self._client = client
        self._tool_runner = tool_runner or run_tool
        self.system_prompt = system_prompt or ""
        self.history = []
        # 最近一次 LLM 响应返回的 token 总量；取不到时由字符数估算兜底
        self._last_usage_tokens = None
        # 压缩期间禁止普通任务与工具调用
        self.compacting = False

    @property
    def tool_names(self):
        return [tool["function"]["name"] for tool in self.tools]

    def _get_client(self):
        if self._client is None:
            from openai import OpenAI

            self._client = OpenAI(
                base_url=self.config.base_url, api_key=self.config.key
            )
        return self._client

    def reset(self):
        self.history.clear()
        self._last_usage_tokens = None

    def load_history(self, messages):
        """替换为一条已保存的会话历史（恢复会话时使用）。"""
        self.history = list(messages or [])
        self._last_usage_tokens = None

    def has_agents_guidance(self):
        return any(is_agents_message(message) for message in self.history)

    def inject_agents_guidance(self):
        """会话首次加载时注入项目根目录的 AGENTS.md，返回注入信息或 None。

        采用「一次注入，全程复用」：注入后的消息一直保留在历史最前面，
        后续轮次不再重复读取文件，保证系统提示与历史前缀稳定、缓存有效。
        """
        if not self.config.get_bool("agents.enabled", True):
            return None
        if self.has_agents_guidance():
            return None
        path, text = read_agents_guidance()
        if not text:
            return None
        message = build_agents_message(path, text)
        if self.history:
            self.history.insert(0, message)
        else:
            self.history.append(message)
        return {"path": str(path), "chars": len(text)}

    def _messages(self):
        """系统提示不写入历史，每次请求时临时拼接。"""
        if not self.system_prompt:
            return self.history
        return [{"role": "system", "content": self.system_prompt}] + self.history

    def _stream(self, messages, tools, on_token=None, is_cancelled=None):
        """发起一次流式请求，返回 (完整文本, 工具调用列表, usage token 总数)。

        工具调用参数是分片到达的，这里按 index 累积后再统一返回。
        is_cancelled 在每个分片检查一次，命中后立即停止接收。
        请求会尝试开启 include_usage；接口不支持时自动退回普通流式请求。
        """
        params = {
            "model": self.config.model_name,
            "messages": messages,
            "tools": tools,
            "tool_choice": "auto",
            "stream": True,
        }
        client = self._get_client()
        try:
            stream = client.chat.completions.create(
                **params, stream_options={"include_usage": True}
            )
        except Exception as e:
            if "stream_options" not in str(e).lower():
                raise
            stream = client.chat.completions.create(**params)

        content_parts = []
        tool_calls = {}
        usage_total = None
        for chunk in stream:
            if is_cancelled is not None and is_cancelled():
                break
            usage = getattr(chunk, "usage", None)
            if usage is not None:
                usage_total = getattr(usage, "total_tokens", None)
                if not usage_total:
                    usage_total = (getattr(usage, "prompt_tokens", 0) or 0) + (
                        getattr(usage, "completion_tokens", 0) or 0
                    )
            if not chunk.choices:
                continue
            delta = chunk.choices[0].delta
            if delta.content:
                content_parts.append(delta.content)
                if on_token:
                    on_token(delta.content)
            for call in delta.tool_calls or []:
                slot = tool_calls.setdefault(
                    call.index or 0, {"id": "", "name": "", "arguments": ""}
                )
                if call.id:
                    slot["id"] = call.id
                function = call.function
                if function is not None:
                    if function.name:
                        slot["name"] += function.name
                    if function.arguments:
                        slot["arguments"] += function.arguments

        if is_cancelled is not None and is_cancelled():
            stream.close()

        return (
            "".join(content_parts),
            [tool_calls[i] for i in sorted(tool_calls)],
            usage_total,
        )

    def send(
        self,
        prompt,
        on_token=None,
        on_tool_start=None,
        on_tool_result=None,
        is_cancelled=None,
    ):
        """提交一条用户消息，返回模型最终回答（取消时返回已收到的部分）"""
        if self.compacting:
            raise RuntimeError("上下文压缩进行中，暂不接受新的任务")
        self.history.append({"role": "user", "content": prompt})
        self._last_usage_tokens = None

        while True:
            content, tool_calls, usage_total = self._stream(
                self._messages(), self.tools, on_token, is_cancelled
            )
            # 记录本次 LLM 响应返回的 token 用量，供上下文监控使用
            self._last_usage_tokens = usage_total

            # 用户取消：丢弃本轮未完成的工具调用，只保留已输出的文本
            if is_cancelled is not None and is_cancelled():
                self.history.append({"role": "assistant", "content": content or None})
                return content

            if not tool_calls:
                self.history.append({"role": "assistant", "content": content})
                return content

            self.history.append(
                {
                    "role": "assistant",
                    "content": content or None,
                    "tool_calls": [
                        {
                            "id": call["id"],
                            "type": "function",
                            "function": {
                                "name": call["name"],
                                "arguments": call["arguments"],
                            },
                        }
                        for call in tool_calls
                    ],
                }
            )

            for call in tool_calls:
                name = call["name"]
                args, error = _parse_arguments(call["arguments"])
                if on_tool_start:
                    on_tool_start(name, args)
                result = error if error else self._tool_runner(name, args)
                self.history.append(
                    {
                        "role": "tool",
                        "tool_call_id": call["id"],
                        "content": result,
                    }
                )
                if on_tool_result:
                    on_tool_result(name, args, result)

    # ------------------------------------------------------------ 上下文管理

    def context_stats(self):
        """返回当前上下文用量：tokens / window / ratio / is_default / source。

        优先使用模型 API 返回的 usage，取不到或历史增长后估算更大时用估算值兜底。
        """
        estimated = estimate_messages_tokens(self._messages(), self.tools)
        tokens = max(self._last_usage_tokens or 0, estimated)
        window, is_default = context_window_for(self.config.model_name)
        return {
            "tokens": tokens,
            "window": window,
            "ratio": tokens / window if window else 0.0,
            "is_default": is_default,
            "source": "api" if self._last_usage_tokens else "estimate",
        }

    def needs_compact(self):
        """上下文占用是否已达到告警阈值（默认 70%，可由配置调整）。"""
        return self.context_stats()["ratio"] >= warning_ratio()

    def render_context_text(self, max_chars=None):
        """渲染完整上下文，供压缩 Prompt 与压缩前后对照面板使用。"""
        return render_context(self.system_prompt, self.history, max_chars=max_chars)

    def compact(self):
        """归档原始上下文并调用 LLM 生成摘要，成功后用摘要替换历史。

        压缩失败时抛 ContextError，原有 history 保持不变。
        返回归档编号、摘要与压缩前原文等信息。
        """
        if self.compacting:
            raise ContextError("上下文压缩正在进行中")
        if not self.history:
            raise ContextError("当前会话为空，没有需要压缩的上下文")

        self.compacting = True
        try:
            # 1. 先完成原始上下文归档，保存成功后才继续压缩
            archive_id, path, created = archive_context(
                self.system_prompt, self.history
            )
            original = render_context(self.system_prompt, self.history)
            preview = original
            preview_limit = setting_int(
                "context.preview_chars", CONTEXT_PREVIEW_CHARS
            )
            if preview_limit > 0 and len(preview) > preview_limit:
                preview = (
                    preview[:preview_limit]
                    + "\n\n…（预览已截断，完整内容见归档文件）"
                )

            # 2. 只调用 LLM 生成摘要，不提供任何工具定义
            messages = [
                {"role": "system", "content": COMPACT_PROMPT},
                {
                    "role": "user",
                    "content": "以下是需要压缩的历史上下文：\n\n" + original,
                },
            ]
            try:
                response = self._get_client().chat.completions.create(
                    model=self.config.model_name,
                    messages=messages,
                    stream=False,
                )
            except Exception as e:
                raise ContextError(f"调用模型生成摘要失败：{e}") from e

            try:
                summary = (response.choices[0].message.content or "").strip()
            except (AttributeError, IndexError, TypeError):
                summary = ""
            if not summary:
                raise ContextError("模型未返回有效的压缩摘要，已保留原有上下文")

            # 3. 摘要 + 归档说明替换历史；System Prompt 与工具定义保持不变
            stamp = created.strftime("%Y-%m-%d %H:%M:%S")
            note = (
                f"此前上下文已于 {stamp} 完成压缩，原始上下文保存在编号为 "
                f"{archive_id} 的归档文件中。如需查找历史信息，请使用 "
                "recallContext 工具。"
            )
            self.history = [
                {
                    "role": "user",
                    "content": "【此前会话的压缩摘要】\n\n"
                    + summary
                    + "\n\n"
                    + note,
                }
            ]
            self._last_usage_tokens = None
            return {
                "archive_id": archive_id,
                "archive_path": str(path),
                "summary": summary,
                "note": note,
                "before_text": preview,
            }
        finally:
            self.compacting = False
