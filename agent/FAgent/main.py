"""程序入口：装配配置、核心 Agent 与指定界面。"""

import argparse
import os
import sys

from core import Agent, ConfigError, ensure_config, load_config, resolve_config_path
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


def _config_notice_text(path, created):
    if created:
        reason = "当前目录缺少 config.ini，已自动生成一份包含全部配置项的模板。"
    else:
        reason = "config.ini 仍在使用 mock 占位信息。"
    return (
        f"{reason}\n\n"
        f"配置文件：{path}\n\n"
        "请修改 base_url、model_name、key（以及需要的其他参数）后重新启动 FAgent，"
        "程序才能正常工作。"
    )


def _notify_config(path, created, ui_name):
    """首启 / 占位配置时提示用户修改后重启：TUI 弹窗，其余界面打印。"""
    text = _config_notice_text(path, created)
    if ui_name == "tui":
        try:
            from tui.notice import show_config_notice

            show_config_notice(path, created)
            return
        except Exception:
            pass
    print(text)
    print("提示：修改配置后重新启动 FAgent。")


def main(argv=None):
    args = parse_args(argv)

    config_path = resolve_config_path()
    try:
        config_path, created = ensure_config(config_path)
    except ConfigError as e:
        print(f"错误：{e}")
        return 1

    try:
        config = load_config(config_path)
    except ConfigError as e:
        print(f"错误：{e}")
        return 1
    except OSError as e:
        print(f"错误：读取配置失败：{e}")
        return 1

    if created or config.is_placeholder:
        _notify_config(config_path, created, args.ui)
        return 1

    mcp_manager, mcp_messages = (None, [])
    if setup_mcp is not None:
        # TUI 先启动界面，MCP 在后台连接并动态刷新侧栏；其他界面同步加载
        background = args.ui == "tui"
        mcp_manager, mcp_messages = setup_mcp(background=background)
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
