# 模块：MCP 工具层（`src/mspbots_agent_mcp/tools/`）

累积事实。每条带 `path:line` + 读取时的 commit sha，**读的时候要核对那一行是否还在、内容是否还对**，
对不上就当「未覆盖」处理并在汇报里点名，不许照抄。

## 加一个新工具时，这四条会咬人（PRD-18216 实做后记，@ e45ded6）

1. **工具输出已经不再有通用上限，不会再被截断。**
   旧行为：`_json.MAX_CHARS = 20_000`，`dump_json_capped` 超限时截最大的 list 字段；而一个**没有 list
   可截**的 payload 会落到兵库分支——整个结果被扔掉，只返回
   `{"truncated":true,"note":"Result too large (26085 chars) ... narrow your query."}`。
   调用方拿到的是**零数据**，而且很多工具根本没有可以 narrow 的参数。已删除（2026-09-08）：
   `_json.py` 只剩 `_compact` / `dump_json`（原 `dump_json_capped`，33 个调用点已同步改名）/
   `error_envelope`，**不再有 MAX_CHARS、不再有任何截断**。剩下的兼容安全网是 MCP 客户端自己的
   上限，它**保留开头**而不是丢弃全部。
   **推论不变：返回大列表的工具仍然要自己截并显式标注**，只是现在是为了模型读得动，
   不再是为了过通用 capper。实测量级（2026-09-03，真实租户）：usage 概览的 `breakdownTotal`
   是 **453**，`pageSize=1000` 时完整输出远超 20000 字符。做法见 `tools/usage.py` 的 `_shape_overview`：
   二分找最大可容纳行数，预算是它**自己的** `_BREAKDOWN_BUDGET = 20_000`（不再是共享的
   `MAX_CHARS`），且**用同一个序列化器度量**（所以它 import 了 `_json._compact`）。
   这是目前全仓**唯一**一处输出被限制的地方，且只限 `breakdown`。

2. **工具 description 有硬断言，别用豁免表绕过。**
   `tests/test_tools.py:126` 断言 ≤ **500** 字符，`:128` 断言首行 ≤ **100** 字符，
   `:111-112` 断言不得出现 `API:` / `GET /` / `POST /`（防泄实现细节）。
   豁免表 `_LONG_DESCRIPTION_EXCEPTIONS` 现在是 **7 个**（原 6 个历史工具 +
   `mspbotsagent_get_sop_data_sources`，2026-09-08 加入：它要写 `connection` 的四个取值，
   其中 `"unavailable"` 不等于断开、以及 agent 优先导致租户那份只能看 `tenantConnected`，
   两条都是会造成误报的坑；完整字段表（含 `tools` / `enabled` / `managed` 等，
   由产品提供）写完后 description 是 2009 字符）。
   **新工具仍然不要往里加**：那张表是欠账不是许可，加之前先在旁边写清理由。
   PRD-18216 第一版 docstring 是 557 字符，压到 483 才过。

3. **三件事 `api_client` 已经统一做了，工具里不要重做。**
   挂载前缀：`api_client.py:13` 的 `_APP_PREFIX = "/apps/mb-platform-agent"`，`:83` 拼进 `_base_url` ——
   工具里只写 `/api/...` 的后半段。
   按调用方转发凭据：`:87` 发 `Authorization: Bearer <调用方 token>`、`:88` 发 `X_Tenant_ID`。
   丢弃未传参数：`:93-96` 的 `_clean_params` 把值为 `None` 的整条丢掉。
   **推论**：可选参数一律声明成 `None` 默认，**不要在工具里重写服务端的默认值** ——
   重写等于给同一份默认值开了第二个会漂移的出处。PRD-18216 的「非法值回落默认」就是靠这条天然成立的。

4. **测试里调工具、取返回值的写法是 `result[0][0].text`**（`tests/test_tools.py:287`）。
   不是 `result[0].text`。写错会得到一个看起来像 MCP 版本差异的报错。

## 再加工具时新踩到的三条（SOP 列表 + 同步对话实做后记，@ 3b1a5da）

5. **`tool.description` 是 docstring 的原文，不做 dedent —— 缩进也算进 500 字符。**
   `tests/test_tools.py:139` 断言的那个长度，包含每个续行前面的 **8 个空格**和空行的换行符。
   同一段文字，`inspect.cleandoc` 量出来 479，装进工具后是 544（差 65 = 缩进）。
   **推论**：压 description 时，删掉一整行比抠词省得多（一行白赚 9 字符），
   而按 `cleandoc` 估长度会稳定低估。豁免表 `:123` 仍然是欠账，本次两个新工具都压进了 500
   （`list_sops` 493 / `chat_with_sop` 497），没往里加。

6. **`instructions` 的 1500 上限已经贴脸，加一组工具必须先重写旧文案。**
   `tests/test_tools.py:160` 断言 ≤ 1500，而改之前实测就是 **1496**——只剩 4 字符。
   本次为塞进 SOP 两个工具，把 twilio / clear_sop_section / 概念段各压了一点，最终 1487。
   **推论**：下一个人再加工具组，同样要先腾地方，别指望直接追加。

7. **跑 agent 的那类 endpoint 不能吃 `api_client` 的默认重试和默认读超时。**
   `POST /api/agents/:id/run/wait` 是同步跑完一轮才响应：默认 30s 读超时撑不住
   （Aegra 自己的兜底是 1 小时），而默认 3 次重试更危险——**重发不是把丢失的响应捞回来，
   是再跑一遍 agent**。为此 `api_client.py:106` 的 `post()` 加了 `read_timeout` / `retries`
   两个 keyword-only 覆盖项（其它调用方默认不变），`tools/sops.py:29` 用 `_CHAT_READ_TIMEOUT = 300.0`
   + `retries=0`，超时错误显式标 `retryable=false` 并提示改用同一会话再问。
   另一半坑在响应上：这个 endpoint **跑失败也是 HTTP 200，body 里 `success: false`**，
   永远走不到 `AgentError`，所以 `tools/sops.py:243` 必须显式查 `success`，
   否则失败会被读成「成功但 agent 没说话」。

## 再加工具时的更正 + 新事实（connector 工具开关实做后记，@ HEAD）

8. **第 5 条已过期：当前 `tool.description` 会 dedent，长度按 `cleandoc` 后计。**
   实测（本次同一批 docstring）原文长度 vs `list_tools()` 里的 `description`：
   `upsert_agent_permissions` 3596→3156、`get_connectors` 563→499、`set_sop_procedure` 562→498。
   **推论反转**：现在按原文（带 8 空格缩进）估长度是**稳定高估**，正确口径是把 docstring 写成
   flush-left 再数，或直接读 `list_tools()`。本次两个新工具按此量到
   `list_connector_tools` 488 / `set_connector_tools` 499，均 < 500，未进豁免表。

9. **第 8 条顺带解除了旧「红灯」。** `get_connectors` 的 description 现在是 **499**（dedent 后），
   不再超 500，`test_tools_list_snapshot` 现在全绿（本次实测 49 passed）。旧记录说的 563 是原文长度、
   非 `description` 长度，属同一个 dedent 误解。

10. **`agents/:id/connectors/:cid/tools` 的 PUT 和 run/wait 一样：业务失败是 HTTP 200 + `success:false`。**
    「agent 不存在」「tools 为空」都走这条，永远到不了 `AgentError`。`tools/connectors.py` 的
    `mspbotsagent_set_connector_tools` 因此显式查 `result.get("success") is False`（同 `tools/sops.py`）。
    成功时取内层 `data`（`{agentId,capabilityId,names,enabled,restartRequired,pending}`）。

11. **`capabilityId` 是全平台同一个 UUID 命名空间——`:cid` 不需要新工具去拿。**
    2026-09-16 实测（INT 租户 `uc1dnhtl1io4ohbz7t0d3`）：`get_connectors` 用的
    `/api/capabilities/connectors/catalog` 里每行的 `id`、`/api/agents/:id/connectors` 里的 `id`、
    以及 `sop-author/data-sources-list` 条目里的 `id`，同一连接器**三处 UUID 完全相同**
    （如 halopsa = `a79030ad-…4bddd`）。所以设计文档里的「接口 1」`GET /api/agents/:id/connectors`
    **没有包成工具**：它返回的是全 catalog（实测 98 个）+ `selected` 标记，拿 `:cid` 用现有
    `get_connectors`（租户级）或 `get_sop_data_sources`（agent 级、每条带 `id`）即可。只包了「接口 2」
    （列工具+开关态）和「接口 3」（改开关）。

12. **`instructions` 预算：本次加两句后实测 1453（≤1500），余 47 字符。** 第 6 条记的 1487 已过期
    （skills 工具组隐藏后腾出过空间）。下一个人加工具组仍要先量再加。

## 未覆盖

本文件目前只覆盖「加新工具」这条路径。凭据注入、gateway 模式的请求头契约、容器部署，都还没有累积事实条目。
