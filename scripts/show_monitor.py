"""Print the monitor's status, tracked URL, schedule, and last run. Use --wait to poll."""

import sys
import time

from _common import run, show

from app.config import require
from app.olostep_client import OlostepClient


def main() -> None:
    monitor_id = require("OLOSTEP_MONITOR_ID")
    client = OlostepClient()
    while True:
        monitor = client.get_monitor(monitor_id)
        tracked = monitor.get("tracked", {}).get("urls") or []
        print(f"status={monitor['status']} tracked={tracked} "
              f"next_run_at={monitor['schedule'].get('next_run_at')}")
        if "--wait" not in sys.argv or (monitor["status"] != "provisioning" and tracked):
            break
        time.sleep(10)
    show({k: monitor.get(k) for k in
          ("id", "status", "tracked", "source_policy", "schedule", "notification",
           "webhook", "last_run", "total_count", "error_message")})


run(main)
