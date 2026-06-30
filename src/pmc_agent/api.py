from __future__ import annotations

from contextlib import nullcontext
from dataclasses import asdict
import os
from typing import Any
from urllib.parse import quote

from pmc_agent.auth import AuthContext, AuthenticatedUser, FeishuAuthService, UserPermissions, apply_permission_filters, item_allowed
from pmc_agent.connectors.database import StiDatabaseConnector
from pmc_agent.control_tower import control_tower_field_decisions, get_control_tower_summary, get_monthly_forecast_review
from pmc_agent.control_tower_export import build_daily_investigation_workbook, export_filename
from pmc_agent.control_tower_recommendations import build_recommendation_export_workbook, recommendation_export_filename
from pmc_agent.control_tower_sku_investigation import build_sku_investigation_export_workbook, sku_investigation_export_filename
from pmc_agent.external_integrations.feishu import FeishuWorkflowService
from pmc_agent.orchestrator import PmcAgent
from pmc_agent.query_cache import BOTTOM_TABLE_QUERY_CACHE
from pmc_agent.sku_diagnosis import diagnose_sku_full_chain_with_ai, diagnose_sku_payload_with_ai, estimate_sku_shipping_cost
from pmc_agent.workflows import JsonlSkuIssueRepository, SkuIssueWorkflow

try:
    from fastapi import FastAPI
    from fastapi import HTTPException
    from fastapi import Query
    from fastapi import Request
    from fastapi.middleware.cors import CORSMiddleware
    from fastapi.responses import JSONResponse
    from fastapi.responses import RedirectResponse
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
        allow_origin_regex=r"https?://(127\.0\.0\.1|localhost):\d+",
        allow_credentials=True,
        allow_methods=["*"],
        allow_headers=["*"],
        expose_headers=["Content-Disposition"],
    )
    agent = PmcAgent.create_default()
    auth_service = FeishuAuthService()
    sku_diagnosis_connector = StiDatabaseConnector()
    sku_issue_workflow = SkuIssueWorkflow(
        workflow_service=FeishuWorkflowService(),
        repository=JsonlSkuIssueRepository(),
    )

    @app.middleware("http")
    async def auth_middleware(request: Request, call_next):
        if _auth_public_path(request.url.path):
            return await call_next(request)
        context = _auth_context_from_request(request)
        if context is None and auth_service.config.required:
            return JSONResponse(
                {
                    "detail": "authentication required",
                    "login_url": "/auth/feishu/login",
                },
                status_code=401,
            )
        request.state.auth_context = context or AuthContext.anonymous_full_access()
        return await call_next(request)

    class RunRequest(BaseModel):
        text: str

    class SkuDiagnosisAnalyzeRequest(BaseModel):
        item: dict[str, Any]
        question: str = "生成 SKU 全链路诊断"
        refresh: bool = False

    class SkuShippingCostRequest(BaseModel):
        item: dict[str, Any]
        refresh: bool = False

    class FeishuEventRequest(BaseModel):
        payload: dict[str, Any] | None = None

    @app.get("/auth/me")
    def auth_me(http_request: Request) -> dict:
        context = _auth_context_from_request(http_request)
        if context is None:
            context = (
                AuthContext.anonymous_full_access()
                if not auth_service.config.required
                else AuthContext(user=AuthenticatedUser.anonymous(), permissions=UserPermissions(), authenticated=False)
            )
        return context.to_public_dict(auth_required=auth_service.config.required)

    @app.get("/auth/feishu/login")
    def feishu_login(next: str = ""):
        try:
            return RedirectResponse(auth_service.login_url(next))
        except RuntimeError as exc:
            raise HTTPException(status_code=503, detail=str(exc)) from exc

    @app.get("/auth/feishu/callback")
    def feishu_callback(code: str = "", state: str = ""):
        try:
            _, session_token, next_url = auth_service.authenticate_callback(code, state)
        except Exception as exc:
            raise HTTPException(status_code=400, detail=str(exc)) from exc
        response = RedirectResponse(next_url)
        response.set_cookie(
            auth_service.config.session_cookie_name,
            session_token,
            max_age=auth_service.config.session_ttl_seconds,
            httponly=True,
            secure=auth_service.config.cookie_secure,
            samesite="lax",
        )
        return response

    @app.post("/auth/logout")
    def auth_logout():
        response = JSONResponse({"ok": True})
        response.delete_cookie(auth_service.config.session_cookie_name)
        return response

    @app.post("/agent/run")
    def run_agent(payload: RunRequest, http_request: Request) -> dict:
        _require_feature(http_request, "agent_chat")
        return asdict(agent.run(payload.text))

    @app.get("/health")
    def health() -> dict:
        return {"ok": True}

    @app.get("/control-tower/fields")
    def control_tower_fields() -> dict:
        return {"fields": [asdict(item) for item in control_tower_field_decisions()]}

    @app.get("/control-tower/cache-stats")
    def control_tower_cache_stats() -> dict:
        return BOTTOM_TABLE_QUERY_CACHE.snapshot()

    @app.post("/control-tower/cache/clear")
    def control_tower_cache_clear(http_request: Request, reset_stats: bool = True) -> dict:
        _require_feature(http_request, "admin")
        before = BOTTOM_TABLE_QUERY_CACHE.snapshot()
        BOTTOM_TABLE_QUERY_CACHE.clear()
        if reset_stats:
            BOTTOM_TABLE_QUERY_CACHE.reset_stats()
        return {
            "ok": True,
            "cleared_entries": before["entry_count"],
            "reset_stats": reset_stats,
            "before": before,
            "after": BOTTOM_TABLE_QUERY_CACHE.snapshot(),
        }

    @app.get("/control-tower/summary")
    def control_tower_summary(
        http_request: Request,
        material_code: str | None = None,
        country_code: list[str] | None = Query(default=None),
        shipments_country: list[str] | None = Query(default=None),
        store_name: list[str] | None = Query(default=None),
        seasonality: list[str] | None = Query(default=None),
        sales_department: list[str] | None = Query(default=None),
        salesman: list[str] | None = Query(default=None),
        product_manager: list[str] | None = Query(default=None),
        seller_id: list[str] | None = Query(default=None),
        sales_property: list[str] | None = Query(default=None),
        product_property: list[str] | None = Query(default=None),
        msku_status: list[str] | None = Query(default=None),
        msku_life_process: list[str] | None = Query(default=None),
        sales_date: str | None = None,
        sales_start_date: str | None = None,
        sales_end_date: str | None = None,
        risk_type: list[str] | None = Query(default=None),
        risk_only: bool = False,
        positive_demand: bool = False,
        page: int = 1,
        page_size: int = 100,
        max_rows: int = 20000,
        refresh: bool = False,
    ) -> dict:
        filters = {
            "country_code": country_code,
            "shipments_country": shipments_country,
            "store_name": store_name,
            "seasonality": seasonality,
            "sales_apartment": sales_department,
            "salesman": salesman,
            "product_manager": product_manager,
            "seller_id": seller_id,
            "sales_property": sales_property,
            "msku_product_property": product_property,
            "msku_status": msku_status,
            "msku_life_process": msku_life_process,
            "risk_type": risk_type,
            "risk_only": risk_only,
            "positive_demand": positive_demand,
            "order_by": "risk_then_demand",
        }
        _require_feature(http_request, "overview")
        filters = _clean_query_filters(filters)
        filters = _apply_permission_filters_for_request(http_request, filters)
        with _connector_refresh_context(sku_diagnosis_connector, refresh):
            return get_control_tower_summary(
                material_code=material_code,
                filters=filters,
                sales_date=sales_date,
                sales_start_date=sales_start_date,
                sales_end_date=sales_end_date,
                page=page,
                page_size=page_size,
                max_rows=max_rows,
                connector=sku_diagnosis_connector,
            ).to_dict()

    @app.get("/control-tower/monthly-forecast-review")
    def control_tower_monthly_forecast_review(
        http_request: Request,
        material_code: str | None = None,
        msku: str | None = None,
        fnsku: str | None = None,
        asin: str | None = None,
        store_name: str | None = None,
        country_code: str | None = None,
        as_of_date: str | None = None,
        month_offset: int = 2,
        refresh: bool = False,
    ) -> dict:
        _require_feature(http_request, "sku_diagnosis")
        with _connector_refresh_context(sku_diagnosis_connector, refresh):
            return get_monthly_forecast_review(
                material_code=material_code,
                msku=msku,
                fnsku=fnsku,
                asin=asin,
                store_name=store_name,
                country_code=country_code,
                as_of_date=as_of_date,
                month_offset=month_offset,
                connector=sku_diagnosis_connector,
            ).to_dict()

    @app.get("/control-tower/first-leg-shipments")
    def control_tower_first_leg_shipments(
        http_request: Request,
        material_code: str | None = None,
        sku: str | None = None,
        msku: str | None = None,
        fnsku: str | None = None,
        asin: str | None = None,
        latest_only: bool = True,
        limit: int = 200,
        refresh: bool = False,
    ) -> dict:
        _require_feature(http_request, "logistics_detail")
        material_codes = _identity_codes(material_code, sku, msku, fnsku, asin)
        if not material_codes:
            raise HTTPException(status_code=400, detail="material_code、sku、msku、fnsku、asin 至少需要一个。")
        bounded_limit = _api_bounded_limit(limit)
        try:
            with _connector_refresh_context(sku_diagnosis_connector, refresh):
                rows = sku_diagnosis_connector.get_first_leg_shipment_rows(
                    material_codes=material_codes,
                    latest_only=latest_only,
                    limit=bounded_limit,
                )
        except Exception as exc:
            raise HTTPException(status_code=502, detail=str(exc)) from exc
        return {
            "query": {
                "material_codes": material_codes,
                "latest_only": latest_only,
                "limit": bounded_limit,
            },
            "source_tables": [
                "feishu_first_leg_shipment_records",
                "in_transit_shipment_records",
                "dwd_lingxing_fba_report_shipment_detail_incr",
            ],
            "join_paths": [
                "feishu_first_leg_shipment_records.ship_id = in_transit_shipment_records.package_id",
                "feishu_first_leg_shipment_records.ship_id = dwd_lingxing_fba_report_shipment_detail_incr.shipment_confirmation_id",
                "feishu_first_leg_shipment_records.refer_id = dwd_lingxing_fba_report_shipment_detail_incr.amazon_reference_id",
            ],
            "row_count": len(rows),
            "shipments": rows,
        }

    @app.get("/control-tower/sku-diagnosis")
    def control_tower_sku_diagnosis(
        http_request: Request,
        material_code: str,
        store_name: str | None = None,
        country_code: str | None = None,
        shipments_country: str | None = None,
        question: str = "生成 SKU 全链路诊断",
        refresh: bool = False,
    ) -> dict:
        _require_feature(http_request, "sku_diagnosis")
        try:
            with _connector_refresh_context(sku_diagnosis_connector, refresh):
                return diagnose_sku_full_chain_with_ai(
                    material_code=material_code,
                    store_name=store_name,
                    country_code=country_code,
                    shipments_country=shipments_country,
                    question=question,
                    connector=sku_diagnosis_connector,
                )
        except LookupError as exc:
            raise HTTPException(status_code=404, detail=str(exc)) from exc
        except Exception as exc:
            raise HTTPException(status_code=502, detail=str(exc)) from exc

    @app.post("/control-tower/sku-diagnosis/analyze")
    def control_tower_sku_diagnosis_analyze(payload: SkuDiagnosisAnalyzeRequest, http_request: Request) -> dict:
        _require_feature(http_request, "sku_diagnosis")
        _assert_item_allowed(http_request, payload.item)
        try:
            with _connector_refresh_context(sku_diagnosis_connector, payload.refresh):
                return diagnose_sku_payload_with_ai(payload.item, question=payload.question, connector=sku_diagnosis_connector)
        except LookupError as exc:
            raise HTTPException(status_code=404, detail=str(exc)) from exc
        except Exception as exc:
            raise HTTPException(status_code=502, detail=str(exc)) from exc

    @app.post("/control-tower/sku-shipping-cost")
    def control_tower_sku_shipping_cost(payload: SkuShippingCostRequest, http_request: Request) -> dict:
        _require_feature(http_request, "sku_diagnosis")
        _assert_item_allowed(http_request, payload.item)
        try:
            with _connector_refresh_context(sku_diagnosis_connector, payload.refresh):
                return estimate_sku_shipping_cost(payload.item, connector=sku_diagnosis_connector)
        except LookupError as exc:
            raise HTTPException(status_code=404, detail=str(exc)) from exc
        except Exception as exc:
            raise HTTPException(status_code=502, detail=str(exc)) from exc

    @app.get("/control-tower/export/daily-investigation")
    def control_tower_daily_investigation_export(
        http_request: Request,
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
        _require_feature(http_request, "export")
        filters = {key: value for key, value in filters.items() if value not in {None, ""}}
        filters = _apply_permission_filters_for_request(http_request, filters)
        content, _ = build_daily_investigation_workbook(filters=filters, max_rows=max_rows)
        filename = export_filename()
        return Response(
            content=content,
            media_type="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
            headers={
                "Content-Disposition": f'attachment; filename="daily_investigation.xlsx"; filename*=UTF-8\'\'{quote(filename)}'
            },
        )

    @app.get("/control-tower/export/recommendations")
    def control_tower_recommendation_export(
        http_request: Request,
        material_code: str | None = None,
        country_code: list[str] | None = Query(default=None),
        shipments_country: list[str] | None = Query(default=None),
        store_name: list[str] | None = Query(default=None),
        seasonality: list[str] | None = Query(default=None),
        sales_department: list[str] | None = Query(default=None),
        salesman: list[str] | None = Query(default=None),
        product_manager: list[str] | None = Query(default=None),
        seller_id: list[str] | None = Query(default=None),
        sales_property: list[str] | None = Query(default=None),
        product_property: list[str] | None = Query(default=None),
        msku_status: list[str] | None = Query(default=None),
        msku_life_process: list[str] | None = Query(default=None),
        sales_date: str | None = None,
        sales_start_date: str | None = None,
        sales_end_date: str | None = None,
        risk_type: list[str] | None = Query(default=None),
        risk_only: bool = False,
        positive_demand: bool = False,
        max_rows: int = 20000,
    ):
        filters = {
            "country_code": country_code,
            "shipments_country": shipments_country,
            "store_name": store_name,
            "seasonality": seasonality,
            "sales_apartment": sales_department,
            "salesman": salesman,
            "product_manager": product_manager,
            "seller_id": seller_id,
            "sales_property": sales_property,
            "msku_product_property": product_property,
            "msku_status": msku_status,
            "msku_life_process": msku_life_process,
            "risk_type": risk_type,
            "risk_only": risk_only,
            "positive_demand": positive_demand,
            "order_by": "risk_then_demand",
        }
        _require_feature(http_request, "export")
        filters = _clean_query_filters(filters)
        filters = _apply_permission_filters_for_request(http_request, filters)
        content, _ = build_recommendation_export_workbook(
            filters=filters,
            material_code=material_code,
            sales_date=sales_date,
            sales_start_date=sales_start_date,
            sales_end_date=sales_end_date,
            max_rows=max_rows,
            connector=sku_diagnosis_connector,
        )
        filename = recommendation_export_filename()
        return Response(
            content=content,
            media_type="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
            headers={
                "Content-Disposition": f'attachment; filename="recommendations.xlsx"; filename*=UTF-8\'\'{quote(filename)}'
            },
        )

    @app.get("/control-tower/export/sku-investigation")
    def control_tower_sku_investigation_export(
        http_request: Request,
        material_code: str | None = None,
        country_code: list[str] | None = Query(default=None),
        shipments_country: list[str] | None = Query(default=None),
        store_name: list[str] | None = Query(default=None),
        seasonality: list[str] | None = Query(default=None),
        sales_department: list[str] | None = Query(default=None),
        salesman: list[str] | None = Query(default=None),
        product_manager: list[str] | None = Query(default=None),
        seller_id: list[str] | None = Query(default=None),
        sales_property: list[str] | None = Query(default=None),
        product_property: list[str] | None = Query(default=None),
        msku_status: list[str] | None = Query(default=None),
        msku_life_process: list[str] | None = Query(default=None),
        sales_date: str | None = None,
        sales_start_date: str | None = None,
        sales_end_date: str | None = None,
        risk_type: list[str] | None = Query(default=None),
        risk_only: bool = False,
        positive_demand: bool = False,
        max_rows: int = 20000,
    ):
        filters = {
            "country_code": country_code,
            "shipments_country": shipments_country,
            "store_name": store_name,
            "seasonality": seasonality,
            "sales_apartment": sales_department,
            "salesman": salesman,
            "product_manager": product_manager,
            "seller_id": seller_id,
            "sales_property": sales_property,
            "msku_product_property": product_property,
            "msku_status": msku_status,
            "msku_life_process": msku_life_process,
            "risk_type": risk_type,
            "risk_only": risk_only,
            "positive_demand": positive_demand,
            "order_by": "risk_then_demand",
        }
        _require_feature(http_request, "export")
        filters = _clean_query_filters(filters)
        filters = _apply_permission_filters_for_request(http_request, filters)
        content, _ = build_sku_investigation_export_workbook(
            filters=filters,
            material_code=material_code,
            sales_date=sales_date,
            sales_start_date=sales_start_date,
            sales_end_date=sales_end_date,
            max_rows=max_rows,
            connector=sku_diagnosis_connector,
        )
        filename = sku_investigation_export_filename()
        return Response(
            content=content,
            media_type="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
            headers={
                "Content-Disposition": f'attachment; filename="sku_investigation.xlsx"; filename*=UTF-8\'\'{quote(filename)}'
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


def _auth_public_path(path: str) -> bool:
    return (
        path == "/health"
        or path.startswith("/auth/")
        or path in {"/docs", "/redoc", "/openapi.json", "/favicon.ico"}
        or path == "/feishu/events"
    )


def _auth_context_from_request(request: Any) -> AuthContext | None:
    if "auth_service" not in globals():
        return None
    token = request.cookies.get(auth_service.config.session_cookie_name)
    if not token:
        authorization = str(request.headers.get("Authorization") or "")
        if authorization.lower().startswith("bearer "):
            token = authorization.split(" ", 1)[1].strip()
    return auth_service.context_from_session(token)


def _current_auth_context(request: Any) -> AuthContext:
    context = getattr(request.state, "auth_context", None)
    if context is None:
        context = _auth_context_from_request(request)
    return context or AuthContext.anonymous_full_access()


def _require_feature(request: Any, feature: str) -> None:
    context = _current_auth_context(request)
    if not context.permissions.allows_feature(feature):
        raise HTTPException(status_code=403, detail=f"missing feature permission: {feature}")


def _apply_permission_filters_for_request(request: Any, filters: dict[str, Any]) -> dict[str, Any]:
    return apply_permission_filters(filters, _current_auth_context(request).permissions)


def _assert_item_allowed(request: Any, item: dict[str, Any]) -> None:
    if not item_allowed(item, _current_auth_context(request).permissions):
        raise HTTPException(status_code=403, detail="item is outside current user's data scope")


def _identity_codes(*values: str | None) -> list[str]:
    codes: list[str] = []
    for value in values:
        if value is None:
            continue
        for item in str(value).replace("，", ",").split(","):
            text = item.strip()
            if text:
                codes.append(text)
    return list(dict.fromkeys(codes))


def _clean_query_filters(filters: dict[str, Any]) -> dict[str, Any]:
    return {key: value for key, value in filters.items() if _query_value_present(value)}


def _query_value_present(value: Any) -> bool:
    if isinstance(value, (list, tuple, set)):
        return any(item not in {None, ""} for item in value)
    return value not in {None, ""}


def _api_bounded_limit(limit: int) -> int:
    try:
        value = int(limit)
    except (TypeError, ValueError):
        value = 200
    return max(1, min(value, 500))


def _connector_refresh_context(connector: Any, refresh: bool):
    if refresh and hasattr(connector, "force_refreshing"):
        return connector.force_refreshing(True)
    return nullcontext()


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
