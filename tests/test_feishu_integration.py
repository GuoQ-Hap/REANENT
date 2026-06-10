from __future__ import annotations

import json
import unittest

from pmc_agent.external_integrations.feishu import FeishuInboundMessage
from pmc_agent.external_integrations.feishu import FeishuConfig
from pmc_agent.external_integrations.feishu import FeishuBot
from pmc_agent.external_integrations.feishu import FeishuReviewRequest
from pmc_agent.external_integrations.feishu import FeishuWorkflowConfig
from pmc_agent.external_integrations.feishu import FeishuWorkflowService
from pmc_agent.external_integrations.feishu import HttpFeishuApprovalClient
from pmc_agent.external_integrations.feishu import HttpFeishuReviewClient
from pmc_agent.external_integrations.feishu import InMemoryFeishuApprovalClient
from pmc_agent.external_integrations.feishu import InMemoryFeishuReviewClient
from pmc_agent.external_integrations.feishu import _build_review_card
from pmc_agent.external_integrations.feishu import _normalize_card_action_event
from pmc_agent.external_integrations.feishu import _normalize_event, _split_text
from pmc_agent.workflows import SkuFeedbackAction, SkuIssueStatus


class _Object:
    def __init__(self, **kwargs):
        self.__dict__.update(kwargs)


class _FakeIssue:
    sku = "A100"
    status = SkuIssueStatus.RECORDED
    feedback = _Object(action=SkuFeedbackAction.SALES_CONTROL)


class _FakeWorkflowHandler:
    def __init__(self) -> None:
        self.payloads = []

    def handle_feishu_callback(self, payload):
        self.payloads.append(payload)
        return _FakeIssue()


class FeishuIntegrationTests(unittest.TestCase):
    def test_group_message_session_uses_chat_id(self) -> None:
        message = FeishuInboundMessage(
            message_id="om_1",
            chat_id="oc_1",
            chat_type="group",
            text="检查 A100 是否有缺料风险",
            open_id="ou_1",
        )

        self.assertEqual("pmc-feishu-chat-oc_1", message.session_id)

    def test_p2p_message_session_uses_open_id(self) -> None:
        message = FeishuInboundMessage(
            message_id="om_1",
            chat_id="oc_1",
            chat_type="p2p",
            text="检查 A100 是否有缺料风险",
            open_id="ou_1",
        )

        self.assertEqual("pmc-feishu-user-ou_1", message.session_id)

    def test_normalize_text_event_removes_group_mentions(self) -> None:
        data = _Object(
            event_id="ev_1",
            event=_Object(
                tenant_key="tenant_1",
                sender=_Object(sender_id=_Object(open_id="ou_1", user_id="u_1")),
                message=_Object(
                    message_id="om_1",
                    chat_id="oc_1",
                    chat_type="group",
                    message_type="text",
                    content='{"text": "@_mention_1 检查 A100 是否有缺料风险"}',
                    mentions=[_Object(key="mention_1", name="PMC库存智能体")],
                ),
            ),
        )

        message = _normalize_event(data)

        self.assertIsNotNone(message)
        self.assertEqual("检查 A100 是否有缺料风险", message.text)
        self.assertEqual("ou_1", message.open_id)
        self.assertEqual("u_1", message.user_id)
        self.assertEqual("tenant_1", message.tenant_key)

    def test_normalize_card_action_event_extracts_business_payload(self) -> None:
        data = _Object(
            event_id="ev_card_1",
            event=_Object(
                operator=_Object(operator_id=_Object(open_id="ou_owner")),
                context=_Object(open_message_id="om_card_1"),
                action=_Object(
                    value={
                        "action": "submit_owner_feedback",
                        "request_id": "issue-A100-owner-feedback-0",
                        "issue_id": "issue-A100",
                        "review_stage": "owner_feedback",
                    },
                    form_value={
                        "feedback_actions": ["sales_control", "promotion"],
                        "feedback_comment": "先控销，再促销清库存",
                    },
                ),
            ),
        )

        payload = _normalize_card_action_event(data)

        self.assertEqual("feishu_review", payload["source"])
        self.assertEqual("ev_card_1", payload["workflow_id"])
        self.assertEqual("issue-A100-owner-feedback-0", payload["request_id"])
        self.assertEqual("submit_owner_feedback", payload["action"])
        self.assertEqual("ou_owner", payload["operator_open_id"])
        self.assertEqual("issue-A100", payload["fields"]["issue_id"])
        self.assertEqual("owner_feedback", payload["fields"]["review_stage"])
        self.assertEqual(["sales_control", "promotion"], payload["fields"]["feedback_actions"])
        self.assertEqual("先控销，再促销清库存", payload["fields"]["feedback_comment"])

    def test_card_action_trigger_returns_feedback_toast(self) -> None:
        workflow_handler = _FakeWorkflowHandler()
        bot = FeishuBot(
            config=FeishuConfig(enabled=False, app_id="", app_secret=""),
            handler=_Object(handle_message=lambda message: ""),
            workflow_event_handler=workflow_handler,
        )
        data = _Object(
            event_id="ev_card_1",
            event=_Object(
                operator=_Object(operator_id=_Object(open_id="ou_owner")),
                context=_Object(open_message_id="om_card_1"),
                action=_Object(
                    value={
                        "action": "sales_control",
                        "request_id": "issue-A100-owner-feedback-0",
                        "issue_id": "issue-A100",
                        "review_stage": "owner_feedback",
                    }
                ),
            ),
        )

        response = bot._on_card_action_trigger(data)

        self.assertEqual(1, len(workflow_handler.payloads))
        self.assertEqual("success", response.toast.type)
        self.assertIn("A100", response.toast.content)
        self.assertIn("销售控销", response.toast.content)

    def test_split_text_respects_limit(self) -> None:
        chunks = _split_text("abc\ndef\nghi", 5)

        self.assertEqual(["abc", "def", "ghi"], chunks)
        self.assertTrue(all(len(chunk) <= 5 for chunk in chunks))

    def test_review_service_routes_low_risk_to_card_review(self) -> None:
        review_client = InMemoryFeishuReviewClient()
        approval_client = InMemoryFeishuApprovalClient()
        service = FeishuWorkflowService(
            config=FeishuWorkflowConfig(
                approval_enabled=True,
                default_review_chat_id="oc_default",
                purchase_review_chat_id="oc_purchase",
                purchase_approval_code="approval_purchase",
            ),
            review_client=review_client,
            approval_client=approval_client,
        )
        request = FeishuReviewRequest(
            request_id="req_1",
            business_type="purchase_confirmation",
            title="采购建议审核",
            summary="建议采购 120 件",
            risk_level="medium",
        )

        result = service.submit(request)

        self.assertTrue(result.ok)
        self.assertEqual("review_card", result.channel)
        self.assertEqual("pending_review", result.status)
        self.assertEqual("oc_purchase", review_client.submitted[0].chat_id)
        self.assertEqual([], approval_client.created)

    def test_http_review_client_sends_interactive_card(self) -> None:
        calls = []

        def transport(url, payload, headers):
            calls.append({"url": url, "payload": payload, "headers": headers})
            if url.endswith("/open-apis/auth/v3/tenant_access_token/internal"):
                return {"code": 0, "tenant_access_token": "tenant-token", "expire": 7200}
            self.assertIn("/open-apis/im/v1/messages?receive_id_type=chat_id", url)
            self.assertEqual("Bearer tenant-token", headers["Authorization"])
            return {"code": 0, "data": {"message_id": "om_review_1"}}

        client = HttpFeishuReviewClient(
            config=FeishuConfig(
                enabled=True,
                app_id="cli_app",
                app_secret="cli_secret",
                bot_name="PMC库存智能体",
                api_base_url="https://open.feishu.test",
            ),
            transport=transport,
        )
        request = FeishuReviewRequest(
            request_id="req_card_1",
            business_type="purchase_confirmation",
            title="采购建议审核",
            summary="建议采购 120 件，需要人工确认。",
            business_object={"sku": "A100", "quantity": 120},
            suggested_action="确认是否按 MOQ 下单",
            risk_level="medium",
            chat_id="oc_review",
        )

        result = client.submit_review(request)

        self.assertTrue(result.ok)
        self.assertEqual("review-req_card_1", result.review_id)
        self.assertEqual("om_review_1", result.message_id)
        self.assertEqual(2, len(calls))
        message_payload = calls[1]["payload"]
        self.assertEqual("oc_review", message_payload["receive_id"])
        self.assertEqual("interactive", message_payload["msg_type"])
        card = json.loads(message_payload["content"])
        self.assertEqual("采购建议审核", card["header"]["title"]["content"])
        self.assertIn("req_card_1", json.dumps(card, ensure_ascii=False))

    def test_http_review_client_sends_direct_cards_to_reviewers(self) -> None:
        calls = []

        def transport(url, payload, headers):
            calls.append({"url": url, "payload": payload, "headers": headers})
            if url.endswith("/open-apis/auth/v3/tenant_access_token/internal"):
                return {"code": 0, "tenant_access_token": "tenant-token", "expire": 7200}
            self.assertIn("/open-apis/im/v1/messages?receive_id_type=open_id", url)
            self.assertEqual("Bearer tenant-token", headers["Authorization"])
            return {"code": 0, "data": {"message_id": f"om_{payload['receive_id']}"}}

        client = HttpFeishuReviewClient(
            config=FeishuConfig(
                enabled=True,
                app_id="cli_app",
                app_secret="cli_secret",
                bot_name="PMC库存智能体",
                api_base_url="https://open.feishu.test",
            ),
            transport=transport,
        )
        request = FeishuReviewRequest(
            request_id="req_direct_1",
            business_type="purchase_confirmation",
            title="采购建议审核",
            summary="建议采购 120 件，需要人工确认。",
            risk_level="medium",
            reviewer_open_ids=("ou_pmc", "ou_purchase"),
        )

        result = client.submit_review(request)

        self.assertTrue(result.ok)
        self.assertEqual("om_ou_pmc", result.message_id)
        self.assertEqual(3, len(calls))
        self.assertEqual("ou_pmc", calls[1]["payload"]["receive_id"])
        self.assertEqual("ou_purchase", calls[2]["payload"]["receive_id"])
        self.assertEqual("interactive", calls[1]["payload"]["msg_type"])

    def test_review_card_includes_metadata_in_button_values(self) -> None:
        card = _build_review_card(
            FeishuReviewRequest(
                request_id="issue-A100-pmc-review",
                business_type="pmc_sku_issue_review",
                title="PMC初审",
                summary="A100 shortage",
                risk_level="high",
                metadata={
                    "issue_id": "issue-A100",
                    "review_stage": "pmc_initial_review",
                    "assignment_department": "sales",
                    "assignment_owner_open_id": "ou_sales",
                },
            ),
            "PMC库存智能体",
        )

        actions = card["elements"][-1]["actions"]
        value = actions[0]["value"]

        self.assertEqual("approve", value["action"])
        self.assertEqual("issue-A100", value["issue_id"])
        self.assertEqual("pmc_initial_review", value["review_stage"])
        self.assertEqual("sales", value["assignment_department"])

    def test_owner_feedback_card_uses_multi_select_form(self) -> None:
        card = _build_review_card(
            FeishuReviewRequest(
                request_id="issue-A100-owner-feedback-0",
                business_type="sales_sku_feedback",
                title="处理反馈",
                summary="A100 shortage",
                risk_level="high",
                metadata={"issue_id": "issue-A100", "review_stage": "owner_feedback"},
            ),
            "PMC库存智能体",
        )

        form = card["elements"][-1]
        selector = form["elements"][1]["columns"][0]["elements"][0]
        button = form["elements"][1]["columns"][1]["elements"][0]
        comment_input = form["elements"][2]

        self.assertEqual("form", form["tag"])
        self.assertEqual("multi_select_static", selector["tag"])
        self.assertEqual("feedback_actions", selector["name"])
        self.assertTrue(selector["required"])
        self.assertEqual("input", comment_input["tag"])
        self.assertEqual("feedback_comment", comment_input["name"])
        self.assertEqual("form_submit", button["action_type"])
        self.assertEqual("确认处理", button["text"]["content"])
        self.assertEqual("submit_owner_feedback", button["value"]["action"])

    def test_http_review_client_requires_recipient(self) -> None:
        client = HttpFeishuReviewClient(
            config=FeishuConfig(enabled=True, app_id="cli_app", app_secret="cli_secret"),
            transport=lambda *_: {"code": 0},
        )

        result = client.submit_review(
            FeishuReviewRequest(
                request_id="req_no_chat",
                business_type="purchase_confirmation",
                title="采购建议审核",
                summary="建议采购 120 件",
                risk_level="medium",
            )
        )

        self.assertFalse(result.ok)
        self.assertEqual("缺少飞书审核接收人 chat_id 或 reviewer_open_ids", result.error)

    def test_review_service_routes_high_risk_purchase_to_approval(self) -> None:
        review_client = InMemoryFeishuReviewClient()
        approval_client = InMemoryFeishuApprovalClient()
        service = FeishuWorkflowService(
            config=FeishuWorkflowConfig(
                approval_enabled=True,
                purchase_approval_code="approval_purchase",
            ),
            review_client=review_client,
            approval_client=approval_client,
        )
        request = FeishuReviewRequest(
            request_id="req_2",
            business_type="purchase_confirmation",
            title="采购建议审批",
            summary="高风险，建议采购 500 件",
            risk_level="high",
            suggested_action="提交采购确认",
            reviewer_open_ids=("ou_pmc", "ou_purchase"),
        )

        result = service.submit(request)

        self.assertTrue(result.ok)
        self.assertEqual("approval_flow", result.channel)
        self.assertEqual("approval-req_2", result.approval_id)
        self.assertEqual([], review_client.submitted)
        self.assertEqual("approval_purchase", approval_client.created[0].approval_code)
        self.assertEqual(("ou_pmc", "ou_purchase"), approval_client.created[0].approver_open_ids)

    def test_approval_requires_configured_approval_code(self) -> None:
        service = FeishuWorkflowService(
            config=FeishuWorkflowConfig(approval_enabled=True),
            review_client=InMemoryFeishuReviewClient(),
            approval_client=InMemoryFeishuApprovalClient(),
        )
        request = FeishuReviewRequest(
            request_id="req_3",
            business_type="purchase_confirmation",
            title="采购建议审批",
            summary="高风险，建议采购 500 件",
            risk_level="high",
        )

        result = service.submit(request)

        self.assertFalse(result.ok)
        self.assertEqual("failed", result.status)
        self.assertEqual("缺少飞书审批码", result.error)

    def test_http_approval_client_creates_approval_instance(self) -> None:
        calls = []

        def transport(url, payload, headers):
            calls.append({"url": url, "payload": payload, "headers": headers})
            if url.endswith("/open-apis/auth/v3/tenant_access_token/internal"):
                return {"code": 0, "tenant_access_token": "tenant-token", "expire": 7200}
            if "/open-apis/approval/v4/approvals/" in url:
                return {"code": 0, "data": {"form": "[]", "node_list": []}}
            self.assertTrue(url.endswith("/open-apis/approval/v4/instances"))
            self.assertEqual("Bearer tenant-token", headers["Authorization"])
            return {"code": 0, "data": {"instance_code": "approval_instance_1"}}

        approval_client = HttpFeishuApprovalClient(
            config=FeishuConfig(
                enabled=True,
                app_id="cli_app",
                app_secret="cli_secret",
                api_base_url="https://open.feishu.test",
            ),
            workflow_config=FeishuWorkflowConfig(
                approval_enabled=True,
                approval_start_open_id="ou_pmc_robot",
                purchase_approval_node_id="pmc_reviewer",
            ),
            transport=transport,
        )
        service = FeishuWorkflowService(
            config=FeishuWorkflowConfig(
                approval_enabled=True,
                purchase_approval_code="approval_purchase",
            ),
            review_client=InMemoryFeishuReviewClient(),
            approval_client=approval_client,
        )
        request = FeishuReviewRequest(
            request_id="req_approval_http",
            business_type="purchase_confirmation",
            title="采购建议审批",
            summary="高风险，建议采购 500 件",
            risk_level="high",
            suggested_action="提交采购确认",
            reviewer_open_ids=("ou_pmc", "ou_purchase"),
            business_object={"sku": "A100", "quantity": 500},
        )

        result = service.submit(request)

        self.assertTrue(result.ok)
        self.assertEqual("approval_flow", result.channel)
        self.assertEqual("approval_instance_1", result.approval_id)
        self.assertEqual(3, len(calls))
        payload = calls[2]["payload"]
        self.assertEqual("approval_purchase", payload["approval_code"])
        self.assertEqual("ou_pmc_robot", payload["open_id"])
        self.assertEqual([{"key": "pmc_reviewer", "value": ["ou_pmc", "ou_purchase"]}], payload["node_approver_open_id_list"])
        form = json.loads(payload["form"])
        self.assertIn({"id": "summary", "type": "textarea", "value": "高风险，建议采购 500 件"}, form)

    def test_http_approval_client_queries_approval_instance(self) -> None:
        calls = []

        def transport(url, payload, headers):
            calls.append({"url": url, "payload": payload, "headers": headers})
            if url.endswith("/open-apis/auth/v3/tenant_access_token/internal"):
                return {"code": 0, "tenant_access_token": "tenant-token", "expire": 7200}
            self.assertTrue(url.endswith("/open-apis/approval/v4/instances/query"))
            self.assertEqual({"instance_code": "approval_instance_1", "page_size": 10}, payload)
            return {
                "code": 0,
                "data": {
                    "instance_list": [
                        {
                            "instance": {
                                "code": "approval_instance_1",
                                "status": "approved",
                                "task_list": [{"status": "APPROVED", "open_id": "ou_manager", "comment": "通过"}],
                            }
                        }
                    ]
                },
            }

        approval_client = HttpFeishuApprovalClient(
            config=FeishuConfig(
                enabled=True,
                app_id="cli_app",
                app_secret="cli_secret",
                api_base_url="https://open.feishu.test",
            ),
            transport=transport,
        )

        instance = approval_client.get_approval_instance("approval_instance_1")

        self.assertTrue(instance.ok)
        self.assertEqual("approved", instance.status)
        self.assertEqual("ou_manager", instance.operator_open_id)
        self.assertEqual("通过", instance.comment)
        self.assertEqual(2, len(calls))

    def test_parse_review_callback(self) -> None:
        service = FeishuWorkflowService()

        callback = service.parse_callback(
            {
                "source": "feishu_review",
                "review_id": "review-req_1",
                "request_id": "req_1",
                "action": "approve",
                "operator_open_id": "ou_1",
                "comment": "同意",
            }
        )

        self.assertEqual("feishu_review", callback.source)
        self.assertEqual("review-req_1", callback.workflow_id)
        self.assertEqual("approved", callback.status)
        self.assertEqual("ou_1", callback.operator_open_id)

    def test_parse_approval_callback(self) -> None:
        service = FeishuWorkflowService()

        callback = service.parse_callback(
            {
                "source": "feishu_approval",
                "approval_id": "approval-req_2",
                "request_id": "req_2",
                "action": "reject",
                "operator_open_id": "ou_manager",
                "fields": {"reason": "数量需重算"},
            }
        )

        self.assertEqual("feishu_approval", callback.source)
        self.assertEqual("approval-req_2", callback.workflow_id)
        self.assertEqual("rejected", callback.status)
        self.assertEqual({"reason": "数量需重算"}, callback.fields)


if __name__ == "__main__":
    unittest.main()
