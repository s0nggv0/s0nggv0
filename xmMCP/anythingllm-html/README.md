# AnythingLLM 工作台（anythingllm-html）

单文件网页 `upload.html`，基于 AnythingLLM 本地 API，用于向工作区上传文档并自动向量化。无需安装依赖、无需启动任何服务，浏览器打开即可使用。

## 使用

1. 确保 AnythingLLM 已在本机运行（默认 `http://localhost:3001`）
2. 双击或在浏览器打开 `upload.html`
3. 填写 API 地址与 API Key，点击「保存并连接」
4. 选择工作区 → 选择文件 → 点击「上传并向量化」

## 功能

| 区域 | 功能 |
| --- | --- |
| 工作区 | 下拉选择、刷新、新建、删除当前工作区 |
| 上传 | 选择本地文件上传到当前工作区并自动向量化（`POST /api/v1/document/upload`），随后轮询等待嵌入完成 |
| 文档列表 | 展示当前工作区的文档（按文件夹分组） |
| 日志 | 实时输出请求与结果，便于排查问题 |

## 配置

页面顶部提供「API 地址」与「API Key」两个输入框，填写后点击「保存并连接」即可生效：

| 字段 | 默认值 | 说明 |
| --- | --- | --- |
| API 地址 | `http://localhost:3001/api` | AnythingLLM 本地 API 地址 |
| API Key | 空 | AnythingLLM Developer API key，请求鉴权用 |

- 点击「保存并连接」后配置写入浏览器 `localStorage`，下次打开自动带出。
- 未填写 Key 时页面不会发起请求，日志会提示先连接。
- 修改地址或 Key 后重新点击「保存并连接」即可切换实例。

> **安全提示**：Key 仅保存在本地浏览器，不在代码中明文写死；请勿将其提交到仓库或分享页面配置。

## 相关目录

- `../anythingllm-mcp/`：AnythingLLM MCP 服务，其中带有一份内容相同的 `upload.html`