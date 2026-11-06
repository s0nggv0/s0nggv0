"""命令行界面：实现 ChatView 契约，输入输出只在本模块内处理。"""

from core.session import is_agents_message

from .base import ChatPresenter, ChatView


class ConsoleUI(ChatView):
    def __init__(self, agent, input_func=input, output_func=print):
        self._input = input_func
        self._output = output_func
        self._presenter = ChatPresenter(agent, self)
        self._buffer = []

    def run(self):
        self._presenter.start()
        while True:
            try:
                self._output("")
                text = self._input("我：")
            except (EOFError, KeyboardInterrupt):
                break

            command = text.strip()
            lowered = command.lower()
            if lowered in ("/quit", "/exit"):
                self._presenter.auto_save()
                break
            if lowered == "/clear":
                self._presenter.clear()
                continue
            if lowered == "/compact":
                self._presenter.compact()
                continue
            if lowered == "/save":
                self._presenter.save()
                continue
            if lowered == "/new":
                self._presenter.new_session()
                continue
            if lowered in ("/sessions", "/resume"):
                self._list_sessions()
                continue
            if lowered.startswith("/resume "):
                session_id = command.split(None, 1)[1].strip()
                self._presenter.resume(session_id)
                continue
            if lowered in ("/help", "/tools"):
                self._output("/compact 压缩上下文 · /new 新建会话 · /save 保存会话"
                             " · /resume 恢复会话 · /quit 退出")
                continue
            if lowered.startswith("/"):
                self._output(f"未知命令：{command}")
                continue

            self._output("---")
            self._presenter.submit(text)

    def _list_sessions(self):
        sessions = self._presenter.list_sessions()
        if not sessions:
            self._output("暂无历史会话。")
            return
        self._output("历史会话（使用 /resume <编号> 恢复）：")
        for info in sessions:
            self._output(
                f"  {info.id}  {info.title}  {info.message_count} 条  "
                f"{info.updated_at}"
            )

    def show_welcome(self, tool_names):
        self._output(
            f"你好，有什么问题（支持 function call: {', '.join(tool_names)}）"
        )

    def show_user_message(self, text):
        pass

    def show_tool_start(self, name, args):
        self._output(f"调用工具 {name}…")

    def show_tool_result(self, name, args, result):
        self._output(result)

    def begin_answer(self):
        self._buffer = []

    def show_token(self, text):
        self._buffer.append(text)

    def end_answer(self):
        text = "".join(self._buffer)
        if text:
            self._output(text)

    def show_error(self, text):
        self._output(f"错误：{text}")

    def show_notice(self, text):
        self._output(text)

    def show_warning(self, text):
        self._output(f"警告：{text}")

    def update_context(self, stats):
        window = stats["window"] / 1000
        mark = "" if not stats["is_default"] else "（默认）"
        self._output(
            f"上下文 {stats['tokens'] / 1000:.1f}k / {window:.0f}k{mark}"
            f"  已占用 {stats['ratio'] * 100:.0f}%"
        )

    def show_compaction_start(self):
        self._output("正在压缩上下文…")

    def show_compaction_result(self, before_text, after_text):
        self._output("压缩完成，压缩后的摘要：")
        self._output(after_text)

    def show_history(self, messages):
        self._output("--- 恢复会话 ---")
        for message in messages:
            role = message.get("role")
            content = message.get("content") or ""
            if is_agents_message(message):
                continue
            if role == "user":
                self._output(f"我：{content}")
            elif role == "assistant" and content:
                self._output(f"FAgent：{content}")
            elif role == "tool":
                self._output(f"[工具结果] {str(content)[:500]}")
        self._output("--- 会话已恢复 ---")

    def set_busy(self, busy):
        pass

    def clear(self):
        self._output("已清空会话历史")
