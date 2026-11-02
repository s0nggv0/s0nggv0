---
name: office-documents
description: "创建、编辑与检查 Word（.docx）、PowerPoint（.pptx）和 Excel（.xlsx）文档。当用户要求生成报告、合同、PPT 演示、电子表格、图表、数据看板或修改已有 Office 文件时使用；通过 OfficeCli 命令行工具完成，无需安装 Microsoft Office。"
---

# 通用 Office 文档技能

## 适用场景

- 新建 Word 报告、方案、合同、备忘录、信函
- 新建 PowerPoint 演示文稿、汇报页、路演材料
- 新建 Excel 表格、数据统计、公式、透视表、图表、看板
- 读取、修改、校验已有的 .docx / .pptx / .xlsx 文件

## 核心原则

1. 所有 Office 文件操作统一通过 OfficeCli 完成，**不要改用 python-docx / openpyxl / python-pptx**。
2. 不确定属性名、取值格式或命令语法时，**先查 help，禁止猜测后反复试错**。
3. 每个产物只加载一个 OfficeCli 专用规则，不要叠加多个。
4. 产物统一写入当前工作目录下的 `deliverables/`（可调整），并在结束时回报绝对路径。
5. 文件被 Word / WPS / PowerPoint 占用时无法修改，遇到锁文件错误应提示用户先关闭。

## 可执行文件

```text
D:\xx\OfficeCli_#SULP#_26sc1d\officecli-win-x64.exe
```

通过 `RunCli` 调用：

```text
RunCli(
  command = "D:\\xx\\OfficeCli_#SULP#_26sc1d\\officecli-win-x64.exe",
  args    = ["create", "deliverables/report.docx"],
  timeout = 60
)
```

调用约定：

- `args` 的每一项必须独立，例如 `["add", "deck.pptx", "/", "--type", "slide", "--prop", "title=Q4 汇报"]`
- 含空格的值整段作为一个参数，不要拆开，也不要加多余引号
- 不经过 Shell，所以路径中的 `#`、`$`、方括号无需转义；`--prop text=$15M` 直接作为一个参数传入即可
- 默认超时 60 秒；生成大文档或批量操作时把 `timeout` 调到 120～300（上限 600）

## 标准工作流

### 1. 明确格式与路径

确认用户要的格式（docx / pptx / xlsx）、文件名称、内容要点和存放位置。缺少关键信息时先向用户确认，不要自行编造业务数据。

### 2. 加载 OfficeCli 专用规则

先执行一次 `load_skill`，按场景选择最具体的一个：

```text
args = ["load_skill", "word"]        # 通用 Word 文档
args = ["load_skill", "academic-paper"]  # 论文、期刊、引用与多栏排版
args = ["load_skill", "pptx"]        # 通用演示文稿
args = ["load_skill", "pitch-deck"]  # 仅融资路演
args = ["load_skill", "morph-ppt"]   # Morph 动画演示
args = ["load_skill", "excel"]       # 通用表格与公式
args = ["load_skill", "financial-model"]  # 财务模型与预测
args = ["load_skill", "data-dashboard"]   # 数据看板
```

加载后被打印的规则在本轮会话内持续有效，**不要重复加载**。不同产物才需要分别加载。

### 3. 查帮助（按需）

```text
args = ["help", "docx", "paragraph"]
args = ["help", "pptx", "shape", "--json"]
```

### 4. 创建文件

```text
# Word
args = ["create", "deliverables/report.docx"]

# PPT
args = ["create", "deliverables/deck.pptx"]

# Excel
args = ["create", "deliverables/data.xlsx"]
```

### 5. 填充内容

Word（段落）：

```text
args = ["add", "deliverables/report.docx", "/body",
        "--type", "paragraph", "--prop", "text=执行摘要", "--prop", "style=Heading1"]
args = ["add", "deliverables/report.docx", "/body",
        "--type", "paragraph", "--prop", "text=本季度营收同比增长 25%。"]
```

PPT（幻灯片与形状）：

```text
args = ["add", "deliverables/deck.pptx", "/",
        "--type", "slide", "--prop", "title=Q4 汇报"]
args = ["add", "deliverables/deck.pptx", "/slide[1]",
        "--type", "shape", "--prop", "text=营收增长 25%",
        "--prop", "x=2cm", "--prop", "y=5cm", "--prop", "size=24"]
```

Excel（单元格）：

```text
args = ["set", "deliverables/data.xlsx", "/Sheet1/A1",
        "--prop", "value=名称", "--prop", "bold=true"]
args = ["set", "deliverables/data.xlsx", "/Sheet1/A2", "--prop", "value=Alice"]
```

内容较多时可改用一次 `batch` 原子提交，减少重复保存：

```text
args = ["batch", "deliverables/data.xlsx", "--commands",
        "[{\"op\":\"set\",\"path\":\"/Sheet1/A1\",\"props\":{\"value\":\"名称\",\"bold\":\"true\"}}]"]
```

### 6. 校验

```text
args = ["validate", "deliverables/report.docx"]
args = ["view", "deliverables/report.docx", "issues"]
args = ["view", "deliverables/report.docx", "text"]
args = ["view", "deliverables/deck.pptx", "outline"]
```

FAgent 无法读取图片，因此不要依赖截图判断质量；用 `validate`、`view issues`、`view text`/`outline`/`stats` 的结果自检。需要人工预览时，把 `view html` 或 `screenshot` 的输出路径交给用户，或运行 `watch` 让用户在浏览器中查看。

### 7. 交付前保存

本技能自身的读写（get / query / view / dump）始终能看到最新修改，无需中途保存。只有在**交给 OfficeCli 之外的程序读取**（如上传、渲染、交付）之前，才执行：

```text
args = ["save", "deliverables/report.docx"]
# 或
args = ["close", "deliverables/report.docx"]
```

### 8. 汇报结果

向用户说明：产物绝对路径、格式与结构（页数、幻灯片数、工作表）、做了什么校验、存在哪些未解决项。不要声称“已检查视觉效果”，除非确实让用户看过。

## 常用命令速查

| 目的 | args 示例 |
| --- | --- |
| 查看结构 | `["view", "f.docx", "outline"]` |
| 查看统计 | `["view", "f.pptx", "stats"]` |
| 查看问题 | `["view", "f.docx", "issues"]` |
| 提取文本 | `["view", "f.docx", "text", "--max-lines", "80"]` |
| 查询元素 | `["query", "f.docx", "paragraph[style=Heading1]"]` |
| 读取节点 | `["get", "f.pptx", "/slide[1]", "--depth", "1", "--json"]` |
| 修改属性 | `["set", "f.pptx", "/slide[1]", "--prop", "background=1A1A2E"]` |
| 查找替换 | `["set", "f.docx", "/", "--find", "草稿", "--replace", "终稿"]` |
| 删除元素 | `["remove", "f.docx", "/body/p[4]"]` |

## 常见错误

| 错误写法 | 正确做法 |
| --- | --- |
| `--name "foo"` | 所有属性写成 `--prop name=foo` |
| 把 `--prop a=b --prop c=d` 拼成一个参数 | 每个 token 都是独立参数 |
| 路径写成 `/body/p3` | 路径从 1 开始：`/body/p[3]` |
| PPT 用 `shape[1]` 放正文 | `shape[1]` 通常是标题占位符，正文用 `shape[2]` 起 |
| 猜属性名导致失败 | 先 `help <格式> <元素>` |
| 在同一个产物上叠加多个专用规则 | 只加载最匹配的一个 |
| 大文档只给 60 秒超时 | 提高 timeout 到 120～300 |
| 失败后反复重试同一命令 | 阅读 stderr / 退出码，先查 help 或调整参数 |

## 完成标准

- 文件已创建在约定目录，扩展名与格式匹配
- `validate` 通过，`view issues` 无阻塞性问题
- 内容与用户要求一致，没有编造的占位数据
- 如需交付给其他程序读取，已执行 `save` 或 `close`

