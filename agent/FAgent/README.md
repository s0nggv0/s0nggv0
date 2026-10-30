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
│   ├── skills.py            # 技能目录扫描、frontmatter 解析与系统提示生成
│   └── tools/               # 工具业务模块
│       ├── __init__.py      # 注册编排 + 公共 API
│       ├── registry.py      # @tool 注册、参数校验、异常兜底、统一分发
│       ├── common.py        # 路径解析、编码探测、文本文件判定
│       ├── system.py        # getDate / isLeapYear / getCwd
│       ├── filesystem.py    # 目录与文件的增删改查
│       ├── web.py           # searchWeb：联网搜索；fetchWeb：抓取网页正文
│       ├── cli.py           # RunCli：以当前用户权限调用本机 CLI 程序
│       └── skill.py         # loadSkill：按需加载技能 SKILL.md 全文或附件文件
├── .agents/skills/          # 技能目录（Agent Skills 规范，可选，按需创建），每个技能一个目录（SKILL.md + references）
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
- 依赖：`openai`、`textual`（TUI 使用，Rich 随其安装）、`trafilatura`（网页正文提取）
- `getDate` 工具依赖 Windows 的 `cmd /c date /t && time /t`，其他系统会返回 `Error`
- `fetchWeb` 依赖本地 `curl` 命令行程序（Windows 10+ 自带），需确保其在 `PATH` 中

安装依赖：

```bash
pip install openai textual trafilatura
```

## 配置

在 `main.py` 同目录创建 `config.ini`（程序按脚本所在目录定位，与启动路径无关）：

```ini
base_url=https://api.deepseek.com
model_name=deepseek-flash
key=你的API密钥

[search]
baidu_api_key=你的百度千帆API Key
```

- 支持 `#` 开头的注释行、空行与 `[section]` 小节
- `base_url`、`model_name`、`key` 任一缺失时，程序打印错误并以退出码 1 结束
- `searchWeb` 使用 `[search]` 小节的 `baidu_api_key` 调用百度千帆搜索 API；缺失时工具会向模型返回明确的错误信息
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
| `Shift+Enter` | 在输入框内换行（终端不支持时可改用 `Ctrl+J`） |
| 直接粘贴 | 多行文本原样插入，输入框随内容自动增高（最多 8 行） |
| `↑` / `↓` | 补全面板可见时选择候选项；否则在首行 / 末行回溯历史提问，多行文本内按行移动光标 |
| `/` | 弹出命令面板，继续输入可过滤，`Tab` 补全选中命令 |
| `@` | 补全当前目录下的文件 / 目录路径，`Tab` 补全；仅插入路径，读取文件仍由模型调用 `readFile` |
| `Tab` | 补全面板可见时应用当前候选；目录补全会继续列出下一级内容 |
| `Ctrl+T` | 展开 / 折叠最近一次工具结果 |
| `Ctrl+Y` | 复制最近一次工具结果（终端需支持 OSC 52） |
| `Ctrl+O` | 全屏查看工具结果，`PgUp` / `PgDn` 翻页，`c` 复制，`Esc` 关闭 |
| `Esc` | 取消当前请求，保留已生成的片段；补全面板可见时先关闭面板 |
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
输入 `/` 或 `@` 会在输入框上方弹出补全面板，支持键盘上下选择与 `Tab` 补全；最近一次工具结果可用
`Ctrl+T` 展开 / 折叠、`Ctrl+Y` 复制、`Ctrl+O` 全屏分页查看。
配色使用内置的自定义深色主题（近黑背景 + 暖橙强调色），终端宽度不足时自动精简提示栏、字标与右侧栏。

## 工具列表（共 16 个）

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
| `fetchWeb` | `url`、`max_chars=20000` | 用 curl 抓取网页，经 trafilatura 提取正文并转为 Markdown |
| `searchWeb` | `query`、`top_k=10` | 调用百度千帆搜索 API，返回结果摘要与参考来源标题、URL |
| `RunCli` | `command`、`args`、`timeout=60` | 以当前用户权限调用本机任意 CLI，返回 stdout、stderr 与退出码，超长输出截断 |
| `loadSkill` | `name`、`filename?` | 仅传 `name` 返回技能 SKILL.md 全文；同时传 `filename` 读取技能附件（仅限技能目录内部） |

所有工具错误统一以 `Error: ...` 文本回传给模型，不会中断对话。

## 技能（Skill）

遵循 Agent Skills 规范：以**程序启动时的工作目录**为项目根，技能位于
`<项目根>/.agents/skills/<技能目录>/SKILL.md`，文件以 YAML frontmatter 开头，
必须包含 `name` 与 `description` 字段；同目录可附带 `references/` 等参考文件。

启动时仅扫描各技能的 `name` 与 `description` 并注入系统提示，不读取技能正文。
模型判断任务匹配后调用 `loadSkill(name)` 加载 SKILL.md 全文；需要细节时再调用
`loadSkill(name, filename)` 读取附件文件（此时不重复返回 SKILL.md）。`filename`
的解析规则：

- 优先精确路径匹配，依次兼容绝对路径、相对技能目录的路径、相对项目根的路径
- 仅提供文件名时在技能目录内递归搜索；命中多个同名文件时返回候选路径，由模型决定读取哪个
- 读取范围始终限制在该技能目录内部，解析到目录之外的路径会被拒绝

当前未安装技能。此前安装的 `humanizer`（去 AI 味）已迁移至 `office/.agents/skills/`。

技能安装后，当用户请求与技能描述相符时，模型会先调用 `loadSkill` 加载操作规程再执行，
也可以在提问中显式指定技能名。

安装新技能时，把包含 `SKILL.md` 的目录整体复制到 `<项目根>/.agents/skills/` 下，
重启 FAgent 即可识别。注意技能目录跟随**启动时的工作目录**，与 `main.py` 所在位置无关：
想用某套技能，就在存放该技能 `.agents/skills/` 的目录下启动 FAgent。
技能正文属于第三方提示词，安装前应自行检查其中是否包含不当的工具调用或数据外发指令。

## 安全护栏

- `deleteDirectory` 拒绝删除磁盘根目录、当前工作目录及其上级目录。
- `createFile` 目标已存在时不覆盖，需改用 `editFile`。
- `readFile` / `editFile` 只处理纯文本文件，二进制文件直接报错。
- `renamePath` 目标已存在时报错，不会静默覆盖。
- `RunCli` 以当前用户权限执行任意本机程序，**并非沙箱**：请仅在可信环境中使用，并注意模型可能发起删除、修改系统状态等操作。
- `RunCli` 使用参数列表且 `shell=False`，不经过 Shell 拼接；标准输入置空，超时上限 600 秒，超长输出自动截断。
- 工具异常由 `registry.run_tool` 统一捕获，避免聊天循环中断。

## 扩展指南

### 新增工具

在 `core/tools/` 下已有模块（`system.py`、`filesystem.py`、`web.py`、`cli.py`）中添加带 `@tool` 装饰器的函数即可：

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
