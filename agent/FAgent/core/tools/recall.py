"""上下文检索工具：在压缩归档中查找历史信息。"""

from ..context import search_archives
from .registry import tool


@tool(
    "recallContext",
    "在上下文压缩归档中检索历史信息。当压缩摘要缺少细节、需要确认此前对话内容时使用。"
    "不传 id 时在项目 .agents/context/ 下的所有归档中检索；传入 id 时只检索该编号的归档。"
    "多个关键词以空格分隔时要求同时命中；返回相关片段、归档编号和消息位置。",
    {
        "type": "object",
        "properties": {
            "id": {
                "type": "string",
                "description": "可选，上下文归档编号（例如 20261022-153000），不传则搜索全部归档",
            },
            "text": {
                "type": "string",
                "description": "必需，要查找的关键词或文本内容",
            },
        },
        "required": ["text"],
    },
)
def recall_context(text, id=None):
    return search_archives(text, archive_id=id)
