from __future__ import annotations

from typing import Protocol

from pmc_agent.app_logging import get_logger, log_extra
from pmc_agent.domain import InventorySnapshot, Material


logger = get_logger(__name__)


class BusinessSystemConnector(Protocol):
    """ERP、MES、WMS、SRM 和计划系统的连接器边界。"""

    def get_material(self, material_code: str) -> Material | None:
        ...

    def get_inventory_snapshot(self, material_code: str | None = None) -> list[InventorySnapshot]:
        ...

    def record_control_advice(self, material_code: str, advice: list[str]) -> str:
        ...


class ConnectorLogMixin:
    connector_name = "business_system"

    def log_query_started(self, operation: str, material_code: str | None = None) -> None:
        logger.info(
            "connector query started",
            extra=log_extra("connector_query_started", connector=self.connector_name, operation=operation, material_code=material_code or "-"),
        )

    def log_query_completed(self, operation: str, result_size: int) -> None:
        logger.info(
            "connector query completed",
            extra=log_extra("connector_query_completed", connector=self.connector_name, operation=operation, result_size=result_size),
        )

    def log_empty_result(self, operation: str) -> None:
        logger.warning(
            "connector returned empty result",
            extra=log_extra("connector_empty_result", connector=self.connector_name, operation=operation),
        )

    def log_query_failed(self, operation: str) -> None:
        logger.error(
            "connector query failed",
            extra=log_extra("connector_query_failed", connector=self.connector_name, operation=operation),
            exc_info=True,
        )
