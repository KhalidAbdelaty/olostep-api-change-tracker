"""Fetch the published page without the cache and show which contract it serves."""

import hashlib
from datetime import datetime, timezone

import httpx
from _common import run

from app.classify import extract_contract
from app.config import require


def main() -> None:
    url = require("DOCS_URL")
    response = httpx.get(url, headers={"Cache-Control": "no-cache", "Pragma": "no-cache"},
                         timeout=20, follow_redirects=True)
    contract = extract_contract(response.text)
    digest = hashlib.sha256(response.content).hexdigest()[:12]
    print(f"{datetime.now(timezone.utc).isoformat(timespec='seconds')} HTTP {response.status_code} "
          f"sha256={digest} age={response.headers.get('age')} "
          f"cache-control={response.headers.get('cache-control')}")
    print(f"required={contract.required if contract else None}")


run(main)
