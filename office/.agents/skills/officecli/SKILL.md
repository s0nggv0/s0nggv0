---
name: officecli
description: 通过 officecli 单文件命令行工具创建、读取、编辑与校验 .docx / .xlsx / .pptx 文件。无需安装 Office，支持 JSON 结构化输出、DOM 级编辑与原始 XML 三层操作；适用于生成报告、幻灯片、表格等工作。当用户需要读写 Word / Excel / PowerPoint 文件，或提到 officecli、docx、xlsx、pptx 操作时使用。
---

# OfficeCli

AI 友好的 Office 文档命令行工具：单个 Windows 可执行文件，无需安装 Office，支持 `.docx`、`.xlsx`、`.pptx`。

## 可执行文件位置

```text
scripts/officecli-win-x64.exe
```

调用时使用该文件的完整路径（技能目录内的 `scripts/officecli-win-x64.exe`），例如：

```powershell
& "<技能目录>/scripts/officecli-win-x64.exe" help
```

## 完整参考文档

详细命令体系、路径语法、属性名、批量操作与常见错误处理，参见：

```text
references/officecli-guide.md
```

需要时用 `loadSkill` 加载该附件（`filename=references/officecli-guide.md`），不要一次性猜测命令参数。

## 核心原则

1. **分层次操作**：`L1 读取/检查` → `L2 DOM 编辑` → `L3 原始 XML`。能用上层就不要用下层。
2. **不要猜参数**：属性名、取值格式或命令语法不确定时，先执行 help，一次查询胜过反复试错。
   ```powershell
   <exe> help                       # 全部命令与全局选项
   <exe> help docx                  # docx 全部元素
   <exe> help docx paragraph        # 某元素的完整 schema
   <exe> help docx set paragraph    # 只看 set 可用的属性
   <exe> help docx paragraph --json # 机器可读 schema
   ```
3. **先读后改**：修改前用 `view outline` / `view text` / `get` / `query` 确认结构，修改后用 `validate` 或 `view issues` 校验。
4. **路径规则**：文档路径 `'/body/p[3]'` 为 1-based；`--index` 为 0-based（`add --type row/col` 例外，为 1-based）。
5. **常驻模式**：命令会在首次访问时自动启动常驻进程，因此 officecli 自身读取始终看到最新修改；只有在**交给非 officecli 程序（Word、WPS、python-docx、上传/交付）读取前**才需要 `save` 或 `close`。
6. **格式别名**：`word`→`docx`，`excel`→`xlsx`，`ppt`/`powerpoint`→`pptx`。

## 快速示例

```powershell
# 新建 PPT 并添加标题页
<exe> create slides.pptx
<exe> add slides.pptx / --type slide --prop title="Q4 Report" --prop background=1A1A2E
<exe> add slides.pptx '/slide[1]' --type shape --prop text="Revenue grew 25%" --prop x=2cm --prop y=5cm

# 新建 Word 并写入段落
<exe> create report.docx
<exe> add report.docx /body --type paragraph --prop text="Executive Summary" --prop style=Heading1
<exe> add report.docx /body --type paragraph --prop text="Revenue increased by 25% year-over-year."

# 编辑 Excel 单元格
<exe> create data.xlsx
<exe> set data.xlsx /Sheet1/A1 --prop value="Name" --prop bold=true
<exe> set data.xlsx /Sheet1/A2 --prop value="Alice"

# 交付前落盘
<exe> close slides.pptx
```

## 专项技能

制作融资 PPT、学术论文、财务模型、数据看板或 Morph 动画时，先执行：

```powershell
<exe> load_skill <name>
```

输出即该专项技能的 SKILL.md，按其中规则执行。每次只加载一个最匹配的技能，不要叠加；常规文档使用 `word` / `pptx` / `excel` 作为默认。
