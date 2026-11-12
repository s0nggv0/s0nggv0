"""系统信息类工具：日期时间、闰年判断、工作目录。"""

import os
from datetime import datetime

from .registry import tool


@tool(
    "getDate",
    "获取当前电脑的本地日期和时间（跨平台，精确到秒）",
    {"type": "object", "properties": {}, "required": []},
)
def get_date():
    now = datetime.now().astimezone()
    return f"{now:%Y-%m-%d %H:%M:%S}（{now.tzname() or '本地时区'}）"


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
