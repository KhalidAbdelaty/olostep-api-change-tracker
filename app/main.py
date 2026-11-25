"""FastAPI receiver for Olostep Monitor callbacks.

The route only stores the callback and returns 202. A worker thread does the
Olostep lookup, the classification, and the GitHub call after the response.
"""

import hmac
import json
import logging
from contextlib import asynccontextmanager

from fastapi import FastAPI, HTTPException, Request

from .config import Settings, describe_shape, redact_value
from .store import Store
from .worker import Worker

MAX_BODY_BYTES = 64 * 1024

class RedactSecrets(logging.Filter):
    """Mask the API keys, the callback path token, and signed URLs in every log line."""

    def filter(self, record: logging.LogRecord) -> bool:
        message = record.getMessage()
        clean = redact_value(message)
        if clean != message:
            record.msg, record.args = clean, ()
        return True


logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(name)s: %(message)s")
for name in ("receiver", "worker", "httpx", "uvicorn.access", "uvicorn.error"):
    logging.getLogger(name).addFilter(RedactSecrets())
log = logging.getLogger("receiver")


@asynccontextmanager
async def lifespan(app: FastAPI):
    settings = Settings.from_env()
    store = Store(settings.db_path)
    worker = Worker(settings, store)
    worker.start()
    app.state.settings = settings
    app.state.store = store
    log.info("Receiver ready. Expected monitor: %s", settings.monitor_id or "<not set yet>")
    yield
    worker.stop()
    store.close()


app = FastAPI(title="Demo Payments API change tracker", lifespan=lifespan)


@app.get("/healthz")
def healthz():
    return {"ok": True}


@app.post("/hooks/olostep/{token}", status_code=202)
async def olostep_callback(token: str, request: Request):
    settings: Settings = request.app.state.settings
    if not hmac.compare_digest(token, settings.webhook_token):
        raise HTTPException(status_code=404)

    raw = await request.body()
    if len(raw) > MAX_BODY_BYTES:
        raise HTTPException(status_code=413, detail="Body too large")
    try:
        body = json.loads(raw)
    except ValueError:
        log.warning("Rejected callback: body is not valid JSON")
        raise HTTPException(status_code=400, detail="Body must be JSON")
    if not isinstance(body, dict):
        log.warning("Rejected callback: JSON body is not an object")
        raise HTTPException(status_code=400, detail="Body must be a JSON object")

    safe_body = redact_value(body)
    delivery_id = request.app.state.store.add_delivery(safe_body)
    log.info("Callback %s stored. Shape: %s", delivery_id, "; ".join(describe_shape(safe_body)))
    return {"received": True, "delivery": delivery_id}
