# 宠物医院 MCP Server（pethospital-mcp）

把「宠物医院管理系统」的 REST API 封装为 MCP 工具，让支持 MCP 的 AI 客户端能够查询与录入宠物档案。

- 协议：MCP `2026-07-28`（Streamable HTTP）
- SDK：Python MCP SDK v1.7.0+
- 后端：由 `pethospital.exe` 提供的 REST API（`http://127.0.0.1:8080`）

## 工具

| 工具 | 说明 |
| --- | --- |
| `list_pets` | 查询宠物档案列表，支持种类 / 医生 / 状态 / 疾病 / 主人等维度筛选，以及全文检索、分页、排序 |
| `create_pet` | 新增一条宠物档案 |

第一期实现 `list_pets`，第二期加入 `create_pet`；后续计划扩展 `get_pet`、`add_record` 等。

### 参数约束

工具入参在 schema 中直接声明类型、范围与枚举，模型从 `tools/list` 即可读到：

| 参数 | 约束 |
| --- | --- |
| `page` | `integer`，最小值 1 |
| `page_size` | `integer`，1–100，默认 20 |
| `min_cost` / `max_cost` | `number`，最小值 0 |
| `order` | 枚举 `asc` / `desc` |
| `sort_by` | 建议取值 `name` / `totalCost` / `visitCount` / `createdAt` |
| `create_pet.name` / `create_pet.species` | 必填，最短 1 字符 |
| `create_pet.gender` | 枚举 `公` / `母` |
| `create_pet.ageMonths` | `integer`，0–1200 |

越界参数会在进入业务逻辑前被 SDK 的 schema 校验拒绝。

### 错误语义

上游失败统一转换为带错误码的 JSON 消息回传给模型（不会透传裸异常或上游 HTML）：

| 错误码 | 触发场景 |
| --- | --- |
| `UPSTREAM_TIMEOUT` | 请求超过 `PETHOSPITAL_TIMEOUT` 秒 |
| `UPSTREAM_UNAVAILABLE` | 连接被拒、DNS/网络不可达 |
| `UPSTREAM_HTTP_ERROR` | 上游返回 4xx/5xx |
| `UPSTREAM_BAD_PAYLOAD` | 返回非 JSON、缺少 `data`、字段与契约不符 |

消息形如 `{"code": "UPSTREAM_TIMEOUT", "message": "...", "detail": "..."}`。

### 韧性与日志

- `GET /api/v1/pets` 按 `PETHOSPITAL_RETRIES` 做指数退避重试（默认 2 次重试，退避 0.5s 起）；`POST` 不重试，避免重复建档。
- 每次工具调用输出一行结构化日志到 stderr：`tool=... path=... status=ok/failed code=... elapsed=...s`，级别由 `MCP_LOG_LEVEL` 控制。


## 快速开始

```powershell
python -m venv .venv
.\.venv\Scripts\pip.exe install -e .

# 启动（会自动检测并拉起同目录的 pethospital.exe）
.\.venv\Scripts\python.exe main.py
```

- MCP 监听：`http://127.0.0.1:8081`
- 依赖 `pethospital.exe` 与本文件同目录；若 `8080` 端口已有服务在运行则直接复用

## 验证

```powershell
.\.venv\Scripts\python.exe verify_mcp.py
```

## 配置（环境变量）

| 变量 | 默认 | 说明 |
| --- | --- | --- |
| `PETHOSPITAL_API_URL` | `http://127.0.0.1:8080` | 宠物医院 REST API 地址 |
| `PETHOSPITAL_TIMEOUT` | `30` | 单次上游请求超时（秒） |
| `PETHOSPITAL_RETRIES` | `2` | 幂等 GET 的最大重试次数 |
| `PETHOSPITAL_RETRY_BACKOFF` | `0.5` | 首次重试退避秒数（之后逐次翻倍） |
| `MCP_LOG_LEVEL` | `INFO` | 日志级别 |
| `MCP_HOST` | `127.0.0.1` | MCP 服务监听地址（仅本机，勿改为 `0.0.0.0`） |
| `MCP_PORT` | `8081` | MCP 服务端口 |
| `MCP_TRANSPORT` | `streamable-http` | 传输方式 |

## 文件说明

| 文件 | 说明 |
| --- | --- |
| `main.py` | MCP Server 主体 |
| `MCP-SERVER-DESIGN.md` | 完整设计规格书（协议规范、工具定义、迭代计划） |
| `verify_mcp.py` | MCP 服务校验脚本 |
| `pyproject.toml` | 依赖与打包配置 |
| `LICENSE` | 开源许可证 |
| `pethospital.exe` | 后端 REST API，二进制文件，未纳入版本控制 |