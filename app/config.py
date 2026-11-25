"""Settings read from the environment, plus helpers that keep secrets out of logs."""

import os
import re
from dataclasses import dataclass
from pathlib import Path

OLOSTEP_API_URL = "https://api.olostep.com/v1"
GITHUB_API_URL = "https://api.github.com"
GITHUB_API_VERSION = "2026-03-10"

PROJECT_ROOT = Path(__file__).resolve().parent.parent


class MissingSetting(RuntimeError):
    """Raised when a required environment variable is not set."""


def require(name: str) -> str:
    value = os.environ.get(name, "").strip()
    if not value:
        raise MissingSetting(
            f"{name} is not set. Export it in your shell before you start this command."
        )
    return value


def optional(name: str, default: str = "") -> str:
    return os.environ.get(name, default).strip()


@dataclass(frozen=True)
class Settings:
    monitor_id: str
    webhook_token: str
    github_repo: str
    docs_url: str
    db_path: Path

    @classmethod
    def from_env(cls) -> "Settings":
        return cls(
            monitor_id=optional("OLOSTEP_MONITOR_ID"),
            webhook_token=require("WEBHOOK_PATH_TOKEN"),
            github_repo=optional("GITHUB_REPO"),
            docs_url=optional("DOCS_URL"),
            db_path=Path(optional("TRACKER_DB", str(PROJECT_ROOT / "data" / "tracker.db"))),
        )


SIGNED_QUERY = re.compile(r"(https?://[^\s\"'?]+)\?[^\s\"']*")


def redact_url(url: str) -> str:
    """Drop the query string, which holds the signature on pre-signed URLs."""
    return SIGNED_QUERY.sub(r"\1?<redacted>", url)


def redact_value(value):
    """Return a copy of a JSON value with signed URLs and secrets masked."""
    secrets = [os.environ.get(n, "") for n in ("OLOSTEP_API_KEY", "GITHUB_PAT", "WEBHOOK_PATH_TOKEN")]
    if isinstance(value, dict):
        return {k: redact_value(v) for k, v in value.items()}
    if isinstance(value, list):
        return [redact_value(v) for v in value]
    if isinstance(value, str):
        for secret in secrets:
            if secret and secret in value:
                value = value.replace(secret, "<redacted>")
        return redact_url(value)
    return value


def describe_shape(value, prefix: str = "") -> list[str]:
    """List the key paths and value types of a JSON body, without the values."""
    if isinstance(value, dict):
        lines = []
        for key, item in value.items():
            lines.extend(describe_shape(item, f"{prefix}{key}."))
        return lines or [f"{prefix.rstrip('.')}: dict(empty)"]
    if isinstance(value, list):
        inner = describe_shape(value[0], f"{prefix.rstrip('.')}[].") if value else []
        return [f"{prefix.rstrip('.')}: list[{len(value)}]"] + inner
    return [f"{prefix.rstrip('.')}: {type(value).__name__}"]
