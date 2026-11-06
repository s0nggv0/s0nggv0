"""配置模型：集中管理全部可调参数，支持 config.ini 覆盖 + 内置默认值。

设计要点：
- ``DEFAULTS`` 是唯一的事实来源，所有业务模块通过 ``setting(key)`` 读取参数；
- config.ini 只需写需要覆盖的键，缺失的键自动回退到默认值；
- 首次启动且当前目录没有 config.ini 时，由 ``ensure_config`` 生成一份带 mock
  信息的完整模板，提示用户修改后重新启动。
"""

import os
from dataclasses import dataclass, field

REQUIRED_FIELDS = ("base_url", "model_name", "key")

# 所有可配置参数的默认值。键名规则：默认小节的键保持原名，
# 其余小节的键写成 "section.key"。
DEFAULTS = {
    "base_url": "https://api.deepseek.com",
    "model_name": "deepseek-chat",
    "key": "",
    # 上下文
    "context.window": 0,  # 0 表示按模型名自动推断
    "context.warning_ratio": 0.7,
    "context.preview_chars": 200_000,
    "context.max_recall_snippets": 12,
    "context.max_recall_chars": 6_000,
    "context.snippet_radius": 160,
    # MCP
    "mcp.connect_timeout": 60,
    "mcp.call_timeout": 120,
    "mcp.probe_timeout": 5,
    "mcp.close_timeout": 10,
    # 文件工具
    "filesystem.max_list_entries": 500,
    "filesystem.max_read_chars": 20_000,
    # 网络工具
    "web.max_chars": 20_000,
    "web.timeout": 20,
    "web.connect_timeout": 10,
    "web.user_agent": (
        "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
        "(KHTML, like Gecko) Chrome/124.0 Safari/537.36"
    ),
    "web.search_endpoint": "https://qianfan.baidubce.com/v2/ai_search/web_search",
    "web.search_timeout": 20,
    "web.search_default_top_k": 10,
    "web.search_max_top_k": 50,
    "web.search_snippet_chars": 500,
    # CLI 工具
    "cli.default_timeout": 60,
    "cli.max_timeout": 600,
    "cli.max_output_chars": 20_000,
    # 系统工具
    "system.date_timeout": 5,
    # 会话
    "session.directory": ".agents/sessions",
    "session.auto_save": True,
    # AGENTS.md 项目规范
    "agents.enabled": True,
    "agents.file": "AGENTS.md",
    "agents.max_chars": 200_000,
    # 界面
    "ui.sidebar_width": 28,
    "ui.sidebar_min_width": 100,
    "ui.input_max_lines": 8,
    "ui.file_completion_limit": 3000,
    "ui.file_completion_items": 8,
    "ui.tool_collapse_lines": 8,
    "ui.tool_collapse_chars": 600,
}

_TRUE_VALUES = {"1", "true", "yes", "on", "y"}
_FALSE_VALUES = {"0", "false", "no", "off", "n"}


class ConfigError(Exception):
    """配置缺失或非法时抛出"""


@dataclass(frozen=True)
class AppConfig:
    base_url: str
    model_name: str
    key: str
    values: dict = field(default_factory=dict)

    def get(self, key, default=None):
        """读取原始配置值，未配置或为空时回退到默认值。"""
        value = self.values.get(key)
        if value is None or value == "":
            return DEFAULTS.get(key, default)
        return value

    def get_int(self, key, default=None):
        fallback = DEFAULTS.get(key, default)
        value = self.get(key, fallback)
        try:
            return int(float(str(value).strip()))
        except (TypeError, ValueError):
            return fallback

    def get_float(self, key, default=None):
        fallback = DEFAULTS.get(key, default)
        value = self.get(key, fallback)
        try:
            return float(str(value).strip())
        except (TypeError, ValueError):
            return fallback

    def get_bool(self, key, default=None):
        fallback = DEFAULTS.get(key, default)
        value = self.get(key, fallback)
        if isinstance(value, bool):
            return value
        text = str(value).strip().lower()
        if text in _TRUE_VALUES:
            return True
        if text in _FALSE_VALUES:
            return False
        return bool(fallback)

    @property
    def is_placeholder(self):
        """是否仍然使用生成模板里的 mock 密钥（需要用户修改后重启）。"""
        return "mock" in (self.key or "").lower()


_ACTIVE_CONFIG = None


def active_config():
    """返回最近一次 load_config 得到的配置，未加载时返回 None。"""
    return _ACTIVE_CONFIG


def activate_config(config):
    """登记当前使用的配置，供工具等模块通过 setting() 读取。"""
    global _ACTIVE_CONFIG
    _ACTIVE_CONFIG = config
    return config


def setting(key, default=None):
    """供工具等模块读取配置：优先当前配置，否则使用默认值。"""
    config = _ACTIVE_CONFIG
    if config is None:
        return DEFAULTS.get(key, default)
    return config.get(key, default)


def setting_int(key, default=None):
    config = _ACTIVE_CONFIG
    if config is None:
        fallback = DEFAULTS.get(key, default)
        try:
            return int(fallback)
        except (TypeError, ValueError):
            return default
    return config.get_int(key, default)


def setting_float(key, default=None):
    config = _ACTIVE_CONFIG
    if config is None:
        try:
            return float(DEFAULTS.get(key, default))
        except (TypeError, ValueError):
            return default
    return config.get_float(key, default)


def setting_bool(key, default=None):
    config = _ACTIVE_CONFIG
    if config is None:
        fallback = DEFAULTS.get(key, default)
        return bool(fallback)
    return config.get_bool(key, default)


def parse_config(path):
    """解析 ini 格式配置，支持 # 注释行、空行与 [section] 小节。

    默认小节的键保持原名，其余小节的键以 "section.key" 形式保存，
    例如 [search] 下的 baidu_api_key 会保存为 "search.baidu_api_key"。
    """
    cfg = {}
    section = ""
    with open(path, "r", encoding="utf-8") as f:
        for line in f:
            line = line.strip()
            if not line or line.startswith("#"):
                continue
            if line.startswith("[") and line.endswith("]"):
                section = line[1:-1].strip()
                continue
            key, _, value = line.partition("=")
            key = key.strip()
            if section:
                key = f"{section}.{key}"
            cfg[key] = value.strip()
    return cfg


def resolve_config_path():
    """定位 config.ini：始终以程序启动时的工作目录为项目根。"""
    return os.path.join(os.getcwd(), "config.ini")


def default_config_path():
    """config.ini 的默认路径，规则见 resolve_config_path。"""
    return resolve_config_path()


CONFIG_TEMPLATE = """# FAgent 配置文件
# 请把下面三项替换为真实可用的模型服务信息，保存后重新启动 FAgent。
base_url=https://api.deepseek.com
model_name=deepseek-chat
key=sk-mock-00000000000000000000000000000000

[context]
# 上下文窗口 token 数，0 表示按模型名自动推断
window=0
warning_ratio=0.7
preview_chars=200000
max_recall_snippets=12
max_recall_chars=6000
snippet_radius=160

[mcp]
connect_timeout=60
call_timeout=120
probe_timeout=5
close_timeout=10

[filesystem]
max_list_entries=500
max_read_chars=20000

[web]
max_chars=20000
timeout=20
connect_timeout=10
user_agent=Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/124.0 Safari/537.36
search_endpoint=https://qianfan.baidubce.com/v2/ai_search/web_search
search_timeout=20
search_default_top_k=10
search_max_top_k=50
search_snippet_chars=500

[search]
# 百度千帆搜索 API Key，使用 searchWeb 工具前请填写真实值
baidu_api_key=mock-baidu-api-key

[cli]
default_timeout=60
max_timeout=600
max_output_chars=20000

[system]
date_timeout=5

[session]
directory=.agents/sessions
auto_save=true

[agents]
# 是否在会话首次加载时注入项目根目录下的 AGENTS.md
enabled=true
file=AGENTS.md
max_chars=200000

[ui]
sidebar_width=28
sidebar_min_width=100
input_max_lines=8
file_completion_limit=3000
file_completion_items=8
tool_collapse_lines=8
tool_collapse_chars=600
"""


def ensure_config(path=None):
    """确保当前目录存在 config.ini，返回 (路径, 是否新建)。

    不存在时写入一份包含全部默认项与 mock 信息的完整模板，
    由调用方提示用户修改后重新启动。
    """
    path = path or resolve_config_path()
    if os.path.isfile(path):
        return path, False
    try:
        parent = os.path.dirname(path)
        if parent:
            os.makedirs(parent, exist_ok=True)
        with open(path, "w", encoding="utf-8", newline="") as f:
            f.write(CONFIG_TEMPLATE)
    except OSError as e:
        raise ConfigError(f"生成配置文件失败：{e}") from e
    return path, True


def load_search_api_key(path=None):
    """读取 [search] 小节的 baidu_api_key，缺失时抛出 ConfigError。

    兼容旧版扁平配置（无小节，直接写 baidu_api_key）。
    """
    path = path or default_config_path()
    if not os.path.isfile(path):
        raise ConfigError(f"搜索引擎配置文件不存在：{path}")

    cfg = parse_config(path)
    key = cfg.get("search.baidu_api_key") or cfg.get("baidu_api_key")
    if not key:
        raise ConfigError(
            f"缺少搜索配置：请在 {path} 的 [search] 小节中设置 baidu_api_key"
        )
    return key


def load_config(path):
    """读取并校验配置，失败时抛出 ConfigError。

    校验通过后会把配置登记为全局活动配置，供工具等模块通过 setting() 读取。
    """
    if not os.path.isfile(path):
        raise ConfigError(f"配置文件不存在：{path}")

    cfg = parse_config(path)
    missing = [field for field in REQUIRED_FIELDS if not cfg.get(field)]
    if missing:
        raise ConfigError("缺少字段 " + ", ".join(missing))

    config = AppConfig(
        base_url=cfg["base_url"],
        model_name=cfg["model_name"],
        key=cfg["key"],
        values=cfg,
    )
    return activate_config(config)
