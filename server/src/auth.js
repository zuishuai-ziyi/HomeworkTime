/**
 * auth.js — 鉴权工具与中间件
 *
 * 1) JWT：后台登录签发（12h 过期），Authorization: Bearer <token> 校验
 * 2) 客户端 Token：X-Client-Token 请求头与 client_token 表比对（403）
 *
 * JWT 密钥 process.env.JWT_SECRET，未设置时使用默认密钥（生产必须配置）。
 */
const jwt = require('jsonwebtoken');
const { query } = require('./db');

const JWT_SECRET = process.env.JWT_SECRET || 'homework-time-default-secret-change-me';
const JWT_EXPIRES_IN = '12h';

/**
 * 签发 JWT
 * @param {object} payload 载荷（含 id、username）
 * @returns {string} token
 */
function signToken(payload) {
  return jwt.sign(payload, JWT_SECRET, { expiresIn: JWT_EXPIRES_IN });
}

/**
 * 后台 JWT 鉴权中间件
 * 校验通过后把载荷写入 req.user = { id, username, iat, exp }
 */
function requireAuth(req, res, next) {
  const header = req.headers.authorization || '';
  const token = header.startsWith('Bearer ') ? header.slice('Bearer '.length).trim() : '';
  if (!token) {
    return res.status(401).json({ error: '未提供 Token，请先登录' });
  }
  try {
    req.user = jwt.verify(token, JWT_SECRET);
    next();
  } catch (err) {
    return res.status(401).json({ error: 'Token 无效或已过期' });
  }
}

/**
 * 客户端 X-Client-Token 鉴权中间件
 * 请求头中的 Token 必须与 client_token 表（单行）匹配才放行
 */
async function requireClientToken(req, res, next) {
  try {
    const token = (req.headers['x-client-token'] || '').trim();
    if (!token) {
      return res.status(403).json({ error: '缺少客户端 Token（请求头 X-Client-Token）' });
    }
    const rows = await query('SELECT `id` FROM `client_token` WHERE `token` = ? LIMIT 1', [token]);
    if (!rows.length) {
      return res.status(403).json({ error: '客户端 Token 无效' });
    }
    next();
  } catch (err) {
    next(err);
  }
}

/**
 * 后台 JWT 或客户端 Token 双鉴权中间件（仅用于少数客户端也需要改写的接口）
 *
 * - Authorization: Bearer <jwt> → 管理员身份，req.user = 载荷
 * - 仅携带 X-Client-Token      → 客户端身份，req.user = null、req.clientAuth = true
 * - 两者都缺失                    → 401
 * - Token 无效                   → 401/403
 */
async function requireAuthOrClientToken(req, res, next) {
  const header = req.headers.authorization || '';
  const jwtToken = header.startsWith('Bearer ') ? header.slice('Bearer '.length).trim() : '';
  if (jwtToken) {
    try {
      req.user = jwt.verify(jwtToken, JWT_SECRET);
      return next();
    } catch (err) {
      return res.status(401).json({ error: 'Token 无效或已过期' });
    }
  }
  const clientToken = (req.headers['x-client-token'] || '').trim();
  if (clientToken) {
    try {
      const rows = await query('SELECT `id` FROM `client_token` WHERE `token` = ? LIMIT 1', [clientToken]);
      if (!rows.length) {
        return res.status(403).json({ error: '客户端 Token 无效' });
      }
      req.user = null; // 无后台登录用户
      req.clientAuth = true;
      return next();
    } catch (err) {
      return next(err);
    }
  }
  return res.status(401).json({ error: '未提供 Token，请先登录' });
}

module.exports = {
  JWT_SECRET,
  JWT_EXPIRES_IN,
  signToken,
  requireAuth,
  requireClientToken,
  requireAuthOrClientToken
};