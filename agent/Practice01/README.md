# chat.py

一个极简的单文件命令行问答工具，通过 OpenAI 兼容的 Chat Completions 接口与模型进行多轮对话，并支持流式输出。

## 功能

- 从脚本同目录读取 `config.ini` 获取接口配置
- 使用 `input()` 获取用户提示词
- 流式调用 Chat Completions 接口，边接收边打印模型回复
- 多轮对话：每次请求携带本次运行内的完整聊天记录（仅内存保存，重启后清空）

## 依赖

- Python 3
- OpenAI 官方 SDK

```bash
pip install openai
```

## 配置

在脚本同目录创建 `config.ini`，严格按三行 `key=value` 格式填写（无需 `[section]`，字段名请保持原样）：

```ini
base_rul=https://api.deepseek.com
mode_name=deepseek-flash
key=你的APIKey
```

- `base_rul`：接口 Base URL
- `mode_name`：模型名称
- `key`：API Key

> 注意：`config.ini` 需自行创建，脚本不会自动生成。请勿将含真实 Key 的 `config.ini` 提交到代码仓库。

## 使用

```bash
python chat.py
```

输入提示词并回车，先输出一行 `---` 分割线，随后流式显示模型回复。

## 常见错误

| 提示 | 原因 |
| --- | --- |
| `错误：config.ini 不存在` | 目录下缺少 `config.ini` |
| `错误：缺少字段 xxx` | `config.ini` 缺少 `base_rul` / `mode_name` / `key` 字段 |
| `Missing credentials` | `key=` 为空，未填写 API Key |