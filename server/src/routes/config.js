/**
 * routes/config.js — 业务配置读写（JWT 或 X-Client-Token 双鉴权）
 *
 * GET /api/config  -> { version, config, updated_at, updated_by }
 * PUT /api/config  body { config } -> 校验通过则 version+1、更新 updated_by、写审计日志。
 *   鉴权说明：后台使用 JWT（req.user 有值）；客户端使用 X-Client-Token
 *   （req.user 为 null、req.clientAuth=true），用于在线保存与离线补传。
 */
const express = require('express');
const { query, pool } = require('../db');
const { validateAndMerge } = require('../utils/validate');
const { writeAudit } = require('../utils/audit');

const router = express.Router();

/** 读取配置单行（id 固定为 1） */
async function getConfigRow() {
  const rows = await query(
    'SELECT `content_json`, `version`, `updated_at`, `updated_by` FROM `config` WHERE `id` = 1'
  );
  return rows.length ? rows[0] : null;
}

// GET /api/config
router.get('/', async (req, res, next) => {
  try {
    const row = await getConfigRow();
    if (!row) return res.status(404).json({ error: '配置不存在（请先执行 schema.sql 或让 seed 初始化）' });
    res.json({
      version: row.version,
      config: row.content_json,
      updated_at: row.updated_at,
      updated_by: row.updated_by
    });
  } catch (err) {
    next(err);
  }
});

// PUT /api/config
router.put('/', async (req, res, next) => {
  try {
    const { config } = req.body || {};
    if (config === undefined) {
      return res.status(400).json({ error: '请求体必须包含 config 字段' });
    }

    // 校验 + 合并默认值（缺失字段自动填充）
    const result = validateAndMerge(config);
    if (!result.ok) {
      return res.status(400).json({ error: '配置校验失败', errors: result.errors });
    }

    // 读取旧版本号用于审计
    const oldRow = await getConfigRow();
    if (!oldRow) return res.status(404).json({ error: '配置不存在（请先执行 schema.sql 或让 seed 初始化）' });

    // 版本号 +1，记录修改人（客户端 X-Client-Token 身份时为 null）
    await pool.execute(
      'UPDATE `config` SET `content_json` = ?, `version` = `version` + 1, `updated_by` = ? WHERE `id` = 1',
      [JSON.stringify(result.merged), req.user ? req.user.id : null]
    );

    // 审计：记录变更后的版本与发生变化的顶层字段
    const changedKeys = Object.keys(result.merged).filter(
      (k) => JSON.stringify(oldRow.content_json[k]) !== JSON.stringify(result.merged[k])
    );
    await writeAudit(req.user ? req.user.id : null, 'config.update', {
      version: oldRow.version + 1,
      changed_keys: changedKeys,
      source: req.clientAuth ? 'client' : 'admin'
    });

    const row = await getConfigRow();
    res.json({
      version: row.version,
      config: row.content_json,
      updated_at: row.updated_at,
      updated_by: row.updated_by
    });
  } catch (err) {
    next(err);
  }
});

module.exports = router;