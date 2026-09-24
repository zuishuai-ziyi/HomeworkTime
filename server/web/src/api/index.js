import http from './http'

// ===================== 认证 =====================
/** POST /api/auth/login { username, password } -> { token, username } */
export const login = (data) => http.post('/auth/login', data)

// ===================== 配置 =====================
/** GET /api/config -> { version, config, updated_at, updated_by } */
export const getConfig = () => http.get('/config')
/** PUT /api/config body { config } -> { version, config, updated_at, updated_by } */
export const updateConfig = (config) => http.put('/config', { config })

// ===================== 音频 =====================
/** GET /api/audio -> { total, items } */
export const getAudioList = () => http.get('/audio')
/** POST /api/audio（multipart，字段名 file）仅 .wav */
export const uploadAudio = (file) => {
  const fd = new FormData()
  fd.append('file', file)
  // 大音频上传单独放宽超时（默认 20s 不动），最长 120s
  return http.post('/audio', fd, {
    headers: { 'Content-Type': 'multipart/form-data' },
    timeout: 120000
  })
}
/** DELETE /api/audio/:id */
export const deleteAudio = (id) => http.delete(`/audio/${id}`)

// ===================== 用户 =====================
/** GET /api/users -> { total, items } */
export const getUsers = () => http.get('/users')
/** POST /api/users { username, password } -> 201 { id, username } */
export const createUser = (data) => http.post('/users', data)
/** PUT /api/users/:id { username?, password? } -> { id, username } */
export const updateUser = (id, data) => http.put(`/users/${id}`, data)
/** DELETE /api/users/:id -> { ok } */
export const deleteUser = (id) => http.delete(`/users/${id}`)

// ===================== 设备 =====================
/** GET /api/devices -> { total, items }（含 online 判定） */
export const getDevices = () => http.get('/devices')
/** PUT /api/devices/:id { room_name } -> { id, room_name } */
export const updateDeviceRoom = (id, room_name) => http.put(`/devices/${id}`, { room_name })

// ===================== 操作日志 =====================
/** GET /api/audit-logs?page=&page_size= -> { total, page, page_size, items } */
export const getAuditLogs = (page, page_size) =>
  http.get('/audit-logs', { params: { page, page_size } })

// ===================== 客户端 Token =====================
/** GET /api/client-token -> { token, updated_at } */
export const getClientToken = () => http.get('/client-token')
/** POST /api/client-token/reset -> { token } */
export const resetClientToken = () => http.post('/client-token/reset')

// ===================== 更新管理 =====================
/** GET /api/updates/current -> { item }（当前已发布的全量更新包，未发布过为 null） */
export const getUpdateInfo = () => http.get('/updates/current')
/**
 * POST /api/updates/upload（multipart：file + version + notes + effective_time）
 * 上传 zip 更新包并立即发布（全量推送，仅保留最新一个包）；effective_time 为空 = 立即生效。
 * 更新包较大，单独放宽超时（最长 10 分钟）。
 */
export const uploadUpdate = (file, version, notes, effectiveTime) => {
  const fd = new FormData()
  fd.append('file', file)
  fd.append('version', version)
  if (notes) fd.append('notes', notes)
  if (effectiveTime) fd.append('effective_time', effectiveTime)
  return http.post('/updates/upload', fd, {
    headers: { 'Content-Type': 'multipart/form-data' },
    timeout: 600000
  })
}
/** PUT /api/updates/current/effective-time { effective_time } -> { ok, effective_time } */
export const updateEffectiveTime = (effectiveTime) =>
  http.put('/updates/current/effective-time', { effective_time: effectiveTime })