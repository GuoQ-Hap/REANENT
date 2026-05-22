from __future__ import annotations

from dataclasses import dataclass


@dataclass(frozen=True)
class InventoryPolicy:
    critical_days_of_cover: float = 3
    high_risk_days_of_cover: float = 7
    medium_risk_days_of_cover: float = 14
    default_daily_demand: float = 1


@dataclass(frozen=True)
class AgentConfig:
    inventory_policy: InventoryPolicy = InventoryPolicy()
    max_tool_calls: int = 12
    require_human_approval_for: tuple[str, ...] = (
        "delete_order",
        "release_purchase_order",
        "change_production_plan",
    )
