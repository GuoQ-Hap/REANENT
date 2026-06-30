from __future__ import annotations

from dataclasses import asdict, dataclass, field
import json
from typing import Any


@dataclass(frozen=True)
class ExternalActionSkill:
    """Placeholder boundary for future write-side business actions."""

    name: str
    owner: str
    action_type: str
    description: str
    implemented: bool = False
    required_confirmation: bool = True
    default_payload: dict[str, Any] = field(default_factory=dict)

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)

    def run(self, payload: dict[str, Any] | None = None) -> dict[str, Any]:
        action_payload = {**self.default_payload, **(payload or {})}
        print(
            "[external-action-skill]",
            json.dumps(
                {
                    "skill": self.name,
                    "owner": self.owner,
                    "action_type": self.action_type,
                    "implemented": self.implemented,
                    "payload": action_payload,
                },
                ensure_ascii=False,
                sort_keys=True,
            ),
        )
        return {
            "ok": True,
            "skill": self.name,
            "implemented": self.implemented,
            "status": "printed_placeholder_action",
            "payload": action_payload,
        }


def build_sku_external_action_skills(
    material_code: str,
    *,
    sales_control_summary: str = "",
    replenishment_summary: str = "",
    purchase_summary: str = "",
) -> list[ExternalActionSkill]:
    base_payload = {"material_code": material_code}
    return [
        ExternalActionSkill(
            name="sales_control_placeholder",
            owner="销售",
            action_type="sales_control",
            description="记录控销、限促、广告降档、价格调整等销售侧动作草稿。",
            default_payload={**base_payload, "summary": sales_control_summary},
        ),
        ExternalActionSkill(
            name="logistics_replenishment_placeholder",
            owner="物流",
            action_type="logistics_replenishment",
            description="记录加急空运、普通空运、快船、慢船、调拨或催上架动作草稿。",
            default_payload={**base_payload, "summary": replenishment_summary},
        ),
        ExternalActionSkill(
            name="purchase_order_placeholder",
            owner="采购",
            action_type="purchase_order_draft",
            description="记录采购建议、MOQ、箱规、供应商、交期复核动作草稿。",
            default_payload={**base_payload, "summary": purchase_summary},
        ),
        ExternalActionSkill(
            name="promotion_clearance_placeholder",
            owner="运营/销售",
            action_type="promotion_clearance",
            description="记录冗余清货、促销、提报运营活动或暂停非必要补货动作草稿。",
            default_payload=base_payload,
        ),
    ]


def run_external_action_skill(skill: ExternalActionSkill | dict[str, Any], payload: dict[str, Any] | None = None) -> dict[str, Any]:
    if isinstance(skill, ExternalActionSkill):
        return skill.run(payload)
    rebuilt = ExternalActionSkill(
        name=str(skill.get("name") or "external_action_placeholder"),
        owner=str(skill.get("owner") or "-"),
        action_type=str(skill.get("action_type") or "external_action"),
        description=str(skill.get("description") or ""),
        implemented=bool(skill.get("implemented", False)),
        required_confirmation=bool(skill.get("required_confirmation", True)),
        default_payload=dict(skill.get("default_payload") or {}),
    )
    return rebuilt.run(payload)
