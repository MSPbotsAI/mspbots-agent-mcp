from collections.abc import Callable
from typing import Annotated

from mcp.server.fastmcp import FastMCP
from mcp.types import ToolAnnotations
from pydantic import Field

from .._json import dump_json_capped
from ..api_client import AgentClient, AgentError
from ._common import NO_TOKEN

_MAX_PAGE_SIZE = 200


def register(mcp: FastMCP, client_factory: Callable[[], AgentClient | None]) -> None:

    @mcp.tool(annotations=ToolAnnotations(readOnlyHint=True))
    async def mspbotsagent_list_triggers(
        agent_id: Annotated[str, Field(description="Agent whose triggers to list.")],
        page: Annotated[int, Field(description="1-based page number.")] = 1,
        page_size: Annotated[
            int, Field(description="Rows per page (max 200).")
        ] = 50,
    ) -> str:
        """List the scheduled/event triggers configured to run an agent.

        A trigger fires the agent automatically: on a cron schedule
        ("recurring") or on an external integration event ("event").
        """
        client = client_factory()
        if client is None:
            return NO_TOKEN
        page_size = min(page_size, _MAX_PAGE_SIZE)
        try:
            result = await client.get(
                "/api/tasks",
                params={"agentId": agent_id, "page": page, "pageSize": page_size},
            )
            return dump_json_capped(result)
        except AgentError as e:
            return e.to_envelope()

    @mcp.tool()
    async def mspbotsagent_upsert_trigger(
        agent_id: Annotated[
            str | None, Field(description="Owning agent. Required on create.")
        ] = None,
        task_id: Annotated[
            str | None,
            Field(description="Set to update that trigger; omit to create a new one."),
        ] = None,
        name: Annotated[str | None, Field(description="Trigger name.")] = None,
        prompt: Annotated[
            str | None, Field(description="Instruction the agent runs when triggered.")
        ] = None,
        type: Annotated[
            str | None, Field(description='"recurring", "event" or "manual".')
        ] = None,
        enabled: Annotated[
            bool | None, Field(description="Whether the trigger is active.")
        ] = None,
        expires_in_days: Annotated[
            int | None, Field(description="Auto-expire after N days.")
        ] = None,
        schedule: Annotated[
            str | None,
            Field(description="Cron expression. recurring only; minimum 1h interval."),
        ] = None,
        timezone: Annotated[
            str | None, Field(description="IANA timezone. recurring only.")
        ] = None,
        run: Annotated[
            bool | None, Field(description="Run once immediately on create. recurring only.")
        ] = None,
        trigger_integration: Annotated[
            str | None, Field(description="Integration key. event only.")
        ] = None,
        trigger_events: Annotated[
            list[str] | None, Field(description="Event names. event only.")
        ] = None,
    ) -> str:
        """Create a trigger (omit task_id) or update one (pass task_id).

        Pass task_id to UPDATE an existing trigger (send only the fields you want
        to change — partial patch). Omit task_id to CREATE a new one.

        Trigger types:
          - "recurring": runs on a cron schedule. Requires `schedule` (cron, e.g.
            "0 * * * *"). Minimum interval is 1 hour. `timezone` optional (e.g.
            "America/New_York"). `run=true` runs it once immediately on create.
          - "event": runs when an integration emits an event. Requires
            `trigger_integration` (e.g. "connectwise") and `trigger_events`
            (e.g. ["ticket.created"]). The combination must be valid — check
            mspbotsagent_get_trigger_catalog first.
          - "manual": runs only when someone starts it. Needs nothing beyond the
            common fields — no schedule, no integration, no events.

        All optional on update; on create agent_id/name/prompt/type are required.

        Returns the created/updated trigger as JSON.
        """
        client = client_factory()
        if client is None:
            return NO_TOKEN

        creating = task_id is None

        if creating:
            missing = [
                label
                for label, value in (
                    ("agent_id", agent_id),
                    ("name", name),
                    ("prompt", prompt),
                    ("type", type),
                )
                if not value
            ]
            if missing:
                return f"Error: creating a trigger requires: {', '.join(missing)}"
            if type not in ("recurring", "event", "manual"):
                return "Error: type must be 'recurring', 'event' or 'manual'"
            if type == "recurring" and not schedule:
                return "Error: recurring triggers require a cron 'schedule' (min 1h interval)"
            if type == "event" and (not trigger_integration or not trigger_events):
                return (
                    "Error: event triggers require 'trigger_integration' and 'trigger_events' "
                    "(must be a valid combination — see mspbotsagent_get_trigger_catalog)"
                )

        body: dict = {}
        for key, value in (
            ("agentId", agent_id),
            ("name", name),
            ("prompt", prompt),
            ("type", type),
            ("enabled", enabled),
            ("expiresInDays", expires_in_days),
            ("schedule", schedule),
            ("timezone", timezone),
            ("run", run),
            ("triggerIntegration", trigger_integration),
            ("triggerEvents", trigger_events),
        ):
            if value is not None:
                body[key] = value

        if not body:
            return "Error: nothing to update — provide at least one field to change"

        try:
            if creating:
                result = await client.post("/api/tasks", body)
            else:
                result = await client.put(f"/api/tasks/{task_id}", body)
            return dump_json_capped(result)
        except AgentError as e:
            return e.to_envelope()

    @mcp.tool(annotations=ToolAnnotations(destructiveHint=True))
    async def mspbotsagent_delete_trigger(
        task_id: Annotated[str, Field(description="Trigger to delete.")],
    ) -> str:
        """Delete a trigger by its task ID. This cannot be undone."""
        client = client_factory()
        if client is None:
            return NO_TOKEN
        try:
            result = await client.delete(f"/api/tasks/{task_id}")
            return dump_json_capped(result)
        except AgentError as e:
            return e.to_envelope()

    @mcp.tool(annotations=ToolAnnotations(readOnlyHint=True))
    async def mspbotsagent_get_trigger_catalog() -> str:
        """List the valid integration + event combinations for event triggers.

        Call this before creating an "event" trigger — a combination not in
        this catalog will be rejected.
        """
        client = client_factory()
        if client is None:
            return NO_TOKEN
        try:
            result = await client.get("/api/tasks/trigger-catalog")
            return dump_json_capped(result)
        except AgentError as e:
            return e.to_envelope()

    @mcp.tool()
    async def mspbotsagent_run_trigger(
        task_id: Annotated[str, Field(description="Trigger to run now.")],
    ) -> str:
        """Run a trigger once immediately, regardless of its schedule/event.

        Useful for testing a newly created trigger or re-running one without
        waiting for its next scheduled time or event.
        """
        client = client_factory()
        if client is None:
            return NO_TOKEN
        try:
            result = await client.post(f"/api/tasks/{task_id}/run")
            return dump_json_capped(result)
        except AgentError as e:
            return e.to_envelope()
