"""工具注册表：装饰器登记、参数校验、异常兜底与统一分发。"""

import inspect
import logging
import time

from .common import PathNotAllowed

logger = logging.getLogger("fagent.tool")

TOOL_SPECS = []
_HANDLERS = {}
# 工具来源：{name: {"kind": "local" | "mcp", "server": 服务器名或 None, "origin": 原始工具名}}
TOOL_SOURCES = {}


def tool(name, description, parameters):
    """把函数注册为可供模型调用的工具。

    name/description/parameters 对应 OpenAI Function Schema，
    函数签名即工具参数，未知参数会被自动忽略。
    """

    def decorator(func):
        TOOL_SPECS.append(
            {
                "type": "function",
                "function": {
                    "name": name,
                    "description": description,
                    "parameters": parameters,
                },
            }
        )
        _HANDLERS[name] = {
            "func": func,
            "parameters": parameters,
            "accepted": set(inspect.signature(func).parameters),
        }
        TOOL_SOURCES[name] = {"kind": "local", "server": None, "origin": name}
        return func

    return decorator


def register_dynamic_tool(name, description, parameters, func, server=None, origin=None):
    """注册运行时动态发现的工具（如 MCP Server 提供的工具）。

    与 @tool 装饰器的区别：参数不做函数签名过滤，按 JSON Schema 原样透传。
    server / origin 用于记录来源：暴露名可能带服务器前缀，origin 保留服务器上的原名。
    """
    TOOL_SPECS.append(
        {
            "type": "function",
            "function": {
                "name": name,
                "description": description,
                "parameters": parameters,
            },
        }
    )
    _HANDLERS[name] = {
        "func": func,
        "parameters": parameters,
        "accepted": None,
    }
    TOOL_SOURCES[name] = {
        "kind": "mcp" if server else "local",
        "server": server,
        "origin": origin or name,
    }


def has_tool(name):
    return name in _HANDLERS


def tool_source(name):
    """返回工具来源信息，未知工具按本地工具处理。"""
    return TOOL_SOURCES.get(name) or {"kind": "local", "server": None, "origin": name}


def tool_names():
    return [spec["function"]["name"] for spec in TOOL_SPECS]


def run_tool(name, args):
    """按工具名分发执行，所有错误统一以 Error: 文本返回。

    每次调用都会记录一行结构化日志（工具名、来源、状态、耗时），
    便于事后追溯模型到底调用了什么、成功与否。
    """
    handler = _HANDLERS.get(name)
    if handler is None:
        logger.warning("tool=unknown name=%s status=rejected", name)
        return f"Error: unknown tool {name}"
    if not isinstance(args, dict):
        logger.warning("tool=%s status=rejected reason=args_not_object", name)
        return "Error: 工具参数必须是 JSON 对象"

    missing = [
        key
        for key in handler["parameters"].get("required", [])
        if key not in args or args[key] is None
    ]
    if missing:
        logger.warning(
            "tool=%s status=rejected reason=missing_args %s", name, ",".join(missing)
        )
        return "Error: 缺少参数 " + ", ".join(missing)

    accepted = handler["accepted"]
    kwargs = (
        dict(args)
        if accepted is None
        else {key: value for key, value in args.items() if key in accepted}
    )
    source = tool_source(name)
    started = time.perf_counter()
    try:
        result = handler["func"](**kwargs)
    except PathNotAllowed as e:
        logger.warning(
            "tool=%s server=%s status=denied elapsed=%.3fs reason=%s",
            name,
            source["server"],
            time.perf_counter() - started,
            e,
        )
        return f"Error: {e}"
    except Exception as e:
        logger.error(
            "tool=%s server=%s status=failed elapsed=%.3fs error=%s",
            name,
            source["server"],
            time.perf_counter() - started,
            e,
        )
        return f"Error: 工具 {name} 执行失败：{e}"

    failed = isinstance(result, str) and result.startswith("Error:")
    logger.info(
        "tool=%s server=%s kind=%s status=%s elapsed=%.3fs chars=%s",
        name,
        source["server"],
        source["kind"],
        "failed" if failed else "ok",
        time.perf_counter() - started,
        len(result) if isinstance(result, str) else "-",
    )
    return result
