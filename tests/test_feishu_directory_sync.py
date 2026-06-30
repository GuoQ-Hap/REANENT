from __future__ import annotations

import json
import tempfile
import unittest

from pmc_agent.external_integrations.feishu_directory import (
    FeishuDepartment,
    FeishuDirectoryClient,
    FeishuDirectoryConfig,
    FeishuDirectorySyncService,
    FeishuEmployee,
    InMemoryCompanyDirectoryRepository,
    JsonlCompanyDirectoryRepository,
)


class FeishuDirectorySyncTests(unittest.TestCase):
    def test_sync_fetches_department_tree_and_active_employees_by_department(self) -> None:
        calls = []

        def transport(url, payload, headers):
            calls.append({"url": url, "payload": payload, "headers": headers})
            if url.endswith("/open-apis/auth/v3/tenant_access_token/internal"):
                return {"code": 0, "tenant_access_token": "tenant-token", "expire": 7200}
            if url.endswith("/open-apis/directory/v1/departments/filter"):
                parent_id = _condition_value(payload, "parent_department_id")
                page_token = payload["page_request"]["page_token"]
                if parent_id == "0" and not page_token:
                    return {
                        "code": 0,
                        "data": {
                            "departments": [_department("D_SALES", "Sales", "0", has_child=True)],
                            "page_response": {"has_more": True, "page_token": "next-root"},
                        },
                    }
                if parent_id == "0" and page_token == "next-root":
                    return {"code": 0, "data": {"departments": [_department("D_PURCHASE", "Purchase", "0")]}}
                if parent_id == "D_SALES":
                    return {"code": 0, "data": {"departments": [_department("D_AMZ", "Amazon Sales", "D_SALES")]}}
                return {"code": 0, "data": {"departments": []}}
            if url.endswith("/open-apis/directory/v1/employees/filter"):
                department_id = _condition_value(payload, "base_info.departments.department_id")
                self.assertEqual("1", _raw_condition_value(payload, "work_info.staff_status"))
                self.assertIn("base_info.open_id", payload["required_fields"])
                if department_id == "D_SALES":
                    return {"code": 0, "data": {"employees": [_employee("E1", "ou_1", "Alice", ["D_SALES", "D_AMZ"])]}}
                if department_id == "D_PURCHASE":
                    return {"code": 0, "data": {"employees": [_employee("E2", "ou_2", "Bob", ["D_PURCHASE"])]}}
                if department_id == "D_AMZ":
                    return {"code": 0, "data": {"employees": [_employee("E1", "ou_1", "Alice", ["D_SALES", "D_AMZ"])]}}
                return {"code": 0, "data": {"employees": []}}
            raise AssertionError(f"unexpected url: {url}")

        client = FeishuDirectoryClient(
            config=FeishuDirectoryConfig(enabled=True, app_id="cli_app", app_secret="secret", api_base_url="https://open.feishu.test"),
            transport=transport,
        )
        repository = InMemoryCompanyDirectoryRepository()
        result = FeishuDirectorySyncService(client=client, repository=repository).sync(batch_id="batch-1")

        self.assertTrue(result.ok)
        self.assertEqual(3, result.department_count)
        self.assertEqual(2, result.employee_count)
        self.assertEqual(3, result.employee_department_count)
        self.assertEqual({"D_SALES", "D_PURCHASE", "D_AMZ"}, set(repository.departments))
        self.assertEqual({"E1", "E2"}, set(repository.employees))
        self.assertIn(("E1", "D_AMZ"), repository.employee_departments)
        self.assertEqual(1, len([call for call in calls if call["url"].endswith("/tenant_access_token/internal")]))

    def test_jsonl_repository_marks_missing_employee_inactive(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            repository = JsonlCompanyDirectoryRepository(tmpdir)
            old_employee = FeishuEmployee(employee_id="E_OLD", open_id="ou_old", name="Old Employee", staff_status="1")
            current_employee = FeishuEmployee(employee_id="E_NEW", open_id="ou_new", name="New Employee", staff_status="1")

            repository.save_snapshot([], [old_employee], [], batch_id="old-batch", synced_at="2026-06-15T00:00:00+00:00")
            inactive_count = repository.save_snapshot([], [current_employee], [], batch_id="new-batch", synced_at="2026-06-16T00:00:00+00:00")
            latest = {row["feishu_employee_id"]: row for row in repository.list_latest_employees()}

        self.assertEqual(1, inactive_count)
        self.assertEqual("active", latest["E_NEW"]["sync_status"])
        self.assertEqual("inactive_missing_from_sync", latest["E_OLD"]["sync_status"])
        self.assertTrue(latest["E_OLD"]["is_resigned"])

    def test_sync_reports_missing_department_identity_fields(self) -> None:
        def transport(url, payload, headers):
            if url.endswith("/open-apis/auth/v3/tenant_access_token/internal"):
                return {"code": 0, "tenant_access_token": "tenant-token", "expire": 7200}
            if url.endswith("/open-apis/directory/v1/departments/filter"):
                return {"code": 0, "data": {"departments": [{"department_count": {}, "parent_department_id": "0"}]}}
            raise AssertionError(f"unexpected url: {url}")

        client = FeishuDirectoryClient(
            config=FeishuDirectoryConfig(enabled=True, app_id="cli_app", app_secret="secret", api_base_url="https://open.feishu.test"),
            transport=transport,
        )
        result = FeishuDirectorySyncService(client=client, repository=InMemoryCompanyDirectoryRepository()).sync(batch_id="batch-missing-fields")

        self.assertFalse(result.ok)
        self.assertIn("department_id", result.errors[0])

    def test_department_and_employee_models_accept_flat_or_nested_payloads(self) -> None:
        department = FeishuDepartment.from_payload({"department_id": "D1", "name": {"default_value": "PMC"}, "has_child": 1})
        employee = FeishuEmployee.from_payload(
            {
                "base_info.employee_id": "E1",
                "base_info.open_id": "ou_1",
                "base_info.name": {"name": {"default_value": "Alice", "i18n_value": {"zh_cn": "爱丽丝"}}},
                "work_info.job_title.job_title_name": "Planner",
            }
        )

        self.assertEqual("D1", department.department_id)
        self.assertEqual("PMC", department.name)
        self.assertTrue(department.has_child)
        self.assertEqual("E1", employee.employee_id)
        self.assertEqual("ou_1", employee.open_id)
        self.assertEqual("Alice", employee.name)
        self.assertEqual("Planner", employee.job_title_name)


def _department(department_id: str, name: str, parent_id: str, has_child: bool = False) -> dict:
    return {
        "department_id": department_id,
        "name": name,
        "parent_department_id": parent_id,
        "department_path_infos": [{"department_id": parent_id}, {"department_id": department_id}],
        "enabled_status": "enabled",
        "leaders": [],
        "has_child": has_child,
        "order_weight": "1",
    }


def _employee(employee_id: str, open_id: str, name: str, department_ids: list[str]) -> dict:
    departments = [{"department_id": department_id, "name": department_id, "is_primary": index == 0} for index, department_id in enumerate(department_ids)]
    return {
        "base_info": {
            "employee_id": employee_id,
            "open_id": open_id,
            "name": name,
            "departments": departments,
            "department_path_infos": [{"department_id": department_id} for department_id in department_ids],
            "leader_id": "leader_1",
            "active_status": "active",
            "is_resigned": False,
        },
        "work_info": {
            "job_number": f"JOB-{employee_id}",
            "staff_status": "1",
            "join_date": "2024-01-01",
            "job_title": {"job_title_id": "JT1", "job_title_name": "Planner"},
            "positions": [{"department_id": department_id, "position_id": f"P-{department_id}"} for department_id in department_ids],
        },
    }


def _condition_value(payload: dict, field: str) -> str:
    return json.loads(_raw_condition_value(payload, field))


def _raw_condition_value(payload: dict, field: str) -> str:
    for condition in payload["filter"]["conditions"]:
        if condition["field"] == field:
            return condition["value"]
    raise AssertionError(f"missing condition: {field}")


if __name__ == "__main__":
    unittest.main()
