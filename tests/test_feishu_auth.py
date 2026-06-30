from __future__ import annotations

import json
import tempfile
import unittest

from pmc_agent.auth import (
    AuthenticatedUser,
    FeishuAuthConfig,
    FeishuAuthService,
    FeishuOAuthClient,
    PermissionRuleEngine,
    SignedPayloadCodec,
    UserPermissions,
    apply_permission_filters,
    item_allowed,
)
from tests.fake_control_tower import FakeMainRuleConnector

try:
    from fastapi.testclient import TestClient
    import pmc_agent.api as api
except ImportError:  # pragma: no cover - optional api dependency
    TestClient = None
    api = None


class FeishuAuthTests(unittest.TestCase):
    def test_oauth_client_exchanges_code_and_fetches_user_info(self) -> None:
        calls = []

        def transport(url, payload, headers, method):
            calls.append({"url": url, "payload": payload, "headers": headers, "method": method})
            if url.endswith("/open-apis/auth/v3/app_access_token/internal"):
                return {"code": 0, "app_access_token": "app-token", "expire": 7200}
            if url.endswith("/open-apis/authen/v1/access_token"):
                self.assertEqual("Bearer app-token", headers["Authorization"])
                self.assertEqual({"grant_type": "authorization_code", "code": "login-code"}, payload)
                return {"code": 0, "data": {"access_token": "user-token", "open_id": "ou_1"}}
            if url.endswith("/open-apis/authen/v1/user_info"):
                self.assertEqual("GET", method)
                self.assertEqual("Bearer user-token", headers["Authorization"])
                return {
                    "code": 0,
                    "data": {
                        "open_id": "ou_1",
                        "user_id": "u_1",
                        "name": "Alice",
                    },
                }
            if url.endswith("/open-apis/auth/v3/tenant_access_token/internal"):
                return {"code": 0, "tenant_access_token": "tenant-token", "expire": 7200}
            if "/open-apis/contact/v3/users/u_1?" in url:
                self.assertEqual("GET", method)
                self.assertEqual("Bearer tenant-token", headers["Authorization"])
                return {
                    "code": 0,
                    "data": {
                        "user": {
                            "open_id": "ou_1",
                            "user_id": "u_1",
                            "employee_id": "E1",
                            "department_ids": ["od_sales"],
                        }
                    },
                }
            raise AssertionError(f"unexpected url: {url}")

        client = FeishuOAuthClient(
            config=FeishuAuthConfig(enabled=True, app_id="cli_app", app_secret="secret", api_base_url="https://open.feishu.test"),
            transport=transport,
        )

        user = client.authenticate_code("login-code")

        self.assertEqual("ou_1", user.open_id)
        self.assertEqual("Alice", user.name)
        self.assertEqual("E1", user.employee_id)
        self.assertEqual(("od_sales",), user.department_ids)
        self.assertEqual(5, len(calls))

    def test_permission_rule_scopes_filters_and_items(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            path = f"{tmpdir}/rules.json"
            with open(path, "w", encoding="utf-8") as handle:
                json.dump(
                    {
                        "rules": [
                            {
                                "id": "sales-na",
                                "role": "sales_manager",
                                "match": {"department_ids": ["od_sales"]},
                                "features": ["overview", "export"],
                                "data_scope": {"sales_department": ["North America"]},
                            }
                        ]
                    },
                    handle,
                )

            config = FeishuAuthConfig(permission_rules_path=path)
            engine = PermissionRuleEngine.from_config(config)
            user = AuthenticatedUser(open_id="ou_1", name="Alice", department_ids=("od_sales",))
            permissions = engine.permissions_for(user)

        self.assertEqual("sales_manager", permissions.role)
        self.assertTrue(permissions.allows_feature("export"))
        self.assertEqual({"sales_department": ("North America",)}, permissions.data_scope)
        self.assertEqual(
            {"sales_apartment": ["North America"], "risk_only": True},
            apply_permission_filters({"sales_apartment": ["North America", "Clearance"], "risk_only": True}, permissions),
        )
        self.assertEqual(
            {"sales_apartment": ["__permission_no_data__"]},
            apply_permission_filters({"sales_apartment": ["Clearance"]}, permissions),
        )
        self.assertTrue(item_allowed({"sales_department": "North America"}, permissions))
        self.assertFalse(item_allowed({"sales_department": "Clearance"}, permissions))

    def test_signed_payload_rejects_tampering(self) -> None:
        codec = SignedPayloadCodec("secret")
        token = codec.encode({"user": "Alice"}, ttl_seconds=60)

        self.assertEqual("Alice", codec.decode(token)["user"])
        tampered = token[:-1] + ("A" if token[-1] != "A" else "B")
        with self.assertRaises(ValueError):
            codec.decode(tampered)


@unittest.skipIf(TestClient is None or api is None or api.app is None, "FastAPI is not installed")
class FeishuAuthApiTests(unittest.TestCase):
    def setUp(self) -> None:
        self.original_auth_service = api.auth_service
        self.original_connector = api.sku_diagnosis_connector
        self.config = FeishuAuthConfig(required=True, session_secret="test-secret", session_cookie_name="test_session")
        api.auth_service = FeishuAuthService(config=self.config)
        api.sku_diagnosis_connector = FakeMainRuleConnector()

    def tearDown(self) -> None:
        api.auth_service = self.original_auth_service
        api.sku_diagnosis_connector = self.original_connector

    def test_summary_requires_session_when_auth_required(self) -> None:
        client = TestClient(api.app)

        response = client.get("/control-tower/summary")

        self.assertEqual(401, response.status_code)

    def test_summary_applies_session_data_scope(self) -> None:
        permissions = UserPermissions(
            role="sales_manager",
            features=("overview",),
            data_scope={"sales_department": ("North America",)},
        )
        user = AuthenticatedUser(open_id="ou_1", name="Alice")
        session = api.auth_service.codec.encode(
            {"user": user.to_public_dict(), "permissions": permissions.to_public_dict()},
            ttl_seconds=3600,
        )
        client = TestClient(api.app)
        client.cookies.set(self.config.session_cookie_name, session)

        response = client.get("/control-tower/summary")

        self.assertEqual(200, response.status_code)
        payload = response.json()
        self.assertEqual(1, payload["pagination"]["total_count"])
        self.assertEqual(["North America"], payload["filter_options"]["sales_department"])
        self.assertEqual("A100", payload["items"][0]["material_code"])


if __name__ == "__main__":
    unittest.main()
