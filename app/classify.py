"""Decide whether a verified run changed the documented contract of POST /payments."""

import re
from dataclasses import dataclass, field

ENDPOINT = "POST /payments"

# One documented row looks like: customer_id | string | Required | ...
ROW = re.compile(
    r"`?\b([a-z][a-z0-9_]*)\b`?(?:</code>)?\s*(?:\||</t[dh]>\s*<t[dh][^>]*>)\s*"
    r"(?:string|integer|number|boolean|object|array)\s*"
    r"(?:\||</t[dh]>\s*<t[dh][^>]*>)\s*(Required|Optional)",
    re.IGNORECASE,
)


@dataclass
class Contract:
    endpoint: str
    required: list[str]
    optional: list[str] = field(default_factory=list)


def snapshot_text(snapshot) -> str:
    """Join every string in the snapshot JSON so the row pattern can scan it."""
    if isinstance(snapshot, dict):
        return "\n".join(snapshot_text(v) for v in snapshot.values())
    if isinstance(snapshot, list):
        return "\n".join(snapshot_text(v) for v in snapshot)
    return snapshot if isinstance(snapshot, str) else ""


def extract_contract(snapshot) -> Contract | None:
    text = snapshot_text(snapshot)
    if "/payments" not in text:
        return None
    required, optional = [], []
    for name, flag in ROW.findall(text):
        bucket = required if flag.lower() == "required" else optional
        if name not in bucket:
            bucket.append(name)
    if not required:
        return None
    return Contract(ENDPOINT, sorted(required), sorted(optional))


@dataclass
class Decision:
    label: str  # baseline, no_contract_change, potentially_breaking, unclassified
    opens_issue: bool
    removed: list[str] = field(default_factory=list)
    added: list[str] = field(default_factory=list)
    reason: str = ""


def decide(previous: list[str] | None, current: Contract | None) -> Decision:
    if current is None:
        return Decision("unclassified", False, reason="no POST /payments contract found in the snapshot")
    if previous is None:
        return Decision("baseline", False, reason="first verified contract for this monitor")
    removed = sorted(set(previous) - set(current.required))
    added = sorted(set(current.required) - set(previous))
    if not removed and not added:
        return Decision("no_contract_change", False,
                        reason="required parameters match the previous snapshot")
    return Decision("potentially_breaking", True, removed, added,
                    reason="required request parameters changed")
