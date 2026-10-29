"""命令行类工具：以当前用户权限调用本机任意 CLI 程序。"""

import shutil
import subprocess

from .common import decode_output
from .registry import tool

DEFAULT_TIMEOUT = 60
MAX_TIMEOUT = 600
DEFAULT_MAX_OUTPUT_CHARS = 20000


def _truncate(text, limit):
    if len(text) <= limit:
        return text
    return text[:limit] + f"\n...（输出已截断，共 {len(text)} 字符，仅显示前 {limit} 字符）"


@tool(
    "RunCli",
    "调用本机已安装的任意命令行程序并返回标准输出、标准错误和退出码。"
    "命令名与参数分开传入，不会经过 Shell 拼接。",
    {
        "type": "object",
        "properties": {
            "command": {
                "type": "string",
                "description": "要执行的命令行程序名称或可执行文件路径，例如 git、python、ping",
            },
            "args": {
                "type": "array",
                "items": {"type": "string"},
                "description": "传给程序的参数列表，例如 [\"--version\"] 或 [\"-c\", \"3\"]",
            },
            "timeout": {
                "type": "integer",
                "description": f"执行超时时间（秒），默认 {DEFAULT_TIMEOUT}，最大 {MAX_TIMEOUT}",
            },
        },
        "required": ["command", "args"],
    },
)
def run_cli(command, args, timeout=DEFAULT_TIMEOUT):
    command = (command or "").strip() if isinstance(command, str) else ""
    if not command:
        return "Error: 缺少参数 command"

    if isinstance(args, str):
        return "Error: args 必须是字符串列表，请把每个参数单独放入列表"
    if not isinstance(args, (list, tuple)):
        return "Error: args 必须是字符串列表"
    if any(not isinstance(arg, str) for arg in args):
        return "Error: args 中的每一项都必须是字符串"

    try:
        timeout = int(timeout)
    except (TypeError, ValueError):
        timeout = DEFAULT_TIMEOUT
    if timeout <= 0:
        timeout = DEFAULT_TIMEOUT
    timeout = min(timeout, MAX_TIMEOUT)

    argv = [command, *args]

    if shutil.which(command) is None:
        return f"Error: 未找到程序：{command}（请确认已安装且在 PATH 中）"

    try:
        result = subprocess.run(
            argv,
            capture_output=True,
            stdin=subprocess.DEVNULL,
            timeout=timeout,
            shell=False,
        )
    except subprocess.TimeoutExpired as e:
        stdout = _truncate(decode_output(e.stdout or b""), DEFAULT_MAX_OUTPUT_CHARS)
        stderr = _truncate(decode_output(e.stderr or b""), DEFAULT_MAX_OUTPUT_CHARS)
        return (
            f"命令：{argv}\n"
            f"退出码：超时（超过 {timeout} 秒已终止）\n"
            f"标准输出 stdout：\n{stdout or '（空）'}\n"
            f"标准错误 stderr：\n{stderr or '（空）'}"
        )
    except FileNotFoundError:
        return f"Error: 未找到程序：{command}"
    except OSError as e:
        return f"Error: 启动命令失败：{e}"

    stdout = _truncate(decode_output(result.stdout or b""), DEFAULT_MAX_OUTPUT_CHARS)
    stderr = _truncate(decode_output(result.stderr or b""), DEFAULT_MAX_OUTPUT_CHARS)
    return (
        f"命令：{argv}\n"
        f"退出码：{result.returncode}\n"
        f"标准输出 stdout：\n{stdout or '（空）'}\n"
        f"标准错误 stderr：\n{stderr or '（空）'}"
    )
