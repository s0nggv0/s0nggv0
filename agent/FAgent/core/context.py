"""上下文管理辅助：Token 估算、上下文窗口、原始上下文归档与历史检索。

本模块只使用 Python 标准库，保持实现简单：
- Token 数量优先使用模型 API 返回的 usage（由 Agent 记录），取不到时按字符数估算；
- 每次压缩把完整上下文写成 ``.agents/context/<编号>.jsonl``，一条消息一行；
- recallContext 工具在所有归档中做本地全文关键词匹配，返回片段与位置。
"""

import json
import math
import re
from datetime import datetime
from pathlib import Path

from .skills import project_root

DEFAULT_CONTEXT_WINDOW = 128_000
CONTEXT_WARNING_RATIO = 0.7

# 已知模型的上下文窗口（token）。按模型名包含关系匹配，更具体的名字放在前面。
MODEL_CONTEXT_WINDOWS = {
    "gpt-4.1": 1_000_000,
    "gpt-4o": 128_000,
    "gpt-4-turbo": 128_000,
    "gpt-4": 128_000,
    "gpt-3.5": 16_000,
    "deepseek-chat": 128_000,
    "deepseek-reasoner": 128_000,
    "deepseek-v3": 128_000,
    "deepseek-v2": 64_000,
    "qwen2.5": 128_000,
    "qwen3": 128_000,
    "claude-sonnet": 200_000,
    "claude-3": 200_000,
    "gemini-2": 1_000_000,
    "gemini-1.5": 1_000_000,
    "kimi-k2": 128_000,
}

MAX_RECALL_SNIPPETS = 12
MAX_RECALL_CHARS = 6000
SNIPPET_RADIUS = 160

_CJK_PATTERN = re.compile(
    r"[\u3400-\u9fff\uf900-\ufaff\u3000-\u303f\uff00-\uffef]"
)


class ContextError(Exception):
    """上下文归档或压缩失败时抛出。"""


def context_window_for(model_name):
    """返回 (上下文窗口 token 数, 是否为默认值)。

    模型名能匹配到内置表时使用表内数值，否则回退到 128k 并标记为默认。
    """
    name = (model_name or "").lower()
    for key, window in MODEL_CONTEXT_WINDOWS.items():
        if key in name:
            return window, False
    return DEFAULT_CONTEXT_WINDOW, True


def estimate_tokens(text):
    """粗略估算文本 token 数：中日韩字符约 1 字 1 token，其余字符约 4 字 1 token。"""
    if not text:
        return 0
    text = str(text)
    cjk = len(_CJK_PATTERN.findall(text))
    other = len(text) - cjk
    return cjk + math.ceil(other / 4)


def _body_text(message):
    """把一条消息还原成文本，保留工具调用参数与工具结果。"""
    parts = []
    content = message.get("content")
    if isinstance(content, str):
        if content:
            parts.append(content)
    elif content is not None:
        parts.append(json.dumps(content, ensure_ascii=False, indent=2))

    for call in message.get("tool_calls") or []:
        function = call.get("function") or {}
        parts.append(
            "工具调用 "
            + (function.get("name") or "")
            + "\n参数 "
            + (function.get("arguments") or "{}")
        )

    if message.get("role") == "tool" and message.get("tool_call_id"):
        parts.insert(0, f"tool_call_id={message['tool_call_id']}")

    return "\n".join(parts) or "（空）"


def estimate_messages_tokens(messages, tools=None):
    """估算整段请求的 token 数（含系统提示、历史消息与工具定义）。"""
    total = 0
    for message in messages:
        total += 4
        total += estimate_tokens(_body_text(message))
        total += estimate_tokens(message.get("role", ""))
    if tools:
        total += 8
        total += estimate_tokens(json.dumps(tools, ensure_ascii=False))
    return total


def context_dir(directory=None):
    """归档目录：项目根下的 .agents/context/。"""
    return Path(directory) if directory else project_root() / ".agents" / "context"


def list_archives(directory=None):
    """列出全部归档文件，编号较新的排在前面。"""
    root = context_dir(directory)
    if not root.is_dir():
        return []
    archives = [path for path in root.glob("*.jsonl") if path.is_file()]
    return sorted(archives, key=lambda path: path.name, reverse=True)


def archive_context(system_prompt, history, directory=None, now=None):
    """把完整上下文写入 JSONL 归档，返回 (归档编号, 文件路径, 归档时间)。

    每条消息一行，保留角色、内容、工具调用参数、工具结果与消息顺序。
    写入或校验失败时抛 ContextError；只有成功返回后调用方才继续压缩。
    """
    if not history:
        raise ContextError("当前会话没有可归档的历史消息")

    created = now or datetime.now()
    base_id = created.strftime("%Y%m%d-%H%M%S")
    root = context_dir(directory)
    try:
        root.mkdir(parents=True, exist_ok=True)
    except OSError as e:
        raise ContextError(f"无法创建上下文归档目录 {root}：{e}")

    archive_id = base_id
    index = 1
    while (root / f"{archive_id}.jsonl").exists():
        archive_id = f"{base_id}-{index}"
        index += 1
    path = root / f"{archive_id}.jsonl"

    records = []
    if system_prompt:
        records.append({"role": "system", "content": system_prompt})
    records.extend(history)

    try:
        with open(path, "w", encoding="utf-8") as f:
            for message in records:
                f.write(json.dumps(message, ensure_ascii=False) + "\n")
        if path.stat().st_size <= 0:
            raise OSError("归档文件为空")
    except (OSError, TypeError) as e:
        raise ContextError(f"保存原始上下文失败：{e}")

    return archive_id, path, created


def render_context(system_prompt, history, max_chars=None):
    """把上下文渲染成带序号的 Markdown 文本，供压缩 Prompt 与预览面板使用。"""
    blocks = []
    index = 0
    if system_prompt:
        index += 1
        blocks.append(f"### [{index}] system\n{system_prompt}")
    for message in history:
        index += 1
        blocks.append(
            f"### [{index}] {message.get('role', 'unknown')}\n{_body_text(message)}"
        )
    text = "\n\n".join(blocks)
    if max_chars and len(text) > max_chars:
        text = text[:max_chars] + "\n\n…（内容过长，预览已截断，完整内容见归档文件）"
    return text


def _snippet(text, terms):
    """截取首次命中位置附近的一段文本，避免整条消息占满上下文。"""
    lower = text.lower()
    positions = [lower.find(term) for term in terms]
    positions = [position for position in positions if position >= 0]
    if not positions:
        return text[: SNIPPET_RADIUS * 2]
    start = max(0, min(positions) - SNIPPET_RADIUS)
    end = min(len(text), max(positions) + SNIPPET_RADIUS)
    snippet = text[start:end].strip()
    return ("…" if start > 0 else "") + snippet + ("…" if end < len(text) else "")


def search_archives(text, archive_id=None, directory=None):
    """在归档中做本地全文关键词检索，返回带归档编号与位置的片段。

    多个关键词以空格分隔时要求全部命中；结果数量与总长度都有限制，
    避免检索结果再次占满上下文。
    """
    query = str(text or "").strip()
    if not query:
        return "Error: text 不能为空"

    terms = [term.lower() for term in query.split()]
    archives = list_archives(directory)
    if archive_id:
        target = str(archive_id).strip()
        archives = [path for path in archives if path.stem == target]
        if not archives:
            available = "、".join(path.stem for path in list_archives(directory)[:10])
            return (
                f"Error: 未找到编号为 {target} 的上下文归档；"
                f"可用归档：{available or '无'}"
            )
    if not archives:
        return "Error: 尚无上下文归档，请先通过 /compact 压缩上下文"

    blocks = []
    total_matches = 0
    total_chars = 0
    truncated = False
    matched_files = 0

    for path in archives:
        try:
            lines = path.read_text(encoding="utf-8").splitlines()
        except OSError:
            continue

        file_hit = False
        for number, raw in enumerate(lines, 1):
            if not raw.strip():
                continue
            try:
                message = json.loads(raw)
            except json.JSONDecodeError:
                continue
            if not isinstance(message, dict):
                continue

            body = _body_text(message)
            haystack = body.lower()
            if not all(term in haystack for term in terms):
                continue

            total_matches += 1
            file_hit = True
            if len(blocks) >= MAX_RECALL_SNIPPETS or total_chars >= MAX_RECALL_CHARS:
                truncated = True
                continue

            block = (
                f"[{len(blocks) + 1}] 归档 {path.stem} · 第 {number} 条消息 · "
                f"role={message.get('role', 'unknown')}\n{_snippet(body, terms)}"
            )
            blocks.append(block)
            total_chars += len(block)
        if file_hit:
            matched_files += 1

    if not blocks:
        scope = f"归档 {archive_id}" if archive_id else "全部归档"
        return f"未在{scope}中找到包含「{query}」的内容"

    header = (
        f"在 {matched_files} 个归档中检索「{query}」，"
        f"共匹配 {total_matches} 条消息：\n"
    )
    footer = ""
    if truncated:
        footer = (
            f"\n\n（结果已截断，仅显示前 {len(blocks)} 条。"
            "可传入 id 精确检索某个归档，或换用更具体的关键词。）"
        )
    return header + "\n\n".join(blocks) + footer
