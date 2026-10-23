"""工具包统一出口。

各业务模块（system / filesystem）在导入时通过 @tool 完成注册，
本模块负责编排注册顺序并对外暴露稳定的公共 API。
"""

from . import system, filesystem  # noqa: F401  注册工具
from .registry import TOOL_SPECS, run_tool, tool_names

TOOLS = TOOL_SPECS

__all__ = ["TOOLS", "run_tool", "tool_names"]
