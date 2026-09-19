/**
 * utils/audit.js — 审计日志写入工具
 *
 * 所有后台敏感操作（配置修改、音频上传/删除、用户增删改、Token 重置）
 * 都通过本工具落库。写入失败只记录到控制台，绝不阻塞主业务流程。
 */
const { pool } = require('../db');

/**
 * 写入一条审计日志
 * @param {number|null} userId 操作者 user.id，系统动作可为 null
 * @param {string}      action 操作类型，如 config.update / audio.upload
 * @param {object}      detail 详情对象（写入 detail_json 列）
 */
async function writeAudit(userId, action, detail) {
  try {
    await pool.execute(
      'INSERT INTO `audit_logs` (`user_id`, `action`, `detail_json`) VALUES (?, ?, ?)',
      [userId || null, action, detail ? JSON.stringify(detail) : null]
    );
  } catch (err) {
    // 审计失败不影响主流程，仅记录
    console.error('[audit] 写入审计日志失败:', err.message);
  }
}

module.exports = { writeAudit };