"""Agent 核心：模型交互、会话历史与工具调用循环，不包含任何输入输出。"""

import json

from .tools import TOOLS, run_tool


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

    def __init__(self, config, client=None, tools=None, tool_runner=None):
        self.config = config
        self.tools = TOOLS if tools is None else tools
        self._client = client
        self._tool_runner = tool_runner or run_tool
        self.history = []

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

    def _stream(self, messages, tools, on_token=None, is_cancelled=None):
        """发起一次流式请求，返回 (完整文本, 工具调用列表)。

        工具调用参数是分片到达的，这里按 index 累积后再统一返回。
        is_cancelled 在每个分片检查一次，命中后立即停止接收。
        """
        stream = self._get_client().chat.completions.create(
            model=self.config.model_name,
            messages=messages,
            tools=tools,
            tool_choice="auto",
            stream=True,
        )

        content_parts = []
        tool_calls = {}
        for chunk in stream:
            if is_cancelled is not None and is_cancelled():
                break
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

        return "".join(content_parts), [tool_calls[i] for i in sorted(tool_calls)]

    def send(
        self,
        prompt,
        on_token=None,
        on_tool_start=None,
        on_tool_result=None,
        is_cancelled=None,
    ):
        """提交一条用户消息，返回模型最终回答（取消时返回已收到的部分）"""
        self.history.append({"role": "user", "content": prompt})

        while True:
            content, tool_calls = self._stream(
                self.history, self.tools, on_token, is_cancelled
            )

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
