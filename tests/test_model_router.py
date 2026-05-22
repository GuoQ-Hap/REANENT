import os
import unittest

from pmc_agent.model_router import ModelAction, ModelRouteRequest, ModelRouter, ModelRoutingPolicy


class ModelRouterTests(unittest.TestCase):
    def test_routes_by_action(self):
        router = ModelRouter(
            ModelRoutingPolicy(
                intent_model="intent-mini",
                goal_repair_model="goal-strong",
                summary_model="summary-mini",
                failure_handling_model="failure-strong",
            )
        )

        intent = router.route(ModelRouteRequest(action=ModelAction.INTENT_RECOGNITION, content="检查库存风险"))
        repair = router.route(ModelRouteRequest(action=ModelAction.GOAL_REPAIR, content="按反馈重算"))
        summary = router.route(ModelRouteRequest(action=ModelAction.SUMMARY, content="总结本轮输出"))
        failure = router.route(ModelRouteRequest(action=ModelAction.FAILURE_HANDLING, content="数据库查不到物料"))

        self.assertEqual(intent.model, "intent-mini")
        self.assertEqual(repair.model, "goal-strong")
        self.assertEqual(summary.model, "summary-mini")
        self.assertEqual(failure.model, "failure-strong")

    def test_high_risk_content_uses_high_risk_model(self):
        router = ModelRouter(ModelRoutingPolicy(intent_model="intent-mini", high_risk_model="risk-strong"))

        decision = router.route(ModelRouteRequest(action=ModelAction.INTENT_RECOGNITION, content="请确认 A100 采购下单"))

        self.assertEqual(decision.model, "risk-strong")
        self.assertEqual(decision.source, "risk_policy")

    def test_failure_handling_uses_failure_model_before_risk_policy(self):
        router = ModelRouter(ModelRoutingPolicy(failure_handling_model="failure-strong", high_risk_model="risk-strong"))

        decision = router.route(ModelRouteRequest(action=ModelAction.FAILURE_HANDLING, content="采购查询失败"))

        self.assertEqual(decision.model, "failure-strong")
        self.assertEqual(decision.source, "action_policy")

    def test_env_overrides_action_models(self):
        os.environ["PMC_AGENT_MODEL_INTENT_RECOGNITION"] = "env-intent"
        os.environ["PMC_AGENT_MODEL_GOAL_REPAIR"] = "env-goal"
        try:
            policy = ModelRoutingPolicy.from_env()
        finally:
            os.environ.pop("PMC_AGENT_MODEL_INTENT_RECOGNITION", None)
            os.environ.pop("PMC_AGENT_MODEL_GOAL_REPAIR", None)

        self.assertEqual(policy.intent_model, "env-intent")
        self.assertEqual(policy.goal_repair_model, "env-goal")


if __name__ == "__main__":
    unittest.main()
