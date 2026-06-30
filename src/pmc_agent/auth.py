from __future__ import annotations

from dataclasses import dataclass, field
import base64
import hashlib
import hmac
import json
import os
from pathlib import Path
import secrets
import time
import urllib.error
import urllib.parse
import urllib.request
from typing import Any, Callable

from pmc_agent.app_logging import get_logger, log_extra
from pmc_agent.env import load_env_file


logger = get_logger(__name__)


AuthTransport = Callable[[str, dict[str, Any] | None, dict[str, str], str], dict[str, Any]]

CONTROL_TOWER_FILTER_ALIASES = {
    "sales_department": "sales_apartment",
    "sales_apartment": "sales_apartment",
    "salesman": "salesman",
    "sales_person": "salesman",
    "product_manager": "product_manager",
    "country_code": "country_code",
    "shipments_country": "shipments_country",
    "store_name": "store_name",
    "seller_id": "seller_id",
}


@dataclass(frozen=True)
class FeishuAuthConfig:
    enabled: bool = False
    required: bool = False
    app_id: str = ""
    app_secret: str = ""
    api_base_url: str = "https://open.feishu.cn"
    redirect_uri: str = ""
    frontend_url: str = "http://127.0.0.1:5173"
    session_secret: str = ""
    session_cookie_name: str = "pmc_session"
    session_ttl_seconds: int = 8 * 60 * 60
    state_ttl_seconds: int = 10 * 60
    cookie_secure: bool = False
    permission_rules_path: str = "config/feishu_permissions.json"
    admin_open_ids: tuple[str, ...] = ()
    admin_user_ids: tuple[str, ...] = ()
    default_person_scope_field: str = "salesman"

    @classmethod
    def from_env(cls) -> "FeishuAuthConfig":
        load_env_file(override=False)
        app_secret = os.getenv("FEISHU_APP_SECRET", "")
        return cls(
            enabled=_env_bool("FEISHU_LOGIN_ENABLED", _env_bool("FEISHU_AUTH_ENABLED", False)),
            required=_env_bool("PMC_AUTH_REQUIRED", False),
            app_id=os.getenv("FEISHU_APP_ID", ""),
            app_secret=app_secret,
            api_base_url=os.getenv("FEISHU_API_BASE_URL", "https://open.feishu.cn").rstrip("/"),
            redirect_uri=os.getenv("FEISHU_AUTH_REDIRECT_URI", ""),
            frontend_url=os.getenv("FRONTEND_URL", "http://127.0.0.1:5173").rstrip("/"),
            session_secret=os.getenv("PMC_SESSION_SECRET", "") or app_secret or "pmc-local-dev-session-secret",
            session_cookie_name=os.getenv("PMC_SESSION_COOKIE_NAME", "pmc_session"),
            session_ttl_seconds=_env_int("PMC_SESSION_TTL_SECONDS", 8 * 60 * 60, minimum=300, maximum=30 * 24 * 60 * 60),
            state_ttl_seconds=_env_int("PMC_AUTH_STATE_TTL_SECONDS", 10 * 60, minimum=60, maximum=60 * 60),
            cookie_secure=_env_bool("PMC_SESSION_COOKIE_SECURE", False),
            permission_rules_path=os.getenv("PMC_PERMISSION_RULES_PATH", "config/feishu_permissions.json"),
            admin_open_ids=_env_csv("PMC_AUTH_ADMIN_OPEN_IDS", ()),
            admin_user_ids=_env_csv("PMC_AUTH_ADMIN_USER_IDS", ()),
            default_person_scope_field=os.getenv("PMC_AUTH_DEFAULT_PERSON_SCOPE_FIELD", "salesman"),
        )

    @property
    def ready(self) -> bool:
        return self.enabled and bool(self.app_id and self.app_secret and self.redirect_uri)


@dataclass(frozen=True)
class AuthenticatedUser:
    open_id: str
    user_id: str = ""
    union_id: str = ""
    name: str = ""
    en_name: str = ""
    email: str = ""
    enterprise_email: str = ""
    mobile: str = ""
    avatar_url: str = ""
    employee_id: str = ""
    department_ids: tuple[str, ...] = ()
    department_names: tuple[str, ...] = ()
    tenant_key: str = ""
    raw: dict[str, Any] = field(default_factory=dict)

    @classmethod
    def anonymous(cls) -> "AuthenticatedUser":
        return cls(open_id="anonymous", name="本地开发用户")

    @classmethod
    def from_feishu_payload(cls, payload: dict[str, Any]) -> "AuthenticatedUser":
        data = payload.get("data") if isinstance(payload.get("data"), dict) else payload
        return cls(
            open_id=str(data.get("open_id") or ""),
            user_id=str(data.get("user_id") or ""),
            union_id=str(data.get("union_id") or ""),
            name=str(data.get("name") or data.get("cn_name") or ""),
            en_name=str(data.get("en_name") or ""),
            email=str(data.get("email") or ""),
            enterprise_email=str(data.get("enterprise_email") or ""),
            mobile=str(data.get("mobile") or ""),
            avatar_url=str(data.get("avatar_url") or data.get("avatar_thumb") or ""),
            employee_id=str(data.get("employee_id") or ""),
            department_ids=tuple(_string_list(data.get("department_ids") or data.get("department_ids_v2"))),
            department_names=tuple(_string_list(data.get("department_names") or data.get("departments"))),
            tenant_key=str(data.get("tenant_key") or ""),
            raw=dict(data),
        )

    def to_public_dict(self) -> dict[str, Any]:
        return {
            "open_id": self.open_id,
            "user_id": self.user_id,
            "union_id": self.union_id,
            "name": self.name,
            "en_name": self.en_name,
            "email": self.email,
            "enterprise_email": self.enterprise_email,
            "mobile": self.mobile,
            "avatar_url": self.avatar_url,
            "employee_id": self.employee_id,
            "department_ids": list(self.department_ids),
            "department_names": list(self.department_names),
            "tenant_key": self.tenant_key,
        }


@dataclass(frozen=True)
class UserPermissions:
    role: str = "viewer"
    features: tuple[str, ...] = ()
    data_scope: dict[str, tuple[str, ...]] = field(default_factory=dict)
    all_data: bool = False
    source_rule: str = ""

    @classmethod
    def anonymous_full_access(cls) -> "UserPermissions":
        return cls(role="local_dev", features=("*",), all_data=True, source_rule="auth_not_required")

    @classmethod
    def admin(cls, source_rule: str = "admin") -> "UserPermissions":
        return cls(role="admin", features=("*",), all_data=True, source_rule=source_rule)

    def allows_feature(self, feature: str) -> bool:
        return "*" in self.features or feature in self.features

    def to_public_dict(self) -> dict[str, Any]:
        return {
            "role": self.role,
            "features": list(self.features),
            "data_scope": {key: list(value) for key, value in self.data_scope.items()},
            "all_data": self.all_data,
            "source_rule": self.source_rule,
        }


@dataclass(frozen=True)
class AuthContext:
    user: AuthenticatedUser
    permissions: UserPermissions
    authenticated: bool = True

    @classmethod
    def anonymous_full_access(cls) -> "AuthContext":
        return cls(AuthenticatedUser.anonymous(), UserPermissions.anonymous_full_access(), authenticated=False)

    def to_public_dict(self, *, auth_required: bool) -> dict[str, Any]:
        return {
            "authenticated": self.authenticated,
            "auth_required": auth_required,
            "user": self.user.to_public_dict(),
            "permissions": self.permissions.to_public_dict(),
        }


@dataclass
class SignedPayloadCodec:
    secret: str

    def encode(self, payload: dict[str, Any], ttl_seconds: int) -> str:
        now = int(time.time())
        body = {**payload, "iat": now, "exp": now + ttl_seconds}
        raw = _b64url(json.dumps(body, ensure_ascii=False, separators=(",", ":")).encode("utf-8"))
        signature = _b64url(hmac.new(self.secret.encode("utf-8"), raw.encode("ascii"), hashlib.sha256).digest())
        return f"{raw}.{signature}"

    def decode(self, token: str) -> dict[str, Any]:
        raw, signature = token.split(".", 1)
        expected = _b64url(hmac.new(self.secret.encode("utf-8"), raw.encode("ascii"), hashlib.sha256).digest())
        if not hmac.compare_digest(signature, expected):
            raise ValueError("invalid token signature")
        payload = json.loads(_b64url_decode(raw).decode("utf-8"))
        if int(payload.get("exp") or 0) < int(time.time()):
            raise ValueError("token expired")
        return payload


@dataclass
class FeishuOAuthClient:
    config: FeishuAuthConfig = field(default_factory=FeishuAuthConfig.from_env)
    transport: AuthTransport | None = None
    token_ttl_buffer_seconds: int = 120
    _app_access_token: str = field(default="", init=False)
    _app_token_expires_at: float = field(default=0, init=False)
    _tenant_access_token: str = field(default="", init=False)
    _tenant_token_expires_at: float = field(default=0, init=False)

    def authorize_url(self, state: str, redirect_uri: str | None = None) -> str:
        params = {
            "app_id": self.config.app_id,
            "redirect_uri": redirect_uri or self.config.redirect_uri,
            "state": state,
        }
        return f"{self.config.api_base_url}/open-apis/authen/v1/authorize?{urllib.parse.urlencode(params)}"

    def authenticate_code(self, code: str) -> AuthenticatedUser:
        token_data = self.exchange_code(code)
        user_access_token = str(token_data.get("access_token") or token_data.get("user_access_token") or "")
        if not user_access_token:
            raise RuntimeError("飞书 user_access_token 为空")
        user_info = self.get_user_info(user_access_token)
        data = user_info.get("data") if isinstance(user_info.get("data"), dict) else {}
        merged = {**token_data, **data}
        try:
            contact_user = self.get_contact_user(
                user_id=str(merged.get("user_id") or ""),
                open_id=str(merged.get("open_id") or ""),
            )
            merged = {**merged, **contact_user}
        except Exception as exc:
            logger.info("feishu contact user enrichment skipped", extra=log_extra("feishu_contact_user_enrichment_skipped", error=str(exc)))
        return AuthenticatedUser.from_feishu_payload(merged)

    def exchange_code(self, code: str) -> dict[str, Any]:
        response = self._request_json(
            f"{self.config.api_base_url}/open-apis/authen/v1/access_token",
            {"grant_type": "authorization_code", "code": code},
            {"Authorization": f"Bearer {self._app_token()}"},
            "POST",
        )
        _ensure_ok(response)
        return dict(response.get("data") or response)

    def get_user_info(self, user_access_token: str) -> dict[str, Any]:
        response = self._request_json(
            f"{self.config.api_base_url}/open-apis/authen/v1/user_info",
            None,
            {"Authorization": f"Bearer {user_access_token}"},
            "GET",
        )
        _ensure_ok(response)
        return response

    def get_contact_user(self, *, user_id: str = "", open_id: str = "") -> dict[str, Any]:
        identity = user_id or open_id
        if not identity:
            return {}
        user_id_type = "user_id" if user_id else "open_id"
        query = urllib.parse.urlencode({"user_id_type": user_id_type, "department_id_type": "open_department_id"})
        response = self._request_json(
            f"{self.config.api_base_url}/open-apis/contact/v3/users/{urllib.parse.quote(identity)}?{query}",
            None,
            {"Authorization": f"Bearer {self._tenant_token()}"},
            "GET",
        )
        _ensure_ok(response)
        data = response.get("data") if isinstance(response.get("data"), dict) else {}
        user = data.get("user") if isinstance(data.get("user"), dict) else data
        return dict(user)

    def _app_token(self) -> str:
        now = time.time()
        if self._app_access_token and now < self._app_token_expires_at:
            return self._app_access_token
        response = self._request_json(
            f"{self.config.api_base_url}/open-apis/auth/v3/app_access_token/internal",
            {"app_id": self.config.app_id, "app_secret": self.config.app_secret},
            {},
            "POST",
        )
        _ensure_ok(response)
        token = str(response.get("app_access_token") or "")
        if not token:
            raise RuntimeError("飞书 app_access_token 为空")
        expire = int(response.get("expire") or 7200)
        self._app_access_token = token
        self._app_token_expires_at = now + max(60, expire - self.token_ttl_buffer_seconds)
        return token

    def _tenant_token(self) -> str:
        now = time.time()
        if self._tenant_access_token and now < self._tenant_token_expires_at:
            return self._tenant_access_token
        response = self._request_json(
            f"{self.config.api_base_url}/open-apis/auth/v3/tenant_access_token/internal",
            {"app_id": self.config.app_id, "app_secret": self.config.app_secret},
            {},
            "POST",
        )
        _ensure_ok(response)
        token = str(response.get("tenant_access_token") or "")
        if not token:
            raise RuntimeError("飞书 tenant_access_token 为空")
        expire = int(response.get("expire") or 7200)
        self._tenant_access_token = token
        self._tenant_token_expires_at = now + max(60, expire - self.token_ttl_buffer_seconds)
        return token

    def _request_json(self, url: str, payload: dict[str, Any] | None, headers: dict[str, str], method: str) -> dict[str, Any]:
        if self.transport:
            return self.transport(url, payload, headers, method)
        data = None if payload is None else json.dumps(payload, ensure_ascii=False).encode("utf-8")
        request = urllib.request.Request(
            url,
            data=data,
            headers={"Content-Type": "application/json; charset=utf-8", **headers},
            method=method,
        )
        try:
            with urllib.request.urlopen(request, timeout=30) as response:
                return json.loads(response.read().decode("utf-8"))
        except urllib.error.HTTPError as exc:
            error_body = exc.read().decode("utf-8", errors="replace")
            raise RuntimeError(f"HTTPError {exc.code}: {error_body[:1000]}") from exc


@dataclass
class PermissionRuleEngine:
    config: FeishuAuthConfig = field(default_factory=FeishuAuthConfig.from_env)
    rules: dict[str, Any] = field(default_factory=dict)

    @classmethod
    def from_config(cls, config: FeishuAuthConfig) -> "PermissionRuleEngine":
        return cls(config=config, rules=_load_rules(config.permission_rules_path))

    def permissions_for(self, user: AuthenticatedUser) -> UserPermissions:
        if user.open_id and user.open_id in self.config.admin_open_ids:
            return UserPermissions.admin("env_admin_open_id")
        if user.user_id and user.user_id in self.config.admin_user_ids:
            return UserPermissions.admin("env_admin_user_id")

        admin_open_ids = set(_string_list(self.rules.get("admin_open_ids")))
        admin_user_ids = set(_string_list(self.rules.get("admin_user_ids")))
        if user.open_id and user.open_id in admin_open_ids:
            return UserPermissions.admin("rules_admin_open_id")
        if user.user_id and user.user_id in admin_user_ids:
            return UserPermissions.admin("rules_admin_user_id")

        for rule in self.rules.get("rules") or []:
            if not isinstance(rule, dict) or not self._matches_rule(user, rule):
                continue
            return self._permissions_from_rule(rule, user)

        default_policy = self.rules.get("default_policy") if isinstance(self.rules.get("default_policy"), dict) else {}
        if default_policy:
            return self._permissions_from_rule(default_policy, user, source="default_policy")
        return UserPermissions(
            role="member",
            features=("overview", "detail", "warehouse", "standards", "sku_diagnosis", "logistics_detail", "agent_chat"),
            data_scope={self.config.default_person_scope_field: _expand_scope_values(("$user.name",), user)},
            source_rule="built_in_default",
        )

    def _matches_rule(self, user: AuthenticatedUser, rule: dict[str, Any]) -> bool:
        match = rule.get("match") if isinstance(rule.get("match"), dict) else rule
        checks = [
            (user.open_id, _string_list(match.get("open_ids"))),
            (user.user_id, _string_list(match.get("user_ids"))),
            (user.union_id, _string_list(match.get("union_ids"))),
            (user.employee_id, _string_list(match.get("employee_ids"))),
            (user.email, _string_list(match.get("emails"))),
            (user.enterprise_email, _string_list(match.get("emails"))),
        ]
        if any(value and value in allowed for value, allowed in checks if allowed):
            return True
        department_ids = set(user.department_ids)
        if department_ids and department_ids.intersection(_string_list(match.get("department_ids"))):
            return True
        department_names = set(user.department_names)
        if department_names and department_names.intersection(_string_list(match.get("department_names"))):
            return True
        email_domains = _string_list(match.get("email_domains"))
        if email_domains:
            emails = [user.email, user.enterprise_email]
            if any(email and any(email.endswith(f"@{domain.lstrip('@')}") for domain in email_domains) for email in emails):
                return True
        return False

    def _permissions_from_rule(self, rule: dict[str, Any], user: AuthenticatedUser, source: str | None = None) -> UserPermissions:
        features = tuple(_string_list(rule.get("features") or self.rules.get("default_features")))
        if not features:
            features = ("overview", "detail")
        raw_scope = rule.get("data_scope") if isinstance(rule.get("data_scope"), dict) else {}
        data_scope: dict[str, tuple[str, ...]] = {}
        all_data = bool(rule.get("all_data")) or "*" in _string_list(raw_scope.get("*"))
        for key, value in raw_scope.items():
            if key == "*":
                continue
            values = _expand_scope_values(_string_list(value), user)
            if "*" in values:
                all_data = True
                continue
            if values:
                data_scope[key] = values
        return UserPermissions(
            role=str(rule.get("role") or "member"),
            features=features,
            data_scope=data_scope,
            all_data=all_data,
            source_rule=source or str(rule.get("id") or rule.get("role") or "matched_rule"),
        )


@dataclass
class FeishuAuthService:
    config: FeishuAuthConfig = field(default_factory=FeishuAuthConfig.from_env)
    oauth_client: FeishuOAuthClient | None = None
    permission_engine: PermissionRuleEngine | None = None
    codec: SignedPayloadCodec | None = None

    def __post_init__(self) -> None:
        if self.oauth_client is None:
            self.oauth_client = FeishuOAuthClient(self.config)
        if self.permission_engine is None:
            self.permission_engine = PermissionRuleEngine.from_config(self.config)
        if self.codec is None:
            self.codec = SignedPayloadCodec(self.config.session_secret)

    def login_url(self, next_url: str = "") -> str:
        if not self.config.ready:
            raise RuntimeError("飞书登录未启用或缺少 FEISHU_APP_ID / FEISHU_APP_SECRET")
        state = self.codec.encode({"nonce": secrets.token_urlsafe(16), "next": self._safe_next_url(next_url)}, self.config.state_ttl_seconds)
        return self.oauth_client.authorize_url(state=state)

    def authenticate_callback(self, code: str, state: str) -> tuple[AuthContext, str, str]:
        if not code:
            raise ValueError("缺少飞书授权 code")
        state_payload = self.codec.decode(state)
        user = self.oauth_client.authenticate_code(code)
        permissions = self.permission_engine.permissions_for(user)
        context = AuthContext(user=user, permissions=permissions, authenticated=True)
        session_token = self.codec.encode(
            {
                "user": user.to_public_dict(),
                "permissions": permissions.to_public_dict(),
            },
            self.config.session_ttl_seconds,
        )
        return context, session_token, self._safe_next_url(str(state_payload.get("next") or ""))

    def context_from_session(self, token: str | None) -> AuthContext | None:
        if not token:
            return None
        try:
            payload = self.codec.decode(token)
        except Exception as exc:
            logger.warning("invalid auth session", extra=log_extra("auth_session_invalid", error=str(exc)))
            return None
        user_payload = payload.get("user") if isinstance(payload.get("user"), dict) else {}
        permission_payload = payload.get("permissions") if isinstance(payload.get("permissions"), dict) else {}
        user = AuthenticatedUser.from_feishu_payload(user_payload)
        permissions = UserPermissions(
            role=str(permission_payload.get("role") or "viewer"),
            features=tuple(_string_list(permission_payload.get("features"))),
            data_scope={key: tuple(_string_list(value)) for key, value in dict(permission_payload.get("data_scope") or {}).items()},
            all_data=bool(permission_payload.get("all_data")),
            source_rule=str(permission_payload.get("source_rule") or "session"),
        )
        return AuthContext(user=user, permissions=permissions, authenticated=True)

    def _safe_next_url(self, next_url: str) -> str:
        if not next_url:
            return self.config.frontend_url
        parsed = urllib.parse.urlparse(next_url)
        frontend = urllib.parse.urlparse(self.config.frontend_url)
        if parsed.scheme in {"http", "https"} and parsed.netloc == frontend.netloc:
            return next_url
        if next_url.startswith("/"):
            return f"{self.config.frontend_url}{next_url}"
        return self.config.frontend_url


def apply_permission_filters(filters: dict[str, Any], permissions: UserPermissions) -> dict[str, Any]:
    if permissions.all_data:
        return dict(filters)
    scoped_filters = dict(filters)
    if not permissions.data_scope:
        scoped_filters["sales_apartment"] = ["__permission_no_data__"]
        return scoped_filters
    for raw_field, allowed_values in permissions.data_scope.items():
        filter_field = CONTROL_TOWER_FILTER_ALIASES.get(raw_field, raw_field)
        allowed = _scope_values_set(allowed_values)
        if not allowed:
            scoped_filters["sales_apartment"] = ["__permission_no_data__"]
            continue
        current = scoped_filters.get(filter_field)
        if _query_value_present(current):
            requested = _scope_values_set(_string_list(current))
            intersection = sorted(requested.intersection(allowed))
            scoped_filters[filter_field] = intersection or ["__permission_no_data__"]
        else:
            scoped_filters[filter_field] = sorted(allowed)
    return scoped_filters


def item_allowed(item: dict[str, Any], permissions: UserPermissions) -> bool:
    if permissions.all_data:
        return True
    if not permissions.data_scope:
        return False
    for raw_field, allowed_values in permissions.data_scope.items():
        allowed = _scope_values_set(allowed_values)
        candidates = [
            item.get(raw_field),
            item.get(CONTROL_TOWER_FILTER_ALIASES.get(raw_field, raw_field)),
        ]
        if allowed and any(str(candidate) in allowed for candidate in candidates if candidate not in {None, ""}):
            return True
    return False


def _load_rules(path: str) -> dict[str, Any]:
    if not path:
        return {}
    rule_path = Path(path)
    if not rule_path.exists():
        return {}
    try:
        return json.loads(rule_path.read_text(encoding="utf-8"))
    except Exception as exc:
        logger.warning("permission rules load failed", extra=log_extra("permission_rules_load_failed", path=str(rule_path), error=str(exc)))
        return {}


def _expand_scope_values(values: tuple[str, ...], user: AuthenticatedUser) -> tuple[str, ...]:
    expanded: list[str] = []
    placeholders = {
        "$user.name": user.name,
        "$user.open_id": user.open_id,
        "$user.user_id": user.user_id,
        "$user.employee_id": user.employee_id,
        "$user.email": user.email,
        "$user.enterprise_email": user.enterprise_email,
    }
    for value in values:
        if value in placeholders:
            if placeholders[value]:
                expanded.append(placeholders[value])
        else:
            expanded.append(value)
    return tuple(dict.fromkeys(item for item in expanded if item))


def _scope_values_set(values: tuple[str, ...] | list[str] | set[str]) -> set[str]:
    return {str(item) for item in values if item not in {None, ""}}


def _ensure_ok(response: dict[str, Any]) -> None:
    code = response.get("code", 0)
    if code not in {0, "0", None}:
        raise RuntimeError(str(response.get("msg") or response.get("error_description") or "飞书接口调用失败"))


def _query_value_present(value: Any) -> bool:
    if isinstance(value, (list, tuple, set)):
        return any(item not in {None, ""} for item in value)
    return value not in {None, ""}


def _string_list(value: Any) -> tuple[str, ...]:
    if value is None:
        return ()
    if isinstance(value, str):
        return tuple(item.strip() for item in value.replace("，", ",").split(",") if item.strip())
    if isinstance(value, (list, tuple, set)):
        return tuple(str(item).strip() for item in value if str(item).strip())
    return (str(value).strip(),) if str(value).strip() else ()


def _env_bool(name: str, default: bool) -> bool:
    value = os.getenv(name)
    if value is None:
        return default
    return value.strip().lower() in {"1", "true", "yes", "y", "on"}


def _env_int(name: str, default: int, *, minimum: int, maximum: int) -> int:
    raw = os.getenv(name, "")
    try:
        value = int(raw)
    except (TypeError, ValueError):
        value = default
    return max(minimum, min(value, maximum))


def _env_csv(name: str, default: tuple[str, ...]) -> tuple[str, ...]:
    value = os.getenv(name)
    if value is None:
        return default
    return _string_list(value)


def _b64url(raw: bytes) -> str:
    return base64.urlsafe_b64encode(raw).decode("ascii").rstrip("=")


def _b64url_decode(value: str) -> bytes:
    padding = "=" * (-len(value) % 4)
    return base64.urlsafe_b64decode(value + padding)
