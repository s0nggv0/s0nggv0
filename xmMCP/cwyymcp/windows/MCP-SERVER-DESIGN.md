# 宠物医院 MCP Server 开发提示词

> 本文档是开发 `pethospital-mcp` MCP Server 的完整设计规格书。
> 基于 **MCP 协议 2026-07-28**（最新版）和 **Python MCP SDK v1.7.0+**。
> **第一期仅实现 `list_pets` 一个工具**，列出宠物档案并支持多维筛选。

---

## 一、项目背景

### 源项目：宠物医院管理系统（Pet Hospital REST API）

一个用 Go 标准库编写的本地宠物医院管理系统，提供 29 个 REST API 接口，数据存储在单文件 `data/pet.db` 中。

- **数据模型**：`Pet`（宠物档案），含 `records[]`（历史病历）和 `charges[]`（消费明细）
- **数据库**：自实现嵌入式存储引擎（追加写日志 + CRC32 校验 + 内存索引 + 自动压实）
- **REST API 地址**：`http://127.0.0.1:8080`（已有 `pethospital.exe` 在运行）
- **列表接口**：`GET /api/v1/pets`，支持 `q` `name` `ownerName` `ownerPhone` `species` `doctor` `disease` `status` `min` `max` `sortBy` `order` `page` `pageSize` 等参数

### 目标：构建 MCP Server（第一期）

将 Pet Hospital 的 `GET /api/v1/pets` 接口封装为 **MCP Server 工具 `list_pets`**，使其他 AI Agent（通过 MCP Client 连接）能够：
- 查询宠物档案列表
- 按种类/医生/状态/疾病/主人等维度筛选
- 全文检索、分页、排序

后续迭代再扩展 `create_pet`、`get_pet`、`add_record` 等工具。

---

## 二、MCP 协议 2026-07-28 关键规范（必须遵守）

### 2.1 核心变更：状态无协议核心（Stateless）

- **已移除** `initialize`/`notifications/initialized` 握手
- **已移除** `Mcp-Session-Id` 头
- **每个请求必须**携带 `_meta` 字段，包含：
  - `io.modelcontextprotocol/protocolVersion`: `"2026-07-28"`（必须）
  - `io.modelcontextprotocol/clientCapabilities`: 客户端能力（必须）
  - `io.modelcontextprotocol/clientInfo`: 客户端信息（建议）
- **每个响应必须**在 `_meta` 中包含 `io.modelcontextprotocol/serverInfo`

### 2.2 `server/discover` RPC（必须实现）

- 服务器 **MUST** 实现 `server/discover` 方法
- 客户端 **MAY** 在首次请求前调用此方法获取服务器能力
- 响应包含：支持的协议版本、服务器能力、服务器身份
- Python SDK v1.7.0+ 会自动注册 `server/discover` 处理器

### 2.3 HTTP 头标准化（SEP-2243）

Streamable HTTP 传输 **必须** 包含以下头：
```http
MCP-Protocol-Version: 2026-07-28
Mcp-Method: tools/call
Mcp-Name: <工具名>
```

### 2.4 Multi Round-Trip Requests (MRTR)（SEP-2322）

- 服务器返回 `resultType: "input_required"` 时，携带 `inputRequests`
- 客户端重试原请求并附带 `inputResponses`
- 第一期不需要此功能（`list_pets` 无需用户交互）

### 2.5 结果缓存（SEP-2549）

- `tools/list` 响应 **必须** 携带 `ttlMs` 和 `cacheScope`
- Python SDK 自动处理

### 2.6 已弃用（不应在新实现中使用）

- ❌ `initialize` / `initialized` 握手
- ❌ `Mcp-Session-Id` 头
- ❌ Roots、Sampling、Logging（SEP-2577）
- ❌ HTTP+SSE 传输
- ❌ `ping`、`logging/setLevel`

### 2.7 传输方式

- **首选**：Streamable HTTP（`POST /mcp`）
- **兼容**：Stdio（用于 Claude Desktop 等本地子进程通信）
- Python SDK 通过 `FastMCP` 同时支持两种传输

---

## 三、技术栈要求

| 项目 | 要求 |
|------|------|
| 语言 | Python 3.10+ |
| MCP SDK | `mcp[cli] >= 1.7.0` |
| HTTP 客户端 | `httpx >= 0.27` |
| 协议版本 | `2026-07-28` |
| 传输 | Streamable HTTP + Stdio 双支持 |
| 序列化 | `pydantic >= 2.0`（用于定义输入/输出 Schema） |

安装命令：
```bash
pip install "mcp[cli]>=1.7.0" httpx pydantic
```

---

## 四、仅实现 `list_pets` 一个工具

### 4.1 工具定义

| MCP Tool Name | 对应 REST 端点 | 说明 |
|---|---|---|
| `list_pets` | `GET /api/v1/pets` | 查询宠物档案列表，支持多维筛选、分页、排序 |

### 4.2 `list_pets` 输入 Schema

所有参数均为可选，使用 `None` 表示不传该参数：

```python
from pydantic import BaseModel, Field
from typing import Optional

class ListPetsInput(BaseModel):
    q: Optional[str] = Field(None, description="全文检索关键词，空格分词AND，含病历全文")
    name: Optional[str] = Field(None, description="宠物姓名")
    ownerName: Optional[str] = Field(None, description="主人姓名")
    ownerPhone: Optional[str] = Field(None, description="主人电话")
    species: Optional[str] = Field(None, description="种类（犬/猫/兔等）")
    doctor: Optional[str] = Field(None, description="主治医生")
    disease: Optional[str] = Field(None, description="疾病")
    status: Optional[str] = Field(None, description="就诊状态（待就诊/就诊中/住院中/已康复/慢性病随访）")
    min_cost: Optional[float] = Field(None, description="最低总花费", alias="min")
    max_cost: Optional[float] = Field(None, description="最高总花费", alias="max")
    sort_by: Optional[str] = Field(None, description="排序字段", description_extra="可选值: name, totalCost, visitCount, createdAt")
    order: Optional[str] = Field(None, description="排序方向", description_extra="可选值: asc, desc")
    page: Optional[int] = Field(1, description="页码", ge=1)
    page_size: Optional[int] = Field(20, description="每页条数", ge=1, le=100, alias="pageSize")
```

### 4.3 `list_pets` 输出 Schema

```python
class PetSummary(BaseModel):
    id: str
    name: str
    species: str
    breed: Optional[str]
    gender: Optional[str]
    ageMonths: Optional[int]
    color: Optional[str]
    ownerName: Optional[str]
    ownerPhone: Optional[str]
    doctor: Optional[str]
    disease: Optional[str]
    status: Optional[str]
    totalCost: Optional[float]
    visitCount: Optional[int]

class ListPetsOutput(BaseModel):
    items: list[PetSummary]
    total: int
    page: int
    pageSize: int
```

### 4.4 REST API 对接

MCP Server 通过 `httpx` 调用已有 `pethospital.exe` 的 REST API：

```
GET http://127.0.0.1:8080/api/v1/pets?q=...&species=犬&page=1&pageSize=20
```

REST 响应格式（从 README.md 可知）：
```json
{
  "code": 200,
  "message": "ok",
  "data": { "items": [...], "total": 308, "page": 1, "pageSize": 20 },
  "time": "2025-01-01T00:00:00+08:00"
}
```

---

## 五、Python 实现模板

### 5.1 完整代码

```python
"""
宠物医院 MCP Server - 第一期：list_pets
基于 MCP 协议 2026-07-28，使用 Python MCP SDK v1.7.0+
"""

import os
import httpx
from pydantic import BaseModel, Field
from typing import Optional
from mcp.server.fastmcp import FastMCP

# === 配置 ===
PETHOSPITAL_API_URL = os.getenv("PETHOSPITAL_API_URL", "http://127.0.0.1:8080")
MCP_PORT = int(os.getenv("MCP_PORT", "8081"))
MCP_TRANSPORT = os.getenv("MCP_TRANSPORT", "streamable-http")  # "streamable-http" or "stdio"

# === Pydantic Schemas ===
class PetSummary(BaseModel):
    id: str
    name: str
    species: str
    breed: Optional[str] = None
    gender: Optional[str] = None
    ageMonths: Optional[int] = None
    color: Optional[str] = None
    ownerName: Optional[str] = None
    ownerPhone: Optional[str] = None
    doctor: Optional[str] = None
    disease: Optional[str] = None
    status: Optional[str] = None
    totalCost: Optional[float] = None
    visitCount: Optional[int] = None

class ListPetsOutput(BaseModel):
    items: list[PetSummary]
    total: int
    page: int
    pageSize: int

class ListPetsInput(BaseModel):
    q: Optional[str] = Field(None, description="全文检索关键词，空格分词AND")
    name: Optional[str] = Field(None, description="宠物姓名")
    ownerName: Optional[str] = Field(None, description="主人姓名")
    ownerPhone: Optional[str] = Field(None, description="主人电话")
    species: Optional[str] = Field(None, description="种类")
    doctor: Optional[str] = Field(None, description="主治医生")
    disease: Optional[str] = Field(None, description="疾病")
    status: Optional[str] = Field(None, description="就诊状态")
    min_cost: Optional[float] = Field(None, description="最低总花费", alias="min")
    max_cost: Optional[float] = Field(None, description="最高总花费", alias="max")
    sort_by: Optional[str] = Field(None, description="排序字段")
    order: Optional[str] = Field(None, description="排序方向")
    page: Optional[int] = Field(1, ge=1, description="页码")
    page_size: Optional[int] = Field(20, ge=1, le=100, alias="pageSize", description="每页条数")

# === HTTP 客户端 ===
async def fetch_pets(params: dict) -> ListPetsOutput:
    """调用 pethospital.exe 的 REST API 获取宠物列表"""
    async with httpx.AsyncClient(timeout=30.0) as client:
        url = f"{PETHOSPITAL_API_URL}/api/v1/pets"
        # 将 alias 映射为实际 query 参数名
        query_params = {}
        for key, value in params.items():
            if value is not None and value != "":
                query_params[key] = str(value)
        resp = await client.get(url, params=query_params)
        resp.raise_for_status()
        json_data = resp.json()
        data = json_data["data"]
        return ListPetsOutput(
            items=[PetSummary(**item) for item in data["items"]],
            total=data["total"],
            page=data["page"],
            pageSize=data["pageSize"]
        )

# === MCP Tool Handler ===
async def list_pets_handler(
    q: Optional[str] = None,
    name: Optional[str] = None,
    ownerName: Optional[str] = None,
    ownerPhone: Optional[str] = None,
    species: Optional[str] = None,
    doctor: Optional[str] = None,
    disease: Optional[str] = None,
    status: Optional[str] = None,
    min_cost: Optional[float] = None,
    max_cost: Optional[float] = None,
    sort_by: Optional[str] = None,
    order: Optional[str] = None,
    page: Optional[int] = 1,
    page_size: Optional[int] = 20,
) -> ListPetsOutput:
    """
    查询宠物档案列表。支持按种类/医生/状态/疾病筛选，支持关键词搜索、分页和排序。
    
    参数说明：
    - q: 全文检索关键词（空格分词AND），含病历全文
    - species: 按种类筛选（犬/猫/兔等）
    - doctor: 按主治医生筛选
    - status: 按就诊状态筛选
    - disease: 按疾病筛选
    - ownerName/ownerPhone: 按主人信息筛选
    - min/max: 按总花费区间筛选
    - sortBy/order: 排序字段和方向
    - page/pageSize: 分页参数
    """
    params = {
        "q": q, "name": name, "ownerName": ownerName, "ownerPhone": ownerPhone,
        "species": species, "doctor": doctor, "disease": disease, "status": status,
        "min": min_cost, "max": max_cost,
        "sortBy": sort_by, "order": order,
        "page": page, "pageSize": page_size,
    }
    return await fetch_pets(params)

# === 服务器初始化 ===
mcp = FastMCP(
    "pet-hospital",
    version="1.0.0",
    instructions="宠物医院管理系统 MCP Server，提供宠物档案查询服务。",
)

# 注册 list_pets 工具
@mcp.tool()
async def list_pets(
    q: Optional[str] = None,
    name: Optional[str] = None,
    ownerName: Optional[str] = None,
    ownerPhone: Optional[str] = None,
    species: Optional[str] = None,
    doctor: Optional[str] = None,
    disease: Optional[str] = None,
    status: Optional[str] = None,
    min_cost: Optional[float] = None,
    max_cost: Optional[float] = None,
    sort_by: Optional[str] = None,
    order: Optional[str] = None,
    page: Optional[int] = 1,
    page_size: Optional[int] = 20,
) -> ListPetsOutput:
    """查询宠物档案列表。支持按种类/医生/状态/疾病筛选，支持关键词搜索、分页和排序。"""
    return await list_pets_handler(
        q=q, name=name, ownerName=ownerName, ownerPhone=ownerPhone,
        species=species, doctor=doctor, disease=disease, status=status,
        min_cost=min_cost, max_cost=max_cost, sort_by=sort_by, order=order,
        page=page, page_size=page_size,
    )

# === 启动 ===
if __name__ == "__main__":
    if MCP_TRANSPORT == "stdio":
        # Stdio 模式：用于 Claude Desktop 等本地客户端
        mcp.run(transport="stdio")
    else:
        # Streamable HTTP 模式：用于远程 MCP Client
        mcp.run(
            transport="streamable-http",
            host="0.0.0.0",
            port=MCP_PORT,
            path="/mcp",
        )
```

### 5.2 `pyproject.toml`

```toml
[project]
name = "pethospital-mcp"
version = "1.0.0"
description = "宠物医院管理系统 MCP Server (2026-07-28)"
requires-python = ">=3.10"
dependencies = [
    "mcp[cli]>=1.7.0",
    "httpx>=0.27",
    "pydantic>=2.0",
]

[build-system]
requires = ["setuptools>=68.0"]
build-backend = "setuptools.build_meta"
```

---

## 六、构建与部署

### 6.1 安装依赖

```bash
pip install -e .
# 或
pip install "mcp[cli]>=1.7.0" httpx pydantic
```

### 6.2 运行方式

```bash
# 方式一：Streamable HTTP（默认，端口 8081）
python main.py

# 方式二：指定端口
MCP_PORT=9090 python main.py

# 方式三：指定 pethospital REST API 地址
PETHOSPITAL_API_URL=http://127.0.0.1:8080 python main.py

# 方式四：Stdio 模式（用于 Claude Desktop）
MCP_TRANSPORT=stdio python main.py

# 方式五：同时指定所有环境变量
PETHOSPITAL_API_URL=http://127.0.0.1:8080 MCP_PORT=8081 MCP_TRANSPORT=streamable-http python main.py
```

### 6.3 Claude Desktop 配置

在 `claude_desktop_config.json` 中添加：

```json
{
  "mcpServers": {
    "pet-hospital": {
      "command": "python",
      "args": ["main.py"],
      "env": {
        "MCP_TRANSPORT": "stdio",
        "PETHOSPITAL_API_URL": "http://127.0.0.1:8080"
      }
    }
  }
}
```

### 6.4 opencode.json 配置

```json
{
  "$schema": "https://opencode.ai/config.json",
  "mcp": {
    "pet-hospital": {
      "type": "local",
      "command": ["python", "main.py"],
      "enabled": true,
      "environment": {
        "MCP_TRANSPORT": "stdio",
        "PETHOSPITAL_API_URL": "http://127.0.0.1:8080"
      }
    }
  }
}
```

---

## 七、测试验证清单

### 协议合规验证

1. ✅ `server/discover` 返回 `protocolVersion: "2026-07-28"` 和服务器能力
2. ✅ 响应包含 `_meta` 中的 `serverInfo`
3. ✅ `tools/list` 响应包含 `ttlMs` 和 `cacheScope`
4. ✅ 所有工具结果包含 `resultType: "complete"`
5. ✅ Streamable HTTP 请求携带 `MCP-Protocol-Version`、`Mcp-Method`、`Mcp-Name` 头
6. ✅ 不使用已弃用特性（initialize、ping、logging/setLevel、roots、sampling）

### 功能验证

1. ✅ `list_pets` 无参数返回全部宠物（分页）
2. ✅ `list_pets` 按 `species=犬` 筛选正确
3. ✅ `list_pets` 按 `doctor=李医生` 筛选正确
4. ✅ `list_pets` 按 `status=待就诊` 筛选正确
5. ✅ `list_pets` 按 `min`/`max` 花费区间筛选正确
6. ✅ `list_pets` `q=肠胃炎` 全文检索正确
7. ✅ `list_pets` `sortBy=totalCost&order=desc` 排序正确
8. ✅ `list_pets` `page`/`pageSize` 分页正确
9. ✅ 返回的 `total` 与实际数据条数一致
10. ✅ REST API 不可达时返回明确错误信息

---

## 八、注意事项

1. **无鉴权**：源项目无鉴权，MCP Server 也不应添加认证（仅本地使用）；如需安全，可通过 `--require-auth` 参数启用
2. **只读工具**：`list_pets` 标记为 `ReadOnlyHint`（Pydantic 模型所有字段为 Optional 即暗示只读）
3. **错误处理**：`httpx` 请求失败时返回明确的错误信息，SDK 会自动转为 JSON-RPC 错误码
4. **并发安全**：Python asyncio 天然支持并发，`httpx.AsyncClient` 确保非阻塞
5. **环境变量**：所有配置通过环境变量管理，便于不同部署环境切换
6. **不要使用已弃用特性**：不要实现 `initialize`、`logging/setLevel`、`notifications/roots/list_changed`、`ping`
7. **数据模型对齐**：`PetSummary` 字段名应与 REST API 返回的 JSON 字段名一致
8. **Python SDK 版本**：必须使用 `mcp >= 1.7.0`，早期版本不支持 `2026-07-28` 协议

---

## 九、参考文档

- MCP 2026-07-28 规范：https://modelcontextprotocol.io/specification/2026-07-28
- MCP Python SDK：https://github.com/modelcontextprotocol/python-sdk
- Python SDK 文档：https://modelcontextprotocol.io/docs/sdks/python
- 变更日志：https://modelcontextprotocol.io/specification/2026-07-28/changelog.md
- Pet Hospital REST API 文档：D:\xx\windows\README.md
- Go SDK 参考（实现逻辑相似）：https://github.com/modelcontextprotocol/go-sdk
