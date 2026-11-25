"""GitHub Issues client with a stable marker so a retry can find an Issue it already made."""

import httpx

from .config import GITHUB_API_URL, GITHUB_API_VERSION, require

RETRYABLE_STATUS = {500, 502, 503, 504}


class GitHubRetryable(RuntimeError):
    def __init__(self, message: str, retry_after: float = 60):
        super().__init__(message)
        self.retry_after = retry_after


class GitHubPermanent(RuntimeError):
    pass


def issue_marker(monitor_id: str, run_id: str) -> str:
    return f"<!-- demo-payments-monitor:{monitor_id}:{run_id} -->"


class GitHubClient:
    def __init__(self, repo: str, token: str | None = None,
                 transport: httpx.BaseTransport | None = None):
        if not repo or "/" not in repo:
            raise GitHubPermanent("GITHUB_REPO must look like owner/name")
        self.repo = repo
        self._http = httpx.Client(
            base_url=GITHUB_API_URL,
            headers={
                "Authorization": f"Bearer {token or require('GITHUB_PAT')}",
                "Accept": "application/vnd.github+json",
                "X-GitHub-Api-Version": GITHUB_API_VERSION,
            },
            timeout=20,
            transport=transport,
        )

    def _check(self, response: httpx.Response) -> httpx.Response:
        status = response.status_code
        if status < 400:
            return response
        rate_limited = status == 429 or (
            status == 403 and response.headers.get("x-ratelimit-remaining") == "0"
        )
        if rate_limited:
            wait = float(response.headers.get("retry-after", 60))
            raise GitHubRetryable(f"GitHub rate limit ({status})", retry_after=wait)
        if status in RETRYABLE_STATUS:
            raise GitHubRetryable(f"GitHub server error ({status})")
        message = response.json().get("message", "") if response.content else ""
        raise GitHubPermanent(f"GitHub refused the request ({status}): {message}")

    def find_issue_by_marker(self, marker: str) -> dict | None:
        """Look through the repository's Issues for one whose body has the marker."""
        for page in range(1, 6):
            try:
                response = self._http.get(
                    f"/repos/{self.repo}/issues",
                    params={"state": "all", "per_page": 100, "page": page},
                )
            except httpx.TransportError as exc:
                raise GitHubRetryable(f"GitHub unreachable: {type(exc).__name__}") from exc
            items = self._check(response).json()
            for item in items:
                # The Issues API also returns pull requests, so skip those
                if "pull_request" not in item and marker in (item.get("body") or ""):
                    return item
            if len(items) < 100:
                return None
        return None

    def create_issue(self, title: str, body: str) -> dict:
        try:
            response = self._http.post(
                f"/repos/{self.repo}/issues", json={"title": title, "body": body}
            )
        except httpx.TransportError as exc:
            # The request may or may not have reached GitHub, so reconcile before retrying
            raise GitHubRetryable(f"No response from GitHub: {type(exc).__name__}") from exc
        return self._check(response).json()
