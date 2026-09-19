/**
 * routes/auth.js — 登录接口
 *
 * POST /api/auth/login  { username, password } -> { token, username }
 *
 * 安全：按 IP 每分钟最多 10 次登录尝试的内存限速（固定窗口）。
 * Map 仅在写入时惰性清理过期项，避免长期运行导致内存增长。
 */
const express = require('express');
const bcrypt = require('bcryptjs');
const { query } = require('../db');
const { signToken } = require('../auth');

const router = express.Router();

// ---- 登录限速（按 IP，每分钟最多 10 次登录尝试）----
const LOGIN_LIMIT_PER_MINUTE = 10;
const LOGIN_WINDOW_MS = 60 * 1000;
// 惰性清理：距上次清理超过 5 分钟时，删除超过 1 个窗口未访问的记录
const LOGIN_CLEANUP_MS = 5 * 60 * 1000;
const loginAttempts = new Map(); // key=ip, value={ count, windowStart }
let lastLoginCleanup = 0;

/** 取客户端真实 IP（trust proxy 已开启；取不到时回退 socket 地址） */
function clientIp(req) {
  const ip = req.ip || (req.socket && req.socket.remoteAddress) || 'unknown';
  // 剥离 IPv6 映射前缀 ::ffff:，保证 v4/v6 形式一致
  return String(ip).replace(/^::ffff:/, '');
}

/** 尝试记账；返回 true 表示已超限应拒绝（返回 429） */
function isLoginRateLimited(ip, now) {
  // 惰性清理过期记录（防内存泄漏）
  if (now - lastLoginCleanup > LOGIN_CLEANUP_MS) {
    for (const [key, rec] of loginAttempts) {
      if (now - rec.windowStart >= LOGIN_CLEANUP_MS) loginAttempts.delete(key);
    }
    lastLoginCleanup = now;
  }
  const rec = loginAttempts.get(ip);
  if (!rec || now - rec.windowStart >= LOGIN_WINDOW_MS) {
    // 首次尝试或窗口已过期 → 重新开窗
    loginAttempts.set(ip, { count: 1, windowStart: now });
    return false;
  }
  rec.count += 1;
  return rec.count > LOGIN_LIMIT_PER_MINUTE;
}

router.post('/login', async (req, res, next) => {
  try {
    if (isLoginRateLimited(clientIp(req), Date.now())) {
      return res.status(429).json({ error: '尝试过于频繁，请稍后再试' });
    }
    const { username, password } = req.body || {};
    if (!username || !password) {
      return res.status(400).json({ error: '用户名和密码不能为空' });
    }
    const rows = await query(
      'SELECT `id`, `username`, `password_hash` FROM `users` WHERE `username` = ? LIMIT 1',
      [username]
    );
    if (!rows.length) {
      return res.status(401).json({ error: '用户名或密码错误' });
    }
    const user = rows[0];
    const matched = await bcrypt.compare(password, user.password_hash);
    if (!matched) {
      return res.status(401).json({ error: '用户名或密码错误' });
    }
    // 签发 JWT（12h 过期）
    const token = signToken({ id: user.id, username: user.username });
    res.json({ token, username: user.username });
  } catch (err) {
    next(err);
  }
});

module.exports = router;