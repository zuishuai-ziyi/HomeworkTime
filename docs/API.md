# API 文档

> 适用版本：HomeworkTime 服务端 v0.1
> 全部接口定义基于 `server/src/app.js` / `server/src/auth.js` / `server/src/routes/*` 与 `client/app/api_client.py` / `server/web/src/api/index.js` 实际实现。

---

## 一、基础说明

### 1.1 baseURL

- 直接访问后端服务（如开发环境）使用：`http://<host>:<PORT>`，默认 `PORT=3000`。
- 通过宝塔面板静态站点 + Nginx 反代时，使用站点域名（如 `https://admin.example.com`）。
- 客户端（PyQt5）使用 `local_config.server_base_url`；后台前端（Vue）axios 实例 `baseURL='/api'`。

### 1.2 数据格式

- 请求体：除文件上传外均为 `application/json`，UTF-8。
- 响应体：均为 `application/json`，UTF-8。
- 错误响应统一格式：`{ "error": "<人类可读消息>" }`。
- 业务校验错误（如 `PUT /api/config`）：`{ "error": "配置校验失败", "errors": ["..."] }`。

### 1.3 三种鉴权方式

服务端通过三种 Express 中间件实现：

| 中间件 | 头部 | 适用接口 | 失败状态码 |
|---|---|---|---|
| `requireAuth` | `Authorization: Bearer <jwt>` | 后台管理接口（除 `/api/config`） | 401 `未提供 Token，请先登录` / 401 `Token 无效或已过期` |
| `requireClientToken` | `X-Client-Token: <token>` | 客户端接口（`/api/client/*`） | 403 `缺少客户端 Token（请求头 X-Client-Token）` / 403 `客户端 Token 无效` |
| `requireAuthOrClientToken` | 任一上述头部 | `GET /api/config`、`PUT /api/config` | 任一头部校验失败分别回 401 / 403；都缺失 → 401 |

#### `requireAuth` 详解

- `JWT_SECRET` 默认值为 `homework-time-default-secret-change-me`，**生产必须通过环境变量覆盖**（`process.env.JWT_SECRET`）。
- JWT 过期时间 12 小时，签发于 `POST /api/auth/login`。
- 通过校验后 `req.user = { id, username, iat, exp }`。

#### `requireClientToken` 详解

- 请求头 `X-Client-Token`（大小写不敏感）与 `client_token` 表中任一行的 `token` 字段相等即可放行（服务端表 `client_token` 是单行 id=1，但 SQL 按 token 全表匹配）。
- 鉴权不修改 `req.user`。

#### `requireAuthOrClientToken` 详解

- 若带 `Authorization: Bearer …` 走 JWT 分支；成功 → `req.user` 有值；
- 否则若带 `X-Client-Token` → 客户端身份，`req.user = null`、`req.clientAuth = true`；
- 两者都缺失 → 401。
- **客户端 Token 身份仅能调用 `GET /api/config` 与 `PUT /api/config`**（即只能读 / 写配置），其余管理接口仍要求 JWT。换句话说：`X-Client-Token` 不等于后台管理员权限。

### 1.4 通用约定

- 所有时间字段（`updated_at`、`last_heartbeat`、`created_at` 等）以 `DATETIME` 存储并以**字符串**形式返回（`db.js` 配置 `dateStrings: true`）。
- `last_config_version` 用于记录该设备最近一次成功拉取的配置版本；客户端心跳携带 `config_version`，服务端 upsert 时刷新。
- 全局启用 CORS（`app.use(cors())`），默认放行所有来源；生产建议按部署需要收敛。
- 全局 JSON body 限制 50MB（`express.json({ limit: '50mb' })`）。超出 → 413 `请求体过大`。
- `/uploads/audio/*` 同时以 `express.static` 直挂（无 token），便于调试；生产部署时建议关闭静态直挂。

---

## 二、错误码一览

| HTTP | 含义 | 触发场景 |
|---|---|---|
| 200 | 成功 | 大多数读 / 写操作 |
| 201 | 已创建 | `POST /api/users` 创建成功 |
| 400 | 请求参数非法 | 字段缺失、类型不符、JSON Schema 校验失败、内置音频不可删等 |
| 401 | 未鉴权 / Token 过期 | 缺 JWT、JWT 过期 / 失效 |
| 403 | 客户端 Token 无效 | 缺 / 错 `X-Client-Token` |
| 404 | 资源不存在 | 配置行缺失（id=1）、音频记录不存在、用户不存在、接口不存在等 |
| 409 | 资源冲突 | 用户名重复（`POST /api/users`、`PUT /api/users/:id`） |
| 413 | 请求体过大 | JSON > 50MB |
| 500 | 服务器内部错误 | 未捕获异常 |

> 4xx 错误响应统一 `{ error, [errors] }`；5xx 错误统一 `{ error: "服务器内部错误" }`，详情可在服务端控制台日志查找。

---

## 三、客户端接口（`X-Client-Token`）

所有 `/api/client/*` 接口均通过 `requireClientToken` 鉴权。客户端（PyQt5）按 `poll_interval_sec` 间隔（默认 10s）调用一次 `heartbeat`，心跳内部按返回的 `version` 决定是否再发起 `GET /api/client/config`。

### 3.1 `GET /api/client/config`

- 鉴权：`X-Client-Token`
- 描述：拉取当前业务配置与版本号；客户端据此判断是否需要更新。

成功响应 `200`：

```json
{
  "version": 7,
  "config": {
    "evening_start": "18:30",
    "evening_end":   "22:00",
    "subjects": [ /* ... */ ],
    "opacity":  { "main": 0.85, "ball": 0.70, "config": 1.00 },
    "allow_local_edit": true,
    "idle_text": "课间休息",
    "sound":    { /* ... */ }
  }
}
```

错误响应：`404 配置不存在`（数据库未初始化时）。

### 3.2 `POST /api/client/heartbeat`

- 鉴权：`X-Client-Token`
- 描述：上报本机心跳；服务端按 `device_uuid` upsert 设备记录，并返回当前 `config.version`，客户端据此决定是否拉取。

请求体：

```json
{
  "device_uuid":    "1f2c4b8a-...",
  "device_name":    "SEEWO-A01",
  "client_version": "1.0.0",
  "config_version": 6
}
```

字段说明：

| 字段 | 类型 | 必填 | 说明 |
|---|---|---|---|
| `device_uuid` | string | 是 | 客户端首次启动生成的 UUID，作为设备唯一标识 |
| `device_name` | string | 否 | 主机名（客户端默认用 `platform.node()`） |
| `client_version` | string | 否 | 客户端版本号（当前 `1.0.0`） |
| `config_version` | integer \| null | 否 | 该客户端最近一次成功拉取的配置版本 |

成功响应 `200`：

```json
{ "version": 7 }
```

错误响应：`400 device_uuid 不能为空`。

服务端行为：
- `last_heartbeat = NOW()`，`ip = req.ip`；
- 返回当前 `config` 表单行（id=1）的 `version`。

### 3.3 `GET /api/client/audio`

- 鉴权：`X-Client-Token`
- 描述：列出服务端可下载的所有音频，客户端按 `filename + sha256` 比对后按需下载。

成功响应 `200`（**裸数组**，非 `{items:[...]}`）：

```json
[
  { "filename": "end.wav",  "size": 12345, "sha256": "abcd...", "is_builtin": true  },
  { "filename": "near.wav", "size": 67890, "sha256": "ef01...", "is_builtin": true  },
  { "filename": "alert.wav","size": 33333, "sha256": "2233...", "is_builtin": false }
]
```

字段说明：

| 字段 | 类型 | 说明 |
|---|---|---|
| `filename` | string | 文件名（带 `.wav`） |
| `size` | number \| null | 字节数；内置音频在 DB 中存 NULL，响应中为 `null` |
| `sha256` | string \| null | 十六进制 sha256；内置音频为 `null` |
| `is_builtin` | boolean | 是否内置（不可删） |

排序：按 `filename ASC`。

### 3.4 `GET /api/client/audio/:filename`

- 鉴权：`X-Client-Token`
- 描述：按文件名下载音频二进制流。**只返回服务端存在物理文件的记录**（即 `stored_path IS NOT NULL` 的行）。

路径参数：

| 参数 | 类型 | 说明 |
|---|---|---|
| `filename` | string | 文件名，必须匹配 `^[A-Za-z0-9._-]+$` |

成功响应 `200`：`audio/wav` 二进制流。

错误响应：
- `400 非法文件名`（不匹配字符白名单）；
- `404 音频不存在`（DB 中无该记录或 `stored_path` 为 NULL）；
- `404 音频文件不存在`（DB 记录存在但物理文件丢失 / ENOENT）。

> `near.wav` / `end.wav` 内置行 `stored_path` 为 NULL，因此**不能**通过本接口下载——客户端内置资源来自 `client/resources/sounds/`；只有当管理员上传同名覆盖版后，本接口才能下到文件。

---

## 四、后台接口（JWT）

后台 axios 实例自动注入 `Authorization: Bearer <jwt>`，401 时自动清 token 并跳转 `/login`。

### 4.1 `POST /api/auth/login`

- 鉴权：无
- 描述：用户名 + 密码登录，签发 12 小时过期的 JWT。

请求体：

```json
{ "username": "admin", "password": "admin123" }
```

成功响应 `200`：

```json
{ "token": "eyJhbGciOiJIUzI1NiIs...", "username": "admin" }
```

错误响应：
- `400 用户名和密码不能为空`；
- `401 用户名或密码错误`（用户名不存在与密码错误均返回此消息，避免用户名枚举）。

### 4.2 `GET /api/config`

- 鉴权：`requireAuthOrClientToken`（JWT 或 `X-Client-Token`）
- 描述：读取当前业务配置单行（id=1）。

成功响应 `200`：

```json
{
  "version":     7,
  "config":      { /* 业务配置 JSON，与 GET /api/client/config 一致 */ },
  "updated_at":  "2026-09-18 12:34:56",
  "updated_by":  1
}
```

字段说明：

| 字段 | 类型 | 说明 |
|---|---|---|
| `version` | integer | 单调递增版本号 |
| `config` | object | 业务配置 JSON |
| `updated_at` | string | 最近一次更新时间 |
| `updated_by` | integer \| null | 最近一次修改者 user.id；客户端 Token 身份提交修改时记录为 `null` |

错误响应：`404 配置不存在（请先执行 schema.sql 或让 seed 初始化）`。

### 4.3 `PUT /api/config`

- 鉴权：`requireAuthOrClientToken`（JWT 或 `X-Client-Token`）
- 描述：写入新业务配置；服务端校验并合并默认值，`version+1` 写审计日志。

请求体：

```json
{ "config": { /* 业务配置 JSON，可部分提交，缺失字段自动用默认值补齐 */ } }
```

成功响应 `200`：

```json
{
  "version":     8,
  "config":      { /* 合并默认值后的完整配置 */ },
  "updated_at":  "2026-09-18 13:00:00",
  "updated_by":  null
}
```

校验错误响应 `400`：

```json
{
  "error": "配置校验失败",
  "errors": [
    "sound.near_seconds 必须为 1~3600 的整数（单位秒）",
    "科目时间段重叠: \"数学\" 19:30-20:30 与 \"物理\" 20:00-21:00"
  ]
}
```

错误响应：
- `400 请求体必须包含 config 字段`；
- `400 配置校验失败`（带 `errors[]`）；
- `404 配置不存在`（同上）。

服务端行为：
- 调用 `validateAndMerge()`（`server/src/utils/validate.js`）做轻量校验 + 默认值合并；
- 写入审计日志 `config.update`，`detail_json = { version: 新版本号, changed_keys: [...], source: 'admin' | 'client' }`；
- `updated_by` 在客户端身份时为 `null`。

### 4.4 `GET /api/audio`

- 鉴权：`requireAuth`（JWT）
- 描述：列出音频元数据（内置在前）。

成功响应 `200`：

```json
{
  "total": 3,
  "items": [
    {
      "id": 1,
      "filename": "near.wav",
      "size": 67890,
      "sha256": "ef01...",
      "is_builtin": true,
      "created_at": "2026-09-13 10:00:00",
      "uploaded_by": "admin"
    },
    /* ... */
  ]
}
```

排序：`is_builtin DESC, id ASC`（内置靠前，按上传顺序）。

> `uploaded_by` 通过 LEFT JOIN `users` 取出，**返回的是用户名（字符串），不是 user.id**；内置行 `uploaded_by` 为 `null`。

### 4.5 `POST /api/audio`

- 鉴权：`requireAuth`（JWT）
- 描述：上传音频；`multipart/form-data`，**字段名必须为 `file`**。

请求（curl 示例）：

```bash
curl -X POST http://host:3000/api/audio \
  -H "Authorization: Bearer <jwt>" \
  -F "file=@/path/to/alert.wav"
```

约束：
- 文件名必须匹配 `^[A-Za-z0-9._-]+$` 且以 `.wav` 结尾（大小写不敏感）；
- 大小不限（multer diskStorage 未设 `limits`，默认无 multipart 限制）；
- 同名覆盖：`INSERT ... ON DUPLICATE KEY UPDATE`，物理文件被新文件覆盖；若冲突行原本是内置音频（`is_builtin=1`），`is_builtin` 保持为 1（仍不可删），但 `stored_path / size / sha256 / uploaded_by` 被刷新。

成功响应 `200`：

```json
{
  "id": 4,
  "filename": "alert.wav",
  "size": 33333,
  "sha256": "2233...",
  "is_builtin": false,
  "created_at": "2026-09-18 13:00:00"
}
```

错误响应：
- `400 仅允许上传 .wav 文件`（扩展名或字符非法）；
- `400 文件名包含非法字符…`（multer 报错统一为 400）；
- `400 缺少上传文件（字段名应为 file）`；
- `400 上传失败: <multer 错误消息>`（如磁盘写入失败）。

服务端行为：
- 计算 sha256、计算相对路径 `uploads/audio/<filename>`；
- 写审计日志 `audio.upload`，`detail_json = { filename, size, sha256 }`；
- 返回新记录的元数据。

### 4.6 `DELETE /api/audio/:id`

- 鉴权：`requireAuth`（JWT）

路径参数：

| 参数 | 类型 | 说明 |
|---|---|---|
| `id` | integer | 音频记录主键 |

成功响应 `200`：

```json
{ "ok": true }
```

错误响应：
- `400 非法 id`；
- `400 内置音频不可删除`；
- `404 音频记录不存在`。

服务端行为：
- 删除记录 + 物理文件（unlink 失败仅记录日志，不影响主流程）；
- 写审计日志 `audio.delete`，`detail_json = { id, filename, size }`。

### 4.7 `GET /api/users`

- 鉴权：`requireAuth`（JWT）
- 描述：列出后台管理员账号（**不含密码哈希**）。

成功响应 `200`：

```json
{
  "total": 2,
  "items": [
    { "id": 1, "username": "admin", "created_at": "...", "updated_at": "..." },
    { "id": 2, "username": "zhangsan", "created_at": "...", "updated_at": "..." }
  ]
}
```

排序：`id ASC`。

### 4.8 `POST /api/users`

- 鉴权：`requireAuth`（JWT）

请求体：

```json
{ "username": "zhangsan", "password": "abc123" }
```

成功响应 `201`：

```json
{ "id": 2, "username": "zhangsan" }
```

错误响应：
- `400 用户名和密码不能为空`；
- `400 密码长度至少 6 位`；
- `409 用户名已存在`。

服务端行为：bcrypt 10 轮哈希；写审计日志 `user.create`，`detail_json = { id, username }`。

### 4.9 `PUT /api/users/:id`

- 鉴权：`requireAuth`（JWT）

请求体（任一字段可单独提交）：

```json
{ "username": "lisi", "password": "newPassw0rd" }
```

成功响应 `200`：

```json
{ "id": 2, "username": "lisi" }
```

错误响应：
- `400 非法 id`；
- `400 用户名不能为空`；
- `400 密码长度至少 6 位`；
- `400 未提供需要修改的字段（username 或 password）`；
- `404 用户不存在`；
- `409 用户名已存在`。

服务端行为：写审计日志 `user.update`，`detail_json = { id, username, changed: ['username = ?' / 'password_hash = ?', ...] }`。

### 4.10 `DELETE /api/users/:id`

- 鉴权：`requireAuth`（JWT）

成功响应 `200`：

```json
{ "ok": true }
```

错误响应：
- `400 非法 id`；
- `400 不能删除自己（当前登录账号）`；
- `400 不能删除最后一个用户`；
- `404 用户不存在`。

服务端行为：写审计日志 `user.delete`，`detail_json = { id, username }`。

### 4.11 `GET /api/client-token`

- 鉴权：`requireAuth`（JWT）
- 描述：查看当前客户端 Token（用于发放到客户端）。

成功响应 `200`：

```json
{ "token": "48位十六进制字符串", "updated_at": "2026-09-18 13:00:00" }
```

错误响应：`404 客户端 Token 未初始化`。

### 4.12 `POST /api/client-token/reset`

- 鉴权：`requireAuth`（JWT）
- 描述：重置客户端 Token；新 Token 是 `crypto.randomBytes(24).toString('hex')`（48 位十六进制）。

请求体：无。

成功响应 `200`：

```json
{ "token": "新48位十六进制字符串" }
```

服务端行为：UPSERT 到 `client_token(id=1)`；写审计日志 `token.reset`，`detail_json = {}`。

> 重置后，**所有正在运行的客户端在下一次心跳时会拿到 403**（Token 不一致）；需在客户端重新填入新 Token 或让用户重启客户端由引导流程填写。

### 4.13 `GET /api/devices`

- 鉴权：`requireAuth`（JWT）
- 描述：列出设备心跳与在线状态。

成功响应 `200`：

```json
{
  "total": 2,
  "items": [
    {
      "id": 1,
      "device_uuid": "1f2c4b8a-...",
      "device_name": "SEEWO-A01",
      "room_name": "一年级一班",
      "ip": "192.168.1.20",
      "client_version": "1.0.0",
      "last_heartbeat": "2026-09-18 13:00:00",
      "last_config_version": 7,
      "created_at": "2026-09-13 10:00:00",
      "updated_at": "2026-09-18 13:00:00",
      "online": true
    }
  ]
}
```

`online` 计算：

```sql
TIMESTAMPDIFF(SECOND, last_heartbeat, NOW()) <= 30 AS online
```

> `last_heartbeat IS NULL`（从未心跳过）的设备 `online` 计算结果为 `false`，并且排序时被排到最后。

排序：`last_heartbeat IS NULL ASC, last_heartbeat DESC, id DESC`。

### 4.14 `PUT /api/devices/:id`

- 鉴权：`requireAuth`（JWT）
- 描述：修改教室名（`room_name`）。

请求体：

```json
{ "room_name": "一年级一班" }
```

- 传 `null` 表示清空教室名；
- 字符串允许空字符串吗？代码仅校验长度 ≤ 128 且去除两端空白，未禁止空串；如需清空建议传 `null`。

成功响应 `200`：

```json
{ "id": 1, "room_name": "一年级一班" }
```

错误响应：
- `400 非法 id`；
- `400 请求体必须包含 room_name 字段`；
- `400 room_name 必须为字符串`；
- `400 room_name 长度不能超过 128 字符`；
- `404 设备不存在`。

服务端行为：写审计日志 `device.rename`，`detail_json = { id, device_uuid, room_name }`。

### 4.15 `GET /api/audit-logs`

- 鉴权：`requireAuth`（JWT）

查询参数：

| 参数 | 类型 | 默认 | 范围 | 说明 |
|---|---|---|---|---|
| `page` | integer | `1` | ≥ 1 | 页码 |
| `page_size` | integer | `20` | 1–100 | 每页条数 |

成功响应 `200`：

```json
{
  "total": 42,
  "page": 1,
  "page_size": 20,
  "items": [
    {
      "id": 42,
      "user_id": 1,
      "action": "config.update",
      "detail_json": { "version": 8, "changed_keys": ["sound"], "source": "admin" },
      "created_at": "2026-09-18 13:00:00",
      "username": "admin"
    }
  ]
}
```

`detail_json` 已是反序列化后的对象（MySQL JSON 列自动解析为 JS 对象）。

排序：`created_at DESC, id DESC`。

### 4.16 `GET /api/health`

- 鉴权：无
- 描述：健康检查端点，供负载均衡 / 部署探测使用。

成功响应 `200`：

```json
{ "ok": true, "time": "2026-09-18T13:00:00.000Z" }
```

---

## 五、常见错误场景对照

| 场景 | HTTP | error 文本 |
|---|---|---|
| JWT 缺失 | 401 | `未提供 Token，请先登录` |
| JWT 过期 / 签名错 | 401 | `Token 无效或已过期` |
| `X-Client-Token` 缺失 | 403 | `缺少客户端 Token（请求头 X-Client-Token）` |
| `X-Client-Token` 错 | 403 | `客户端 Token 无效` |
| 用 `X-Client-Token` 调后台管理接口 | 401 | `未提供 Token，请先登录`（`requireAuth` 只认 JWT） |
| 登录密码错 | 401 | `用户名或密码错误` |
| 创建同名用户 | 409 | `用户名已存在` |
| 改自己密码 / 删自己 | 400 | `不能删除自己（当前登录账号）` |
| 删最后一个用户 | 400 | `不能删除最后一个用户` |
| 上传非 .wav 文件 | 400 | `仅允许上传 .wav 文件` |
| 删除内置音频 | 400 | `内置音频不可删除` |
| 配置 PUT 字段缺失 / 非法 | 400 | `配置校验失败`（附 `errors[]`） |
| 配置行 id=1 不存在 | 404 | `配置不存在（请先执行 schema.sql 或让 seed 初始化）` |
| 请求体 > 50MB | 413 | `请求体过大` |
| 接口路径不存在 | 404 | `接口不存在` |
| 数据库连接断开等 | 500 | `服务器内部错误`（控制台有完整堆栈） |