from __future__ import annotations

from dataclasses import dataclass
import json
import re
from typing import Any

from pmc_agent.app_logging import get_logger, log_extra
from pmc_agent.memory.store import JsonlMemoryStore
from pmc_agent.memory.types import MemoryRecord
from pmc_agent.memory.vector_store import MilvusMemoryStore


logger = get_logger(__name__)


@dataclass
class MemoryLookupTool:
    """Retrieve durable project memories from the local auditable JSONL store."""

    store: JsonlMemoryStore | None = None
    vector_store: MilvusMemoryStore | None = None
    name: str = "memory_lookup"
    description: str = "Retrieve durable user preferences, business rules, feedback, and failure lessons."

    def run(
        self,
        query: str = "",
        memory_type: str = "",
        subject_id: str = "",
        limit: int = 5,
        **_: Any,
    ) -> dict[str, Any]:
        query = str(query or "").strip()
        memory_type = str(memory_type or "").strip()
        subject_id = str(subject_id or "").strip()
        limit = max(1, min(int(limit or 5), 20))
        if not query and not memory_type and not subject_id:
            return {
                "ok": False,
                "error_type": "MissingMemoryLookupQuery",
                "error": "memory_lookup requires query, memory_type, or subject_id.",
            }

        vector_memories = self._search_vector(query=query, memory_type=memory_type, subject_id=subject_id, limit=limit)
        if vector_memories:
            return {
                "ok": True,
                "mode": "memory_lookup",
                "retrieval_source": "milvus",
                "query": query,
                "memory_type": memory_type,
                "subject_id": subject_id,
                "memories": vector_memories,
                "memory_count": len(vector_memories),
            }

        records = (self.store or JsonlMemoryStore()).read_all()
        matches = [
            (score, record)
            for record in records
            if _filter_record(record, memory_type=memory_type, subject_id=subject_id)
            for score in [_score_record(record, query)]
            if score > 0 or not query
        ]
        matches.sort(key=lambda item: (item[0], item[1].updated_at), reverse=True)
        memories = [_record_to_result(record, score) for score, record in matches[:limit]]
        logger.info(
            "memory lookup completed",
            extra=log_extra("memory_lookup_completed", result_size=len(memories), query_present=bool(query)),
        )
        return {
            "ok": True,
            "mode": "memory_lookup",
            "retrieval_source": "jsonl",
            "query": query,
            "memory_type": memory_type,
            "subject_id": subject_id,
            "memories": memories,
            "memory_count": len(memories),
        }

    def _search_vector(self, query: str, memory_type: str, subject_id: str, limit: int) -> list[dict[str, Any]]:
        if not query:
            return []
        vector_store = self.vector_store or MilvusMemoryStore()
        try:
            rows = vector_store.search(query=query, limit=limit)
        except Exception as exc:
            logger.warning("memory vector lookup failed; falling back to jsonl", extra=log_extra("memory_vector_lookup_failed", error_type=type(exc).__name__))
            return []
        filtered = [
            row for row in rows
            if str(row.get("status") or "active") == "active"
            and (not memory_type or row.get("memory_type") == memory_type)
            and (not subject_id or row.get("subject_id") == subject_id)
        ]
        return filtered[:limit]


def _filter_record(record: MemoryRecord, memory_type: str, subject_id: str) -> bool:
    if record.status != "active":
        return False
    if memory_type and record.memory_type != memory_type:
        return False
    if subject_id and record.subject_id != subject_id:
        return False
    return True


def _score_record(record: MemoryRecord, query: str) -> int:
    if not query:
        return 1
    terms = _terms(query)
    if not terms:
        return 1
    haystacks = {
        "summary": record.summary,
        "content": record.content,
        "tags": " ".join(record.tags),
        "entities": json.dumps(record.entities, ensure_ascii=False, sort_keys=True),
        "subject": f"{record.subject_type} {record.subject_id} {record.memory_type}",
    }
    score = 0
    for term in terms:
        lowered = term.lower()
        if lowered in haystacks["summary"].lower():
            score += 5
        if lowered in haystacks["content"].lower():
            score += 3
        if lowered in haystacks["tags"].lower():
            score += 4
        if lowered in haystacks["entities"].lower():
            score += 4
        if lowered in haystacks["subject"].lower():
            score += 2
    return score


def _terms(query: str) -> list[str]:
    raw_terms = re.findall(r"[\w\u4e00-\u9fff]+", query)
    return [term for term in raw_terms if len(term) > 1 or re.search(r"[\u4e00-\u9fff]", term)]


def _record_to_result(record: MemoryRecord, score: int) -> dict[str, Any]:
    return {
        "id": record.id,
        "memory_type": record.memory_type,
        "scope": record.scope,
        "subject_type": record.subject_type,
        "subject_id": record.subject_id,
        "summary": record.summary,
        "content": record.content,
        "tags": record.tags,
        "entities": record.entities,
        "source_request_id": record.source_request_id,
        "confidence": record.confidence,
        "score": score,
        "updated_at": record.updated_at,
        "retrieval_source": "jsonl",
    }
