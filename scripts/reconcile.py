"""Find monitor runs the receiver never recorded, for example while it was offline.

Each missing run is stored as a delivery that names only the monitor and run IDs.
The running worker then verifies and classifies it like any other callback.
"""

from _common import run

from app.config import Settings, require
from app.olostep_client import OlostepClient
from app.store import Store

MAX_PAGES = 4


def main() -> None:
    monitor_id = require("OLOSTEP_MONITOR_ID")
    store = Store(Settings.from_env().db_path)
    client = OlostepClient()
    cursor, queued, seen = None, 0, 0
    for _ in range(MAX_PAGES):
        page = client.list_events(monitor_id, limit=100, cursor=cursor)
        for event in page.get("data", []):
            seen += 1
            if store.get_change(monitor_id, event["run_id"]) is None:
                store.add_delivery({"monitor_id": monitor_id, "run_id": event["run_id"],
                                    "source": "reconcile"})
                queued += 1
                print(f"Queued {event['run_id']} (changed={event['changed']})")
        cursor = page.get("next_cursor")
        if not page.get("has_more") or not cursor:
            break
    print(f"Checked {seen} events, queued {queued} missing runs.")


run(main)
