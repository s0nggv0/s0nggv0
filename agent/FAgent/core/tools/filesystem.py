"""文件系统类工具：目录浏览与文件/目录增删改查。"""

import mimetypes
import os
import shutil

from .common import detect_encoding, is_text_file, resolve_path
from .registry import tool

MAX_LIST_ENTRIES = 500
DEFAULT_MAX_CHARS = 20000


@tool(
    "listDirectory",
    "列出指定目录下的所有文件和子目录，并显示文件大小",
    {
        "type": "object",
        "properties": {
            "path": {
                "type": "string",
                "description": "要列出的目录路径，相对路径基于当前工作目录，默认为当前目录",
            },
            "recursive": {
                "type": "boolean",
                "description": "是否递归列出所有子目录内容，默认 false",
            },
        },
        "required": [],
    },
)
def list_directory(path=".", recursive=False):
    base = resolve_path(path or ".")
    if not os.path.isdir(base):
        return f"Error: 目录不存在：{base}"

    lines = [f"目录：{base}"]
    count = 0

    def add_entry(display, full):
        nonlocal count
        if count >= MAX_LIST_ENTRIES:
            return
        count += 1
        if os.path.isdir(full):
            lines.append(f"[DIR]  {display}")
        else:
            try:
                size = os.path.getsize(full)
            except OSError:
                size = 0
            lines.append(f"[FILE] {display} ({size} bytes)")

    if recursive:
        for root, dirs, files in os.walk(base):
            dirs.sort()
            files.sort()
            rel = os.path.relpath(root, base)
            prefix = "" if rel == "." else rel + os.sep
            for d in dirs:
                add_entry(prefix + d, os.path.join(root, d))
            for f in files:
                add_entry(prefix + f, os.path.join(root, f))
    else:
        for name in sorted(os.listdir(base)):
            add_entry(name, os.path.join(base, name))

    if not count:
        lines.append("（空目录）")
    elif count >= MAX_LIST_ENTRIES:
        lines.append(f"...（条目过多，仅显示前 {MAX_LIST_ENTRIES} 项）")
    return "\n".join(lines)


@tool(
    "getFileType",
    "获取指定文件的类型，包括是文本文件还是二进制文件、MIME 类型和扩展名",
    {
        "type": "object",
        "properties": {"path": {"type": "string", "description": "文件路径"}},
        "required": ["path"],
    },
)
def get_file_type(path):
    p = resolve_path(path)
    if not os.path.exists(p):
        return f"Error: 路径不存在：{p}"
    if os.path.isdir(p):
        return f"{p}\n类型：目录"
    if not os.path.isfile(p):
        return f"{p}\n类型：其他（非普通文件）"

    mime, _ = mimetypes.guess_type(p)
    ext = os.path.splitext(p)[1].lower() or "无"
    kind = "文本文件" if is_text_file(p) else "二进制文件"
    return f"{p}\n类型：{kind}\nMIME：{mime or '未知'}\n扩展名：{ext}"


@tool(
    "readFile",
    "读取指定纯文本文件的内容，自动识别 UTF-8/GBK 编码，非纯文本文件会返回错误",
    {
        "type": "object",
        "properties": {
            "path": {"type": "string", "description": "要读取的文件路径"},
            "max_chars": {
                "type": "integer",
                "description": "最多返回的字符数，默认 20000，超出会截断",
            },
        },
        "required": ["path"],
    },
)
def read_file(path, max_chars=DEFAULT_MAX_CHARS):
    p = resolve_path(path)
    if not os.path.isfile(p):
        return f"Error: 文件不存在：{p}"
    if not is_text_file(p):
        return f"Error: {p} 不是纯文本文件，仅支持读取纯文本格式文件"

    try:
        max_chars = int(max_chars)
    except (TypeError, ValueError):
        max_chars = DEFAULT_MAX_CHARS
    if max_chars <= 0:
        max_chars = DEFAULT_MAX_CHARS

    enc = detect_encoding(p)
    with open(p, "r", encoding=enc, errors="replace") as f:
        content = f.read()

    total = len(content)
    if total > max_chars:
        content = content[:max_chars] + f"\n...（内容已截断，文件共 {total} 字符）"
    return f"文件：{p}\n编码：{enc}\n\n{content}"


@tool(
    "createFile",
    "在指定的目录和文件名下创建新文件，目录不存在时会自动创建（含多级目录），目标已存在时不会覆盖",
    {
        "type": "object",
        "properties": {
            "directory": {
                "type": "string",
                "description": "文件所在目录，默认为当前工作目录",
            },
            "filename": {
                "type": "string",
                "description": "文件名，可包含子路径，例如 notes/todo.txt",
            },
            "content": {
                "type": "string",
                "description": "写入文件的初始内容，默认为空",
            },
        },
        "required": ["filename"],
    },
)
def create_file(directory=".", filename="", content=""):
    if not filename:
        return "Error: 缺少参数 filename"
    base = resolve_path(directory or ".")
    if os.path.exists(base) and not os.path.isdir(base):
        return f"Error: {base} 已存在且不是目录"

    try:
        os.makedirs(base, exist_ok=True)
        target = os.path.join(base, filename)
        parent = os.path.dirname(target)
        if parent:
            os.makedirs(parent, exist_ok=True)
        if os.path.exists(target):
            return f"Error: 目标已存在，未覆盖：{target}"
        with open(target, "w", encoding="utf-8", newline="") as f:
            f.write(content or "")
    except OSError as e:
        return f"Error: 创建文件失败：{e}"
    return f"已创建文件：{target}（{os.path.getsize(target)} bytes）"


@tool(
    "editFile",
    "编辑指定纯文本文件的内容，支持整文件覆盖或追加。文件必须已存在且为纯文本格式",
    {
        "type": "object",
        "properties": {
            "path": {"type": "string", "description": "要编辑的文件路径"},
            "content": {"type": "string", "description": "要写入或追加的内容"},
            "mode": {
                "type": "string",
                "enum": ["overwrite", "append"],
                "description": "overwrite 表示覆盖全部内容（默认），append 表示追加到文件末尾",
            },
        },
        "required": ["path", "content"],
    },
)
def edit_file(path, content="", mode="overwrite"):
    p = resolve_path(path)
    if not os.path.isfile(p):
        return f"Error: 文件不存在：{p}（新建文件请使用 createFile）"
    if not is_text_file(p):
        return f"Error: {p} 不是纯文本文件，仅支持编辑纯文本格式文件"
    if mode not in ("overwrite", "append"):
        return f"Error: mode 只能是 overwrite 或 append，收到：{mode}"

    enc = detect_encoding(p)
    try:
        with open(p, "a" if mode == "append" else "w", encoding=enc, newline="") as f:
            f.write(content or "")
    except OSError as e:
        return f"Error: 编辑文件失败：{e}"

    action = "追加内容到" if mode == "append" else "覆盖写入"
    return f"已{action}：{p}（当前 {os.path.getsize(p)} bytes，编码 {enc}）"


@tool(
    "createDirectory",
    "创建新目录，支持一次创建多级目录，目录已存在时不会报错",
    {
        "type": "object",
        "properties": {"path": {"type": "string", "description": "要创建的目录路径"}},
        "required": ["path"],
    },
)
def create_directory(path):
    p = resolve_path(path)
    if os.path.exists(p):
        if os.path.isdir(p):
            return f"目录已存在：{p}"
        return f"Error: {p} 已存在且不是目录"
    try:
        os.makedirs(p, exist_ok=True)
    except OSError as e:
        return f"Error: 创建目录失败：{e}"
    return f"已创建目录：{p}"


@tool(
    "deleteDirectory",
    "删除指定目录及其全部内容（支持非空目录），拒绝删除磁盘根目录或当前工作目录及其上级目录",
    {
        "type": "object",
        "properties": {"path": {"type": "string", "description": "要删除的目录路径"}},
        "required": ["path"],
    },
)
def delete_directory(path):
    p = resolve_path(path)
    if not os.path.isdir(p):
        return f"Error: 目录不存在：{p}"

    _, tail = os.path.splitdrive(p)
    cwd = os.getcwd()
    if tail in ("\\", "/"):
        return "Error: 拒绝删除磁盘根目录"
    if p == cwd or cwd.startswith(p + os.sep):
        return "Error: 拒绝删除当前工作目录或其上级目录"

    try:
        shutil.rmtree(p)
    except OSError as e:
        return f"Error: 删除目录失败：{e}"
    return f"已删除目录（含全部内容）：{p}"


@tool(
    "deleteFile",
    "删除指定的文件",
    {
        "type": "object",
        "properties": {"path": {"type": "string", "description": "要删除的文件路径"}},
        "required": ["path"],
    },
)
def delete_file(path):
    p = resolve_path(path)
    if not os.path.isfile(p):
        return f"Error: 文件不存在：{p}"
    try:
        os.remove(p)
    except OSError as e:
        return f"Error: 删除文件失败：{e}"
    return f"已删除文件：{p}"


@tool(
    "renamePath",
    "重命名文件或目录，目标路径不能已存在；目标父目录不存在时会自动创建",
    {
        "type": "object",
        "properties": {
            "src": {"type": "string", "description": "原文件或目录路径"},
            "dst": {"type": "string", "description": "新的文件或目录路径"},
        },
        "required": ["src", "dst"],
    },
)
def rename_path(src, dst):
    s = resolve_path(src)
    d = resolve_path(dst)
    if not os.path.exists(s):
        return f"Error: 源路径不存在：{s}"
    if os.path.exists(d):
        return f"Error: 目标路径已存在：{d}"
    try:
        parent = os.path.dirname(d)
        if parent:
            os.makedirs(parent, exist_ok=True)
        os.rename(s, d)
    except OSError as e:
        return f"Error: 重命名失败：{e}"
    return f"已重命名：{s} -> {d}"
