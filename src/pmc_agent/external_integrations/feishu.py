from __future__ import annotations

from concurrent.futures import ThreadPoolExecutor
from dataclasses import dataclass, field
import hashlib
import json
import os
import re
import threading
import time
import urllib.error
import urllib.request
from typing import Any, Callable, Protocol

from pmc_agent.app_logging import get_logger, log_extra
from pmc_agent.env import load_env_file
from pmc_agent.orchestrator import PmcAgent
from pmc_agent.response_formatter import format_agent_reply


logger = get_logger(__name__)


@dataclass(frozen=True)
class FeishuConfig:
    enabled: bool = False
    app_id: str = ""
    app_secret: str = ""
    bot_name: str = "PMC库存智能体"
    max_workers: int = 4
    max_message_length: int = 3500
    api_base_url: str = "https://open.feishu.cn"

    @classmethod
    def from_env(cls) -> "FeishuConfig":
        load_env_file(override=False)
        return cls(
            enabled=_env_bool("FEISHU_ENABLED", False),
            app_id=os.getenv("FEISHU_APP_ID", ""),
            app_secret=os.getenv("FEISHU_APP_SECRET", ""),
            bot_name=os.getenv("FEISHU_BOT_NAME", "PMC库存智能体"),
            max_workers=_env_int("FEISHU_MAX_WORKERS", 4, minimum=1, maximum=16),
            max_message_length=_env_int("FEISHU_MAX_MESSAGE_LENGTH", 3500, minimum=500, maximum=12000),
            api_base_url=os.getenv("FEISHU_API_BASE_URL", "https://open.feishu.cn").rstrip("/"),
        )

    @property
    def ready(self) -> bool:
        return self.enabled and bool(self.app_id and self.app_secret)


@dataclass(frozen=True)
class FeishuWorkflowConfig:
    review_enabled: bool = True
    approval_enabled: bool = False
    review_mode: str = "card_or_approval"
    default_review_chat_id: str = ""
    purchase_review_chat_id: str = ""
    shipment_review_chat_id: str = ""
    case_followup_chat_id: str = ""
    purchase_approval_code: str = ""
    shipment_approval_code: str = ""
    case_close_approval_code: str = ""
    default_approval_code: str = ""
    approval_start_open_id: str = ""
    approval_start_user_id: str = ""
    approval_free_node_id: str = ""
    purchase_approval_node_id: str = ""
    shipment_approval_node_id: str = ""
    case_close_approval_node_id: str = ""
    approval_business_types: tuple[str, ...] = ("purchase_confirmation", "shipment_confirmation", "case_close")
    approval_risk_levels: tuple[str, ...] = ("critical", "high")

    @classmethod
    def from_env(cls) -> "FeishuWorkflowConfig":
        load_env_file(override=False)
        return cls(
            review_enabled=_env_bool("FEISHU_REVIEW_ENABLED", True),
            approval_enabled=_env_bool("FEISHU_APPROVAL_ENABLED", False),
            review_mode=os.getenv("FEISHU_REVIEW_MODE", "card_or_approval"),
            default_review_chat_id=os.getenv("FEISHU_DEFAULT_CHAT_ID", ""),
            purchase_review_chat_id=os.getenv("FEISHU_PURCHASE_REVIEW_CHAT_ID", ""),
            shipment_review_chat_id=os.getenv("FEISHU_SHIPMENT_REVIEW_CHAT_ID", ""),
            case_followup_chat_id=os.getenv("FEISHU_CASE_FOLLOWUP_CHAT_ID", ""),
            purchase_approval_code=os.getenv("FEISHU_APPROVAL_PURCHASE_CODE", ""),
            shipment_approval_code=os.getenv("FEISHU_APPROVAL_SHIPMENT_CODE", ""),
            case_close_approval_code=os.getenv("FEISHU_APPROVAL_CASE_CLOSE_CODE", ""),
            default_approval_code=os.getenv("FEISHU_APPROVAL_DEFAULT_CODE", ""),
            approval_start_open_id=os.getenv("FEISHU_APPROVAL_START_OPEN_ID", ""),
            approval_start_user_id=os.getenv("FEISHU_APPROVAL_START_USER_ID", ""),
            approval_free_node_id=os.getenv("FEISHU_APPROVAL_FREE_NODE_ID", ""),
            purchase_approval_node_id=os.getenv("FEISHU_APPROVAL_PURCHASE_NODE_ID", ""),
            shipment_approval_node_id=os.getenv("FEISHU_APPROVAL_SHIPMENT_NODE_ID", ""),
            case_close_approval_node_id=os.getenv("FEISHU_APPROVAL_CASE_CLOSE_NODE_ID", ""),
            approval_business_types=_env_csv(
                "FEISHU_APPROVAL_BUSINESS_TYPES",
                ("purchase_confirmation", "shipment_confirmation", "case_close"),
            ),
            approval_risk_levels=_env_csv("FEISHU_APPROVAL_RISK_LEVELS", ("critical", "high")),
        )

    def review_chat_id_for(self, business_type: str) -> str:
        if business_type in {"purchase_confirmation", "purchase_verification"} and self.purchase_review_chat_id:
            return self.purchase_review_chat_id
        if business_type in {"shipment_confirmation", "shipment_verification", "weekly_shipment_plan"} and self.shipment_review_chat_id:
            return self.shipment_review_chat_id
        if business_type in {"case_close", "exception_case"} and self.case_followup_chat_id:
            return self.case_followup_chat_id
        return self.default_review_chat_id

    def approval_code_for(self, business_type: str) -> str:
        if business_type in {"purchase_confirmation", "purchase_verification"}:
            return self.purchase_approval_code
        if business_type in {"shipment_confirmation", "shipment_verification", "weekly_shipment_plan"}:
            return self.shipment_approval_code
        if business_type in {"case_close", "exception_case"}:
            return self.case_close_approval_code
        return self.default_approval_code or self.purchase_approval_code

    def approval_node_id_for(self, business_type: str) -> str:
        if business_type in {"purchase_confirmation", "purchase_verification"} and self.purchase_approval_node_id:
            return self.purchase_approval_node_id
        if business_type in {"shipment_confirmation", "shipment_verification", "weekly_shipment_plan"} and self.shipment_approval_node_id:
            return self.shipment_approval_node_id
        if business_type in {"case_close", "exception_case"} and self.case_close_approval_node_id:
            return self.case_close_approval_node_id
        return self.approval_free_node_id


@dataclass(frozen=True)
class FeishuReviewRequest:
    request_id: str
    business_type: str
    title: str
    summary: str
    business_object: dict[str, Any] = field(default_factory=dict)
    suggested_action: str = ""
    risk_level: str = "medium"
    reviewer_open_ids: tuple[str, ...] = ()
    chat_id: str = ""
    source_message_id: str = ""
    metadata: dict[str, Any] = field(default_factory=dict)


@dataclass(frozen=True)
class FeishuReviewResult:
    ok: bool
    review_id: str
    status: str
    channel: str = "review_card"
    message_id: str = ""
    url: str = ""
    error: str = ""
    raw: dict[str, Any] = field(default_factory=dict)


@dataclass(frozen=True)
class FeishuApprovalRequest:
    request_id: str
    business_type: str
    approval_code: str
    title: str
    summary: str
    business_object: dict[str, Any] = field(default_factory=dict)
    form_fields: dict[str, Any] = field(default_factory=dict)
    approver_open_ids: tuple[str, ...] = ()
    source_message_id: str = ""
    metadata: dict[str, Any] = field(default_factory=dict)


@dataclass(frozen=True)
class FeishuApprovalResult:
    ok: bool
    approval_id: str
    status: str
    channel: str = "approval_flow"
    url: str = ""
    error: str = ""
    raw: dict[str, Any] = field(default_factory=dict)


@dataclass(frozen=True)
class FeishuApprovalInstance:
    ok: bool
    approval_id: str
    status: str
    operator_open_id: str = ""
    comment: str = ""
    error: str = ""
    raw: dict[str, Any] = field(default_factory=dict)


@dataclass(frozen=True)
class FeishuWorkflowCallback:
    source: str
    workflow_id: str
    request_id: str
    action: str
    operator_open_id: str = ""
    status: str = ""
    comment: str = ""
    fields: dict[str, Any] = field(default_factory=dict)
    raw: dict[str, Any] = field(default_factory=dict)


class FeishuReviewClient(Protocol):
    def submit_review(self, request: FeishuReviewRequest) -> FeishuReviewResult:
        ...

    def parse_review_callback(self, payload: dict[str, Any]) -> FeishuWorkflowCallback:
        ...


class FeishuApprovalClient(Protocol):
    def create_approval(self, request: FeishuApprovalRequest) -> FeishuApprovalResult:
        ...

    def get_approval_instance(self, approval_id: str) -> FeishuApprovalInstance:
        ...

    def parse_approval_callback(self, payload: dict[str, Any]) -> FeishuWorkflowCallback:
        ...


@dataclass
class InMemoryFeishuReviewClient:
    """测试用审核客户端，模拟飞书卡片审核接口。"""

    submitted: list[FeishuReviewRequest] = field(default_factory=list)

    def submit_review(self, request: FeishuReviewRequest) -> FeishuReviewResult:
        self.submitted.append(request)
        return FeishuReviewResult(
            ok=True,
            review_id=f"review-{request.request_id}",
            message_id=f"msg-{request.request_id}",
            status="pending_review",
            raw={"request_id": request.request_id, "chat_id": request.chat_id},
        )

    def parse_review_callback(self, payload: dict[str, Any]) -> FeishuWorkflowCallback:
        value = payload.get("value") if isinstance(payload.get("value"), dict) else {}
        return FeishuWorkflowCallback(
            source="feishu_review",
            workflow_id=str(payload.get("review_id") or payload.get("workflow_id") or ""),
            request_id=str(payload.get("request_id") or value.get("request_id") or ""),
            action=str(payload.get("action") or value.get("action") or ""),
            operator_open_id=str(payload.get("operator_open_id") or ""),
            status=str(payload.get("status") or _status_for_action(str(payload.get("action") or value.get("action") or ""))),
            comment=str(payload.get("comment") or value.get("comment") or ""),
            fields=dict(payload.get("fields") or value),
            raw=payload,
        )


FeishuHttpTransport = Callable[[str, dict[str, Any], dict[str, str]], dict[str, Any]]


@dataclass
class HttpFeishuReviewClient:
    """真实飞书审核卡片客户端。

    当前实现通过飞书开放平台 HTTP API 获取 tenant_access_token，并向指定会话发送
    interactive 消息卡片。卡片按钮的回调落地由后续 HTTP 回调入口承接。
    """

    config: FeishuConfig = field(default_factory=FeishuConfig.from_env)
    transport: FeishuHttpTransport | None = None
    token_ttl_buffer_seconds: int = 120
    _tenant_access_token: str = field(default="", init=False)
    _token_expires_at: float = field(default=0, init=False)

    def submit_review(self, request: FeishuReviewRequest) -> FeishuReviewResult:
        if not self.config.ready:
            return FeishuReviewResult(
                ok=False,
                review_id="",
                status="failed",
                error="飞书未启用或缺少应用凭证",
                raw={"request_id": request.request_id},
            )
        recipients = _review_message_recipients(request)
        if not recipients:
            return FeishuReviewResult(
                ok=False,
                review_id="",
                status="failed",
                error="缺少飞书审核接收人 chat_id 或 reviewer_open_ids",
                raw={"request_id": request.request_id},
            )

        try:
            token = self._tenant_token()
            card = _build_review_card(request, self.config.bot_name)
            responses = []
            for receive_id_type, receive_id in recipients:
                payload = {
                    "receive_id": receive_id,
                    "msg_type": "interactive",
                    "content": json.dumps(card, ensure_ascii=False),
                }
                response = self._post_json(
                    f"{self.config.api_base_url}/open-apis/im/v1/messages?receive_id_type={receive_id_type}",
                    payload,
                    {"Authorization": f"Bearer {token}"},
                )
                responses.append({"receive_id_type": receive_id_type, "receive_id": receive_id, "response": response})
        except Exception as exc:
            logger.exception("feishu review card send failed", extra=log_extra("feishu_review_card_send_failed", request_id=request.request_id))
            return FeishuReviewResult(
                ok=False,
                review_id="",
                status="failed",
                error=f"{type(exc).__name__}: {exc}",
                raw={"request_id": request.request_id},
            )

        failed = next((item for item in responses if _response_code(item["response"]) != 0), None)
        if failed:
            response = failed["response"]
            return FeishuReviewResult(
                ok=False,
                review_id="",
                status="failed",
                error=str(response.get("msg") or "飞书审核卡片发送失败"),
                raw={"request_id": request.request_id, "failed": failed, "responses": responses},
            )
        message_id = _message_id_from_response(responses[0]["response"]) if responses else ""
        return FeishuReviewResult(
            ok=True,
            review_id=f"review-{request.request_id}",
            message_id=message_id,
            status="pending_review",
            raw={"request_id": request.request_id, "responses": responses},
        )

    def parse_review_callback(self, payload: dict[str, Any]) -> FeishuWorkflowCallback:
        action = str(payload.get("action") or payload.get("value", {}).get("action") or "")
        value = payload.get("value") if isinstance(payload.get("value"), dict) else {}
        return FeishuWorkflowCallback(
            source="feishu_review",
            workflow_id=str(payload.get("review_id") or payload.get("workflow_id") or payload.get("message_id") or ""),
            request_id=str(payload.get("request_id") or value.get("request_id") or ""),
            action=action,
            operator_open_id=str(payload.get("operator_open_id") or payload.get("operator", {}).get("open_id") or ""),
            status=str(payload.get("status") or _status_for_action(action)),
            comment=str(payload.get("comment") or value.get("comment") or ""),
            fields=dict(payload.get("fields") or value),
            raw=payload,
        )

    def _tenant_token(self) -> str:
        now = time.time()
        if self._tenant_access_token and now < self._token_expires_at:
            return self._tenant_access_token
        response = self._post_json(
            f"{self.config.api_base_url}/open-apis/auth/v3/tenant_access_token/internal",
            {"app_id": self.config.app_id, "app_secret": self.config.app_secret},
            {},
        )
        code = _response_code(response)
        if code != 0:
            raise RuntimeError(str(response.get("msg") or "获取飞书 tenant_access_token 失败"))
        token = str(response.get("tenant_access_token") or "")
        if not token:
            raise RuntimeError("飞书 tenant_access_token 为空")
        expire = int(response.get("expire") or 7200)
        self._tenant_access_token = token
        self._token_expires_at = now + max(60, expire - self.token_ttl_buffer_seconds)
        return token

    def _post_json(self, url: str, payload: dict[str, Any], headers: dict[str, str]) -> dict[str, Any]:
        if self.transport:
            return self.transport(url, payload, headers)
        body = json.dumps(payload, ensure_ascii=False).encode("utf-8")
        request = urllib.request.Request(
            url,
            data=body,
            headers={"Content-Type": "application/json; charset=utf-8", **headers},
            method="POST",
        )
        try:
            with urllib.request.urlopen(request, timeout=30) as response:
                return json.loads(response.read().decode("utf-8"))
        except urllib.error.HTTPError as exc:
            error_body = exc.read().decode("utf-8", errors="replace")
            raise RuntimeError(f"HTTPError {exc.code}: {error_body[:1000]}") from exc


@dataclass
class InMemoryFeishuApprovalClient:
    """测试用审批客户端，模拟飞书流程审批接口。"""

    created: list[FeishuApprovalRequest] = field(default_factory=list)

    def create_approval(self, request: FeishuApprovalRequest) -> FeishuApprovalResult:
        self.created.append(request)
        if not request.approval_code:
            return FeishuApprovalResult(
                ok=False,
                approval_id="",
                status="failed",
                error="缺少飞书审批码",
                raw={"request_id": request.request_id},
            )
        return FeishuApprovalResult(
            ok=True,
            approval_id=f"approval-{request.request_id}",
            status="pending_review",
            raw={"request_id": request.request_id, "approval_code": request.approval_code},
        )

    def get_approval_instance(self, approval_id: str) -> FeishuApprovalInstance:
        return FeishuApprovalInstance(
            ok=True,
            approval_id=approval_id,
            status="pending",
            raw={"approval_id": approval_id},
        )

    def parse_approval_callback(self, payload: dict[str, Any]) -> FeishuWorkflowCallback:
        return FeishuWorkflowCallback(
            source="feishu_approval",
            workflow_id=str(payload.get("approval_id") or payload.get("workflow_id") or ""),
            request_id=str(payload.get("request_id") or ""),
            action=str(payload.get("action") or ""),
            operator_open_id=str(payload.get("operator_open_id") or ""),
            status=str(payload.get("status") or _status_for_action(str(payload.get("action") or ""))),
            comment=str(payload.get("comment") or ""),
            fields=dict(payload.get("fields") or {}),
            raw=payload,
        )


@dataclass
class HttpFeishuApprovalClient:
    """真实飞书原生审批客户端，创建进入审批中心的审批实例。"""

    config: FeishuConfig = field(default_factory=FeishuConfig.from_env)
    workflow_config: FeishuWorkflowConfig = field(default_factory=FeishuWorkflowConfig.from_env)
    transport: FeishuHttpTransport | None = None
    token_ttl_buffer_seconds: int = 120
    _tenant_access_token: str = field(default="", init=False)
    _token_expires_at: float = field(default=0, init=False)

    def create_approval(self, request: FeishuApprovalRequest) -> FeishuApprovalResult:
        if not self.config.ready:
            return FeishuApprovalResult(
                ok=False,
                approval_id="",
                status="failed",
                error="飞书未启用或缺少应用凭证",
                raw={"request_id": request.request_id},
            )
        if not request.approval_code:
            return FeishuApprovalResult(
                ok=False,
                approval_id="",
                status="failed",
                error="缺少飞书审批码",
                raw={"request_id": request.request_id},
            )
        start_open_id = str(request.metadata.get("approval_start_open_id") or self.workflow_config.approval_start_open_id)
        start_user_id = str(request.metadata.get("approval_start_user_id") or self.workflow_config.approval_start_user_id)
        if not start_open_id and not start_user_id:
            return FeishuApprovalResult(
                ok=False,
                approval_id="",
                status="failed",
                error="缺少飞书审批发起人 open_id 或 user_id",
                raw={"request_id": request.request_id},
            )

        try:
            token = self._tenant_token()
            definition = self._approval_definition(token, request.approval_code)
            payload: dict[str, Any] = {
                "approval_code": request.approval_code,
                "form": json.dumps(_approval_form_items(request, definition=definition), ensure_ascii=False),
                "uuid": _approval_uuid(request.request_id),
            }
            if start_user_id:
                payload["user_id"] = start_user_id
            else:
                payload["open_id"] = start_open_id

            node_id = str(request.metadata.get("approval_node_id") or self.workflow_config.approval_node_id_for(request.business_type))
            approver_open_ids = list(dict.fromkeys(open_id.strip() for open_id in request.approver_open_ids if open_id and open_id.strip()))
            if node_id and approver_open_ids:
                payload["node_approver_open_id_list"] = [{"key": node_id, "value": approver_open_ids}]

            response = self._post_json(
                f"{self.config.api_base_url}/open-apis/approval/v4/instances",
                payload,
                {"Authorization": f"Bearer {token}"},
            )
        except Exception as exc:
            logger.exception("feishu approval instance create failed", extra=log_extra("feishu_approval_create_failed", request_id=request.request_id))
            return FeishuApprovalResult(
                ok=False,
                approval_id="",
                status="failed",
                error=f"{type(exc).__name__}: {exc}",
                raw={"request_id": request.request_id},
            )

        if _response_code(response) != 0:
            return FeishuApprovalResult(
                ok=False,
                approval_id="",
                status="failed",
                error=str(response.get("msg") or "飞书审批实例创建失败"),
                raw=response,
            )
        data = dict(response.get("data") or {})
        instance_code = str(data.get("instance_code") or "")
        return FeishuApprovalResult(
            ok=True,
            approval_id=instance_code,
            status="pending_review",
            url=str(data.get("url") or ""),
            raw=response,
        )

    def get_approval_instance(self, approval_id: str) -> FeishuApprovalInstance:
        if not self.config.ready:
            return FeishuApprovalInstance(
                ok=False,
                approval_id=approval_id,
                status="unknown",
                error="飞书未启用或缺少应用凭证",
            )
        if not approval_id:
            return FeishuApprovalInstance(ok=False, approval_id="", status="unknown", error="缺少飞书审批实例 ID")
        try:
            token = self._tenant_token()
            response = self._post_json(
                f"{self.config.api_base_url}/open-apis/approval/v4/instances/query",
                {"instance_code": approval_id, "page_size": 10},
                {"Authorization": f"Bearer {token}"},
            )
        except Exception as exc:
            logger.exception("feishu approval instance query failed", extra=log_extra("feishu_approval_query_failed", approval_id=approval_id))
            return FeishuApprovalInstance(
                ok=False,
                approval_id=approval_id,
                status="unknown",
                error=f"{type(exc).__name__}: {exc}",
            )

        if _response_code(response) != 0:
            return FeishuApprovalInstance(
                ok=False,
                approval_id=approval_id,
                status="unknown",
                error=str(response.get("msg") or "飞书审批实例查询失败"),
                raw=response,
            )
        instance = _approval_instance_from_query(response, approval_id)
        if not instance:
            return FeishuApprovalInstance(
                ok=False,
                approval_id=approval_id,
                status="unknown",
                error="未查询到飞书审批实例",
                raw=response,
            )
        status = _normalize_approval_instance_status(str(instance.get("status") or ""))
        operator_open_id = _approval_instance_operator_open_id(instance)
        comment = _approval_instance_comment(instance)
        return FeishuApprovalInstance(
            ok=True,
            approval_id=str(instance.get("code") or instance.get("instance_code") or approval_id),
            status=status,
            operator_open_id=operator_open_id,
            comment=comment,
            raw=instance,
        )

    def parse_approval_callback(self, payload: dict[str, Any]) -> FeishuWorkflowCallback:
        return InMemoryFeishuApprovalClient().parse_approval_callback(payload)

    def _tenant_token(self) -> str:
        now = time.time()
        if self._tenant_access_token and now < self._token_expires_at:
            return self._tenant_access_token
        response = self._post_json(
            f"{self.config.api_base_url}/open-apis/auth/v3/tenant_access_token/internal",
            {"app_id": self.config.app_id, "app_secret": self.config.app_secret},
            {},
        )
        code = _response_code(response)
        if code != 0:
            raise RuntimeError(str(response.get("msg") or "获取飞书 tenant_access_token 失败"))
        token = str(response.get("tenant_access_token") or "")
        if not token:
            raise RuntimeError("飞书 tenant_access_token 为空")
        expire = int(response.get("expire") or 7200)
        self._tenant_access_token = token
        self._token_expires_at = now + max(60, expire - self.token_ttl_buffer_seconds)
        return token

    def _post_json(self, url: str, payload: dict[str, Any], headers: dict[str, str]) -> dict[str, Any]:
        if self.transport:
            return self.transport(url, payload, headers)
        body = json.dumps(payload, ensure_ascii=False).encode("utf-8")
        request = urllib.request.Request(
            url,
            data=body,
            headers={"Content-Type": "application/json; charset=utf-8", **headers},
            method="POST",
        )
        try:
            with urllib.request.urlopen(request, timeout=30) as response:
                return json.loads(response.read().decode("utf-8"))
        except urllib.error.HTTPError as exc:
            error_body = exc.read().decode("utf-8", errors="replace")
            raise RuntimeError(f"HTTPError {exc.code}: {error_body[:1000]}") from exc

    def _approval_definition(self, token: str, approval_code: str) -> dict[str, Any]:
        if self.transport:
            return self.transport(
                f"{self.config.api_base_url}/open-apis/approval/v4/approvals/{approval_code}?locale=zh-CN&user_id_type=open_id",
                {},
                {"Authorization": f"Bearer {token}"},
            )
        request = urllib.request.Request(
            f"{self.config.api_base_url}/open-apis/approval/v4/approvals/{approval_code}?locale=zh-CN&user_id_type=open_id",
            headers={"Authorization": f"Bearer {token}"},
            method="GET",
        )
        try:
            with urllib.request.urlopen(request, timeout=30) as response:
                return json.loads(response.read().decode("utf-8"))
        except urllib.error.HTTPError as exc:
            error_body = exc.read().decode("utf-8", errors="replace")
            raise RuntimeError(f"HTTPError {exc.code}: {error_body[:1000]}") from exc


@dataclass
class FeishuWorkflowService:
    config: FeishuWorkflowConfig = field(default_factory=FeishuWorkflowConfig.from_env)
    review_client: FeishuReviewClient = field(default_factory=HttpFeishuReviewClient)
    approval_client: FeishuApprovalClient = field(default_factory=HttpFeishuApprovalClient)

    def submit(self, request: FeishuReviewRequest) -> FeishuReviewResult | FeishuApprovalResult:
        channel = self.route_channel(request)
        if channel == "approval_flow":
            approval_request = FeishuApprovalRequest(
                request_id=request.request_id,
                business_type=request.business_type,
                approval_code=self.config.approval_code_for(request.business_type),
                title=request.title,
                summary=request.summary,
                business_object=request.business_object,
                form_fields={
                    "suggested_action": request.suggested_action,
                    "risk_level": request.risk_level,
                    **request.metadata,
                },
                approver_open_ids=request.reviewer_open_ids,
                source_message_id=request.source_message_id,
                metadata={
                    "review_chat_id": request.chat_id,
                    "approval_start_open_id": self.config.approval_start_open_id,
                    "approval_start_user_id": self.config.approval_start_user_id,
                    "approval_node_id": self.config.approval_node_id_for(request.business_type),
                    **request.metadata,
                },
            )
            return self.approval_client.create_approval(approval_request)

        routed_request = FeishuReviewRequest(
            request_id=request.request_id,
            business_type=request.business_type,
            title=request.title,
            summary=request.summary,
            business_object=request.business_object,
            suggested_action=request.suggested_action,
            risk_level=request.risk_level,
            reviewer_open_ids=request.reviewer_open_ids,
            chat_id=request.chat_id or self.config.review_chat_id_for(request.business_type),
            source_message_id=request.source_message_id,
            metadata=request.metadata,
        )
        return self.review_client.submit_review(routed_request)

    def route_channel(self, request: FeishuReviewRequest) -> str:
        mode = self.config.review_mode.strip().lower()
        if mode in {"card", "review_card"}:
            return "review_card"
        if mode in {"approval", "approval_flow"}:
            return "approval_flow" if self.config.approval_enabled else "review_card"
        should_approve = (
            self.config.approval_enabled
            and request.business_type in self.config.approval_business_types
            and request.risk_level in self.config.approval_risk_levels
        )
        return "approval_flow" if should_approve else "review_card"

    def parse_callback(self, payload: dict[str, Any]) -> FeishuWorkflowCallback:
        source = str(payload.get("source") or payload.get("type") or "")
        if source in {"feishu_approval", "approval", "approval_flow"} or payload.get("approval_id"):
            return self.approval_client.parse_approval_callback(payload)
        return self.review_client.parse_review_callback(payload)

    def get_approval_instance(self, approval_id: str) -> FeishuApprovalInstance:
        getter = getattr(self.approval_client, "get_approval_instance", None)
        if not callable(getter):
            return FeishuApprovalInstance(ok=False, approval_id=approval_id, status="unknown", error="当前审批客户端不支持查询实例状态")
        return getter(approval_id)


@dataclass(frozen=True)
class FeishuInboundMessage:
    """飞书进入 PMC Agent 的固定消息接口。"""

    message_id: str
    chat_id: str
    chat_type: str
    text: str
    open_id: str = ""
    user_id: str = ""
    tenant_key: str = ""
    event_id: str = ""
    metadata: dict[str, Any] = field(default_factory=dict)

    @property
    def session_id(self) -> str:
        if self.chat_type == "group" and self.chat_id:
            return f"pmc-feishu-chat-{self.chat_id}"
        if self.open_id:
            return f"pmc-feishu-user-{self.open_id}"
        return "pmc-feishu-default"


class FeishuMessageHandler(Protocol):
    def handle_message(self, message: FeishuInboundMessage) -> str:
        ...


class FeishuWorkflowEventHandler(Protocol):
    def handle_feishu_callback(self, payload: dict[str, Any]) -> Any:
        ...


@dataclass
class PmcAgentFeishuHandler:
    agent: PmcAgent = field(default_factory=PmcAgent.create_default)

    def handle_message(self, message: FeishuInboundMessage) -> str:
        result = self.agent.run(message.text)
        return format_agent_reply(result)


class FeishuBot:
    """飞书 WebSocket 长连接机器人固定接口。

    参考 `D:\\laydown` 中已验证的接入方式：通过 lark-oapi WebSocket 接收消息，
    只把标准化后的文本消息交给 handler，回复仍使用原消息的 message_id。
    """

    def __init__(
        self,
        config: FeishuConfig | None = None,
        handler: FeishuMessageHandler | None = None,
        workflow_event_handler: FeishuWorkflowEventHandler | None = None,
    ) -> None:
        self.config = config or FeishuConfig.from_env()
        self.handler = handler or PmcAgentFeishuHandler()
        self.workflow_event_handler = workflow_event_handler
        self._executor = ThreadPoolExecutor(max_workers=self.config.max_workers, thread_name_prefix="pmc-feishu")
        self._lark = _import_lark()

        if not self.config.ready:
            logger.warning(
                "feishu bot not ready",
                extra=log_extra("feishu_bot_not_ready", enabled=self.config.enabled, has_app_id=bool(self.config.app_id)),
            )

        self.api_client = (
            self._lark.Client.builder()
            .app_id(self.config.app_id)
            .app_secret(self.config.app_secret)
            .log_level(self._lark.LogLevel.INFO)
            .build()
        )
        event_handler = (
            self._lark.EventDispatcherHandler.builder("", "")
            .register_p2_im_message_receive_v1(self._on_message_receive)
            .register_p2_card_action_trigger(self._on_card_action_trigger)
            .build()
        )
        self.ws_client = self._lark.ws.Client(
            self.config.app_id,
            self.config.app_secret,
            event_handler=event_handler,
            log_level=self._lark.LogLevel.INFO,
        )

    def start_in_thread(self) -> None:
        if not self.config.ready:
            logger.error("feishu credentials missing or disabled", extra=log_extra("feishu_start_skipped"))
            return
        thread = threading.Thread(target=self.run_forever, name="pmc-feishu-ws", daemon=True)
        thread.start()
        logger.info("feishu websocket thread started", extra=log_extra("feishu_ws_started", app_id=self.config.app_id))

    def run_forever(self) -> None:
        if not self.config.ready:
            logger.error("feishu credentials missing or disabled", extra=log_extra("feishu_run_skipped"))
            return
        import asyncio

        asyncio.set_event_loop(asyncio.new_event_loop())
        try:
            self.ws_client.start()
        except Exception:
            logger.exception("feishu websocket exited", extra=log_extra("feishu_ws_exited"))

    def _on_message_receive(self, data: Any) -> None:
        self._executor.submit(self._handle_event, data)

    def _on_card_action_trigger(self, data: Any) -> Any:
        from lark_oapi.event.callback.model.p2_card_action_trigger import P2CardActionTriggerResponse

        try:
            issue = self._handle_card_action(data)
            if issue is None:
                return P2CardActionTriggerResponse({"toast": {"type": "info", "content": "未识别到可处理的卡片反馈。"}})
            return P2CardActionTriggerResponse({"toast": {"type": "success", "content": _card_action_success_text(issue)}})
        except Exception as exc:
            logger.exception("feishu card action handling failed", extra=log_extra("feishu_card_action_failed"))
            return P2CardActionTriggerResponse({"toast": {"type": "error", "content": f"反馈处理失败：{exc}"}})

    def _handle_card_action(self, data: Any) -> Any:
        payload = _normalize_card_action_event(data)
        if not payload:
            return None
        logger.info(
            "feishu card action received",
            extra=log_extra(
                "feishu_card_action_received",
                request_id=str(payload.get("request_id") or "-"),
                action=str(payload.get("action") or "-"),
                issue_id=str(payload.get("fields", {}).get("issue_id") or "-"),
                review_stage=str(payload.get("fields", {}).get("review_stage") or "-"),
            ),
        )
        if not self.workflow_event_handler:
            logger.warning("feishu card action ignored", extra=log_extra("feishu_card_action_ignored", reason="missing_workflow_event_handler"))
            return None
        return self.workflow_event_handler.handle_feishu_callback(payload)

    def _handle_event(self, data: Any) -> None:
        inbound: FeishuInboundMessage | None = None
        try:
            inbound = _normalize_event(data)
            if not inbound:
                return
            if not inbound.text:
                self._reply_text(inbound.message_id, "你好，请直接输入要查询或处理的 PMC 问题。")
                return
            logger.info(
                "feishu message received",
                extra=log_extra(
                    "feishu_message_received",
                    message_id=inbound.message_id,
                    chat_id=inbound.chat_id or "-",
                    chat_type=inbound.chat_type or "-",
                    session_id=inbound.session_id,
                ),
            )
            reply = self.handler.handle_message(inbound).strip() or "当前没有生成可返回的结果，请补充查询条件后重试。"
            for chunk in _split_text(reply, self.config.max_message_length):
                self._reply_text(inbound.message_id, chunk)
        except Exception:
            logger.exception("feishu message handling failed", extra=log_extra("feishu_message_failed"))
            if inbound:
                self._reply_text(inbound.message_id, "系统处理异常，请稍后重试。")

    def _reply_text(self, message_id: str, text: str) -> None:
        from lark_oapi.api.im.v1 import ReplyMessageRequest, ReplyMessageRequestBody

        body = (
            ReplyMessageRequestBody.builder()
            .msg_type("text")
            .content(json.dumps({"text": text}, ensure_ascii=False))
            .build()
        )
        request = (
            ReplyMessageRequest.builder()
            .message_id(message_id)
            .request_body(body)
            .build()
        )
        response = self.api_client.im.v1.message.reply(request)
        if not response.success():
            logger.error(
                "feishu reply failed",
                extra=log_extra("feishu_reply_failed", code=response.code, msg=response.msg, log_id=response.get_log_id()),
            )


def create_default_feishu_bot() -> FeishuBot:
    from pmc_agent.workflows.sku_issue import JsonlSkuIssueRepository, SkuIssueWorkflow

    workflow_event_handler = SkuIssueWorkflow(
        workflow_service=FeishuWorkflowService(),
        repository=JsonlSkuIssueRepository(),
    )
    return FeishuBot(config=FeishuConfig.from_env(), handler=PmcAgentFeishuHandler(), workflow_event_handler=workflow_event_handler)


def _normalize_event(data: Any) -> FeishuInboundMessage | None:
    event = getattr(data, "event", None)
    msg = getattr(event, "message", None)
    if msg is None:
        return None
    message_id = str(getattr(msg, "message_id", "") or "")
    if not message_id:
        return None
    message_type = str(getattr(msg, "message_type", "") or "")
    if message_type != "text":
        return FeishuInboundMessage(
            message_id=message_id,
            chat_id=str(getattr(msg, "chat_id", "") or ""),
            chat_type=str(getattr(msg, "chat_type", "") or ""),
            text="",
            open_id=_sender_open_id(event),
            metadata={"unsupported_message_type": message_type},
        )

    text = _extract_text(getattr(msg, "content", ""))
    if str(getattr(msg, "chat_type", "") or "") == "group":
        text = _remove_group_mentions(text, getattr(msg, "mentions", None))
    sender = getattr(event, "sender", None)
    return FeishuInboundMessage(
        message_id=message_id,
        chat_id=str(getattr(msg, "chat_id", "") or ""),
        chat_type=str(getattr(msg, "chat_type", "") or ""),
        text=text.strip(),
        open_id=_sender_open_id(event),
        user_id=str(getattr(getattr(sender, "sender_id", None), "user_id", "") or ""),
        tenant_key=str(getattr(event, "tenant_key", "") or ""),
        event_id=str(getattr(data, "event_id", "") or ""),
        metadata={
            "message_type": message_type,
            "session_id": f"pmc-feishu-chat-{getattr(msg, 'chat_id', '') or 'default'}",
        },
    )


def _normalize_card_action_event(data: Any) -> dict[str, Any]:
    event = _attr(data, "event", {})
    action = _attr(event, "action", {})
    value = _attr(action, "value", {})
    if not isinstance(value, dict):
        value = _object_to_dict(value)
    form_value = _attr(action, "form_value", {})
    if not isinstance(form_value, dict):
        form_value = _object_to_dict(form_value)
    operator = _attr(event, "operator", {})
    context = _attr(event, "context", {})
    operator_id = _attr(operator, "operator_id", {})
    fields = {**dict(value or {}), **dict(form_value or {})}
    return {
        "source": "feishu_review",
        "workflow_id": str(_attr(data, "event_id", "") or _attr(context, "open_message_id", "") or ""),
        "request_id": str(fields.get("request_id") or ""),
        "action": str(fields.get("action") or ""),
        "operator_open_id": str(_attr(operator, "open_id", "") or _attr(operator, "operator_open_id", "") or _attr(operator_id, "open_id", "") or ""),
        "comment": str(fields.get("comment") or ""),
        "fields": fields,
    }


def _object_to_dict(value: Any) -> dict[str, Any]:
    if isinstance(value, dict):
        return value
    if isinstance(value, str):
        try:
            parsed = json.loads(value)
        except json.JSONDecodeError:
            return {}
        return parsed if isinstance(parsed, dict) else {}
    if value is None:
        return {}
    result = {}
    for name in dir(value):
        if name.startswith("_"):
            continue
        try:
            item = getattr(value, name)
        except Exception:
            continue
        if callable(item) or name in {"swagger_types", "attribute_map"}:
            continue
        if isinstance(item, (str, int, float, bool)) or item is None:
            result[name] = item
    return result


def _attr(value: Any, name: str, default: Any = "") -> Any:
    if isinstance(value, dict):
        return value.get(name, default)
    return getattr(value, name, default)


def _card_action_success_text(issue: Any) -> str:
    sku = str(_attr(issue, "sku", "") or "SKU")
    status = str(_attr(_attr(issue, "status", ""), "value", "") or _attr(issue, "status", "") or "")
    feedback = _attr(issue, "feedback", None)
    action = str(_attr(_attr(feedback, "action", ""), "value", "") or _attr(feedback, "action", "") or "")
    actions = _attr(feedback, "actions", []) if feedback else []
    if status == "recorded":
        labels = "、".join(_feedback_action_label(str(item)) for item in actions or [action])
        return f"{sku} 反馈已记录：{labels}"
    if status == "owner_feedback_pending":
        return f"{sku} 已通过 PMC 审核，已发送给处理人反馈。"
    if status == "pmc_rejected":
        return f"{sku} 已被 PMC 驳回。"
    return f"{sku} 已处理，当前状态：{status or '-'}"


def _feedback_action_label(action: str) -> str:
    return {
        "expedite_shipment": "加急发货",
        "purchase_replenishment": "补采购",
        "sales_control": "销售控销",
        "promotion": "促销",
        "data_issue": "数据有误",
        "need_decision": "需要上级决策",
        "no_action": "暂不处理",
    }.get(action, action or "-")


def _extract_text(content: Any) -> str:
    if isinstance(content, str):
        try:
            payload = json.loads(content)
        except json.JSONDecodeError:
            return content
    elif isinstance(content, dict):
        payload = content
    else:
        return ""
    return str(payload.get("text") or "")


def _remove_group_mentions(text: str, mentions: Any) -> str:
    cleaned = text
    for mention in mentions or []:
        key = str(getattr(mention, "key", "") or "")
        name = str(getattr(mention, "name", "") or "")
        if key:
            cleaned = cleaned.replace(f"@_{key}", "")
        if name:
            cleaned = cleaned.replace(f"@{name}", "")
    return re.sub(r"\s+", " ", cleaned).strip()


def _build_review_card(request: FeishuReviewRequest, bot_name: str) -> dict[str, Any]:
    fields = _review_card_fields(request)
    elements: list[dict[str, Any]] = [
        {"tag": "markdown", "content": f"**业务类型**：{request.business_type}\n**风险等级**：{request.risk_level}"},
        {"tag": "markdown", "content": f"**摘要**\n{_truncate(request.summary, 1200)}"},
    ]
    if request.suggested_action:
        elements.append({"tag": "markdown", "content": f"**建议动作**\n{_truncate(request.suggested_action, 800)}"})
    if fields:
        elements.append({"tag": "markdown", "content": "**关键字段**\n" + "\n".join(fields)})
    elements.append(_review_card_action_element(request))
    return {
        "config": {"wide_screen_mode": True},
        "header": {
            "title": {"tag": "plain_text", "content": request.title or "PMC 审核请求"},
            "template": _card_template_for_risk(request.risk_level),
        },
        "elements": [
            {"tag": "markdown", "content": f"来自：{bot_name}"},
            *elements,
        ],
    }


def _review_card_action_element(request: FeishuReviewRequest) -> dict[str, Any]:
    if request.metadata.get("review_stage") == "owner_feedback":
        return _owner_feedback_form(request)
    return {
        "tag": "action",
        "actions": _review_card_actions(request),
    }


def _review_card_actions(request: FeishuReviewRequest) -> list[dict[str, Any]]:
    return [
        _review_card_button(request, "同意", "approve", button_type="primary"),
        _review_card_button(request, "驳回", "reject", button_type="danger"),
        _review_card_button(request, "补充信息", "need_more_info"),
    ]


def _review_card_button(request: FeishuReviewRequest, text: str, action: str, button_type: str = "default") -> dict[str, Any]:
    payload = _review_card_value(request, action)
    button = {
        "tag": "button",
        "text": {"tag": "plain_text", "content": text},
        "value": payload,
    }
    if button_type != "default":
        button["type"] = button_type
    return button


def _owner_feedback_form(request: FeishuReviewRequest) -> dict[str, Any]:
    return {
        "tag": "form",
        "name": f"feedback_form_{_safe_card_name(request.request_id)}",
        "elements": [
            {"tag": "markdown", "content": "**处理反馈**"},
            {
                "tag": "column_set",
                "flex_mode": "stretch",
                "horizontal_spacing": "default",
                "background_style": "default",
                "columns": [
                    {
                        "tag": "column",
                        "width": "weighted",
                        "weight": 1,
                        "vertical_align": "top",
                        "elements": [_owner_feedback_multi_select()],
                    },
                    {
                        "tag": "column",
                        "width": "auto",
                        "vertical_align": "top",
                        "elements": [_owner_feedback_submit_button(request)],
                    },
                ],
            },
            {
                "tag": "input",
                "name": "feedback_comment",
                "placeholder": {"tag": "plain_text", "content": "请输入处理备注，例如预计完成时间、原因或补充说明"},
                "input_type": "multiline_text",
                "rows": 3,
                "auto_resize": True,
                "max_length": 500,
                "label": {"tag": "plain_text", "content": "备注"},
                "label_position": "top",
                "required": False,
            },
        ],
    }


def _owner_feedback_multi_select() -> dict[str, Any]:
    return {
        "tag": "multi_select_static",
        "type": "default",
        "name": "feedback_actions",
        "placeholder": {"tag": "plain_text", "content": "请选择一个或多个处理动作"},
        "width": "fill",
        "required": True,
        "options": [
            _feedback_action_option("加急发货", "expedite_shipment"),
            _feedback_action_option("补采购", "purchase_replenishment"),
            _feedback_action_option("销售控销", "sales_control"),
            _feedback_action_option("促销", "promotion"),
            _feedback_action_option("数据有误", "data_issue"),
            _feedback_action_option("需决策", "need_decision"),
            _feedback_action_option("暂不处理", "no_action"),
        ],
    }


def _feedback_action_option(text: str, value: str) -> dict[str, Any]:
    return {"text": {"tag": "plain_text", "content": text}, "value": value}


def _owner_feedback_submit_button(request: FeishuReviewRequest) -> dict[str, Any]:
    return {
        "tag": "button",
        "text": {"tag": "plain_text", "content": "确认处理"},
        "type": "primary",
        "action_type": "form_submit",
        "name": f"submit_feedback_{_safe_card_name(request.request_id)}",
        "value": _review_card_value(request, "submit_owner_feedback"),
        "confirm": {
            "title": {"tag": "plain_text", "content": "确认提交反馈？"},
            "text": {"tag": "plain_text", "content": "提交后将记录处理动作和备注，并进入 Agent 落表。"},
        },
    }


def _safe_card_name(value: str) -> str:
    cleaned = re.sub(r"[^0-9A-Za-z_]", "_", value or "default")
    return cleaned[:32] or "default"


def _review_card_value(request: FeishuReviewRequest, action: str) -> dict[str, Any]:
    value = {
        "action": action,
        "request_id": request.request_id,
        "business_type": request.business_type,
    }
    for key in (
        "issue_id",
        "review_stage",
        "assignment_department",
        "assignment_owner_open_id",
        "assignment_owner_name",
        "is_reminder",
    ):
        if key in request.metadata:
            value[key] = request.metadata[key]
    return value


def _approval_form_items(request: FeishuApprovalRequest, definition: dict[str, Any] | None = None) -> list[dict[str, Any]]:
    explicit_form = request.metadata.get("approval_form")
    if isinstance(explicit_form, list):
        return [dict(item) for item in explicit_form if isinstance(item, dict)]

    widgets = _definition_widgets(definition)
    if widgets:
        values = _approval_form_values(request)
        field_list = next((widget for widget in widgets if widget.get("type") == "fieldList" and isinstance(widget.get("children"), list)), None)
        if field_list:
            row = []
            for child in field_list.get("children") or []:
                key = str(child.get("custom_id") or child.get("name") or child.get("id") or "")
                value = values.get(key, "")
                if value == "" and child.get("required"):
                    value = "-"
                widget_type = child.get("type") or "input"
                row.append({"id": child.get("id"), "type": widget_type, "value": _approval_widget_value(value, widget_type)})
            return [{"id": field_list.get("id"), "type": "fieldList", "value": [row]}]
        mapped = []
        for widget in widgets:
            key = str(widget.get("custom_id") or widget.get("name") or widget.get("id") or "")
            value = values.get(key, "")
            if value == "" and widget.get("required"):
                value = "-"
            if value == "":
                continue
            widget_type = widget.get("type") or _approval_form_type(value)
            mapped.append({"id": widget.get("id"), "type": widget_type, "value": _approval_widget_value(value, widget_type)})
        if mapped:
            return mapped

    items = [
        {"id": "title", "type": "input", "value": request.title},
        {"id": "summary", "type": "textarea", "value": request.summary},
    ]
    risk_level = request.form_fields.get("risk_level")
    if risk_level:
        items.append({"id": "risk_level", "type": "input", "value": str(risk_level)})
    suggested_action = request.form_fields.get("suggested_action")
    if suggested_action:
        items.append({"id": "suggested_action", "type": "textarea", "value": str(suggested_action)})
    for key, value in request.business_object.items():
        if value in (None, "", [], {}):
            continue
        items.append({"id": str(key), "type": _approval_form_type(value), "value": _approval_form_value(value)})
    return items


def _approval_uuid(request_id: str) -> str:
    if len(request_id) <= 64:
        return request_id
    digest = hashlib.sha1(request_id.encode("utf-8")).hexdigest()[:12]
    return f"{request_id[:51]}-{digest}"


def _approval_form_values(request: FeishuApprovalRequest) -> dict[str, Any]:
    values: dict[str, Any] = {
        "title": request.title,
        "summary": request.summary,
    }
    risk_level = request.form_fields.get("risk_level")
    if risk_level:
        values["risk_level"] = str(risk_level)
    suggested_action = request.form_fields.get("suggested_action")
    if suggested_action:
        values["suggested_action"] = str(suggested_action)
    values.update({str(key): value for key, value in request.business_object.items() if value not in (None, "", [], {})})
    return values


def _definition_widgets(definition: dict[str, Any] | None) -> list[dict[str, Any]]:
    if not definition or _response_code(definition) != 0:
        return []
    form = (definition.get("data") or {}).get("form")
    if isinstance(form, str):
        try:
            parsed = json.loads(form)
        except json.JSONDecodeError:
            return []
    else:
        parsed = form
    return [widget for widget in parsed if isinstance(widget, dict)] if isinstance(parsed, list) else []


def _approval_form_type(value: Any) -> str:
    if isinstance(value, (int, float)) and not isinstance(value, bool):
        return "number"
    text = json.dumps(value, ensure_ascii=False) if isinstance(value, (dict, list)) else str(value)
    return "textarea" if len(text) > 80 or "\n" in text else "input"


def _approval_form_value(value: Any) -> str | int | float:
    if isinstance(value, (int, float)) and not isinstance(value, bool):
        return value
    if isinstance(value, (dict, list)):
        return json.dumps(value, ensure_ascii=False)
    return str(value)


def _approval_widget_value(value: Any, widget_type: str) -> Any:
    if widget_type == "number" and isinstance(value, (int, float)) and not isinstance(value, bool):
        return value
    if widget_type in {"input", "textarea"}:
        if isinstance(value, (dict, list)):
            return json.dumps(value, ensure_ascii=False)
        return str(value)
    return _approval_form_value(value)


def _approval_instance_from_query(response: dict[str, Any], approval_id: str) -> dict[str, Any]:
    data = response.get("data") if isinstance(response.get("data"), dict) else {}
    candidates: list[Any] = []
    for key in ("instance_list", "instances", "items", "list"):
        value = data.get(key)
        if isinstance(value, list):
            candidates.extend(value)
    if not candidates and isinstance(data.get("instance"), dict):
        candidates.append(data.get("instance"))
    for candidate in candidates:
        if not isinstance(candidate, dict):
            continue
        instance = candidate.get("instance") if isinstance(candidate.get("instance"), dict) else candidate
        if str(instance.get("code") or instance.get("instance_code") or candidate.get("instance_code") or candidate.get("approval_id") or "") == approval_id:
            return {**candidate, **instance}
    first = next((candidate for candidate in candidates if isinstance(candidate, dict)), None)
    if isinstance(first, dict) and isinstance(first.get("instance"), dict):
        return {**first, **first["instance"]}
    return dict(first or {})


def _normalize_approval_instance_status(status: str) -> str:
    normalized = status.strip().lower()
    return {
        "pending": "pending",
        "approved": "approved",
        "rejected": "rejected",
        "canceled": "cancelled",
        "cancelled": "cancelled",
        "deleted": "deleted",
    }.get(normalized, normalized or "unknown")


def _approval_instance_operator_open_id(instance: dict[str, Any]) -> str:
    tasks = instance.get("task_list")
    if not isinstance(tasks, list):
        return str(instance.get("operator_open_id") or instance.get("open_id") or "")
    finished = [
        task
        for task in tasks
        if isinstance(task, dict) and str(task.get("status") or "").strip().upper() in {"APPROVED", "REJECTED", "TRANSFERRED", "DONE"}
    ]
    task = finished[-1] if finished else next((item for item in reversed(tasks) if isinstance(item, dict)), {})
    if not isinstance(task, dict):
        return ""
    return str(task.get("open_id") or task.get("operator_open_id") or task.get("user_id") or "")


def _approval_instance_comment(instance: dict[str, Any]) -> str:
    comments = instance.get("comment_list")
    if isinstance(comments, list):
        for comment in reversed(comments):
            if isinstance(comment, dict) and comment.get("comment"):
                return str(comment.get("comment") or "")
    tasks = instance.get("task_list")
    if isinstance(tasks, list):
        for task in reversed(tasks):
            if isinstance(task, dict) and task.get("comment"):
                return str(task.get("comment") or "")
    return ""


def _review_message_recipients(request: FeishuReviewRequest) -> list[tuple[str, str]]:
    if request.chat_id:
        return [("chat_id", request.chat_id)]
    open_ids = list(dict.fromkeys(open_id.strip() for open_id in request.reviewer_open_ids if open_id and open_id.strip()))
    return [("open_id", open_id) for open_id in open_ids]


def _message_id_from_response(response: dict[str, Any]) -> str:
    data = dict(response.get("data") or {})
    return str(data.get("message_id") or data.get("message", {}).get("message_id") or "")


def _review_card_fields(request: FeishuReviewRequest) -> list[str]:
    fields: list[str] = []
    for key, value in request.business_object.items():
        if value in (None, "", [], {}):
            continue
        text = json.dumps(value, ensure_ascii=False) if isinstance(value, (dict, list)) else str(value)
        fields.append(f"- **{key}**：{_truncate(text, 180)}")
        if len(fields) >= 10:
            break
    return fields


def _card_template_for_risk(risk_level: str) -> str:
    return {
        "critical": "red",
        "high": "red",
        "medium": "orange",
        "low": "green",
    }.get(risk_level, "blue")


def _truncate(text: str, limit: int) -> str:
    return text if len(text) <= limit else f"{text[:limit - 3]}..."


def _sender_open_id(event: Any) -> str:
    sender = getattr(event, "sender", None)
    sender_id = getattr(sender, "sender_id", None)
    return str(getattr(sender_id, "open_id", "") or "")


def _split_text(text: str, limit: int) -> list[str]:
    if len(text) <= limit:
        return [text]
    chunks: list[str] = []
    current = ""
    for line in text.splitlines(keepends=True):
        if len(current) + len(line) <= limit:
            current += line
            continue
        if current:
            chunks.append(current.rstrip())
            current = ""
        while len(line) > limit:
            chunks.append(line[:limit].rstrip())
            line = line[limit:]
        current = line
    if current:
        chunks.append(current.rstrip())
    return chunks or [text[:limit]]


def _import_lark() -> Any:
    try:
        import lark_oapi as lark
    except ImportError as exc:
        raise RuntimeError("FeishuBot 需要安装 lark-oapi，请执行 `pip install -e .[feishu]`。") from exc
    return lark


def _env_bool(name: str, default: bool) -> bool:
    value = os.getenv(name)
    if value is None:
        return default
    return value.strip().lower() in {"1", "true", "yes", "on"}


def _env_int(name: str, default: int, minimum: int, maximum: int) -> int:
    try:
        value = int(os.getenv(name, str(default)))
    except ValueError:
        value = default
    return max(minimum, min(maximum, value))


def _env_csv(name: str, default: tuple[str, ...]) -> tuple[str, ...]:
    value = os.getenv(name)
    if not value:
        return default
    items = tuple(item.strip() for item in value.split(",") if item.strip())
    return items or default


def _response_code(response: dict[str, Any]) -> int:
    value = response.get("code", -1)
    if value is None:
        return -1
    try:
        return int(value)
    except (TypeError, ValueError):
        return -1


def _status_for_action(action: str) -> str:
    return {
        "approve": "approved",
        "approved": "approved",
        "reject": "rejected",
        "rejected": "rejected",
        "need_more_info": "need_more_info",
        "comment": "commented",
        "cancel": "cancelled",
        "cancelled": "cancelled",
    }.get(action, action or "unknown")
