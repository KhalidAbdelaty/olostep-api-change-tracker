"""Store a copy of an earlier callback as a new delivery, the way a provider retry would arrive."""

import json
import sys

from _common import run

from app.config import Settings
from app.store import Store


def main() -> None:
    if len(sys.argv) != 2 or not sys.argv[1].isdigit():
        print("Usage: python scripts/replay.py <delivery-id>")
        sys.exit(2)
    store = Store(Settings.from_env().db_path)
    original = store.get_delivery(int(sys.argv[1]))
    if original is None:
        print(f"No delivery {sys.argv[1]} in the database")
        sys.exit(1)
    new_id = store.add_delivery(json.loads(original["body_json"]))
    print(f"Stored delivery {new_id} as a replay of {sys.argv[1]}. The running worker picks it up.")


run(main)
