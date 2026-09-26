import { createRouter, createWebHashHistory } from 'vue-router'

const routes = [
  {
    path: '/login',
    name: 'Login',
    component: () => import('../views/Login.vue'),
    meta: { public: true, title: '登录' }
  },
  {
    path: '/',
    component: () => import('../layout/MainLayout.vue'),
    redirect: '/config',
    children: [
      {
        path: 'config',
        name: 'ConfigEdit',
        component: () => import('../views/ConfigEdit.vue'),
        meta: { title: '配置编辑' }
      },
      {
        path: 'audio',
        name: 'AudioManage',
        component: () => import('../views/AudioManage.vue'),
        meta: { title: '音频管理' }
      },
      {
        path: 'updates',
        name: 'UpdateManage',
        component: () => import('../views/UpdateManage.vue'),
        meta: { title: '更新管理' }
      },
      {
        path: 'installs',
        name: 'InstallManage',
        component: () => import('../views/InstallManage.vue'),
        meta: { title: '一键安装' }
      },
      {
        path: 'users',
        name: 'UserManage',
        component: () => import('../views/UserManage.vue'),
        meta: { title: '用户管理' }
      },
      {
        path: 'devices',
        name: 'DeviceMonitor',
        component: () => import('../views/DeviceMonitor.vue'),
        meta: { title: '设备监控' }
      },
      {
        path: 'token',
        name: 'TokenManage',
        component: () => import('../views/TokenManage.vue'),
        meta: { title: '客户端 Token' }
      },
      {
        path: 'audit',
        name: 'AuditLogs',
        component: () => import('../views/AuditLogs.vue'),
        meta: { title: '操作日志' }
      }
    ]
  },
  { path: '/:pathMatch(.*)*', redirect: '/' }
]

const router = createRouter({
  history: createWebHashHistory(),
  routes
})

// 登录守卫：无 token 只能访问公开页（/login）
router.beforeEach((to) => {
  const token = localStorage.getItem('ht_admin_token')
  if (!to.meta.public && !token) {
    // 连续 401 时 http.js 会直接改 hash，此处防止无限跳转
    if (to.path !== '/login') {
      return { path: '/login' }
    }
  }
  if (to.path === '/login' && token) {
    return { path: '/' }
  }
  return true
})

export default router