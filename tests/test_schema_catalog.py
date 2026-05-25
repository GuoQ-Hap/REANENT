import unittest

from pmc_agent.domain import TaskType
from pmc_agent.query_spec import QuerySpec
from pmc_agent.schema_catalog import ALL_WAREHOUSE_CATALOG, FieldPack, field_pack_for_task, normalize_field_pack


class SchemaCatalogTests(unittest.TestCase):
    def test_field_pack_expands_identity_and_pack_fields(self):
        fields = ALL_WAREHOUSE_CATALOG.fields_for(FieldPack.PURCHASE_VERIFICATION)

        self.assertIn("sku", fields)
        self.assertIn("fnsku", fields)
        self.assertIn("msku_sales_property", fields)
        self.assertIn("seasonality", fields)
        self.assertIn("basic_purchase_quantity", fields)
        self.assertIn("jypurchase_quantity", fields)

    def test_inventory_risk_includes_database_risk_flags(self):
        fields = ALL_WAREHOUSE_CATALOG.fields_for(FieldPack.INVENTORY_RISK)

        self.assertIn("fnsku_out_of_stock_risk_1", fields)
        self.assertIn("fnsku_out_of_stock_risk_6", fields)

    def test_unknown_field_pack_falls_back_to_snapshot(self):
        self.assertEqual(normalize_field_pack("unknown"), FieldPack.INVENTORY_SNAPSHOT)

    def test_task_maps_to_controlled_field_pack(self):
        self.assertEqual(field_pack_for_task(TaskType.SHORTAGE_TRACE), FieldPack.SHORTAGE_TRACE)
        self.assertEqual(field_pack_for_task(TaskType.SHIPMENT_VERIFICATION), FieldPack.SHIPMENT_VERIFICATION)

    def test_query_spec_defaults_scope_from_material_code(self):
        single = QuerySpec.inventory(material_code="A100", field_pack="purchase_verification")
        portfolio = QuerySpec.inventory(filters={"sales_property": "爆"})

        self.assertEqual(single.scope, "single_material")
        self.assertEqual(single.field_pack, FieldPack.PURCHASE_VERIFICATION)
        self.assertEqual(portfolio.scope, "portfolio")
        self.assertEqual(portfolio.filters["sales_property"], "爆")


if __name__ == "__main__":
    unittest.main()
