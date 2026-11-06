"""MCP Client：连接外部 MCP Server，并将其工具注册到本地工具表。

启动时读取当前项目目录（程序启动时的工作目录）下的 ``.mcp.json``：

```json
{
  "mcpServers": {
    "server-name": {
      "type": "stdio",
      "command": "uvx",
      "args": ["some-mcp-server"],
      "env": {"KEY": "value"}
    },
    "remote": {
      "type": "streamable_http",
      "url": "https://example.com/mcp",
      "headers": {"Authorization": "Bearer ..."}
    }
  }
}
```

MCP SDK 基于 asyncio，而 Agent 的工具调用循环是同步的，
这里用独立的后台事件循环线程持有全部会话，同步侧通过
``asyncio.run_coroutine_threadsafe`` 桥接。
"""

import asyncio
import json
import socket
import threading
from contextlib import AsyncExitStack
from urllib.parse import urlparse

from mcp import ClientSession, StdioServerParameters
from mcp.client.stdio import get_default_environment, stdio_client
from mcp.client.streamable_http import streamablehttp_client

from .skills import project_root
from .tools.registry import has_tool, register_dynamic_tool

CONNECT_TIMEOUT = 60
CALL_TIMEOUT = 120
HTTP_TYPES = {"streamable_http", "http", "streamable-http"}

# 最近一次 setup_mcp 的连接结果：{server 名: {"state": "connected" | "error",
# "detail": 失败原因, "tool_count": 已注册工具数}}
MCP_STATUS = {}


def mcp_status():
    """返回本次启动的 MCP Server 状态快照，供界面展示。"""
    return {name: dict(info) for name, info in MCP_STATUS.items()}


def default_mcp_config_path():
    """.mcp.json 位于当前项目根目录（程序启动时的工作目录）。"""
    return project_root() / ".mcp.json"


def load_mcp_servers(path=None):
    """读取 .mcp.json，返回 (服务器配置列表 [(name, spec)], 错误信息)。"""
    path = path or default_mcp_config_path()
    if not path.is_file():
        return [], None
    try:
        data = json.loads(path.read_text(encoding="utf-8-sig"))
    except (OSError, json.JSONDecodeError) as e:
        return [], f"错误：解析 MCP 配置 {path} 失败：{e}"
    if not isinstance(data, dict):
        return [], f"错误：MCP 配置 {path} 必须是 JSON 对象"

    servers = data.get("mcpServers")
    if not isinstance(servers, dict):
        return [], f"错误：MCP 配置 {path} 缺少 mcpServers 对象"

    entries = []
    for name, spec in servers.items():
        if not isinstance(spec, dict):
            return [], f"错误：MCP Server {name} 的配置必须是 JSON 对象"
        entries.append((str(name), spec))
    return entries, None


def _transport_of(spec):
    """推断传输协议：显式 type 优先，否则按是否存在 command 字段判断。"""
    transport = str(spec.get("type") or "").strip().lower()
    if transport:
        return transport
    return "stdio" if spec.get("command") else "streamable_http"


def _validate_spec(name, spec):
    transport = _transport_of(spec)
    if transport == "stdio":
        if not spec.get("command"):
            return f"MCP Server {name} 缺少 command 字段"
    elif transport in HTTP_TYPES:
        if not spec.get("url"):
            return f"MCP Server {name} 缺少 url 字段"
    else:
        return f"MCP Server {name} 的 type {transport} 不受支持（仅支持 stdio / streamable_http）"
    return None


def describe_error(error):
    """提取可读的错误描述。

    MCP SDK 的 anyio TaskGroup 会把真实异常包进 ExceptionGroup，
    而 ExceptionGroup 的 str() 通常为空，这里递归展开取最内层原因。
    """
    children = getattr(error, "exceptions", None)
    if children:
        inner = [text for text in (describe_error(e) for e in children) if text]
        if inner:
            # 同一原因的重复项去重，避免多层包装后重复输出
            unique = list(dict.fromkeys(inner))
            return "; ".join(unique)
        return type(error).__name__
    text = str(error).strip()
    return text or type(error).__name__


def unreachable_reason(spec, timeout=5):
    """streamable_http 服务器先探测 TCP 连通性，返回可读原因或 None。

    MCP SDK 的 anyio cancel scope 会把连接失败的原因替换成 CancelledError，
    提前探测可以给出「地址、端口、拒绝原因」这类明确信息。
    """
    raw_url = str(spec.get("url") or "")
    parsed = urlparse(raw_url)
    host = parsed.hostname
    if not host:
        return f"url 缺少有效主机名：{raw_url}"
    port = parsed.port or (443 if parsed.scheme == "https" else 80)
    try:
        with socket.create_connection((host, port), timeout=timeout):
            return None
    except OSError as e:
        return f"无法连接 {host}:{port}（{e}）"


def format_tool_result(result):
    """把 CallToolResult 转成回传给模型的文本。

    拼接文本内容，其他类型内容（图片、资源等）以 JSON 形式附后；
    structuredContent 仅在文本内容未包含等价数据时附加，避免重复占用上下文；
    isError 时加 Error: 前缀。
    """
    parts = []
    for content in result.content or []:
        text = getattr(content, "text", None)
        if text is not None:
            parts.append(text)
        else:
            parts.append(json.dumps(content.model_dump(mode="json"), ensure_ascii=False))
    text_output = "\n".join(parts)

    structured = None
    if result.structuredContent is not None:
        try:
            text_data = json.loads(text_output) if text_output else None
        except json.JSONDecodeError:
            text_data = None
        if text_data != result.structuredContent:
            structured = json.dumps(
                result.structuredContent, ensure_ascii=False, default=str
            )

    chunks = [text_output]
    if structured:
        chunks.append("结构化数据：" + structured)
    chunks = [chunk for chunk in chunks if chunk]
    output = "\n".join(chunks) if chunks else "(MCP 工具未返回内容)"
    if result.isError:
        return "Error: " + output
    return output


class MCPManager:
    """在后台事件循环线程中维护全部 MCP Server 会话。"""

    def __init__(self):
        self._loop = asyncio.new_event_loop()
        self._thread = threading.Thread(
            target=self._run_loop, name="mcp-client", daemon=True
        )
        self._sessions = {}
        self._stacks = {}

    def _run_loop(self):
        asyncio.set_event_loop(self._loop)
        self._loop.run_forever()

    def start(self):
        self._thread.start()

    async def _connect(self, name, spec):
        """建立单个服务器连接并返回其工具列表，失败时抛出异常。"""
        transport = _transport_of(spec)
        stack = AsyncExitStack()
        try:
            if transport == "stdio":
                env = spec.get("env")
                merged_env = (
                    None
                    if env is None
                    else {**get_default_environment(), **{str(k): str(v) for k, v in env.items()}}
                )
                params = StdioServerParameters(
                    command=str(spec["command"]),
                    args=[str(arg) for arg in spec.get("args") or []],
                    env=merged_env,
                )
                read, write = await stack.enter_async_context(stdio_client(params))
            else:
                headers = spec.get("headers")
                read, write, _ = await stack.enter_async_context(
                    streamablehttp_client(
                        str(spec["url"]),
                        headers=(
                            {str(k): str(v) for k, v in headers.items()}
                            if isinstance(headers, dict)
                            else None
                        ),
                    )
                )
            session = await stack.enter_async_context(ClientSession(read, write))
            await asyncio.wait_for(session.initialize(), timeout=CONNECT_TIMEOUT)
            listed = await asyncio.wait_for(session.list_tools(), timeout=CONNECT_TIMEOUT)
        except Exception:
            # 关闭失败可能是 CancelledError，必须吞掉以保留原始异常
            try:
                await stack.aclose()
            except BaseException:
                pass
            raise

        self._stacks[name] = stack
        self._sessions[name] = session
        return listed.tools or []

    def connect(self, name, spec, timeout=CONNECT_TIMEOUT + 10):
        future = asyncio.run_coroutine_threadsafe(
            self._connect(name, spec), self._loop
        )
        return future.result(timeout)

    def call_tool(self, server_name, tool_name, args):
        """同步调用指定服务器上的工具，返回值始终是回传给模型的文本。"""
        session = self._sessions.get(server_name)
        if session is None:
            return f"Error: MCP Server {server_name} 未连接"
        future = asyncio.run_coroutine_threadsafe(
            session.call_tool(tool_name, args or {}), self._loop
        )
        try:
            result = future.result(CALL_TIMEOUT)
        except Exception as e:
            return f"Error: MCP 工具 {tool_name} 调用失败：{describe_error(e)}"
        try:
            return format_tool_result(result)
        except Exception as e:
            return f"Error: MCP 工具 {tool_name} 的结果解析失败：{describe_error(e)}"

    def close(self):
        """尽力关闭全部连接（程序退出时调用，异常静默忽略）。"""
        if not self._loop.is_running():
            return

        async def _close_all():
            for stack in self._stacks.values():
                try:
                    await stack.aclose()
                except Exception:
                    pass

        try:
            future = asyncio.run_coroutine_threadsafe(_close_all(), self._loop)
            future.result(10)
        except Exception:
            pass
        self._loop.call_soon_threadsafe(self._loop.stop)


def _pick_exposed_name(server_name, tool_name, taken):
    """为 LLM 暴露的工具名：无冲突用原名，有冲突加 服务器名__ 前缀。"""
    if tool_name not in taken and not has_tool(tool_name):
        return tool_name
    prefixed = f"{server_name}__{tool_name}"
    if prefixed not in taken and not has_tool(prefixed):
        return prefixed
    return None


def _make_caller(manager, server_name, tool_name):
    """把 run_tool 传入的关键字参数打包成 arguments dict 转发给 MCP Server。"""

    def _call(**kwargs):
        return manager.call_tool(server_name, tool_name, kwargs)

    return _call


def setup_mcp(manager=None, path=None):
    """读取 .mcp.json、连接各服务器并把工具注册进本地工具表。

    返回 (manager, 状态消息列表)；单个服务器失败只记录错误消息，不影响其他服务器。
    没有配置文件时返回 (None, [])。
    """
    servers, error = load_mcp_servers(path)
    if error:
        return None, [error]
    if not servers:
        return None, []

    MCP_STATUS.clear()
    manager = manager or MCPManager()
    manager.start()

    messages = []
    taken = set()  # 本次注册已占用的暴露名
    for name, spec in servers:
        spec_error = _validate_spec(name, spec)
        if spec_error:
            messages.append(f"错误：{spec_error}")
            MCP_STATUS[name] = {"state": "error", "detail": spec_error, "tool_count": 0}
            continue
        if _transport_of(spec) in HTTP_TYPES:
            reason = unreachable_reason(spec)
            if reason:
                messages.append(f"错误：MCP Server {name} {reason}")
                MCP_STATUS[name] = {"state": "error", "detail": reason, "tool_count": 0}
                continue
        try:
            tools = manager.connect(name, spec)
        except BaseException as e:
            detail = describe_error(e)
            messages.append(f"错误：MCP Server {name} 连接失败：{detail}")
            MCP_STATUS[name] = {"state": "error", "detail": detail, "tool_count": 0}
            continue

        registered = 0
        for tool in tools:
            exposed = _pick_exposed_name(name, tool.name, taken)
            if exposed is None:
                messages.append(
                    f"错误：MCP 工具 {tool.name}（来自 {name}）名称冲突，已跳过"
                )
                continue
            taken.add(exposed)
            schema = tool.inputSchema if isinstance(tool.inputSchema, dict) else {
                "type": "object",
                "properties": {},
            }
            description = tool.description or f"MCP 工具 {tool.name}（来自 {name}）"
            if exposed != tool.name:
                description = f"[{name}] {description}"
            register_dynamic_tool(
                exposed,
                description,
                schema,
                _make_caller(manager, name, tool.name),
                server=name,
                origin=tool.name,
            )
            registered += 1
        MCP_STATUS[name] = {
            "state": "connected",
            "detail": "",
            "tool_count": registered,
        }
        messages.append(f"MCP Server {name} 已连接，注册 {registered} 个工具")

    return manager, messages
