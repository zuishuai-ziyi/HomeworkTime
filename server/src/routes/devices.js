/**
 * routes/devices.js — 设备在线监控（JWT 鉴权）
 *
 * GET /api/devices       -> 设备列表，online 字段：last_heartbeat 距今 <= 30s 视为在线
 * PUT /api/devices/:id   body { room_name } -> 修改教室名；写审计日志 action='device.rename'
 */
const express = require('express');
const { query, pool } = require('../db');
const { writeAudit } = require('../utils/audit');

const router = express.Router();

router.get('/', async (req, res, next) => {
  try {
    const rows = await query(
      `SELECT id, device_uuid, device_name, room_name, ip, client_version,
              update_pending_version,
              last_heartbeat, last_config_version, created_at, updated_at,
              TIMESTAMPDIFF(SECOND, last_heartbeat, NOW()) <= 30 AS online
       FROM devices
       ORDER BY last_heartbeat IS NULL ASC, last_heartbeat DESC, id DESC`
    );
    const items = rows.map((r) => ({ ...r, online: !!r.online }));
    res.json({ total: items.length, items });
  } catch (err) {
    next(err);
  }
});

// PUT /api/devices/:id（后台改教室名；body: { room_name }）
router.put('/:id', async (req, res, next) => {
  try {
    const id = parseInt(req.params.id, 10);
    if (!Number.isInteger(id) || id <= 0) {
      return res.status(400).json({ error: '非法 id' });
    }

    const { room_name } = req.body || {};
    if (room_name === undefined) {
      return res.status(400).json({ error: '请求体必须包含 room_name 字段' });
    }

    // null 表示清空教室名；否则必须是长度不超过 128 的字符串
    let rn = null;
    if (room_name !== null) {
      if (typeof room_name !== 'string') {
        return res.status(400).json({ error: 'room_name 必须为字符串' });
      }
      rn = room_name.trim();
      if (rn.length > 128) {
        return res.status(400).json({ error: 'room_name 长度不能超过 128 字符' });
      }
    }

    const rows = await query(
      'SELECT id, device_uuid, device_name, room_name FROM devices WHERE id = ?',
      [id]
    );
    if (!rows.length) {
      return res.status(404).json({ error: '设备不存在' });
    }

    await pool.execute('UPDATE devices SET room_name = ? WHERE id = ?', [rn, id]);

    await writeAudit(req.user.id, 'device.rename', {
      id,
      device_uuid: rows[0].device_uuid,
      room_name: rn
    });

    res.json({ id, room_name: rn });
  } catch (err) {
    next(err);
  }
});

module.exports = router;