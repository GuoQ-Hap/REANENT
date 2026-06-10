import tempfile
import unittest
from pathlib import Path

from pmc_agent.memory.lookup import MemoryLookupTool
from pmc_agent.memory.store import JsonlMemoryStore
from pmc_agent.memory.types import MemoryRecord


class MemoryLookupTests(unittest.TestCase):
    class EmptyVectorStore:
        def search(self, query, limit=5):
            return []

    def test_lookup_finds_relevant_jsonl_memory(self):
        with tempfile.TemporaryDirectory() as tmp:
            store = JsonlMemoryStore(Path(tmp) / "memory.jsonl")
            store.append_many(
                [
                    MemoryRecord(
                        id="m1",
                        memory_type="user_preference",
                        scope="project",
                        subject_type="purchase_verification",
                        subject_id="pmc_agent",
                        content="以后采购建议都要展示 MOQ 和人工确认边界。",
                        summary="采购建议需要展示 MOQ 和人工确认边界。",
                        tags=["moq", "human_confirmation"],
                    )
                ]
            )

            result = MemoryLookupTool(store=store, vector_store=self.EmptyVectorStore()).run(query="采购建议 MOQ", limit=3)

            self.assertTrue(result["ok"])
            self.assertEqual(result["memory_count"], 1)
            self.assertIn("MOQ", result["memories"][0]["summary"])

    def test_lookup_prefers_vector_memory_when_available(self):
        class FakeVectorStore:
            def search(self, query, limit=5):
                return [
                    {
                        "id": "v1",
                        "memory_type": "business_rule",
                        "status": "active",
                        "subject_id": "data_catalog",
                        "summary": "主宽表是月度快照。",
                        "content": "ads_lingxing_all_warehouse_new 月更。",
                    }
                ]

        result = MemoryLookupTool(vector_store=FakeVectorStore()).run(query="主宽表 口径", limit=3)

        self.assertEqual(result["retrieval_source"], "milvus")
        self.assertEqual(result["memory_count"], 1)
        self.assertEqual(result["memories"][0]["id"], "v1")

    def test_lookup_falls_back_to_jsonl_when_vector_fails(self):
        class FailingVectorStore:
            def search(self, query, limit=5):
                raise RuntimeError("vector unavailable")

        with tempfile.TemporaryDirectory() as tmp:
            store = JsonlMemoryStore(Path(tmp) / "memory.jsonl")
            store.append_many(
                [
                    MemoryRecord(
                        id="m1",
                        memory_type="case_lesson",
                        scope="project",
                        subject_type="runtime",
                        subject_id="pmc_agent",
                        content="库存快照缺失时不要编造。",
                        summary="库存快照缺失要保守处理。",
                        tags=["inventory_snapshot"],
                    )
                ]
            )

            result = MemoryLookupTool(store=store, vector_store=FailingVectorStore()).run(query="库存快照 缺失", limit=3)

            self.assertEqual(result["retrieval_source"], "jsonl")
            self.assertEqual(result["memory_count"], 1)


if __name__ == "__main__":
    unittest.main()
