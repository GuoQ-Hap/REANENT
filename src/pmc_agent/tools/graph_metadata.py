from __future__ import annotations

from dataclasses import dataclass
import os
from typing import Any

from pmc_agent.app_logging import get_logger, log_extra
from pmc_agent.env import load_env_file


logger = get_logger(__name__)


@dataclass
class GraphMetadataTool:
    """Read table and field metadata from the Neo4j schema knowledge graph."""

    uri: str | None = None
    user: str | None = None
    password: str | None = None
    database: str | None = None
    name: str = "graph_metadata_lookup"
    description: str = "Query Neo4j table/field metadata graph with controlled read-only lookups."

    def run(
        self,
        query_type: str = "",
        table_name: str = "",
        concept: str = "",
        keyword: str = "",
        query: str = "",
        limit: int = 20,
        **_: Any,
    ) -> dict[str, Any]:
        query_type = (query_type or "").strip()
        limit = max(1, min(int(limit or 20), 200))
        if query_type == "describe_table":
            if not table_name.strip():
                return _missing("table_name", query_type)
            rows = self._execute(_describe_table_cypher(), {"table_name": table_name.strip(), "limit": limit})
            return {"mode": query_type, "table_name": table_name.strip(), "fields": rows, "row_count": len(rows)}
        if query_type == "find_tables_by_concept":
            resolved_concept = _normalize_concept(concept or keyword or query or table_name)
            if not resolved_concept:
                return _missing("concept", query_type)
            rows = self._execute(_find_tables_by_concept_cypher(), {"concept": resolved_concept, "limit": limit})
            return {"mode": query_type, "concept": resolved_concept, "tables": rows, "row_count": len(rows)}
        if query_type == "find_fields":
            keyword = (keyword or query or concept).strip()
            if not keyword:
                return _missing("keyword", query_type)
            rows = self._execute(_find_fields_cypher(), {"keyword": keyword.strip().lower(), "limit": limit})
            return {"mode": query_type, "keyword": keyword.strip(), "fields": rows, "row_count": len(rows)}
        return {
            "ok": False,
            "error_type": "UnsupportedGraphMetadataQuery",
            "error": "query_type must be one of: describe_table, find_tables_by_concept, find_fields.",
        }

    def _execute(self, cypher: str, parameters: dict[str, Any]) -> list[dict[str, Any]]:
        try:
            from neo4j import GraphDatabase
        except ImportError as exc:
            raise RuntimeError("Neo4j driver is not installed. Install with `pip install neo4j`.") from exc

        load_env_file(override=False)
        uri = self.uri or os.getenv("NEO4J_URI")
        user = self.user or os.getenv("NEO4J_USER", "neo4j")
        password = self.password or os.getenv("NEO4J_PASSWORD")
        database = self.database or os.getenv("NEO4J_DATABASE", "neo4j")
        if not uri or not password:
            raise RuntimeError("NEO4J_URI and NEO4J_PASSWORD are required for graph metadata lookup.")

        driver = GraphDatabase.driver(uri, auth=(user, password))
        try:
            with driver.session(database=database) as session:
                result = [dict(record) for record in session.run(cypher, parameters)]
        finally:
            driver.close()
        logger.info(
            "graph metadata lookup completed",
            extra=log_extra("graph_metadata_lookup_completed", result_size=len(result)),
        )
        return result


def _missing(argument_name: str, query_type: str) -> dict[str, Any]:
    return {
        "ok": False,
        "error_type": "MissingGraphMetadataArgument",
        "error": f"{query_type} requires {argument_name}.",
        "supported_concepts": sorted(set(CONCEPT_ALIASES.values())),
    }


CONCEPT_ALIASES = {
    "fnsku": "FNSKU",
    "f_n_s_k_u": "FNSKU",
    "msku": "MSKU",
    "sku": "SKU",
    "asin": "ASIN",
    "spu": "SPU",
    "store": "Store",
    "店铺": "Store",
    "country": "Country",
    "国家": "Country",
    "warehouse": "Warehouse",
    "仓库": "Warehouse",
    "date": "Date",
    "日期": "Date",
    "inventory": "InventoryQuantity",
    "stock": "InventoryQuantity",
    "库存": "InventoryQuantity",
    "销量": "Sales",
    "销售": "Sales",
    "sales": "Sales",
    "forecast": "Forecast",
    "预测": "Forecast",
    "shipment": "Shipment",
    "shipping": "Shipment",
    "发货": "Shipment",
    "purchase": "Purchase",
    "采购": "Purchase",
    "logistics": "Logistics",
    "物流": "Logistics",
    "supplier": "Supplier",
    "供应商": "Supplier",
    "rule": "Rule",
    "规则": "Rule",
}


def _normalize_concept(value: str) -> str:
    text = (value or "").strip()
    if not text:
        return ""
    if text in set(CONCEPT_ALIASES.values()):
        return text
    lower_text = text.lower()
    if lower_text in CONCEPT_ALIASES:
        return CONCEPT_ALIASES[lower_text]
    for alias, concept in CONCEPT_ALIASES.items():
        if alias in lower_text or alias in text:
            return concept
    return ""


def _describe_table_cypher() -> str:
    return """
    MATCH (t:DataTable {name: $table_name})
    OPTIONAL MATCH (layer:DataLayer)-[:HAS_TABLE]->(t)
    OPTIONAL MATCH (t)-[:RELATED_TO_CATEGORY]->(category:BusinessCategory)
    WITH t, layer, collect(DISTINCT category.name) AS categories
    OPTIONAL MATCH (t)-[rel:HAS_FIELD]->(field:DataField)
    OPTIONAL MATCH (field)-[:MEANS]->(concept:FieldConcept)
    WITH t, layer, categories, field, rel, collect(DISTINCT concept.name) AS concepts
    RETURN
      t.name AS table,
      layer.name AS layer,
      categories AS categories,
      field.name AS field,
      field.type AS type,
      field.comment AS comment,
      field.is_key AS is_key,
      concepts AS concepts,
      rel.ordinal AS ordinal
    ORDER BY ordinal
    LIMIT $limit
    """


def _find_tables_by_concept_cypher() -> str:
    return """
    MATCH (t:DataTable)-[:HAS_FIELD]->(field:DataField)-[:MEANS]->(:FieldConcept {name: $concept})
    OPTIONAL MATCH (layer:DataLayer)-[:HAS_TABLE]->(t)
    WITH t, layer, collect(DISTINCT field.name) AS fields
    RETURN
      t.name AS table,
      layer.name AS layer,
      fields[0..8] AS matched_fields,
      size(fields) AS matched_field_count
    ORDER BY
      CASE layer WHEN 'ADS-应用数据层' THEN 0 WHEN 'DWS-汇总数据层' THEN 1 WHEN 'DWD-明细数据层' THEN 2 WHEN 'DIM-维度表' THEN 3 WHEN 'ODS-操作数据层' THEN 4 ELSE 5 END,
      matched_field_count DESC,
      table
    LIMIT $limit
    """


def _find_fields_cypher() -> str:
    return """
    MATCH (t:DataTable)-[:HAS_FIELD]->(field:DataField)
    WHERE toLower(field.name) CONTAINS $keyword OR toLower(coalesce(field.comment, '')) CONTAINS $keyword
    OPTIONAL MATCH (layer:DataLayer)-[:HAS_TABLE]->(t)
    OPTIONAL MATCH (field)-[:MEANS]->(concept:FieldConcept)
    WITH t, layer, field, collect(DISTINCT concept.name) AS concepts
    RETURN
      t.name AS table,
      layer.name AS layer,
      field.name AS field,
      field.type AS type,
      field.comment AS comment,
      concepts AS concepts
    ORDER BY
      CASE layer WHEN 'ADS-应用数据层' THEN 0 WHEN 'DWS-汇总数据层' THEN 1 WHEN 'DWD-明细数据层' THEN 2 WHEN 'DIM-维度表' THEN 3 WHEN 'ODS-操作数据层' THEN 4 ELSE 5 END,
      table,
      field
    LIMIT $limit
    """
