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
    parser = argparse.ArgumentParser(description="Get Feishu user IDs by mobile or email.")
    parser.add_argument("--mobile", default="", help="User mobile number.")
    parser.add_argument("--email", default="", help="User email.")
    args = parser.parse_args()

    load_env_file(override=False)
    app_id = os.getenv("FEISHU_APP_ID", "")
    app_secret = os.getenv("FEISHU_APP_SECRET", "")
    base_url = os.getenv("FEISHU_API_BASE_URL", "https://open.feishu.cn").rstrip("/")
    if not app_id or not app_secret:
        print("Missing FEISHU_APP_ID or FEISHU_APP_SECRET in .env.")
        return 2
    if not args.mobile and not args.email:
        print("Pass --mobile or --email.")
        return 2

    try:
        token = _tenant_token(base_url, app_id, app_secret)
        result = _lookup_user_id(base_url, token, mobile=args.mobile, email=args.email)
    except Exception as exc:
        print(f"Failed: {type(exc).__name__}: {exc}")
        return 1

    print(json.dumps(result, ensure_ascii=False, indent=2))
    users = result.get("data", {}).get("user_list") or result.get("data", {}).get("users") or []
    if users:
        print("\nCandidates:")
        for user in users:
            print(f"- open_id={user.get('open_id', '')} user_id={user.get('user_id', '')} union_id={user.get('union_id', '')}")
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


def _lookup_user_id(base_url: str, token: str, mobile: str = "", email: str = "") -> dict:
    payload = {}
    if mobile:
        payload["mobiles"] = [mobile]
    if email:
        payload["emails"] = [email]
    query = urllib.parse.urlencode({"user_id_type": "open_id"})
    return _post_json(
        f"{base_url}/open-apis/contact/v3/users/batch_get_id?{query}",
        payload,
        {"Authorization": f"Bearer {token}"},
    )


def _post_json(url: str, payload: dict, headers: dict[str, str]) -> dict:
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


if __name__ == "__main__":
    raise SystemExit(main())
