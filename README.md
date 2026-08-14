# mspbots-agent-mcp

MCP server for the **MSPbots Agent Platform capabilities API** — exposes the
Agent Platform's connector inventory to MCP clients.

It follows the same design as the sibling `ticketqa-mcp` service: stateless, no
stored credentials, per-request header authentication over the
[Model Context Protocol](https://modelcontextprotocol.io/) (Streamable HTTP/SSE
transport).

## Tools

| Tool | 功能 | 参数 |
|---|---|---|
| `mspbotsagent_get_connectors` | 列出当前租户的所有 connector，返回每个的名称、是否已安装、连接状态 | 无(凭证全部来自请求头) |

`mspbotsagent_get_connectors` returns one row per connector:

| Field | 说明 |
|---|---|
| `name` | Connector 显示名 |
| `integration` | Connector/integration key (如 `connectwise-command`) |
| `scope` | Connector 作用域 (如 `mspbots`) |
| `managed` | 管理方式 (如 `gateway`) |
| `installed` | 是否已安装/启用 (bool，来自 API 的 `enabled`) |
| `connected` | 当前是否已连接 (bool，来自 API 的 `connected`) |
| `status` | 派生状态：`not_installed` / `connected` / `installed_disconnected` |

> API 返回的每个 connector 还带一个很大的 base64 `logo` 字段——本服务会将其**剥离**，
> 以保持响应精简。

Backing endpoint: `GET /apps/mb-platform-agent/api/capabilities/connectors`, which
returns `{"success": true, "data": {"list": [ {connector}, ... ]}}`.

## Quick Start

### Docker (recommended)

```bash
docker compose up --build
```

The server starts on `http://localhost:8080`.

### Local (uv)

```bash
uv sync
python -m mspbots_agent_mcp
```

## Health Check

```bash
curl http://localhost:8080/health
# {"status": "ok", "service": "mspbots-agent-mcp", "transport": "http"}
```

No credentials are required for the health endpoint.

## 授权参数说明 (Authentication)

Every request to `/mcp` must include the following HTTP headers (provided by the
MCP caller — kept consistent with `ticketqa-mcp`):

| Header | 类型 | 是否必填 | 字段描述 | Example |
|---|---|---|---|---|
| `X-MSP-Token` | string | 必填 | Agent Platform 已签发的访问凭证 (JWT bearer token)。本服务原样转发为下游请求的 `Authorization: Bearer <token>`。 | `X-MSP-Token: <jwt-bearer-token>` |
| `X-MSP-Tenant-Id` | string | 必填 | 租户标识。转发给下游 API 时改名为 `X_Tenant_ID` header(租户也已内嵌在 JWT 中)。 | `X-MSP-Tenant-Id: <tenant-id>` |
| `X-MSP-Host` | string | 必填 | Agent API 所在的 host。本服务会拼接 `/apps/mb-platform-agent/api/capabilities/<endpoint>` 得到完整请求地址。 | `X-MSP-Host: https://agent.mspbots.ai` |

Missing any of the three headers returns `401 Unauthorized`.

## Environment Variables

| Variable | Default | Description |
|---|---|---|
| `MCP_HTTP_PORT` | `8080` | Listening port |
| `MCP_HTTP_HOST` | `0.0.0.0` | Listening host |

## MCP Endpoint

```
POST http://localhost:8080/mcp
```

Connect your MCP client with:
- Transport: `http` (Streamable HTTP / SSE)
- Headers: `X-MSP-Token`, `X-MSP-Tenant-Id`, `X-MSP-Host` (all required)

## 测试示例 (Test Example)

```bash
curl -X POST http://localhost:8080/mcp \
  -H "Content-Type: application/json" \
  -H "Accept: application/json, text/event-stream" \
  -H "X-MSP-Token: <token>" \
  -H "X-MSP-Tenant-Id: <tenant-id>" \
  -H "X-MSP-Host: https://agent.mspbots.ai" \
  -d '{
    "jsonrpc": "2.0",
    "id": 1,
    "method": "tools/call",
    "params": { "name": "mspbotsagent_get_connectors", "arguments": {} }
  }'
```

> ⚠️ 本仓库为公开仓库，请勿在任何提交的文件中写入真实的 token / tenant id 等敏感信息，
> 上面的 `<token>` / `<tenant-id>` 仅为占位符。
