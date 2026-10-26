import os
from dataclasses import dataclass

REQUIRED_FIELDS = ("base_url", "model_name", "key")


class ConfigError(Exception):
    """配置缺失或非法时抛出"""


@dataclass(frozen=True)
class AppConfig:
    base_url: str
    model_name: str
    key: str


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


def default_config_path():
    """config.ini 固定位于项目根目录（core 的上一级）"""
    return os.path.join(
        os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "config.ini"
    )


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
    """读取并校验配置，失败时抛出 ConfigError"""
    if not os.path.isfile(path):
        raise ConfigError(f"配置文件不存在：{path}")

    cfg = parse_config(path)
    missing = [field for field in REQUIRED_FIELDS if not cfg.get(field)]
    if missing:
        raise ConfigError("缺少字段 " + ", ".join(missing))

    return AppConfig(
        base_url=cfg["base_url"],
        model_name=cfg["model_name"],
        key=cfg["key"],
    )
