"""Injected GitHub failures. Everything here uses the FakeGitHub test double, never the live API."""

import json

from app.config import Settings
from app.github_client import GitHubClient
from app.store import Store
from app.worker import Worker
from fakes import FakeGitHub

MONITOR = "monitor_test"
RUN = "run_test"


def pending_change(store: Store) -> None:
    store.claim_change(MONITOR, RUN, {"created": 1, "changed": True, "summary": "test"})
    record = {
        "monitor_id": MONITOR, "run_id": RUN, "docs_url": "https://docs.test/",
        "endpoint": "POST /payments", "event_time": "2026-11-25T00:00:00+00:00",
        "olostep_changed": True, "olostep_summary": "test",
        "previous_required": ["amount", "currency", "customer_id"],
        "current_required": ["account_id", "amount", "currency"],
        "removed": ["customer_id"], "added": ["account_id"],
        "decision": "potentially_breaking", "reason": "test", "review_status": "pending_review",
    }
    store.set_decision(MONITOR, RUN, "potentially_breaking", record, "issue_pending")


def make_worker(tmp_path, fake: FakeGitHub) -> tuple[Worker, Store]:
    settings = Settings(MONITOR, "token", "owner/repo", "https://docs.test/", tmp_path / "t.db")
    store = Store(settings.db_path)
    github = GitHubClient("owner/repo", token="test-token", transport=fake.transport())
    return Worker(settings, store, olostep=None, github=github), store


def test_injected_503_is_retried_and_opens_one_issue(tmp_path):
    fake = FakeGitHub(fail_next=["503"])
    worker, store = make_worker(tmp_path, fake)
    pending_change(store)

    worker.process_issue(MONITOR, RUN)
    row = store.get_change(MONITOR, RUN)
    assert row["state"] == "issue_retry"
    assert "503" in row["last_error"]
    assert fake.issues == []

    worker.process_issue(MONITOR, RUN)
    row = store.get_change(MONITOR, RUN)
    assert row["state"] == "issue_created"
    assert row["issue_number"] == 1
    assert len(fake.issues) == 1
    assert "pending review" in fake.issues[0]["title"]


def test_timeout_after_github_accepted_does_not_duplicate(tmp_path):
    fake = FakeGitHub(fail_next=["timeout_after"])
    worker, store = make_worker(tmp_path, fake)
    pending_change(store)

    # GitHub stored the Issue, but the client never saw the 201
    worker.process_issue(MONITOR, RUN)
    assert store.get_change(MONITOR, RUN)["state"] == "issue_retry"
    assert len(fake.issues) == 1

    # The retry finds the marker and records the existing Issue instead of posting again
    worker.process_issue(MONITOR, RUN)
    row = store.get_change(MONITOR, RUN)
    assert row["state"] == "issue_created"
    assert len(fake.issues) == 1
    assert fake.calls.count("POST /repos/owner/repo/issues") == 1


def test_crash_after_create_is_reconciled_after_restart(tmp_path):
    fake = FakeGitHub()
    worker, store = make_worker(tmp_path, fake)
    pending_change(store)

    # Simulate a crash: the attempt started and GitHub created the Issue,
    # but the process died before the local row was updated
    store.start_issue_attempt(MONITOR, RUN)
    title, body = "Potential breaking documentation change", json.dumps({})
    from app.github_client import issue_marker
    fake.issues.append({"number": 1, "title": title,
                        "body": body + issue_marker(MONITOR, RUN),
                        "html_url": "https://github.com/owner/repo/issues/1"})
    store.close()

    # A new process opens the same database file
    restarted, store2 = make_worker(tmp_path, fake)
    assert store2.get_change(MONITOR, RUN)["state"] == "issue_creating"
    restarted.run_once()
    row = store2.get_change(MONITOR, RUN)
    assert row["state"] == "issue_created"
    assert row["issue_number"] == 1
    assert len(fake.issues) == 1
    assert "POST /repos/owner/repo/issues" not in fake.calls


def test_permanent_410_stops_without_retry(tmp_path):
    class IssuesDisabled(FakeGitHub):
        def handler(self, request):
            if request.method == "POST":
                self.calls.append("POST")
                import httpx
                return httpx.Response(410, json={"message": "Issues are disabled for this repo"})
            return super().handler(request)

    fake = IssuesDisabled()
    worker, store = make_worker(tmp_path, fake)
    pending_change(store)
    worker.process_issue(MONITOR, RUN)
    row = store.get_change(MONITOR, RUN)
    assert row["state"] == "issue_failed"
    assert "410" in row["last_error"]
    worker.run_once()
    assert fake.calls.count("POST") == 1
