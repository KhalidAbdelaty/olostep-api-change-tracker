"""Turn an unsigned callback into a run we fetched ourselves from the Olostep API."""

from dataclasses import dataclass

from .olostep_client import OlostepClient

EVENT_PAGES_TO_SEARCH = 4


@dataclass
class Verification:
    status: str  # verified, unmatched, or rejected
    reason: str
    monitor_id: str | None = None
    run_id: str | None = None
    event: dict | None = None


def callback_ids(body: dict) -> tuple[str | None, str | None] | None:
    """Return (monitor_id, run_id) named by the callback.

    Olostep does not document the Monitor callback body. The first real callbacks,
    captured on November 25, 2026, carried monitor_id, run_id, changed,
    is_first_snapshot, summary, and the page content as top-level keys. Only the
    two IDs are read here. Everything else is fetched again from the API.
    """
    monitor_id, run_id = body.get("monitor_id"), body.get("run_id")
    if not isinstance(monitor_id, str) or not isinstance(run_id, str):
        return None
    return monitor_id, run_id


def find_event(olostep: OlostepClient, monitor_id: str, run_id: str) -> dict | None:
    cursor = None
    for _ in range(EVENT_PAGES_TO_SEARCH):
        page = olostep.list_events(monitor_id, limit=25, cursor=cursor)
        for event in page.get("data", []):
            if event.get("run_id") == run_id:
                return event
        cursor = page.get("next_cursor")
        if not page.get("has_more") or not cursor:
            return None
    return None


def verify_callback(body: dict, expected_monitor: str, docs_url: str,
                    olostep: OlostepClient) -> Verification:
    ids = callback_ids(body)
    if ids is None:
        return Verification("rejected", "callback has no monitor_id and run_id strings")
    monitor_id, run_id = ids

    if not expected_monitor:
        return Verification("rejected", "OLOSTEP_MONITOR_ID is not set")
    if monitor_id and monitor_id != expected_monitor:
        return Verification("rejected", f"callback names a different monitor ({monitor_id})")
    if not run_id or not run_id.startswith("run_"):
        return Verification("rejected", "callback has no run id")

    monitor = olostep.get_monitor(expected_monitor)
    tracked = monitor.get("tracked", {}).get("urls") or []
    if docs_url and docs_url not in tracked:
        return Verification("rejected", f"monitor does not track {docs_url}")

    event = find_event(olostep, expected_monitor, run_id)
    if event is None:
        return Verification("unmatched", "no event with this run id yet",
                            expected_monitor, run_id)

    # The run detail holds the page content Olostep captured for this run
    run = olostep.get_run(expected_monitor, run_id)
    if run.get("snapshot", {}).get("run_id") != run_id:
        return Verification("unmatched", "run detail is not ready yet", expected_monitor, run_id)
    event = {**event, "content": run_content(run)}
    return Verification("verified", "run found in the authenticated events list",
                        expected_monitor, run_id, event)


def run_content(run: dict) -> str | None:
    """Find the captured page markdown inside the run detail's node results."""
    results = (run.get("events") or {}).get("results") or {}
    for node in results.values():
        output = (node or {}).get("output") or {}
        if isinstance(output.get("content"), str):
            return output["content"]
    for node in results.values():
        output = (node or {}).get("output") or {}
        if isinstance(output.get("markdown"), str):
            return output["markdown"]
    return None
