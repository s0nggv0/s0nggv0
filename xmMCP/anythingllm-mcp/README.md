# AnythingLLM MCP Server

MCP Server（协议版本 **2026-07-28**，Streamable HTTP）将本机 AnythingLLM 暴露为一个 MCP 工具：向其中唯一的工作区提问，AI 会基于该工作区中存储的文档/知识进行回答。

## 功能

- **工具 `workspace_chat`**：提问 → 调用 AnythingLLM `POST /api/v1/workspace/{slug}/chat`，返回工作区 AI 的回答。
- **工具 `workspace_file_count`**：读取 `GET /api/v1/workspace/{slug}`，返回工作区中的文件（文档）数量，可附带列出文件名。
- 工作区自动识别：AnythingLLM 只有一个工作区时自动选用；多个时通过 `.env` 的 `ANYTHINGLLM_WORKSPACE_SLUG` 指定。
- 固定 `ANYTHINGLLM_SESSION_ID` 让 AnythingLLM 保持滚动对话历史。
- 监听 `127.0.0.1:3002/mcp`，stateless（2026-07-28 无会话），单 JSON 应答。

## 网页录入工具（upload.html）

随服务器一并提供 `upload.html`：浏览器打开即可把本地文档上传到 AnythingLLM 工作区并自动向量化（`POST /api/v1/document/upload` + 轮询等待嵌入完成），之后即可通过 `workspace_chat` 基于这些文档提问。

- 直接双击或在浏览器打开 `upload.html` 即可使用。
- 页面内置 API 地址 `http://localhost:3001/api` 与 API key（与 `.env` 保持一致）；上传前请确保 AnythingLLM 正在运行。

## 快速开始

```powershell
# 1) 依赖（项目已提供 .venv）
python -m venv .venv
.\.venv\Scripts\pip.exe install -r requirements.txt

# 2) 配置
Copy-Item .env.example .env   # 填入 ANYTHINGLLM_API_KEY

# 3) 启动（确保 AnythingLLM 正在运行，端口 3001）
.\.venv\Scripts\python.exe server.py
```

启动后端点：`http://127.0.0.1:3002/mcp`。

## 验证

```powershell
# 另开终端，端到端冒烟测试（discover / tools/list / tools/call / 头校验）
.\.venv\Scripts\python.exe smoke_test.py
```

## 接入 MCP 客户端

以 Claude Code / Cursor 等支持 HTTP 传输的客户端为例，配置：

```json
{
  "mcpServers": {
    "anythingllm": {
      "type": "http",
      "url": "http://127.0.0.1:3002/mcp"
    }
  }
}
```

本机推理（GGUF）单次回答可能需要数秒到数十秒，客户端超时请放宽。

## 配置项（`.env`）

| 变量 | 默认 | 说明 |
|---|---|---|
| `ANYTHINGLLM_URL` | `http://localhost:3001/api` | AnythingLLM API 基地址 |
| `ANYTHINGLLM_API_KEY` | 必填 | Developer API key |
| `ANYTHINGLLM_WORKSPACE_SLUG` | 空（自动检测唯一工作区） | 指定工作区 |
| `ANYTHINGLLM_SESSION_ID` | `mcp-anythingllm-workspace` | 对话窗口 ID |
| `MCP_HOST` / `MCP_PORT` / `MCP_PATH` | `127.0.0.1` / `3002` / `/mcp` | MCP HTTP 监听 |
| `MCP_LOG_LEVEL` | `INFO` | 日志级别 |

## 安全说明

- 仅绑定 `127.0.0.1`，请不要对外网开放。
- API key 只放在 `.env`（该文件已被 `.gitignore` 建议排除），不要提交到仓库。