"""Create the monitor that watches the Demo Payments API page."""

from _common import run, show

from app.config import require
from app.olostep_client import OlostepClient

QUERY = (
    "Watch the Demo Payments API reference page at {url}. Report a change only when "
    "the documented request contract for POST /payments changes: a required request "
    "parameter is added, removed, or renamed, the endpoint path or method changes, or "
    "the authentication requirement changes. Ignore styling, layout, wording, typo, and "
    "punctuation edits that leave the contract the same."
)


def main() -> None:
    docs_url = require("DOCS_URL")
    payload = {
        "query": QUERY.format(url=docs_url),
        "frequency": "every 10 minutes",
        "source_policy": {"include_urls": [docs_url]},
    }
    status, monitor = OlostepClient().create_monitor(payload)
    print(f"HTTP {status}")
    show(monitor)


run(main)
