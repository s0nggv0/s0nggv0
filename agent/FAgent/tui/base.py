"""界面契约与共享展示逻辑。

ChatView 是任何界面（TUI / Console / 未来的 Web、Desktop）都需要实现的契约；
ChatPresenter 负责调用 core.Agent，并把结果翻译成 ChatView 调用，同时管理会话持久化。

新增界面版本时：
1. 实现一个 ChatView（把事件渲染到对应控件 / WebSocket / 窗口）；
2. 在 tui/factory.py 的 _BACKENDS 中登记入口类；
3. 无需修改 core 与 ChatPresenter。
"""

import threading

from core.session import SessionStore


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

    def show_history(self, messages):
        """把一条已保存的会话历史重新渲染到界面（恢复会话时调用）"""
        raise NotImplementedError

    def set_busy(self, busy):
        """切换忙碌状态（禁用输入、显示进度提示等）"""
        raise NotImplementedError

    def clear(self):
        """清空当前会话的界面内容"""
        raise NotImplementedError


class ChatPresenter:
    """会话控制器：把用户输入交给 Agent，把过程事件转给 ChatView，并负责会话存档。"""

    def __init__(self, agent, view, session_store=None):
        self.agent = agent
        self.view = view
        self._busy = False
        self._cancel_event = threading.Event()
        self._store = session_store or SessionStore()
        self._session_id = None
        self._session_created = None

    @property
    def busy(self):
        return self._busy

    @property
    def session_id(self):
        return self._session_id

    def cancel(self):
        """请求中止当前回答，返回是否确实有请求在进行"""
        if not self._busy:
            return False
        self._cancel_event.set()
        return True

    # ---------------------------------------------------------------- 会话

    def start(self):
        """启动会话：生成会话编号、注入 AGENTS.md，然后通知界面。"""
        details = self._begin_session()
        self.view.show_welcome(self.agent.tool_names)
        self._notify_context()
        if self.agent.needs_compact():
            self.view.show_warning(
                "上下文占用已达告警阈值，请执行 /compact 压缩上下文后再开始提问。"
            )
        if details:
            self.view.show_notice(
                f"已加载项目规范 {details['path']}（{details['chars']} 字符），"
                "本会话后续轮次将直接复用，不再重复读取。"
            )

    def _begin_session(self):
        """新建一个会话事件日志并完成 AGENTS.md 首次注入。"""
        self._session_id = self._store.new_id()
        self._session_created = None
        details = self.agent.inject_agents_guidance()
        if details:
            self._persist_session()
        return details

    def _persist_session(self):
        """把当前历史写入会话事件日志，失败时抛出 OSError。"""
        if not self._session_id or not self.agent.history:
            return None
        return self._store.save(
            self._session_id,
            self.agent.history,
            model=self.agent.config.model_name,
            created_at=self._session_created,
        )

    def save(self):
        """保存当前会话，返回会话信息；会话为空时返回 None。"""
        if self._busy:
            return None
        if not self.agent.history:
            self.view.show_notice("当前会话为空，没有需要保存的内容。")
            return None
        try:
            info = self._persist_session()
        except OSError as e:
            self.view.show_error(f"保存会话失败：{e}")
            return None
        self.view.show_notice(f"已保存会话 {info.id}：{info.path}")
        return info

    def auto_save(self):
        """静默保存当前会话（/new、退出与每轮结束后调用）。"""
        if not self.agent.config.get_bool("session.auto_save", True):
            return None
        if not self.agent.history:
            return None
        try:
            return self._persist_session()
        except OSError as e:
            self.view.show_error(f"自动保存会话失败：{e}")
            return None

    def new_session(self):
        """保存当前会话并开始一个全新的会话（保存动作不受 auto_save 配置影响）。"""
        if self._busy:
            return False
        saved = None
        if self.agent.history:
            try:
                saved = self._persist_session()
            except OSError as e:
                self.view.show_error(f"保存会话失败：{e}")
        self.agent.reset()
        self._session_id = self._store.new_id()
        self._session_created = None
        details = self.agent.inject_agents_guidance()
        if details:
            self._persist_session()
        self.view.clear()
        self._notify_context()
        message = "已新建会话"
        if saved is not None:
            message += f"，上一个会话已保存为 {saved.id}"
        if details:
            message += f"，已加载项目规范 {details['path']}"
        self.view.show_notice(message + "。")
        return True

    def list_sessions(self):
        return self._store.list()

    def resume(self, session_id):
        """恢复指定会话，返回是否成功。"""
        if self._busy:
            return False
        if self.agent.history:
            # 切换前先保存当前会话，避免未保存的对话丢失
            self.auto_save()
        try:
            payload = self._store.load(session_id)
        except (OSError, FileNotFoundError) as e:
            self.view.show_error(f"恢复会话失败：{e}")
            return False

        self.agent.load_history(payload["history"])
        self._session_id = payload["id"]
        self._session_created = payload["created_at"] or None
        details = self.agent.inject_agents_guidance()
        if details:
            try:
                self._persist_session()
            except OSError as e:
                self.view.show_error(f"保存会话失败：{e}")
        self.view.show_history(self.agent.history)
        self._notify_context()
        self.view.show_notice(
            f"已恢复会话 {payload['id']}（{payload['message_count']} 条历史消息）。"
        )
        return True

    # ---------------------------------------------------------------- 对话

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
                "上下文占用已达告警阈值，请先执行 /compact 压缩上下文后再继续提问。"
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
            self.auto_save()
            if self.agent.needs_compact() and not self._cancel_event.is_set():
                self.view.show_warning(
                    "上下文占用已达告警阈值，请执行 /compact 压缩上下文；"
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
            self.auto_save()
        finally:
            self._busy = False
            self.view.set_busy(False)
            self._notify_context()
            if self.agent.needs_compact():
                self.view.show_warning(
                    "上下文占用仍超过告警阈值，请检查错误后重新执行 /compact。"
                )

    def clear(self):
        if self._busy:
            return
        self.agent.reset()
        self.view.clear()
        self._notify_context()
