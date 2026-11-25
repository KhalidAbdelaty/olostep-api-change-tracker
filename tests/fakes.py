"""Test doubles for GitHub and Olostep, built on httpx.MockTransport."""

import json

import httpx


class FakeGitHub:
    """Pretends to be the GitHub Issues API for one repository.

    fail_next: list of failures to inject on the next create calls, in order.
      "503"            -> GitHub answers 503 and stores nothing
      "timeout_after"  -> GitHub stores the Issue, then the client sees a read timeout
    """

    def __init__(self, fail_next: list[str] | None = None):
        self.issues: list[dict] = []
        self.fail_next = list(fail_next or [])
        self.calls: list[str] = []

    def handler(self, request: httpx.Request) -> httpx.Response:
        self.calls.append(f"{request.method} {request.url.path}")
        assert request.headers["X-GitHub-Api-Version"] == "2026-03-10"
        if request.method == "GET" and request.url.path.endswith("/issues"):
            return httpx.Response(200, json=list(reversed(self.issues)))
        if request.method == "POST" and request.url.path.endswith("/issues"):
            failure = self.fail_next.pop(0) if self.fail_next else None
            if failure == "503":
                return httpx.Response(503, json={"message": "Service Unavailable"})
            data = json.loads(request.content)
            number = len(self.issues) + 1
            issue = {
                "number": number,
                "title": data["title"],
                "body": data["body"],
                "html_url": f"https://github.com/owner/repo/issues/{number}",
            }
            self.issues.append(issue)
            if failure == "timeout_after":
                raise httpx.ReadTimeout("simulated timeout after GitHub stored the Issue")
            return httpx.Response(201, json=issue)
        return httpx.Response(404, json={"message": "Not Found"})

    def transport(self) -> httpx.MockTransport:
        return httpx.MockTransport(self.handler)


class FakeOlostep:
    """Serves one monitor and a fixed list of events. Snapshots are served by URL."""

    def __init__(self, monitor_id: str, docs_url: str, events: list[dict], snapshots: dict):
        self.monitor_id = monitor_id
        self.docs_url = docs_url
        self.events = events
        self.snapshots = snapshots
        self.calls: list[str] = []

    def handler(self, request: httpx.Request) -> httpx.Response:
        self.calls.append(f"{request.method} {request.url.path}")
        path = request.url.path
        if path == f"/v1/monitors/{self.monitor_id}":
            return httpx.Response(200, json={
                "id": self.monitor_id, "status": "active",
                "tracked": {"type": "urls", "urls": [self.docs_url]},
            })
        if path == f"/v1/monitors/{self.monitor_id}/events":
            return httpx.Response(200, json={
                "data": self.events, "has_more": False, "next_cursor": None,
                "total_count": len(self.events),
            })
        if request.url.host == "snapshots.test":
            return httpx.Response(200, json=self.snapshots[path])
        return httpx.Response(404, json={"error": "Monitor not found"})

    def transport(self) -> httpx.MockTransport:
        return httpx.MockTransport(self.handler)
