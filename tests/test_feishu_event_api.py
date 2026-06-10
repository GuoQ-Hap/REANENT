from __future__ import annotations

import os
import unittest

from pmc_agent.domain import RiskLevel
from pmc_agent.workflows import SkuIssueRecord, SkuIssueStatus

try:
    from fastapi.testclient import TestClient
    import pmc_agent.api as api
except ImportError:  # pragma: no cover - optional api dependency
    TestClient = None
    api = None


class FakeSkuIssueWorkflow:
    def __init__(self) -> None:
        self.payloads = []

    def handle_feishu_callback(self, payload):
        self.payloads.append(payload)
        return SkuIssueRecord(
            issue_id=payload["fields"]["issue_id"],
            sku="A100",
            issue_type="shortage",
            risk_level=RiskLevel.HIGH,
            summary="A100 shortage",
            suggested_department="sales",
            status=SkuIssueStatus.RECORDED,
        )


@unittest.skipIf(TestClient is None or api is None or api.app is None, "FastAPI is not installed")
class FeishuEventApiTests(unittest.TestCase):
    def setUp(self) -> None:
        self.original_workflow = api.sku_issue_workflow
        self.original_token = os.environ.get("FEISHU_EVENT_VERIFICATION_TOKEN")

    def tearDown(self) -> None:
        api.sku_issue_workflow = self.original_workflow
        if self.original_token is None:
            os.environ.pop("FEISHU_EVENT_VERIFICATION_TOKEN", None)
        else:
            os.environ["FEISHU_EVENT_VERIFICATION_TOKEN"] = self.original_token

    def test_feishu_url_verification_returns_challenge(self):
        client = TestClient(api.app)

        response = client.post("/feishu/events", json={"challenge": "challenge-token"})

        self.assertEqual(200, response.status_code)
        self.assertEqual({"challenge": "challenge-token"}, response.json())

    def test_feishu_card_event_calls_sku_issue_workflow(self):
        fake_workflow = FakeSkuIssueWorkflow()
        api.sku_issue_workflow = fake_workflow
        os.environ["FEISHU_EVENT_VERIFICATION_TOKEN"] = "verify-token"
        client = TestClient(api.app)

        response = client.post(
            "/feishu/events",
            json={
                "type": "card.action.trigger",
                "token": "verify-token",
                "event": {
                    "operator": {"operator_id": {"open_id": "ou_owner"}},
                    "context": {"open_message_id": "om_1"},
                    "action": {
                        "value": {
                            "action": "sales_control",
                            "request_id": "issue-A100-owner-feedback-0",
                            "issue_id": "issue-A100",
                            "review_stage": "owner_feedback",
                        }
                    },
                },
            },
        )

        self.assertEqual(200, response.status_code)
        self.assertEqual("issue-A100", response.json()["issue_id"])
        self.assertEqual(SkuIssueStatus.RECORDED, response.json()["status"])
        self.assertEqual("sales_control", fake_workflow.payloads[0]["action"])
        self.assertEqual("ou_owner", fake_workflow.payloads[0]["operator_open_id"])
        self.assertEqual("owner_feedback", fake_workflow.payloads[0]["fields"]["review_stage"])

    def test_feishu_event_rejects_invalid_token(self):
        os.environ["FEISHU_EVENT_VERIFICATION_TOKEN"] = "verify-token"
        client = TestClient(api.app)

        response = client.post(
            "/feishu/events",
            json={"token": "wrong-token", "value": {"issue_id": "issue-A100", "review_stage": "owner_feedback"}},
        )

        self.assertEqual(403, response.status_code)


if __name__ == "__main__":
    unittest.main()
