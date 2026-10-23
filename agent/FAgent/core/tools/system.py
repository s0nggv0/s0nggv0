"""系统信息类工具：日期时间、闰年判断、工作目录。"""

import os
import subprocess

from .common import decode_output
from .registry import tool


@tool(
    "getDate",
    "获取当前电脑的日期和时间",
    {"type": "object", "properties": {}, "required": []},
)
def get_date():
    try:
        result = subprocess.run(
            ["cmd", "/c", "date /t && time /t"],
            capture_output=True,
            timeout=5,
        )
        if result.returncode == 0:
            out = decode_output(result.stdout or b"")
            return " ".join(line.strip() for line in out.splitlines() if line.strip())
        err = decode_output(result.stderr or b"") if result.stderr else ""
        return f"Error: {err}"
    except subprocess.TimeoutExpired:
        return "Error: date command timeout"
    except Exception as e:
        return f"Error: {e}"


@tool(
    "isLeapYear",
    "判断输入的年份是否是闰年",
    {
        "type": "object",
        "properties": {
            "year": {"type": "integer", "description": "要判断的年份，例如 2024"}
        },
        "required": ["year"],
    },
)
def is_leap_year(year):
    year = int(year)
    if (year % 4 == 0 and year % 100 != 0) or (year % 400 == 0):
        return f"{year} 年是闰年"
    return f"{year} 年不是闰年"


@tool(
    "getCwd",
    "获取当前工作目录的绝对路径",
    {"type": "object", "properties": {}, "required": []},
)
def get_cwd():
    return os.getcwd()
