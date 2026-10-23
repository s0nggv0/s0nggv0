# FAgent - Function Call 智能助手

基于 OpenAI SDK 的本地智能助手，通过 **Function Call（工具调用）** 让大模型执行本地操作，
包括日期查询、闰年判断以及完整的文件系统增删改查。项目采用 **`core` + `tui`** 两层架构，
业务逻辑与界面展示完全隔离，当前提供 Textual TUI 与命令行两种界面。

## 目录结构

```text
FAgent/
├── main.py                  # 组合根：加载配置、装配 Agent 与界面、解析启动参数
├── config.ini               # API 配置（不纳入版本控制）
├── core/                    # 核心层：纯业务逻辑，不依赖任何 UI
│   ├── __init__.py          # 对外统一出口
│   ├── config.py            # 配置模型、解析与校验
│   ├── agent.py             # 会话历史、模型调用、工具调用循环
│   └── tools/               # 工具业务模块
│       ├── __init__.py      # 注册编排 + 公共 API
│       ├── registry.py      # @tool 注册、参数校验、异常兜底、统一分发
│       ├── common.py        # 路径解析、编码探测、文本文件判定
│       ├── system.py        # getDate / isLeapYear / getCwd
│       └── filesystem.py    # 目录与文件的增删改查
└── tui/                     # 展示层：交互与渲染
    ├── __init__.py
    ├── base.py              # ChatView 契约 + ChatPresenter 共享控制器
    ├── console.py           # 命令行界面适配器
    ├── app.py               # Textual TUI
    └── factory.py           # 界面注册与延迟加载
```

## 分层设计

依赖方向严格单向：

```text
main.py  ──>  core
   │
   └──────>  tui  ──(注入 Agent)──> core
```

- `core` 不引用 `tui`、Textual、Rich，可独立复用或测试。
- `tui` 不直接实现业务，只把界面事件交给 `ChatPresenter`，再由 `ChatPresenter` 调用 `Agent`。
- `main.py` 是唯一的组合根，负责创建 `Agent` 并注入界面。
- `core/tools` 按业务拆分模块，通过 `@tool` 装饰器注册，新增工具无需修改分发代码。

## 环境要求

- Python 3.9 及以上
- 依赖：`openai`、`textual`（TUI 使用，Rich 随其安装）
- `getDate` 工具依赖 Windows 的 `cmd /c date /t && time /t`，其他系统会返回 `Error`；其余工具跨平台可用

安装依赖：

```bash
pip install openai textual
```

## 配置

在 `main.py` 同目录创建 `config.ini`（程序按脚本所在目录定位，与启动路径无关）：

```ini
base_url=https://api.deepseek.com
model_name=deepseek-flash
key=你的API密钥
```

- 支持 `#` 开头的注释行与空行
- `base_url`、`model_name`、`key` 任一缺失时，程序打印错误并以退出码 1 结束
- `config.ini` 已被 `.gitignore` 忽略，请勿提交真实密钥

## 运行

```bash
# 默认启动 Textual TUI
python main.py

# 启动命令行界面
python main.py --ui console

# 查看帮助
python main.py --help
```

### TUI 操作

| 操作 | 说明 |
| --- | --- |
| 输入问题后回车 | 发送消息，等待模型回答 |
| `↑` / `↓` | 在输入框中回溯历史提问 |
| `Esc` | 取消当前请求，保留已生成的片段 |
| `/help` | 查看命令与快捷键 |
| `/tools` | 查看全部工具及用途 |
| `/retry` | 重发上一条提问 |
| `/clear` 或 `Ctrl+L` | 清空界面与会话历史 |
| `/quit` 或 `Ctrl+Q` | 退出程序 |
| `Ctrl+B` | 显示/隐藏右侧栏（终端窄于 100 列时自动隐藏） |

界面参考 opencode 的极简风格：启动时显示居中的 FAGENT 字标、模型 / 目录 / 工具信息卡，
随后消息流以限宽居中的方式滚动，底部是带提示符的输入框与状态栏（模型、轮次、耗时、当前状态）。
右侧栏展示工具列表（执行中的工具带 spinner 高亮）、轮次 / 耗时 / 状态与快捷键。
模型请求在后台线程中执行，不会阻塞界面；回答逐字流式显示并带光标，思考期间行内展示 spinner，
工具执行时以单行消息显示 spinner 与参数，完成后显示耗时与可折叠结果，回答结束后自动转为 Markdown 渲染。
配色使用内置的自定义深色主题（近黑背景 + 暖橙强调色），终端宽度不足时自动精简提示栏、字标与右侧栏。

## 工具列表（共 12 个）

| 工具 | 参数 | 功能 |
| --- | --- | --- |
| `getDate` | 无 | 获取当前日期时间（仅 Windows） |
| `isLeapYear` | `year` | 判断闰年 |
| `getCwd` | 无 | 获取当前工作目录绝对路径 |
| `listDirectory` | `path="."`、`recursive=false` | 列出目录内容，单次最多 500 条 |
| `getFileType` | `path` | 返回目录/文本/二进制类型、MIME 与扩展名 |
| `readFile` | `path`、`max_chars=20000` | 读取纯文本，自动识别 UTF-8/GBK，超长截断 |
| `createFile` | `directory="."`、`filename`、`content` | 创建文件，自动建多级目录，目标存在时不覆盖 |
| `editFile` | `path`、`content`、`mode` | `overwrite` 覆盖 / `append` 追加，保留原编码 |
| `createDirectory` | `path` | 创建多级目录，已存在不报错 |
| `deleteDirectory` | `path` | 递归删除目录，带安全护栏 |
| `deleteFile` | `path` | 删除文件 |
| `renamePath` | `src`、`dst` | 重命名/移动，目标不可已存在 |

所有工具错误统一以 `Error: ...` 文本回传给模型，不会中断对话。

## 安全护栏

- `deleteDirectory` 拒绝删除磁盘根目录、当前工作目录及其上级目录。
- `createFile` 目标已存在时不覆盖，需改用 `editFile`。
- `readFile` / `editFile` 只处理纯文本文件，二进制文件直接报错。
- `renamePath` 目标已存在时报错，不会静默覆盖。
- 工具异常由 `registry.run_tool` 统一捕获，避免聊天循环中断。

## 扩展指南

### 新增工具

在 `core/tools/system.py` 或 `core/tools/filesystem.py` 中添加带 `@tool` 装饰器的函数即可：

```python
from .registry import tool


@tool(
    "echoText",
    "原样返回输入文本",
    {
        "type": "object",
        "properties": {"text": {"type": "string", "description": "要返回的文本"}},
        "required": ["text"],
    },
)
def echo_text(text):
    return text
```

`registry.run_tool` 会自动完成必填参数校验、未知参数过滤、异常兜底与分发。
若新增业务模块，在 `core/tools/__init__.py` 中导入以触发注册。

### 新增界面

1. 实现 `tui.base.ChatView` 的全部方法（WebSocket、桌面窗口等均可）。
2. 在 `tui/factory.py` 的 `_BACKENDS` 中登记入口类，例如 `"web": "web:WebUI"`。
3. `WebUI` / `DesktopUI` 需提供 `run()` 方法，并自行把 `ChatPresenter.submit` 放到后台线程或任务中执行。

`core` 与 `ChatPresenter` 无需任何改动。
