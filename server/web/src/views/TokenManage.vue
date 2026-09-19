<template>
  <div class="page-card">
    <div class="toolbar">
      <div class="toolbar-title">客户端 Token</div>
      <el-button type="danger" :loading="resetting" @click="handleReset">
        <el-icon style="margin-right: 4px"><Refresh /></el-icon>
        重置 Token
      </el-button>
    </div>

    <el-descriptions :column="1" border v-loading="loading">
      <el-descriptions-item label="当前 Token">
        <div class="token-row">
          <code class="token-code">{{ shown ? token : maskToken }}</code>
          <el-button type="primary" link :disabled="!token" @click="shown = !shown">
            {{ shown ? '隐藏' : '显示' }}
          </el-button>
          <el-button type="primary" link :disabled="!token" @click="copyToken">
            复制
          </el-button>
        </div>
      </el-descriptions-item>
      <el-descriptions-item label="更新时间">
        {{ updatedAt || '-' }}
      </el-descriptions-item>
    </el-descriptions>

    <el-alert
      class="tip"
      type="warning"
      :closable="false"
      show-icon
      title="重置后所有客户端需更新本地配置中的 client_token，否则将无法连接服务器。"
    />
  </div>
</template>

<script setup>
import { ref, computed, onMounted } from 'vue'
import { ElMessage, ElMessageBox } from 'element-plus'
import { getClientToken, resetClientToken } from '../api'

const token = ref('')
const updatedAt = ref('')
const loading = ref(false)
const resetting = ref(false)
const shown = ref(false)

const maskToken = computed(() => {
  if (!token.value) return ''
  if (token.value.length <= 8) return '••••••••'
  return token.value.slice(0, 8) + '••••••••' + token.value.slice(-4)
})

function showError(err, fallback) {
  ElMessage.error(err.response?.data?.error || fallback)
}

async function loadToken() {
  loading.value = true
  try {
    const { data } = await getClientToken()
    token.value = data.token || ''
    updatedAt.value = data.updated_at || ''
  } catch (err) {
    showError(err, 'Token 获取失败')
  } finally {
    loading.value = false
  }
}

async function copyToken() {
  if (!token.value) return
  try {
    await navigator.clipboard.writeText(token.value)
    ElMessage.success('已复制到剪贴板')
  } catch (err) {
    // clipboard API 不可用时回退 execCommand
    const ta = document.createElement('textarea')
    ta.value = token.value
    document.body.appendChild(ta)
    ta.select()
    const ok = document.execCommand('copy')
    document.body.removeChild(ta)
    if (ok) ElMessage.success('已复制到剪贴板')
    else showError(err, '复制失败，请手动选择复制')
  }
}

function handleReset() {
  ElMessageBox.confirm(
    '重置后所有客户端需更新配置中的 client_token，否则将无法连接服务器。确定继续吗？',
    '重置 Token',
    {
      confirmButtonText: '重置',
      cancelButtonText: '取消',
      type: 'warning'
    }
  )
    .then(async () => {
      resetting.value = true
      try {
        const { data } = await resetClientToken()
        token.value = data.token || ''
        shown.value = true // 重置后直接展示新 Token 便于复制
        ElMessage.success('Token 已重置，请及时同步到各客户端')
      } catch (err) {
        showError(err, '重置失败')
      } finally {
        resetting.value = false
      }
    })
    .catch(() => {})
}

onMounted(loadToken)
</script>

<style scoped>
.toolbar {
  display: flex;
  align-items: center;
  justify-content: space-between;
  margin-bottom: 14px;
}

.toolbar-title {
  font-size: 14px;
  font-weight: 600;
  color: #1f2329;
}

.token-row {
  display: flex;
  align-items: center;
  gap: 4px;
}

.token-code {
  font-family: Consolas, Menlo, monospace;
  font-size: 13px;
  background: #EAF6FB;
  border-radius: 4px;
  padding: 4px 8px;
  user-select: all;
}

.tip {
  margin-top: 16px;
}
</style>