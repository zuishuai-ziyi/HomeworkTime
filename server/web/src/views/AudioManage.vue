<template>
  <div class="page-card">
    <div class="toolbar">
      <div class="toolbar-title">已上传音频（{{ list.length }} 个）</div>
      <el-upload
        :show-file-list="false"
        :before-upload="beforeUpload"
        :http-request="doUpload"
        accept=".wav"
      >
        <el-button type="primary" :loading="uploading">
          <el-icon style="margin-right: 4px"><Upload /></el-icon>
          上传音频（.wav）
        </el-button>
      </el-upload>
    </div>

    <el-table :data="list" border stripe v-loading="loading">
      <el-table-column prop="id" label="ID" width="70" align="center" />
      <el-table-column prop="filename" label="文件名" min-width="220" show-overflow-tooltip />
      <el-table-column label="大小" width="120" align="right">
        <template #default="{ row }">{{ formatSize(row.size) }}</template>
      </el-table-column>
      <el-table-column label="SHA256" min-width="180">
        <template #default="{ row }">
          <span v-if="row.sha256" class="sha" :title="row.sha256">{{ truncate(row.sha256) }}</span>
          <span v-else class="muted">—</span>
        </template>
      </el-table-column>
      <el-table-column label="类型" width="100" align="center">
        <template #default="{ row }">
          <el-tag v-if="row.is_builtin" type="info" size="small">内置</el-tag>
          <el-tag v-else type="warning" size="small">上传</el-tag>
        </template>
      </el-table-column>
      <el-table-column label="上传人" width="120">
        <template #default="{ row }">{{ row.uploaded_by || '—' }}</template>
      </el-table-column>
      <el-table-column prop="created_at" label="上传时间" width="180" />
      <el-table-column label="操作" width="100" align="center">
        <template #default="{ row }">
          <el-button
            type="danger"
            link
            :disabled="!!row.is_builtin"
            @click="handleDelete(row)"
          >
            删除
          </el-button>
        </template>
      </el-table-column>
    </el-table>
  </div>
</template>

<script setup>
import { ref, onMounted } from 'vue'
import { ElMessage, ElMessageBox } from 'element-plus'
import { getAudioList, uploadAudio, deleteAudio } from '../api'

const list = ref([])
const loading = ref(false)
const uploading = ref(false)

async function loadList() {
  loading.value = true
  try {
    const { data } = await getAudioList()
    list.value = data.items || []
  } catch (err) {
    ElMessage.error(err.response?.data?.error || '音频列表加载失败')
  } finally {
    loading.value = false
  }
}

function beforeUpload(file) {
  if (!/\.wav$/i.test(file.name)) {
    ElMessage.error('仅允许上传 .wav 音频文件')
    return false
  }
  return true
}

async function doUpload({ file }) {
  uploading.value = true
  try {
    await uploadAudio(file)
    ElMessage.success(`上传成功：${file.name}`)
    await loadList()
  } catch (err) {
    ElMessage.error(err.response?.data?.error || '上传失败')
  } finally {
    uploading.value = false
  }
}

function handleDelete(row) {
  ElMessageBox.confirm(
    `确定删除音频「${row.filename}」吗？删除后不可恢复。`,
    '删除音频',
    {
      confirmButtonText: '删除',
      cancelButtonText: '取消',
      type: 'warning'
    }
  )
    .then(async () => {
      try {
        await deleteAudio(row.id)
        ElMessage.success('删除成功')
        await loadList()
      } catch (err) {
        ElMessage.error(err.response?.data?.error || '删除失败')
      }
    })
    .catch(() => {})
}

function formatSize(bytes) {
  if (bytes === null || bytes === undefined) return '—'
  const n = Number(bytes)
  if (n < 1024) return `${n} B`
  if (n < 1024 * 1024) return `${(n / 1024).toFixed(1)} KB`
  return `${(n / 1024 / 1024).toFixed(2)} MB`
}

function truncate(sha, len = 16) {
  if (!sha) return ''
  return sha.length > len ? `${sha.slice(0, len)}…` : sha
}

onMounted(loadList)
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

.sha {
  font-family: Consolas, Menlo, monospace;
  font-size: 12px;
  color: #606266;
}

.muted {
  color: #c0c4cc;
}
</style>