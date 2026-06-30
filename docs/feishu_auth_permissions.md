# 飞书网页登录与权限控制

## 目标

把控制塔网页接入飞书授权登录，并按飞书人员、部门和本系统权限规则限制：

- 可访问的功能界面，例如总览、明细、仓库、字段口径、导出、AI 诊断。
- 可查看的数据范围，例如销售部门、销售员、产品经理、店铺、国家。
- 后端接口的数据返回和导出结果。

前端只负责显示或隐藏入口，真正的数据权限在 FastAPI 后端执行。

## 飞书后台配置

在飞书开放平台的企业自建应用中配置：

1. 网页应用主页地址：你的前端地址，例如 `https://your-domain.com`。
2. OAuth 回调地址：你的后端回调地址，例如 `https://api.your-domain.com/auth/feishu/callback`。
3. 权限申请：
   - 网页应用登录 / 获取用户登录信息。
   - 获取用户基本信息。
   - 获取单个用户信息 / 以应用身份访问通讯录，用于登录后补齐 `employee_id` 和 `department_ids`。
   - 如需同步组织架构，继续保留项目已有的组织架构权限和通讯录授权范围。
4. 应用发布，并设置可用范围。

## 环境变量

复制 `.env.example` 后配置：

```dotenv
FEISHU_LOGIN_ENABLED=true
PMC_AUTH_REQUIRED=true
FEISHU_APP_ID=cli_xxx
FEISHU_APP_SECRET=xxx
FEISHU_AUTH_REDIRECT_URI=https://api.your-domain.com/auth/feishu/callback
FRONTEND_URL=https://your-domain.com
PMC_SESSION_SECRET=replace-with-a-long-random-secret
PMC_SESSION_COOKIE_SECURE=true
PMC_PERMISSION_RULES_PATH=config/feishu_permissions.json
PMC_AUTH_ADMIN_OPEN_IDS=ou_xxx,ou_yyy
```

本地调试时可先使用：

```dotenv
FEISHU_LOGIN_ENABLED=true
PMC_AUTH_REQUIRED=true
FEISHU_AUTH_REDIRECT_URI=http://127.0.0.1:8000/auth/feishu/callback
FRONTEND_URL=http://127.0.0.1:5173
PMC_SESSION_COOKIE_SECURE=false
```

## 权限规则

复制示例文件：

```powershell
Copy-Item config\feishu_permissions.example.json config\feishu_permissions.json
```

规则结构：

```json
{
  "rules": [
    {
      "id": "sales-north-america-manager",
      "role": "sales_manager",
      "match": {
        "department_ids": ["od_feishu_sales_department_id"],
        "department_names": ["北美销售部"]
      },
      "features": ["overview", "detail", "warehouse", "sku_diagnosis", "export"],
      "data_scope": {
        "sales_department": ["North America"]
      }
    }
  ],
  "default_policy": {
    "role": "member",
    "features": ["overview", "detail", "sku_diagnosis"],
    "data_scope": {
      "salesman": ["$user.name"]
    }
  }
}
```

支持的匹配条件：

- `open_ids`
- `user_ids`
- `union_ids`
- `employee_ids`
- `emails`
- `email_domains`
- `department_ids`
- `department_names`

支持的功能位：

- `overview`
- `detail`
- `warehouse`
- `standards`
- `sku_diagnosis`
- `logistics_detail`
- `agent_chat`
- `export`
- `admin`
- `*`

支持的数据范围字段：

- `sales_department`
- `salesman`
- `product_manager`
- `country_code`
- `shipments_country`
- `store_name`
- `seller_id`

占位符：

- `$user.name`
- `$user.open_id`
- `$user.user_id`
- `$user.employee_id`
- `$user.email`
- `$user.enterprise_email`

## 验证

启动后访问：

```text
GET /auth/me
```

未登录且 `PMC_AUTH_REQUIRED=true` 时，业务接口会返回 `401`。

登录后检查：

- `/auth/me` 是否返回飞书用户和 `permissions`。
- 控制塔总览是否只返回权限范围内的数据。
- 没有 `export` 功能位的用户是否看不到导出按钮，并且直接请求导出接口会返回 `403`。

## 已接入的后端边界

- `/control-tower/summary`：按权限数据范围裁剪。
- `/control-tower/export/*`：按权限数据范围裁剪，并要求 `export` 功能位。
- `/control-tower/sku-diagnosis/analyze`：要求 `sku_diagnosis`，并校验传入 SKU 是否在用户范围内。
- `/control-tower/sku-shipping-cost`：同上。
- `/control-tower/first-leg-shipments`：要求 `logistics_detail`。
- `/agent/run`：要求 `agent_chat`。
- `/control-tower/cache/clear`：要求 `admin`。
