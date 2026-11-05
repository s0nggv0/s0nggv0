"""程序入口：装配配置、核心 Agent 与指定界面。"""

import argparse
import os
import sys

from core import Agent, ConfigError, load_config, resolve_config_path
from core.skills import build_skills_prompt, discover_skills
from tui import available_backends, create_ui

try:
    from core.mcp_client import setup_mcp
except ImportError:
    setup_mcp = None


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
        config = load_config(resolve_config_path())
    except ConfigError as e:
        print(f"错误：{e}")
        return 1
    except OSError as e:
        print(f"错误：读取配置失败：{e}")
        return 1

    mcp_manager, mcp_messages = (None, [])
    if setup_mcp is not None:
        mcp_manager, mcp_messages = setup_mcp()
    elif os.path.isfile(os.path.join(os.getcwd(), ".mcp.json")):
        mcp_messages = ["错误：检测到 .mcp.json 但未安装 mcp 包，请先执行 pip install mcp"]
    for message in mcp_messages:
        print(message)

    try:
        system_prompt = build_skills_prompt(discover_skills())
        ui = create_ui(args.ui, Agent(config, system_prompt=system_prompt))
    except ImportError as e:
        print(f"错误：无法加载 {args.ui} 界面：{e}")
        return 1

    try:
        ui.run()
    finally:
        if mcp_manager is not None:
            mcp_manager.close()
    return 0


if __name__ == "__main__":
    sys.exit(main())
