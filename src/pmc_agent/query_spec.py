from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any

from pmc_agent.schema_catalog import FieldPack, normalize_field_pack


@dataclass(frozen=True)
class QuerySpec:
    """受控查询规格。

    上层表达业务意图和字段包，connector 负责把它映射到白名单 SQL。
    """

    intent: str
    material_code: str | None = None
    scope: str = "single_material"
    field_pack: FieldPack = FieldPack.INVENTORY_SNAPSHOT
    filters: dict[str, Any] = field(default_factory=dict)
    limit: int = 50

    @classmethod
    def inventory(
        cls,
        material_code: str | None = None,
        field_pack: FieldPack | str | None = None,
        intent: str = "inventory_snapshot",
        scope: str | None = None,
        filters: dict[str, Any] | None = None,
        limit: int = 50,
    ) -> "QuerySpec":
        return cls(
            intent=intent,
            material_code=material_code,
            scope=scope or ("single_material" if material_code else "portfolio"),
            field_pack=normalize_field_pack(field_pack),
            filters=dict(filters or {}),
            limit=limit,
        )
