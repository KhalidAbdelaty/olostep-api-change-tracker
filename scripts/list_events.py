"""List the monitor's snapshot events, newest first. Signed URLs are redacted."""

from datetime import datetime, timezone

from _common import run, show

from app.config import require
from app.olostep_client import OlostepClient


def main() -> None:
    page = OlostepClient().list_events(require("OLOSTEP_MONITOR_ID"), limit=25)
    for event in page.get("data", []):
        when = datetime.fromtimestamp(event["created"], timezone.utc).isoformat()
        print(f"{when}  {event['run_id']}  changed={event['changed']}  {event['summary']}")
    show(page)


run(main)
