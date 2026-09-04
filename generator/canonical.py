from __future__ import annotations

from hashlib import sha256
import json
from typing import Any


def canonical_json_bytes(value: Any) -> bytes:
    """Serialize benchmark content deterministically without insignificant whitespace."""
    return json.dumps(
        value,
        sort_keys=True,
        separators=(",", ":"),
        ensure_ascii=False,
        allow_nan=False,
    ).encode("utf-8")


def content_sha256(document: dict[str, Any], *, checksum_field: str = "content_sha256") -> str:
    """Hash a document while excluding its self-referential checksum field."""
    content = {key: value for key, value in document.items() if key != checksum_field}
    return sha256(canonical_json_bytes(content)).hexdigest()
