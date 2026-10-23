"""界面工厂：按名称延迟加载并创建界面，避免无关依赖被提前导入。"""

import importlib

_BACKENDS = {
    "console": "console:ConsoleUI",
    "tui": "app:FAgentApp",
}


def available_backends():
    return sorted(_BACKENDS)


def create_ui(name, agent):
    """创建界面实例，返回对象需提供 run() 方法。

    未来接入 Web / Desktop 时，只需新增实现并在 _BACKENDS 登记，
    例如 "web": "web:WebUI"、"desktop": "desktop:DesktopUI"。
    """
    try:
        target = _BACKENDS[name]
    except KeyError:
        raise ValueError(
            f"未知界面：{name}，可选：{', '.join(available_backends())}"
        ) from None

    module_name, class_name = target.split(":")
    module = importlib.import_module(f"{__package__}.{module_name}")
    return getattr(module, class_name)(agent)
