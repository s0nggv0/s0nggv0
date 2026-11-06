"""配置提示对话框：首次运行自动生成 config.ini 后展示，阻止在配置完成前进入主界面。"""

from textual.app import App, ComposeResult
from textual.binding import Binding
from textual.containers import Vertical
from textual.widgets import Button, Static


class ConfigNoticeApp(App):
    """一个只显示配置提醒、等待用户确认退出的最小界面。"""

    CSS = """
    Screen {
        align: center middle;
        background: #131211;
        color: #e8e3dc;
    }
    #notice-box {
        width: 84%;
        max-width: 96;
        height: auto;
        padding: 1 2;
        border: round #fab283;
        background: #1b1917;
    }
    #notice-title {
        width: 100%;
        padding-bottom: 1;
        color: #fab283;
        text-style: bold;
    }
    #notice-body {
        width: 100%;
        height: auto;
        color: #e8e3dc;
    }
    #notice-hint {
        width: 100%;
        height: auto;
        padding-top: 1;
        color: #e8e3dc;
    }
    #notice-path {
        width: 100%;
        height: auto;
        padding: 1 0;
        color: #8d8379;
    }
    #notice-actions {
        width: 100%;
        height: 3;
        align-horizontal: right;
        padding-top: 1;
    }
    """

    BINDINGS = [Binding("escape", "close", "退出")]

    def __init__(self, path, created=True):
        super().__init__()
        self._path = str(path)
        self._created = created

    def compose(self) -> ComposeResult:
        if self._created:
            reason = "当前目录没有 config.ini，已自动生成一份完整模板（含 mock 占位信息）。"
        else:
            reason = "config.ini 仍在使用 mock 占位信息，无法连接模型服务。"
        yield Vertical(
            Static("需要先完成配置", id="notice-title"),
            Static(reason, id="notice-body"),
            Static(self._path, id="notice-path"),
            Static(
                "请修改 base_url、model_name、key（以及其他需要的参数）后重新启动 FAgent。",
                id="notice-hint",
            ),
            Vertical(
                Button("退出程序", id="notice-close", variant="primary"),
                id="notice-actions",
            ),
            id="notice-box",
        )

    def on_mount(self):
        self.query_one("#notice-close", Button).focus()

    def on_button_pressed(self, event):
        if event.button.id == "notice-close":
            self.exit()

    def action_close(self):
        self.exit()


def show_config_notice(path, created=True):
    """在当前终端弹出配置提示框，用户确认后退出。"""
    ConfigNoticeApp(path, created).run()
