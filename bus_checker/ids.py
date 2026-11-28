"""Deterministic identifiers. The same source fact always gets the same ID, so replays are
idempotent and repeated snapshots of an unchanged vehicle report collapse to one row."""

from __future__ import annotations

import hashlib
import json
import uuid
from typing import Any


def canonical_json(value: Any) -> str:
    return json.dumps(value, sort_keys=True, separators=(",", ":"), ensure_ascii=False, default=str)


def sha256_hex(data: bytes | str) -> str:
    if isinstance(data, str):
        data = data.encode("utf-8")
    return hashlib.sha256(data).hexdigest()


def stable_uuid(*parts: Any) -> str:
    digest = hashlib.sha256(canonical_json(list(parts)).encode("utf-8")).digest()
    return str(uuid.UUID(bytes=digest[:16]))


def new_uuid() -> str:
    return str(uuid.uuid4())
