/**
 * routes/client.js — 客户端专用接口（全部 requireClientToken 鉴权）
 *
 * GET  /api/client/config          -> { version, config }（业务配置 + 版本号）
 * POST /api/client/heartbeat       body { device_uuid, device_name, client_version, config_version }
 *                                   -> 设备 upsert，响应 { version }（当前配置版本，供客户端判断是否需拉取）
 * GET  /api/client/audio           -> [{ filename, sha256, size, is_builtin }]（按 filename 排序，
 *                                     供客户端按 sha256 比对后按需下载）
 * GET  /api/client/audio/:filename -> 音频二进制流（仅返回服务端存在物理文件的记录）
 */
const express = require('express');
const path = require('path');
const { query, pool } = require('../db');
const { requireClientToken } = require('../auth');

const router = express.Router();
router.use(requireClientToken);

const SERVER_ROOT = path.join(__dirname, '..', '..');

// GET /api/client/config
router.get('/config', async (req, res, next) => {
  try {
    const rows = await query('SELECT `content_json`, `version` FROM `config` WHERE `id` = 1');
    if (!rows.length) return res.status(404).json({ error: '配置不存在' });
    res.json({ version: rows[0].version, config: rows[0].content_json });
  } catch (err) {
    next(err);
  }
});

// POST /api/client/heartbeat
router.post('/heartbeat', async (req, res, next) => {
  try {
    const { device_uuid, device_name, client_version, config_version } = req.body || {};
    if (!device_uuid) {
      return res.status(400).json({ error: 'device_uuid 不能为空' });
    }
    // 设备 upsert：按 device_uuid 唯一键，刷新名称/IP/版本/心跳时间/在客户端配置版本
    await pool.execute(
      `INSERT INTO devices
         (device_uuid, device_name, ip, client_version, last_heartbeat, last_config_version)
       VALUES (?, ?, ?, ?, NOW(), ?)
       ON DUPLICATE KEY UPDATE
         device_name = VALUES(device_name),
         ip = VALUES(ip),
         client_version = VALUES(client_version),
         last_heartbeat = NOW(),
         last_config_version = VALUES(last_config_version)`,
      [
        device_uuid,
        device_name || null,
        req.ip || null,
        client_version || null,
        config_version || null
      ]
    );

    // 返回当前配置版本，客户端可据此判断是否拉取更新
    const cfg = await query('SELECT `version` FROM `config` WHERE `id` = 1');
    res.json({ version: cfg.length ? cfg[0].version : 1 });
  } catch (err) {
    next(err);
  }
});

// GET /api/client/audio（音频文件列表，供客户端按 sha256 比对后按需下载）
router.get('/audio', async (req, res, next) => {
  try {
    const rows = await query(
      `SELECT filename, size, sha256, is_builtin
       FROM audio_files
       ORDER BY filename ASC`
    );
    const items = rows.map((r) => ({
      filename: r.filename,
      size: r.size === null || r.size === undefined ? null : Number(r.size),
      sha256: r.sha256 || null,
      is_builtin: !!r.is_builtin
    }));
    res.json(items);
  } catch (err) {
    next(err);
  }
});

// GET /api/client/audio/:filename
router.get('/audio/:filename', async (req, res, next) => {
  try {
    const filename = req.params.filename;
    // 安全过滤：仅允许字母数字 _ - . 组成的文件名，防路径穿越
    if (!/^[A-Za-z0-9._-]+$/.test(filename)) {
      return res.status(400).json({ error: '非法文件名' });
    }
    // 仅返回服务端存在物理文件的音频（stored_path 非空；纯内置行 stored_path 为 NULL 不在此列）
    const rows = await query(
      'SELECT `stored_path` FROM `audio_files` WHERE `filename` = ? AND `stored_path` IS NOT NULL LIMIT 1',
      [filename]
    );
    if (!rows.length) {
      return res.status(404).json({ error: '音频不存在' });
    }
    const absPath = path.resolve(SERVER_ROOT, rows[0].stored_path);
    res.sendFile(absPath, (err) => {
      if (!err) return;
      if (err.code === 'ENOENT') {
        if (!res.headersSent) return res.status(404).json({ error: '音频文件不存在' });
        return res.end();
      }
      next(err);
    });
  } catch (err) {
    next(err);
  }
});

module.exports = router;