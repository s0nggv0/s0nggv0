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