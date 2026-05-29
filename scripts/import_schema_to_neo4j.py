from __future__ import annotations

import argparse
import json
import os
from pathlib import Path
import sys
from typing import Any


REPO_ROOT = Path(__file__).resolve().parents[1]
SRC_ROOT = REPO_ROOT / "src"
if str(SRC_ROOT) not in sys.path:
    sys.path.insert(0, str(SRC_ROOT))

try:
    from pmc_agent.env import load_env_file
except Exception:  # pragma: no cover - keeps the script usable outside package context.
    load_env_file = None


DEFAULT_SCHEMA_INDEX = Path("D:/laydown/ric-train-master/LDA/data/schema_index.json")
DEFAULT_SCHEMA_RAW = Path("D:/laydown/ric-train-master/LDA/data/schema_raw.json")
DEFAULT_POOL_FILE = REPO_ROOT / "docs" / "inventory_traceability_table_pools.json"


CONCEPT_PATTERNS: tuple[tuple[str, tuple[str, ...]], ...] = (
    ("FNSKU", ("fnsku", "f_n_s_k_u")),
    ("MSKU", ("msku", "seller_sku", "price_list_seller_sku")),
    ("SKU", ("sku", "product_sku")),
    ("ASIN", ("asin",)),
    ("SPU", ("spu",)),
    ("Store", ("store", "store_name", "seller_id", "sid")),
    ("Country", ("country", "marketplace", "nation")),
    ("Warehouse", ("warehouse", "warehouse_name", "wid")),
    ("Date", ("date", "day", "month", "year")),
    ("InventoryQuantity", ("inventory", "quantity", "qty", "num", "stock", "kucun")),
    ("Sales", ("sales", "sale", "销量")),
    ("Forecast", ("forecast", "estimate", "predict", "expected")),
    ("Shipment", ("shipment", "shipping", "fh", "fahuo", "发货")),
    ("Purchase", ("purchase", "caigou", "采购")),
    ("Logistics", ("logistics", "carrier", "channel", "物流")),
    ("Supplier", ("supplier", "vendor", "供应商")),
    ("Rule", ("rule", "frequency", "safety", "oversell", "规则")),
)


def main() -> int:
    parser = argparse.ArgumentParser(
        description="Import data-warehouse schema metadata into Neo4j as a table/field knowledge graph."
    )
    parser.add_argument("--schema-index", default=str(DEFAULT_SCHEMA_INDEX))
    parser.add_argument("--schema-raw", default=str(DEFAULT_SCHEMA_RAW))
    parser.add_argument("--pool-file", default=str(DEFAULT_POOL_FILE))
    parser.add_argument("--database-name", default=None)
    parser.add_argument("--neo4j-uri", default=None)
    parser.add_argument("--neo4j-user", default=None)
    parser.add_argument("--neo4j-password", default=None)
    parser.add_argument("--neo4j-database", default=None)
    parser.add_argument("--limit-tables", type=int, default=0, help="Import only the first N tables for a smoke test.")
    parser.add_argument("--dry-run", action="store_true", help="Only print the planned import summary.")
    parser.add_argument("--clear", action="store_true", help="Delete existing schema metadata graph before importing.")
    args = parser.parse_args()

    if load_env_file:
        load_env_file(override=False)

    schema_index_path = Path(args.schema_index)
    schema_raw_path = Path(args.schema_raw)
    pool_path = Path(args.pool_file)

    schema_index = _read_json(schema_index_path)
    schema_raw = _read_json(schema_raw_path)
    pool_index = _read_json(pool_path) if pool_path.exists() else {}

    import_plan = build_import_plan(
        schema_index=schema_index,
        schema_raw=schema_raw,
        pool_index=pool_index,
        database_name=args.database_name or schema_index.get("database") or "dw_leang",
        limit_tables=args.limit_tables,
    )

    print_summary(import_plan)
    if args.dry_run:
        return 0

    try:
        from neo4j import GraphDatabase
    except ImportError as exc:
        raise SystemExit(
            "Missing dependency: neo4j. Install it with `pip install neo4j` or `pip install -e .[graph]`."
        ) from exc

    uri = args.neo4j_uri or os.getenv("NEO4J_URI", "bolt://10.0.10.106:7687")
    user = args.neo4j_user or os.getenv("NEO4J_USER", "neo4j")
    password = args.neo4j_password or os.getenv("NEO4J_PASSWORD")
    neo4j_database = args.neo4j_database or os.getenv("NEO4J_DATABASE", "neo4j")
    if not password:
        raise SystemExit("Set NEO4J_PASSWORD in .env or pass --neo4j-password.")

    driver = GraphDatabase.driver(uri, auth=(user, password))
    try:
        with driver.session(database=neo4j_database) as session:
            ensure_constraints(session)
            if args.clear:
                clear_schema_graph(session)
            import_schema_graph(session, import_plan)
            print("Import complete.")
    finally:
        driver.close()
    return 0


def _read_json(path: Path) -> dict[str, Any]:
    with path.open("r", encoding="utf-8") as file:
        return json.load(file)


def build_import_plan(
    *,
    schema_index: dict[str, Any],
    schema_raw: dict[str, list[dict[str, Any]]],
    pool_index: dict[str, Any],
    database_name: str,
    limit_tables: int,
) -> dict[str, Any]:
    layer_by_table: dict[str, str] = {}
    description_by_table: dict[str, str] = {}
    for layer_name, layer_data in schema_index.get("layers", {}).items():
        for table_name in layer_data.get("tables", []):
            layer_by_table[table_name] = layer_name
            description_by_table.setdefault(table_name, layer_data.get("description", ""))

    pool_by_table: dict[str, dict[str, Any]] = {}
    for pool_name, tables in pool_index.get("pools", {}).items():
        for table_name, info in tables.items():
            pool_by_table[table_name] = {"pool": pool_name, **info}
            if info.get("layer"):
                layer_by_table.setdefault(table_name, info["layer"])
            if info.get("description"):
                description_by_table.setdefault(table_name, info["description"])

    table_names = sorted(set(schema_raw) | set(layer_by_table) | set(pool_by_table))
    if limit_tables > 0:
        table_names = table_names[:limit_tables]

    tables: list[dict[str, Any]] = []
    fields: list[dict[str, Any]] = []
    concepts: set[str] = set()
    field_concept_edges: list[dict[str, str]] = []
    table_category_edges: list[dict[str, str]] = []

    for table_name in table_names:
        raw_fields = schema_raw.get(table_name, [])
        pool_info = pool_by_table.get(table_name, {})
        categories = [str(value) for value in pool_info.get("categories", [])]
        for category in categories:
            table_category_edges.append({"table": table_name, "category": category})

        tables.append(
            {
                "name": table_name,
                "database": database_name,
                "layer": layer_by_table.get(table_name, "UNKNOWN"),
                "description": description_by_table.get(table_name, ""),
                "field_count": len(raw_fields) or int(pool_info.get("column_count") or 0),
                "source": _table_source(table_name, schema_raw, pool_by_table),
            }
        )

        for ordinal, field in enumerate(raw_fields, start=1):
            field_id = f"{table_name}.{field.get('name', '')}"
            field_row = {
                "id": field_id,
                "table": table_name,
                "name": str(field.get("name", "")),
                "ordinal": ordinal,
                "type": str(field.get("type", "")),
                "nullable": str(field.get("null", "")),
                "is_key": str(field.get("key", "")).upper() in {"YES", "PRI", "MUL", "UNI"},
                "default": "" if field.get("default") is None else str(field.get("default")),
                "extra": str(field.get("extra", "")),
                "comment": str(field.get("comment", "")),
            }
            fields.append(field_row)

            for concept in detect_concepts(field_row["name"], field_row["comment"]):
                concepts.add(concept)
                field_concept_edges.append({"field_id": field_id, "concept": concept})

    return {
        "database": {"name": database_name, "description": schema_index.get("database_description", "")},
        "layers": sorted(set(layer_by_table.values()) | {"UNKNOWN"}),
        "tables": tables,
        "fields": fields,
        "concepts": sorted(concepts),
        "field_concept_edges": field_concept_edges,
        "table_category_edges": table_category_edges,
    }


def _table_source(
    table_name: str,
    schema_raw: dict[str, list[dict[str, Any]]],
    pool_by_table: dict[str, dict[str, Any]],
) -> str:
    if table_name in schema_raw and table_name in pool_by_table:
        return "schema_json+table_plan"
    if table_name in schema_raw:
        return "schema_json"
    return "table_plan"


def detect_concepts(field_name: str, comment: str) -> list[str]:
    haystack = f"{field_name} {comment}".lower()
    matched: list[str] = []
    for concept, patterns in CONCEPT_PATTERNS:
        if any(pattern.lower() in haystack for pattern in patterns):
            matched.append(concept)
    return matched


def print_summary(import_plan: dict[str, Any]) -> None:
    layer_count = len(import_plan["layers"])
    table_count = len(import_plan["tables"])
    field_count = len(import_plan["fields"])
    concept_count = len(import_plan["concepts"])
    category_edge_count = len(import_plan["table_category_edges"])
    concept_edge_count = len(import_plan["field_concept_edges"])
    print(
        "Planned Neo4j metadata import: "
        f"{layer_count} layers, {table_count} tables, {field_count} fields, "
        f"{concept_count} field concepts, {category_edge_count} table-category edges, "
        f"{concept_edge_count} field-concept edges."
    )


def ensure_constraints(session: Any) -> None:
    statements = [
        "CREATE CONSTRAINT metadata_database_name IF NOT EXISTS FOR (n:Database) REQUIRE n.name IS UNIQUE",
        "CREATE CONSTRAINT metadata_layer_name IF NOT EXISTS FOR (n:DataLayer) REQUIRE n.name IS UNIQUE",
        "CREATE CONSTRAINT metadata_table_name IF NOT EXISTS FOR (n:DataTable) REQUIRE n.name IS UNIQUE",
        "CREATE CONSTRAINT metadata_field_id IF NOT EXISTS FOR (n:DataField) REQUIRE n.id IS UNIQUE",
        "CREATE CONSTRAINT metadata_concept_name IF NOT EXISTS FOR (n:FieldConcept) REQUIRE n.name IS UNIQUE",
        "CREATE CONSTRAINT metadata_category_name IF NOT EXISTS FOR (n:BusinessCategory) REQUIRE n.name IS UNIQUE",
    ]
    for statement in statements:
        session.run(statement).consume()


def clear_schema_graph(session: Any) -> None:
    session.run(
        """
        MATCH (n)
        WHERE n:Database OR n:DataLayer OR n:DataTable OR n:DataField
           OR n:FieldConcept OR n:BusinessCategory
        DETACH DELETE n
        """
    ).consume()


def import_schema_graph(session: Any, import_plan: dict[str, Any]) -> None:
    session.execute_write(_merge_database, import_plan["database"])
    for layer in import_plan["layers"]:
        session.execute_write(_merge_layer, import_plan["database"]["name"], layer)
    for concept in import_plan["concepts"]:
        session.execute_write(_merge_concept, concept)
    for table in import_plan["tables"]:
        session.execute_write(_merge_table, table)
    for field in import_plan["fields"]:
        session.execute_write(_merge_field, field)
    for edge in import_plan["field_concept_edges"]:
        session.execute_write(_merge_field_concept_edge, edge)
    for edge in import_plan["table_category_edges"]:
        session.execute_write(_merge_table_category_edge, edge)


def _merge_database(tx: Any, database: dict[str, str]) -> None:
    tx.run(
        """
        MERGE (db:Database {name: $name})
        SET db.description = $description
        """,
        **database,
    ).consume()


def _merge_layer(tx: Any, database_name: str, layer_name: str) -> None:
    tx.run(
        """
        MERGE (db:Database {name: $database_name})
        MERGE (layer:DataLayer {name: $layer_name})
        MERGE (db)-[:HAS_LAYER]->(layer)
        """,
        database_name=database_name,
        layer_name=layer_name,
    ).consume()


def _merge_concept(tx: Any, concept: str) -> None:
    tx.run("MERGE (:FieldConcept {name: $concept})", concept=concept).consume()


def _merge_table(tx: Any, table: dict[str, Any]) -> None:
    tx.run(
        """
        MERGE (table:DataTable {name: $name})
        SET table.database = $database,
            table.description = $description,
            table.field_count = $field_count,
            table.source = $source
        MERGE (layer:DataLayer {name: $layer})
        MERGE (layer)-[:HAS_TABLE]->(table)
        """,
        **table,
    ).consume()


def _merge_field(tx: Any, field: dict[str, Any]) -> None:
    tx.run(
        """
        MERGE (field:DataField {id: $id})
        SET field.name = $name,
            field.ordinal = $ordinal,
            field.type = $type,
            field.nullable = $nullable,
            field.is_key = $is_key,
            field.default = $default,
            field.extra = $extra,
            field.comment = $comment
        MERGE (table:DataTable {name: $table})
        MERGE (table)-[:HAS_FIELD {ordinal: $ordinal}]->(field)
        """,
        **field,
    ).consume()


def _merge_field_concept_edge(tx: Any, edge: dict[str, str]) -> None:
    tx.run(
        """
        MATCH (field:DataField {id: $field_id})
        MERGE (concept:FieldConcept {name: $concept})
        MERGE (field)-[:MEANS]->(concept)
        """,
        **edge,
    ).consume()


def _merge_table_category_edge(tx: Any, edge: dict[str, str]) -> None:
    tx.run(
        """
        MATCH (table:DataTable {name: $table})
        MERGE (category:BusinessCategory {name: $category})
        MERGE (table)-[:RELATED_TO_CATEGORY]->(category)
        """,
        **edge,
    ).consume()


if __name__ == "__main__":
    raise SystemExit(main())
