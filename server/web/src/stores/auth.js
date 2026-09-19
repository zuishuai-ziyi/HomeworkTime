import { defineStore } from 'pinia'

const TOKEN_KEY = 'ht_admin_token'
const USERNAME_KEY = 'ht_admin_username'

/**
 * 认证状态：token / username 持久化到 localStorage（键名按约定 ht_admin_token）。
 */
export const useAuthStore = defineStore('auth', {
  state: () => ({
    token: localStorage.getItem(TOKEN_KEY) || '',
    username: localStorage.getItem(USERNAME_KEY) || ''
  }),
  actions: {
    setAuth(token, username) {
      this.token = token
      this.username = username
      localStorage.setItem(TOKEN_KEY, token)
      localStorage.setItem(USERNAME_KEY, username)
    },
    logout() {
      this.token = ''
      this.username = ''
      localStorage.removeItem(TOKEN_KEY)
      localStorage.removeItem(USERNAME_KEY)
    }
  }
})