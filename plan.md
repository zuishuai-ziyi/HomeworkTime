# HomeworkTime 作业时间提醒 — 实施方案

> 客户端：PyQt5 运行于学校希沃一体机（Windows x64），先源码运行
> 服务端：Node.js + Express + MySQL + Vue3，部署于宝塔面板

---

## 一、项目概述

| 组件 | 技术栈 | 运行位置 |
|---|---|---|
| 客户端 | Python 3.14 + PyQt5 5.15.11（Qt 5.15.2） | 希沃一体机 Windows x64，先源码运行 |
| 服务端 | Node.js + Express + MySQL（mysql2 / jsonwebtoken / bcryptjs / multer） | 宝塔面板服务器 |
| 后台前端 | Vue3 + Vite + Element Plus（前后端分离） | 宝塔静态托管 |

当前工作目录为空，全新项目。

### 核心功能（对应题目要求，无删减）

1. **晚自习时间内**：半透明置顶主窗口，显示当前时段应书写的科目、剩余时间倒计时、整个晚自习的纵向时间轴；窗口可被关闭，关闭后变为半透明悬浮球，可点击打开主窗口或拖动移动。
2. **晚自习时间之外**：显示为置底的半透明悬浮球。
3. 同时支持**通过网络远程修改配置**和**直接在本地修改配置**；右键悬浮球弹出确认对话框，确定后打开配置窗口。
4. 临近结束（结束前 N 秒）每秒提示音一次；结束时额外提示音一次；音频、时机、开关均可配置。
5. 服务端提供**后台管理界面**（登录、配置编辑、音频上传、用户管理、Token 重置、设备监控、操作日志）。

---

## 二、最终决策清单

### 2.1 客户端行为

- 晚自习内：无边框圆角半透明**置顶**主窗口，可拖动、可关闭；关闭后变为悬浮球。
- 晚自习外：**置底**半透明悬浮球；点击仍可打开主窗口并提示"不在晚自习时间"，窗口保持置底。
- 到点自动弹窗 + 置顶；退出晚自习自动收起为悬浮球。
- 悬浮球：圆形图标、尺寸可配（默认 64px）、位置记忆（本地持久化）；单击打开主窗口、按住拖动移动（移动 >5px 判定为拖动）、右键弹确认对话框（仅确认是否打开配置窗口）。
- 主窗口**不在任务栏显示**（`Qt.Tool`），仅靠托盘 + 悬浮球控制。
- 托盘图标：双击显示主窗口；右键菜单（显示主窗口 / 配置 / 退出）。
- 单实例（`QLocalServer` 优先，`QSharedMemory` 兜底）。
- 开机自启（写 `HKCU\Software\Microsoft\Windows\CurrentVersion\Run`）。
- 首次运行：打包时提供默认配置；未提供默认配置则弹出引导窗口（服务器地址 + Token + 测试连接按钮）。
- 本地日志：按天滚动写入本地文件，**不上报**服务器。

### 2.2 配置项

| 分类 | 配置项 |
|---|---|
| 业务配置（服务器下发 + 本地缓存） | 晚自习起止时间；科目及时间段（每天同一套，单晚 ≤10 个，超出时间轴区域可滚动）；主窗口/悬浮球/配置窗口透明度（默认 85% / 70% / 100%，范围 20%–100%）；是否允许本地修改配置；空档期显示文本（默认"课间休息"）；提示音（仅全局一套：临近阈值 N 秒 + 临近音频 + 结束音频 + 各自开关） |
| 本机专属配置（local_config.json，不同步） | server_base_url、client_token、poll_interval_sec（默认 10s）、autostart、ball_pos、ball_size、device_uuid |

- 透明度实现：整体 `setWindowOpacity`（在希沃触摸屏上仍可交互）。
- 是否允许本地修改配置 = false 时：隐藏/置灰本地配置入口并提示改用远程后台。

### 2.3 配置一致性

- 远程与本地读取/修改的是**同一份配置**（单一数据源 = 服务器），不存在优先级问题，后修改的自然生效。
- 本地配置窗口保存时直接调用服务器 API 写入；**离线时写入待同步队列**（pending_updates.json），联网后按序补传。
- 服务器不可达时：使用**本地缓存配置离线运行**，恢复后自动同步。

### 2.4 服务端

- 后台鉴权：用户名 + 密码（JWT + bcrypt）；客户端使用**独立单一 Token**，后台可重置。
- 后台模块：配置编辑、音频上传管理、用户管理、Token 重置、设备在线监控、操作日志。
- **取消配置版本快照与回滚**（经确认），仅保留操作日志（谁在何时改了什么）。
- 音频：**不限制大小**，仍记录 size + sha256 供客户端比对；内置 `near.wav` / `end.wav` 由开发方合成并随客户端打包，后台不可删；上传音频后台可管理（含删除）。
- 设备标识：随机 UUID（首次生成存本地）+ 主机名；后台可改教室名。
- 心跳与轮询同频（默认 10 秒一次）；**30 秒无心跳判离线**。
- 全部设备共用一套全局配置。
- 存储：宝塔 MySQL，**新建独立库 `homework_time`**，建表脚本随项目提供。

### 2.5 网络与时间

- 通信：HTTP 轮询，默认间隔 10 秒（本地可配置）。
- 时间基准：本地系统时间。
- 时间模型：每天同一套时间段（周一至周日相同）。
- 晚自习**一般不会跨 00:00**，但调度器需做**跨天兼容处理**（end <= start 视为跨天，次日 end 结束）。
- 音频下发：客户端按文件名 + sha256 对比，按需下载并缓存到本地目录。

---

## 三、架构与数据流

```
┌──────────────── 宝塔服务器 (Express + MySQL + Vue3 后台) ────────────────┐
│                                                                        │
│   客户端接口 (X-Client-Token 鉴权)            后台接口 (JWT 鉴权)          │
│   GET  /api/client/config                    POST /api/auth/login       │
│   POST /api/client/heartbeat                 GET/PUT /api/config        │
│   GET  /api/client/audio/:filename           GET/POST/DELETE /api/audio │
│                                             GET/POST/PUT/DELETE /api/users│
│                                             GET /api/client-token       │
│                                             POST /api/client-token/reset │
│                                             GET /api/devices            │
│                                             GET /api/audit-logs         │
└───────────────▲─────────────────────────────────────────────────────────┘
                │ 轮询(10s) / 心跳 / 音频下载(diff-sha256) / PATCH 配置(离线暂存补传)
                ▼
┌─────────────────────────── PyQt5 客户端 ────────────────────────────────┐
│  主窗口 / 悬浮球 / 配置窗口 / 首次运行引导 / 托盘 / 右键确认对话框           │
│  Scheduler     — 当前科目、空档、剩余时间、临近/结束提示音调度（含跨天）     │
│  ConfigManager — 本地配置(local_config.json)、业务配置缓存、待同步队列      │
│  ApiClient     — 轮询、心跳、上传配置、音频按需下载 + sha256 校验          │
│  AudioPlayer   — winsound 异步播放 WAV                                   │
│  Logger / SingleInstance / Autostart                                    │
└─────────────────────────────────────────────────────────────────────────┘
```

### 双配置文件

- `local_config.json`（本机专属，不参与服务器同步）：`server_base_url`、`client_token`、`poll_interval_sec`、`autostart`、`ball_pos`、`ball_size`、`device_uuid`。
- 业务配置（服务器下发 + 本地缓存）：晚自习起止、科目时间段、透明度、本地配置开关、提示音、空档期文本等。

### 调度模型（含跨天兼容）

```
晚自习区间 [start, end]（若 end <= start 视为跨天：结束于次日 end）
  ├─ 科目段 [start, end] → 显示科目大字 + end - t 倒计时
  ├─ 空档期               → 显示可配置文本（默认"课间休息"）
  └─ ...
```

- 当前时刻 t 落在科目段 → 科目大字 + `end - t` 倒计时。
- t 落在空档期 → 显示空档文本。
- t 在晚自习区间外 → 悬浮球态；打开主窗口显示"不在晚自习时间"，窗口置底。
- 提示音触发：
  - `0 < end_t - t <= near_seconds` 且开启 → 每秒播放 `near.wav`。
  - 跨越 `end_t` 的瞬间 → 播放一次 `end.wav`。
  - 进入新科目段 → 重置本段提示音状态。
- 跨天处理：时间统一转换为"当天秒数 + 日偏移"进行区间比较，避免午夜判断错误。

---

## 四、数据库设计（表结构不含版本快照表）

| 表 | 用途 | 关键字段 |
|---|---|---|
| `users` | 后台管理员 | id, username, password_hash(bcrypt), created_at |
| `config` | 当前全局配置（单行） | id, content_json, version, updated_at, updated_by |
| `client_token` | 客户端 Token | id, token, updated_at |
| `devices` | 设备在线监控 | id, device_uuid, device_name, ip, client_version, last_heartbeat, last_config_version |
| `audio_files` | 音频文件元数据 | id, filename, stored_path, size, sha256, is_builtin, uploaded_by, created_at |
| `audit_logs` | 操作日志 | id, user_id, action, detail_json, created_at |

---

## 五、API 设计

### 客户端接口（`X-Client-Token` 鉴权）
- `GET /api/client/config` → `{version, config}`
- `POST /api/client/heartbeat` → `{device_uuid, device_name, client_version, config_version}`
- `GET /api/client/audio/:filename` → 二进制流

### 后台接口（JWT 鉴权）
- `POST /api/auth/login`
- `GET /api/config` / `PUT /api/config`（保存即写审计日志）
- `GET /api/audio` / `POST /api/audio`（multer 上传，仅 WAV）/ `DELETE /api/audio/:id`
- `GET/POST/PUT/DELETE /api/users`
- `GET /api/client-token` / `POST /api/client-token/reset`
- `GET /api/devices`（在线判定：last_heartbeat 距今 ≤ 30s）
- `GET /api/audit-logs`

---

## 六、项目结构

```
HomeworkTime/
├─ plan.md                         # 本方案文档
├─ client/
│  ├─ main.py                      # 程序入口
│  ├─ app/
│  │  ├─ __init__.py
│  │  ├─ config.py                 # 配置模型、本地配置文件读写、业务配置缓存、待同步队列
│  │  ├─ api_client.py             # 轮询、心跳、PATCH 配置、音频下载 + sha256 校验
│  │  ├─ scheduler.py              # 时间段计算、跨天兼容、提示音调度（纯函数，可单测）
│  │  ├─ audio.py                  # winsound 异步播放 WAV
│  │  ├─ single_instance.py        # 单实例锁
│  │  ├─ autostart.py              # 开机自启（注册表 Run）
│  │  ├─ logger.py                 # 按天滚动本地日志
│  │  └─ windows/
│  │     ├─ __init__.py
│  │     ├─ main_window.py         # 无边框圆角半透明卡片、时间轴、倒计时、可拖动
│  │     ├─ float_ball.py          # 圆形悬浮球（单击/拖动/右键）
│  │     ├─ config_window.py       # 配置窗口
│  │     ├─ confirm_dialog.py      # 右键确认对话框
│  │     ├─ guide_window.py        # 首次运行引导
│  │     └─ tray.py                # 托盘图标
│  ├─ resources/
│  │  ├─ sounds/                   # 内置 near.wav / end.wav（合成）
│  │  └─ icons/                    # 悬浮球、托盘图标
│  ├─ requirements.txt
│  └─ local_config.example.json    # 本地配置示例（打包时随附）
├─ server/
│  ├─ package.json
│  ├─ src/
│  │  ├─ app.js                    # Express 入口
│  │  ├─ db.js                     # MySQL 连接池
│  │  ├─ auth.js                   # JWT + bcrypt + 客户端 Token 校验中间件
│  │  ├─ routes/                   # auth / config / audio / users / token / devices / audit
│  │  └─ utils/                    # 通用工具、审计日志写入
│  ├─ web/                         # Vue3 + Vite + Element Plus 后台（前后端分离）
│  │  ├─ package.json
│  │  ├─ vite.config.js
│  │  └─ src/ ...
│  ├─ sql/
│  │  └─ schema.sql                # 建库建表脚本
│  └─ uploads/
│     └─ audio/                    # 上传音频存储目录
└─ docs/
   ├─ 配置说明.md                  # 全部配置项含义与示例
   ├─ API.md                       # 接口文档
   └─ 部署说明.md                  # 宝塔部署步骤
```

---

## 七、实施阶段

1. **阶段 0 脚手架**
   - 建目录结构；`client/requirements.txt`、`server/package.json`、`sql/schema.sql`
   - 定义业务配置 JSON Schema（作为客户端模型、服务端校验、后台表单的唯一契约）
   - 合成内置音频 `near.wav` / `end.wav`

2. **阶段 1 客户端核心**
   - `scheduler.py`（含跨天兼容，纯函数可单测）
   - `audio.py`（winsound 异步播放）
   - `main_window.py` 无边框圆角半透明卡片 + 纵向时间轴 + 科目大字 + 倒计时 + 可拖动 + 关闭按钮
   - `float_ball.py` 圆形悬浮球（单击/拖动/右键三态，位置记忆）
   - 窗口状态机：晚自习内（置顶主窗口）/ 晚自习外（置底悬浮球）/ 主窗口关闭（悬浮球）
   - 到点自动弹窗、自动收起（QTimer 每秒 tick）
   - 主窗口 `Qt.Tool` 不占任务栏

3. **阶段 2 本地化能力**
   - `config_window.py` 全部配置项编辑（透明度滑条、本地配置开关、提示音阈值/音频/开关、晚自习起止、科目时间段增删改、空档期文本、悬浮球尺寸）
   - 右键确认对话框 → 打开配置窗口；本地配置开关关闭时隐藏/置灰入口并提示
   - `tray.py` 托盘（双击显示、右键菜单）
   - `single_instance.py`、`autostart.py`、`logger.py`、首次运行引导窗口

4. **阶段 3 服务端**
   - MySQL 建库建表；`db.js` 连接池
   - 鉴权中间件（JWT + bcrypt + 客户端 Token）
   - 配置读写、音频上传/列表/下载、用户管理、客户端 Token 重置、设备心跳与在线列表、审计日志

5. **阶段 4 Vue3 后台**
   - 登录页、配置编辑页（时间段编辑器、透明度滑条、开关、提示音配置）、音频管理页、用户管理页、设备监控页、操作日志页

6. **阶段 5 客户端接入服务端联调**
   - `api_client.py`：10 秒轮询、心跳、离线缓存、待同步队列补传、音频按需下载 + sha256 校验
   - 端到端验证：后台改配置 → 客户端 ≤10 秒生效；断网 → 缓存运行 + 恢复同步；音频上传 → 客户端下发音效

7. **阶段 6 部署与文档**
   - 宝塔部署 Node 项目 + MySQL + Vue 静态托管（部署信息由用户后续提供：域名/IP、端口、HTTPS）
   - `docs/` 配置说明、API、部署说明

---

## 八、关键技术要点

- **窗口样式**：`Qt.FramelessWindowHint | Qt.WA_TranslucentBackground`，`paintEvent` 自绘圆角矩形，整体透明度用 `setWindowOpacity`（保触摸交互）。
- **置顶/置底**：`Qt.WindowStaysOnTopHint` / `Qt.WindowStaysOnBottomHint`，配合状态机切换。
- **单击/拖动区分**：移动距离 >5px 视为拖动，否则单击。
- **单实例**：`QLocalServer/QLocalSocket` 优先，`QSharedMemory` 兜底。
- **提示音播放**：`winsound.PlaySound(SND_FILENAME | SND_ASYNC)`。
- **音频校验**：客户端按文件名 + sha256 对比本地缓存，缺失或哈希不符则下载。
- **跨天调度**：时间统一转"当天秒数 + 日偏移"再比较。
- **离线同步**：本地改动先写 `pending_updates.json`，恢复连接后按序 PATCH，成功后清除。

---

## 九、约定与注意事项

- 单晚科目数 ≤ 10，超出时时间轴区域滚动。
- 提示音**仅全局一套**（阈值 + 临近音频 + 结束音频 + 开关），不支持每科目覆盖。
- 音频格式：仅 WAV；大小不限；内置 `near.wav` / `end.wav` 后台不可删。
- 后台**不做配置版本回滚**，但每次配置变更写审计日志。
- 设备在线判定：心跳同频轮询（默认 10s），30 秒无心跳判离线。
- 时间基准为本地系统时间，不校准服务器时间。