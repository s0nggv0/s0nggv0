"""工具注册表：装饰器登记、参数校验、异常兜底与统一分发。"""

import inspect

TOOL_SPECS = []
_HANDLERS = {}


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
        return func

    return decorator


def tool_names():
    return [spec["function"]["name"] for spec in TOOL_SPECS]


def run_tool(name, args):
    """按工具名分发执行，所有错误统一以 Error: 文本返回。"""
    handler = _HANDLERS.get(name)
    if handler is None:
        return f"Error: unknown tool {name}"
    if not isinstance(args, dict):
        return "Error: 工具参数必须是 JSON 对象"

    missing = [
        key
        for key in handler["parameters"].get("required", [])
        if key not in args or args[key] is None
    ]
    if missing:
        return "Error: 缺少参数 " + ", ".join(missing)

    kwargs = {
        key: value
        for key, value in args.items()
        if key in handler["accepted"]
    }
    try:
        return handler["func"](**kwargs)
    except Exception as e:
        return f"Error: 工具 {name} 执行失败：{e}"
