from __future__ import annotations

from dataclasses import asdict, dataclass, field
from datetime import datetime, timezone
from typing import Any


@dataclass(frozen=True)
class MemoryRecord:
    """A reusable PMC memory extracted from audited runtime records."""

    id: str
    memory_type: str
    scope: str
    subject_type: str
    subject_id: str
    content: str
    summary: str
    tags: list[str] = field(default_factory=list)
    entities: dict[str, str] = field(default_factory=dict)
    source_request_id: str = ""
    confidence: float = 0.5
    status: str = "active"
    created_at: str = field(default_factory=lambda: datetime.now(timezone.utc).isoformat())
    updated_at: str = field(default_factory=lambda: datetime.now(timezone.utc).isoformat())
    expires_at: str | None = None

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)

