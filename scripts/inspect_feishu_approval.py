from __future__ import annotations

import argparse
import json
import os
from pathlib import Path
import sys
import urllib.error
import urllib.parse
import urllib.request


ROOT = Path(__file__).resolve().parents[1]
SRC = ROOT / "src"
if str(SRC) not in sys.path:
    sys.path.insert(0, str(SRC))

from pmc_agent.env import load_env_file


def main() -> int:
    parser = argparse.ArgumentParser(description="Inspect a Feishu native approval definition.")
    parser.add_argument("--approval-code", required=True, help="Approval definition code, also called definitionCode in Feishu admin URL.")
    args = parser.parse_args()

    load_env_file(override=False)
    app_id = os.getenv("FEISHU_APP_ID", "")
    app_secret = os.getenv("FEISHU_APP_SECRET", "")
    base_url = os.getenv("FEISHU_API_BASE_URL", "https://open.feishu.cn").rstrip("/")
    if not app_id or not app_secret:
        print("Missing FEISHU_APP_ID or FEISHU_APP_SECRET in .env.")
        return 2

    try:
        token = _tenant_token(base_url, app_id, app_secret)
        result = _get_approval(base_url, token, args.approval_code)
    except Exception as exc:
        print(f"Failed: {type(exc).__name__}: {exc}")
        return 1

    print(json.dumps(result, ensure_ascii=False, indent=2))
    if int(result.get("code", -1)) != 0:
        return 1
    data = result.get("data") or {}
    print("\nApproval:")
    print(f"- name: {data.get('approval_name', '')}")
    print(f"- code: {args.approval_code}")
    print(f"- status: {data.get('status', '')}")
    print("\nForm widgets:")
    for widget in _parse_json_field(data.get("form")):
        print(
            f"- id={widget.get('id', '')} custom_id={widget.get('custom_id', '')} "
            f"type={widget.get('type', '')} name={widget.get('name', '')}"
        )
    print("\nProcess nodes:")
    for node in data.get("node_list") or []:
        print(
            f"- node_id={node.get('node_id', '')} custom_node_id={node.get('custom_node_id', '')} "
            f"name={node.get('name', '')} need_approver={node.get('need_approver', '')} type={node.get('node_type', '')}"
        )
    return 0


def _tenant_token(base_url: str, app_id: str, app_secret: str) -> str:
    response = _post_json(
        f"{base_url}/open-apis/auth/v3/tenant_access_token/internal",
        {"app_id": app_id, "app_secret": app_secret},
        {},
    )
    if int(response.get("code", -1)) != 0:
        raise RuntimeError(response.get("msg") or response)
    token = str(response.get("tenant_access_token") or "")
    if not token:
        raise RuntimeError("tenant_access_token is empty")
    return token


def _get_approval(base_url: str, token: str, approval_code: str) -> dict:
    quoted = urllib.parse.quote(approval_code, safe="")
    query = urllib.parse.urlencode({"locale": "zh-CN", "user_id_type": "open_id"})
    return _get_json(
        f"{base_url}/open-apis/approval/v4/approvals/{quoted}?{query}",
        {"Authorization": f"Bearer {token}"},
    )


def _parse_json_field(value) -> list[dict]:
    if isinstance(value, list):
        return [item for item in value if isinstance(item, dict)]
    if not isinstance(value, str) or not value:
        return []
    try:
        parsed = json.loads(value)
    except json.JSONDecodeError:
        return []
    return [item for item in parsed if isinstance(item, dict)] if isinstance(parsed, list) else []


def _post_json(url: str, payload: dict, headers: dict[str, str]) -> dict:
    body = json.dumps(payload, ensure_ascii=False).encode("utf-8")
    request = urllib.request.Request(
        url,
        data=body,
        headers={"Content-Type": "application/json; charset=utf-8", **headers},
        method="POST",
    )
    return _open_json(request)


def _get_json(url: str, headers: dict[str, str]) -> dict:
    request = urllib.request.Request(url, headers=headers, method="GET")
    return _open_json(request)


def _open_json(request: urllib.request.Request) -> dict:
    try:
        with urllib.request.urlopen(request, timeout=30) as response:
            return json.loads(response.read().decode("utf-8"))
    except urllib.error.HTTPError as exc:
        error_body = exc.read().decode("utf-8", errors="replace")
        raise RuntimeError(f"HTTPError {exc.code}: {error_body[:1000]}") from exc


if __name__ == "__main__":
    raise SystemExit(main())
