"""程序入口：装配配置、核心 Agent 与指定界面。"""

import argparse
import os
import sys

from core import Agent, ConfigError, load_config
from tui import available_backends, create_ui

SCRIPT_DIR = os.path.dirname(os.path.abspath(__file__))
CONFIG_PATH = os.path.join(SCRIPT_DIR, "config.ini")


def parse_args(argv=None):
    parser = argparse.ArgumentParser(description="FAgent - Function Call 助手")
    parser.add_argument(
        "--ui",
        choices=available_backends(),
        default="tui",
        help="界面类型，默认 tui",
    )
    return parser.parse_args(argv)


def main(argv=None):
    args = parse_args(argv)

    try:
        config = load_config(CONFIG_PATH)
    except ConfigError as e:
        print(f"错误：{e}")
        return 1
    except OSError as e:
        print(f"错误：读取配置失败：{e}")
        return 1

    try:
        ui = create_ui(args.ui, Agent(config))
    except ImportError as e:
        print(f"错误：无法加载 {args.ui} 界面：{e}")
        return 1

    ui.run()
    return 0


if __name__ == "__main__":
    sys.exit(main())
