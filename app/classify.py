"""Decide whether a verified run changed the documented contract of POST /payments."""

import re
from dataclasses import dataclass, field

ENDPOINT = "POST /payments"

# One documented row: the name, its type, then Required or Optional.
# Cells may be split by pipes, HTML table cells, or line breaks (Olostep's markdown).
SEP = r"(?:\s*\|\s*|\s*</t[dh]>\s*<t[dh][^>]*>\s*|\s*\n\s*)"
ROW = re.compile(
    r"`?\b([a-z][a-z0-9_]*)\b`?(?:</code>)?" + SEP
    + r"(?:string|integer|number|boolean|object|array)" + SEP + r"(Required|Optional)\b",
    re.IGNORECASE,
)


@dataclass
class Contract:
    endpoint: str
    required: list[str]
    optional: list[str] = field(default_factory=list)


def extract_contract(text: str | None) -> Contract | None:
    """Read the required and optional request parameters of POST /payments."""
    if not text or "/payments" not in text:
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
        return Decision("unclassified", False,
                        reason="no POST /payments contract found in the captured page")
    if previous is None:
        return Decision("baseline", False, reason="first verified contract for this monitor")
    removed = sorted(set(previous) - set(current.required))
    added = sorted(set(current.required) - set(previous))
    if not removed and not added:
        return Decision("no_contract_change", False,
                        reason="required parameters match the previous snapshot")
    return Decision("potentially_breaking", True, removed, added,
                    reason="required request parameters changed")
