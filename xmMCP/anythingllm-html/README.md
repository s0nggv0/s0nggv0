# AnythingLLM 工作台（anythingllm-html）

单文件网页 `upload.html`，基于 AnythingLLM 本地 API，用于向工作区上传文档并自动向量化。无需安装依赖、无需启动任何服务，浏览器打开即可使用。

## 使用

1. 确保 AnythingLLM 已在本机运行（默认 `http://localhost:3001`）
2. 双击或在浏览器打开 `upload.html`
3. 选择工作区 → 选择文件 → 点击「上传并向量化」

## 功能

| 区域 | 功能 |
| --- | --- |
| 工作区 | 下拉选择、刷新、新建、删除当前工作区 |
| 上传 | 选择本地文件上传到当前工作区并自动向量化（`POST /api/v1/document/upload`），随后轮询等待嵌入完成 |
| 文档列表 | 展示当前工作区的文档（按文件夹分组） |
| 日志 | 实时输出请求与结果，便于排查问题 |

## 配置

页面脚本顶部有两个常量：

| 常量 | 默认值 | 说明 |
| --- | --- | --- |
| `API` | `http://localhost:3001/api` | AnythingLLM 本地 API 地址 |
| `KEY` | AnythingLLM Developer API key | 请求鉴权用 |

修改这两个常量即可对接其他 AnythingLLM 实例。

> **安全提示**：当前 `upload.html` 中的 key 是明文写死的。如果该文件会进入公开仓库，请先重置该 key，并改为运行时输入或从配置读取，避免泄露。

## 相关目录

- `../anythingllm-mcp/`：AnythingLLM MCP 服务，其中带有一份内容相同的 `upload.html`