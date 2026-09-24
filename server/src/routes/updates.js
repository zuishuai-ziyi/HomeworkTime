/**
 * routes/updates.js — 客户端全量更新包管理（JWT 鉴权）
 *
 * POST /api/updates/upload                    multipart { file, version?, notes?, effective_time? }
 *   -> 上传 zip 全量更新包并立即发布（单行表 client_update 仅保留最新一个包，
 *      旧包物理文件随后删除；回滚 = 重新上传旧包）。effective_time 为空表示立即生效。
 * GET  /api/updates/current                   -> { item }（当前已发布版本；未发布过则 item=null，
 *      不含 stored_path 敏感字段）
 * PUT  /api/updates/current/effective-time    body { effective_time }
 *   -> 修改当前版本的生效时间（发布后调整客户端到点时刻）
 *
 * 更新包约定：PyInstaller onedir 整目录压缩的 zip，根级为 HomeworkTime.exe
 * 与 _internal/ 等（由 client/build.py 自动产出，内含 update_manifest.json）。
 * version 字段应与包内 update_manifest.json 的 version 一致（前端从文件名预填）。
 */
const express = require('express');
const path = require('path');
const fs = require('fs');
const crypto = require('crypto');
const multer = require('multer');
const { query, pool } = require('../db');
const { writeAudit } = require('../utils/audit');

const router = express.Router();

const SERVER_ROOT = path.join(__dirname, '..', '..');
const UPLOAD_DIR = path.join(SERVER_ROOT, 'uploads', 'updates');

/** 版本号白名单：字母数字开头，可含 . + -，长度 1-32 */
const VERSION_RE = /^[0-9A-Za-z][0-9A-Za-z.+-]{0,31}$/;
/** 从 zip 文件名提取版本号：HomeworkTime_1.2.0.zip / HomeworkTime_1.2.0-beta.zip */
const FILENAME_VERSION_RE = /_([0-9]+\.[0-9]+\.[0-9]+(?:[-+][0-9A-Za-z.+-]+)?)\.zip$/i;
/** 接受的日期时间格式：YYYY-MM-DD HH:mm[:ss] 或 ISO T 分隔 */
const DATETIME_RE = /^(\d{4})-(\d{2})-(\d{2})[ T](\d{2}):(\d{2})(?::(\d{2}))?$/;

/** 更新包大小上限：500MB（PyInstaller onedir zip 通常 40-100MB，留足余量） */
const MAX_UPLOAD_BYTES = 500 * 1024 * 1024;

/**
 * 归一化日期时间字符串为 MySQL DATETIME 格式（YYYY-MM-DD HH:MM:SS）。
 * 非法输入返回空串（由调用方决定 400）。
 */
function normalizeDateTime(input) {
  if (typeof input !== 'string') return '';
  const m = DATETIME_RE.exec(input.trim());
  if (!m) return '';
  const [, y, mo, d, h, mi, s] = m;
  const mon = Number(mo), day = Number(d);
  const hh = Number(h), mm = Number(mi), ss = Number(s || 0);
  if (mon < 1 || mon > 12 || day < 1 || day > 31 || hh > 23 || mm > 59 || ss > 59) return '';
  return `${y}-${mo}-${d} ${h}:${mi}:${s || '00'}`;
}

/** 计算文件 sha256（十六进制，流式） */
function computeSha256(filePath) {
  return new Promise((resolve, reject) => {
    const hash = crypto.createHash('sha256');
    const stream = fs.createReadStream(filePath);
    stream.on('data', (chunk) => hash.update(chunk));
    stream.on('end', () => resolve(hash.digest('hex')));
    stream.on('error', reject);
  });
}

/** 行数据 → 对外 item（剥离 stored_path，日期格式化） */
function toItem(row, uploader) {
  if (!row) return null;
  return {
    id: row.id,
    version: row.version,
    notes: row.notes,
    size: row.size === null || row.size === undefined ? null : Number(row.size),
    sha256: row.sha256,
    effective_time: row.effective_time,
    published_at: row.published_at,
    uploaded_by: uploader || null
  };
}

// multer 配置：磁盘存储到 uploads/updates/，文件名 = HomeworkTime_<version>_<时间戳>.zip
const upload = multer({
  storage: multer.diskStorage({
    destination: (req, file, cb) => cb(null, UPLOAD_DIR),
    filename: (req, file, cb) => {
      const base = path.basename(file.originalname || '');
      if (!/^[A-Za-z0-9._-]+$/.test(base)) {
        return cb(new Error('文件名包含非法字符，仅允许字母、数字、_、-、.'));
      }
      // 版本号在 fileFilter 阶段尚不可用（text 字段可能晚于文件到达），
      // 这里先用原始基名落盘，写库前统一 rename 为规范名
      cb(null, `tmp_${Date.now()}_${base}`);
    }
  }),
  limits: { fileSize: MAX_UPLOAD_BYTES },
  fileFilter: (req, file, cb) => {
    if (!/\.zip$/i.test(file.originalname || '')) {
      return cb(new Error('仅允许上传 .zip 更新包'));
    }
    cb(null, true);
  }
});

/** multer 包装：捕获上传错误转为 400 JSON */
function uploadSingle(field) {
  return (req, res, next) => {
    upload.single(field)(req, res, (err) => {
      if (err) {
        if (err instanceof multer.MulterError) {
          const msg =
            err.code === 'LIMIT_FILE_SIZE'
              ? '更新包超过 500MB 上传上限'
              : `上传失败: ${err.message}`;
          return res.status(400).json({ error: msg });
        }
        return res.status(400).json({ error: err.message || '上传失败' });
      }
      next();
    });
  };
}

// POST /api/updates/upload（上传并发布）
router.post('/upload', uploadSingle('file'), async (req, res, next) => {
  let absPath = null;
  try {
    if (!req.file) {
      return res.status(400).json({ error: '缺少上传文件（字段名应为 file）' });
    }
    absPath = req.file.path;

    // 版本号：表单显式填写优先，否则从文件名提取
    const body = req.body || {};
    let version = String(body.version || '').trim();
    if (!version) {
      const m = FILENAME_VERSION_RE.exec(path.basename(req.file.originalname || ''));
      if (m) version = m[1];
    }
    if (!VERSION_RE.test(version)) {
      return res.status(400).json({
        error: '版本号非法（字母数字开头，可含 . + -，长度 1-32），请与包内 update_manifest.json 一致'
      });
    }

    // 更新说明（可选，<=500 字符）
    let notes = null;
    if (body.notes !== undefined && body.notes !== null && String(body.notes).trim() !== '') {
      notes = String(body.notes).trim().slice(0, 500);
    }

    // 生效时间：空 = 立即生效（当前时间）
    let effectiveTime;
    if (body.effective_time === undefined || body.effective_time === null || String(body.effective_time).trim() === '') {
      effectiveTime = null; // 写库时取 NOW()
    } else {
      effectiveTime = normalizeDateTime(String(body.effective_time));
      if (!effectiveTime) {
        return res.status(400).json({ error: '生效时间格式非法，应为 YYYY-MM-DD HH:mm' });
      }
    }

    const sha256 = await computeSha256(absPath);
    const size = req.file.size;

    // 规范化落盘文件名（含版本与时间戳，防覆盖）
    const stamp = new Date()
      .toISOString()
      .replace(/[-:T]/g, '')
      .slice(0, 14);
    const finalName = `HomeworkTime_${version}_${stamp}.zip`;
    const finalPath = path.join(UPLOAD_DIR, finalName);
    await fs.promises.rename(absPath, finalPath);
    absPath = finalPath;
    const storedPath = path.relative(SERVER_ROOT, finalPath).split(path.sep).join('/');

    // 旧版本信息（用于删除旧物理文件）
    const oldRows = await query('SELECT `stored_path` FROM `client_update` WHERE `id` = 1');
    const oldStoredPath = oldRows.length ? oldRows[0].stored_path : null;

    // 单行 upsert：id 固定 1，仅保留最新一个包
    await pool.execute(
      `INSERT INTO client_update
         (id, version, notes, stored_path, size, sha256, effective_time, published_at, uploaded_by)
       VALUES (1, ?, ?, ?, ?, ?, COALESCE(?, NOW()), NOW(), ?)
       ON DUPLICATE KEY UPDATE
         version = VALUES(version),
         notes = VALUES(notes),
         stored_path = VALUES(stored_path),
         size = VALUES(size),
         sha256 = VALUES(sha256),
         effective_time = VALUES(effective_time),
         published_at = NOW(),
         uploaded_by = VALUES(uploaded_by)`,
      [version, notes, storedPath, size, sha256, effectiveTime, req.user.id]
    );

    // 删除旧包物理文件（失败不阻塞，仅记录）
    if (oldStoredPath && oldStoredPath !== storedPath) {
      const oldAbs = path.resolve(SERVER_ROOT, oldStoredPath);
      await fs.promises.unlink(oldAbs).catch((e) => {
        console.error('[updates] 删除旧更新包失败:', e.message);
      });
    }

    await writeAudit(req.user.id, 'update.upload', {
      version,
      size,
      sha256,
      effective_time: effectiveTime || '(立即生效)'
    });

    const rows = await query(
      `SELECT c.id, c.version, c.notes, c.size, c.sha256,
              DATE_FORMAT(c.effective_time, '%Y-%m-%d %H:%i:%s') AS effective_time,
              DATE_FORMAT(c.published_at, '%Y-%m-%d %H:%i:%s') AS published_at,
              u.username AS uploaded_by
       FROM client_update c LEFT JOIN users u ON u.id = c.uploaded_by
       WHERE c.id = 1`
    );
    res.json({ item: toItem(rows[0], rows[0] && rows[0].uploaded_by) });
  } catch (err) {
    // 失败时清理已落盘的临时文件，避免残留
    if (absPath) {
      await fs.promises.unlink(absPath).catch(() => {});
    }
    next(err);
  }
});

// GET /api/updates/current（当前已发布版本）
router.get('/current', async (req, res, next) => {
  try {
    const rows = await query(
      `SELECT c.id, c.version, c.notes, c.size, c.sha256,
              DATE_FORMAT(c.effective_time, '%Y-%m-%d %H:%i:%s') AS effective_time,
              DATE_FORMAT(c.published_at, '%Y-%m-%d %H:%i:%s') AS published_at,
              u.username AS uploaded_by
       FROM client_update c LEFT JOIN users u ON u.id = c.uploaded_by
       WHERE c.id = 1`
    );
    res.json({ item: rows.length ? toItem(rows[0], rows[0].uploaded_by) : null });
  } catch (err) {
    next(err);
  }
});

// PUT /api/updates/current/effective-time（修改生效时间）
router.put('/current/effective-time', async (req, res, next) => {
  try {
    const effectiveTime = normalizeDateTime(String((req.body || {}).effective_time || ''));
    if (!effectiveTime) {
      return res.status(400).json({ error: '生效时间格式非法，应为 YYYY-MM-DD HH:mm' });
    }
    const rows = await query('SELECT `id`, `version` FROM `client_update` WHERE `id` = 1');
    if (!rows.length) {
      return res.status(404).json({ error: '尚未发布过更新包' });
    }
    await pool.execute('UPDATE `client_update` SET `effective_time` = ? WHERE `id` = 1', [effectiveTime]);
    await writeAudit(req.user.id, 'update.effective_time', {
      version: rows[0].version,
      effective_time: effectiveTime
    });
    res.json({ ok: true, effective_time: effectiveTime });
  } catch (err) {
    next(err);
  }
});

module.exports = router;
