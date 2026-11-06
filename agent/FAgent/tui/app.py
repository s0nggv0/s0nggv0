"""Textual TUI 界面：只负责渲染与交互，聊天流程委托给 ChatPresenter。"""

import os
import threading
import time
from pathlib import Path

from rich.text import Text
from textual.app import App, ComposeResult
from textual.binding import Binding
from textual.containers import Horizontal, Vertical, VerticalScroll
from textual.css.query import NoMatches
from textual.message import Message
from textual.screen import ModalScreen
from textual.theme import Theme
from textual.widgets import Collapsible, Markdown, OptionList, Static, TextArea
from textual.widgets.option_list import Option

from core.tools.registry import tool_source

try:
    from core.mcp_client import mcp_status
except ImportError:  # 未安装 mcp 包时界面仍可正常使用
    def mcp_status():
        return {}

from .base import ChatPresenter, ChatView

# 取色参考 opencode 的深色暖调：近黑背景 + 暖橙强调色
ACCENT = "#fab283"
TEXT = "#e8e3dc"
MUTED = "#8d8379"
SURFACE = "#1b1917"
GREEN = "#9ece8f"
RED = "#ef7a85"

FAGENT_THEME = Theme(
    name="fagent",
    primary=ACCENT,
    secondary="#8f9ecb",
    accent=ACCENT,
    foreground=TEXT,
    background="#131211",
    surface=SURFACE,
    panel="#2c2825",
    boost="#252220",
    success=GREEN,
    warning="#f2c97d",
    error=RED,
    dark=True,
)

_SPINNER_FRAMES = "⠋⠙⠹⠸⠼⠴⠦⠧⠇⠏"

# 命令面板与 /help 共用的命令清单
COMMANDS = (
    ("/help", "显示帮助"),
    ("/tools", "列出可用工具"),
    ("/retry", "重发上一条提问"),
    ("/clear", "清空会话"),
    ("/quit", "退出程序"),
)

_SKIP_DIRS = {".git", "__pycache__", "node_modules", ".venv", "venv"}

# ANSI Shadow 字体的 FAGENT 字标
_LOGO_LINES = (
    "███████╗ █████╗  ██████╗ ███████╗███╗   ██╗████████╗",
    "██╔════╝██╔══██╗██╔════╝ ██╔════╝████╗  ██║╚══██╔══╝",
    "█████╗  ███████║██║  ███╗█████╗  ██╔██╗ ██║   ██║   ",
    "██╔══╝  ██╔══██║██║   ██║██╔══╝  ██║╚██╗██║   ██║   ",
    "██║     ██║  ██║╚██████╔╝███████╗██║ ╚████║   ██║   ",
    "╚═╝     ╚═╝  ╚═╝ ╚═════╝ ╚══════╝╚═╝  ╚═══╝   ╚═╝   ",
)
_LOGO_COLORS = ("#ffd8bd", "#fbc7a3", "#f7b78c", "#eca675", "#de955f", "#cd854f")


def _logo() -> Text:
    logo = Text()
    for line, color in zip(_LOGO_LINES, _LOGO_COLORS):
        logo.append(line + "\n", style=f"bold {color}")
    return logo


def _short_path(path, limit=52):
    """把过长的路径压缩为「盘符/…/末两级」，避免开场信息撑破面板。"""
    if len(path) <= limit:
        return path
    parts = path.replace("\\", "/").split("/")
    tail = "/".join(parts[-2:])
    return f"{parts[0]}/…/{tail}"


class WelcomeMessage(Vertical):
    """开场页：字标、简介、环境信息与操作提示。"""

    def __init__(self, tool_names, model_name):
        self._tool_names = list(tool_names)
        self._model_name = model_name
        super().__init__()

    def compose(self) -> ComposeResult:
        yield Static(_logo(), id="logo")

        tagline = Text()
        tagline.append("本地 Function Call 智能助手", style=f"bold {TEXT}")
        tagline.append("\n向模型提问，由模型决定是否调用本地工具", style=MUTED)
        yield Static(tagline, id="tagline")

        yield Horizontal(
            Vertical(
                self._row("模型", self._model_name),
                self._row("目录", _short_path(os.getcwd())),
                self._row("工具", f"{len(self._tool_names)} 个已注册"),
                id="welcome-info",
            ),
            id="welcome-info-wrap",
        )

        tips = Text()
        tips.append("直接输入问题开始", style=TEXT)
        tips.append("   ·   ", style=MUTED)
        tips.append("/help", style=ACCENT)
        tips.append(" 查看命令   ·   ", style=MUTED)
        tips.append("/tools", style=ACCENT)
        tips.append(" 查看工具", style=MUTED)
        yield Static(tips, id="welcome-tips")

    @staticmethod
    def _row(label, value):
        return Horizontal(
            Static(label, classes="k"),
            Static(value, classes="v"),
            classes="row",
        )


class UserMessage(Static):
    """用户提问消息块。"""

    def __init__(self, text):
        content = Text()
        content.append("❯ ", style=f"bold {ACCENT}")
        content.append(text, style=f"bold {TEXT}")
        super().__init__(content)


class TurnBlock(Vertical):
    """一轮对话的过程容器。

    思考提示、工具调用与回答都挂在这个容器下，结束时会补一行本轮摘要，
    让「提问 → 过程 → 结果」在长会话里保持清晰的层级。
    """

    def __init__(self):
        super().__init__()
        self.started_at = time.monotonic()
        self.tool_count = 0
        self.failed_count = 0
        # 容器挂载是异步的，先入队再统一挂上，避免快速连续事件丢消息
        self._pending = []
        self._ready = False

    def on_mount(self):
        self._ready = True
        for widget in self._pending:
            self.mount(widget)
        self._pending.clear()

    def attach(self, widget):
        """挂载子控件；容器尚未挂载时先暂存，挂载完成后按顺序补齐。"""
        if self._ready:
            self.mount(widget)
        else:
            self._pending.append(widget)

    def detach(self, widget):
        """移除子控件；尚未挂载的直接从暂存队列里丢弃。"""
        if widget in self._pending:
            self._pending.remove(widget)
        elif widget.is_mounted:
            widget.remove()

    def summary(self):
        elapsed = time.monotonic() - self.started_at
        parts = []
        if self.tool_count:
            parts.append(f"{self.tool_count} 个工具")
            if self.failed_count:
                parts.append(f"{self.failed_count} 失败")
        parts.append(f"{elapsed:.1f}s")
        return "本轮 · " + " · ".join(parts)


class AssistantMessage(Vertical):
    """助手回答消息块。

    流式期间用 Static 逐字追加并显示光标（开销小），结束后隐藏该 Static、
    显示预置的 Markdown 控件，兼顾实时性与最终排版（代码块高亮）。
    """

    def __init__(self):
        super().__init__()
        self._buffer = ""
        self._finished = False
        # 提前创建而不是结束时 mount：组件挂载是异步的，回答极快时 compose
        # 可能还没执行，后 mount 的 Markdown 会排在标签前面、旧文本也会残留
        self._body = Static(Text(""), classes="body")
        self._final = Markdown("")
        self._final.display = False

    def compose(self):
        label = Text()
        label.append("● ", style=ACCENT)
        label.append("FAgent", style=f"bold {TEXT}")
        yield Static(label, classes="label")
        yield self._body
        yield self._final

    def append(self, text):
        if self._finished:
            return
        self._buffer += text
        self._body.update(
            Text.assemble((self._buffer, TEXT), ("▍", ACCENT))
        )

    def finish(self):
        if self._finished:
            return
        self._finished = True
        self._body.display = False
        self._final.display = True
        if self._final.is_mounted:
            self._render_final()

    def on_mount(self):
        # 结束事件可能早于组件挂载，此时补渲染
        if self._finished:
            self._render_final()

    def _render_final(self):
        self._final.update(self._buffer or "（无回答）")


class ThinkingIndicator(Static):
    """思考中的行内提示，由 App 的定时器驱动帧与耗时。"""

    def tick(self, frame, elapsed):
        content = Text()
        content.append(frame, style=ACCENT)
        content.append(" 思考中", style=MUTED)
        content.append(f"  {elapsed:.1f}s", style=MUTED)
        self.update(content)


class ToolMessage(Collapsible):
    """工具调用消息块：执行中显示 spinner，完成后显示摘要与可折叠结果。"""

    def __init__(self, name, args):
        # 注意不要用 _name：DOMNode 内部同名属性会被 super().__init__ 覆盖
        self._tool_name = name
        self._tool_args = args or {}
        self._result_text = ""
        self._body = Static(Text("等待工具返回…", style=MUTED), classes="tool-body")
        super().__init__(self._body, title=f"⠋ {name}", collapsed=True)

    def tick(self, frame):
        self.title = f"{frame} {self._tool_name}{self._summary()}"

    def finish(self, result, seconds):
        result = str(result)
        self._result_text = result
        failed = result.lstrip().startswith("Error")
        mark = "✗" if failed else "✓"
        self.title = f"{mark} {self._tool_name}{self._summary()} · {seconds:.2f}s"
        self.add_class("failed" if failed else "done")
        self._body.update(self._detail(result))
        self.collapsed = result.count("\n") > 8 or len(result) > 600

    def full_text(self):
        """工具名、参数与完整输出，供复制 / 全屏查看。"""
        if not self._result_text:
            return ""
        return f"{self._tool_name}{self._summary()}\n\n{self._result_text}"

    def toggle(self):
        self.collapsed = not self.collapsed

    def _summary(self):
        if not self._tool_args:
            return ""
        text = ", ".join(f"{k}={v}" for k, v in self._tool_args.items())
        if len(text) > 46:
            text = text[:43] + "…"
        return f"({text})"

    def _detail(self, result):
        content = Text()
        content.append("参数  ", style=f"bold {MUTED}")
        content.append(str(self._tool_args), style=TEXT)
        content.append("\n\n")
        content.append(result, style=TEXT)
        return content


class ToolResultScreen(ModalScreen):
    """工具结果全屏查看：PgUp/PgDn 翻页，c 复制，Esc 关闭。"""

    BINDINGS = [
        Binding("escape", "close_viewer", "关闭", priority=True),
        Binding("pageup", "page_up", "上一页", show=False),
        Binding("pagedown", "page_down", "下一页", show=False),
        Binding("c", "copy_result", "复制", show=False),
    ]

    def __init__(self, name, text):
        super().__init__()
        self._result_name = name
        self._result_text = text

    def compose(self):
        title = Text()
        title.append(self._result_name, style=f"bold {ACCENT}")
        title.append("  工具结果", style=MUTED)
        title.append(f"  ·  {len(self._result_text.splitlines())} 行", style=MUTED)

        hint = Static(
            "PgUp / PgDn 翻页   ·   c 复制   ·   Esc 关闭",
            id="viewer-footer",
        )
        yield Vertical(
            Static(title, id="viewer-title"),
            VerticalScroll(
                Static(Text(self._result_text or "（无输出）", style=TEXT)),
                id="viewer-body",
            ),
            hint,
            id="viewer-box",
        )

    def action_close_viewer(self):
        self.dismiss()

    def action_page_up(self):
        self.query_one("#viewer-body", VerticalScroll).scroll_page_up()

    def action_page_down(self):
        self.query_one("#viewer-body", VerticalScroll).scroll_page_down()

    def action_copy_result(self):
        self.app.copy_to_clipboard(self._result_text)
        self.query_one("#viewer-footer", Static).update(
            "已复制到剪贴板（终端需支持 OSC 52）   ·   Esc 关闭"
        )


class ErrorMessage(Static):
    """错误消息块。"""

    def __init__(self, text):
        content = Text()
        content.append("✗ ", style=f"bold {RED}")
        content.append(text, style=RED)
        super().__init__(content)


class NoticeMessage(Static):
    """提示消息块：帮助、工具列表、已取消等中性信息。"""

    def __init__(self, content):
        if isinstance(content, str):
            content = Text(content, style=MUTED)
        super().__init__(content)


class HistoryTextArea(TextArea):
    """支持多行编辑与 ↑/↓ 历史回溯的输入框。

    Enter 发送；Shift+Enter（终端不支持时用 Ctrl+J）插入换行；
    直接粘贴多行文本会原样保留换行，输入框随内容自动增高。
    """

    MAX_LINES = 8

    class Submitted(Message):
        """用户按下 Enter 提交输入。"""

        def __init__(self, text_area: "HistoryTextArea"):
            self.text_area = text_area
            self.value = text_area.text
            super().__init__()

    def __init__(self, **kwargs):
        kwargs.setdefault("compact", True)
        kwargs.setdefault("show_line_numbers", False)
        kwargs.setdefault("highlight_cursor_line", False)
        super().__init__(**kwargs)
        self._history = []
        self._index = None
        self._draft = ""
        # App 注入的补全键处理函数：返回 True 表示已消费该按键
        self.completion_handler = None

    def remember(self, text):
        """记录一条已提交的输入（相邻重复不重复记录）"""
        if self._history and self._history[-1] == text:
            self._index = None
            return
        self._history.append(text)
        self._index = None

    async def _on_key(self, event):
        if self.completion_handler is not None and event.key == "tab":
            if self.completion_handler("tab"):
                event.prevent_default()
                event.stop()
                return
        if event.key == "enter":
            event.prevent_default()
            event.stop()
            self.post_message(self.Submitted(self))
            return
        if event.key in ("shift+enter", "ctrl+j"):
            event.prevent_default()
            event.stop()
            self.insert("\n")
            return
        await super()._on_key(event)

    def action_cursor_up(self, select=False):
        # 补全面板可见时优先移动选中项，否则按行移动 / 回溯历史
        if (
            not select
            and self.completion_handler is not None
            and self.completion_handler("up")
        ):
            return
        # 光标已在首行时，↑ 改为回溯历史；多行内部仍按行移动
        if not select and self.cursor_at_first_line and self._history_step(-1):
            return
        super().action_cursor_up(select)

    def action_cursor_down(self, select=False):
        if (
            not select
            and self.completion_handler is not None
            and self.completion_handler("down")
        ):
            return
        # 光标已在末行时，↓ 改为前进历史
        if not select and self.cursor_at_last_line and self._history_step(1):
            return
        super().action_cursor_down(select)

    def on_text_area_changed(self, event):
        self.sync_height()

    def sync_height(self):
        """按换行后的可视行数调整高度，超长时内部滚动。"""
        lines = max(1, self.virtual_size.height)
        height = min(lines, self.MAX_LINES)
        if self.styles.height != height:
            self.styles.height = height

    def _history_step(self, direction):
        if not self._history:
            return False
        if direction < 0:
            if self._index is None:
                self._draft = self.text
                self._index = len(self._history) - 1
            elif self._index > 0:
                self._index -= 1
            self._set_value(self._history[self._index])
        else:
            if self._index is None:
                return False
            if self._index < len(self._history) - 1:
                self._index += 1
                self._set_value(self._history[self._index])
            else:
                self._index = None
                self._set_value(self._draft)
        return True

    def _set_value(self, text):
        self.text = text
        self.cursor_location = self.document.end


class FAgentApp(App, ChatView):
    TITLE = "FAgent"
    SUB_TITLE = "Function Call TUI"

    CSS = """
    Screen {
        background: $background;
    }
    #shell {
        height: 1fr;
    }
    #topbar {
        height: 1;
        padding: 0 2;
        background: $background;
    }
    #brand {
        width: auto;
        color: $primary;
        text-style: bold;
    }
    #brand-mark {
        width: auto;
        color: $primary;
    }
    #meta {
        width: 1fr;
        content-align: right middle;
        color: $text-muted;
    }

    #main {
        height: 1fr;
    }

    #chat {
        height: 1fr;
        width: 1fr;
        padding: 1 2 0 2;
        align-horizontal: center;
        scrollbar-size-vertical: 1;
        scrollbar-visibility: hidden;
        scrollbar-background: $background;
        scrollbar-color: $panel;
        scrollbar-color-hover: $primary;
        scrollbar-color-active: $primary;
    }

    #sidebar {
        width: 28;
        height: 1fr;
        padding: 1 1 0 1;
        border-left: solid $panel;
        background: $background;
    }
    #sidebar-scroll {
        height: 1fr;
        scrollbar-size-vertical: 1;
        scrollbar-visibility: hidden;
    }
    #sidebar .section {
        width: 100%;
        height: 1;
        margin-bottom: 1;
        color: $primary;
        text-style: bold;
    }
    #sidebar .group {
        width: 100%;
        height: 1;
        margin-top: 1;
        color: $text-muted;
        text-style: bold;
    }
    #sidebar .tool {
        width: 100%;
        height: 1;
        padding: 0 0 0 1;
        color: $text-muted;
    }
    #sidebar .tool.running {
        color: $warning;
        text-style: bold;
    }
    #sidebar .list {
        width: 100%;
        height: auto;
        margin-bottom: 1;
        color: $text-muted;
    }
    #session {
        width: 100%;
        height: auto;
        margin-bottom: 1;
        color: $text-muted;
    }

    .message {
        width: 100%;
        max-width: 108;
        height: auto;
        margin: 0 0 1 0;
        background: transparent;
    }

    .turn {
        width: 100%;
        height: auto;
        padding: 0 0 0 2;
    }
    .turn-summary {
        width: 100%;
        height: 1;
        color: $text-muted;
        margin: 0 0 1 0;
    }

    UserMessage {
        background: $boost;
        border-left: thick $primary;
        padding: 0 1;
    }

    AssistantMessage .label {
        color: $primary;
        text-style: bold;
    }
    AssistantMessage .body {
        padding: 0 0 0 2;
        color: $foreground;
    }
    AssistantMessage Markdown {
        height: auto;
        width: 100%;
        margin: 0;
        padding: 0 0 0 2;
        background: transparent;
    }

    ThinkingIndicator {
        padding: 0 0 0 2;
    }

    ToolMessage {
        border: none;
        background: transparent;
    }
    ToolMessage CollapsibleTitle {
        padding: 0 0 0 2;
        background: transparent;
        color: $text-muted;
    }
    ToolMessage CollapsibleTitle:hover {
        background: $boost;
        color: $foreground;
    }
    ToolMessage.done CollapsibleTitle {
        color: $success;
    }
    ToolMessage.failed CollapsibleTitle {
        color: $error;
    }
    ToolMessage Contents {
        padding: 0 0 0 4;
        background: transparent;
    }
    ToolMessage .tool-body {
        color: $text-muted;
    }

    ErrorMessage {
        border-left: thick $error;
        padding: 0 1;
        color: $error;
    }

    NoticeMessage {
        padding: 0 0 0 2;
        color: $text-muted;
    }

    WelcomeMessage {
        align-horizontal: center;
    }
    #logo {
        width: 100%;
        height: auto;
        text-align: center;
        margin: 1 0 0 0;
    }
    #tagline {
        width: 100%;
        height: auto;
        text-align: center;
        color: $text-muted;
        margin: 0 0 1 0;
    }
    #welcome-info-wrap {
        width: 100%;
        height: auto;
        align-horizontal: center;
    }
    #welcome-info {
        width: 64;
        max-width: 100%;
        height: auto;
        padding: 1 2;
        margin: 0 0 1 0;
        border: round $panel;
        background: $surface;
    }
    #welcome-info .row {
        width: 100%;
        height: 1;
    }
    #welcome-info .k {
        width: 8;
        color: $text-muted;
    }
    #welcome-info .v {
        width: 1fr;
        color: $foreground;
    }
    #welcome-tips {
        width: 100%;
        height: auto;
        text-align: center;
        color: $text-muted;
    }

    #completions {
        display: none;
        height: auto;
        max-height: 9;
        margin: 0 2;
        padding: 0;
        border: round $panel;
        background: $surface;
    }
    #completions > .option-list--option {
        padding: 0 1;
    }
    #completions > .option-list--option-highlighted {
        background: $boost;
        color: $primary;
    }

    #input-bar {
        height: auto;
        min-height: 3;
        margin: 0 2;
        padding: 0 1;
        border: round $panel;
        background: $surface;
    }
    #input-bar:focus-within {
        border: round $primary;
    }
    #prompt {
        width: 2;
        height: 1;
        content-align: left top;
        color: $primary;
        text-style: bold;
    }
    #input {
        width: 1fr;
        height: 1;
        padding: 0;
        border: none;
        background: transparent;
        scrollbar-size-vertical: 1;
    }
    #input:focus {
        border: none;
        background: transparent;
    }
    #input .text-area--placeholder {
        color: $text-muted;
    }

    #footer {
        height: 1;
        padding: 0 2;
        margin: 1 0 0 0;
        background: $background;
    }
    #hint {
        width: 1fr;
        color: $text-muted;
    }
    #status {
        width: auto;
        color: $text-muted;
        text-align: right;
    }

    ToolResultScreen {
        align: center middle;
        background: $background 70%;
    }
    #viewer-box {
        width: 92%;
        height: 82%;
        max-width: 140;
        padding: 0 1;
        border: round $primary;
        background: $surface;
    }
    #viewer-title {
        height: 1;
        padding: 0 1;
        background: $surface;
    }
    #viewer-body {
        height: 1fr;
        padding: 1 1;
        background: transparent;
    }
    #viewer-footer {
        height: 1;
        padding: 0 1;
        color: $text-muted;
    }
    """

    BINDINGS = [
        Binding("ctrl+t", "toggle_tool_result", "展开/折叠工具结果", priority=True),
        Binding("ctrl+y", "copy_tool_result", "复制工具结果", priority=True),
        Binding("ctrl+o", "view_tool_result", "查看工具结果", priority=True),
        ("ctrl+b", "toggle_sidebar", "侧栏"),
        ("ctrl+l", "clear", "清空会话"),
        ("ctrl+q", "quit", "退出"),
        ("escape", "cancel_request", "停止回答"),
    ]

    def __init__(self, agent):
        super().__init__()
        self.register_theme(FAGENT_THEME)
        self._presenter = ChatPresenter(agent, self)
        self._answer = None
        self._thinking = None
        self._think_started = None
        self._tool = None
        self._tool_started = None
        self._last_tool_message = None
        self._tool_rows = {}
        self._running_tool = None
        self._sidebar_hidden = False
        self._completion_items = []
        self._completion_visible = False
        self._completion_signature = ()
        self._completion_token_start = 0
        self._completion_kind = None
        self._completion_suppress = False
        self._spinner_timer = None
        self._spinner_frame = 0
        self._welcome = None
        self._turn = None
        self._rounds = 0
        self._started_at = None
        self._elapsed = None
        self._was_cancelled = False
        self._last_prompt = ""
        self._state = "就绪"

    def _tool_groups(self):
        """按来源分组：本地工具一组，每个 MCP Server 一组。

        连接失败、没有注册任何工具的 Server 也会保留在结果里，方便侧栏显示状态。
        """
        local = []
        servers = {}
        for name in self._presenter.agent.tool_names:
            source = tool_source(name)
            server = source.get("server")
            if source.get("kind") == "mcp" and server:
                servers.setdefault(server, []).append(name)
            else:
                local.append(name)
        for server in mcp_status():
            servers.setdefault(server, [])
        return local, servers

    @staticmethod
    def _mcp_group_title(server, info, count):
        """侧栏里的 MCP Server 标题：名称 + 连接状态 + 工具数。"""
        label = Text()
        label.append("MCP · ", style=MUTED)
        label.append(
            server if len(server) <= 14 else server[:13] + "…",
            style=f"bold {TEXT}",
        )
        state = (info or {}).get("state")
        if state == "connected":
            label.append("  ●", style=GREEN)
        elif state == "error":
            label.append("  ✕", style=RED)
        else:
            label.append("  ·", style=MUTED)
        if count:
            label.append(f" {count}", style=MUTED)
        return Static(label, classes="group")

    def compose(self) -> ComposeResult:
        agent = self._presenter.agent
        tools = agent.tool_names

        brand = Text()
        brand.append("◆ ", style=ACCENT)
        brand.append("FAgent", style=f"bold {TEXT}")

        meta = Text()
        meta.append(agent.config.model_name, style=TEXT)
        meta.append(f"  ·  {len(tools)} 个工具", style=MUTED)

        sidebar = [Static("工具", classes="section")]
        local_tools, mcp_servers = self._tool_groups()
        status = mcp_status()
        if local_tools:
            sidebar.append(Static(f"本地 · {len(local_tools)}", classes="group"))
        for name in local_tools:
            row = Static(f"· {name}", classes="tool", id=f"tool-{name}")
            self._tool_rows[name] = row
            sidebar.append(row)
        for server, names in mcp_servers.items():
            sidebar.append(
                self._mcp_group_title(server, status.get(server), len(names))
            )
            for name in names:
                row = Static(f"· {name}", classes="tool", id=f"tool-{name}")
                self._tool_rows[name] = row
                sidebar.append(row)
        sidebar += [
            Static("会话", classes="section"),
            Static(self._session_text(), id="session"),
            Static("快捷键", classes="section"),
            Static(
                "Enter         发送\n"
                "Shift+Enter   换行\n"
                "Tab           补全\n"
                "Esc           停止回答\n"
                "Ctrl+T        展开工具结果\n"
                "Ctrl+Y        复制工具结果\n"
                "Ctrl+O        查看工具结果\n"
                "Ctrl+B        显示/隐藏侧栏\n"
                "Ctrl+L        清空会话\n"
                "Ctrl+Q        退出",
                classes="list",
            ),
        ]

        yield Vertical(
            Horizontal(
                Static(brand, id="brand"),
                Static(meta, id="meta"),
                id="topbar",
            ),
            Horizontal(
                VerticalScroll(id="chat"),
                Vertical(
                    VerticalScroll(*sidebar, id="sidebar-scroll"),
                    id="sidebar",
                ),
                id="main",
            ),
            OptionList(id="completions"),
            Horizontal(
                Static("❯", id="prompt"),
                HistoryTextArea(
                    placeholder="随便问点什么…（Shift+Enter 换行）",
                    id="input",
                ),
                id="input-bar",
            ),
            Horizontal(
                Static(self._hint_text(), id="hint"),
                Static("", id="status"),
                id="footer",
            ),
            id="shell",
        )

    def on_mount(self):
        self.theme = "fagent"
        self._apply_sidebar()
        self._update_status()
        self._presenter.start()
        input_widget = self.query_one("#input", HistoryTextArea)
        input_widget.completion_handler = self._handle_completion_key
        input_widget.focus()
        self.call_after_refresh(self._center_welcome)

    def on_resize(self, event):
        narrow = self.size.width < 74
        try:
            self.query_one("#hint", Static).display = not narrow
            self.query_one("#logo", Static).display = self.size.width >= 66
        except NoMatches:
            pass
        self._apply_sidebar()
        self.call_after_refresh(self._center_welcome)
        try:
            input_widget = self.query_one("#input", HistoryTextArea)
        except NoMatches:
            return
        self.call_after_refresh(input_widget.sync_height)

    def _apply_sidebar(self):
        """窄屏自动收起侧栏，Ctrl+B 可手动切换。"""
        try:
            sidebar = self.query_one("#sidebar")
        except NoMatches:
            return
        sidebar.display = not self._sidebar_hidden and self.size.width >= 100

    def action_toggle_sidebar(self):
        self._sidebar_hidden = not self._sidebar_hidden
        self._apply_sidebar()

    # ---------------------------------------------------------------- 补全

    def on_text_area_changed(self, event):
        if event.text_area.id == "input":
            self._update_completions(event.text_area.text)

    def _handle_completion_key(self, key):
        """输入框按键回调：补全面板可见时消费 Tab / ↑ / ↓。"""
        if not self._completion_visible:
            return False
        try:
            palette = self.query_one("#completions", OptionList)
        except NoMatches:
            return False
        count = palette.option_count
        if not count:
            self._hide_completions()
            return False
        if key == "tab":
            self._apply_completion()
            return True
        if key in ("up", "down"):
            index = palette.highlighted or 0
            offset = -1 if key == "up" else 1
            palette.highlighted = (index + offset) % count
            palette.scroll_to_highlight()
            return True
        return False

    def _update_completions(self, text):
        if self._completion_suppress:
            self._completion_suppress = False
            self._hide_completions()
            return

        context = self._completion_context(text)
        if context is None:
            self._hide_completions()
            return

        kind, entries, token_start = context
        if not entries:
            self._hide_completions()
            return

        try:
            palette = self.query_one("#completions", OptionList)
        except NoMatches:
            return

        signature = (kind, tuple(insert for _, insert in entries))
        if signature != self._completion_signature:
            palette.clear_options()
            palette.add_options([Option(label) for label, _ in entries])
            self._completion_signature = signature
            self._completion_items = [(kind, insert) for _, insert in entries]
            palette.highlighted = 0
            palette.scroll_to_highlight()

        self._completion_kind = kind
        self._completion_token_start = token_start
        palette.display = True
        self._completion_visible = True

    def _hide_completions(self):
        try:
            palette = self.query_one("#completions", OptionList)
        except NoMatches:
            palette = None
        if palette is not None:
            palette.display = False
            palette.clear_options()
        self._completion_visible = False
        self._completion_items = []
        self._completion_signature = ()
        self._completion_kind = None

    def _completion_context(self, text):
        """返回（类型, 候选项, token 起点），没有可补全内容时返回 None。"""
        if not text:
            return None

        # 命令：仅当整段输入是 /xxx 时生效
        if text.startswith("/") and not any(ch.isspace() for ch in text):
            prefix = text[1:].lower()
            entries = [
                (
                    Text.assemble(
                        (command, f"bold {ACCENT}"),
                        "  ",
                        (description, MUTED),
                    ),
                    command,
                )
                for command, description in COMMANDS
                if command[1:].lower().startswith(prefix)
            ]
            return ("command", entries, 0) if entries else None

        # 文件：光标所在 token 以 @ 开头时补全路径
        if text[-1].isspace():
            return None
        token = text.rsplit(None, 1)[-1]
        if not token.startswith("@"):
            return None
        entries = self._file_entries(token[1:])
        if not entries:
            return None
        return ("file", entries, len(text) - len(token))

    def _file_entries(self, fragment):
        raw = fragment.replace("\\", "/")
        directory, base = os.path.split(raw)
        if directory in ("", "."):
            root = Path.cwd()
            prefix = "" if not directory else "./"
        else:
            expanded = os.path.expanduser(directory)
            root = Path(expanded) if os.path.isabs(expanded) else Path.cwd() / expanded
            prefix = directory.rstrip("/") + "/"

        matches = []
        try:
            with os.scandir(root) as entries:
                for count, entry in enumerate(entries):
                    if count >= 3000:
                        break
                    name = entry.name
                    if name.startswith(".") and not base.startswith("."):
                        continue
                    try:
                        is_dir = entry.is_dir()
                    except OSError:
                        is_dir = False
                    if is_dir and name in _SKIP_DIRS:
                        continue
                    if not name.lower().startswith(base.lower()):
                        continue
                    matches.append((not is_dir, name.lower(), name, is_dir))
        except OSError:
            return []

        matches.sort()
        result = []
        for _, _, name, is_dir in matches[:8]:
            insert = f"@{prefix}{name}{'/' if is_dir else ''}"
            label = Text.assemble(
                ("◍ " if is_dir else "· ", MUTED),
                (insert, ACCENT if is_dir else TEXT),
            )
            result.append((label, insert))
        return result

    def _apply_completion(self, index=None):
        if not self._completion_visible or not self._completion_items:
            return
        try:
            palette = self.query_one("#completions", OptionList)
        except NoMatches:
            return
        if index is None:
            index = palette.highlighted or 0
        if not 0 <= index < len(self._completion_items):
            index = 0
        kind, insert = self._completion_items[index]

        input_widget = self.query_one("#input", HistoryTextArea)
        if kind == "command":
            self._completion_suppress = True
            input_widget.text = insert
        else:
            current = input_widget.text
            start = self._completion_token_start
            self._completion_suppress = not insert.endswith("/")
            input_widget.text = current[:start] + insert

        input_widget.cursor_location = input_widget.document.end
        input_widget.focus()
        if self._completion_suppress:
            self._hide_completions()

    def on_option_list_option_selected(self, event):
        self._apply_completion(event.option_index)

    # ---------------------------------------------------------------- 会话信息
    def _session_text(self):
        elapsed = "—" if self._elapsed is None else f"{self._elapsed:.1f}s"
        return f"轮次  {self._rounds}\n耗时  {elapsed}\n状态  {self._state}"

    def _update_session(self):
        try:
            self.query_one("#session", Static).update(self._session_text())
        except NoMatches:
            pass

    def _hint_text(self):
        return (
            "Enter 发送   Shift+Enter 换行   / 命令   @ 文件   Tab 补全   "
            "Ctrl+T 结果   Ctrl+O 查看   Ctrl+Q 退出"
        )

    def _center_welcome(self):
        """把开场页垂直居中，终端高度变化时保持视觉平衡。"""
        if self._welcome is None or not self._welcome.is_mounted:
            return
        chat = self.query_one("#chat", VerticalScroll)
        available = max(1, chat.size.height - 2)
        height = self._welcome.size.height or 16
        # 会话开始后不再留白，避免重新调整窗口时顶部出现大块空区
        top = 1 if self._rounds else max(1, (available - height) // 2)
        self._welcome.styles.margin = (top, 0, 1, 0)

    # ---------------------------------------------------------------- 输入

    def action_cancel_request(self):
        if self._completion_visible:
            self._hide_completions()
            return
        if not self._presenter.busy:
            return
        if self._presenter.cancel():
            self._was_cancelled = True
            self._set_state("正在停止…")

    # ------------------------------------------------------------ 工具结果

    def action_toggle_tool_result(self):
        message = self._last_tool_message
        if message is None or not message.is_mounted:
            self._append(NoticeMessage("暂无工具结果可展开。"))
            return
        message.toggle()
        if not message.collapsed:
            chat = self.query_one("#chat", VerticalScroll)
            self.call_after_refresh(chat.scroll_end, animate=False)

    def action_copy_tool_result(self):
        text = self._latest_tool_text()
        if text is None:
            return
        self.copy_to_clipboard(text)
        self._append(NoticeMessage("已复制工具结果到剪贴板（终端需支持 OSC 52）。"))

    def action_view_tool_result(self):
        text = self._latest_tool_text()
        if text is None:
            return
        name = self._last_tool_message._tool_name
        self.push_screen(ToolResultScreen(name, text))

    def _latest_tool_text(self):
        message = self._last_tool_message
        if message is None or not message.is_mounted:
            self._append(NoticeMessage("暂无工具结果。"))
            return None
        text = message.full_text()
        if not text:
            self._append(NoticeMessage("工具尚未返回结果。"))
            return None
        return text

    def on_history_text_area_submitted(self, event: HistoryTextArea.Submitted):
        input_widget = event.text_area
        text = event.value.strip()
        input_widget.text = ""
        self._hide_completions()

        if not text:
            return
        if text in ("/quit", "/exit"):
            self.exit()
            return
        if text == "/clear":
            self._presenter.clear()
            input_widget.focus()
            return
        if text == "/help":
            self._append(NoticeMessage(self._help_text()))
            return
        if text == "/tools":
            self._append(NoticeMessage(self._tools_text()))
            return
        if text == "/retry":
            if self._last_prompt:
                self._submit(self._last_prompt)
            else:
                self._append(NoticeMessage("暂无可重发的提问。"))
            return
        if text.startswith("/"):
            self._append(NoticeMessage(f"未知命令：{text}，输入 /help 查看可用命令。"))
            return

        self._submit(text)

    def _submit(self, text):
        if self._presenter.busy:
            return
        self._last_prompt = text
        input_widget = self.query_one("#input", HistoryTextArea)
        input_widget.remember(text)
        input_widget.disabled = True
        self.run_worker(
            lambda: self._presenter.submit(text),
            thread=True,
            exclusive=True,
            group="chat",
        )

    def _help_text(self):
        return (
            "命令：/help 帮助 · /tools 工具说明 · /retry 重发上一条 · "
            "/clear 清空会话 · /quit 退出\n"
            "输入 / 弹出命令面板，输入 @ 补全文件路径，Tab 应用候选，↑↓ 选择候选。\n"
            "快捷键：Enter 发送 · Shift+Enter 换行（Ctrl+J 同样可用）· "
            "Esc 停止回答 · Ctrl+T 展开/折叠工具结果 · Ctrl+Y 复制工具结果 · "
            "Ctrl+O 全屏查看工具结果 · Ctrl+B 侧栏 · Ctrl+L 清空 · Ctrl+Q 退出\n"
            "支持直接粘贴多行文本，输入框会随内容自动增高。"
        )

    def _tools_text(self):
        content = Text()
        local, servers = self._tool_groups()
        status = mcp_status()
        specs = {
            tool["function"]["name"]: tool["function"]
            for tool in self._presenter.agent.tools
        }

        def add_tool(name):
            function = specs.get(name)
            if function is None:
                return
            content.append(f"  {name}", style=f"bold {TEXT}")
            content.append(f"  {function.get('description', '')}\n", style=MUTED)

        content.append(f"本地工具（{len(local)}）\n", style=ACCENT)
        for name in local:
            add_tool(name)
        for server, names in servers.items():
            info = status.get(server) or {}
            content.append(f"\nMCP · {server}", style=f"bold {TEXT}")
            if info.get("state") == "connected":
                content.append(
                    f"  ● 已连接 · {info.get('tool_count', len(names))} 个工具\n",
                    style=GREEN,
                )
            elif info.get("state") == "error":
                content.append("  ✕ 未连接\n", style=RED)
                content.append(f"    {info.get('detail', '')}\n", style=MUTED)
            else:
                content.append(f"  · {len(names)} 个工具\n", style=MUTED)
            for name in names:
                add_tool(name)
        return content

    def action_clear(self):
        self._presenter.clear()
        self.query_one("#input", HistoryTextArea).focus()

    # ---------------------------------------------------------------- 渲染

    def _ui(self, callback, *args):
        """确保控件更新发生在 UI 线程"""
        if threading.current_thread() is threading.main_thread():
            callback(*args)
        else:
            self.call_from_thread(callback, *args)

    def _append(self, widget, in_turn=False):
        """挂载消息控件；in_turn=True 时挂到当前轮次容器，保持过程层级。"""
        chat = self.query_one("#chat", VerticalScroll)
        if in_turn and self._turn is not None:
            self._turn.attach(widget)
        else:
            chat.mount(widget)
        self.call_after_refresh(chat.scroll_end, animate=False)

    def _finish_turn(self):
        """在当前轮次末尾补一行摘要，并结束该轮。"""
        turn = self._turn
        self._turn = None
        if turn is None:
            return
        turn.attach(Static(Text(turn.summary(), style=MUTED), classes="turn-summary"))
        chat = self.query_one("#chat", VerticalScroll)
        self.call_after_refresh(chat.scroll_end, animate=False)

    def _set_state(self, text):
        self._state = text
        self._update_status()

    def _update_status(self):
        parts = [self._presenter.agent.config.model_name, f"{self._rounds} 轮"]
        if self._elapsed is not None:
            parts.append(f"{self._elapsed:.1f}s")
        parts.append(self._state)
        self.query_one("#status", Static).update(" · ".join(parts))
        self._update_session()

    # ---------------------------------------------------------------- 事件

    def show_welcome(self, tool_names):
        def apply():
            model = self._presenter.agent.config.model_name
            self._welcome = WelcomeMessage(tool_names, model)
            self._welcome.add_class("message")
            self._append(self._welcome)
            self.call_after_refresh(self._center_welcome)

        self._ui(apply)

    def show_user_message(self, text):
        def apply():
            self._rounds += 1
            self._started_at = time.monotonic()
            self._elapsed = None
            self._update_status()
            widget = UserMessage(text)
            widget.add_class("message")
            self._append(widget)
            self._turn = TurnBlock()
            self._turn.add_class("turn")
            self._append(self._turn)

        self._ui(apply)

    def show_tool_start(self, name, args):
        def apply():
            # 工具执行前先收尾当前回答，后续文本会另起消息块，
            # 保证「回答 -> 工具 -> 回答」的时序不会错乱
            self._finish_answer()
            self._drop_thinking()
            self._tool_started = time.monotonic()
            widget = ToolMessage(name, args)
            widget.add_class("message")
            self._tool = widget
            self._last_tool_message = widget
            self._append(widget, in_turn=True)
            if self._turn is not None:
                self._turn.tool_count += 1
            self._set_sidebar_running(name)
            self._set_state(f"执行 {name}…")
            self._start_spinner()

        self._ui(apply)

    def show_tool_result(self, name, args, result):
        def apply():
            seconds = (
                time.monotonic() - self._tool_started
                if self._tool_started is not None
                else 0.0
            )
            self._tool_started = None
            widget = self._tool
            self._tool = None
            self._set_sidebar_running(None)
            if widget is not None:
                widget.finish(result, seconds)
                if str(result).lstrip().startswith("Error") and self._turn is not None:
                    self._turn.failed_count += 1
                if not widget.collapsed:
                    chat = self.query_one("#chat", VerticalScroll)
                    self.call_after_refresh(chat.scroll_end, animate=False)
            else:
                if str(result).lstrip().startswith("Error") and self._turn is not None:
                    self._turn.failed_count += 1
                fallback = ToolMessage(name, args)
                fallback.add_class("message")
                fallback.finish(result, seconds)
                self._last_tool_message = fallback
                self._append(fallback, in_turn=True)
            # 工具结果回传后模型还会继续推理，重新显示思考提示
            self._show_thinking()
            self._set_state("思考中…")

        self._ui(apply)

    def begin_answer(self):
        def apply():
            self._answer = None
            self._was_cancelled = False
            self._show_thinking()

        self._ui(apply)

    def show_token(self, text):
        def apply():
            if self._was_cancelled:
                return
            self._drop_thinking()
            if self._answer is None:
                self._answer = AssistantMessage()
                self._answer.add_class("message")
                self._append(self._answer, in_turn=True)
            self._answer.append(text)
            self.query_one("#chat", VerticalScroll).scroll_end(animate=False)

        self._ui(apply)

    def end_answer(self):
        self._ui(self._end_answer)

    def _end_answer(self):
        self._finish_answer()
        self._drop_thinking()
        if self._was_cancelled:
            self._append(NoticeMessage("已停止生成。"), in_turn=True)

    def _finish_answer(self):
        if self._answer is not None:
            self._answer.finish()
            self._answer = None

    def show_error(self, text):
        def apply():
            self._drop_thinking()
            widget = ErrorMessage(text)
            widget.add_class("message")
            self._append(widget, in_turn=True)

        self._ui(apply)

    def set_busy(self, busy):
        def apply():
            input_widget = self.query_one("#input", HistoryTextArea)
            input_widget.disabled = busy
            if busy:
                self._hide_completions()
                self._set_state("思考中…")
                return

            self._drop_thinking()
            self._finish_answer()
            self._tool = None
            self._tool_started = None
            self._set_sidebar_running(None)
            if self._started_at is not None:
                self._elapsed = time.monotonic() - self._started_at
                self._started_at = None
            self._finish_turn()
            self._set_state("就绪")
            input_widget.focus()

        self._ui(apply)

    def clear(self):
        def apply():
            self._drop_thinking()
            self._answer = None
            self._tool = None
            self._last_tool_message = None
            self._turn = None
            self._hide_completions()
            self._set_sidebar_running(None)
            self.query_one("#chat", VerticalScroll).remove_children()
            self._rounds = 0
            self._elapsed = None
            self._started_at = None
            self._welcome = WelcomeMessage(
                self._presenter.agent.tool_names,
                self._presenter.agent.config.model_name,
            )
            self._welcome.add_class("message")
            self._append(self._welcome)
            self._set_state("新会话")
            self.call_after_refresh(self._center_welcome)

        self._ui(apply)

    # ------------------------------------------------------------ 思考/工具

    def _show_thinking(self):
        self._drop_thinking()
        self._thinking = ThinkingIndicator()
        self._thinking.add_class("message")
        self._thinking.tick(_SPINNER_FRAMES[0], 0.0)
        self._think_started = time.monotonic()
        self._append(self._thinking, in_turn=True)
        self._start_spinner()

    def _drop_thinking(self):
        if self._thinking is not None:
            if self._turn is not None:
                self._turn.detach(self._thinking)
            elif self._thinking.is_mounted:
                self._thinking.remove()
            self._thinking = None
        self._think_started = None
        self._stop_spinner_if_idle()

    def _set_sidebar_running(self, name):
        """在侧栏高亮正在执行的工具，None 表示结束。"""
        if self._running_tool and self._running_tool != name:
            self._reset_tool_row(self._running_tool)
        self._running_tool = name
        row = self._tool_rows.get(name) if name else None
        if row is not None:
            row.add_class("running")

    def _reset_tool_row(self, name):
        row = self._tool_rows.get(name)
        if row is not None:
            row.remove_class("running")
            row.update(f"· {name}")

    def _start_spinner(self):
        if self._spinner_timer is None:
            self._spinner_frame = 0
            self._spinner_timer = self.set_interval(0.1, self._tick_spinner)

    def _stop_spinner_if_idle(self):
        if self._thinking is None and self._tool is None:
            if self._spinner_timer is not None:
                self._spinner_timer.stop()
                self._spinner_timer = None

    def _tick_spinner(self):
        if self._thinking is None and self._tool is None:
            self._stop_spinner_if_idle()
            return
        self._spinner_frame += 1
        frame = _SPINNER_FRAMES[self._spinner_frame % len(_SPINNER_FRAMES)]
        if self._thinking is not None:
            elapsed = (
                time.monotonic() - self._think_started
                if self._think_started is not None
                else 0.0
            )
            self._thinking.tick(frame, elapsed)
        if self._tool is not None:
            self._tool.tick(frame)
        if self._running_tool:
            row = self._tool_rows.get(self._running_tool)
            if row is not None:
                row.update(f"{frame} {self._running_tool}")
