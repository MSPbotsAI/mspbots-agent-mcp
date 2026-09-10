# mspbots-agent-mcp

MCP server for the **MSPbots Agent Platform API** — exposes the Agent Platform's
connector inventory, agent triggers (scheduled/event tasks), and per-agent policy
(permissions, self-evaluation, human-in-the-loop approval) to MCP clients.

It follows the same design as the sibling `ticketqa-mcp` service: stateless, no
stored credentials, per-request header authentication over the
[Model Context Protocol](https://modelcontextprotocol.io/) (Streamable HTTP/SSE
transport).

## When would you use this

This MCP is meta: it doesn't wrap a customer-facing integration, it wraps the
Agent Platform's own admin/config API for an agent. The "users" are platform
admins/builders setting up an agent, or an agent introspecting/adjusting its
own configuration:

- "What connectors does this tenant have hooked up, and which are actually
  connected right now?" → `mspbotsagent_get_connectors`
- "What connectors can *this agent* use / what does it pull data from?" →
  `mspbotsagent_get_sop_data_sources` (agent-scoped — not
  `mspbotsagent_get_connectors`, which is tenant-wide)
- "Make this agent run every Monday morning to summarize open tickets" →
  `mspbotsagent_upsert_trigger` (type `recurring`)
- "Kick this agent off automatically whenever a new ConnectWise ticket comes
  in" → `mspbotsagent_upsert_trigger` (type `event`, after checking
  `mspbotsagent_get_trigger_catalog`)
- "Lock down what this agent is allowed to do without asking first" →
  `mspbotsagent_upsert_agent_permissions`
- "Require a human to sign off before this agent issues a refund" →
  `mspbotsagent_upsert_agent_approval`
- "Write up this agent's SOP so it has a documented, repeatable procedure" →
  `mspbotsagent_set_sop_purpose` / `mspbotsagent_set_sop_procedure` / the
  other `mspbotsagent_set_sop_*` tools
- "Give this agent a private skill for X" / "What skills does this agent
  already have?" → `mspbotsagent_create_agent_skill` /
  `mspbotsagent_list_agent_skills`
- "What SOPs does this tenant have / which are still drafts?" →
  `mspbotsagent_list_sops`
- "Ask the onboarding SOP what it would do with this ticket" →
  `mspbotsagent_chat_with_sop` (one blocking turn with that SOP's own agent)

## Tools

所有工具的凭证均来自请求头（`X-MSP-Token` / `X-MSP-Tenant-Id` / `X-MSP-Host`），
工具参数里不需要传 token。

### Connectors

| Tool | 功能 | 参数 |
|---|---|---|
| `mspbotsagent_get_connectors` | 列出当前租户的所有 connector，返回每个的名称、是否已安装、连接状态 | 无 |

`mspbotsagent_get_connectors` is **tenant-scoped**: it takes no `agent_id` and
returns the same inventory regardless of which agent is being configured. For
the connectors a *specific* agent is declared to use, see
[`mspbotsagent_get_sop_data_sources`](#agent-sop-author) instead.

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
upsert 工具会**拒绝回写 `permission`/`interruptOn`**（owners-only 更新不受影响）以避免持久化坏策略。主键均为 `agentId`。

| Tool | 功能 | 参数 |
|---|---|---|
| `mspbotsagent_get_agent_permissions` | 读取权限配置：`permission` / `interruptOn` / `owners` / `tools`(只读) / `policyError` | `agent_id`(必填) |
| `mspbotsagent_upsert_agent_permissions` | 更新工具权限、打断设置与归属（partial，三个 key 独立，可只发 owners） | `agent_id`(必填)、`permission`(tool→`allow`/`ask`/`deny`)、`interrupt_on`(tool→`true` 或 `{allowed_decisions, description}`)、`owners`(`[{userId, name, email}]`)，三者至少一个 |
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

一个 agent 的 SOP（标准作业流程）草稿，含 5 个独立字段，每个字段各有读/写两个工具，
各字段写入走各自独立的 endpoint（不像上面的 permission/evaluation/approval 三者共用同一个
`PUT /api/agents/:id`）。写入统一为 `PUT {"value": ...}`。主键 `agentId`。

> 尽管每个字段的 endpoint 不同，这 5 个字段仍然挂在**同一条 agent 记录**（`sopAuthor`
> 子文档）上，因此和上面的 permission/evaluation/approval 一样：**不要对同一 agent 的
> SOP 字段并发写**，否则可能互相覆盖。SOP 本身是一份文档/规划性质的草稿，用于描述 agent
> "应该怎么做"；而上面的 permission/evaluation/approval 是运行时真正生效的行为策略，
> 决定 agent "实际能做什么"——两者是互补但不同的两类配置。

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

dataSources `value` 结构（每个 source 只存 `integration`，无 `preconditions`）：

```json
{
  "sources": [
    { "integration": "open-meteo" },
    { "integration": "ms-graph" }
  ]
}
```

`mspbotsagent_get_sop_data_sources` 读回来的每个 entry 就是一个 connector
（一个 agent 可用的 MCP server），除了 `integration` 还带连接状态和工具清单：

| 字段 | 类型 | 含义 |
|---|---|---|
| `integration` | string | 数据源 key |
| `org` | bool，可选 | 该 source 是在组织级添加的时候才有 |
| `found` | bool | `false` = 引用的 connector 已被删除或禁用，不可用，当不存在处理 |
| `name` / `description` / `transport` / `endpoint` | string | connector 展示信息及其 MCP endpoint（`found` 时才有） |
| `connection` | string | 当前连接状态，见下表。**agent 级优先于 org 级** |
| `tenantConnected` | bool | 组织 / 租户级连接是否存在 |
| `enabled` | bool | 该 connector 在组织层面是否启用 |
| `managed` | string，可选 | 网关托管的 connector 为 `"gateway"` |
| `tools` | array | 该 connector 提供的工具（`{name, label, description}`）；未连接或 discovery 失败时为空 |

`connection` 取值：

| 值 | 含义 | 该怎么对待 |
|---|---|---|
| `"agent"` | 该 agent 用自己的账号连上了（agent 级连接） | 可用 |
| `"org"` | 用的是组织 / 租户级的连接 | 可用 |
| `"none"` | 未连接（或该连接器被组织禁用） | 不可用，需要用户先去连接 |
| `"unavailable"` | 网关状态读不到 | ⚠️ **不代表已断开**，只是此刻查不到。不要据此判定"未连接" |

两条容易错的地方，已写进工具 description：

- `connection` 是单值且 agent 优先。**两级同时连上时 `connection` 只显示 `"agent"`**，
  租户那份要看 `tenantConnected`。目前没有对称的独立 `agentConnected` 布尔字段，
  agent 级只能靠 `connection === "agent"` 判断。
- `"none"` 与 `"unavailable"` 必须区别对待：前者是真没连（可提示用户去连），
  后者只是状态读不到（倾向按仍可用处理，别误报）。

汇总判断：能用 = `found === true` 且 `connection ∈ {agent, org}`（`unavailable` 倒向可用）；
不能用 = `found === false` 或 `connection === "none"`。

> `mspbotsagent_get_sop_data_sources` is the **agent-scoped** answer to
> "what connectors does this agent use", and its rows carry connection
> status, so it usually answers "can this agent use X" on its own.
> [`mspbotsagent_get_connectors`](#connectors) is the tenant-wide inventory
> — reach for it when the question is not about a particular agent.

> Backing endpoints: `GET|PUT /api/agents/:id/sop-author/{name,source,purpose,data-sources-list,procedure}`。

### Agent skills

一个 agent 可用的 skill 分三类：`mspbots`(平台内置)、`org`(组织共享)、`agent`(该 agent 私有)。
只有私有(`agent`)skill 能在这里创建/编辑/删除；`mspbots`/`org` skill 只能读、不能改。
主键为 `capabilityId`（列表接口里每条记录的 `id`）。

| Tool | 功能 | 参数 |
|---|---|---|
| `mspbotsagent_list_agent_skills` | 列出某 agent 可用的全部 skill(org 共享 + 该 agent 私有 + 平台 mspbots)及勾选状态 | `agent_id`(必填) |
| `mspbotsagent_create_agent_skill` | 为某 agent 新建一个私有 skill(scope=agent)，发布为 npm 版本并装入该 agent 工作区 | `agent_id`(必填)、`name`(必填)、`files`(必填，需含一个 `SKILL.md`) |
| `mspbotsagent_update_agent_skill_files` | 编辑某 agent 私有 skill 的文件并发布新版本(整包替换)。仅限该 agent 拥有的私有 skill | `agent_id`(必填)、`capability_id`(必填)、`files`(必填，完整文件集)、`note`(可选，缺省 "Edit") |
| `mspbotsagent_delete_agent_skill` | 删除某 agent 的私有 skill：软删 capability + 清 opt-out 行 + 从工作区卸载 | `agent_id`(必填)、`capability_id`(必填) |

`mspbotsagent_list_agent_skills` 返回每个 skill 的 `id`/`type`(`mspbots`|`org`|`agent`)/`ref`/`scope`/`name`/`skillName`/`description`/`version`/`enabled`/`selected`(未 opt-out 即 `true`)/`available`，以及一份 `selectedIds` 列表。

> ⚠️ **`files` 里每个元素("SkillFile")的具体字段结构，接手时给的 API 规格里只写了 `"$ref": "#/definitions/SkillFile"`，没有附上这个 definitions 块。**
> 本实现假设是 `{"path": "<相对路径，如 'SKILL.md'>", "content": "<原始文本内容>"}` ——参照通用的 SKILL.md 打包约定推断，**未经真实 API 验证**，接入前请与后端确认实际字段名（是否还有 `encoding`/`executable` 等）。
>
> Backing endpoints: `GET /api/agents/:id/skills`, `POST /api/agents/:id/skills/create`,
> `PUT /api/agents/:id/skills/:capabilityId/files`, `DELETE /api/agents/:id/skills`
> (最后一个的请求体是 `{"id": "<capabilityId>"}` —— DELETE 带 body 在 HTTP 里少见，
> 本服务走 httpx 的底层 `request()` 而非 `delete()` 来发这个请求)。

### SOP library (list + synchronous chat)

一个 **SOP**（标准作业流程）是租户级记录，创建时会为它开一个**专属 agent**；
`mspbotsagent_chat_with_sop` 对话的就是这个 agent，所以它只收 `sop_id`、不收 `agent_id`。
这与上面的 [Agent SOP author](#agent-sop-author) 是两件事：那组工具编辑挂在 agent 上的
**SOP 草稿分节**，这组读的是 **SOP 库**并真正跑一轮对话。

| Tool | 功能 | 参数 |
|---|---|---|
| `mspbotsagent_list_sops` | 分页列出租户的 SOP，返回每条的状态与所属 agent | `search`(按名称模糊匹配，不搜正文)、`status`(`draft`/`published`)、`page`(默认 1)、`page_size`(默认 20，上限 100) |
| `mspbotsagent_chat_with_sop` | 与某 SOP 的 agent 进行**一轮同步对话**：阻塞等待整轮跑完后返回回复 | `sop_id`(必填)、`message`(必填)、`thread_id`(续同一会话)、`new_thread`(另起新会话) |

`mspbotsagent_list_sops` 每行返回
`id`/`name`/`description`/`status`/`source`/`tags`/`agentId`/`agentLive`/`updatedAt`。
`agentLive` 为 `false` 表示那个 agent 记录已不存在——SOP 仍可读，但无法对话，
两个工具的任何参数都救不回来。

**「用户用自己的话点名一个 SOP」怎么落到 `sop_id`：**
后端的 `search` 只做 `name ILIKE '%…%'`（`service/sop/db.ts:88`）——不匹配 description / tags / body，
也没有模糊、同义词或跨语言匹配。**所以搜不到不等于不存在**，多半只是措辞不同（用户说「退款那个」，
SOP 叫 `Refund Handling`）。把用户原话直接丢进 `search` 拿到 0 行，然后回答「没有这个 SOP」，
是这条链路上最贵的一种错。正确姿势是**不传 `search`**，读每行的 `name` + `description` 自己挑，
用 `total` 判断要不要翻页；`search` 只用于你已经确知的名字片段。
这段指引写在 `search` 参数的描述里（参数描述不计入 500 字符上限），并由
`tests/test_sops.py` 的 `test_search_param_warns_that_a_miss_is_not_an_absence` 守住。

**只有 `agent_id` 时**：`list_sops` 每行都带 `agentId`，列出来按它匹配即可拿到 `sop_id`；
`mspbotsagent_get_usage_overview` 的行里也同时有 `sopId` 和 `agentId`。不要去解析 agent 名字——
虽然 SOP agent 建出来叫 `${sop.name} #${sop.id}` 且改名会同步，但 `PUT /api/agents/:id` 允许
用户直接改 name，改完即脱钩，且普通 agent 也能起同名。

`mspbotsagent_chat_with_sop` 返回
`sopId`/`sopName`/`agentId`/`threadId`/`status`/`reply`，其中 `status` 解释空回复：

| `status` | 含义 |
|---|---|
| `completed` | 正常跑完，`reply` 是本轮最后一条对用户可见的 assistant 消息 |
| `interrupted` | 命中人工审批门而暂停，附 `pausedActions`；需有人在 Agent Platform 里裁决后才会继续 |
| `no_reply` | 跑完但没产出 assistant 消息 |

`reply` 的取法对齐前端 `components/assistant-ui/aegra/messages.ts` 的 `lastAssistantText`：
从后往前找 `type=ai`/`role=assistant` 的消息，并跳过 UI 隐藏的内部消息
（`rubric_grader`、`sop_context`、`sop_suffix`、`compact_summary`、`task_notification`）。

> ⚠️ **这一路调用与其它工具有两点不同，改动时别退回默认值：**
> 1. 它**关掉了重试**（`retries=0`）。跑 agent 的请求不是幂等的——重发丢失的响应会**再跑一遍 agent**，
>    而不是把第一次的结果捞回来。
> 2. 它把读超时放宽到 **300s**（默认 30s 撑不住一轮真实的 agent 运行；Aegra 自己的兜底是 1 小时）。
>    超时返回的错误里 `retryable=false`，并明确提示「不要重发，改用同一会话再问一次」。
>
> Backing endpoints: `GET /api/sops`（分页时返回 `{list, total}`）、`GET /api/sops/:id`（取 `agent_id`）、
> `POST /api/agents/:id/run/wait`。最后一个**用 HTTP 200 + `{"success": false}` 表示跑失败**，
> 不会走 4xx/5xx，所以本工具显式检查 `success` 字段，避免把失败读成「成功但没说话」。

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
# {"status": "ok"}
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
