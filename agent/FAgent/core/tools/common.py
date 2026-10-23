"""文件工具共享的路径、编码与文本判定辅助函数。"""

import os


def decode_output(raw):
    """命令输出编码随终端代码页变化，依次尝试 UTF-8 / GBK"""
    for enc in ("utf-8", "gbk"):
        try:
            return raw.decode(enc)
        except UnicodeDecodeError:
            continue
    return raw.decode("utf-8", errors="replace")


def resolve_path(path):
    """把用户/模型给出的路径转成绝对路径，相对路径基于进程当前工作目录"""
    return os.path.abspath(os.path.expanduser(path))


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
