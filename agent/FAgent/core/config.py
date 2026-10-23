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
    """解析 ini 格式配置，支持 # 注释行与空行"""
    cfg = {}
    with open(path, "r", encoding="utf-8") as f:
        for line in f:
            line = line.strip()
            if not line or line.startswith("#"):
                continue
            key, _, value = line.partition("=")
            cfg[key.strip()] = value.strip()
    return cfg


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
