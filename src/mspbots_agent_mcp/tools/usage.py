"""Usage overview — one read-only tool over the tenant's usage report (PRD-18216).

The wrapper is deliberately thin: `api_client` already applies the app mount
prefix, forwards the caller's bearer per call, and drops unset params so the
platform keeps sole ownership of its own defaults. Restating those defaults
here would only give them a second place to drift.

The one piece of real logic is `_shape_overview`. The tool's output budget
(`_json.MAX_CHARS`) is smaller than a full page of `breakdown` at the
platform's maximum page size, and the generic capper trims the largest list
*silently* — leaving a model with a short breakdown next to a full
`breakdownTotal` and no way to tell it was cut. So the trimming is done here
instead, with a marker, and `breakdownTotal` is left reporting upstream's
number so the two can be compared.
"""

from collections.abc import Callable

from mcp.server.fastmcp import FastMCP
from mcp.types import ToolAnnotations

# _compact is imported rather than re-implemented: the size decision below has
# to be measured with the exact serializer the return value goes through, or
# the marker would be attached at a threshold that does not match reality.
from .._json import MAX_CHARS, _compact, dump_json_capped
from ..api_client import AgentClient, AgentError
from ._common import NO_TOKEN

_PATH = "/api/usage/overview"


def _with_rows(shaped: dict, rows: list, kept: int) -> dict:
    out = dict(shaped)
    out["breakdown"] = rows
    out["breakdownReturned"] = kept
    out["breakdownTruncatedByToolOutput"] = True
    return out


def _shape_overview(payload, max_chars: int = MAX_CHARS):
    """Drop `debug`, and trim `breakdown` explicitly if the rest would not fit.

    Returns a new dict; the input is never mutated. Anything that is not a dict
    (an error-shaped body, an older deployment) is passed straight through
    rather than raising — this runs on whatever the platform answered.
    """
    if not isinstance(payload, dict):
        return payload

    shaped = {k: v for k, v in payload.items() if k != "debug"}
    if len(_compact(shaped)) <= max_chars:
        return shaped

    rows = shaped.get("breakdown")
    if not isinstance(rows, list) or not rows:
        # Nothing here is ours to trim. dump_json_capped still bounds the
        # output; we simply have no honest marker to add.
        return shaped

    # Largest row count that fits, measured with the markers already present so
    # the answer stays true after they are added.
    lo, hi, best = 0, len(rows), 0
    while lo <= hi:
        mid = (lo + hi) // 2
        if len(_compact(_with_rows(shaped, rows[:mid], mid))) <= max_chars:
            best = mid
            lo = mid + 1
        else:
            hi = mid - 1
    return _with_rows(shaped, rows[:best], best)


def register(mcp: FastMCP, client_factory: Callable[[], AgentClient | None]) -> None:

    @mcp.tool(annotations=ToolAnnotations(readOnlyHint=True))
    async def mspbotsagent_get_usage_overview(
        range: str | None = None,
        page: int | None = None,
        pageSize: int | None = None,
        sortBy: str | None = None,
        sortOrder: str | None = None,
        sopId: int | None = None,
        source: str | None = None,
    ) -> str:
        """Tenant usage report: spend, runs, threads, agents, and a per-agent breakdown.

        Use for "how much did we spend", "which agent costs most", "who created
        this agent". Paging is over agents, not time — the totals cover the whole
        range. If spendUnavailable is true, costs are 0 because the spend backend
        could not be read: say unavailable, never 0. createdBy is an email when
        resolvable, else a raw user id. Amounts match the Usage page's CREDITS.
        """
        client = client_factory()
        if client is None:
            return NO_TOKEN
        try:
            result = await client.get(
                _PATH,
                params={
                    "range": range,
                    "page": page,
                    "pageSize": pageSize,
                    "sortBy": sortBy,
                    "sortOrder": sortOrder,
                    "sopId": sopId,
                    "source": source,
                },
            )
        except AgentError as e:
            return e.to_envelope()

        return dump_json_capped(_shape_overview(result))
