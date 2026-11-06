"""会话事件日志：把聊天历史持久化到 .agents/sessions/*.jsonl。

文件采用「每行一个事件」的 JSONL 格式：
- 第一行是 meta（会话编号、标题、创建 / 更新时间、模型）；
- 之后按顺序记录 message 与 agents_guidance 事件，恢复会话时按原顺序回放。

会话目录可通过 config.ini 的 [session] directory 配置，默认 .agents/sessions。
"""

import json
import os
import threading
from dataclasses import dataclass
from datetime import datetime
from pathlib import Path

from .config import setting
from .skills import project_root, read_text

# 注入 AGENTS.md 的消息前缀，用于避免重复注入与识别事件类型
AGENTS_MARKER = "【项目规范 AGENTS.md】"

SESSION_EVENT_AGENTS = "agents_guidance"
SESSION_EVENT_MESSAGE = "message"


@dataclass(frozen=True)
class SessionInfo:
    id: str
    title: str
    created_at: str
    updated_at: str
    message_count: int
    model: str
    path: str


def session_dir(directory=None):
    """会话目录：config.ini 配置的路径（相对项目根），默认 .agents/sessions。"""
    raw = directory or setting("session.directory", ".agents/sessions")
    path = Path(raw)
    return path if path.is_absolute() else project_root() / path


def _timestamp():
    return datetime.now().strftime("%Y-%m-%d %H:%M:%S")


def _infer_title(history):
    """用第一条普通用户消息作为标题，跳过 AGENTS.md 注入消息。"""
    for message in history or []:
        if message.get("role") != "user":
            continue
        content = message.get("content")
        if not isinstance(content, str):
            continue
        text = content.strip()
        if not text or text.startswith(AGENTS_MARKER):
            continue
        line = text.splitlines()[0].strip()
        return line[:40] + ("…" if len(line) > 40 else "")
    return "（空会话）"


def _read_meta(path):
    try:
        with open(path, "r", encoding="utf-8") as f:
            first = f.readline()
        meta = json.loads(first)
    except (OSError, json.JSONDecodeError, StopIteration):
        return None
    return meta if isinstance(meta, dict) and meta.get("type") == "meta" else None


class SessionStore:
    """负责会话的保存、列举与读取。"""

    def __init__(self, directory=None):
        self.directory = session_dir(directory)
        self._write_lock = threading.Lock()

    def path_for(self, session_id):
        return self.directory / f"{session_id}.jsonl"

    def new_id(self):
        base = datetime.now().strftime("%Y%m%d-%H%M%S")
        session_id = base
        index = 1
        while self.path_for(session_id).exists():
            session_id = f"{base}-{index}"
            index += 1
        return session_id

    def list(self):
        """列出全部会话，按更新时间倒序。"""
        if not self.directory.is_dir():
            return []
        sessions = []
        for path in self.directory.glob("*.jsonl"):
            if not path.is_file():
                continue
            meta = _read_meta(path)
            sessions.append(
                SessionInfo(
                    id=path.stem,
                    title=(meta or {}).get("title") or "（无法读取）",
                    created_at=(meta or {}).get("created_at") or "",
                    updated_at=(meta or {}).get("updated_at") or "",
                    message_count=int((meta or {}).get("message_count") or 0),
                    model=(meta or {}).get("model") or "",
                    path=str(path),
                )
            )
        return sorted(sessions, key=lambda item: item.updated_at, reverse=True)

    def save(
        self,
        session_id,
        history,
        model="",
        title=None,
        created_at=None,
        additional_events=None,
    ):
        """写入完整会话事件日志，返回会话信息。

        additional_events 用于记录不属于普通消息的事件（例如 AGENTS.md 注入）。
        """
        created = created_at or _timestamp()
        path = self.path_for(session_id)
        existing_meta = _read_meta(path) if path.is_file() else None
        if existing_meta and existing_meta.get("created_at"):
            created = existing_meta["created_at"]

        meta = {
            "type": "meta",
            "id": session_id,
            "title": title or _infer_title(history),
            "created_at": created,
            "updated_at": _timestamp(),
            "message_count": len(history or []),
            "model": model,
        }

        events = []
        for message in history or []:
            event_type = SESSION_EVENT_MESSAGE
            content = message.get("content")
            if (
                message.get("role") == "user"
                and isinstance(content, str)
                and content.lstrip().startswith(AGENTS_MARKER)
            ):
                event_type = SESSION_EVENT_AGENTS
            events.append({"type": event_type, "message": message})
        events.extend(additional_events or [])

        with self._write_lock:
            try:
                self.directory.mkdir(parents=True, exist_ok=True)
                temp_path = path.with_suffix(".jsonl.tmp")
                with open(temp_path, "w", encoding="utf-8", newline="") as f:
                    f.write(json.dumps(meta, ensure_ascii=False) + "\n")
                    for event in events:
                        f.write(json.dumps(event, ensure_ascii=False) + "\n")
                os.replace(temp_path, path)
            except OSError as e:
                raise OSError(f"保存会话失败：{e}") from e

        return SessionInfo(
            id=session_id,
            title=meta["title"],
            created_at=meta["created_at"],
            updated_at=meta["updated_at"],
            message_count=meta["message_count"],
            model=meta["model"],
            path=str(path),
        )

    def load(self, session_id):
        """读取会话，返回 dict：id / title / created_at / updated_at / model / history。"""
        path = self.path_for(session_id)
        if not path.is_file():
            raise FileNotFoundError(f"会话不存在：{session_id}")

        history = []
        meta = None
        try:
            with open(path, "r", encoding="utf-8") as f:
                for line in f:
                    line = line.strip()
                    if not line:
                        continue
                    try:
                        event = json.loads(line)
                    except json.JSONDecodeError:
                        continue
                    if not isinstance(event, dict):
                        continue
                    if event.get("type") == "meta":
                        meta = event
                        continue
                    message = event.get("message")
                    if isinstance(message, dict):
                        history.append(message)
        except OSError as e:
            raise OSError(f"读取会话失败：{e}") from e

        meta = meta or {}
        return {
            "id": session_id,
            "title": meta.get("title") or _infer_title(history),
            "created_at": meta.get("created_at") or "",
            "updated_at": meta.get("updated_at") or "",
            "message_count": meta.get("message_count") or len(history),
            "model": meta.get("model") or "",
            "history": history,
            "path": str(path),
        }


def read_agents_guidance(filename=None, max_chars=None):
    """读取项目根目录下的 AGENTS.md，返回 (路径, 文本)；不存在时返回 (None, None)。"""
    name = filename or setting("agents.file", "AGENTS.md")
    path = Path(name)
    if not path.is_absolute():
        path = project_root() / path
    if not path.is_file():
        return None, None
    try:
        text = read_text(path)
    except (OSError, UnicodeDecodeError):
        return None, None
    limit = max_chars if max_chars is not None else setting("agents.max_chars", 200_000)
    try:
        limit = int(limit)
    except (TypeError, ValueError):
        limit = 200_000
    if limit > 0 and len(text) > limit:
        text = text[:limit] + "\n\n…（AGENTS.md 内容过长，已截断）"
    return path, text


def build_agents_message(path, text):
    """把 AGENTS.md 内容包装成一条可持久化的聊天消息。"""
    return {
        "role": "user",
        "content": f"{AGENTS_MARKER}\n来源：{path}\n\n{text}",
    }


def is_agents_message(message):
    content = (message or {}).get("content")
    return (
        message.get("role") == "user"
        and isinstance(content, str)
        and content.lstrip().startswith(AGENTS_MARKER)
    )
