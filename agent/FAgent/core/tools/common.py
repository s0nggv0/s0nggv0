"""文件工具共享的路径、编码与文本判定辅助函数。"""

import os
from pathlib import Path

from ..config import setting, setting_bool


class PathNotAllowed(Exception):
    """路径超出允许访问的根目录时抛出。"""


def decode_output(raw):
    """命令输出编码随终端代码页变化，依次尝试 UTF-8 / GBK"""
    for enc in ("utf-8", "gbk"):
        try:
            return raw.decode(enc)
        except UnicodeDecodeError:
            continue
    return raw.decode("utf-8", errors="replace")


def allowed_root():
    """返回文件工具允许访问的根目录；返回 None 表示不限制。

    [filesystem] root 留空时以启动时的工作目录为根，
    allow_outside=true 时完全关闭边界校验。
    """
    if setting_bool("filesystem.allow_outside", False):
        return None
    raw = str(setting("filesystem.root", "") or "").strip()
    base = raw or os.getcwd()
    return Path(os.path.realpath(os.path.expanduser(base)))


def resolve_path(path):
    """把用户/模型给出的路径转成绝对路径，并校验是否在允许的根目录内。

    相对路径基于进程当前工作目录；符号链接按真实路径判断，
    避免通过链接绕过边界。
    """
    target = os.path.realpath(os.path.expanduser(str(path)))
    root = allowed_root()
    if root is None:
        return target
    try:
        Path(target).relative_to(root)
    except ValueError as exc:
        raise PathNotAllowed(
            f"拒绝访问工作区之外的路径：{target}（允许范围：{root}，"
            "可在 config.ini 的 [filesystem] 调整 root 或 allow_outside）"
        ) from exc
    return target


def detect_encoding(path):
    """探测文本文件编码，依次尝试 UTF-8 / GBK"""
    with open(path, "rb") as f:
        raw = f.read(8192)
    for enc in ("utf-8", "gbk"):
        try:
            raw.decode(enc)
            return enc
        except UnicodeDecodeError:
            continue
    return "utf-8"


def is_text_file(path):
    """通过是否包含 NUL 字节以及能否按 UTF-8/GBK 解码判断是否为纯文本文件"""
    with open(path, "rb") as f:
        chunk = f.read(8192)
    if b"\x00" in chunk:
        return False
    for enc in ("utf-8", "gbk"):
        try:
            chunk.decode(enc)
            return True
        except UnicodeDecodeError:
            continue
    return False
