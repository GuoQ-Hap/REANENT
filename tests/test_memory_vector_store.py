import unittest

from pmc_agent.connectors.vector_database import MilvusConfig
from pmc_agent.memory.types import MemoryRecord
from pmc_agent.memory.vector_store import MemoryMilvusConfig, MilvusMemoryStore, _embedding_text


class FakeEmbeddingClient:
    def embed(self, text):
        return [0.1, 0.2, 0.3]


class FakeCollection:
    def __init__(self):
        self.rows = []
        self.flushed = False

    def insert(self, rows):
        self.rows.extend(rows)

    def flush(self):
        self.flushed = True


class FakeMilvusMemoryStore(MilvusMemoryStore):
    def __init__(self, config, embedding_client):
        super().__init__(config=config, embedding_client=embedding_client)
        self.collection = FakeCollection()

    def _get_collection(self):
        return self.collection


class MemoryVectorStoreTests(unittest.TestCase):
    def test_embedding_text_contains_business_fields(self):
        record = MemoryRecord(
            id="m1",
            memory_type="business_rule",
            scope="project",
            subject_type="rule",
            subject_id="purchase",
            content="采购建议需要展示 MOQ。",
            summary="展示 MOQ",
            tags=["moq"],
            entities={"rule": "MOQ"},
        )
        text = _embedding_text(record)
        self.assertIn("business_rule", text)
        self.assertIn("purchase", text)
        self.assertIn("MOQ", text)

    def test_milvus_store_writes_rows_with_memory_schema(self):
        config = MemoryMilvusConfig(
            milvus=MilvusConfig(
                host="localhost",
                port=19530,
                uri="",
                user="",
                password="",
                database="pmc_memory",
                timeout=1,
                collection_name="pmc_agent_memory",
                vector_dim=3,
                secure=False,
                alias="memory_test",
            ),
            enabled=True,
        )
        store = FakeMilvusMemoryStore(config=config, embedding_client=FakeEmbeddingClient())
        record = MemoryRecord(
            id="m1",
            memory_type="case_lesson",
            scope="project",
            subject_type="playbook",
            subject_id="inventory_snapshot",
            content="库存快照缺失时不要编造。",
            summary="库存缺失保守处理",
            tags=["failure"],
            entities={"tool": "inventory_snapshot"},
        )

        written = store.append_many([record])

        self.assertEqual(written, 1)
        self.assertEqual(store.collection.rows[0]["id"], "m1")
        self.assertEqual(store.collection.rows[0]["embedding"], [0.1, 0.2, 0.3])
        self.assertIn("entities_json", store.collection.rows[0])


if __name__ == "__main__":
    unittest.main()
