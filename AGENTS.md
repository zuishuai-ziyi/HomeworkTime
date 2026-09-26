# AGENTS.md — HomeworkTime Agent 规范

> 本文件面向 AI 编码代理（以及人类协作者），说明项目结构、常用命令、风格约定、敏感文件红线与文档同步规则。任何对本项目的修改都必须遵守。

---

## 一、项目一句话简介

**HomeworkTime** 是部署在中学希沃一体机（Windows x64）上的晚自习作业时间提示系统。PyQt5 客户端在晚自习时段显示当前科目/倒计时/纵向时间轴（半透明置顶主窗口），时段外退为置底悬浮球；后台管理员可通过 Vue3 管理端远程下发业务配置、调整音频、管理教室设备。

---

## 二、三端技术栈速览

| 端 | 位置 | 技术栈 |
|---|---|---|
| 桌面客户端 | `client/` | Python 3.10+ / 3.14、PyQt5 5.15.11（Qt 5.15.2）、requests；windows 平台 winsound 异步播放 |
| 服务端 | `server/` | Node.js ≥ 18、Express 4.19、mysql2、jsonwebtoken、bcryptjs、multer、cors、dotenv |
| 管理前端 | `server/web/` | Vue 3.5、Vite 5.4、Element Plus 2.9、Pinia 2、Vue Router 4（hash 模式）、axios |

部署：服务端 + 管理前端均部署于宝塔面板，MySQL 库 `homework_time`（utf8mb4）。

---

## 三、目录结构速查

```text
HomeworkTime/
├─ README.md                       # 项目主入口文档（人类读者）
├─ AGENTS.md                       # 本文件（Agent/协作者规范）
├─ plan.md                         # 实施方案存档（阶段 0–6 决策记录）
├─ docs/
│  ├─ API.md                       # REST 接口文档
│  ├─ 配置说明.md                  # 业务配置 + 本机配置字段说明
│  ├─ 部署说明.md                  # 宝塔部署步骤 + 客户端打包
│  └─ 开发文档.md                  # 面向开发者的项目现状权威文档
├─ client/
│  ├─ main.py                      # 入口（sys.path + UTF-8 stdout）
│  ├─ build.py / build.bat         # PyInstaller onedir 打包
│  ├─ local_config.example.json    # 本机配置示例（仅模板）
│  ├─ local_config.preset.json     # 打包预设（不入库；.gitignore；按需从 example 复制并填写）
│  ├─ requirements.txt
│  ├─ app/
│  │  ├─ main.py                   # AppController 启动 + 状态机（含远程更新时机判定）
│  │  ├─ config.py                 # LocalConfig / AppConfig / 离线队列
│  │  ├─ api_client.py             # 心跳/轮询/补传/音频三态下载/更新包流式下载
│  │  ├─ version.py                # APP_VERSION 版本号单一来源
│  │  ├─ theme.py                  # 窗口主题色（业务配置 theme 激活/取色）
│  │  ├─ updater.py                # 远程全量更新（下载/校验/暂存/生效判定/update.bat 替换）
│  │  ├─ scheduler.py              # 纯函数时间调度（含跨天兼容）
│  │  ├─ audio.py                  # winsound 异步播放
│  │  ├─ autostart.py              # 注册表 HKCU\...\Run
│  │  ├─ single_instance.py        # QLocalServer + QSharedMemory
│  │  ├─ logger.py                 # 按天滚动本地日志（30 天）
│  │  ├─ default_config.json       # 内置默认业务配置
│  │  ├─ config_schema.json        # 业务配置 JSON Schema（与 server 对齐）
│  │  └─ windows/                  # main_window / float_ball /
│  │     config_window / guide_window / confirm_dialog / tray
│  ├─ resources/
│  │  ├─ sounds/                   # 内置 near.wav / end.wav
│  │  └─ icons/                    # 悬浮球 / 托盘图标
│  └─ tests/                       # unittest + smoke 测试（含 test_updater / test_theme）
└─ server/
   ├─ package.json
   ├─ .env.example                 # 环境变量样例（真实 .env 不入库）
   ├─ src/
   │  ├─ app.js                    # Express 入口（含 JWT 启动校验 + SPA 兜底）
   │  ├─ auth.js                   # 三种鉴权中间件
   │  ├─ db.js                     # mysql2 连接池
   │  ├─ config.schema.json        # 业务配置契约（与 client 严格一致）
   │  ├─ default_config.json       # 默认业务配置（与 client 一致）
   │  ├─ smoke_test.js             # 纯函数冒烟测试（validate.js + install_script.js）
   │  ├─ routes/                   # auth / config / audio / users /
   │  │                            # token / devices / audit / client / updates / installs
   │  └─ utils/                    # seed（幂等初始化）、validate、install_script、audit
   ├─ sql/schema.sql               # 建库建表 + 初始数据（演示用）
   ├─ uploads/audio/               # 后台上传音频落点（运行时创建）
   ├─ uploads/updates/             # 后台上传更新包落点（运行时创建）
   ├─ uploads/installs/            # 一键安装包落点（运行时创建）
   └─ web/                         # Vue3 后台（独立 npm 工程）
      ├─ package.json
      ├─ vite.config.js            # /api、/uploads 代理到 127.0.0.1:3000
      └─ src/
         ├─ main.js / App.vue / router/
         ├─ api/http.js + api/index.js   # axios 实例 + 接口封装
         ├─ stores/auth.js               # token + username 持久化
         ├─ styles/theme.css             # 蓝色调主题（9 色 + EP 主色覆盖）
         ├─ layout/MainLayout.vue
         └─ views/  Login / ConfigEdit / AudioManage / UpdateManage /
                    InstallManage / UserManage / DeviceMonitor / TokenManage / AuditLogs
```

---

## 四、常用命令（已逐条核实）

### 4.1 服务端（Node）

```bash
cd server
npm install              # 首次安装依赖（开发可选 --omit=dev）
npm run dev              # 开发：node --watch src/app.js（自动重启）
npm start                # 生产：node src/app.js
```

- 启动前需要：MySQL 库已创建并执行 `server/sql/schema.sql`；`.env` 已存在。
- 健康检查：`curl http://127.0.0.1:3000/api/health` → `{"ok":true,"time":"..."}`
- 路由表与方法详见 `docs/API.md` 与 `docs/开发文档.md` 第三章。

### 4.2 管理前端（Vue3）

```bash
cd server/web
npm install              # 首次安装依赖
npm run dev              # 开发：vite，端口 5173；代理 /api→127.0.0.1:3000
npm run build            # 生产：输出 web/dist/，由 Express 直挂
npm run preview          # 预览构建产物
```

- 开发时 Vite dev server 必须配合后端一起启动（前端通过 `/api` 代理访问）。
- `vite.config.js` 已配好 `/api` 与 `/uploads` 转发，无需手动改。

### 4.3 客户端源码运行（Windows）

```powershell
cd client
pip install -r requirements.txt   # 仅 PyQt5==5.15.11 + requests
python main.py                     # 三种等价启动：python main.py / python -m app.main
```

- 首次运行若 `local_config.json` 缺失或 url/token 为空，会弹出 **首次运行引导窗口**（`GuideWindow`）。
- 也可在「跳过（离线模式）」后通过托盘「服务器设置」重新打开。

### 4.4 客户端语法检查

```powershell
# 整包语法检查
python -m compileall client/app

# 逐文件快速过
python -m py_compile client\main.py
python -m py_compile client\app\main.py client\app\config.py client\app\api_client.py
python -m py_compile client\app\scheduler.py client\app\audio.py client\app\logger.py
python -m py_compile client\app\single_instance.py client\app\autostart.py
python -m py_compile client\app\windows\main_window.py
python -m py_compile client\app\windows\float_ball.py
python -m py_compile client\app\windows\config_window.py
python -m py_compile client\app\windows\guide_window.py
python -m py_compile client\app\windows\confirm_dialog.py
python -m py_compile client\app\windows\tray.py
```

### 4.5 客户端测试

```powershell
# 单元测试（unittest，从项目根目录运行）
python -m unittest client.tests.test_scheduler -v
python -m unittest client.tests.test_preset -v
python -m unittest client.tests.test_stage2 -v
python -m unittest client.tests.test_stage5 -v

# 无头冒烟测试（offscreen 平台下安全）
python client\tests\smoke_controller.py
python client\tests\smoke_stage2.py
python client\tests\smoke_ui.py

# 一键跑完所有单元测试
python -m unittest discover -s client/tests -p "test_*.py" -v
```

- `smoke_*` 需在 import 前设 `QT_QPA_PLATFORM=offscreen`（脚本内部已 `setdefault`）。
- `smoke_ui.py` 在 PyQt5 未安装时退出码 42 表示跳过。

### 4.6 服务端校验器测试

```bash
cd server
node src/smoke_test.js          # 不依赖数据库，校验 validate.js + install_script.js 全部路径
```

### 4.7 客户端打包

```powershell
cd client
python build.py                 # 等价于双击 build.bat
```

- 打包前必须先 **从 `client/local_config.example.json` 复制一份** 为 `client/local_config.preset.json`（该文件**不在仓库中**，已在 `.gitignore` 内）并填好 `server_base_url` + `client_token`，否则脚本会询问是否仍要继续打包（产物首次启动会弹引导）。若仓库已无该文件，build.py 会走「未填写确认」分支并给出明确提示，不会崩溃。
- 产物：`client/dist/HomeworkTime/HomeworkTime.exe`（onedir 单目录，便于拷贝）。

---

## 五、编码与风格规范

### 5.1 Python（客户端）

- 遵循现有 PEP 8 风格：UTF-8 头声明 `# -*- coding: utf-8 -*-`、类型注解（`from __future__ import annotations`）、`threading.RLock` 保护可变状态。
- 入口文件 `client/main.py` 与 `client/app/main.py` 是仅有的两个含 `if __name__ == "__main__":` 入口的脚本；其它模块仅暴露函数与类。
- 模块顶部 docstring 必须说明职责与关键不变量（如跨天处理、原子写、平台降级）。
- Qt 控件样式（颜色、圆角）**统一使用本项目蓝色调主题色板**（见 `docs/开发文档.md` 第六章）。不要引入与主题无关的新颜色。
- 业务配置契约修改须 **同步** `client/app/config_schema.json`、`server/src/config.schema.json`、双端 `default_config.json`、`docs/配置说明.md`、`docs/开发文档.md` 第七章。

### 5.2 JavaScript（服务端）

- Node CommonJS（`require`/`module.exports`），不使用 ESM；Vue3 前端才是 ESM。
- 路由文件统一 `try/catch + next(err)` 风格（`app.js` 全局错误中间件统一 `{error}`）。
- 所有管理员敏感操作必须 `await writeAudit(req.user.id, 'action.name', {...})`。
- 业务配置写入必须先 `validateAndMerge()`，禁止跳过校验直接落库。
- 任何外发到客户端的字段需过滤：密码哈希不出现在 `GET /api/users`、`stored_path` 不出现在 `GET /api/client/audio`。

### 5.3 Vue（前端）

- Composition API + `<script setup>`；状态用 Pinia（`useAuthStore`）。
- axios 全部走 `src/api/index.js` 封装的实例（自动注入 JWT、401 跳登录）；不要在组件里直接 `import axios`。
- 颜色 / 主题色值从 `src/styles/theme.css` 的 CSS 变量取；新增页面用既有变量，不要硬编码新颜色。
- 路由 hash 模式（`createWebHashHistory`）；新增页面在 `src/router/index.js` 注册。

### 5.4 通用

- 提交信息用中文，简洁说明变更内容与影响面。
- 修改前必看：`git status` + `git diff`（项目仓库已初始化 Git 后生效）。
- 不要把 `.env`、`local_config.json`、`cache/`、`logs/`、`uploads/`、构建产物 `dist/` 提交。

---

## 六、安全红线（绝对不可违反）

以下文件与字段 **绝不允许** 提交到 Git、绝不允许写入任何文档示例、绝不允许上传到公网：

| 类别 | 路径 / 字段 | 原因 |
|---|---|---|
| 服务端环境变量 | `server/.env`（含 `JWT_SECRET`、`DB_PASSWORD`） | 密钥与数据库密码泄露即失守 |
| 客户端本机配置 | `client/local_config.json`（含 `client_token`） | Token 泄露 = 任何人都能冒充本机心跳 |
| 客户端打包预设 | `client/local_config.preset.json`（含真实 `server_base_url` + `client_token`） | 该文件已不入库（`.gitignore`），**严禁以任何方式提交或推送到远程**；曾因本地填写真实地址后误提交导致凭据泄露 |
| 客户端运行产物 | `client/cache/`（含 `business_config.json`、`pending_updates.json`、`sounds/`） | 业务配置版本号缓存；含运行期数据 |
| 客户端日志 | `client/logs/app_*.log` | 可能包含 URL / Token 片段、心跳异常堆栈 |
| 音频上传 | `server/uploads/audio/*`（非 `.gitkeep`） | 用户上传内容 |
| 一键安装包 | `server/uploads/installs/*`（非 `.gitkeep`） | 客户端安装包二进制，与源码不同步；下载地址含 slug 凭据亦不得外传 |
| 构建产物 | `server/web/dist/`、`client/dist/`、`client/build/`、`client/HomeworkTime.spec`、`*/node_modules/` | 大体积 + 与源码不同步（`client/build/` 与 `client/HomeworkTime.spec` 为 PyInstaller 中间产物，build.py 每次构建重新生成） |

默认凭据（`admin / admin123`、`CHANGE_ME_DEFAULT_TOKEN`）**仅供演示**，任何非本地初始测试场景都必须先修改。

`.gitignore` 已覆盖以上路径，但 Agent 在写入示例、复制模板时仍须主动避开。

> **`client/local_config.preset.json` 的本机操作约定**：该文件**已从 Git 索引移除且不入库**（`.gitignore` 覆盖）。本机可保留该文件用于本地打包，但**严禁**：
> - 用 `git add client/local_config.preset.json` / `git add -f ...` 等任何方式把它加入索引；
> - 把它写进任何文档示例、问题复现片段或 PR 描述；
> - 通过聊天 / 工单 / 截图 / 日志 透传其真实内容。
> 新克隆仓库应从 `local_config.example.json` 复制一份作为模板，再在本地按需填写真实地址与 Token；提交任何变更前请用 `git status` + `git diff --cached` 复核，**不得**让该路径出现在索引里。

---

## 七、文档同步规则（**最重要，请仔细阅读**）

> **任何 Agent 对本项目做更改（新增/修改/删除功能、接口、配置、依赖、目录、部署方式、UI 主题等），都必须同步更新 `docs/` 下受影响的章节，并在 `docs/开发文档.md` 第十章「变更记录」中追加一行**，使文档始终与项目现状一致。

### 7.1 同步映射表

| 修改类型 | 同步位置 |
|---|---|
| 业务配置字段（增删/类型/约束变化） | `docs/配置说明.md` 第二章；`client/app/config_schema.json`；`server/src/config.schema.json`；`client/app/default_config.json`；`server/src/default_config.json`；`server/sql/schema.sql` 初始 `INSERT`；`docs/开发文档.md` 第七章；`docs/开发文档.md` 第十章追加一行 |
| 新增/修改/删除 API 端点 | `docs/API.md` 对应小节；`docs/开发文档.md` 第三章路由表；`docs/开发文档.md` 第十章追加一行 |
| 新增/修改/删除数据库表或字段 | `server/sql/schema.sql`；`docs/开发文档.md` 第三章数据库表结构表；`docs/开发文档.md` 第十章追加一行 |
| 环境变量新增/默认值变化 | `server/.env.example`；`docs/部署说明.md` 第二章 2.4 节；`docs/开发文档.md` 第三章环境变量表；`docs/开发文档.md` 第十章追加一行 |
| 客户端模块/启动流程/状态机调整 | `docs/开发文档.md` 第五章对应章节；`docs/开发文档.md` 第十章追加一行 |
| 管理前端路由/页面/接口封装调整 | `docs/开发文档.md` 第四章对应章节；`docs/开发文档.md` 第十章追加一行 |
| UI 主题色板变化（新增/删除色） | `server/web/src/styles/theme.css`；`docs/开发文档.md` 第六章色板表与取值规则；PyQt 各窗口 QSS 中对应硬编码同步；`docs/开发文档.md` 第十章追加一行 |
| 部署步骤调整 | `docs/部署说明.md` 对应小节；`docs/开发文档.md` 第九章命令速查；`docs/开发文档.md` 第十章追加一行 |
| 客户端依赖变化 | `client/requirements.txt`；`docs/部署说明.md` 第三章 3.1；`docs/开发文档.md` 第十章追加一行 |
| 服务端依赖变化 | `server/package.json`；`docs/部署说明.md` 第二章 2.2；`docs/开发文档.md` 第十章追加一行 |

### 7.2 变更记录格式

`docs/开发文档.md` 第十章每行格式：

```markdown
| YYYY-MM-DD | 简短变更描述（中文） | 受影响文档章节 |
```

最新条目写在表格最上方（倒序）。

### 7.3 文档同步优先级

1. **强同步**：业务配置契约、API 端点、数据库 schema、环境变量、UI 主题色板 —— 这些字段任一变化必须立即同步**全部**对应位置，不允许单边修改。
2. **弱同步**：内部实现细节（如某个函数的私有算法）若对外部行为无影响，可仅在 `docs/开发文档.md` 第五章简述，无需改动其他文档。

---

## 八、变更完成后的检查清单

提交前请逐项确认：

- [ ] 代码语法/类型检查通过（`python -m compileall client/app` / `node -c <file>`）
- [ ] 相关单元测试通过（`python -m unittest client.tests.test_*` / `node src/smoke_test.js`）
- [ ] 客户端冒烟测试通过（`python client/tests/smoke_*.py`）
- [ ] 受影响文档已同步（按第七章映射表）
- [ ] `docs/开发文档.md` 第十章「变更记录」已追加新行
- [ ] `git status` 与 `git diff` 已检查，**不含** 任何敏感文件（见第六章）
- [ ] 没有引入未在依赖文件中声明的第三方包

---

## 九、Git 约定

- 主分支：`main`
- 工作流：功能开发可在临时分支进行，最终合并到 `main`。
- 提交信息：中文，格式 `<类型>: <一句话说明>`（类型示例：新增 / 修复 / 重构 / 文档 / 测试 / 构建 / 样式）。
- 提交前必看 `git status` + `git diff`，确认改动范围符合预期。
- 严禁 `git push --force`、跳过 hooks、提交空 commit、提交包含真实凭据的 commit。
- 仓库已初始化：主分支 `main` 跟踪 `origin/main`（https://github.com/zuishuai-ziyi/HomeworkTime.git），初始化提交 `2c252f9`。日常按 `git status` → `git diff` → `git add <文件>` → `git commit` → `git push` 流程操作。
- `client/local_config.preset.json` 历史上由初始化提交（`0bae435`，即在 `2c252f9` 之后）跟踪过一次；现已通过 `git rm --cached` 从索引移除并加入 `.gitignore`。历史提交中残留的安全默认模板（`server_base_url=http://127.0.0.1:3000`、`client_token=""`）不算敏感信息，**不视为凭据泄露**，无需改写历史；若仍存疑可整体 `git filter-repo` 清理并强制同步远端（不在本规范强制范围内）。
- `client/local_config.preset.json` 已彻底**移出版本控制**（`.gitignore` 覆盖 + 从索引移除），仓库中不再保留任何版本；本地可自行从 `client/local_config.example.json` 复制创建并填写真实生产地址与 Token 用于打包。**严禁以任何方式提交或推送该文件**（详见第六章红线）。
