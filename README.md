# s0nggv0

本机运行的 MCP（Model Context Protocol）服务与配套工具集合。所有服务仅监听 `127.0.0.1`，面向本地使用，不对外网开放。

## 目录结构

```
xmMCP/
├── anythingllm-mcp/     AnythingLLM MCP 服务（Python）
├── anythingllm-html/    基于 AnythingLLM 本地 API 的工作台网页
├── cwyymcp/             宠物医院 Windows 发行包（Go 后端 + MCP Server）
└── pethospital-mcp/     宠物医院 MCP 服务（Python）

agent/
└── Practice01/          命令行问答小工具（OpenAI 兼容接口）
```

## xmMCP/anythingllm-mcp

基于 MCP 协议 `2026-07-28`（Streamable HTTP，stateless），将本机 AnythingLLM 暴露为 MCP 工具。

| 工具 | 说明 |
| --- | --- |
| `workspace_chat` | 向 AnythingLLM 工作区提问，AI 基于工作区中的文档作答 |
| `workspace_file_count` | 返回工作区文档数量，可附文件名列表 |

- 端点：`http://127.0.0.1:3002/mcp`
- 启动：`python server.py`（需 AnythingLLM 在 `3001` 端口运行）
- 配置：复制 `.env.example` 为 `.env`，填入 `ANYTHINGLLM_API_KEY`
- 冒烟测试：`python smoke_test.py`

## xmMCP/anythingllm-html

`upload.html`：AnythingLLM 工作台网页，浏览器打开即可使用。

- 上传本地文档到当前工作区并自动向量化
- 工作区管理：刷新 / 新建 / 删除，查看工作区文档列表
- 顶部输入 API 地址与 Key，点击「保存并连接」后生效；配置存于浏览器 `localStorage`，默认地址 `http://localhost:3001/api`

## xmMCP/pethospital-mcp

宠物医院 MCP 服务（Python），基于 MCP 协议 `2026-07-28`，把宠物医院 REST API（`http://127.0.0.1:8080`）封装为 MCP 工具。

| 工具 | 说明 |
| --- | --- |
| `list_pets` | 查询宠物档案列表，支持种类 / 医生 / 状态 / 疾病 / 主人等维度筛选，以及全文检索、分页、排序 |
| `create_pet` | 新增宠物档案 |

- 依赖 `pethospital.exe`（宠物医院 REST API），启动时自动检测端口并拉起
- 设计规格见 `MCP-SERVER-DESIGN.md`，校验脚本 `verify_mcp.py`

## xmMCP/cwyymcp

宠物医院 Windows 发行包，一个目录里包含后端与 MCP 服务两部分：

| 部分 | 说明 |
| --- | --- |
| `pethospital.exe` | Go 标准库编写的宠物医院 REST API，内嵌网页操作界面，监听 `127.0.0.1:8080`，数据存于单文件 `data/pet.db` |
| `main.py` | 把 REST API 封装为 MCP 工具，监听 `127.0.0.1:8081`，启动时自动拉起 `pethospital.exe` |

## agent/Practice01

极简命令行问答工具 `chat.py`，通过 OpenAI 兼容的 Chat Completions 接口做多轮流式问答（对话记录仅存内存，重启后清空）。

```bash
pip install openai
python chat.py
```

配置从同目录 `config.ini` 读取（`base_rul` / `mode_name` / `key`）。该文件含 API Key，已由 `.gitignore` 排除，需自行创建。

## 安全说明

- 所有服务仅绑定 `127.0.0.1`，请勿直接暴露到公网。
- API key 等敏感信息请放在 `.env` / `config.ini`（均已在 `.gitignore` 中排除），不要提交到仓库。
- `pethospital.exe`、`data/pet.db` 等二进制与数据文件不纳入版本控制。