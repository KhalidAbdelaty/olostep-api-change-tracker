"""The three local states that must never call GitHub, plus a replay after a restart.

Olostep and GitHub are both test doubles here. The callback fixture is the real
first-snapshot callback captured on November 25, 2026.
"""

import json
from pathlib import Path

from fastapi.testclient import TestClient

from app.config import Settings
from app.github_client import GitHubClient
from app.olostep_client import OlostepClient
from app.store import Store
from app.worker import Worker
from fakes import FakeGitHub, FakeOlostep

FIXTURES = Path(__file__).parent / "fixtures"
BASELINE = json.loads((FIXTURES / "callback_first_snapshot.json").read_text(encoding="utf-8"))
MONITOR = BASELINE["monitor_id"]
DOCS_URL = "https://khalidabdelaty.github.io/olostep-api-change-tracker/"
STAGES = Path(__file__).parent.parent / "stages"
BASELINE_PAGE = (STAGES / "1-baseline.html").read_text(encoding="utf-8")
ACCOUNT_PAGE = (STAGES / "3-account-id.html").read_text(encoding="utf-8")

CHANGE_RUN = "run_change_test"
CHANGE_CALLBACK = {**BASELINE, "run_id": CHANGE_RUN, "changed": True,
                   "is_first_snapshot": False, "created_at": BASELINE["created_at"] + 600}
EVENTS = [
    {"id": CHANGE_RUN, "run_id": CHANGE_RUN, "created": BASELINE["created_at"] + 600,
     "changed": True, "summary": "customer_id was renamed to account_id"},
    {"id": BASELINE["run_id"], "run_id": BASELINE["run_id"], "created": BASELINE["created_at"],
     "changed": False, "summary": BASELINE["summary"]},
]
RUN_CONTENT = {BASELINE["run_id"]: BASELINE_PAGE, CHANGE_RUN: ACCOUNT_PAGE}


def build(tmp_path, github: FakeGitHub, olostep: FakeOlostep) -> tuple[Worker, Store]:
    settings = Settings(MONITOR, "path-token", "owner/repo", DOCS_URL, tmp_path / "t.db")
    store = Store(settings.db_path)
    worker = Worker(
        settings, store,
        olostep=OlostepClient(api_key="test-key", transport=olostep.transport()),
        github=GitHubClient("owner/repo", token="test-token", transport=github.transport()),
    )
    return worker, store


def fakes() -> tuple[FakeGitHub, FakeOlostep]:
    return FakeGitHub(), FakeOlostep(MONITOR, DOCS_URL, EVENTS, RUN_CONTENT)


def test_no_callback_yet_calls_nothing(tmp_path):
    github, olostep = fakes()
    worker, _ = build(tmp_path, github, olostep)
    worker.run_once()
    assert github.calls == [] and olostep.calls == []


def test_unmatched_callback_never_reaches_github(tmp_path):
    github, olostep = fakes()
    worker, store = build(tmp_path, github, olostep)
    delivery = store.add_delivery({**BASELINE, "run_id": "run_doesnotexist"})
    for _ in range(6):
        # Skip the 30-second wait between retries
        store._run("UPDATE deliveries SET next_attempt_at = 0")
        worker.run_once()
    assert store.get_delivery(delivery)["status"] == "rejected"
    assert github.calls == []
    assert store.all_changes() == []


def test_other_monitor_is_refused(tmp_path):
    github, olostep = fakes()
    worker, store = build(tmp_path, github, olostep)
    delivery = store.add_delivery({**BASELINE, "monitor_id": "monitor_someoneelse"})
    worker.run_once()
    row = store.get_delivery(delivery)
    assert row["status"] == "rejected" and "different monitor" in row["note"]
    assert github.calls == [] and olostep.calls == []


def test_change_opens_one_issue_and_replay_after_restart_does_not(tmp_path):
    github, olostep = fakes()
    worker, store = build(tmp_path, github, olostep)
    store.add_delivery(BASELINE)
    worker.run_once()
    assert github.calls == []

    store.add_delivery(CHANGE_CALLBACK)
    worker.run_once()
    assert len(github.issues) == 1
    row = store.get_change(MONITOR, CHANGE_RUN)
    assert row["state"] == "issue_created"
    record = json.loads(row["record_json"])
    assert record["removed"] == ["customer_id"] and record["added"] == ["account_id"]
    store.close()

    # New process, same database: replay the change callback
    github.calls.clear()
    restarted, store2 = build(tmp_path, github, olostep)
    replay = store2.add_delivery(CHANGE_CALLBACK)
    restarted.run_once()
    assert store2.get_delivery(replay)["status"] == "duplicate"
    assert len(github.issues) == 1
    assert github.calls == []


def test_receiver_rejects_bad_input_without_storing(tmp_path, monkeypatch):
    monkeypatch.setenv("WEBHOOK_PATH_TOKEN", "path-token")
    monkeypatch.setenv("TRACKER_DB", str(tmp_path / "r.db"))
    monkeypatch.setenv("OLOSTEP_MONITOR_ID", MONITOR)
    from app.main import app
    with TestClient(app) as client:
        assert client.post("/hooks/olostep/wrong", json=BASELINE).status_code == 404
        bad = client.post("/hooks/olostep/path-token", content=b"{oops",
                          headers={"content-type": "application/json"})
        assert bad.status_code == 400
        assert client.post("/hooks/olostep/path-token", json=["x"]).status_code == 400
        big = client.post("/hooks/olostep/path-token", content=b"x" * 70000)
        assert big.status_code == 413
        ok = client.post("/hooks/olostep/path-token", json=BASELINE)
        assert ok.status_code == 202
