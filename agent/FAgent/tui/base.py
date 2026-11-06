"""界面契约与共享展示逻辑。

ChatView 是任何界面（TUI / Console / 未来的 Web、Desktop）都需要实现的契约；
ChatPresenter 负责调用 core.Agent，并把结果翻译成 ChatView 调用。

新增界面版本时：
1. 实现一个 ChatView（把事件渲染到对应控件 / WebSocket / 窗口）；
2. 在 tui/factory.py 的 _BACKENDS 中登记入口类；
3. 无需修改 core 与 ChatPresenter。
"""

import threading


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

    def show_tool_start(self, name, args):
        """工具开始执行（展示执行状态）"""
        raise NotImplementedError

    def show_tool_result(self, name, args, result):
        """展示一次工具调用及其结果"""
        raise NotImplementedError

    def begin_answer(self):
        """准备接收一条助手回答（流式输出开始）"""
        raise NotImplementedError

    def show_token(self, text):
        """收到一段回答增量文本"""
        raise NotImplementedError

    def end_answer(self):
        """回答输出结束（用于收尾渲染）"""
        raise NotImplementedError

    def show_error(self, text):
        """展示错误信息"""
        raise NotImplementedError

    def show_notice(self, text):
        """展示中性提示信息"""
        raise NotImplementedError

    def show_warning(self, text):
        """展示需要用户注意的警告"""
        raise NotImplementedError

    def update_context(self, stats):
        """更新上下文用量展示（tokens / window / ratio / is_default）"""
        raise NotImplementedError

    def show_compaction_start(self):
        """上下文压缩开始"""
        raise NotImplementedError

    def show_compaction_result(self, before_text, after_text):
        """展示压缩前后的对照内容"""
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
        self._cancel_event = threading.Event()

    @property
    def busy(self):
        return self._busy

    def cancel(self):
        """请求中止当前回答，返回是否确实有请求在进行"""
        if not self._busy:
            return False
        self._cancel_event.set()
        return True

    def start(self):
        self.view.show_welcome(self.agent.tool_names)
        self._notify_context()
        if self.agent.needs_compact():
            self.view.show_warning(
                "上下文占用已达 70%，请执行 /compact 压缩上下文后再开始提问。"
            )

    def _notify_context(self):
        """把最新的上下文用量同步给界面。"""
        self.view.update_context(self.agent.context_stats())

    def submit(self, text):
        """处理一条用户输入，阻塞直到得到最终回答。

        图形界面应把本方法放到后台线程 / 任务中执行，避免阻塞事件循环。
        上下文占用达到阈值后，普通提问会被暂停，直到 /compact 成功完成。
        """
        text = (text or "").strip()
        if not text or self._busy:
            return
        if self.agent.needs_compact():
            self.view.show_warning(
                "上下文占用已达 70%，请先执行 /compact 压缩上下文后再继续提问。"
            )
            self._notify_context()
            return

        self._busy = True
        self._cancel_event.clear()
        self.view.set_busy(True)
        try:
            self.view.show_user_message(text)
            self.view.begin_answer()
            try:
                self.agent.send(
                    text,
                    on_token=self.view.show_token,
                    on_tool_start=self.view.show_tool_start,
                    on_tool_result=self.view.show_tool_result,
                    is_cancelled=self._cancel_event.is_set,
                )
            finally:
                self.view.end_answer()
        except Exception as e:
            self.view.show_error(f"请求失败：{e}")
        finally:
            self._busy = False
            self.view.set_busy(False)
            self._notify_context()
            if self.agent.needs_compact() and not self._cancel_event.is_set():
                self.view.show_warning(
                    "上下文占用已达 70%，请执行 /compact 压缩上下文；"
                    "压缩成功前将暂停接受新的提问。"
                )

    def compact(self):
        """执行上下文压缩：归档原文、调用 LLM 生成摘要并替换历史。

        压缩期间禁止普通任务与工具调用；失败时保留原有上下文，可重新执行 /compact。
        """
        if self._busy:
            return

        self._busy = True
        self._cancel_event.clear()
        self.view.set_busy(True)
        self.view.show_compaction_start()
        try:
            result = self.agent.compact()
        except Exception as e:
            self.view.show_error(f"上下文压缩失败：{e}")
        else:
            after_text = result["summary"] + "\n\n" + result["note"]
            self.view.show_compaction_result(result["before_text"], after_text)
            self.view.show_notice(
                f"上下文压缩完成，原始上下文已归档到 {result['archive_id']}。"
            )
        finally:
            self._busy = False
            self.view.set_busy(False)
            self._notify_context()
            if self.agent.needs_compact():
                self.view.show_warning(
                    "上下文占用仍超过 70%，请检查错误后重新执行 /compact。"
                )

    def clear(self):
        if self._busy:
            return
        self.agent.reset()
        self.view.clear()
        self._notify_context()
