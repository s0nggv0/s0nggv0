# -*- coding: utf-8 -*-
"""FAgent 自测脚本：不依赖模型与网络，直接验证工具层与核心模块的关键行为。

用法：
    python selfcheck.py

覆盖：
- 闰年规则（含整百年被 400 整除的边界）
- 跨平台日期格式、当前工作目录
- 工具注册表：未知工具、缺少必填参数、异常兜底
- 文件/目录工具的真实副作用（建目录、建文件、追加、读、列、改类型、重命名、删除）
- 路径白名单：工作区之外的路径被拒绝
- 技能创建（命名规范化、重复拒绝、frontmatter）与加载截断
- 会话保存 / 读取往返
- 上下文归档与关键词检索
"""

import os
import re
import shutil
import sys
import tempfile
from datetime import datetime
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))

import logging

from core import skills as skills_module
from core.config import AppConfig, activate_config
from core.context import archive_context, estimate_tokens, search_archives
from core.session import SessionStore
from core.tools import run_tool

logging.getLogger("fagent").addHandler(logging.NullHandler())
logging.getLogger("fagent").propagate = False

RESULTS = []


def check(name, condition, detail=""):
    ok = bool(condition)
    RESULTS.append((name, ok, "" if ok else detail))
    print(f"{'PASS' if ok else 'FAIL'}  {name}" + ("" if ok else f"  -> {detail}"))


def expect_error(name, text, keyword):
    check(name, isinstance(text, str) and text.startswith("Error:") and keyword in text, text)


def main():
    tmp = Path(tempfile.mkdtemp(prefix="fagent-selfcheck-"))
    workspace = tmp / "workspace"
    workspace.mkdir()
    sessions_dir = tmp / "sessions"
    context_dir = tmp / "context"
    skills_module.PROJECT_ROOT = workspace
    origin = os.getcwd()
    # 相对路径以进程工作目录为基准，这里切到临时工作区，避免碰到真实项目文件
    os.chdir(workspace)

    activate_config(
        AppConfig(
            base_url="http://127.0.0.1:0",
            model_name="selfcheck",
            key="selfcheck",
            values={
                "filesystem.root": str(workspace),
                "filesystem.allow_outside": "false",
                "skills.max_chars": "80",
                "session.directory": str(sessions_dir),
                "log.directory": str(tmp / "logs"),
            },
        )
    )

    # ---------------- 系统类工具
    for year, expected in ((2024, True), (2023, False), (1900, False), (2000, True)):
        text = run_tool("isLeapYear", {"year": year})
        check(f"isLeapYear {year} -> {expected}", (("不是" not in text) is expected), text)

    date_text = run_tool("getDate", {})
    check(
        "getDate 返回本地日期时间",
        bool(re.match(r"^\d{4}-\d{2}-\d{2} \d{2}:\d{2}:\d{2}", date_text))
        and str(datetime.now().year) in date_text,
        date_text,
    )
    check("getCwd 等于进程工作目录", run_tool("getCwd", {}) == os.getcwd())

    # ---------------- 注册表
    expect_error("未知工具被拒绝", run_tool("noSuchTool", {}), "unknown tool")
    expect_error("缺少必填参数被拒绝", run_tool("isLeapYear", {}), "缺少参数")
    expect_error("非对象参数被拒绝", run_tool("isLeapYear", "2024"), "JSON 对象")

    # ---------------- 文件 / 目录工具真实副作用
    created_dir = run_tool("createDirectory", {"path": "docs/sub"})
    check("createDirectory 建多级目录", (workspace / "docs/sub").is_dir(), created_dir)

    created_file = run_tool(
        "createFile", {"directory": "docs", "filename": "note.txt", "content": "hello"}
    )
    target = workspace / "docs" / "note.txt"
    check("createFile 真实落盘", target.is_file() and target.read_text(encoding="utf-8") == "hello", created_file)
    expect_error(
        "createFile 目标存在时拒绝覆盖",
        run_tool("createFile", {"directory": "docs", "filename": "note.txt", "content": "x"}),
        "已存在",
    )

    run_tool("editFile", {"path": "docs/note.txt", "content": " world", "mode": "append"})
    check(
        "editFile append 追加内容",
        target.read_text(encoding="utf-8").endswith(" world"),
        target.read_text(encoding="utf-8"),
    )

    read_back = run_tool("readFile", {"path": "docs/note.txt"})
    check("readFile 读回内容", "hello world" in read_back, read_back)

    listing = run_tool("listDirectory", {"path": "docs"})
    check("listDirectory 枚举真实目录项", "note.txt" in listing and "sub" in listing, listing)

    type_text = run_tool("getFileType", {"path": "docs/note.txt"})
    check("getFileType 区分文本类型", "文本文件" in type_text and "txt" in type_text, type_text)

    renamed = run_tool("renamePath", {"src": "docs/note.txt", "dst": "docs/note2.txt"})
    moved = workspace / "docs" / "note2.txt"
    check("renamePath 真实改名", moved.is_file() and not target.exists(), renamed)

    deleted = run_tool("deleteFile", {"path": "docs/note2.txt"})
    check("deleteFile 真实删除", not moved.exists(), deleted)

    removed_dir = run_tool("deleteDirectory", {"path": "docs"})
    expect_error("deleteDirectory 拒绝删除工作区根", run_tool("deleteDirectory", {"path": "."}), "拒绝删除")
    check("deleteDirectory 真实删除非空目录", not (workspace / "docs").exists(), removed_dir)

    # ---------------- 路径白名单
    outside = Path(tmp) / "outside.txt"
    outside.write_text("nope", encoding="utf-8")
    expect_error("工作区外读取被拒绝", run_tool("readFile", {"path": str(outside)}), "拒绝访问")
    expect_error("工作区外建文件被拒绝", run_tool("createFile", {"directory": str(tmp), "filename": "x.txt"}), "拒绝访问")

    # ---------------- 技能创建与加载
    long_body = "# 长技能\n\n" + "细节说明。" * 40
    created_skill = run_tool("createSkill", {"name": "Weekly Report", "skillContext": long_body})
    skill_dir = workspace / ".agents" / "skills" / "weekly-report"
    skill_file = skill_dir / "SKILL.md"
    check("createSkill 目录与 SKILL.md 落盘", skill_file.is_file(), created_skill)
    content = skill_file.read_text(encoding="utf-8") if skill_file.is_file() else ""
    check(
        "createSkill 生成 frontmatter 与规范名",
        content.startswith("---") and "name: weekly-report" in content and "description:" in content,
        content[:120],
    )
    expect_error(
        "createSkill 拒绝覆盖同名技能",
        run_tool("createSkill", {"name": "weekly-report", "skillContext": long_body}),
        "已存在",
    )

    loaded = run_tool("loadSkill", {"name": "weekly-report"})
    check("loadSkill 读取技能全文并按上限截断", "已截断" in loaded, loaded[:160])
    expect_error("loadSkill 拒绝读取技能目录外文件", run_tool("loadSkill", {"name": "weekly-report", "filename": "../../../outside.txt"}), "Error:")

    # ---------------- 会话往返
    store = SessionStore(directory=str(sessions_dir))
    session_id = store.new_id()
    history = [
        {"role": "user", "content": "第一条问题"},
        {"role": "assistant", "content": "第一条回答"},
    ]
    info = store.save(session_id, history, model="selfcheck")
    payload = store.load(session_id)
    check(
        "会话保存/读取往返一致",
        info.message_count == 2 and payload["history"] == history and payload["title"] == "第一条问题",
        str(payload)[:160],
    )
    check("会话列表可枚举", any(item.id == session_id for item in store.list()))

    # ---------------- 上下文归档与检索
    check("token 估算对空文本为 0 且对中文大于 0", estimate_tokens("") == 0 and estimate_tokens("中文五个字") > 0)
    archive_id, archive_path, _ = archive_context(
        "system", [{"role": "user", "content": "需要记住的关键路径是 D:/xx/agent"}], directory=context_dir
    )
    hit = search_archives("关键路径", directory=context_dir)
    check(
        "上下文归档后可检索",
        archive_path.is_file() and archive_id in hit and "关键路径" in hit,
        hit[:160],
    )

    failed = [name for name, ok, _ in RESULTS if not ok]
    total = len(RESULTS)
    print("\n" + "-" * 48)
    print(f"共 {total} 项，通过 {total - len(failed)} 项，失败 {len(failed)} 项")
    for name, _, detail in RESULTS:
        if detail:
            print(f"  [FAIL] {name}: {detail}")

    os.chdir(origin)
    shutil.rmtree(tmp, ignore_errors=True)
    return 0 if not failed else 1


if __name__ == "__main__":
    sys.exit(main())
