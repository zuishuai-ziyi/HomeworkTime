/**
 * routes/installs.js — 客户端一键安装（管理端 JWT + 公开 slug 下载双路由）
 *
 * 管理端（挂载于 /api/installs，外部套 requireAuth）：
 *   POST   /api/installs                 multipart { file, version?, notes?,
 *                                        install_dir?, client_base_url?, embed_config? }
 *                                        -> 上传客户端 zip 并创建安装入口（生成随机 slug）
 *   GET    /api/installs                 -> { total, items }（含派生 script_url / command）
 *   PATCH  /api/installs/:id             body { version?, notes?, install_dir?,
 *                                        client_base_url?, embed_config?, enabled? }
 *   DELETE /api/installs/:id             -> 删除记录与物理文件
 *   POST   /api/installs/:id/shortlink   body { sink_url?, sink_api_key?, slug? }
 *                                        -> 调 Sink /api/link/upsert 生成短链，
 *                                           返回 { short_url, command }
 *                                           （地址/Key 缺省时回退 sink_settings 已保存配置）
 *   GET    /api/installs/sink-settings   -> 已保存 Sink 配置（Key 仅回传脱敏形式）
 *                                           { sink_url, api_key_set, api_key_masked, updated_at }
 *   PUT    /api/installs/sink-settings   body { sink_url, api_key? }
 *                                        -> 保存 Sink 配置（api_key 留空 = 保持已保存 Key），
 *                                           写审计 install.sink.save（不记录 Key 值）
 *
 * 公开接口（挂载于 /api/install，无登录态，随机 slug 即访问凭据）：
 *   GET /api/install/s/:slug          -> PowerShell 安装脚本文本（text/plain）
 *   GET /api/install/s/:slug/package  -> 安装包 zip 二进制流（计数 download_count）
 *
 * 安装包约定与更新包同构：PyInstaller onedir 整目录压缩的 zip（client/build.py
 * 产物 dist/HomeworkTime_<版本>.zip 可直接复用），脚本解压后按根级或一层子目录
 * 定位 HomeworkTime.exe。
 */
const express = require('express');
const path = require('path');
const fs = require('fs');
const crypto = require('crypto');
const multer = require('multer');
const { query, pool } = require('../db');
const { writeAudit } = require('../utils/audit');
const {
  normalizeClientBaseUrl,
  normalizeInstallDir,
  isValidSlug,
  isValidSinkSlug,
  parseSinkUrl,
  maskApiKey,
  buildScriptUrl,
  buildInstallCommand,
  buildInstallScript
} = require('../utils/install_script');

const adminRouter = express.Router();
const publicRouter = express.Router();

const SERVER_ROOT = path.join(__dirname, '..', '..');
const UPLOAD_DIR = path.join(SERVER_ROOT, 'uploads', 'installs');

/** 版本号白名单 / 文件名版本提取（与 routes/updates.js 保持一致） */
const VERSION_RE = /^[0-9A-Za-z][0-9A-Za-z.+-]{0,31}$/;
const FILENAME_VERSION_RE = /_([0-9]+\.[0-9]+\.[0-9]+(?:[-+][0-9A-Za-z.+-]+)?)\.zip$/i;

/** 安装包大小上限：与更新包一致（500MB） */
const MAX_UPLOAD_BYTES = 500 * 1024 * 1024;

/** Sink 短链创建超时（毫秒） */
const SINK_TIMEOUT_MS = 15000;

fs.mkdirSync(UPLOAD_DIR, { recursive: true });

/** 生成 16 位随机 slug（[A-Za-z0-9]，约 95 bit 熵，即公开接口凭据） */
function generateSlug() {
  const alphabet = 'ABCDEFGHIJKLMNOPQRSTUVWXYZabcdefghijklmnopqrstuvwxyz0123456789';
  const bytes = crypto.randomBytes(16);
  let s = '';
  for (let i = 0; i < 16; i++) s += alphabet[bytes[i] % alphabet.length];
  return s;
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

/** 读取当前客户端 Token（embed_config 脚本按请求实时嵌入，Token 重置后自动跟随） */
async function getCurrentClientToken() {
  try {
    const rows = await query('SELECT `token` FROM `client_token` WHERE `id` = 1');
    return rows.length ? rows[0].token : '';
  } catch (e) {
    return '';
  }
}

/** multipart 文本字段 → 布尔（缺省默认 true 的字段由调用方处理） */
function parseBoolField(value, fallback) {
  if (value === undefined || value === null || String(value).trim() === '') return fallback;
  const v = String(value).trim().toLowerCase();
  if (['1', 'true', 'yes', 'on'].includes(v)) return true;
  if (['0', 'false', 'no', 'off'].includes(v)) return false;
  return fallback;
}

/** Sink API Key 白名单：1-255 位，不含空白与控制字符（Bearer 令牌原样发送） */
function isValidSinkApiKey(key) {
  const k = String(key || '');
  return k.length >= 1 && k.length <= 255 && !/[\s\x00-\x1f]/.test(k);
}

/** 读取已保存的 Sink 配置单行（无行/未保存返回空对象） */
async function getSinkSettingsRow() {
  try {
    const rows = await query('SELECT sink_url, api_key, updated_at FROM sink_settings WHERE id = 1');
    return rows[0] || {};
  } catch (e) {
    return {};
  }
}

/** sink_settings 行 → 对外响应（Key 只回传脱敏形式，不回传明文） */
function toSinkSettingsItem(row) {
  return {
    sink_url: row.sink_url || '',
    api_key_set: !!row.api_key,
    api_key_masked: row.api_key ? maskApiKey(row.api_key) : '',
    updated_at: row.updated_at || null
  };
}

/** 行数据 → 对外 item（剥离 stored_path；派生 script_url 与长命令） */
function toItem(row, creator) {
  if (!row) return null;
  const scriptUrl = buildScriptUrl(row.client_base_url, row.slug);
  return {
    id: row.id,
    slug: row.slug,
    version: row.version || null,
    notes: row.notes || null,
    filename: row.filename,
    size: Number(row.size),
    sha256: row.sha256,
    install_dir: row.install_dir,
    client_base_url: row.client_base_url,
    embed_config: !!row.embed_config,
    enabled: !!row.enabled,
    download_count: Number(row.download_count || 0),
    created_by: creator || null,
    created_at: row.created_at,
    script_url: scriptUrl,
    command: buildInstallCommand(scriptUrl)
  };
}

const SELECT_ITEM_SQL = `
  SELECT i.*, u.username AS created_by_name
  FROM install_packages i LEFT JOIN users u ON u.id = i.created_by`;

// multer 配置：磁盘存储到 uploads/installs/，先以临时名落盘，写库前 rename
const upload = multer({
  storage: multer.diskStorage({
    destination: (req, file, cb) => cb(null, UPLOAD_DIR),
    filename: (req, file, cb) => {
      const base = path.basename(file.originalname || '');
      if (!/^[A-Za-z0-9._-]+$/.test(base)) {
        return cb(new Error('文件名包含非法字符，仅允许字母、数字、_、-、.'));
      }
      cb(null, `tmp_${Date.now()}_${base}`);
    }
  }),
  limits: { fileSize: MAX_UPLOAD_BYTES },
  fileFilter: (req, file, cb) => {
    if (!/\.zip$/i.test(file.originalname || '')) {
      return cb(new Error('仅允许上传 .zip 安装包'));
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
              ? '安装包超过 500MB 上传上限'
              : `上传失败: ${err.message}`;
          return res.status(400).json({ error: msg });
        }
        return res.status(400).json({ error: err.message || '上传失败' });
      }
      next();
    });
  };
}

// ============ 管理端接口 ============

// POST /api/installs（上传 zip 并创建安装入口）
adminRouter.post('/', uploadSingle('file'), async (req, res, next) => {
  let absPath = null;
  try {
    if (!req.file) {
      return res.status(400).json({ error: '缺少上传文件（字段名应为 file）' });
    }
    absPath = req.file.path;
    const body = req.body || {};

    // 安装目录与客户端地址：必填（前端预填默认值）
    let installDir;
    let clientBaseUrl;
    try {
      installDir = normalizeInstallDir(body.install_dir && String(body.install_dir).trim() !== ''
        ? body.install_dir
        : 'C:\\HomeworkTime');
      clientBaseUrl = normalizeClientBaseUrl(body.client_base_url);
    } catch (e) {
      return res.status(400).json({ error: e.message });
    }
    const embedConfig = parseBoolField(body.embed_config, true);

    // 版本号：显式填写优先，否则从文件名提取；允许为空
    let version = String(body.version || '').trim();
    if (!version) {
      const m = FILENAME_VERSION_RE.exec(path.basename(req.file.originalname || ''));
      if (m) version = m[1];
    }
    if (version && !VERSION_RE.test(version)) {
      return res.status(400).json({ error: '版本号非法（字母数字开头，可含 . + -，长度 1-32）' });
    }
    version = version || null;

    let notes = null;
    if (body.notes !== undefined && body.notes !== null && String(body.notes).trim() !== '') {
      notes = String(body.notes).trim().slice(0, 500);
    }

    const sha256 = await computeSha256(absPath);
    const size = req.file.size;

    // 规范化落盘文件名（含时间戳，防覆盖）
    const stamp = new Date().toISOString().replace(/[-:T]/g, '').slice(0, 14);
    const finalName = `HomeworkTime_install_${version || 'na'}_${stamp}.zip`;
    const finalPath = path.join(UPLOAD_DIR, finalName);
    await fs.promises.rename(absPath, finalPath);
    absPath = finalPath;
    const storedPath = path.relative(SERVER_ROOT, finalPath).split(path.sep).join('/');

    // 插入记录（slug 唯一键冲突时重试）
    let row = null;
    for (let attempt = 0; attempt < 3 && !row; attempt++) {
      const slug = generateSlug();
      try {
        const [result] = await pool.execute(
          `INSERT INTO install_packages
             (slug, version, notes, filename, stored_path, size, sha256,
              install_dir, client_base_url, embed_config, enabled, created_by)
           VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, 1, ?)`,
          [
            slug, version, notes, path.basename(req.file.originalname || finalName),
            storedPath, size, sha256, installDir, clientBaseUrl, embedConfig ? 1 : 0,
            req.user.id
          ]
        );
        const rows = await query(`${SELECT_ITEM_SQL} WHERE i.id = ?`, [result.insertId]);
        row = rows[0] || null;
      } catch (e) {
        if (e && e.code === 'ER_DUP_ENTRY') continue; // slug 撞库，换一个重试
        throw e;
      }
    }
    if (!row) {
      return res.status(500).json({ error: 'slug 生成冲突，请重试' });
    }

    await writeAudit(req.user.id, 'install.create', {
      id: row.id,
      slug: row.slug,
      version,
      filename: row.filename,
      size,
      install_dir: installDir,
      client_base_url: clientBaseUrl,
      embed_config: embedConfig
    });

    res.status(201).json({ item: toItem(row, row.created_by_name) });
  } catch (err) {
    if (absPath) {
      await fs.promises.unlink(absPath).catch(() => {});
    }
    next(err);
  }
});

// GET /api/installs（列表，按创建时间倒序）
adminRouter.get('/', async (req, res, next) => {
  try {
    const rows = await query(`${SELECT_ITEM_SQL} ORDER BY i.id DESC`);
    res.json({ total: rows.length, items: rows.map((r) => toItem(r, r.created_by_name)) });
  } catch (err) {
    next(err);
  }
});

// GET /api/installs/sink-settings（查看已保存 Sink 配置，Key 仅脱敏回传）
adminRouter.get('/sink-settings', async (req, res, next) => {
  try {
    res.json(toSinkSettingsItem(await getSinkSettingsRow()));
  } catch (err) {
    next(err);
  }
});

// PUT /api/installs/sink-settings（保存 Sink 配置；api_key 留空 = 保持已保存 Key）
adminRouter.put('/sink-settings', async (req, res, next) => {
  try {
    const body = req.body || {};
    const sinkUrl = String(body.sink_url || '').trim();
    if (!sinkUrl) {
      return res.status(400).json({ error: '缺少 Sink 服务地址（sink_url）' });
    }
    let sink;
    try {
      sink = parseSinkUrl(sinkUrl);
    } catch (e) {
      return res.status(400).json({ error: e.message });
    }
    const apiKey = String(body.api_key || '').trim();
    if (apiKey && !isValidSinkApiKey(apiKey)) {
      return res.status(400).json({ error: 'API Key 非法（1-255 位，不含空白与控制字符）' });
    }

    // 单行表 UPSERT 兜底；api_key 留空时只更新地址（保留已保存 Key）
    if (apiKey) {
      await pool.execute(
        `INSERT INTO sink_settings (id, sink_url, api_key, updated_by) VALUES (1, ?, ?, ?)
         ON DUPLICATE KEY UPDATE sink_url = VALUES(sink_url), api_key = VALUES(api_key),
           updated_by = VALUES(updated_by)`,
        [sinkUrl, apiKey, req.user.id]
      );
    } else {
      await pool.execute(
        `INSERT INTO sink_settings (id, sink_url, api_key, updated_by) VALUES (1, ?, NULL, ?)
         ON DUPLICATE KEY UPDATE sink_url = VALUES(sink_url), updated_by = VALUES(updated_by)`,
        [sinkUrl, req.user.id]
      );
    }

    // 审计只记主机名与是否更换 Key，绝不记录 Key 值
    await writeAudit(req.user.id, 'install.sink.save', {
      sink_host: sink.hostname,
      api_key_changed: !!apiKey
    });

    res.json(toSinkSettingsItem(await getSinkSettingsRow()));
  } catch (err) {
    next(err);
  }
});

// PATCH /api/installs/:id（部分更新安装配置）
adminRouter.patch('/:id', async (req, res, next) => {
  try {
    const id = Number(req.params.id);
    if (!Number.isInteger(id) || id <= 0) {
      return res.status(400).json({ error: 'id 非法' });
    }
    const rows = await query('SELECT * FROM install_packages WHERE id = ? LIMIT 1', [id]);
    if (!rows.length) return res.status(404).json({ error: '安装包不存在' });

    const body = req.body || {};
    const updates = {};
    try {
      if (body.install_dir !== undefined) updates.install_dir = normalizeInstallDir(body.install_dir);
      if (body.client_base_url !== undefined) updates.client_base_url = normalizeClientBaseUrl(body.client_base_url);
    } catch (e) {
      return res.status(400).json({ error: e.message });
    }
    if (body.version !== undefined) {
      const v = String(body.version || '').trim();
      if (v && !VERSION_RE.test(v)) {
        return res.status(400).json({ error: '版本号非法（字母数字开头，可含 . + -，长度 1-32）' });
      }
      updates.version = v || null;
    }
    if (body.notes !== undefined) {
      updates.notes = String(body.notes || '').trim().slice(0, 500) || null;
    }
    if (body.embed_config !== undefined) {
      updates.embed_config = body.embed_config ? 1 : 0;
    }
    if (body.enabled !== undefined) {
      updates.enabled = body.enabled ? 1 : 0;
    }
    if (!Object.keys(updates).length) {
      return res.status(400).json({ error: '没有需要更新的字段' });
    }

    const setSql = Object.keys(updates).map((k) => `\`${k}\` = ?`).join(', ');
    await pool.execute(`UPDATE install_packages SET ${setSql} WHERE id = ?`, [
      ...Object.values(updates), id
    ]);

    const after = await query(`${SELECT_ITEM_SQL} WHERE i.id = ?`, [id]);
    await writeAudit(req.user.id, 'install.update', { id, changes: Object.keys(updates) });
    res.json({ item: toItem(after[0], after[0].created_by_name) });
  } catch (err) {
    next(err);
  }
});

// DELETE /api/installs/:id（删除记录与物理文件）
adminRouter.delete('/:id', async (req, res, next) => {
  try {
    const id = Number(req.params.id);
    if (!Number.isInteger(id) || id <= 0) {
      return res.status(400).json({ error: 'id 非法' });
    }
    const rows = await query('SELECT * FROM install_packages WHERE id = ? LIMIT 1', [id]);
    if (!rows.length) return res.status(404).json({ error: '安装包不存在' });
    const row = rows[0];

    await pool.execute('DELETE FROM install_packages WHERE id = ?', [id]);
    if (row.stored_path) {
      const absPath = path.resolve(SERVER_ROOT, row.stored_path);
      await fs.promises.unlink(absPath).catch((e) => {
        console.error('[installs] 删除安装包文件失败:', e.message);
      });
    }
    await writeAudit(req.user.id, 'install.delete', { id, slug: row.slug, filename: row.filename });
    res.json({ ok: true });
  } catch (err) {
    next(err);
  }
});

// POST /api/installs/:id/shortlink（调 Sink 生成短链 + 短命令）
adminRouter.post('/:id/shortlink', async (req, res, next) => {
  try {
    const id = Number(req.params.id);
    if (!Number.isInteger(id) || id <= 0) {
      return res.status(400).json({ error: 'id 非法' });
    }
    const rows = await query('SELECT * FROM install_packages WHERE id = ? LIMIT 1', [id]);
    if (!rows.length) return res.status(404).json({ error: '安装包不存在' });
    const pkg = rows[0];
    if (!pkg.enabled) {
      return res.status(400).json({ error: '该安装入口已停用，请先启用' });
    }

    const body = req.body || {};
    // 地址/Key 未随请求传入时回退到服务端已保存的 Sink 配置（管理端「短链服务设置」）
    const saved = await getSinkSettingsRow();
    const sinkUrl = String(body.sink_url || '').trim() || String(saved.sink_url || '').trim();
    const sinkApiKey = String(body.sink_api_key || '').trim() || String(saved.api_key || '').trim();
    if (!sinkUrl) {
      return res.status(400).json({ error: '缺少短链服务地址（sink_url），请填写或先在「短链服务设置」中保存' });
    }
    if (!sinkApiKey) {
      return res.status(400).json({ error: '缺少短链服务 API Key，请填写或先在「短链服务设置」中保存' });
    }
    if (!isValidSinkApiKey(sinkApiKey)) {
      return res.status(400).json({ error: 'API Key 非法（1-255 位，不含空白与控制字符）' });
    }
    const customSlug = String(body.slug || '').trim();
    if (!isValidSinkSlug(customSlug)) {
      return res.status(400).json({ error: '自定义短链 slug 非法（字母数字开头，可含 -，最长 64）' });
    }

    let sink;
    try {
      sink = parseSinkUrl(sinkUrl);
    } catch (e) {
      return res.status(400).json({ error: e.message });
    }

    const scriptUrl = buildScriptUrl(pkg.client_base_url, pkg.slug);
    const payload = {
      url: scriptUrl,
      domain: sink.hostname,
      comment: 'HomeworkTime 一键安装脚本'
    };
    if (customSlug) payload.slug = customSlug;

    const controller = new AbortController();
    const timer = setTimeout(() => controller.abort(), SINK_TIMEOUT_MS);
    let resp;
    try {
      resp = await fetch(`${sink.origin}/api/link/upsert`, {
        method: 'POST',
        headers: {
          Authorization: `Bearer ${sinkApiKey}`,
          'Content-Type': 'application/json'
        },
        body: JSON.stringify(payload),
        signal: controller.signal
      });
    } catch (e) {
      return res.status(502).json({
        error: `短链服务连接失败：${e.name === 'AbortError' ? '请求超时' : e.message}`
      });
    } finally {
      clearTimeout(timer);
    }

    if (!resp.ok) {
      let detail = '';
      try {
        detail = (await resp.text()).slice(0, 300);
      } catch (e) { /* 忽略 */ }
      const mapped = resp.status === 401 || resp.status === 403
        ? '短链服务鉴权失败（API Key 不正确）'
        : resp.status === 423
          ? '短链服务存储未就绪（请先在 Sink 后台打开一次 Links 页面）'
          : resp.status === 400
            ? `短链服务拒绝请求（域名未注册或 slug 非法）：${detail || resp.statusText}`
            : `短链服务返回 ${resp.status}：${detail || resp.statusText}`;
      return res.status(502).json({ error: mapped });
    }

    const data = await resp.json().catch(() => null);
    const shortUrl = data && typeof data.shortLink === 'string' ? data.shortLink : '';
    if (!shortUrl) {
      return res.status(502).json({ error: '短链服务响应异常（未返回 shortLink）' });
    }

    await writeAudit(req.user.id, 'install.shortlink', {
      id,
      slug: pkg.slug,
      sink_host: sink.hostname,
      custom_slug: customSlug || null,
      short_url: shortUrl,
      status: data.status || null
    });

    res.json({
      short_url: shortUrl,
      command: buildInstallCommand(shortUrl),
      status: data.status || null
    });
  } catch (err) {
    next(err);
  }
});

// ============ 公开接口（slug 即凭据） ============

/** 按 slug 取启用的安装包；不存在或已停用返回 null */
async function getEnabledPackage(slug) {
  if (!isValidSlug(slug)) return null;
  const rows = await query('SELECT * FROM install_packages WHERE slug = ? AND enabled = 1 LIMIT 1', [slug]);
  return rows.length ? rows[0] : null;
}

// GET /api/install/s/:slug（安装脚本文本）
publicRouter.get('/s/:slug', async (req, res, next) => {
  try {
    const pkg = await getEnabledPackage(req.params.slug);
    if (!pkg) {
      return res.status(404).type('text/plain; charset=utf-8').send('Install entry not found or disabled.');
    }
    const clientToken = pkg.embed_config ? await getCurrentClientToken() : '';
    const script = buildInstallScript({
      slug: pkg.slug,
      clientBaseUrl: pkg.client_base_url,
      installDir: pkg.install_dir,
      embedConfig: !!pkg.embed_config,
      clientToken
    });
    res.setHeader('Content-Type', 'text/plain; charset=utf-8');
    res.setHeader('Cache-Control', 'no-store');
    res.send(script);
  } catch (err) {
    next(err);
  }
});

// GET /api/install/s/:slug/package（安装包 zip 二进制流）
publicRouter.get('/s/:slug/package', async (req, res, next) => {
  try {
    const pkg = await getEnabledPackage(req.params.slug);
    if (!pkg) {
      return res.status(404).type('text/plain; charset=utf-8').send('Install entry not found or disabled.');
    }
    const absPath = path.resolve(SERVER_ROOT, pkg.stored_path);
    // 下载计数（异步，失败不影响下载）
    pool.execute('UPDATE install_packages SET download_count = download_count + 1 WHERE id = ?', [pkg.id])
      .catch((e) => console.error('[installs] 下载计数失败:', e.message));
    res.setHeader('X-Install-Sha256', pkg.sha256 || '');
    res.setHeader('X-Install-Size', String(pkg.size || ''));
    res.setHeader('Content-Type', 'application/zip');
    res.sendFile(absPath, (err) => {
      if (!err) return;
      if (err.code === 'ENOENT') {
        if (!res.headersSent) return res.status(404).type('text/plain; charset=utf-8').send('Package file missing.');
        return res.end();
      }
      next(err);
    });
  } catch (err) {
    next(err);
  }
});

module.exports = { adminRouter, publicRouter };
