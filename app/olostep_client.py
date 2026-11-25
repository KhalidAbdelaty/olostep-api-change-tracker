"""Small client for the Olostep Monitors REST API."""

import httpx

from .config import OLOSTEP_API_URL, require


class OlostepError(RuntimeError):
    def __init__(self, status: int, message: str):
        super().__init__(f"Olostep returned {status}: {message}")
        self.status = status


class OlostepClient:
    def __init__(self, api_key: str | None = None, transport: httpx.BaseTransport | None = None):
        key = api_key or require("OLOSTEP_API_KEY")
        self._http = httpx.Client(
            base_url=OLOSTEP_API_URL,
            headers={"Authorization": f"Bearer {key}"},
            timeout=30,
            transport=transport,
        )
        # Pre-signed snapshot URLs must not receive the Olostep key
        self._plain = httpx.Client(timeout=30, transport=transport)

    def _call(self, method: str, path: str, **kwargs) -> tuple[int, dict]:
        response = self._http.request(method, path, **kwargs)
        try:
            body = response.json()
        except ValueError:
            body = {"error": response.text[:200]}
        if response.status_code >= 400:
            raise OlostepError(response.status_code, str(body.get("error", body))[:300])
        return response.status_code, body

    def create_monitor(self, payload: dict) -> tuple[int, dict]:
        return self._call("POST", "/monitors", json=payload)

    def get_monitor(self, monitor_id: str) -> dict:
        return self._call("GET", f"/monitors/{monitor_id}")[1]

    def update_monitor(self, monitor_id: str, payload: dict) -> dict:
        return self._call("POST", f"/monitors/{monitor_id}", json=payload)[1]

    def pause_monitor(self, monitor_id: str) -> dict:
        return self._call("POST", f"/monitors/{monitor_id}/pause")[1]

    def list_events(self, monitor_id: str, limit: int = 25, cursor: str | None = None) -> dict:
        params = {"limit": limit}
        if cursor:
            params["cursor"] = cursor
        return self._call("GET", f"/monitors/{monitor_id}/events", params=params)[1]

    def get_run(self, monitor_id: str, run_id: str) -> dict:
        return self._call("GET", f"/monitors/{monitor_id}/runs/{run_id}")[1]

    def download_snapshot(self, snapshot_url: str) -> dict:
        """Fetch the pre-signed snapshot JSON. The URL expires, so call this right away."""
        response = self._plain.get(snapshot_url)
        response.raise_for_status()
        return response.json()
