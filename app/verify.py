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

    Olostep does not document the Monitor callback body, so this returns None
    until a real callback has been captured and modeled.
    """
    return None


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
        return Verification("rejected", "callback shape not modeled yet")
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
    return Verification("verified", "run found in the authenticated events list",
                        expected_monitor, run_id, event)
