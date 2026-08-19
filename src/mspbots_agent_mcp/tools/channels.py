from collections.abc import Callable
from typing import Annotated, Any

from mcp.server.fastmcp import FastMCP
from mcp.types import ToolAnnotations
from pydantic import Field

from .._json import dump_json_capped
from ..api_client import AgentClient, AgentError
from ._common import NO_TOKEN
from .agents import _fetch_agent_data

# Microsoft Teams and Twilio Voice are two more fields on the SAME agent
# record permissions/evaluation/approval live on — reads share one
# GET /api/agents/:id, writes share one partial PUT /api/agents/:id. Do not
# update the same agent from two calls at once (see agents.py's module
# comment; this applies here too).
#
# Both channels store a credential (Teams: app_password / Twilio:
# auth_token) that the platform's own contract says GET never returns in
# the clear — only has_password / has_auth_token. That masking is
# confirmed for GET; it was NOT confirmed for the PUT response (which
# could plausibly echo back what was just written, since a naive
# "return the updated record" implementation would do exactly that). Since
# that hasn't been tested against a real deployment, _redact_channel_secrets
# strips the credential fields defensively before an upsert response ever
# reaches an agent's context, rather than trust an unverified assumption.


def _redact_channel_secrets(result: Any) -> Any:
    if not isinstance(result, dict):
        return result
    data = result.get("data")
    if not isinstance(data, dict):
        return result
    data = dict(data)
    msteams = data.get("msteams")
    if isinstance(msteams, dict) and "app_password" in msteams:
        data["msteams"] = {k: v for k, v in msteams.items() if k != "app_password"}
    twilio = data.get("twilio")
    if isinstance(twilio, dict) and "auth_token" in twilio:
        data["twilio"] = {k: v for k, v in twilio.items() if k != "auth_token"}
    return {**result, "data": data}


def register(mcp: FastMCP, client_factory: Callable[[], AgentClient | None]) -> None:

    # ----- Microsoft Teams channel ------------------------------------

    @mcp.tool(annotations=ToolAnnotations(readOnlyHint=True))
    async def mspbotsagent_get_agent_teams(
        agent_id: Annotated[str, Field(description="Agent to read.")],
    ) -> str:
        """Read an agent's Microsoft Teams channel config (Azure Bot).

        The client secret is never returned — only whether one is set
        (has_password) — plus the read-only webhook URL to paste into the
        Azure Bot's messaging endpoint.

        Returns msteams = {enabled, app_id, tenant_id, allow_from,
        has_password} (or null if the channel was never configured), and
        msteamsWebhookUrl (read-only).
        """
        client = client_factory()
        if client is None:
            return NO_TOKEN
        try:
            data = await _fetch_agent_data(client, agent_id)
        except AgentError as e:
            return e.to_envelope()
        return dump_json_capped(
            {
                "msteams": data.get("msteams"),
                "msteamsWebhookUrl": data.get("msteamsWebhookUrl"),
            }
        )

    @mcp.tool(annotations=ToolAnnotations(idempotentHint=True))
    async def mspbotsagent_upsert_agent_teams(
        agent_id: Annotated[str, Field(description="Agent to update.")],
        msteams: Annotated[
            dict | None,
            Field(
                description=(
                    "Object to enable/configure the channel, or null to disable "
                    "AND clear it entirely (the stored client secret included — "
                    "there's no way back except reconfiguring from scratch). To "
                    "pause without losing the stored secret, send an object with "
                    "enabled:false instead of null. Object shape: "
                    '{"enabled": bool (default true), "app_id": "<Azure Bot '
                    'registration GUID, required only if no channel is stored '
                    'yet>", "tenant_id": "...", "allow_from": "comma-separated '
                    'Entra object ids, empty = everyone", "app_password": '
                    '"<client secret, write-only — omit to keep the stored '
                    'value>"}. Any value other than an object or null is '
                    "rejected by the backend."
                )
            ),
        ],
    ) -> str:
        """Enable/configure or disable an agent's Microsoft Teams channel.

        app_password is required the first time this agent gets a Teams
        channel (no stored secret yet); omit it on a later update to keep
        the existing one — the response never echoes it back either way.

        Shares the same agent record as permissions/evaluation/approval
        (partial PUT /api/agents/:id) — do not update the same agent from
        two calls at once.
        """
        client = client_factory()
        if client is None:
            return NO_TOKEN
        try:
            result = await client.put(f"/api/agents/{agent_id}", {"msteams": msteams})
        except AgentError as e:
            return e.to_envelope()
        return dump_json_capped(_redact_channel_secrets(result))

    # ----- Twilio Voice channel ----------------------------------------

    @mcp.tool(annotations=ToolAnnotations(readOnlyHint=True))
    async def mspbotsagent_get_agent_twilio(
        agent_id: Annotated[str, Field(description="Agent to read.")],
    ) -> str:
        """Read an agent's Twilio Voice channel config.

        The Auth Token is never returned — only whether one is set
        (has_auth_token) — plus the read-only voice webhook URL to paste
        into the Twilio number's Voice configuration.

        Returns twilio = {enabled, allow_from, welcome_greeting, language,
        has_auth_token} (or null if the channel was never configured), and
        twilioWebhookUrl (read-only).
        """
        client = client_factory()
        if client is None:
            return NO_TOKEN
        try:
            data = await _fetch_agent_data(client, agent_id)
        except AgentError as e:
            return e.to_envelope()
        return dump_json_capped(
            {
                "twilio": data.get("twilio"),
                "twilioWebhookUrl": data.get("twilioWebhookUrl"),
            }
        )

    @mcp.tool(annotations=ToolAnnotations(idempotentHint=True))
    async def mspbotsagent_upsert_agent_twilio(
        agent_id: Annotated[str, Field(description="Agent to update.")],
        twilio: Annotated[
            dict | None,
            Field(
                description=(
                    "Object to enable/configure the channel, or null to disable "
                    "AND clear it entirely (the stored Auth Token included — "
                    "there's no way back except reconfiguring from scratch). To "
                    "pause without losing the stored token, send an object with "
                    "enabled:false instead of null. Object shape: "
                    '{"enabled": bool (default true), "auth_token": "<Twilio '
                    'Auth Token, write-only — omit to keep the stored value; '
                    'required only if no channel is stored yet>", "allow_from": '
                    '"comma-separated E.164 numbers, empty = everyone", '
                    '"welcome_greeting": "spoken when the call connects", '
                    '"language": "e.g. en-US"}. Any value other than an object '
                    "or null is rejected by the backend."
                )
            ),
        ],
    ) -> str:
        """Enable/configure or disable an agent's Twilio Voice channel.

        auth_token is required the first time this agent gets a Twilio
        channel (no stored token yet); omit it on a later update to keep
        the existing one — the response never echoes it back either way.

        Shares the same agent record as permissions/evaluation/approval
        (partial PUT /api/agents/:id) — do not update the same agent from
        two calls at once.
        """
        client = client_factory()
        if client is None:
            return NO_TOKEN
        try:
            result = await client.put(f"/api/agents/{agent_id}", {"twilio": twilio})
        except AgentError as e:
            return e.to_envelope()
        return dump_json_capped(_redact_channel_secrets(result))
