/**
 * routes/users.js — 后台用户管理（JWT 鉴权）
 *
 * GET    /api/users        列表（不含 password_hash）
 * POST   /api/users        { username, password } 创建（bcrypt 10 轮，用户名唯一，重复 409）
 * PUT    /api/users/:id    { username?, password? } 改用户名或密码
 * DELETE /api/users/:id    不能删除自己（400）；不能删除最后一个用户（400）；写审计日志
 */
const express = require('express');
const bcrypt = require('bcryptjs');
const { query, pool } = require('../db');
const { writeAudit } = require('../utils/audit');

const router = express.Router();

/** 检查用户名是否已存在（可选排除指定 id） */
async function usernameExists(username, excludeId) {
  const rows = excludeId
    ? await query('SELECT id FROM users WHERE username = ? AND id <> ? LIMIT 1', [username, excludeId])
    : await query('SELECT id FROM users WHERE username = ? LIMIT 1', [username]);
  return rows.length > 0;
}

// GET /api/users
router.get('/', async (req, res, next) => {
  try {
    const rows = await query(
      'SELECT id, username, created_at, updated_at FROM users ORDER BY id ASC'
    );
    res.json({ total: rows.length, items: rows });
  } catch (err) {
    next(err);
  }
});

// POST /api/users
router.post('/', async (req, res, next) => {
  try {
    const { username, password } = req.body || {};
    if (!username || !password) {
      return res.status(400).json({ error: '用户名和密码不能为空' });
    }
    if (password.length < 6) {
      return res.status(400).json({ error: '密码长度至少 6 位' });
    }
    if (await usernameExists(username)) {
      return res.status(409).json({ error: '用户名已存在' });
    }
    const hash = await bcrypt.hash(password, 10);
    const [r] = await pool.execute(
      'INSERT INTO users (username, password_hash) VALUES (?, ?)',
      [username, hash]
    );
    await writeAudit(req.user.id, 'user.create', { id: r.insertId, username });
    res.status(201).json({ id: r.insertId, username });
  } catch (err) {
    next(err);
  }
});

// PUT /api/users/:id
router.put('/:id', async (req, res, next) => {
  try {
    const id = parseInt(req.params.id, 10);
    if (!Number.isInteger(id) || id <= 0) return res.status(400).json({ error: '非法 id' });

    const rows = await query('SELECT id, username FROM users WHERE id = ?', [id]);
    if (!rows.length) return res.status(404).json({ error: '用户不存在' });

    const { username, password } = req.body || {};
    const updates = [];
    const params = [];

    if (username !== undefined) {
      const u = String(username).trim();
      if (!u) return res.status(400).json({ error: '用户名不能为空' });
      if (await usernameExists(u, id)) return res.status(409).json({ error: '用户名已存在' });
      updates.push('username = ?');
      params.push(u);
    }
    if (password !== undefined) {
      if (typeof password !== 'string' || password.length < 6) {
        return res.status(400).json({ error: '密码长度至少 6 位' });
      }
      const hash = await bcrypt.hash(password, 10);
      updates.push('password_hash = ?');
      params.push(hash);
    }
    if (!updates.length) {
      return res.status(400).json({ error: '未提供需要修改的字段（username 或 password）' });
    }

    params.push(id);
    await pool.execute(`UPDATE users SET ${updates.join(', ')} WHERE id = ?`, params);

    const newUsername = username !== undefined ? String(username).trim() : rows[0].username;
    await writeAudit(req.user.id, 'user.update', { id, username: newUsername, changed: updates });
    res.json({ id, username: newUsername });
  } catch (err) {
    next(err);
  }
});

// DELETE /api/users/:id
router.delete('/:id', async (req, res, next) => {
  try {
    const id = parseInt(req.params.id, 10);
    if (!Number.isInteger(id) || id <= 0) return res.status(400).json({ error: '非法 id' });

    if (id === req.user.id) {
      return res.status(400).json({ error: '不能删除自己（当前登录账号）' });
    }

    const rows = await query('SELECT id, username FROM users WHERE id = ?', [id]);
    if (!rows.length) return res.status(404).json({ error: '用户不存在' });

    const [cnt] = await pool.execute('SELECT COUNT(*) AS n FROM users');
    if (Number(cnt[0].n) <= 1) {
      return res.status(400).json({ error: '不能删除最后一个用户' });
    }

    await pool.execute('DELETE FROM users WHERE id = ?', [id]);
    await writeAudit(req.user.id, 'user.delete', { id, username: rows[0].username });
    res.json({ ok: true });
  } catch (err) {
    next(err);
  }
});

module.exports = router;