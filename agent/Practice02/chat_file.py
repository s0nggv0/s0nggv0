from openai import OpenAI
import json
import mimetypes
import os
import shutil
import subprocess
import sys

SCRIPT_DIR = os.path.dirname(os.path.abspath(__file__))
CONFIG_PATH = os.path.join(SCRIPT_DIR, "config.ini")

# 单次列目录最多返回的条目数，防止输出过长
MAX_LIST_ENTRIES = 500

# 读取文件时默认返回的最大字符数
DEFAULT_MAX_CHARS = 20000


def load_config(path):
    cfg = {}
    with open(path, "r", encoding="utf-8") as f:
        for line in f:
            line = line.strip()
            if not line or line.startswith("#"):
                continue
            key, _, value = line.partition("=")
            cfg[key.strip()] = value.strip()
    return cfg


def _decode(raw):
    """date 命令输出编码随终端代码页变化，依次尝试 UTF-8 / GBK"""
    for enc in ("utf-8", "gbk"):
        try:
            return raw.decode(enc)
        except UnicodeDecodeError:
            continue
    return raw.decode("utf-8", errors="replace")


def _resolve(path):
    """把用户/模型给出的路径转成绝对路径，相对路径基于进程当前工作目录"""
    return os.path.abspath(os.path.expanduser(path))


def _detect_encoding(path):
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


def _is_text_file(path):
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


def getDate():
    try:
        result = subprocess.run(
            ["cmd", "/c", "date /t && time /t"],
            capture_output=True,
            timeout=5,
        )
        if result.returncode == 0:
            out = _decode(result.stdout or b"")
            return " ".join(line.strip() for line in out.splitlines() if line.strip())
        err = _decode(result.stderr or b"") if result.stderr else ""
        return f"Error: {err}"
    except subprocess.TimeoutExpired:
        return "Error: date command timeout"
    except Exception as e:
        return f"Error: {e}"


def isLeapYear(year):
    if (year % 4 == 0 and year % 100 != 0) or (year % 400 == 0):
        return True
    return False


def getCwd():
    return os.getcwd()


def listDirectory(path=".", recursive=False):
    base = _resolve(path)
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


def getFileType(path):
    p = _resolve(path)
    if not os.path.exists(p):
        return f"Error: 路径不存在：{p}"
    if os.path.isdir(p):
        return f"{p}\n类型：目录"
    if not os.path.isfile(p):
        return f"{p}\n类型：其他（非普通文件）"

    mime, _ = mimetypes.guess_type(p)
    ext = os.path.splitext(p)[1].lower() or "无"
    kind = "文本文件" if _is_text_file(p) else "二进制文件"
    return (
        f"{p}\n类型：{kind}\nMIME：{mime or '未知'}\n扩展名：{ext}"
    )


def readFile(path, max_chars=DEFAULT_MAX_CHARS):
    p = _resolve(path)
    if not os.path.isfile(p):
        return f"Error: 文件不存在：{p}"
    if not _is_text_file(p):
        return f"Error: {p} 不是纯文本文件，仅支持读取纯文本格式文件"

    try:
        max_chars = int(max_chars)
    except (TypeError, ValueError):
        max_chars = DEFAULT_MAX_CHARS
    if max_chars <= 0:
        max_chars = DEFAULT_MAX_CHARS

    enc = _detect_encoding(p)
    with open(p, "r", encoding=enc, errors="replace") as f:
        content = f.read()

    total = len(content)
    if total > max_chars:
        content = content[:max_chars] + f"\n...（内容已截断，文件共 {total} 字符）"
    return f"文件：{p}\n编码：{enc}\n\n{content}"


def createFile(directory=".", filename="", content=""):
    if not filename:
        return "Error: 缺少参数 filename"
    base = _resolve(directory or ".")
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


def editFile(path, content="", mode="overwrite"):
    p = _resolve(path)
    if not os.path.isfile(p):
        return f"Error: 文件不存在：{p}（新建文件请使用 createFile）"
    if not _is_text_file(p):
        return f"Error: {p} 不是纯文本文件，仅支持编辑纯文本格式文件"
    if mode not in ("overwrite", "append"):
        return f"Error: mode 只能是 overwrite 或 append，收到：{mode}"

    enc = _detect_encoding(p)
    try:
        with open(p, "a" if mode == "append" else "w", encoding=enc, newline="") as f:
            f.write(content or "")
    except OSError as e:
        return f"Error: 编辑文件失败：{e}"

    action = "追加内容到" if mode == "append" else "覆盖写入"
    return f"已{action}：{p}（当前 {os.path.getsize(p)} bytes，编码 {enc}）"


def createDirectory(path):
    p = _resolve(path)
    if os.path.exists(p):
        if os.path.isdir(p):
            return f"目录已存在：{p}"
        return f"Error: {p} 已存在且不是目录"
    try:
        os.makedirs(p, exist_ok=True)
    except OSError as e:
        return f"Error: 创建目录失败：{e}"
    return f"已创建目录：{p}"


def deleteDirectory(path):
    p = _resolve(path)
    if not os.path.isdir(p):
        return f"Error: 目录不存在：{p}"

    drive, tail = os.path.splitdrive(p)
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


def deleteFile(path):
    p = _resolve(path)
    if not os.path.isfile(p):
        return f"Error: 文件不存在：{p}"
    try:
        os.remove(p)
    except OSError as e:
        return f"Error: 删除文件失败：{e}"
    return f"已删除文件：{p}"


def renamePath(src, dst):
    s = _resolve(src)
    d = _resolve(dst)
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


def run_tool(name, args):
    """根据工具名分发执行，统一兜底异常"""
    handlers = {
        "getDate": lambda: getDate(),
        "isLeapYear": lambda: (
            f"{args.get('year')} 年是闰年"
            if isLeapYear(int(args["year"]))
            else f"{args.get('year')} 年不是闰年"
        )
        if args.get("year") is not None
        else "Error: 缺少参数 year",
        "getCwd": lambda: getCwd(),
        "listDirectory": lambda: listDirectory(
            args.get("path") or ".", bool(args.get("recursive", False))
        ),
        "getFileType": lambda: (
            getFileType(args["path"])
            if args.get("path")
            else "Error: 缺少参数 path"
        ),
        "readFile": lambda: (
            readFile(args["path"], args.get("max_chars", DEFAULT_MAX_CHARS))
            if args.get("path")
            else "Error: 缺少参数 path"
        ),
        "createFile": lambda: createFile(
            args.get("directory") or ".",
            args.get("filename") or "",
            args.get("content") or "",
        ),
        "editFile": lambda: (
            editFile(
                args["path"],
                args.get("content") or "",
                args.get("mode") or "overwrite",
            )
            if args.get("path")
            else "Error: 缺少参数 path"
        ),
        "createDirectory": lambda: (
            createDirectory(args["path"])
            if args.get("path")
            else "Error: 缺少参数 path"
        ),
        "deleteDirectory": lambda: (
            deleteDirectory(args["path"])
            if args.get("path")
            else "Error: 缺少参数 path"
        ),
        "deleteFile": lambda: (
            deleteFile(args["path"])
            if args.get("path")
            else "Error: 缺少参数 path"
        ),
        "renamePath": lambda: (
            renamePath(args["src"], args["dst"])
            if args.get("src") and args.get("dst")
            else "Error: 缺少参数 src 或 dst"
        ),
    }
    handler = handlers.get(name)
    if handler is None:
        return f"Error: unknown tool {name}"
    try:
        return handler()
    except Exception as e:
        return f"Error: 工具 {name} 执行失败：{e}"


TOOLS = [
    {
        "type": "function",
        "function": {
            "name": "getDate",
            "description": "获取当前电脑的日期和时间",
            "parameters": {"type": "object", "properties": {}, "required": []},
        },
    },
    {
        "type": "function",
        "function": {
            "name": "isLeapYear",
            "description": "判断输入的年份是否是闰年",
            "parameters": {
                "type": "object",
                "properties": {
                    "year": {
                        "type": "integer",
                        "description": "要判断的年份，例如 2024",
                    }
                },
                "required": ["year"],
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "getCwd",
            "description": "获取当前工作目录的绝对路径",
            "parameters": {"type": "object", "properties": {}, "required": []},
        },
    },
    {
        "type": "function",
        "function": {
            "name": "listDirectory",
            "description": "列出指定目录下的所有文件和子目录，并显示文件大小",
            "parameters": {
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
        },
    },
    {
        "type": "function",
        "function": {
            "name": "getFileType",
            "description": "获取指定文件的类型，包括是文本文件还是二进制文件、MIME 类型和扩展名",
            "parameters": {
                "type": "object",
                "properties": {
                    "path": {"type": "string", "description": "文件路径"}
                },
                "required": ["path"],
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "readFile",
            "description": "读取指定纯文本文件的内容，自动识别 UTF-8/GBK 编码，非纯文本文件会返回错误",
            "parameters": {
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
        },
    },
    {
        "type": "function",
        "function": {
            "name": "createFile",
            "description": "在指定的目录和文件名下创建新文件，目录不存在时会自动创建（含多级目录），目标已存在时不会覆盖",
            "parameters": {
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
        },
    },
    {
        "type": "function",
        "function": {
            "name": "editFile",
            "description": "编辑指定纯文本文件的内容，支持整文件覆盖或追加。文件必须已存在且为纯文本格式",
            "parameters": {
                "type": "object",
                "properties": {
                    "path": {"type": "string", "description": "要编辑的文件路径"},
                    "content": {
                        "type": "string",
                        "description": "要写入或追加的内容",
                    },
                    "mode": {
                        "type": "string",
                        "enum": ["overwrite", "append"],
                        "description": "overwrite 表示覆盖全部内容（默认），append 表示追加到文件末尾",
                    },
                },
                "required": ["path", "content"],
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "createDirectory",
            "description": "创建新目录，支持一次创建多级目录，目录已存在时不会报错",
            "parameters": {
                "type": "object",
                "properties": {
                    "path": {"type": "string", "description": "要创建的目录路径"}
                },
                "required": ["path"],
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "deleteDirectory",
            "description": "删除指定目录及其全部内容（支持非空目录），拒绝删除磁盘根目录或当前工作目录及其上级目录",
            "parameters": {
                "type": "object",
                "properties": {
                    "path": {"type": "string", "description": "要删除的目录路径"}
                },
                "required": ["path"],
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "deleteFile",
            "description": "删除指定的文件",
            "parameters": {
                "type": "object",
                "properties": {
                    "path": {"type": "string", "description": "要删除的文件路径"}
                },
                "required": ["path"],
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "renamePath",
            "description": "重命名文件或目录，目标路径不能已存在；目标父目录不存在时会自动创建",
            "parameters": {
                "type": "object",
                "properties": {
                    "src": {"type": "string", "description": "原文件或目录路径"},
                    "dst": {"type": "string", "description": "新的文件或目录路径"},
                },
                "required": ["src", "dst"],
            },
        },
    },
]


def main():
    if not os.path.exists(CONFIG_PATH):
        print("错误：config.ini 不存在")
        sys.exit(1)

    cfg = load_config(CONFIG_PATH)
    for field in ("base_url", "model_name", "key"):
        if field not in cfg:
            print("错误：缺少字段 " + field)
            sys.exit(1)

    tool_names = ", ".join(tool["function"]["name"] for tool in TOOLS)
    print(f"你好，有什么问题（支持 function call: {tool_names}）")
    history = []
    while True:
        try:
            print()
            prompt = input("我：")
        except EOFError:
            break
        except KeyboardInterrupt:
            break
        history.append({"role": "user", "content": prompt})
        print("---")

        client = OpenAI(base_url=cfg["base_url"], api_key=cfg["key"])

        while True:
            response = client.chat.completions.create(
                model=cfg["model_name"],
                messages=history,
                tools=TOOLS,
                tool_choice="auto",
                stream=False,
            )

            message = response.choices[0].message

            if message.tool_calls:
                history.append(message.model_dump(exclude_none=True))
                for tool_call in message.tool_calls:
                    try:
                        args = json.loads(tool_call.function.arguments or "{}")
                    except json.JSONDecodeError as e:
                        tool_result = f"Error: 参数不是合法 JSON：{e}"
                    else:
                        if not isinstance(args, dict):
                            tool_result = "Error: 工具参数必须是 JSON 对象"
                        else:
                            tool_result = run_tool(tool_call.function.name, args)
                    history.append(
                        {
                            "role": "tool",
                            "tool_call_id": tool_call.id,
                            "content": tool_result,
                        }
                    )
                    print(tool_result)
            else:
                reply = message.content or ""
                print(reply)
                history.append({"role": "assistant", "content": reply})
                break


if __name__ == "__main__":
    main()
