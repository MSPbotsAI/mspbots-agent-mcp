import json
from collections.abc import Callable

from mcp.server.fastmcp import FastMCP

from ..api_client import AgentClient, AgentError
from ._common import NO_TOKEN


def register(mcp: FastMCP, client_factory: Callable[[], AgentClient | None]) -> None:

    @mcp.tool()
    async def mspbotsagent_list_triggers(
        agent_id: str,
        page: int = 1,
        page_size: int = 50,
    ) -> str:
        """List all triggers (scheduled/event tasks) owned by an agent.

        A trigger fires the agent automatically — either on a recurring cron
        schedule ("recurring") or when an external integration event happens
        ("event"). Use this to see what is already configured before adding or
        changing one.

        Args:
            agent_id:  The agent whose triggers to list. Required.
            page:      1-based page number. Default 1.
            page_size: Rows per page. Default 50.

        Returns JSON with the total count and one row per trigger, each holding
        its taskId, name, prompt, type, enabled flag, schedule/timezone (for
        recurring), triggerIntegration/triggerEvents (for event), and expiry.
        """
        client = client_factory()
        if client is None:
            return NO_TOKEN
        try:
            result = await client.get(
                "/api/tasks",
                params={"agentId": agent_id, "page": page, "pageSize": page_size},
            )
        except AgentError as e:
            return f"Error: {e}"
        return json.dumps(result, indent=2, ensure_ascii=False)

    @mcp.tool()
    async def mspbotsagent_upsert_trigger(
        agent_id: str | None = None,
        task_id: str | None = None,
        name: str | None = None,
        prompt: str | None = None,
        type: str | None = None,
        enabled: bool | None = None,
        expires_in_days: int | None = None,
        schedule: str | None = None,
        timezone: str | None = None,
        run: bool | None = None,
        trigger_integration: str | None = None,
        trigger_events: list[str] | None = None,
    ) -> str:
        """Create or update a trigger for an agent.

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

        Args (all optional on update; on create agent_id/name/prompt/type are
        required):
            agent_id:            Owning agent (required on create).
            task_id:             Present = update that trigger; absent = create.
            name:                Human-readable trigger name.
            prompt:              Instruction the agent runs when triggered.
            type:                "recurring" or "event".
            enabled:             Whether the trigger is active.
            expires_in_days:     Auto-expire after N days.
            schedule:            Cron expression (recurring only, min 1h interval).
            timezone:            IANA timezone for the schedule (recurring only).
            run:                 Run once immediately on create (recurring only).
            trigger_integration: Integration key (event only).
            trigger_events:      Event names (event only).

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
            if type not in ("recurring", "event"):
                return "Error: type must be 'recurring' or 'event'"
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
        except AgentError as e:
            return f"Error: {e}"
        return json.dumps(result, indent=2, ensure_ascii=False)

    @mcp.tool()
    async def mspbotsagent_delete_trigger(task_id: str) -> str:
        """Delete a trigger by its taskId. This cannot be undone.

        Args:
            task_id: The trigger to delete. Required.

        Returns the API response as JSON.
        """
        client = client_factory()
        if client is None:
            return NO_TOKEN
        try:
            result = await client.delete(f"/api/tasks/{task_id}")
        except AgentError as e:
            return f"Error: {e}"
        return json.dumps(result, indent=2, ensure_ascii=False)

    @mcp.tool()
    async def mspbotsagent_get_trigger_catalog() -> str:
        """List the valid integration + event combinations for event triggers.

        Call this before creating an "event" trigger to learn which
        triggerIntegration / triggerEvents pairs are allowed. Passing a
        combination not in this catalog will be rejected.

        Returns the catalog as JSON. No arguments needed.
        """
        client = client_factory()
        if client is None:
            return NO_TOKEN
        try:
            result = await client.get("/api/tasks/trigger-catalog")
        except AgentError as e:
            return f"Error: {e}"
        return json.dumps(result, indent=2, ensure_ascii=False)

    @mcp.tool()
    async def mspbotsagent_run_trigger(task_id: str) -> str:
        """Run a trigger once immediately, regardless of its schedule/event.

        Useful for testing a newly created trigger or manually re-running one
        without waiting for its next scheduled time or event.

        Args:
            task_id: The trigger to run now. Required.

        Returns the run result as JSON.
        """
        client = client_factory()
        if client is None:
            return NO_TOKEN
        try:
            result = await client.post(f"/api/tasks/{task_id}/run")
        except AgentError as e:
            return f"Error: {e}"
        return json.dumps(result, indent=2, ensure_ascii=False)
