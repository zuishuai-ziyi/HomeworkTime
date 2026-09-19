import axios from 'axios'
import { ElMessage } from 'element-plus'

const TOKEN_KEY = 'ht_admin_token'
const USERNAME_KEY = 'ht_admin_username'

/**
 * axios 实例：baseURL=/api，请求自动携带 Bearer token；
 * 响应 401 时清除 token 并跳转登录页。
 */
const http = axios.create({
  baseURL: '/api',
  timeout: 20000
})

http.interceptors.request.use((config) => {
  const token = localStorage.getItem(TOKEN_KEY)
  if (token) {
    config.headers.Authorization = `Bearer ${token}`
  }
  return config
})

http.interceptors.response.use(
  (response) => response,
  (error) => {
    const status = error.response?.status
    if (status === 401) {
      localStorage.removeItem(TOKEN_KEY)
      localStorage.removeItem(USERNAME_KEY)
      if (!window.location.hash.startsWith('#/login')) {
        window.location.hash = '#/login'
      }
      ElMessage.error(error.response?.data?.error || '登录已过期，请重新登录')
    }
    return Promise.reject(error)
  }
)

export default http