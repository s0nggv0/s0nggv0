# Practice02 - Function Call 聊天助手

基于 OpenAI SDK 的命令行聊天程序，通过 Function Call 让大模型调用本地 Python 函数完成计算与查询。

## 文件说明

| 文件 | 说明 |
| --- | --- |
| `chat.py` | 基础版本，支持 `getDate` 工具（获取当前日期时间） |
| `chat_leap.py` | 增强版本，在基础版本上新增 `isLeapYear` 工具（判断闰年） |
| `config.ini` | 配置文件，存放 API 地址、模型名称和密钥（未纳入版本控制） |
| `.gitignore` | 忽略 `config.ini`、`__pycache__/`、`*.pyc` |

## 环境要求

- **Python 3.8 及以上**
- **仅支持 Windows**：`getDate` 通过调用系统 `cmd /c date /t && time /t` 命令获取时间，其他系统上该工具会返回错误
- 依赖：`openai` SDK

## 配置

编辑 `config.ini`：

```ini
base_url=https://api.deepseek.com
model_name=deepseek-flash
key=你的API密钥
```

> 注意：请勿将真实 API 密钥提交到版本库。

## 运行

安装依赖：

```bash
pip install openai
```

运行基础版本：

```bash
python chat.py
```

运行闰年判断版本：

```bash
python chat_leap.py
```

## 工具列表

### getDate

- **功能**：获取当前电脑的日期和时间
- **参数**：无
- **实现**：调用系统 `date /t && time /t` 命令（仅 Windows）

### isLeapYear（仅 chat_leap.py）

- **功能**：判断输入年份是否为闰年
- **参数**：`year`（整数，要判断的年份）
- **计算方式**：纯 Python 代码实现

```python
def isLeapYear(year):
    if (year % 4 == 0 and year % 100 != 0) or (year % 400 == 0):
        return True
    return False
```

闰年规则：

1. 能被 4 整除且不能被 100 整除的是闰年
2. 能被 400 整除的也是闰年

## 使用示例

```
你好，有什么问题（支持 function call: getDate, isLeapYear）

我：2024年是闰年吗？
---
2024 年是闰年
2024 年是闰年，因为它能被 4 整除且不能被 100 整除。
```

> 第一行是工具返回的原始结果，第二行是模型据此生成的最终回答。

## 工作流程

1. 用户输入问题，程序将对话历史发送给大模型
2. 大模型判断需要调用工具时，返回 `tool_calls`
3. 程序解析参数，执行对应的本地 Python 函数
4. 将执行结果以 `tool` 角色回传给大模型，由其生成最终回答
5. 若模型继续请求工具，重复步骤 2-4，直到模型不再请求工具为止
