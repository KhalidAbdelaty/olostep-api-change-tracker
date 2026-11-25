"""Shared helpers for the command-line scripts."""

import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from app.config import MissingSetting, redact_value  # noqa: E402


def show(data) -> None:
    print(json.dumps(redact_value(data), indent=2))


def run(main) -> None:
    try:
        main()
    except MissingSetting as exc:
        print(f"Stopped: {exc}")
        sys.exit(2)
