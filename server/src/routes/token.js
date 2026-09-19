/**
 * routes/token.js — 客户端 Token 管理（JWT 鉴权）
 *
 * GET  /api/client-token        -> { token, updated_at }
 * POST /api/client-token/reset  -> 生成新 Token；写审计日志；-> { token }
 */
const express = require('express');
const crypto = require('crypto');
const { query, pool } = require('../db');
const { writeAudit } = require('../utils/audit');

const router = express.Router();

// GET /api/client-token
router.get('/', async (req, res, next) => {
  try {
    const rows = await query('SELECT token, updated_at FROM client_token WHERE id = 1');
    if (!rows.length) return res.status(404).json({ error: '客户端 Token 未初始化' });
    res.json(rows[0]);
  } catch (err) {
    next(err);
  }
});

// POST /api/client-token/reset
router.post('/reset', async (req, res, next) => {
  try {
    const newToken = crypto.randomBytes(24).toString('hex');
    // 单行表：UPSERT 兜底，避免未初始化时插入失败
    await pool.execute(
      'INSERT INTO client_token (id, token) VALUES (1, ?) ON DUPLICATE KEY UPDATE token = VALUES(token)',
      [newToken]
    );
    await writeAudit(req.user.id, 'token.reset', {});
    res.json({ token: newToken });
  } catch (err) {
    next(err);
  }
});

module.exports = router;