from __future__ import annotations

import unittest

from pmc_agent.external_integrations.feishu import FeishuInboundMessage
from pmc_agent.external_integrations.feishu import FeishuReviewRequest
from pmc_agent.external_integrations.feishu import FeishuWorkflowConfig
from pmc_agent.external_integrations.feishu import FeishuWorkflowService
from pmc_agent.external_integrations.feishu import InMemoryFeishuApprovalClient
from pmc_agent.external_integrations.feishu import InMemoryFeishuReviewClient
from pmc_agent.external_integrations.feishu import _normalize_event, _split_text


class _Object:
    def __init__(self, **kwargs):
        self.__dict__.update(kwargs)


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
