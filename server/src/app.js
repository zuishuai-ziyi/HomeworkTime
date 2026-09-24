/**
 * app.js — HomeworkTime 服务端入口
 *
 * 职责：
 *   - 可选加载 dotenv（未安装则直接使用 process.env）
 *   - 启动校验 JWT_SECRET（生产未配置则拒绝启动，开发仅告警）
 *   - JSON body 限制 50MB、CORS 默认全开（CORS_ORIGIN 可收紧）
 *   - 挂载 /api 后台路由（JWT）与 /api/client 客户端路由（X-Client-Token）
 *   - 可选直挂静态目录 /uploads/audio（SERVE_UPLOADS_STATIC=1 才启用，调试用；
 *     生产客户端走带鉴权的下载接口）
 *   - 全局 404 与错误处理（统一 { error: msg }）
 *   - 启动时幂等初始化默认数据（seed.ensure()）
 *   - 监听 process.env.PORT || 3000，SIGINT/SIGTERM 优雅关闭
 *
 * 注意：本服务同时托管 web/dist 前端构建产物（含 SPA 路由兜底）。
 */

// 可选加载 dotenv：未安装时跳过，直接读 process.env
try {
  require('dotenv').config();
} catch (e) {
  /* dotenv 未安装，忽略 */
}

const path = require('path');
const fs = require('fs');
const express = require('express');
const cors = require('cors');
const { pool } = require('./db');
const { ensure } = require('./utils/seed');
const { requireAuth, requireAuthOrClientToken } = require('./auth');

const authRoutes = require('./routes/auth');
const configRoutes = require('./routes/config');
const audioRoutes = require('./routes/audio');
const usersRoutes = require('./routes/users');
const tokenRoutes = require('./routes/token');
const devicesRoutes = require('./routes/devices');
const auditRoutes = require('./routes/audit');
const updatesRoutes = require('./routes/updates');
const clientRoutes = require('./routes/client');

const DEFAULT_JWT_SECRET = 'homework-time-default-secret-change-me';

/**
 * 启动时校验 JWT 密钥：
 * - 未设置或仍为默认值时：
 *   生产环境（NODE_ENV=production）打印严重错误并拒绝启动；
 *   开发/测试环境仅打印醒目警告（auth.js 保留默认值以兼容本地开发）。
 */
function assertJwtSecretConfigured() {
  const secret = process.env.JWT_SECRET;
  if (secret && secret !== DEFAULT_JWT_SECRET) return;
  const msg =
    '[security] JWT_SECRET 未设置或仍为默认值，登录 Token 可被伪造！' +
    '请立即设置环境变量 JWT_SECRET 为足够随机的长字符串。';
  if (process.env.NODE_ENV === 'production') {
    console.error(`[security][fatal] ${msg} 生产环境拒绝启动。`);
    process.exit(1);
  }
  console.warn(`[security][warn] ${msg}`);
}

const app = express();

// CORS：配置了 CORS_ORIGIN（逗号分隔白名单）时按白名单收紧，否则保持开发默认全开
const corsOrigin = process.env.CORS_ORIGIN;
app.use(corsOrigin ? cors({ origin: corsOrigin.split(',') }) : cors());
app.use(express.json({ limit: '50mb' }));

// 仅用于将 req.ip 解析为真实客户端 IP（设备监控 / 登录限速的展示与归因），不影响鉴权
app.set('trust proxy', true);

// 直挂静态音频目录仅用于本地调试：默认关闭，设置 SERVE_UPLOADS_STATIC=1 才启用。
// 生产客户端请走带鉴权的 GET /api/client/audio/:filename，勿开放静态直挂。
if (process.env.SERVE_UPLOADS_STATIC === '1') {
  app.use('/uploads/audio', express.static(path.join(__dirname, '..', 'uploads', 'audio')));
}

// ---- 后台接口（JWT 鉴权，挂载前统一套 requireAuth）----
app.use('/api/auth', authRoutes);
// /api/config 双鉴权：后台用 JWT，客户端用 X-Client-Token（离线补传/在线保存）
app.use('/api/config', requireAuthOrClientToken, configRoutes);
app.use('/api/audio', requireAuth, audioRoutes);
app.use('/api/users', requireAuth, usersRoutes);
app.use('/api/client-token', requireAuth, tokenRoutes);
app.use('/api/devices', requireAuth, devicesRoutes);
app.use('/api/audit-logs', requireAuth, auditRoutes);
app.use('/api/updates', requireAuth, updatesRoutes);

// ---- 客户端接口（路由内部已用 requireClientToken 统一鉴权）----
app.use('/api/client', clientRoutes);

// 健康检查（无鉴权，供部署探测）
app.get('/api/health', (req, res) => res.json({ ok: true, time: new Date().toISOString() }));

// /api 下的未匹配请求 → 404 JSON
app.use('/api', (req, res) => res.status(404).json({ error: '接口不存在' }));

// ---- 前端静态托管（web/dist）与 SPA 兜底 ----
// 生产部署：由本服务直接提供后台管理页面，API 与页面同源（80/SamWAF、81/Nginx 反代、3001 直连均可访问）。
// 开发环境未构建 web/dist 时跳过托管，仅提供 API（前端走 vite dev server）。
const webDistDir = path.join(__dirname, '..', 'web', 'dist');
if (fs.existsSync(path.join(webDistDir, 'index.html'))) {
  app.use(express.static(webDistDir));
  // 非文件资源且非 /api 的 GET 请求统一回退到 index.html（SPA 路由兜底）
  app.get('*', (req, res, next) => {
    if (req.path === '/api' || req.path.startsWith('/api/')) return next();
    // 仅浏览器导航类请求回退到 SPA；静态资源/接口客户端的未命中请求保留 404 语义
    if (!req.accepts('html')) return res.status(404).json({ error: '资源不存在' });
    res.sendFile(path.join(webDistDir, 'index.html'));
  });
} else {
  console.warn('[server] 未找到 web/dist 构建产物，跳过前端托管（仅提供 API）');
}

// ---- 全局错误处理：统一 { error: msg } ----
// eslint-disable-next-line no-unused-vars
app.use((err, req, res, next) => {
  console.error('[error]', err);
  if (res.headersSent) return next(err);
  // 保留 4xx 语义（如 body 解析失败 400、请求体过大 413），其余按 500 处理
  const status =
    err.status && err.status >= 400 && err.status < 600
      ? err.status
      : err.type === 'entity.too.large'
        ? 413
        : 500;
  const message = err.type === 'entity.too.large'
    ? '请求体过大'
    : (err.expose !== undefined ? err.message : (err.message || '服务器内部错误'));
  res.status(status).json({ error: message });
});

// ============ 启动与优雅关闭 ============

const PORT = parseInt(process.env.PORT || '3000', 10);

async function start() {
  // 启动前先校验 JWT 密钥（生产未配置直接退出，开发仅告警）
  assertJwtSecretConfigured();

  // 幂等初始化默认数据（无用户建 admin，无配置写默认，无 Token 写占位，无内置音频写元数据）
  await ensure();

  const server = app.listen(PORT, () => {
    console.log(`[server] HomeworkTime 服务端已启动: http://0.0.0.0:${PORT}`);
  });

  const shutdown = async (signal) => {
    console.log(`[server] 收到 ${signal}，正在优雅关闭...`);
    server.close(async () => {
      try {
        await pool.end();
      } catch (e) {
        /* 忽略 */
      }
      console.log('[server] 已关闭');
      process.exit(0);
    });
    // 兜底：10 秒内未完成关闭则强制退出
    setTimeout(() => process.exit(1), 10000).unref();
  };

  process.on('SIGINT', () => shutdown('SIGINT'));
  process.on('SIGTERM', () => shutdown('SIGTERM'));
}

// 作为入口脚本运行时启动；被 require 时只导出 app 供测试
if (require.main === module) {
  start().catch((err) => {
    console.error('[server] 启动失败:', err);
    process.exit(1);
  });
}

module.exports = app;