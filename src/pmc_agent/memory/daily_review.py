from __future__ import annotations

from collections import Counter
from dataclasses import dataclass
from datetime import date, datetime
import argparse
import json
from pathlib import Path
import re
from typing import Any

from pmc_agent.memory.store import JsonlMemoryStore
from pmc_agent.memory.types import MemoryRecord
from pmc_agent.memory.review_client import MemoryReviewClient, OpenAIMemoryReviewClient
from pmc_agent.memory.vector_store import MilvusMemoryStore
from pmc_agent.model_io import generate_time_id


DEFAULT_LOG_DIR = Path("logs/model_interactions/conversations")
DEFAULT_REVIEW_DIR = Path("logs/memory_reviews")


@dataclass(frozen=True)
class DailyMemoryReviewResult:
    review_date: str
    conversation_count: int
    interaction_count: int
    error_count: int
    memory_count: int
    milvus_memory_count: int
    review_path: Path
    memory_path: Path


def run_daily_memory_review(
    review_date: date | None = None,
    log_dir: str | Path = DEFAULT_LOG_DIR,
    review_dir: str | Path = DEFAULT_REVIEW_DIR,
    memory_store: JsonlMemoryStore | None = None,
    vector_store: Any | None = None,
    review_client: MemoryReviewClient | None = None,
) -> DailyMemoryReviewResult:
    target_date = review_date or date.today()
    log_path = Path(log_dir)
    review_path = Path(review_dir) / f"{target_date.isoformat()}.md"
    store = memory_store or JsonlMemoryStore()

    conversations = _load_conversations_for_date(log_path, target_date)
    client = review_client or OpenAIMemoryReviewClient()
    draft = client.review(target_date, conversations)
    memories = _dedupe_new_records(draft.memory_records, store.read_all())
    milvus_written_count = (vector_store or MilvusMemoryStore()).append_many(memories)
    written_count = store.append_many(memories)
    review_text = _render_review(target_date, conversations, memories, model_review=draft.review_markdown, milvus_memory_count=milvus_written_count)

    review_path.parent.mkdir(parents=True, exist_ok=True)
    review_path.write_text(review_text, encoding="utf-8")

    return DailyMemoryReviewResult(
        review_date=target_date.isoformat(),
        conversation_count=len(conversations),
        interaction_count=sum(len(item.get("interactions", [])) for item in conversations),
        error_count=sum(1 for item in conversations for interaction in item.get("interactions", []) if interaction.get("error")),
        memory_count=written_count,
        milvus_memory_count=milvus_written_count,
        review_path=review_path,
        memory_path=store.path,
    )


def _load_conversations_for_date(log_dir: Path, target_date: date) -> list[dict[str, Any]]:
    if not log_dir.exists():
        return []
    conversations: list[dict[str, Any]] = []
    for path in sorted(log_dir.glob("*.txt")):
        try:
            record = json.loads(path.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError):
            continue
        interactions = [
            item for item in record.get("interactions", [])
            if _same_date(str(item.get("created_at") or record.get("created_at") or ""), target_date)
        ]
        if interactions:
            conversations.append({**record, "path": str(path), "interactions": interactions})
    return conversations


def _same_date(value: str, target_date: date) -> bool:
    try:
        return datetime.fromisoformat(value).date() == target_date
    except ValueError:
        return False


def _extract_memory_candidates(conversations: list[dict[str, Any]], review_date: date) -> list[MemoryRecord]:
    records: list[MemoryRecord] = []
    for conversation in conversations:
        request_id = str(conversation.get("id") or "")
        text = _conversation_text(conversation)
        lower = text.lower()
        if any(term in text for term in ("以后", "偏好", "口径", "人工确认", "MOQ", "驳回", "反馈")):
            records.append(
                MemoryRecord(
                    id=f"{review_date.isoformat()}_{generate_time_id()}",
                    memory_type="manual_feedback" if "反馈" in text or "驳回" in text else "user_preference",
                    scope="project",
                    subject_type=_infer_subject_type(text),
                    subject_id=_infer_subject_id(text),
                    content=_compact_text(text, 1000),
                    summary=_compact_text(_first_matching_sentence(text), 240),
                    tags=_infer_tags(text),
                    entities=_infer_entities(text),
                    source_request_id=request_id,
                    confidence=0.7,
                )
            )
        if any(term in lower for term in ("httperror", "traceback", "missingmodelargument", "tool_failed")):
            records.append(
                MemoryRecord(
                    id=f"{review_date.isoformat()}_{generate_time_id()}",
                    memory_type="case_lesson",
                    scope="project",
                    subject_type="runtime",
                    subject_id="agentic_loop",
                    content=_compact_text(text, 1000),
                    summary="运行中出现失败或参数缺失，需要在后续编排中复用该修复经验。",
                    tags=["failure", "runtime_review"],
                    entities=_infer_entities(text),
                    source_request_id=request_id,
                    confidence=0.6,
                )
            )
    return records


def _render_review(
    target_date: date,
    conversations: list[dict[str, Any]],
    memories: list[MemoryRecord],
    model_review: str = "",
    milvus_memory_count: int = 0,
) -> str:
    interaction_types = Counter(
        str(interaction.get("interaction_type") or "unknown")
        for conversation in conversations
        for interaction in conversation.get("interactions", [])
    )
    errors = [
        (str(conversation.get("id") or ""), str(interaction.get("error") or ""))
        for conversation in conversations
        for interaction in conversation.get("interactions", [])
        if interaction.get("error")
    ]
    lines = [
        f"# PMC Memory Daily Review - {target_date.isoformat()}",
        "",
        "## Summary",
        "",
        f"- Conversations reviewed: {len(conversations)}",
        f"- Model/tool interactions reviewed: {sum(interaction_types.values())}",
        f"- Errors found: {len(errors)}",
        f"- Long-term memory records written: {len(memories)}",
        f"- Milvus memory records written: {milvus_memory_count}",
        "",
        "## LLM Review",
        "",
        model_review.strip() or "模型未返回额外总结。",
        "",
        "## Interaction Types",
        "",
    ]
    if interaction_types:
        lines.extend(f"- {name}: {count}" for name, count in sorted(interaction_types.items()))
    else:
        lines.append("- No interactions found for this date.")
    lines.extend(["", "## Extracted Memories", ""])
    if memories:
        for record in memories:
            lines.append(f"- [{record.memory_type}] {record.summary} (source={record.source_request_id or '-'})")
    else:
        lines.append("- No durable business memories extracted.")
    lines.extend(["", "## Errors", ""])
    if errors:
        lines.extend(f"- {request_id}: {_compact_text(error, 300)}" for request_id, error in errors)
    else:
        lines.append("- No model/tool errors recorded.")
    lines.extend(["", "## Review Notes", ""])
    lines.append("- Realtime inventory quantities are intentionally excluded from long-term memory.")
    lines.append("- Human feedback, preference, rule wording, and failure lessons are eligible for future retrieval.")
    lines.append("")
    return "\n".join(lines)


def _dedupe_new_records(records: list[MemoryRecord], existing: list[MemoryRecord]) -> list[MemoryRecord]:
    seen = {_memory_key(record) for record in existing}
    unique: list[MemoryRecord] = []
    for record in records:
        key = _memory_key(record)
        if key in seen:
            continue
        seen.add(key)
        unique.append(record)
    return unique


def _memory_key(record: MemoryRecord) -> tuple[str, str, str, str]:
    return (record.memory_type, record.source_request_id, record.subject_id, record.summary)


def _conversation_text(conversation: dict[str, Any]) -> str:
    parts: list[str] = []
    for interaction in conversation.get("interactions", []):
        parts.append(json.dumps(interaction.get("input"), ensure_ascii=False, default=str))
        if interaction.get("error"):
            parts.append(str(interaction["error"]))
    return "\n".join(parts)


def _first_matching_sentence(text: str) -> str:
    for sentence in re.split(r"[。！？\n]", text):
        if any(term in sentence for term in ("以后", "偏好", "口径", "人工确认", "MOQ", "驳回", "反馈")):
            return sentence.strip()
    return text.strip()


def _infer_subject_type(text: str) -> str:
    if re.search(r"\bB0[A-Z0-9]{8}\b", text, re.IGNORECASE):
        return "material"
    if "采购" in text or "MOQ" in text:
        return "purchase_verification"
    if "发货" in text:
        return "shipment_verification"
    return "task_type"


def _infer_subject_id(text: str) -> str:
    match = re.search(r"\bB0[A-Z0-9]{8}\b", text, re.IGNORECASE)
    if match:
        return match.group(0).upper()
    for keyword in ("purchase_verification", "shipment_verification", "inventory_risk"):
        if keyword in text:
            return keyword
    return "pmc_agent"


def _infer_entities(text: str) -> dict[str, str]:
    entities: dict[str, str] = {}
    match = re.search(r"\bB0[A-Z0-9]{8}\b", text, re.IGNORECASE)
    if match:
        entities["material_code"] = match.group(0).upper()
    if "MOQ" in text:
        entities["rule"] = "MOQ"
    return entities


def _infer_tags(text: str) -> list[str]:
    tags: list[str] = ["daily_review"]
    for keyword, tag in (("MOQ", "moq"), ("人工确认", "human_confirmation"), ("口径", "business_definition"), ("反馈", "feedback"), ("驳回", "rejected")):
        if keyword in text:
            tags.append(tag)
    return tags


def _compact_text(text: str, limit: int) -> str:
    normalized = re.sub(r"\s+", " ", text).strip()
    return normalized[:limit]


def main() -> None:
    parser = argparse.ArgumentParser(description="Run the PMC daily memory review.")
    parser.add_argument("--date", help="Review date in YYYY-MM-DD. Defaults to today.")
    args = parser.parse_args()
    target_date = datetime.strptime(args.date, "%Y-%m-%d").date() if args.date else None
    result = run_daily_memory_review(review_date=target_date)
    print(f"Review date: {result.review_date}")
    print(f"Conversations: {result.conversation_count}")
    print(f"Interactions: {result.interaction_count}")
    print(f"Errors: {result.error_count}")
    print(f"Memories written: {result.memory_count}")
    print(f"Milvus memories written: {result.milvus_memory_count}")
    print(f"Review path: {result.review_path}")
    print(f"Memory path: {result.memory_path}")


if __name__ == "__main__":
    main()
