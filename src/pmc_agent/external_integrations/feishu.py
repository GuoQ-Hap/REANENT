from __future__ import annotations

from concurrent.futures import ThreadPoolExecutor
from dataclasses import dataclass, field
import json
import os
import re
import threading
from typing import Any, Protocol

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
        return ""


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
        return FeishuWorkflowCallback(
            source="feishu_review",
            workflow_id=str(payload.get("review_id") or payload.get("workflow_id") or ""),
            request_id=str(payload.get("request_id") or ""),
            action=str(payload.get("action") or ""),
            operator_open_id=str(payload.get("operator_open_id") or ""),
            status=str(payload.get("status") or _status_for_action(str(payload.get("action") or ""))),
            comment=str(payload.get("comment") or ""),
            fields=dict(payload.get("fields") or {}),
            raw=payload,
        )


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
class FeishuWorkflowService:
    config: FeishuWorkflowConfig = field(default_factory=FeishuWorkflowConfig.from_env)
    review_client: FeishuReviewClient = field(default_factory=InMemoryFeishuReviewClient)
    approval_client: FeishuApprovalClient = field(default_factory=InMemoryFeishuApprovalClient)

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
                metadata={"review_chat_id": request.chat_id},
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
    ) -> None:
        self.config = config or FeishuConfig.from_env()
        self.handler = handler or PmcAgentFeishuHandler()
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
    return FeishuBot(config=FeishuConfig.from_env(), handler=PmcAgentFeishuHandler())


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
