"""命令行界面：实现 ChatView 契约，输入输出只在本模块内处理。"""

from .base import ChatPresenter, ChatView


class ConsoleUI(ChatView):
    def __init__(self, agent, input_func=input, output_func=print):
        self._input = input_func
        self._output = output_func
        self._presenter = ChatPresenter(agent, self)

    def run(self):
        self._presenter.start()
        while True:
            try:
                self._output("")
                text = self._input("我：")
            except (EOFError, KeyboardInterrupt):
                break

            command = text.strip().lower()
            if command in ("/quit", "/exit"):
                break
            if command == "/clear":
                self._presenter.clear()
                continue

            self._output("---")
            self._presenter.submit(text)

    def show_welcome(self, tool_names):
        self._output(
            f"你好，有什么问题（支持 function call: {', '.join(tool_names)}）"
        )

    def show_user_message(self, text):
        pass

    def show_tool_result(self, name, args, result):
        self._output(result)

    def show_answer(self, text):
        self._output(text)

    def show_error(self, text):
        self._output(f"错误：{text}")

    def set_busy(self, busy):
        pass

    def clear(self):
        self._output("已清空会话历史")
