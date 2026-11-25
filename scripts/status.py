"""Print what the receiver has stored: callbacks, verified runs, and Issue state."""

import json

from _common import run

from app.config import Settings
from app.store import Store


def main() -> None:
    store = Store(Settings.from_env().db_path)
    print("Callbacks")
    for row in store._run("SELECT id, received_at, status, run_id, note FROM deliveries ORDER BY id"):
        print(f"  #{row['id']} {row['received_at']} {row['status']:<10} {row['run_id'] or '-'}  {row['note'] or ''}")
    print("Verified runs")
    for row in store.all_changes():
        record = json.loads(row["record_json"] or "{}")
        print(f"  {row['run_id']} changed={bool(row['changed'])} decision={row['decision']} "
              f"state={row['state']} issue={row['issue_number'] or '-'} "
              f"required={record.get('current_required')}")


run(main)
