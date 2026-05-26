# Codex Responses API 代理服务

***

## 背景

Codex CLI 0.81.0+ 版本要求使用 OpenAI 新推出的 **Responses API** (`/v1/responses`)，但大多数第三方 API 中转服务和自建大模型服务仅支持标准的 **Chat Completions API** (`/v1/chat/completions`)。本代理服务填补了这一兼容性缺口，让 Codex 能够与 OpenAI 兼容的 API 正常协作。

## 功能特性

* **API 格式转换** — 将 `/v1/responses` 请求转换为 `/v1/chat/completions`

* **流式响应支持** — 完整支持 SSE（Server-Sent Events）流式传输

* **消息格式转换**

  * `role: "developer"` → `role: "system"`

  * 内容数组格式转换为纯文本

* **模型回退机制** — 自动将不支持的模型替换为默认模型

* **参数过滤** — 移除可能导致错误的复杂参数（tools、tool_choice 等）

## 快速开始

### 环境要求

* Python 3.8+

* pip

### 安装步骤

```bash
# 克隆仓库
git clone https://github.com/hunterwuhao/response_proxy.git
cd codex-responses-proxy

# 安装依赖
pip install flask requests
```

### 配置

1. **编辑 `response_proxy.py`**，修改后端设置：

```python
BACKEND_URL = "https://your-api-endpoint/v1"  # 您的 OpenAI 兼容 API 地址
API_KEY = "your-api-key-here"                  # 您的 API Key
DEFAULT_MODEL = "your-default-model"           # 默认使用的模型
SUPPORTED_MODELS = ["model-1", "model-2"]      # 无需替换的模型列表
```

2. **配置 Codex**（`~/.codex/settings.toml`）：

```toml
model_provider = "custom"
model = "your-model-name"
wire_api = "responses"

[model_providers.custom]
name = "CustomAPI"
base_url = "http://localhost:8080/v1"
requires_openai_auth = false
```

### 运行

```bash
python response_proxy.py
```

代理服务将在 `http://localhost:8080` 启动。

## 配置详解

### 后端设置

| 变量                 | 说明                                          |
| ------------------ | ------------------------------------------- |
| `BACKEND_URL`      | OpenAI 兼容的 API 端点地址（不含 `/chat/completions`） |
| `API_KEY`          | 用于认证的 API Key                               |
| `DEFAULT_MODEL`    | 当请求的模型不在支持列表时使用的默认模型                        |
| `SUPPORTED_MODELS` | 支持的模型列表，这些模型不会被替换                           |

### Codex 设置

| 设置项                    | 值                            | 说明                           |
| ---------------------- | ---------------------------- | ---------------------------- |
| `wire_api`             | `"responses"`                | 告知 Codex 使用 Responses API 格式 |
| `base_url`             | `"http://localhost:8080/v1"` | 指向代理服务地址                     |
| `requires_openai_auth` | `false`                      | 禁用 OpenAI 认证                 |

## API 转换详解

### 请求格式转换

**Responses API（输入）：**

```json
{
  "model": "gpt-4o",
  "input": [
    {"type": "message", "role": "developer", "content": [{"type": "input_text", "text": "You are helpful."}]},
    {"role": "user", "content": "Hello"}
  ],
  "stream": true,
  "tools": [...],
  "tool_choice": "auto"
}
```

**Chat Completions API（输出）：**

```json
{
  "model": "your-model-name",
  "messages": [
    {"role": "system", "content": "You are helpful."},
    {"role": "user", "content": "Hello"}
  ],
  "stream": true
}
```

### 流式响应转换

**Chat Completions SSE：**

```
data: {"choices": [{"delta": {"content": "Hello"}}]}
data: [DONE]
```

**Responses API SSE：**

```
event: response.created
data: {"type": "response.created", ...}

event: response.output_item.added
data: {"type": "response.output_item.added", ...}

event: response.output_text.delta
data: {"type": "response.output_text.delta", "delta": "Hello", ...}

event: response.completed
data: {"type": "response.completed", ...}
```

### 事件类型说明

| 事件                           | 说明     |
| ---------------------------- | ------ |
| `response.created`           | 响应开始创建 |
| `response.output_item.added` | 输出项已添加 |
| `response.output_text.delta` | 文本增量   |
| `response.output_text.done`  | 文本输出完成 |
| `response.output_item.done`  | 输出项完成  |
| `response.completed`         | 响应完成   |

## 测试

### 非流式请求

```bash
curl -X POST "http://localhost:8080/v1/responses" \
  -H "Content-Type: application/json" \
  -d '{"model": "test-model", "input": "你好"}'
```

### 流式请求

```bash
curl -X POST "http://localhost:8080/v1/responses" \
  -H "Content-Type: application/json" \
  -d '{"model": "test-model", "input": "你好", "stream": true}'
```

### 健康检查

```bash
curl http://localhost:8080/health
```

## 常见问题

### Codex 无响应

* 确认代理服务正在运行（访问 `http://localhost:8080/health`）

* 检查 Codex 配置中的 `base_url` 是否正确指向代理地址

* 查看代理控制台日志排查错误

### API Key 错误

* 确认 `response_proxy.py` 中的 `API_KEY` 填写正确

* 检查 API Key 是否有足够的配额

### 模型不存在

* 确认 `DEFAULT_MODEL` 与后端支持的模型匹配

* 将后端支持的模型添加到 `SUPPORTED_MODELS` 列表

### 流式响应中断

* 检查代理日志中的 `Backend stream status` 是否为 200

* 查看是否有错误信息或连接问题

## 限制说明

1. **不支持工具调用** — `tools` 和 `tool_choice` 参数已被移除，Codex 的工具调用功能不可用

2. **开发服务器** — 使用 Flask 开发服务器，不建议用于生产环境

3. **单一后端** — 仅支持配置一个后端 API 端点

## 项目结构

```
codex-responses-proxy/
├── response_proxy.py    # 代理服务主程序
├── config.toml          # Codex 配置示例
├── auth.json            # 认证配置示例
└── README.md            # 说明文档
```

## 安全提示

**请勿将 API Key 提交到公开仓库！** 建议将以下文件添加到 `.gitignore`：

```
auth.json
*.toml
```

## 贡献

欢迎贡献！您可以：

1. 提交 Issue 报告问题或建议新功能

2. 提交 Pull Request 改进代码

3. 分享您的使用场景和配置经验

## 许可证

MIT License — 自由使用和修改。

***

