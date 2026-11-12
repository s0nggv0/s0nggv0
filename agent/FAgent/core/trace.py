"""运行日志：把模型调用、工具执行与 MCP 连接写入 .agents/logs/。

TUI 独占终端，不能往 stdout 打日志，因此只写文件；文件名按天切分，
单文件超过 log.max_bytes 自动轮转，便于事后追溯一次任务的完整执行链。
"""

import logging
import os
from datetime import datetime
from logging.handlers import RotatingFileHandler
from pathlib import Path

from .config import setting, setting_bool, setting_int
from .skills import project_root

_configured = False


def log_dir():
    """日志目录：默认项目根下的 .agents/logs/，可通过 [log] directory 覆盖。"""
    raw = str(setting("log.directory", ".agents/logs") or ".agents/logs")
    path = Path(os.path.expanduser(raw))
    return path if path.is_absolute() else project_root() / path


def setup_logging():
    """初始化 fagent 日志，返回日志文件路径；被关闭或初始化失败时返回 None。"""
    global _configured
    if _configured:
        return None
    if not setting_bool("log.enabled", True):
        # 关闭日志时挂空处理器，避免 logging 的 lastResort 把内容打到 stderr 干扰界面
        logging.getLogger("fagent").addHandler(logging.NullHandler())
        _configured = True
        return None

    directory = log_dir()
    try:
        directory.mkdir(parents=True, exist_ok=True)
        path = directory / f"fagent-{datetime.now():%Y%m%d}.log"
        handler = RotatingFileHandler(
            path,
            maxBytes=max(4096, setting_int("log.max_bytes", 1_048_576)),
            backupCount=3,
            encoding="utf-8",
        )
    except OSError as exc:
        print(f"警告：无法初始化运行日志：{exc}")
        return None

    handler.setFormatter(
        logging.Formatter("%(asctime)s %(levelname)s %(name)s %(message)s")
    )
    level_name = str(setting("log.level", "INFO") or "INFO").upper()
    root = logging.getLogger("fagent")
    root.setLevel(getattr(logging, level_name, logging.INFO))
    root.addHandler(handler)
    root.propagate = False
    _configured = True
    root.info("logging initialized path=%s level=%s", path, level_name)
    return path
