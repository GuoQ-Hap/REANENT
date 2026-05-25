from __future__ import annotations

from dataclasses import dataclass
import json
import os
from typing import Any

from pmc_agent.app_logging import get_logger, log_extra
from pmc_agent.connectors.vector_database import MilvusConfig
from pmc_agent.env import load_env_file
from pmc_agent.memory.embedding import EmbeddingClient, OpenAIEmbeddingClient
from pmc_agent.memory.types import MemoryRecord


logger = get_logger(__name__)


@dataclass(frozen=True)
class MemoryMilvusConfig:
    milvus: MilvusConfig
    auto_create_collection: bool = True
    enabled: bool = False

    @classmethod
    def from_env(cls) -> "MemoryMilvusConfig":
        load_env_file(override=False)
        base = MilvusConfig.from_env()
        memory_database = os.getenv("MILVUS_MEMORY_DATABASE", base.database or "default")
        memory_collection = os.getenv("MILVUS_MEMORY_COLLECTION_NAME", "pmc_agent_memory")
        memory_alias = os.getenv("MILVUS_MEMORY_ALIAS", base.alias)
        memory_dim = int(os.getenv("MILVUS_MEMORY_VECTOR_DIM", os.getenv("VECTOR_DIM", str(base.vector_dim))) or base.vector_dim)
        enabled = str(os.getenv("PMC_AGENT_MEMORY_MILVUS_ENABLED", "false")).strip().lower() in {"1", "true", "yes", "y"}
        auto_create = str(os.getenv("MILVUS_MEMORY_AUTO_CREATE", "true")).strip().lower() in {"1", "true", "yes", "y"}
        return cls(
            milvus=MilvusConfig(
                host=base.host,
                port=base.port,
                uri=base.uri,
                user=base.user,
                password=base.password,
                database=memory_database,
                timeout=base.timeout,
                collection_name=memory_collection,
                vector_dim=memory_dim,
                secure=base.secure,
                alias=memory_alias,
                vector_field=os.getenv("MILVUS_MEMORY_VECTOR_FIELD", base.vector_field),
                title_field="summary",
                content_field="content",
                source_field="source_request_id",
            ),
            auto_create_collection=auto_create,
            enabled=enabled,
        )

    @property
    def ready(self) -> bool:
        return self.enabled and self.milvus.ready


class MilvusMemoryStore:
    def __init__(self, config: MemoryMilvusConfig | None = None, embedding_client: EmbeddingClient | None = None) -> None:
        self.config = config or MemoryMilvusConfig.from_env()
        self.embedding_client = embedding_client
        self._collection: Any | None = None

    def append_many(self, records: list[MemoryRecord]) -> int:
        if not records:
            return 0
        if not self.config.ready:
            logger.info("memory milvus store disabled", extra=log_extra("memory_milvus_store_disabled"))
            return 0
        collection = self._get_collection()
        rows = [self._record_to_row(record) for record in records]
        if not rows:
            return 0
        collection.insert(rows)
        try:
            collection.flush()
        except Exception:
            logger.debug("memory milvus flush skipped", extra=log_extra("memory_milvus_flush_skipped"), exc_info=True)
        logger.info(
            "memory records written to milvus",
            extra=log_extra(
                "memory_milvus_records_written",
                database=self.config.milvus.database,
                collection=self.config.milvus.collection_name,
                record_count=len(rows),
            ),
        )
        return len(rows)

    def _record_to_row(self, record: MemoryRecord) -> dict[str, Any]:
        text = _embedding_text(record)
        if self.embedding_client is None:
            self.embedding_client = OpenAIEmbeddingClient()
        vector = self.embedding_client.embed(text)
        if len(vector) != self.config.milvus.vector_dim:
            raise ValueError(f"memory embedding dimension {len(vector)} does not match MILVUS_MEMORY_VECTOR_DIM={self.config.milvus.vector_dim}.")
        return {
            "id": record.id,
            "memory_type": record.memory_type,
            "scope": record.scope,
            "subject_type": record.subject_type,
            "subject_id": record.subject_id,
            "summary": record.summary,
            "content": record.content,
            "tags_json": json.dumps(record.tags, ensure_ascii=False),
            "entities_json": json.dumps(record.entities, ensure_ascii=False, sort_keys=True),
            "source_request_id": record.source_request_id,
            "confidence": float(record.confidence),
            "status": record.status,
            "created_at": record.created_at,
            "updated_at": record.updated_at,
            "expires_at": record.expires_at or "",
            self.config.milvus.vector_field: vector,
        }

    def _get_collection(self) -> Any:
        if self._collection is not None:
            return self._collection
        try:
            from pymilvus import Collection, CollectionSchema, DataType, FieldSchema, connections, db, utility
        except ImportError as exc:  # pragma: no cover - optional dependency guard
            raise RuntimeError("pymilvus is required for MilvusMemoryStore. Install the vector extra.") from exc

        milvus = self.config.milvus
        kwargs: dict[str, Any] = {
            "alias": milvus.alias,
            "user": milvus.user or None,
            "password": milvus.password or None,
            "db_name": "default",
            "secure": milvus.secure,
            "timeout": milvus.timeout,
        }
        if milvus.uri:
            kwargs["uri"] = milvus.uri
        else:
            kwargs["host"] = milvus.host
            kwargs["port"] = str(milvus.port)
        connections.connect(**{key: value for key, value in kwargs.items() if value is not None})
        self._ensure_database(db, milvus.database, milvus.alias)
        if not utility.has_collection(milvus.collection_name, using=milvus.alias):
            if not self.config.auto_create_collection:
                raise RuntimeError(f"Milvus memory collection {milvus.collection_name!r} does not exist.")
            schema = self._schema(CollectionSchema, FieldSchema, DataType)
            collection = Collection(milvus.collection_name, schema=schema, using=milvus.alias)
            collection.create_index(
                milvus.vector_field,
                {"index_type": "HNSW", "metric_type": "COSINE", "params": {"M": 16, "efConstruction": 200}},
            )
        else:
            collection = Collection(milvus.collection_name, using=milvus.alias)
        collection.load()
        self._collection = collection
        return collection

    def _ensure_database(self, db_module: Any, database: str, alias: str) -> None:
        if not database or database == "default":
            return
        try:
            names = set(db_module.list_database(using=alias))
            if database not in names:
                db_module.create_database(database, using=alias)
            db_module.using_database(database, using=alias)
        except Exception:
            logger.warning("milvus database ensure skipped", extra=log_extra("memory_milvus_database_ensure_skipped", database=database), exc_info=True)

    def _schema(self, CollectionSchema: Any, FieldSchema: Any, DataType: Any) -> Any:
        vector_field = self.config.milvus.vector_field
        fields = [
            FieldSchema(name="id", dtype=DataType.VARCHAR, is_primary=True, max_length=128),
            FieldSchema(name="memory_type", dtype=DataType.VARCHAR, max_length=64),
            FieldSchema(name="scope", dtype=DataType.VARCHAR, max_length=32),
            FieldSchema(name="subject_type", dtype=DataType.VARCHAR, max_length=96),
            FieldSchema(name="subject_id", dtype=DataType.VARCHAR, max_length=160),
            FieldSchema(name="summary", dtype=DataType.VARCHAR, max_length=512),
            FieldSchema(name="content", dtype=DataType.VARCHAR, max_length=4096),
            FieldSchema(name="tags_json", dtype=DataType.VARCHAR, max_length=1024),
            FieldSchema(name="entities_json", dtype=DataType.VARCHAR, max_length=2048),
            FieldSchema(name="source_request_id", dtype=DataType.VARCHAR, max_length=128),
            FieldSchema(name="confidence", dtype=DataType.FLOAT),
            FieldSchema(name="status", dtype=DataType.VARCHAR, max_length=32),
            FieldSchema(name="created_at", dtype=DataType.VARCHAR, max_length=64),
            FieldSchema(name="updated_at", dtype=DataType.VARCHAR, max_length=64),
            FieldSchema(name="expires_at", dtype=DataType.VARCHAR, max_length=64),
            FieldSchema(name=vector_field, dtype=DataType.FLOAT_VECTOR, dim=self.config.milvus.vector_dim),
        ]
        return CollectionSchema(fields=fields, description="PMC agent long-term memory records")


def _embedding_text(record: MemoryRecord) -> str:
    parts = [
        f"type: {record.memory_type}",
        f"scope: {record.scope}",
        f"subject: {record.subject_type}/{record.subject_id}",
        f"summary: {record.summary}",
        f"content: {record.content}",
        f"tags: {', '.join(record.tags)}",
    ]
    if record.entities:
        parts.append(f"entities: {json.dumps(record.entities, ensure_ascii=False, sort_keys=True)}")
    return "\n".join(parts)
