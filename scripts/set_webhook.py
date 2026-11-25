"""Attach the public receiver URL to the existing monitor."""

import sys

from _common import run, show

from app.config import require
from app.olostep_client import OlostepClient


def main() -> None:
    if len(sys.argv) != 2 or not sys.argv[1].startswith("https://"):
        print("Usage: python scripts/set_webhook.py https://<public-host>")
        sys.exit(2)
    url = f"{sys.argv[1].rstrip('/')}/hooks/olostep/{require('WEBHOOK_PATH_TOKEN')}"
    monitor = OlostepClient().update_monitor(require("OLOSTEP_MONITOR_ID"), {"webhook": {"url": url}})
    show({k: monitor.get(k) for k in ("id", "status", "webhook", "notification", "schedule")})


run(main)
