# 10.0.10.186 部署说明

## 推荐访问地址

推荐把 Web 容器绑定到 80 端口：

```text
前端主页：http://10.0.10.186
后端 API：http://10.0.10.186/api
飞书 OAuth 回调：http://10.0.10.186/api/auth/feishu/callback
```

当前 `docker-compose.yml` 的前端构建参数已经使用 `VITE_API_BASE_URL=/api`，浏览器请求会走同源 `/api`，再由 Nginx 反代到后端容器 `api:8000`。

## 飞书后台配置

在飞书开放平台企业自建应用中配置：

```text
网页应用主页地址：http://10.0.10.186
OAuth 回调地址：http://10.0.10.186/api/auth/feishu/callback
```

权限需要包含：

- 获取用户登录信息 / 网页应用登录。
- 获取用户基本信息。
- 获取单个用户信息或通讯录用户信息，用于补齐 `employee_id`、`department_ids`。
- 如需组织架构同步，继续开启通讯录部门和员工读取权限。

如果飞书后台不接受 `http://10.0.10.186` 作为回调地址，或公司要求生产环境 HTTPS，请在 10.0.10.186 前面配置域名和 TLS，例如：

```text
https://pmc.your-company.com
https://pmc.your-company.com/api/auth/feishu/callback
```

然后同步更新 `.env` 里的 `FRONTEND_URL` 和 `FEISHU_AUTH_REDIRECT_URI`。

## 环境变量

在部署机项目根目录执行：

```powershell
Copy-Item deploy\env.10.0.10.186.example .env
```

然后编辑 `.env`，至少补齐：

```dotenv
PMC_WEB_PORT=80
FEISHU_LOGIN_ENABLED=true
PMC_AUTH_REQUIRED=true
FEISHU_APP_ID=cli_xxx
FEISHU_APP_SECRET=xxx
FEISHU_AUTH_REDIRECT_URI=http://10.0.10.186/api/auth/feishu/callback
FRONTEND_URL=http://10.0.10.186
PMC_SESSION_SECRET=replace-with-a-long-random-secret
PMC_SESSION_COOKIE_SECURE=false
```

如果改用 HTTPS，设置：

```dotenv
FEISHU_AUTH_REDIRECT_URI=https://pmc.your-company.com/api/auth/feishu/callback
FRONTEND_URL=https://pmc.your-company.com
PMC_SESSION_COOKIE_SECURE=true
```

## 权限规则

复制权限示例：

```powershell
Copy-Item config\feishu_permissions.example.json config\feishu_permissions.json
```

把里面的 `department_ids`、`department_names`、`sales_department`、`product_manager` 等映射改成真实组织和业务字段。

## 启动

```powershell
docker compose up -d --build
```

检查：

```powershell
docker compose ps
Invoke-RestMethod http://10.0.10.186/health
Invoke-RestMethod http://10.0.10.186/api/auth/me
```

## 常见问题

- `401 authentication required`：正常，说明 `PMC_AUTH_REQUIRED=true` 已生效，需要从飞书入口登录。
- 登录后没有部门权限：确认飞书应用已开通讯录用户读取权限，或在 `config/feishu_permissions.json` 中改用 `open_ids/user_ids/emails` 匹配。
- 导出按钮不可见：当前用户没有 `export` 功能位。
- 能看页面但没有数据：当前用户的数据范围没有匹配到主宽表字段，例如 `sales_department` 和底表 `sales_apartment` 的值不一致。
