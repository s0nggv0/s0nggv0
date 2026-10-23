"""Textual TUI 界面：只负责渲染与交互，聊天流程委托给 ChatPresenter。"""

import os
import threading
import time

from rich.text import Text
from textual.app import App, ComposeResult
from textual.containers import Horizontal, Vertical, VerticalScroll
from textual.css.query import NoMatches
from textual.theme import Theme
from textual.widgets import Collapsible, Input, Markdown, Static

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
        self._body = Static(Text("等待工具返回…", style=MUTED), classes="tool-body")
        super().__init__(self._body, title=f"⠋ {name}", collapsed=True)

    def tick(self, frame):
        self.title = f"{frame} {self._tool_name}{self._summary()}"

    def finish(self, result, seconds):
        result = str(result)
        failed = result.lstrip().startswith("Error")
        mark = "✗" if failed else "✓"
        self.title = f"{mark} {self._tool_name}{self._summary()} · {seconds:.2f}s"
        self.add_class("failed" if failed else "done")
        self._body.update(self._detail(result))
        self.collapsed = result.count("\n") > 8 or len(result) > 600

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


class HistoryInput(Input):
    """支持 ↑/↓ 回溯历史提问的单行输入框。"""

    def __init__(self, **kwargs):
        super().__init__(**kwargs)
        self._history = []
        self._index = None
        self._draft = ""

    def remember(self, text):
        """记录一条已提交的输入（相邻重复不重复记录）"""
        if self._history and self._history[-1] == text:
            self._index = None
            return
        self._history.append(text)
        self._index = None

    def on_key(self, event):
        if event.key not in ("up", "down") or not self._history:
            return
        event.prevent_default()
        event.stop()

        if event.key == "up":
            if self._index is None:
                self._draft = self.value
                self._index = len(self._history) - 1
            elif self._index > 0:
                self._index -= 1
            self._set_value(self._history[self._index])
        elif self._index is None:
            return
        elif self._index < len(self._history) - 1:
            self._index += 1
            self._set_value(self._history[self._index])
        else:
            self._index = None
            self._set_value(self._draft)

    def _set_value(self, text):
        self.value = text
        self.cursor_position = len(text)


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
    #sidebar .tool {
        width: 100%;
        height: 1;
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

    #input-bar {
        height: 3;
        margin: 0 2;
        padding: 0 1;
        border: round $panel;
        background: $surface;
    }
    #input-bar.focused {
        border: round $primary;
    }
    #prompt {
        width: 2;
        height: 1;
        content-align: left middle;
        color: $primary;
        text-style: bold;
    }
    #input {
        width: 1fr;
        height: 1;
        padding: 0;
        border: none;
        background: transparent;
    }
    #input:focus {
        border: none;
        background: transparent;
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
    """

    BINDINGS = [
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
        self._tool_rows = {}
        self._running_tool = None
        self._sidebar_hidden = False
        self._spinner_timer = None
        self._spinner_frame = 0
        self._welcome = None
        self._rounds = 0
        self._started_at = None
        self._elapsed = None
        self._was_cancelled = False
        self._last_prompt = ""
        self._state = "就绪"

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
        for name in tools:
            row = Static(f"· {name}", classes="tool", id=f"tool-{name}")
            self._tool_rows[name] = row
            sidebar.append(row)
        sidebar += [
            Static("会话", classes="section"),
            Static(self._session_text(), id="session"),
            Static("快捷键", classes="section"),
            Static(
                "Enter   发送\n"
                "Esc     停止回答\n"
                "Ctrl+B  显示/隐藏侧栏\n"
                "Ctrl+L  清空会话\n"
                "Ctrl+Q  退出",
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
            Horizontal(
                Static("❯", id="prompt"),
                HistoryInput(
                    placeholder="随便问点什么…",
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
        input_widget = self.query_one("#input", HistoryInput)
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

    def _session_text(self):
        elapsed = "—" if self._elapsed is None else f"{self._elapsed:.1f}s"
        return f"轮次  {self._rounds}\n耗时  {elapsed}\n状态  {self._state}"

    def _update_session(self):
        try:
            self.query_one("#session", Static).update(self._session_text())
        except NoMatches:
            pass

    def _hint_text(self):
        return "Enter 发送   ↑↓ 历史   Esc 停止   / 命令   Ctrl+L 清空   Ctrl+Q 退出"

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

    def on_input_focus(self):
        self.query_one("#input-bar").add_class("focused")

    def on_input_blur(self):
        self.query_one("#input-bar").remove_class("focused")

    def action_cancel_request(self):
        if not self._presenter.busy:
            return
        if self._presenter.cancel():
            self._was_cancelled = True
            self._set_state("正在停止…")

    def on_input_submitted(self, event: Input.Submitted):
        text = event.value.strip()
        event.input.value = ""

        if not text:
            return
        if text in ("/quit", "/exit"):
            self.exit()
            return
        if text == "/clear":
            self._presenter.clear()
            event.input.focus()
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
        input_widget = self.query_one("#input", HistoryInput)
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
            "快捷键：Enter 发送 · ↑↓ 历史 · Esc 停止回答 · "
            "Ctrl+L 清空 · Ctrl+Q 退出"
        )

    def _tools_text(self):
        content = Text()
        for tool in self._presenter.agent.tools:
            function = tool["function"]
            content.append(f"{function['name']}", style=f"bold {TEXT}")
            content.append(f"  {function.get('description', '')}\n", style=MUTED)
        return content

    def action_clear(self):
        self._presenter.clear()
        self.query_one("#input", HistoryInput).focus()

    # ---------------------------------------------------------------- 渲染

    def _ui(self, callback, *args):
        """确保控件更新发生在 UI 线程"""
        if threading.current_thread() is threading.main_thread():
            callback(*args)
        else:
            self.call_from_thread(callback, *args)

    def _append(self, widget):
        container = self.query_one("#chat", VerticalScroll)
        container.mount(widget)
        self.call_after_refresh(container.scroll_end, animate=False)

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
            self._append(widget)
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
                if not widget.collapsed:
                    chat = self.query_one("#chat", VerticalScroll)
                    self.call_after_refresh(chat.scroll_end, animate=False)
            else:
                fallback = ToolMessage(name, args)
                fallback.add_class("message")
                fallback.finish(result, seconds)
                self._append(fallback)
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
                self._append(self._answer)
            self._answer.append(text)
            self.query_one("#chat", VerticalScroll).scroll_end(animate=False)

        self._ui(apply)

    def end_answer(self):
        self._ui(self._end_answer)

    def _end_answer(self):
        self._finish_answer()
        self._drop_thinking()
        if self._was_cancelled:
            self._append(NoticeMessage("已停止生成。"))

    def _finish_answer(self):
        if self._answer is not None:
            self._answer.finish()
            self._answer = None

    def show_error(self, text):
        def apply():
            self._drop_thinking()
            widget = ErrorMessage(text)
            widget.add_class("message")
            self._append(widget)

        self._ui(apply)

    def set_busy(self, busy):
        def apply():
            input_widget = self.query_one("#input", HistoryInput)
            input_widget.disabled = busy
            if busy:
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
            self._set_state("就绪")
            input_widget.focus()

        self._ui(apply)

    def clear(self):
        def apply():
            self._drop_thinking()
            self._answer = None
            self._tool = None
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
        self._append(self._thinking)
        self._start_spinner()

    def _drop_thinking(self):
        if self._thinking is not None:
            if self._thinking.is_mounted:
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
