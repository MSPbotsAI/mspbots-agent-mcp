# mspbots-agent-mcp

MCP server for the **MSPbots Agent Platform API** — exposes the Agent Platform's
connector inventory, agent triggers (scheduled/event tasks), and per-agent policy
(permissions, self-evaluation, human-in-the-loop approval) to MCP clients.

It follows the same design as the sibling `ticketqa-mcp` service: stateless, no
stored credentials, per-request header authentication over the
[Model Context Protocol](https://modelcontextprotocol.io/) (Streamable HTTP/SSE
transport).

## Tools

所有工具的凭证均来自请求头（`X-MSP-Token` / `X-MSP-Tenant-Id` / `X-MSP-Host`），
工具参数里不需要传 token。

### Connectors

| Tool | 功能 | 参数 |
|---|---|---|
| `mspbotsagent_get_connectors` | 列出当前租户的所有 connector，返回每个的名称、是否已安装、连接状态 | 无 |

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

### Triggers (agent scheduled / event tasks)

一个 trigger 会自动触发 agent 运行：按 cron 定时（`recurring`）或在外部集成事件发生时（`event`）。
主键 `taskId`，归属于某个 `agentId`。

| Tool | 功能 | 参数 |
|---|---|---|
| `mspbotsagent_list_triggers` | 列出某 agent 的全部 trigger（分页） | `agent_id`(必填)、`page`(默认 1)、`page_size`(默认 50) |
| `mspbotsagent_upsert_trigger` | 新建或修改一个 trigger（带 `task_id`=改，不带=建） | `agent_id`、`task_id`、`name`、`prompt`、`type`(`recurring`/`event`)、`enabled`、`expires_in_days`；recurring: `schedule`(cron,最小 1h)、`timezone`、`run`；event: `trigger_integration`、`trigger_events` |
| `mspbotsagent_delete_trigger` | 删除一个 trigger（不可撤销） | `task_id`(必填) |
| `mspbotsagent_get_trigger_catalog` | 列出 event 触发器合法的 integration + events 组合 | 无 |
| `mspbotsagent_run_trigger` | 立即手动运行一次某 trigger（用于测试/补跑） | `task_id`(必填) |

> `upsert` 新建时需 `agent_id`/`name`/`prompt`/`type`；`recurring` 需 `schedule`（cron 最小间隔 1h），
> `event` 需 `trigger_integration`+`trigger_events`，且组合须在 `get_trigger_catalog` 目录内。修改时只提交要改的字段。
>
> Backing endpoints: `GET|POST /api/tasks`, `PUT|DELETE /api/tasks/:taskId`,
> `GET /api/tasks/trigger-catalog`, `POST /api/tasks/:taskId/run`.

### Agent policy (permissions / evaluation / approval)

以下三块配置都挂在**同一条 agent 记录**上：读共用一个 GET，写共用一条 **partial** PUT。
因此**不要对同一 agent 并发写**（partial patch 会互相覆盖）；当读到 `policyError=true` 时，
upsert 工具会**拒绝回写**以避免持久化坏策略。主键均为 `agentId`。

| Tool | 功能 | 参数 |
|---|---|---|
| `mspbotsagent_get_agent_permissions` | 读取权限配置：`permission` / `interruptOn` / `tools`(只读) / `policyError` | `agent_id`(必填) |
| `mspbotsagent_upsert_agent_permissions` | 更新工具权限与打断设置（partial） | `agent_id`(必填)、`permission`(tool→`allow`/`ask`/`deny`)、`interrupt_on`(tool→`true` 或 `{allowed_decisions, description}`)，二者至少一个 |
| `mspbotsagent_get_agent_evaluation` | 读取自评配置 `review = {rules, max_iterations}` | `agent_id`(必填) |
| `mspbotsagent_upsert_agent_evaluation` | 设置/更新自评规则（`rules` 传空数组=关闭自评） | `agent_id`(必填)、`rules`(规则数组)、`max_iterations` |
| `mspbotsagent_get_agent_approval` | 读取人工审批规则 `approval`(数组) | `agent_id`(必填) |
| `mspbotsagent_upsert_agent_approval` | 设置/更新人工审批规则（空数组=移除全部审批门） | `agent_id`(必填)、`rules`(审批规则数组) |

规则对象结构：

- evaluation `rules[]`：`{ rubric, name, description, triggers: [正则/关键词] }`
- approval `rules[]`：`{ name, intent, triggers: [正则/关键词], tools: [...], decisions: [...] }`

> Backing endpoints: `GET /api/agents/:id`（三个 get 共用），`PUT /api/agents/:id`（三个 upsert 共用，
> partial：分别写 `permission`/`interruptOn`、`review`、`approval`）。

### Agent SOP author

一个 agent 的 SOP（标准作业流程）草稿，含 5 个独立字段，每个字段各有读/写两个工具。
写入统一为 `PUT {"value": ...}`。主键 `agentId`。

| Tool | 功能 | 参数 |
|---|---|---|
| `mspbotsagent_get_sop_name` | 读取 SOP 名称 | `agent_id`(必填) |
| `mspbotsagent_set_sop_name` | 设置 SOP 名称（非空、≤60 字符、租户内唯一、不可清空） | `agent_id`(必填)、`value`(必填) |
| `mspbotsagent_get_sop_source` | 读取 source（撰写 SOP 所依据的原始任务描述） | `agent_id`(必填) |
| `mspbotsagent_set_sop_source` | 设置 source（传 null 清空） | `agent_id`(必填)、`value`(必填，字符串或 null) |
| `mspbotsagent_get_sop_purpose` | 读取 purpose（markdown） | `agent_id`(必填) |
| `mspbotsagent_set_sop_purpose` | 设置 purpose（markdown） | `agent_id`(必填)、`value`(必填) |
| `mspbotsagent_get_sop_data_sources` | 读取 dataSources list（结构化对象） | `agent_id`(必填) |
| `mspbotsagent_set_sop_data_sources` | 设置 dataSources list（结构化对象） | `agent_id`(必填)、`value`(必填，对象) |
| `mspbotsagent_get_sop_procedure` | 读取 procedure（markdown） | `agent_id`(必填) |
| `mspbotsagent_set_sop_procedure` | 设置 procedure（markdown） | `agent_id`(必填)、`value`(必填) |

dataSources `value` 结构：

```json
{
  "sources": [
    { "name": "Open-Meteo API", "object": "current weather", "connector": "http",
      "role": "ssot", "usedBy": "s6", "connected": false, "assumed": true }
  ],
  "preconditions": ["The runtime can reach api.open-meteo.com."]
}
```

> Backing endpoints: `GET|PUT /api/agents/:id/sop-author/{name,source,purpose,data-sources-list,procedure}`。

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
| `X-MSP-Host` | string | 必填 | Agent API 所在的 host。

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
