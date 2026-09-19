/**
 * utils/seed.js — 幂等初始化默认数据
 *
 * 应用启动时调用 ensure()：
 *   - users 表为空      -> 创建默认管理员 admin / admin123
 *   - config 表为空     -> 写入默认业务配置（default_config.json）
 *   - client_token 为空 -> 写入占位 Token CHANGE_ME_DEFAULT_TOKEN
 *   - audio_files 无内置行 -> 写入 near.wav / end.wav 元数据
 *
 * 所有操作均是 "已有则跳过"，重复执行安全。
 */
const path = require('path');
const fs = require('fs');
const bcrypt = require('bcryptjs');
const { pool } = require('../db');

const UPLOADS_DIR = path.join(__dirname, '..', '..', 'uploads', 'audio');

async function ensure() {
  // 确保音频上传目录存在
  fs.mkdirSync(UPLOADS_DIR, { recursive: true });

  // 1) 默认管理员
  const [users] = await pool.execute('SELECT COUNT(*) AS n FROM `users`');
  if (users[0].n === 0) {
    const hash = await bcrypt.hash('admin123', 10);
    await pool.execute(
      'INSERT INTO `users` (`username`, `password_hash`) VALUES (?, ?)',
      ['admin', hash]
    );
    console.warn('[seed] 默认管理员 admin/admin123 已创建，请立即登录后台修改密码');
  }

  // 2) 默认业务配置（单行 id=1）
  const [cfgs] = await pool.execute('SELECT COUNT(*) AS n FROM `config`');
  if (cfgs[0].n === 0) {
    const raw = JSON.parse(fs.readFileSync(path.join(__dirname, '..', 'default_config.json'), 'utf8'));
    delete raw._comment; // 去除说明占位键
    await pool.execute(
      'INSERT INTO `config` (`id`, `content_json`, `version`, `updated_by`) VALUES (1, ?, 1, NULL)',
      [JSON.stringify(raw)]
    );
    console.log('[seed] 已写入默认业务配置');
  }

  // 3) 客户端 Token（单行 id=1）
  const [toks] = await pool.execute('SELECT COUNT(*) AS n FROM `client_token`');
  if (toks[0].n === 0) {
    await pool.execute(
      'INSERT INTO `client_token` (`id`, `token`) VALUES (1, ?)',
      ['CHANGE_ME_DEFAULT_TOKEN']
    );
    console.log('[seed] 已写入默认客户端 Token');
  }

  // 4) 内置音频元数据（is_builtin=1，后台不可删）
  const [auds] = await pool.execute('SELECT COUNT(*) AS n FROM `audio_files` WHERE `is_builtin` = 1');
  if (auds[0].n === 0) {
    await pool.execute(
      'INSERT INTO `audio_files` (`filename`, `stored_path`, `size`, `sha256`, `is_builtin`) VALUES (?, NULL, NULL, NULL, 1), (?, NULL, NULL, NULL, 1)',
      ['near.wav', 'end.wav']
    );
    console.log('[seed] 已写入内置音频元数据 near.wav / end.wav');
  }
}

module.exports = { ensure, UPLOADS_DIR };