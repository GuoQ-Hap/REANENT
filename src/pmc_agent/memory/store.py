from __future__ import annotations

import json
from pathlib import Path
from typing import Iterable

from pmc_agent.memory.types import MemoryRecord


class JsonlMemoryStore:
    """Append-only local memory store for the first auditable implementation."""

    def __init__(self, path: str | Path = "logs/memory/memory_records.jsonl") -> None:
        self.path = Path(path)

    def append_many(self, records: Iterable[MemoryRecord]) -> int:
        items = list(records)
        if not items:
            return 0
        self.path.parent.mkdir(parents=True, exist_ok=True)
        with self.path.open("a", encoding="utf-8") as handle:
            for record in items:
                handle.write(json.dumps(record.to_dict(), ensure_ascii=False, sort_keys=True))
                handle.write("\n")
        return len(items)

    def read_all(self) -> list[MemoryRecord]:
        if not self.path.exists():
            return []
        records: list[MemoryRecord] = []
        for line in self.path.read_text(encoding="utf-8").splitlines():
            if not line.strip():
                continue
            data = json.loads(line)
            records.append(MemoryRecord(**data))
        return records

