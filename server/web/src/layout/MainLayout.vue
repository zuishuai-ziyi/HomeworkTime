<template>
  <el-container class="layout-root">
    <el-aside width="220px" class="layout-aside">
      <div class="layout-logo">
        <span class="logo-title">HomeworkTime</span>
        <span class="logo-sub">后台管理</span>
      </div>
      <el-menu
        class="layout-menu"
        :default-active="$route.path"
        router
        background-color="transparent"
        text-color="rgba(255,255,255,0.78)"
        active-text-color="#ffffff"
      >
        <el-menu-item index="/config">
          <el-icon><Setting /></el-icon>
          <span>配置编辑</span>
        </el-menu-item>
        <el-menu-item index="/audio">
          <el-icon><Headset /></el-icon>
          <span>音频管理</span>
        </el-menu-item>
        <el-menu-item index="/updates">
          <el-icon><UploadFilled /></el-icon>
          <span>更新管理</span>
        </el-menu-item>
        <el-menu-item index="/users">
          <el-icon><User /></el-icon>
          <span>用户管理</span>
        </el-menu-item>
        <el-menu-item index="/devices">
          <el-icon><Monitor /></el-icon>
          <span>设备监控</span>
        </el-menu-item>
        <el-menu-item index="/token">
          <el-icon><Key /></el-icon>
          <span>客户端 Token</span>
        </el-menu-item>
        <el-menu-item index="/audit">
          <el-icon><Document /></el-icon>
          <span>操作日志</span>
        </el-menu-item>
      </el-menu>
    </el-aside>

    <el-container class="layout-body">
      <el-header class="layout-header" height="56px">
        <span class="header-title">{{ $route.meta.title || '' }}</span>
        <div class="header-right">
          <el-dropdown trigger="click" @command="handleCommand">
            <span class="header-user">
              <el-icon><UserFilled /></el-icon>
              <span class="header-username">{{ auth.username || '未登录' }}</span>
              <el-icon><ArrowDown /></el-icon>
            </span>
            <template #dropdown>
              <el-dropdown-menu>
                <el-dropdown-item command="logout">
                  <el-icon><SwitchButton /></el-icon>
                  退出登录
                </el-dropdown-item>
              </el-dropdown-menu>
            </template>
          </el-dropdown>
        </div>
      </el-header>

      <el-main class="layout-main">
        <router-view />
      </el-main>
    </el-container>
  </el-container>
</template>

<script setup>
import { useRouter } from 'vue-router'
import { ElMessageBox } from 'element-plus'
import { useAuthStore } from '../stores/auth'

const router = useRouter()
const auth = useAuthStore()

function handleCommand(command) {
  if (command === 'logout') {
    ElMessageBox.confirm('确定要退出登录吗？', '退出登录', {
      confirmButtonText: '确定',
      cancelButtonText: '取消',
      type: 'warning'
    })
      .then(() => {
        auth.logout()
        router.push('/login')
      })
      .catch(() => {})
  }
}
</script>

<style scoped>
.layout-root {
  height: 100%;
}

.layout-aside {
  background: linear-gradient(180deg, #023E8A 0%, #03045E 100%);
  display: flex;
  flex-direction: column;
  overflow: hidden;
}

.layout-logo {
  height: 56px;
  display: flex;
  flex-direction: column;
  justify-content: center;
  padding: 0 20px;
  color: #fff;
  border-bottom: 1px solid rgba(255, 255, 255, 0.08);
  flex-shrink: 0;
}

.logo-title {
  font-size: 17px;
  font-weight: 600;
  line-height: 1.2;
}

.logo-sub {
  font-size: 12px;
  color: rgba(255, 255, 255, 0.5);
}

.layout-menu {
  border-right: none;
  flex: 1;
}

.layout-menu :deep(.el-menu-item.is-active) {
  background-color: #0096C7;
}

.layout-menu :deep(.el-menu-item:hover) {
  background-color: rgba(72, 202, 228, 0.15) !important;
}

.layout-body {
  min-width: 0;
}

.layout-header {
  background: #fff;
  border-bottom: 1px solid #90E0EF;
  display: flex;
  align-items: center;
  justify-content: space-between;
}

.header-title {
  font-size: 15px;
  font-weight: 600;
  color: #1f2329;
}

.header-right {
  display: flex;
  align-items: center;
}

.header-user {
  display: flex;
  align-items: center;
  gap: 4px;
  cursor: pointer;
  color: #1f2329;
  outline: none;
}

.header-username {
  font-size: 14px;
}

.layout-main {
  background: #CAF0F8;
  padding: 16px;
  overflow: auto;
}

.layout-main :deep(.page-card) {
  background: #fff;
  border-radius: 6px;
  padding: 16px 20px;
}
</style>