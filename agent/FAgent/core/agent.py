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

    UI 通过回调 on_tool_result(name, args, result) 观察工具执行结果，
    核心层自身不打印任何内容。
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

    def _complete(self, messages, tools):
        return self._get_client().chat.completions.create(
            model=self.config.model_name,
            messages=messages,
            tools=tools,
            tool_choice="auto",
            stream=False,
        )

    def send(self, prompt, on_tool_result=None):
        """提交一条用户消息，返回模型最终回答"""
        self.history.append({"role": "user", "content": prompt})

        while True:
            response = self._complete(self.history, self.tools)
            message = response.choices[0].message

            if not message.tool_calls:
                reply = message.content or ""
                self.history.append({"role": "assistant", "content": reply})
                return reply

            self.history.append(message.model_dump(exclude_none=True))
            for tool_call in message.tool_calls:
                name = tool_call.function.name
                args, error = _parse_arguments(tool_call.function.arguments)
                result = error if error else self._tool_runner(name, args)
                self.history.append(
                    {
                        "role": "tool",
                        "tool_call_id": tool_call.id,
                        "content": result,
                    }
                )
                if on_tool_result:
                    on_tool_result(name, args, result)
