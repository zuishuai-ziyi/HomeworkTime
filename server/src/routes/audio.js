/**
 * routes/audio.js — 音频管理（JWT 鉴权）
 *
 * GET    /api/audio        -> { total, items } 列表（含 is_builtin / size / sha256 / uploaded_by / created_at）
 * POST   /api/audio        multer 磁盘存储到 uploads/audio/，仅允许 .wav，大小不限；
 *                          同名覆盖（更新记录并覆盖物理文件；内置行被覆盖时保留 is_builtin=1 不可删）
 * DELETE /api/audio/:id    内置音频拒绝删除（400）；否则删除记录 + 物理文件；写审计日志
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
const UPLOAD_DIR = path.join(SERVER_ROOT, 'uploads', 'audio');

/** 文件名安全字符白名单（防路径穿越与非法字符） */
const SAFE_NAME_RE = /^[A-Za-z0-9._-]+$/;
const WAV_EXT_RE = /\.wav$/i;

/** 净化原始文件名：剔除路径部分，只保留安全基名 */
function sanitizeFilename(original) {
  const base = path.basename(original || '');
  if (!SAFE_NAME_RE.test(base)) return '';
  return base;
}

/** 计算文件 sha256（十六进制） */
function computeSha256(filePath) {
  return new Promise((resolve, reject) => {
    const hash = crypto.createHash('sha256');
    const stream = fs.createReadStream(filePath);
    stream.on('data', (chunk) => hash.update(chunk));
    stream.on('end', () => resolve(hash.digest('hex')));
    stream.on('error', reject);
  });
}

// multer 配置：磁盘存储，原始文件名（同名自动覆盖），仅 .wav
// limits.fileSize：100MB 上限防磁盘被填满（业务上不限制时长/大小，但需防护）
const MAX_UPLOAD_BYTES = 100 * 1024 * 1024;
const upload = multer({
  storage: multer.diskStorage({
    destination: (req, file, cb) => cb(null, UPLOAD_DIR),
    filename: (req, file, cb) => {
      const name = sanitizeFilename(file.originalname);
      if (!name) return cb(new Error('文件名包含非法字符，仅允许字母、数字、_、-、.'));
      cb(null, name);
    }
  }),
  limits: { fileSize: MAX_UPLOAD_BYTES },
  fileFilter: (req, file, cb) => {
    const extOk = WAV_EXT_RE.test(file.originalname || '');
    const safe = sanitizeFilename(file.originalname) !== '';
    if (!extOk || !safe) {
      // 传入普通 Error（而非 MulterError），统一映射为 400
      return cb(new Error('仅允许上传 .wav 文件'));
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
              ? '文件超过 100MB 上传上限'
              : `上传失败: ${err.message}`;
          return res.status(400).json({ error: msg });
        }
        return res.status(400).json({ error: err.message || '上传失败' });
      }
      next();
    });
  };
}

// GET /api/audio
router.get('/', async (req, res, next) => {
  try {
    const rows = await query(
      `SELECT f.id, f.filename, f.stored_path, f.size, f.sha256, f.is_builtin, f.created_at,
              u.username AS uploaded_by
       FROM audio_files f
       LEFT JOIN users u ON u.id = f.uploaded_by
       ORDER BY f.is_builtin DESC, f.id ASC`
    );
    const items = rows.map((r) => ({
      id: r.id,
      filename: r.filename,
      size: r.size,
      sha256: r.sha256,
      is_builtin: !!r.is_builtin,
      created_at: r.created_at,
      uploaded_by: r.uploaded_by
    }));
    res.json({ total: items.length, items });
  } catch (err) {
    next(err);
  }
});

// POST /api/audio（上传）
router.post('/', uploadSingle('file'), async (req, res, next) => {
  try {
    if (!req.file) {
      return res.status(400).json({ error: '缺少上传文件（字段名应为 file）' });
    }
    const filename = req.file.filename;
    const absPath = req.file.path;
    const size = req.file.size;
    const sha256 = await computeSha256(absPath);
    // stored_path 存相对 server 根目录的路径（正斜杠），便于跨平台解析
    const storedPath = path.relative(SERVER_ROOT, absPath).split(path.sep).join('/');

    // 同名覆盖策略：INSERT 冲突时更新记录并覆盖物理文件
    // （若冲突行是内置音频，is_builtin 保持不变，仍不可删除，
    //   但补上 stored_path/size/sha256，使客户端可从服务端下载到真实文件）
    await pool.execute(
      `INSERT INTO audio_files (filename, stored_path, size, sha256, is_builtin, uploaded_by)
       VALUES (?, ?, ?, ?, 0, ?)
       ON DUPLICATE KEY UPDATE
         stored_path = VALUES(stored_path),
         size = VALUES(size),
         sha256 = VALUES(sha256),
         uploaded_by = VALUES(uploaded_by)`,
      [filename, storedPath, size, sha256, req.user.id]
    );

    await writeAudit(req.user.id, 'audio.upload', { filename, size, sha256 });

    const rows = await query('SELECT * FROM audio_files WHERE filename = ?', [filename]);
    const row = rows[0];
    res.json({
      id: row.id,
      filename: row.filename,
      size: row.size,
      sha256: row.sha256,
      is_builtin: !!row.is_builtin,
      created_at: row.created_at
    });
  } catch (err) {
    next(err);
  }
});

// DELETE /api/audio/:id
router.delete('/:id', async (req, res, next) => {
  try {
    const id = parseInt(req.params.id, 10);
    if (!Number.isInteger(id) || id <= 0) {
      return res.status(400).json({ error: '非法 id' });
    }
    const rows = await query('SELECT * FROM audio_files WHERE id = ?', [id]);
    if (!rows.length) {
      return res.status(404).json({ error: '音频记录不存在' });
    }
    const file = rows[0];
    if (Number(file.is_builtin) === 1) {
      return res.status(400).json({ error: '内置音频不可删除' });
    }

    await pool.execute('DELETE FROM audio_files WHERE id = ?', [id]);

    // 删除物理文件（失败不阻塞，仅记录）
    if (file.stored_path) {
      const absPath = path.resolve(SERVER_ROOT, file.stored_path);
      await fs.promises.unlink(absPath).catch((e) => {
        console.error('[audio] 删除物理文件失败:', e.message);
      });
    }

    await writeAudit(req.user.id, 'audio.delete', { id, filename: file.filename, size: file.size });
    res.json({ ok: true });
  } catch (err) {
    next(err);
  }
});

module.exports = router;