/**
 * routes/audit.js — 操作日志查询（JWT 鉴权）
 *
 * GET /api/audit-logs?page=1&page_size=20 -> { total, items }
 * items 按 created_at DESC 排序，JOIN users 带出操作者用户名
 */
const express = require('express');
const { query } = require('../db');

const router = express.Router();

router.get('/', async (req, res, next) => {
  try {
    const page = Math.max(1, parseInt(req.query.page, 10) || 1);
    const pageSize = Math.min(100, Math.max(1, parseInt(req.query.page_size, 10) || 20));
    const offset = (page - 1) * pageSize;

    const [totalRow] = await query('SELECT COUNT(*) AS n FROM audit_logs');
    const total = totalRow.n;

    const rows = await query(
      `SELECT a.id, a.user_id, a.action, a.detail_json, a.created_at,
              u.username
       FROM audit_logs a
       LEFT JOIN users u ON u.id = a.user_id
       ORDER BY a.created_at DESC, a.id DESC
       LIMIT ? OFFSET ?`,
      [pageSize, offset]
    );

    res.json({ total, page, page_size: pageSize, items: rows });
  } catch (err) {
    next(err);
  }
});

module.exports = router;