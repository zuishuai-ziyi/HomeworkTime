<template>
  <div class="page-card">
    <div class="toolbar">
      <span class="toolbar-title">操作日志（共 {{ total }} 条）</span>
      <el-button :loading="loading" @click="loadData">
        <el-icon style="margin-right: 4px"><Refresh /></el-icon>
        刷新
      </el-button>
    </div>

    <el-table :data="items" border stripe v-loading="loading">
      <el-table-column type="expand">
        <template #default="{ row }">
          <div class="detail-block">
            <div class="detail-label">动作：{{ actionLabel(row.action) }}</div>
            <pre class="detail-json">{{ formatDetail(row.detail_json) }}</pre>
          </div>
        </template>
      </el-table-column>
      <el-table-column prop="created_at" label="时间" width="180" />
      <el-table-column label="用户名" width="140">
        <template #default="{ row }">{{ row.username || '—' }}</template>
      </el-table-column>
      <el-table-column label="动作" min-width="160">
        <template #default="{ row }">
          <el-tag size="small" effect="plain">{{ actionLabel(row.action) }}</el-tag>
        </template>
      </el-table-column>
      <el-table-column label="详情" min-width="240">
        <template #default="{ row }">
          <span class="detail-preview">{{ previewDetail(row.detail_json) }}</span>
        </template>
      </el-table-column>
    </el-table>

    <div class="pager">
      <el-pagination
        v-model:current-page="page"
        v-model:page-size="pageSize"
        :total="total"
        :page-sizes="[20, 50, 100]"
        layout="total, sizes, prev, pager, next, jumper"
        background
        @size-change="handlePageChange"
        @current-change="handlePageChange"
      />
    </div>
  </div>
</template>

<script setup>
import { ref, onMounted } from 'vue'
import { ElMessage } from 'element-plus'
import { getAuditLogs } from '../api'

const items = ref([])
const total = ref(0)
const page = ref(1)
const pageSize = ref(20)
const loading = ref(false)

const ACTION_LABELS = {
  'config.update': '修改配置',
  'audio.upload': '上传音频',
  'audio.delete': '删除音频',
  'user.create': '新增用户',
  'user.update': '修改用户',
  'user.delete': '删除用户',
  'token.reset': '重置客户端 Token',
  'device.rename': '修改教室名'
}

function actionLabel(action) {
  return ACTION_LABELS[action] || action || '—'
}

function parseDetail(detailJson) {
  if (detailJson === null || detailJson === undefined) return null
  if (typeof detailJson === 'object') return detailJson
  try {
    return JSON.parse(detailJson)
  } catch {
    return { raw: String(detailJson) }
  }
}

function formatDetail(detailJson) {
  const obj = parseDetail(detailJson)
  if (!obj) return '（无详情）'
  return JSON.stringify(obj, null, 2)
}

function previewDetail(detailJson) {
  const obj = parseDetail(detailJson)
  if (!obj) return '—'
  const s = JSON.stringify(obj)
  return s && s.length > 60 ? `${s.slice(0, 60)}…` : s
}

async function loadData() {
  loading.value = true
  try {
    const { data } = await getAuditLogs(page.value, pageSize.value)
    items.value = data.items || []
    total.value = data.total || 0
  } catch (err) {
    ElMessage.error(err.response?.data?.error || '操作日志加载失败')
  } finally {
    loading.value = false
  }
}

function handlePageChange() {
  loadData()
}

onMounted(loadData)
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

.detail-block {
  padding: 4px 16px;
}

.detail-label {
  font-size: 13px;
  color: #606266;
  margin-bottom: 6px;
}

.detail-json {
  margin: 0;
  padding: 10px 12px;
  background: #EAF6FB;
  border-radius: 4px;
  font-family: Consolas, Menlo, monospace;
  font-size: 12px;
  line-height: 1.6;
  color: #303133;
  max-height: 260px;
  overflow: auto;
  white-space: pre-wrap;
  word-break: break-all;
}

.detail-preview {
  font-size: 13px;
  color: #606266;
}

.pager {
  display: flex;
  justify-content: flex-end;
  margin-top: 14px;
}
</style>