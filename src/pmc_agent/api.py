from __future__ import annotations

from dataclasses import asdict
import os
from typing import Any
from urllib.parse import quote

from pmc_agent.control_tower import control_tower_field_decisions, get_control_tower_summary
from pmc_agent.control_tower_export import build_daily_investigation_workbook, export_filename
from pmc_agent.external_integrations.feishu import FeishuWorkflowService
from pmc_agent.orchestrator import PmcAgent
from pmc_agent.workflows import JsonlSkuIssueRepository, SkuIssueWorkflow

try:
    from fastapi import FastAPI
    from fastapi import HTTPException
    from fastapi.middleware.cors import CORSMiddleware
    from fastapi.responses import Response
    from pydantic import BaseModel
except ImportError:  # pragma: no cover - optional integration surface
    FastAPI = None
    HTTPException = None
    BaseModel = object


if FastAPI:
    app = FastAPI(title="PMC Supply Chain Control Agent")
    app.add_middleware(
        CORSMiddleware,
        allow_origins=["http://127.0.0.1:5173", "http://localhost:5173"],
        allow_credentials=True,
        allow_methods=["*"],
        allow_headers=["*"],
        expose_headers=["Content-Disposition"],
    )
    agent = PmcAgent.create_default()
    sku_issue_workflow = SkuIssueWorkflow(
        workflow_service=FeishuWorkflowService(),
        repository=JsonlSkuIssueRepository(),
    )

    class RunRequest(BaseModel):
        text: str

    class FeishuEventRequest(BaseModel):
        payload: dict[str, Any] | None = None

    @app.post("/agent/run")
    def run_agent(request: RunRequest) -> dict:
        return asdict(agent.run(request.text))

    @app.get("/health")
    def health() -> dict:
        return {"ok": True}

    @app.get("/control-tower/fields")
    def control_tower_fields() -> dict:
        return {"fields": [asdict(item) for item in control_tower_field_decisions()]}

    @app.get("/control-tower/summary")
    def control_tower_summary(
        material_code: str | None = None,
        country_code: str | None = None,
        shipments_country: str | None = None,
        store_name: str | None = None,
        sales_property: str | None = None,
        sales_date: str | None = None,
        sales_start_date: str | None = None,
        sales_end_date: str | None = None,
        risk_type: str | None = None,
        risk_only: bool = False,
        positive_demand: bool = False,
        page: int = 1,
        page_size: int = 100,
        max_rows: int = 20000,
    ) -> dict:
        filters = {
            "country_code": country_code,
            "shipments_country": shipments_country,
            "store_name": store_name,
            "sales_property": sales_property,
            "risk_type": risk_type,
            "risk_only": risk_only,
            "positive_demand": positive_demand,
            "order_by": "risk_then_demand",
        }
        filters = {key: value for key, value in filters.items() if value not in {None, ""}}
        return get_control_tower_summary(
            material_code=material_code,
            filters=filters,
            sales_date=sales_date,
            sales_start_date=sales_start_date,
            sales_end_date=sales_end_date,
            page=page,
            page_size=page_size,
            max_rows=max_rows,
        ).to_dict()

    @app.get("/control-tower/export/daily-investigation")
    def control_tower_daily_investigation_export(
        country_code: str | None = None,
        shipments_country: str | None = None,
        store_name: str | None = None,
        sales_property: str | None = None,
        max_rows: int = 20000,
    ):
        filters = {
            "country_code": country_code,
            "shipments_country": shipments_country,
            "store_name": store_name,
            "sales_property": sales_property,
        }
        filters = {key: value for key, value in filters.items() if value not in {None, ""}}
        content, _ = build_daily_investigation_workbook(filters=filters, max_rows=max_rows)
        filename = export_filename()
        return Response(
            content=content,
            media_type="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
            headers={
                "Content-Disposition": f'attachment; filename="daily_investigation.xlsx"; filename*=UTF-8\'\'{quote(filename)}'
            },
        )

    @app.post("/feishu/events")
    def feishu_events(payload: dict[str, Any]) -> dict:
        challenge = _feishu_challenge_response(payload)
        if challenge is not None:
            return challenge
        _verify_feishu_event_token(payload)
        normalized = _normalize_feishu_event_payload(payload)
        try:
            issue = sku_issue_workflow.handle_feishu_callback(normalized)
        except KeyError as exc:
            raise HTTPException(status_code=404, detail=str(exc)) from exc
        except ValueError as exc:
            raise HTTPException(status_code=400, detail=str(exc)) from exc
        return {
            "ok": True,
            "issue_id": issue.issue_id,
            "sku": issue.sku,
            "status": issue.status,
            "reminder_count": issue.reminder_count,
        }
else:
    app = None


def _feishu_challenge_response(payload: dict[str, Any]) -> dict[str, Any] | None:
    if payload.get("challenge"):
        return {"challenge": payload.get("challenge")}
    event = payload.get("event") if isinstance(payload.get("event"), dict) else {}
    if event.get("challenge"):
        return {"challenge": event.get("challenge")}
    return None


def _verify_feishu_event_token(payload: dict[str, Any]) -> None:
    expected = os.getenv("FEISHU_EVENT_VERIFICATION_TOKEN", "").strip()
    if not expected:
        return
    header = payload.get("header") if isinstance(payload.get("header"), dict) else {}
    token = str(payload.get("token") or header.get("token") or "")
    if token != expected:
        raise HTTPException(status_code=403, detail="invalid feishu event token")


def _normalize_feishu_event_payload(payload: dict[str, Any]) -> dict[str, Any]:
    event = payload.get("event") if isinstance(payload.get("event"), dict) else {}
    action = event.get("action") if isinstance(event.get("action"), dict) else payload.get("action")
    action_value = action.get("value") if isinstance(action, dict) and isinstance(action.get("value"), dict) else {}
    form_value = action.get("form_value") if isinstance(action, dict) and isinstance(action.get("form_value"), dict) else {}
    operator = event.get("operator") if isinstance(event.get("operator"), dict) else payload.get("operator")
    operator_id = operator.get("operator_id") if isinstance(operator, dict) and isinstance(operator.get("operator_id"), dict) else {}
    context = event.get("context") if isinstance(event.get("context"), dict) else {}
    value = payload.get("value") if isinstance(payload.get("value"), dict) else {}
    fields = {**dict(value), **dict(action_value), **dict(form_value), **dict(payload.get("fields") or {})}
    return {
        "source": payload.get("source") or payload.get("type") or "feishu_review",
        "workflow_id": payload.get("workflow_id") or payload.get("message_id") or context.get("open_message_id") or "",
        "request_id": payload.get("request_id") or fields.get("request_id") or "",
        "action": payload.get("action") or fields.get("action") or "",
        "operator_open_id": payload.get("operator_open_id") or _operator_open_id(operator, operator_id),
        "comment": payload.get("comment") or fields.get("comment") or "",
        "fields": fields,
    }


def _operator_open_id(operator: Any, operator_id: dict[str, Any]) -> str:
    if isinstance(operator, dict):
        return str(operator.get("open_id") or operator.get("operator_open_id") or operator_id.get("open_id") or "")
    return ""
