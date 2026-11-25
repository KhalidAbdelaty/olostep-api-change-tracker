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
    """Serves one monitor, a fixed events list, and run details shaped like the live API."""

    def __init__(self, monitor_id: str, docs_url: str, events: list[dict],
                 run_content: dict[str, str], baseline_content: str = "stale baseline"):
        self.monitor_id = monitor_id
        self.docs_url = docs_url
        self.events = events
        self.run_content = run_content
        self.baseline_content = baseline_content
        self.calls: list[str] = []

    def handler(self, request: httpx.Request) -> httpx.Response:
        self.calls.append(f"{request.method} {request.url.path}")
        path = request.url.path
        base = f"/v1/monitors/{self.monitor_id}"
        if path == base:
            return httpx.Response(200, json={
                "id": self.monitor_id, "status": "active",
                "tracked": {"type": "urls", "urls": [self.docs_url]},
            })
        if path == f"{base}/events":
            return httpx.Response(200, json={
                "data": self.events, "has_more": False, "next_cursor": None,
                "total_count": len(self.events),
            })
        if path.startswith(f"{base}/runs/"):
            run_id = path.rsplit("/", 1)[1]
            if run_id not in self.run_content:
                return httpx.Response(404, json={"error": "Run not found"})
            return httpx.Response(200, json={
                "monitor_id": self.monitor_id, "run_id": run_id,
                "snapshot": {"run_id": run_id},
                # Node 1 is the fresh scrape, node 3 the stored baseline, as in the live API
                "events": {"results": {
                    "1": {"output": {"kind": "scalar", "markdown": self.run_content[run_id]}},
                    "3": {"output": {"content": self.baseline_content}},
                }},
            })
        return httpx.Response(404, json={"error": "Monitor not found"})

    def transport(self) -> httpx.MockTransport:
        return httpx.MockTransport(self.handler)
