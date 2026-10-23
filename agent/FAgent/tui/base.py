"""界面契约与共享展示逻辑。

ChatView 是任何界面（TUI / Console / 未来的 Web、Desktop）都需要实现的契约；
ChatPresenter 负责调用 core.Agent，并把结果翻译成 ChatView 调用。

新增界面版本时：
1. 实现一个 ChatView（把事件渲染到对应控件 / WebSocket / 窗口）；
2. 在 tui/factory.py 的 _BACKENDS 中登记入口类；
3. 无需修改 core 与 ChatPresenter。
"""


class ChatView:
    """界面渲染契约，所有方法都可能在后台线程中被调用。

    刻意不使用 ABCMeta，避免与 Textual App 等自带元类的框架冲突。
    """

    def show_welcome(self, tool_names):
        """展示欢迎语与可用工具列表"""
        raise NotImplementedError

    def show_user_message(self, text):
        """展示用户消息"""
        raise NotImplementedError

    def show_tool_result(self, name, args, result):
        """展示一次工具调用及其结果"""
        raise NotImplementedError

    def show_answer(self, text):
        """展示模型最终回答"""
        raise NotImplementedError

    def show_error(self, text):
        """展示错误信息"""
        raise NotImplementedError

    def set_busy(self, busy):
        """切换忙碌状态（禁用输入、显示进度提示等）"""
        raise NotImplementedError

    def clear(self):
        """清空当前会话的界面内容"""
        raise NotImplementedError


class ChatPresenter:
    """会话控制器：把用户输入交给 Agent，并把过程中的事件转给 ChatView"""

    def __init__(self, agent, view):
        self.agent = agent
        self.view = view
        self._busy = False

    @property
    def busy(self):
        return self._busy

    def start(self):
        self.view.show_welcome(self.agent.tool_names)

    def submit(self, text):
        """处理一条用户输入，阻塞直到得到最终回答。

        图形界面应把本方法放到后台线程 / 任务中执行，避免阻塞事件循环。
        """
        text = (text or "").strip()
        if not text or self._busy:
            return

        self._busy = True
        self.view.set_busy(True)
        try:
            self.view.show_user_message(text)
            reply = self.agent.send(text, on_tool_result=self.view.show_tool_result)
            self.view.show_answer(reply)
        except Exception as e:
            self.view.show_error(f"请求失败：{e}")
        finally:
            self._busy = False
            self.view.set_busy(False)

    def clear(self):
        if self._busy:
            return
        self.agent.reset()
        self.view.clear()
