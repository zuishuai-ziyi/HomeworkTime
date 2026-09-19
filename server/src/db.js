/**
 * db.js — MySQL 连接池（mysql2/promise）
 *
 * 连接参数全部来自环境变量，未设置时使用默认值：
 *   DB_HOST      默认 127.0.0.1
 *   DB_PORT      默认 3306
 *   DB_USER      默认 root
 *   DB_PASSWORD  默认空
 *   DB_NAME      默认 homework_time
 *
 * 导出 pool（供需要事务/原生连接的场景）与 query（便捷查询助手）。
 */
const mysql = require('mysql2/promise');

const pool = mysql.createPool({
  host: process.env.DB_HOST || '127.0.0.1',
  port: parseInt(process.env.DB_PORT || '3306', 10),
  user: process.env.DB_USER || 'root',
  password: process.env.DB_PASSWORD || '',
  database: process.env.DB_NAME || 'homework_time',
  waitForConnections: true,
  connectionLimit: 10,
  queueLimit: 0,
  charset: 'utf8mb4',
  // 让 DATETIME 直接以字符串返回，避免驱动时区转换与前端展示不一致
  dateStrings: true
});

/**
 * 便捷查询助手，返回行数组（SELECT 为 rows，其余返回操作结果对象）。
 * @param {string} sql    SQL 语句（建议使用 ? 占位符）
 * @param {Array}  params 参数数组
 * @returns {Promise<Array>}
 */
async function query(sql, params) {
  const [rows] = await pool.execute(sql, params || []);
  return rows;
}

module.exports = { pool, query };