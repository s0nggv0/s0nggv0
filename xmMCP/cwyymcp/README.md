# cwyymcp · 宠物医院（Windows 发行包）

「宠物医院管理系统」的 Windows 发行目录，一个文件夹里包含后端 REST API、网页操作界面和数据文件，外加把 REST API 封装成 MCP 工具的 Python 服务。

## 目录结构

```text
cwyymcp/
├── windows/
│   ├── pethospital.exe       后端程序（64 位 Windows，已内嵌网页界面，未纳入版本控制）
│   ├── main.py               MCP Server（Python）
│   ├── pyproject.toml        MCP Server 依赖配置
│   ├── README.md             后端完整文档（接口、模拟数据、构建与发布）
│   ├── README-Windows.md     Windows 运行说明
│   ├── MCP-SERVER-DESIGN.md  MCP Server 设计规格
│   ├── LICENSE               MIT 许可证
│   └── data/pet.db           单文件数据库（未纳入版本控制）
└── .gitignore
```

## 组成

| 部分 | 说明 |
| --- | --- |
| `pethospital.exe` | Go 标准库编写的宠物医院 REST API，内嵌网页操作界面，监听 `127.0.0.1:8080`，数据存于单文件 `data/pet.db`，零第三方依赖 |
| `main.py` | 把 REST API 封装为 MCP 工具（MCP `2026-07-28`，Streamable HTTP），监听 `127.0.0.1:8081`，启动时自动检测并拉起 `pethospital.exe` |

## 快速开始

```bat
:: 1) 启动后端（浏览器打开 http://127.0.0.1:8080/ 即为操作界面）
windows\pethospital.exe

:: 2) 启动 MCP Server
cd windows
python -m venv .venv
.venv\Scripts\pip.exe install -e .
.venv\Scripts\python.exe main.py
```

网页界面（HTML/CSS/JS）已编译进 exe，不需要额外的网页文件；`data/pet.db` 与 macOS / Linux 版完全通用，可直接互相拷贝。

## 与 xmMCP/pethospital-mcp 的关系

两者是同一套 MCP Server 的不同分发目录：`pethospital-mcp/` 是开发目录，`cwyymcp/windows/` 是 Windows 成品目录（`pyproject.toml` 中项目名同为 `pethospital-mcp`）。

## 文档

- `windows/README.md`：后端完整文档（29 个 REST 接口、模拟数据生成、数据库格式、构建发布）
- `windows/README-Windows.md`：Windows 运行说明与常见问题
- `windows/MCP-SERVER-DESIGN.md`：MCP Server 设计规格

## 安全提示

程序无登录、无鉴权，仅监听本机地址，请勿直接暴露到公网。数据全部在 `data/pet.db` 单个文件里，复制该文件即可完成备份。