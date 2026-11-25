"""Background worker: verify stored callbacks, classify them, and open at most one Issue per run."""

import json
import logging
import threading
from datetime import datetime, timezone

from .classify import Decision, decide, extract_contract
from .config import MissingSetting, Settings
from .github_client import GitHubClient, GitHubPermanent, GitHubRetryable, issue_marker
from .olostep_client import OlostepClient, OlostepError
from .store import Store
from .verify import verify_callback

log = logging.getLogger("worker")

UNMATCHED_RETRY_SECONDS = 30
MAX_UNMATCHED_ATTEMPTS = 6


def build_issue(record: dict) -> tuple[str, str]:
    added = ", ".join(f"`{p}`" for p in record["added"]) or "none"
    removed = ", ".join(f"`{p}`" for p in record["removed"]) or "none"
    title = (f"Potential breaking documentation change: {record['endpoint']} "
             f"required parameters changed (pending review)")
    body = f"""The Demo Payments API documentation changed the required request parameters for `{record['endpoint']}`.

This Issue was opened from documentation evidence only. Nobody has confirmed that the live API rejects the old request yet.

| | Required parameters |
| --- | --- |
| Previous snapshot | {', '.join(f'`{p}`' for p in record['previous_required'])} |
| Current snapshot | {', '.join(f'`{p}`' for p in record['current_required'])} |

- Removed: {removed}
- Added: {added}
- Documentation: {record['docs_url']}
- Olostep monitor: `{record['monitor_id']}`
- Olostep run: `{record['run_id']}` (run recorded {record['event_time']})
- Olostep summary: {record['olostep_summary']}

## Review checklist

- [ ] Read the updated documentation page
- [ ] Check the provider changelog or contact the provider
- [ ] Find every call that sends the removed parameters
- [ ] Test the new request against the sandbox before changing production code
- [ ] Close this Issue with a note on what changed, or why nothing needed to

{issue_marker(record['monitor_id'], record['run_id'])}
"""
    return title, body


class Worker:
    def __init__(self, settings: Settings, store: Store,
                 olostep: OlostepClient | None = None, github: GitHubClient | None = None,
                 interval: float = 2.0):
        self.settings = settings
        self.store = store
        self._olostep = olostep
        self._github = github
        self.interval = interval
        self._stop = threading.Event()
        self._thread: threading.Thread | None = None
        self._github_warned = False
        self._olostep_warned = False

    @property
    def olostep(self) -> OlostepClient:
        if self._olostep is None:
            self._olostep = OlostepClient()
        return self._olostep

    @property
    def github(self) -> GitHubClient:
        if self._github is None:
            self._github = GitHubClient(self.settings.github_repo)
        return self._github

    def start(self) -> None:
        self._thread = threading.Thread(target=self._loop, name="worker", daemon=True)
        self._thread.start()

    def stop(self) -> None:
        self._stop.set()
        if self._thread:
            self._thread.join(timeout=10)

    def _loop(self) -> None:
        while not self._stop.is_set():
            try:
                self.run_once()
            except MissingSetting as exc:
                if not self._olostep_warned:
                    log.error("Live path stopped: %s", exc)
                    self._olostep_warned = True
            except Exception:
                log.exception("Worker pass failed, will retry")
            self._stop.wait(self.interval)

    def run_once(self) -> None:
        for row in self.store.due_deliveries():
            self.process_delivery(row)
        for row in self.store.due_issues():
            self.process_issue(row["monitor_id"], row["run_id"])

    # Step 1: verify the callback against the authenticated events list

    def process_delivery(self, row) -> None:
        body = json.loads(row["body_json"])
        try:
            result = verify_callback(body, self.settings.monitor_id,
                                     self.settings.docs_url, self.olostep)
        except OlostepError as exc:
            self.store.update_delivery(row["id"], "unmatched", str(exc),
                                       retry_in=UNMATCHED_RETRY_SECONDS)
            log.warning("Delivery %s: Olostep lookup failed (%s), will retry", row["id"], exc.status)
            return

        if result.status == "rejected":
            self.store.update_delivery(row["id"], "rejected", result.reason)
            log.warning("Delivery %s rejected: %s. No Issue.", row["id"], result.reason)
            return
        if result.status == "unmatched":
            if row["attempts"] + 1 >= MAX_UNMATCHED_ATTEMPTS:
                self.store.update_delivery(row["id"], "rejected", "never matched an event",
                                           result.monitor_id, result.run_id)
                log.warning("Delivery %s never matched an event. No Issue.", row["id"])
            else:
                self.store.update_delivery(row["id"], "unmatched", result.reason,
                                           result.monitor_id, result.run_id,
                                           retry_in=UNMATCHED_RETRY_SECONDS)
                log.info("Delivery %s: %s, retrying", row["id"], result.reason)
            return

        is_new = self.store.claim_change(result.monitor_id, result.run_id, result.event)
        self.store.update_delivery(row["id"], "verified" if is_new else "duplicate",
                                   result.reason, result.monitor_id, result.run_id)
        if not is_new:
            log.info("Delivery %s repeats run %s, already recorded. Skipping.",
                     row["id"], result.run_id)
            return
        log.info("Delivery %s verified: run %s changed=%s", row["id"],
                 result.run_id, result.event.get("changed"))
        self.classify(result.monitor_id, result.run_id, result.event)

    # Step 2: classify the verified run against the previous contract

    def classify(self, monitor_id: str, run_id: str, event: dict) -> Decision:
        snapshot_url = event.get("snapshot_url")
        snapshot = self.olostep.download_snapshot(snapshot_url) if snapshot_url else None
        contract = extract_contract(snapshot) if snapshot is not None else None
        previous = self.store.previous_contract(monitor_id, event.get("created"))
        previous_required = json.loads(previous["required_params"]) if previous else None
        decision = decide(previous_required, contract)

        if contract is not None:
            self.store.save_contract(monitor_id, run_id, event.get("created"),
                                     contract.endpoint, contract.required)

        created = event.get("created")
        record = {
            "monitor_id": monitor_id,
            "run_id": run_id,
            "docs_url": self.settings.docs_url,
            "endpoint": contract.endpoint if contract else "POST /payments",
            "event_time": datetime.fromtimestamp(created, timezone.utc).isoformat()
            if created else "unknown",
            "olostep_changed": bool(event.get("changed")),
            "olostep_summary": (event.get("summary") or "").strip(),
            "previous_required": previous_required or [],
            "current_required": contract.required if contract else [],
            "removed": decision.removed,
            "added": decision.added,
            "decision": decision.label,
            "reason": decision.reason,
            "review_status": "pending_review" if decision.opens_issue else "not_needed",
        }
        state = "issue_pending" if decision.opens_issue else "no_issue"
        self.store.set_decision(monitor_id, run_id, decision.label, record, state)
        log.info("Run %s classified as %s: %s", run_id, decision.label, decision.reason)
        return decision

    # Step 3: open the Issue once, even across retries and restarts

    def process_issue(self, monitor_id: str, run_id: str) -> None:
        try:
            self.github
        except (MissingSetting, GitHubPermanent) as exc:
            if not self._github_warned:
                log.error("Run %s needs an Issue, but the GitHub path is stopped: %s",
                          run_id, exc)
                self._github_warned = True
            return
        previous_state = self.store.start_issue_attempt(monitor_id, run_id)
        if previous_state is None:
            return
        record = json.loads(self.store.get_change(monitor_id, run_id)["record_json"])
        marker = issue_marker(monitor_id, run_id)
        try:
            if previous_state in ("issue_retry", "issue_creating"):
                # An earlier attempt may have reached GitHub, so look before posting again
                existing = self.github.find_issue_by_marker(marker)
                if existing:
                    self.store.finish_issue(monitor_id, run_id, existing["number"],
                                            existing["html_url"])
                    log.info("Run %s: found Issue #%s from an earlier attempt",
                             run_id, existing["number"])
                    return
            title, body = build_issue(record)
            issue = self.github.create_issue(title, body)
        except GitHubRetryable as exc:
            self.store.fail_issue(monitor_id, run_id, str(exc), retry_in=exc.retry_after)
            log.warning("Run %s: %s. Will retry in %ss.", run_id, exc, int(exc.retry_after))
            return
        except GitHubPermanent as exc:
            self.store.fail_issue(monitor_id, run_id, str(exc), retry_in=None)
            log.error("Run %s: %s. Not retrying.", run_id, exc)
            return
        self.store.finish_issue(monitor_id, run_id, issue["number"], issue["html_url"])
        log.info("Run %s: opened Issue #%s", run_id, issue["number"])
