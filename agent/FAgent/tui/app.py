"""Textual TUI 界面：只负责渲染与交互，聊天流程委托给 ChatPresenter。"""

import threading

from rich.text import Text
from textual.app import App, ComposeResult
from textual.widgets import Footer, Header, Input, RichLog, Static

from .base import ChatPresenter, ChatView


class FAgentApp(App, ChatView):
    TITLE = "FAgent"
    SUB_TITLE = "Function Call TUI"

    CSS = """
    Screen {
        layout: vertical;
    }
    #log {
        height: 1fr;
        border: round $accent;
        padding: 0 1;
    }
    #status {
        height: 1;
        padding: 0 1;
        color: $text-muted;
    }
    #input {
        dock: bottom;
    }
    """

    BINDINGS = [
        ("ctrl+l", "clear", "清空会话"),
        ("ctrl+q", "quit", "退出"),
    ]

    def __init__(self, agent):
        super().__init__()
        self._presenter = ChatPresenter(agent, self)

    def compose(self) -> ComposeResult:
        yield Header()
        yield RichLog(id="log", wrap=True, markup=False, highlight=False)
        yield Static("就绪", id="status")
        yield Input(
            placeholder="输入问题后回车发送；/clear 清空会话；/quit 退出",
            id="input",
        )
        yield Footer()

    def on_mount(self):
        self._presenter.start()
        self.query_one("#input", Input).focus()

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
        if self._presenter.busy:
            return

        event.input.disabled = True
        self.run_worker(
            lambda: self._presenter.submit(text),
            thread=True,
            exclusive=True,
            group="chat",
        )

    def action_clear(self):
        self._presenter.clear()
        self.query_one("#input", Input).focus()

    def _ui(self, callback, *args):
        """确保控件更新发生在 UI 线程"""
        if threading.current_thread() is threading.main_thread():
            callback(*args)
        else:
            self.call_from_thread(callback, *args)

    def _write(self, renderable):
        self.query_one("#log", RichLog).write(renderable)

    def show_welcome(self, tool_names):
        line = Text()
        line.append("FAgent 已就绪\n", style="bold")
        line.append("可用工具：", style="bold")
        line.append(", ".join(tool_names), style="dim")
        self._ui(self._write, line)

    def show_user_message(self, text):
        line = Text()
        line.append("我：", style="bold cyan")
        line.append(text)
        self._ui(self._write, line)

    def show_tool_result(self, name, args, result):
        line = Text()
        line.append(f"工具 {name}", style="bold yellow")
        if args is not None:
            line.append(f" {args}", style="dim")
        line.append("\n")
        line.append(result)
        self._ui(self._write, line)

    def show_answer(self, text):
        line = Text()
        line.append("\n助手：", style="bold green")
        line.append(text)
        self._ui(self._write, line)

    def show_error(self, text):
        self._ui(self._write, Text(text, style="bold red"))

    def set_busy(self, busy):
        def apply():
            input_widget = self.query_one("#input", Input)
            input_widget.disabled = busy
            self.query_one("#status", Static).update("思考中…" if busy else "就绪")
            if not busy:
                input_widget.focus()

        self._ui(apply)

    def clear(self):
        def apply():
            self.query_one("#log", RichLog).clear()
            self.query_one("#status", Static).update("已清空会话历史")

        self._ui(apply)
