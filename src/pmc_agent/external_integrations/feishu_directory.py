from __future__ import annotations

from dataclasses import asdict, dataclass, field, replace
from datetime import datetime, timezone
import json
import os
from pathlib import Path
import time
import urllib.error
import urllib.request
import uuid
from typing import Any, Callable, Iterable, Protocol

from pmc_agent.app_logging import get_logger, log_extra
from pmc_agent.env import load_env_file


logger = get_logger(__name__)


DEFAULT_DEPARTMENT_FIELDS: tuple[str, ...] = (
    "department_id",
    "name",
    "parent_department_id",
    "department_path_infos",
    "enabled_status",
    "leaders",
    "has_child",
    "order_weight",
)

DEFAULT_EMPLOYEE_FIELDS: tuple[str, ...] = (
    "base_info.employee_id",
    "base_info.open_id",
    "base_info.user_id",
    "base_info.name",
    "base_info.mobile",
    "base_info.email",
    "base_info.enterprise_email",
    "base_info.gender",
    "base_info.avatar",
    "base_info.departments.department_id",
    "base_info.departments.name",
    "base_info.department_path_infos",
    "base_info.leader_id",
    "base_info.active_status",
    "base_info.is_resigned",
    "work_info.job_number",
    "work_info.staff_status",
    "work_info.join_date",
    "work_info.job_title.job_title_id",
    "work_info.job_title.job_title_name",
    "work_info.positions",
)


FeishuDirectoryTransport = Callable[[str, dict[str, Any], dict[str, str]], dict[str, Any]]


@dataclass(frozen=True)
class FeishuDirectoryConfig:
    enabled: bool = False
    app_id: str = ""
    app_secret: str = ""
    api_base_url: str = "https://open.feishu.cn"
    root_department_id: str = "0"
    department_page_size: int = 100
    employee_page_size: int = 100
    output_dir: str = "output/feishu_directory"
    department_required_fields: tuple[str, ...] = DEFAULT_DEPARTMENT_FIELDS
    employee_required_fields: tuple[str, ...] = DEFAULT_EMPLOYEE_FIELDS

    @classmethod
    def from_env(cls) -> "FeishuDirectoryConfig":
        load_env_file(override=False)
        return cls(
            enabled=_env_bool("FEISHU_DIRECTORY_SYNC_ENABLED", _env_bool("FEISHU_ENABLED", False)),
            app_id=os.getenv("FEISHU_APP_ID", ""),
            app_secret=os.getenv("FEISHU_APP_SECRET", ""),
            api_base_url=os.getenv("FEISHU_API_BASE_URL", "https://open.feishu.cn").rstrip("/"),
            root_department_id=os.getenv("FEISHU_DIRECTORY_ROOT_DEPARTMENT_ID", "0"),
            department_page_size=_env_int("FEISHU_DIRECTORY_DEPARTMENT_PAGE_SIZE", 100, minimum=1, maximum=100),
            employee_page_size=_env_int("FEISHU_DIRECTORY_EMPLOYEE_PAGE_SIZE", 100, minimum=1, maximum=100),
            output_dir=os.getenv("FEISHU_DIRECTORY_OUTPUT_DIR", "output/feishu_directory"),
            department_required_fields=_env_csv("FEISHU_DIRECTORY_DEPARTMENT_REQUIRED_FIELDS", DEFAULT_DEPARTMENT_FIELDS),
            employee_required_fields=_env_csv("FEISHU_DIRECTORY_EMPLOYEE_REQUIRED_FIELDS", DEFAULT_EMPLOYEE_FIELDS),
        )

    @property
    def ready(self) -> bool:
        return bool(self.enabled and self.app_id and self.app_secret)


@dataclass(frozen=True)
class FeishuDepartment:
    department_id: str
    name: str
    parent_department_id: str = ""
    department_path_infos: list[dict[str, Any]] = field(default_factory=list)
    enabled_status: str = ""
    leaders: list[dict[str, Any]] = field(default_factory=list)
    has_child: bool = False
    order_weight: str = ""
    raw: dict[str, Any] = field(default_factory=dict)

    @classmethod
    def from_payload(cls, payload: dict[str, Any]) -> "FeishuDepartment":
        return cls(
            department_id=str(_field(payload, "department_id") or ""),
            name=_text_value(_field(payload, "name")),
            parent_department_id=str(_field(payload, "parent_department_id") or ""),
            department_path_infos=_list_of_dicts(_field(payload, "department_path_infos")),
            enabled_status=str(_field(payload, "enabled_status") or ""),
            leaders=_list_of_dicts(_field(payload, "leaders")),
            has_child=_bool_value(_field(payload, "has_child")),
            order_weight=str(_field(payload, "order_weight") or ""),
            raw=dict(payload),
        )

    @property
    def depth(self) -> int:
        return max(0, len(self.department_path_infos) - 1) if self.department_path_infos else 0


@dataclass(frozen=True)
class FeishuEmployee:
    employee_id: str
    name: str
    open_id: str = ""
    user_id: str = ""
    mobile: str = ""
    email: str = ""
    enterprise_email: str = ""
    gender: str = ""
    avatar: Any = ""
    departments: list[dict[str, Any]] = field(default_factory=list)
    department_path_infos: list[dict[str, Any]] = field(default_factory=list)
    leader_id: str = ""
    active_status: str = ""
    is_resigned: bool = False
    job_number: str = ""
    staff_status: str = ""
    join_date: str = ""
    job_title_id: str = ""
    job_title_name: str = ""
    positions: list[dict[str, Any]] = field(default_factory=list)
    source_department_id: str = ""
    raw: dict[str, Any] = field(default_factory=dict)

    @classmethod
    def from_payload(cls, payload: dict[str, Any], source_department_id: str = "") -> "FeishuEmployee":
        return cls(
            employee_id=str(_field(payload, "base_info.employee_id") or _field(payload, "employee_id") or ""),
            open_id=str(_field(payload, "base_info.open_id") or _field(payload, "open_id") or ""),
            user_id=str(_field(payload, "base_info.user_id") or _field(payload, "user_id") or ""),
            name=_text_value(_field(payload, "base_info.name") or _field(payload, "name")),
            mobile=str(_field(payload, "base_info.mobile") or _field(payload, "mobile") or ""),
            email=str(_field(payload, "base_info.email") or _field(payload, "email") or ""),
            enterprise_email=str(_field(payload, "base_info.enterprise_email") or _field(payload, "enterprise_email") or ""),
            gender=str(_field(payload, "base_info.gender") or _field(payload, "gender") or ""),
            avatar=_field(payload, "base_info.avatar") or _field(payload, "avatar") or "",
            departments=_list_of_dicts(_field(payload, "base_info.departments") or _field(payload, "departments")),
            department_path_infos=_list_of_dicts(_field(payload, "base_info.department_path_infos") or _field(payload, "department_path_infos")),
            leader_id=str(_field(payload, "base_info.leader_id") or _field(payload, "leader_id") or ""),
            active_status=str(_field(payload, "base_info.active_status") or _field(payload, "active_status") or ""),
            is_resigned=_bool_value(_field(payload, "base_info.is_resigned") or _field(payload, "is_resigned")),
            job_number=str(_field(payload, "work_info.job_number") or _field(payload, "job_number") or ""),
            staff_status=str(_field(payload, "work_info.staff_status") or _field(payload, "staff_status") or ""),
            join_date=str(_field(payload, "work_info.join_date") or _field(payload, "join_date") or ""),
            job_title_id=str(_field(payload, "work_info.job_title.job_title_id") or _field(payload, "job_title_id") or ""),
            job_title_name=str(_field(payload, "work_info.job_title.job_title_name") or _field(payload, "job_title_name") or ""),
            positions=_list_of_dicts(_field(payload, "work_info.positions") or _field(payload, "positions")),
            source_department_id=source_department_id,
            raw=dict(payload),
        )

    @property
    def stable_id(self) -> str:
        return self.employee_id or self.open_id or self.user_id

    @property
    def primary_department_id(self) -> str:
        explicit = next((_department_id(dept) for dept in self.departments if _bool_value(dept.get("is_primary"))), "")
        if explicit:
            return explicit
        return _department_id(self.departments[0]) if self.departments else self.source_department_id


@dataclass(frozen=True)
class FeishuEmployeeDepartment:
    employee_id: str
    open_id: str
    department_id: str
    department_name: str = ""
    is_primary: bool = False
    department_path_infos: list[dict[str, Any]] = field(default_factory=list)
    positions: list[dict[str, Any]] = field(default_factory=list)
    source_department_id: str = ""


@dataclass(frozen=True)
class FeishuDirectorySyncResult:
    batch_id: str
    started_at: str
    finished_at: str
    department_count: int
    employee_count: int
    employee_department_count: int
    inactive_employee_count: int = 0
    errors: list[str] = field(default_factory=list)

    @property
    def ok(self) -> bool:
        return not self.errors


class CompanyDirectoryRepository(Protocol):
    def save_snapshot(
        self,
        departments: list[FeishuDepartment],
        employees: list[FeishuEmployee],
        employee_departments: list[FeishuEmployeeDepartment],
        *,
        batch_id: str,
        synced_at: str,
    ) -> int:
        ...


@dataclass
class InMemoryCompanyDirectoryRepository:
    departments: dict[str, FeishuDepartment] = field(default_factory=dict)
    employees: dict[str, FeishuEmployee] = field(default_factory=dict)
    employee_departments: dict[tuple[str, str], FeishuEmployeeDepartment] = field(default_factory=dict)
    inactive_employee_count: int = 0

    def save_snapshot(
        self,
        departments: list[FeishuDepartment],
        employees: list[FeishuEmployee],
        employee_departments: list[FeishuEmployeeDepartment],
        *,
        batch_id: str,
        synced_at: str,
    ) -> int:
        del batch_id, synced_at
        current_ids = {employee.stable_id for employee in employees if employee.stable_id}
        self.inactive_employee_count = len([key for key in self.employees if key not in current_ids])
        self.departments = {department.department_id: department for department in departments}
        self.employees = {employee.stable_id: employee for employee in employees if employee.stable_id}
        self.employee_departments = {
            (relation.employee_id or relation.open_id, relation.department_id): relation
            for relation in employee_departments
            if (relation.employee_id or relation.open_id) and relation.department_id
        }
        return self.inactive_employee_count


class JsonlCompanyDirectoryRepository:
    def __init__(self, directory: str | Path = "output/feishu_directory") -> None:
        self.directory = Path(directory)
        self.departments_path = self.directory / "sys_company_department.jsonl"
        self.employees_path = self.directory / "sys_company_employee.jsonl"
        self.employee_departments_path = self.directory / "sys_company_employee_department.jsonl"
        self.sync_runs_path = self.directory / "sys_company_directory_sync_run.jsonl"

    def save_snapshot(
        self,
        departments: list[FeishuDepartment],
        employees: list[FeishuEmployee],
        employee_departments: list[FeishuEmployeeDepartment],
        *,
        batch_id: str,
        synced_at: str,
    ) -> int:
        self.directory.mkdir(parents=True, exist_ok=True)
        current_employee_ids = {employee.stable_id for employee in employees if employee.stable_id}
        inactive_rows = self._inactive_employee_rows(current_employee_ids, batch_id, synced_at)

        self._append_jsonl(self.departments_path, [_department_row(item, batch_id, synced_at) for item in departments])
        self._append_jsonl(self.employees_path, [_employee_row(item, batch_id, synced_at, "active") for item in employees])
        self._append_jsonl(self.employees_path, inactive_rows)
        self._append_jsonl(
            self.employee_departments_path,
            [_employee_department_row(item, batch_id, synced_at) for item in employee_departments],
        )
        return len(inactive_rows)

    def record_sync_run(self, result: FeishuDirectorySyncResult) -> None:
        self.directory.mkdir(parents=True, exist_ok=True)
        self._append_jsonl(self.sync_runs_path, [asdict(result)])

    def list_latest_employees(self) -> list[dict[str, Any]]:
        return list(self._latest_rows_by_key(self.employees_path, _employee_row_key).values())

    def list_latest_departments(self) -> list[dict[str, Any]]:
        return list(self._latest_rows_by_key(self.departments_path, lambda row: str(row.get("feishu_department_id") or "")).values())

    def _inactive_employee_rows(self, current_employee_ids: set[str], batch_id: str, synced_at: str) -> list[dict[str, Any]]:
        latest = self._latest_rows_by_key(self.employees_path, _employee_row_key)
        inactive: list[dict[str, Any]] = []
        for key, row in latest.items():
            if not key or key in current_employee_ids or _employee_row_inactive(row):
                continue
            inactive.append(
                {
                    **row,
                    "batch_id": batch_id,
                    "synced_at": synced_at,
                    "sync_status": "inactive_missing_from_sync",
                    "staff_status": "inactive",
                    "active_status": "inactive",
                    "is_resigned": True,
                }
            )
        return inactive

    def _latest_rows_by_key(self, path: Path, key_fn: Callable[[dict[str, Any]], str]) -> dict[str, dict[str, Any]]:
        if not path.exists():
            return {}
        latest: dict[str, dict[str, Any]] = {}
        for line in path.read_text(encoding="utf-8").splitlines():
            if not line.strip():
                continue
            row = json.loads(line)
            key = key_fn(row)
            if key:
                latest[key] = row
        return latest

    def _append_jsonl(self, path: Path, rows: list[dict[str, Any]]) -> None:
        if not rows:
            return
        with path.open("a", encoding="utf-8") as handle:
            for row in rows:
                handle.write(json.dumps(row, ensure_ascii=False) + "\n")


@dataclass
class FeishuDirectoryClient:
    config: FeishuDirectoryConfig = field(default_factory=FeishuDirectoryConfig.from_env)
    transport: FeishuDirectoryTransport | None = None
    token_ttl_buffer_seconds: int = 120
    _tenant_access_token: str = field(default="", init=False)
    _token_expires_at: float = field(default=0, init=False)

    def fetch_department_tree(self, root_department_id: str | None = None) -> list[FeishuDepartment]:
        root = root_department_id if root_department_id is not None else self.config.root_department_id
        departments: list[FeishuDepartment] = []
        seen: set[str] = set()

        def visit(parent_department_id: str) -> None:
            for department in self.fetch_departments(parent_department_id):
                if not department.department_id or department.department_id in seen:
                    continue
                seen.add(department.department_id)
                departments.append(department)
                if department.has_child:
                    visit(department.department_id)

        visit(root)
        return departments

    def fetch_departments(self, parent_department_id: str = "0") -> list[FeishuDepartment]:
        payload_base = {
            "filter": {
                "conditions": [
                    {
                        "field": "parent_department_id",
                        "operator": "eq",
                        "value": _quoted_filter_value(parent_department_id),
                    }
                ]
            },
            "required_fields": list(self.config.department_required_fields),
        }
        items: list[FeishuDepartment] = []
        for response in self._post_paged(
            f"{self.config.api_base_url}/open-apis/directory/v1/departments/filter",
            payload_base,
            self.config.department_page_size,
        ):
            raw_items = _response_items(response, "departments", "department_infos")
            parsed = [FeishuDepartment.from_payload(item) for item in raw_items]
            if raw_items and not any(item.department_id for item in parsed):
                sample_keys = ",".join(raw_items[0].keys())
                raise RuntimeError(
                    "Feishu department response did not include department_id. "
                    "Check Directory department field permissions for department_id/name. "
                    f"sample_keys={sample_keys}"
                )
            items.extend(parsed)
            _log_field_errors(response, "feishu_department_filter")
        return items

    def fetch_active_employees(self, department_id: str) -> list[FeishuEmployee]:
        payload_base = {
            "filter": {
                "conditions": [
                    {
                        "field": "base_info.departments.department_id",
                        "operator": "eq",
                        "value": _quoted_filter_value(department_id),
                    },
                    {
                        "field": "work_info.staff_status",
                        "operator": "eq",
                        "value": "1",
                    },
                ]
            },
            "required_fields": list(self.config.employee_required_fields),
        }
        items: list[FeishuEmployee] = []
        for response in self._post_paged(
            f"{self.config.api_base_url}/open-apis/directory/v1/employees/filter",
            payload_base,
            self.config.employee_page_size,
        ):
            raw_items = _response_items(response, "employees", "employee_infos")
            parsed = [FeishuEmployee.from_payload(item, source_department_id=department_id) for item in raw_items]
            if raw_items and not any(item.stable_id for item in parsed):
                sample_keys = ",".join(raw_items[0].keys())
                raise RuntimeError(
                    "Feishu employee response did not include employee_id/open_id/user_id. "
                    "Check Directory employee identity field permissions. "
                    f"sample_keys={sample_keys}"
                )
            items.extend(parsed)
            _log_field_errors(response, "feishu_employee_filter")
        return items

    def fetch_active_employees_for_departments(self, department_ids: Iterable[str]) -> list[FeishuEmployee]:
        employees: list[FeishuEmployee] = []
        for department_id in department_ids:
            if not department_id:
                continue
            employees.extend(self.fetch_active_employees(department_id))
        return employees

    def mget_departments(self, department_ids: Iterable[str]) -> list[FeishuDepartment]:
        departments: list[FeishuDepartment] = []
        token = self._tenant_token()
        for chunk in _batched([item for item in department_ids if item], 100):
            response = self._post_json(
                f"{self.config.api_base_url}/open-apis/directory/v1/departments/mget",
                {"department_ids": chunk, "required_fields": list(self.config.department_required_fields)},
                {"Authorization": f"Bearer {token}"},
            )
            _ensure_ok(response)
            departments.extend(FeishuDepartment.from_payload(item) for item in _response_items(response, "departments", "department_infos"))
        return departments

    def mget_employees(self, employee_ids: Iterable[str]) -> list[FeishuEmployee]:
        employees: list[FeishuEmployee] = []
        token = self._tenant_token()
        for chunk in _batched([item for item in employee_ids if item], 100):
            response = self._post_json(
                f"{self.config.api_base_url}/open-apis/directory/v1/employees/mget",
                {"employee_ids": chunk, "required_fields": list(self.config.employee_required_fields)},
                {"Authorization": f"Bearer {token}"},
            )
            _ensure_ok(response)
            employees.extend(FeishuEmployee.from_payload(item) for item in _response_items(response, "employees", "employee_infos"))
        return employees

    def _post_paged(self, url: str, payload_base: dict[str, Any], page_size: int) -> list[dict[str, Any]]:
        if not self.config.ready:
            raise RuntimeError("Feishu directory sync is disabled or missing app credentials.")
        token = self._tenant_token()
        page_token = ""
        responses: list[dict[str, Any]] = []
        while True:
            payload = {
                **payload_base,
                "page_request": {"page_size": page_size, "page_token": page_token},
            }
            response = self._post_json(url, payload, {"Authorization": f"Bearer {token}"})
            _ensure_ok(response)
            responses.append(response)
            page_token = _next_page_token(response)
            if not page_token:
                return responses

    def _tenant_token(self) -> str:
        now = time.time()
        if self._tenant_access_token and now < self._token_expires_at:
            return self._tenant_access_token
        response = self._post_json(
            f"{self.config.api_base_url}/open-apis/auth/v3/tenant_access_token/internal",
            {"app_id": self.config.app_id, "app_secret": self.config.app_secret},
            {},
        )
        _ensure_ok(response)
        token = str(response.get("tenant_access_token") or "")
        if not token:
            raise RuntimeError("Feishu tenant_access_token is empty.")
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
class FeishuDirectorySyncService:
    client: FeishuDirectoryClient = field(default_factory=FeishuDirectoryClient)
    repository: CompanyDirectoryRepository = field(default_factory=JsonlCompanyDirectoryRepository)

    def sync(self, batch_id: str | None = None) -> FeishuDirectorySyncResult:
        started_at = _now()
        resolved_batch_id = batch_id or _batch_id(started_at)
        errors: list[str] = []
        departments: list[FeishuDepartment] = []
        employees: list[FeishuEmployee] = []
        employee_departments: list[FeishuEmployeeDepartment] = []
        inactive_count = 0
        try:
            departments = self.client.fetch_department_tree()
            department_ids = [department.department_id for department in departments if department.department_id]
            employees = _dedupe_employees(self.client.fetch_active_employees_for_departments(department_ids))
            employee_departments = _employee_department_relations(employees)
            inactive_count = self.repository.save_snapshot(
                departments,
                employees,
                employee_departments,
                batch_id=resolved_batch_id,
                synced_at=_now(),
            )
        except Exception as exc:
            logger.exception("feishu directory sync failed", extra=log_extra("feishu_directory_sync_failed", request_id=resolved_batch_id))
            errors.append(f"{type(exc).__name__}: {exc}")

        result = FeishuDirectorySyncResult(
            batch_id=resolved_batch_id,
            started_at=started_at,
            finished_at=_now(),
            department_count=len(departments),
            employee_count=len(employees),
            employee_department_count=len(employee_departments),
            inactive_employee_count=inactive_count,
            errors=errors,
        )
        recorder = getattr(self.repository, "record_sync_run", None)
        if callable(recorder):
            recorder(result)
        logger.info(
            "feishu directory sync completed",
            extra=log_extra(
                "feishu_directory_sync_completed",
                request_id=resolved_batch_id,
                department_count=result.department_count,
                employee_count=result.employee_count,
                employee_department_count=result.employee_department_count,
                inactive_employee_count=result.inactive_employee_count,
                ok=result.ok,
            ),
        )
        return result


def _dedupe_employees(employees: list[FeishuEmployee]) -> list[FeishuEmployee]:
    deduped: dict[str, FeishuEmployee] = {}
    for employee in employees:
        key = employee.stable_id
        if not key:
            continue
        if key not in deduped:
            deduped[key] = employee
            continue
        existing = deduped[key]
        deduped[key] = replace(
            employee,
            departments=_merge_dict_lists(existing.departments, employee.departments, _department_id),
            department_path_infos=_merge_dict_lists(existing.department_path_infos, employee.department_path_infos, _path_info_id),
            positions=_merge_dict_lists(existing.positions, employee.positions, _position_key),
            source_department_id=existing.source_department_id or employee.source_department_id,
        )
    return list(deduped.values())


def _employee_department_relations(employees: list[FeishuEmployee]) -> list[FeishuEmployeeDepartment]:
    relations: dict[tuple[str, str], FeishuEmployeeDepartment] = {}
    for employee in employees:
        employee_key = employee.stable_id
        departments = employee.departments or ([{"department_id": employee.source_department_id}] if employee.source_department_id else [])
        for department in departments:
            department_id = _department_id(department)
            if not employee_key or not department_id:
                continue
            relation = FeishuEmployeeDepartment(
                employee_id=employee.employee_id,
                open_id=employee.open_id,
                department_id=department_id,
                department_name=_text_value(department.get("name") or department.get("department_name")),
                is_primary=department_id == employee.primary_department_id or _bool_value(department.get("is_primary")),
                department_path_infos=_relation_path_infos(employee, department_id),
                positions=_positions_for_department(employee.positions, department_id),
                source_department_id=employee.source_department_id,
            )
            relations[(employee_key, department_id)] = relation
    return list(relations.values())


def _relation_path_infos(employee: FeishuEmployee, department_id: str) -> list[dict[str, Any]]:
    paths = []
    for path in employee.department_path_infos:
        if not isinstance(path, dict):
            continue
        if str(path.get("department_id") or path.get("id") or "") == department_id:
            paths.append(path)
    return paths or employee.department_path_infos


def _positions_for_department(positions: list[dict[str, Any]], department_id: str) -> list[dict[str, Any]]:
    matched = []
    for position in positions:
        position_department_id = str(
            position.get("department_id")
            or position.get("dept_id")
            or _field(position, "department.department_id")
            or _field(position, "department.id")
            or ""
        )
        if not position_department_id or position_department_id == department_id:
            matched.append(position)
    return matched


def _department_row(department: FeishuDepartment, batch_id: str, synced_at: str) -> dict[str, Any]:
    return {
        "batch_id": batch_id,
        "synced_at": synced_at,
        "feishu_department_id": department.department_id,
        "parent_feishu_department_id": department.parent_department_id,
        "name": department.name,
        "department_path_infos": department.department_path_infos,
        "depth": department.depth,
        "enabled_status": department.enabled_status,
        "leaders": department.leaders,
        "has_child": department.has_child,
        "order_weight": department.order_weight,
        "raw": department.raw,
    }


def _employee_row(employee: FeishuEmployee, batch_id: str, synced_at: str, sync_status: str) -> dict[str, Any]:
    return {
        "batch_id": batch_id,
        "synced_at": synced_at,
        "sync_status": sync_status,
        "feishu_employee_id": employee.employee_id,
        "feishu_open_id": employee.open_id,
        "feishu_user_id": employee.user_id,
        "job_number": employee.job_number,
        "name": employee.name,
        "mobile": employee.mobile,
        "email": employee.email,
        "enterprise_email": employee.enterprise_email,
        "gender": employee.gender,
        "avatar": employee.avatar,
        "leader_id": employee.leader_id,
        "staff_status": employee.staff_status,
        "active_status": employee.active_status,
        "is_resigned": employee.is_resigned,
        "job_title_id": employee.job_title_id,
        "job_title_name": employee.job_title_name,
        "main_department_id": employee.primary_department_id,
        "department_path_infos": employee.department_path_infos,
        "join_date": employee.join_date,
        "raw": employee.raw,
    }


def _employee_department_row(relation: FeishuEmployeeDepartment, batch_id: str, synced_at: str) -> dict[str, Any]:
    return {
        "batch_id": batch_id,
        "synced_at": synced_at,
        "feishu_employee_id": relation.employee_id,
        "feishu_open_id": relation.open_id,
        "feishu_department_id": relation.department_id,
        "department_name": relation.department_name,
        "is_primary": relation.is_primary,
        "department_path_infos": relation.department_path_infos,
        "positions": relation.positions,
        "source_department_id": relation.source_department_id,
    }


def _employee_row_key(row: dict[str, Any]) -> str:
    return str(row.get("feishu_employee_id") or row.get("feishu_open_id") or row.get("feishu_user_id") or "")


def _employee_row_inactive(row: dict[str, Any]) -> bool:
    if row.get("is_resigned") is True:
        return True
    status = str(row.get("sync_status") or row.get("staff_status") or row.get("active_status") or "").lower()
    return status in {"inactive", "resigned", "inactive_missing_from_sync", "offboarded"}


def _field(payload: dict[str, Any], path: str) -> Any:
    if path in payload:
        return payload[path]
    value: Any = payload
    for part in path.split("."):
        if not isinstance(value, dict):
            return None
        value = value.get(part)
    return value


def _text_value(value: Any) -> str:
    if value is None:
        return ""
    if isinstance(value, str):
        return value
    if isinstance(value, dict):
        nested_name = value.get("name")
        if isinstance(nested_name, dict):
            return _text_value(nested_name)
        if isinstance(nested_name, str):
            return nested_name
        default_value = value.get("default_value")
        if default_value:
            return str(default_value)
        i18n_value = value.get("i18n_value")
        if isinstance(i18n_value, dict):
            for key in ("zh_cn", "en_us", "ja_jp"):
                if i18n_value.get(key):
                    return str(i18n_value[key])
        for key in ("text", "value"):
            if value.get(key):
                return str(value[key])
    return str(value)


def _list_of_dicts(value: Any) -> list[dict[str, Any]]:
    if isinstance(value, dict):
        return [value]
    if not isinstance(value, list):
        return []
    return [dict(item) for item in value if isinstance(item, dict)]


def _department_id(department: dict[str, Any]) -> str:
    return str(department.get("department_id") or department.get("id") or department.get("open_department_id") or "")


def _path_info_id(path_info: dict[str, Any]) -> str:
    return str(path_info.get("department_id") or path_info.get("id") or json.dumps(path_info, ensure_ascii=False, sort_keys=True))


def _position_key(position: dict[str, Any]) -> str:
    return str(
        position.get("position_id")
        or position.get("id")
        or f"{position.get('department_id')}-{position.get('name')}"
        or json.dumps(position, ensure_ascii=False, sort_keys=True)
    )


def _merge_dict_lists(left: list[dict[str, Any]], right: list[dict[str, Any]], key_fn: Callable[[dict[str, Any]], str]) -> list[dict[str, Any]]:
    merged: dict[str, dict[str, Any]] = {}
    for item in [*left, *right]:
        key = key_fn(item)
        if key:
            merged[key] = item
    return list(merged.values())


def _response_items(response: dict[str, Any], *preferred_names: str) -> list[dict[str, Any]]:
    data = response.get("data") if isinstance(response.get("data"), dict) else {}
    containers = [data, response]
    names = [*preferred_names, "items", "list", "records"]
    for container in containers:
        for name in names:
            value = container.get(name)
            if isinstance(value, list):
                return [dict(item) for item in value if isinstance(item, dict)]
    for container in containers:
        for value in container.values():
            if isinstance(value, list) and all(isinstance(item, dict) for item in value):
                return [dict(item) for item in value]
    return []


def _next_page_token(response: dict[str, Any]) -> str:
    data = response.get("data") if isinstance(response.get("data"), dict) else {}
    page_response = data.get("page_response") if isinstance(data.get("page_response"), dict) else {}
    has_more = _bool_value(page_response.get("has_more") if page_response else data.get("has_more"))
    token = str(
        page_response.get("page_token")
        or page_response.get("next_page_token")
        or data.get("page_token")
        or data.get("next_page_token")
        or ""
    )
    return token if has_more and token else ""


def _ensure_ok(response: dict[str, Any]) -> None:
    code = response.get("code", 0)
    try:
        numeric_code = int(code)
    except (TypeError, ValueError):
        numeric_code = -1
    if numeric_code != 0:
        raise RuntimeError(str(response.get("msg") or response.get("message") or f"Feishu directory API failed: {code}"))


def _log_field_errors(response: dict[str, Any], event: str) -> None:
    data = response.get("data") if isinstance(response.get("data"), dict) else {}
    abnormals = data.get("abnormals") if isinstance(data.get("abnormals"), dict) else response.get("abnormals")
    field_errors = abnormals.get("field_errors") if isinstance(abnormals, dict) else None
    if field_errors:
        logger.warning("feishu directory field errors", extra=log_extra(event, field_errors=field_errors))


def _quoted_filter_value(value: str) -> str:
    return json.dumps(str(value), ensure_ascii=False)


def _bool_value(value: Any) -> bool:
    if isinstance(value, bool):
        return value
    if isinstance(value, (int, float)):
        return value != 0
    if isinstance(value, str):
        return value.strip().lower() in {"1", "true", "yes", "on", "enabled"}
    return False


def _batched(values: list[str], size: int) -> Iterable[list[str]]:
    for index in range(0, len(values), size):
        yield values[index : index + size]


def _batch_id(started_at: str) -> str:
    stamp = started_at.replace("-", "").replace(":", "").replace("+", "").replace(".", "")[:15]
    return f"feishu-directory-{stamp}-{uuid.uuid4().hex[:8]}"


def _now() -> str:
    return datetime.now(timezone.utc).isoformat()


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
    if value is None:
        return default
    items = tuple(item.strip() for item in value.split(",") if item.strip())
    return items or default
