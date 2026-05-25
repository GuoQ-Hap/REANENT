import json
import tempfile
import unittest
from datetime import date
from pathlib import Path

from pmc_agent.memory.daily_review import run_daily_memory_review
from pmc_agent.memory.store import JsonlMemoryStore
from pmc_agent.memory.types import MemoryRecord
from pmc_agent.memory.review_client import MemoryReviewDraft


class FakeMemoryReviewClient:
    def review(self, review_date, conversations):
        records = []
        if conversations:
            records.append(
                MemoryRecord(
                    id="fake-1",
                    memory_type="user_preference",
                    scope="project",
                    subject_type="purchase_verification",
                    subject_id="pmc_agent",
                    content="以后采购建议都要展示 MOQ 和人工确认边界",
                    summary="采购建议需要展示 MOQ 和人工确认边界。",
                    tags=["daily_review", "moq", "human_confirmation"],
                    entities={"rule": "MOQ"},
                    source_request_id="req-1",
                    confidence=0.8,
                )
            )
        return MemoryReviewDraft(review_markdown="## 模型总结\n- 已完成每日记忆审查。", memory_records=records)


class FakeVectorStore:
    def __init__(self):
        self.records = []

    def append_many(self, records):
        self.records.extend(records)
        return len(records)


class DailyMemoryReviewTests(unittest.TestCase):
    def test_daily_review_writes_summary_and_memory_records(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            log_dir = root / "logs" / "model_interactions" / "conversations"
            log_dir.mkdir(parents=True)
            record = {
                "id": "req-1",
                "created_at": "2026-05-22T08:00:00",
                "interactions": [
                    {
                        "interaction_type": "agentic_orchestration",
                        "created_at": "2026-05-22T08:01:00",
                        "input": {"request": "以后采购建议都要展示 MOQ 和人工确认边界"},
                        "output": {"ok": True},
                        "error": None,
                    }
                ],
            }
            (log_dir / "req-1.txt").write_text(json.dumps(record, ensure_ascii=False), encoding="utf-8")

            store = JsonlMemoryStore(root / "logs" / "memory" / "memory_records.jsonl")
            vector_store = FakeVectorStore()
            result = run_daily_memory_review(
                review_date=date(2026, 5, 22),
                log_dir=log_dir,
                review_dir=root / "logs" / "memory_reviews",
                memory_store=store,
                vector_store=vector_store,
                review_client=FakeMemoryReviewClient(),
            )

            self.assertEqual(result.conversation_count, 1)
            self.assertEqual(result.interaction_count, 1)
            self.assertEqual(result.memory_count, 1)
            self.assertEqual(result.milvus_memory_count, 1)
            self.assertTrue(result.review_path.exists())
            self.assertIn("Long-term memory records written: 1", result.review_path.read_text(encoding="utf-8"))
            self.assertIn("Milvus memory records written: 1", result.review_path.read_text(encoding="utf-8"))
            records = store.read_all()
            self.assertEqual(records[0].memory_type, "user_preference")
            self.assertIn("moq", records[0].tags)
            rerun = run_daily_memory_review(
                review_date=date(2026, 5, 22),
                log_dir=log_dir,
                review_dir=root / "logs" / "memory_reviews",
                memory_store=store,
                vector_store=vector_store,
                review_client=FakeMemoryReviewClient(),
            )
            self.assertEqual(rerun.memory_count, 0)
            self.assertEqual(rerun.milvus_memory_count, 0)
            self.assertEqual(len(store.read_all()), 1)

    def test_daily_review_ignores_other_dates(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            log_dir = root / "logs" / "model_interactions" / "conversations"
            log_dir.mkdir(parents=True)
            record = {
                "id": "req-old",
                "created_at": "2026-05-21T08:00:00",
                "interactions": [
                    {
                        "interaction_type": "summary",
                        "created_at": "2026-05-21T08:01:00",
                        "input": {"request": "以后都按 MSKU 口径"},
                    }
                ],
            }
            (log_dir / "req-old.txt").write_text(json.dumps(record, ensure_ascii=False), encoding="utf-8")

            result = run_daily_memory_review(
                review_date=date(2026, 5, 22),
                log_dir=log_dir,
                review_dir=root / "logs" / "memory_reviews",
                memory_store=JsonlMemoryStore(root / "logs" / "memory" / "memory_records.jsonl"),
                vector_store=FakeVectorStore(),
                review_client=FakeMemoryReviewClient(),
            )

            self.assertEqual(result.conversation_count, 0)
            self.assertEqual(result.memory_count, 0)


if __name__ == "__main__":
    unittest.main()
