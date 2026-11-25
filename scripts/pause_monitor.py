"""Pause the monitor so scheduled runs stop."""

from _common import run, show

from app.config import require
from app.olostep_client import OlostepClient


def main() -> None:
    monitor = OlostepClient().pause_monitor(require("OLOSTEP_MONITOR_ID"))
    show({k: monitor.get(k) for k in ("id", "status", "schedule")})


run(main)
