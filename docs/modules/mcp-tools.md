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

## 未覆盖

本文件目前只覆盖「加新工具」这条路径。凭据注入、gateway 模式的请求头契约、容器部署，都还没有累积事实条目。
