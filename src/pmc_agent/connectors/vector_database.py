from __future__ import annotations

from dataclasses import dataclass
import os
from typing import Any

from pmc_agent.app_logging import get_logger, log_extra
from pmc_agent.connectors.base import ConnectorLogMixin
from pmc_agent.env import load_env_file


logger = get_logger(__name__)


@dataclass(frozen=True)
class MilvusConfig:
    host: str
    port: int
    uri: str
    user: str
    password: str
    database: str
    timeout: float
    collection_name: str
    vector_dim: int
    secure: bool
    alias: str
    vector_field: str = "embedding"
    title_field: str = "title"
    content_field: str = "text"
    source_field: str = "file_name"

    @classmethod
    def from_env(cls) -> "MilvusConfig":
        load_env_file(override=False)
        return cls(
            host=os.getenv("MILVUS_HOST", ""),
            port=int(os.getenv("MILVUS_PORT", "19530") or 19530),
            uri=os.getenv("MILVUS_URI", ""),
            user=os.getenv("MILVUS_USER", ""),
            password=os.getenv("MILVUS_PASSWORD", ""),
            database=os.getenv("MILVUS_DATABASE", "default"),
            timeout=float(os.getenv("MILVUS_TIMEOUT", "10") or 10),
            collection_name=os.getenv("MILVUS_COLLECTION_NAME", "leang_documents"),
            vector_dim=int(os.getenv("VECTOR_DIM", "768") or 768),
            secure=str(os.getenv("MILVUS_SECURE", "false")).strip().lower() in {"1", "true", "yes", "y"},
            alias=os.getenv("MILVUS_ALIAS", "default"),
            vector_field=os.getenv("MILVUS_VECTOR_FIELD", "embedding"),
            title_field=os.getenv("MILVUS_TITLE_FIELD", "title"),
            content_field=os.getenv("MILVUS_CONTENT_FIELD", "text"),
            source_field=os.getenv("MILVUS_SOURCE_FIELD", "file_name"),
        )

    @property
    def ready(self) -> bool:
        return bool(self.collection_name and (self.uri or (self.host and self.port)))


class MilvusVectorConnector(ConnectorLogMixin):
    connector_name = "milvus_vector_database"

    def __init__(self, config: MilvusConfig | None = None) -> None:
        self.config = config or MilvusConfig.from_env()
        self._collection: Any | None = None

    def search(self, query: str, query_vector: list[float] | None = None, limit: int = 5) -> list[dict[str, Any]]:
        if not self.config.ready:
            logger.info("milvus connector disabled", extra=log_extra("milvus_connector_disabled"))
            return []
        self.log_query_started("knowledge_search")
        try:
            collection = self._get_collection()
            vector_field = self._resolve_vector_field(collection)
            expected_dim = self._resolve_vector_dim(collection, vector_field)
            if query_vector is None:
                snippets = self._query_text(collection, query, limit)
                self.log_query_completed("knowledge_search", len(snippets))
                return snippets
            if len(query_vector) != expected_dim:
                raise ValueError(f"query_vector dimension {len(query_vector)} does not match Milvus field {vector_field} dim={expected_dim}.")
            output_fields = self._resolve_output_fields(collection)
            results = collection.search(
                data=[query_vector],
                anns_field=vector_field,
                param={"metric_type": "COSINE", "params": {"nprobe": 10}},
                limit=max(1, min(int(limit or 5), 20)),
                output_fields=output_fields,
            )
            snippets = [_hit_to_snippet(hit, output_fields) for hit in (results[0] if results else [])]
            self.log_query_completed("knowledge_search", len(snippets))
            return snippets
        except Exception:
            self.log_query_failed("knowledge_search")
            raise

    def _get_collection(self) -> Any:
        if self._collection is not None:
            return self._collection
        try:
            from pymilvus import Collection, connections
        except ImportError as exc:  # pragma: no cover - optional dependency guard
            raise RuntimeError("pymilvus is required for MilvusVectorConnector. Install the vector extra.") from exc

        kwargs: dict[str, Any] = {
            "alias": self.config.alias,
            "user": self.config.user or None,
            "password": self.config.password or None,
            "db_name": self.config.database or "default",
            "secure": self.config.secure,
            "timeout": self.config.timeout,
        }
        if self.config.uri:
            kwargs["uri"] = self.config.uri
        else:
            kwargs["host"] = self.config.host
            kwargs["port"] = str(self.config.port)
        connections.connect(**{key: value for key, value in kwargs.items() if value is not None})
        collection = Collection(self.config.collection_name, using=self.config.alias)
        collection.load()
        self._collection = collection
        return collection

    def _resolve_vector_field(self, collection: Any) -> str:
        schema_fields = getattr(getattr(collection, "schema", None), "fields", []) or []
        field_names = [str(getattr(field, "name", "")) for field in schema_fields]
        if self.config.vector_field in field_names:
            return self.config.vector_field
        for field in schema_fields:
            dtype = str(getattr(field, "dtype", "")).upper()
            if "VECTOR" in dtype:
                return str(getattr(field, "name"))
        return self.config.vector_field

    def _resolve_output_fields(self, collection: Any) -> list[str]:
        schema_fields = getattr(getattr(collection, "schema", None), "fields", []) or []
        field_names = {str(getattr(field, "name", "")) for field in schema_fields}
        preferred = [
            self.config.title_field,
            self.config.content_field,
            self.config.source_field,
            "content",
            "source",
            "text",
            "file_name",
        ]
        return [field for field in preferred if field in field_names]

    def _resolve_vector_dim(self, collection: Any, vector_field: str) -> int:
        schema_fields = getattr(getattr(collection, "schema", None), "fields", []) or []
        for field in schema_fields:
            if str(getattr(field, "name", "")) != vector_field:
                continue
            params = getattr(field, "params", {}) or {}
            try:
                return int(params.get("dim") or self.config.vector_dim)
            except (TypeError, ValueError):
                return self.config.vector_dim
        return self.config.vector_dim

    def _query_text(self, collection: Any, query: str, limit: int) -> list[dict[str, Any]]:
        query = str(query or "").strip()
        if not query:
            return []
        output_fields = self._resolve_output_fields(collection)
        if self.config.content_field not in output_fields:
            logger.info("milvus text query skipped without content field", extra=log_extra("milvus_text_query_no_content_field"))
            return []
        expr = f'{self.config.content_field} like "%{_escape_like_value(query[:64])}%"'
        rows = collection.query(
            expr=expr,
            output_fields=output_fields,
            limit=max(1, min(int(limit or 5), 20)),
        )
        return [_row_to_snippet(row) for row in rows]


def _hit_to_snippet(hit: Any, output_fields: list[str]) -> dict[str, Any]:
    entity = getattr(hit, "entity", None)
    data: dict[str, Any] = {}
    for field in output_fields:
        try:
            data[field] = entity.get(field) if entity is not None else None
        except Exception:
            data[field] = None
    return {
        "title": str(data.get("title") or data.get("file_name") or data.get("source") or getattr(hit, "id", "Milvus result")),
        "content": str(data.get("content") or data.get("text") or ""),
        "source": str(data.get("source") or data.get("file_name") or ""),
        "score": float(getattr(hit, "score", 0.0) or 0.0),
    }


def _row_to_snippet(row: dict[str, Any]) -> dict[str, Any]:
    return {
        "title": str(row.get("title") or row.get("file_name") or row.get("source") or "Milvus result"),
        "content": str(row.get("content") or row.get("text") or ""),
        "source": str(row.get("source") or row.get("file_name") or ""),
        "score": 0.0,
    }


def _escape_like_value(value: str) -> str:
    return value.replace("\\", "\\\\").replace('"', '\\"')
