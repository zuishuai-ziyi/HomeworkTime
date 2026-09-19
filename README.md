# HomeworkTime 晚自习作业时间提示系统

> 部署在学校希沃一体机上的晚自习作业时间提示系统。PyQt5 客户端在晚自习时段显示当前科目/倒计时/纵向时间轴（半透明置顶主窗口），时段外退为置底悬浮球；后台管理员可通过 Vue3 管理端远程下发业务配置、调整音频、管理教室设备。

```text
┌───────────────── 宝塔服务器 (Express + MySQL + Vue3 后台) ──────────────────┐
│                                                                          │
│   客户端接口 (X-Client-Token 鉴权)         后台接口 (JWT 鉴权)               │
│   GET  /api/client/config                 POST /api/auth/login            │
│   POST /api/client/heartbeat              GET/PUT /api/config             │
│   GET  /api/client/audio                  GET/POST/DELETE /api/audio      │
│   GET  /api/client/audio/:filename        GET/POST/PUT/DELETE /api/users  │
│                                           GET /api/client-token           │
│                                           POST /api/client-token/reset    │
│                                           GET/PUT /api/devices            │
│                                           GET /api/audit-logs             │
└───────────────▲──────────────────────────────────────────────────────────┘
                │ 轮询(10s) / 心跳 / 音频下载(diff-sha256) / PATCH 配置(离线暂存补传)
                ▼
┌─────────────────────────── PyQt5 客户端 (Windows 希沃一体机) ──────────────┐
│  主窗口 / 悬浮球 / 配置窗口 / 首次运行引导 / 托盘 / 右键确认对话框         │
│  Scheduler     — 当前科目、空档、剩余时间、临近/结束提示音调度（含跨天）   │
│  ConfigManager — 本地配置 + 业务配置缓存 + 待同步队列                      │
│  ApiClient     — 轮询、心跳、上传配置、音频按需下载 + sha256 校验         │
│  AudioPlayer   — winsound 异步播放 WAV                                    │
│  Logger / SingleInstance / Autostart                                     │
└──────────────────────────────────────────────────────────────────────────┘
```

---

## 一、功能特性

### 客户端（PyQt5）

- 晚自习时段半透明置顶主窗口（440×620 圆角卡片），含当前科目大字、倒计时、纵向时间轴
- 时段外退为置底悬浮球（圆形图标，可拖动、位置记忆）
- 临近结束（默认 60 秒）每秒提示音；结束时额外一次；总/分项开关
- 悬浮球右键 → 确认弹窗 → 配置窗口（业务配置 + 悬浮球尺寸）
- 业务配置支持远程后台 / 本地窗口双轨编辑，服务器为单一数据源
- 离线缓存运行 + 恢复后自动补传队列（`pending_updates.json`）
- 10 秒轮询配置 + 心跳；30 秒无心跳判离线（设备监控）
- 单实例（QLocalServer + QSharedMemory）、开机自启（HKCU 注册表）
- 首次运行引导窗口（服务器地址 + Token + 测试连接）
- 按天滚动本地日志（30 天，仅本地留存，不上报服务器）

### 后台管理（Vue3 + Element Plus）

- 登录鉴权（JWT，12h 过期，bcrypt 密码哈希）
- 业务配置编辑（时间段、透明度、提示音、是否允许本地编辑等）
- 音频管理（上传 WAV、列表、删除；内置音频不可删）
- 用户管理（增删改查；不能删除自己 / 最后一个用户）
- 设备监控（在线判定、心跳时间、教室名改名）
- 客户端 Token 管理（查看 / 重置为 48 位十六进制）
- 操作日志（分页、按时间倒序，含操作人 + 详情 JSON）

---

## 二、技术栈

| 端 | 技术 | 说明 |
|---|---|---|
| 桌面客户端 | Python 3.10+ / 3.14 + PyQt5 5.15.11 + requests | Windows x64，希沃一体机；winsound 异步播放 |
| 服务端 | Node.js ≥ 18 + Express 4.19 + mysql2 + JWT + bcryptjs + multer | 部署于宝塔面板；MySQL 库 `homework_time` (utf8mb4) |
| 管理前端 | Vue 3.5 + Vite 5.4 + Element Plus 2.9 + Pinia + Vue Router 4 (hash) + axios | SPA，`npm run dev` 端口 5173，`build` 输出 `web/dist/` |

---

## 三、目录结构

```text
HomeworkTime/
├─ README.md                       # 本文件
├─ AGENTS.md                       # Agent / 协作者规范
├─ plan.md                         # 实施方案存档
├─ docs/                           # 详细文档（API、配置、部署、开发）
├─ client/                         # PyQt5 桌面客户端
│  ├─ main.py                      # 入口
│  ├─ build.py / build.bat         # PyInstaller 打包
│  ├─ app/                         # 业务模块（main / config / api_client / scheduler …）
│  ├─ resources/                   # 内置音频 / 图标
│  └─ tests/                       # unittest + smoke 测试
└─ server/                         # Node.js 服务端 + Vue3 后台
   ├─ src/                         # Express 入口 / 路由 / 中间件 / utils
   ├─ sql/schema.sql               # 建库建表 + 初始数据
   ├─ uploads/audio/               # 后台上传音频落点
   └─ web/                         # Vue3 后台（独立 npm 工程）
```

更详细结构见 [`docs/开发文档.md`](docs/开发文档.md) 第二章。

---

## 四、快速开始

### 4.1 服务端（Node）

```bash
cd server
npm install                                   # 安装依赖
# 在 MySQL 中创建 homework_time 库并导入初始数据：
mysql -u root -p < sql/schema.sql
# 复制环境变量样例并按需修改：
cp .env.example .env                          # 编辑 .env，至少填 DB_PASSWORD / JWT_SECRET
npm run dev                                   # node --watch src/app.js
curl http://127.0.0.1:3000/api/health         # 期望: {"ok":true,"time":"..."}
```

### 4.2 管理前端（Vue3）

```bash
cd server/web
npm install
npm run dev                                   # 端口 5173，代理 /api→127.0.0.1:3000
# 浏览器访问 http://127.0.0.1:5173
# 默认管理员: admin / admin123（首次部署后立即修改！）
```

### 4.3 客户端（Windows）

```powershell
cd client
pip install -r requirements.txt                # 仅 PyQt5==5.15.11 + requests
python main.py                                # 三种等价启动
```

- 若 `local_config.json` 缺失或 `server_base_url` / `client_token` 为空 → 弹出「首次运行引导」。
- 也可在引导里点「跳过（离线模式）」，客户端使用内置默认业务配置运行（所有保存会写入离线队列）。

---

## 五、客户端打包

```powershell
cd client
# 1) 编辑 local_config.preset.json，填好 server_base_url 与 client_token
#    （免引导；否则产物首次运行会弹引导）
# 2) 打包
python build.py                                # 等价于双击 build.bat
```

产物：`client/dist/HomeworkTime/HomeworkTime.exe`（onedir 单目录）。将整个 `HomeworkTime/` 文件夹拷贝到目标希沃一体机，双击 `HomeworkTime.exe` 即可。

---

## 六、生产部署摘要

1. **服务端**：宝塔面板创建 Node 项目（运行用户 www、Node ≥ 18、端口 3000），上传 `server/`、`npm install --omit=dev`、PM2 守护；创建 `homework_time` 库导入 `sql/schema.sql`；写 `.env`（生产必改 `JWT_SECRET`）。
2. **管理前端**：`cd server/web && npm run build` → 输出 `web/dist/`，由本服务直接静态托管（`app.js` 已配 SPA 兜底），也可走宝塔「网站」+ Nginx 反代 `/api` 与 `/uploads`。
3. **安全**：登录后台立刻修改 `admin` 密码，并在「客户端 Token」页重置 Token；旧客户端需通过引导或托盘「服务器设置」填入新 Token。
4. **客户端**：在 `client/local_config.preset.json` 中填好地址与 Token，`python build.py` 出包后整包分发。

完整步骤、Nginx 反代模板、SSL 与 FAQ 见 [`docs/部署说明.md`](docs/部署说明.md)。

---

## 七、安全提示 ⚠️

- `schema.sql` 末尾的默认管理员 `admin / admin123` 与占位 Token `CHANGE_ME_DEFAULT_TOKEN` **仅供演示**，**首次部署后必须立即修改**（后台「用户管理」+「客户端 Token」页）。
- `JWT_SECRET` 生产环境必须设置为强随机字符串（`openssl rand -hex 32`），否则 `app.js` 启动时会拒绝运行（`NODE_ENV=production` 时直接 `process.exit(1)`）。
- 详见 [`AGENTS.md` 第六章](AGENTS.md) 与 [`docs/部署说明.md`](docs/部署说明.md) 第五章 FAQ。

---

## 八、文档索引

| 文档 | 内容 |
|---|---|
| [docs/API.md](docs/API.md) | REST 接口完整文档（鉴权、请求/响应、错误码、字段约束） |
| [docs/配置说明.md](docs/配置说明.md) | 业务配置 + 本机配置字段含义、默认值、跨天兼容、提示音三态解析 |
| [docs/部署说明.md](docs/部署说明.md) | 宝塔部署步骤 + Nginx 反代 + 客户端打包 + FAQ |
| [docs/开发文档.md](docs/开发文档.md) | 面向开发者的项目现状权威文档（目录、路由、状态机、UI 主题、测试、变更记录） |
| [AGENTS.md](AGENTS.md) | AI 编码代理 / 协作者规范（风格、安全红线、文档同步规则） |