<template>
  <div class="page-card">
    <div class="toolbar">
      <div class="toolbar-left">
        <span class="toolbar-title">设备列表（{{ list.length }} 台）</span>
        <el-tag :type="onlineCount > 0 ? 'success' : 'info'" size="small">
          在线 {{ onlineCount }} 台
        </el-tag>
      </div>
      <div class="toolbar-right">
        <span class="auto-label">自动刷新（30s）</span>
        <el-switch v-model="autoRefresh" />
        <el-button :loading="loading" @click="loadList">
          <el-icon style="margin-right: 4px"><Refresh /></el-icon>
          刷新
        </el-button>
      </div>
    </div>

    <el-table :data="sortedList" border stripe v-loading="loading">
      <el-table-column prop="device_uuid" label="设备 UUID" min-width="240" show-overflow-tooltip />
      <el-table-column prop="device_name" label="设备名" min-width="140" show-overflow-tooltip />
      <el-table-column label="教室名" min-width="160">
        <template #default="{ row }">
          <span>{{ row.room_name || '—' }}</span>
          <el-button link type="primary" size="small" @click="openEditRoom(row)">
            修改
          </el-button>
        </template>
      </el-table-column>
      <el-table-column prop="ip" label="IP 地址" min-width="130">
        <template #default="{ row }">{{ row.ip || '—' }}</template>
      </el-table-column>
      <el-table-column prop="client_version" label="客户端版本" min-width="120">
        <template #default="{ row }">{{ row.client_version || '—' }}</template>
      </el-table-column>
      <el-table-column prop="update_pending_version" label="待更新" min-width="110" align="center">
        <template #default="{ row }">
          <el-tag v-if="row.update_pending_version" type="warning" size="small">
            {{ row.update_pending_version }}
          </el-tag>
          <span v-else class="muted">—</span>
        </template>
      </el-table-column>
      <el-table-column prop="last_heartbeat" label="最后心跳" min-width="170">
        <template #default="{ row }">{{ row.last_heartbeat || '—' }}</template>
      </el-table-column>
      <el-table-column label="在线状态" width="100" align="center">
        <template #default="{ row }">
          <el-tag :type="row.online ? 'success' : 'info'">
            {{ row.online ? '在线' : '离线' }}
          </el-tag>
        </template>
      </el-table-column>
    </el-table>

    <!-- 修改教室名 -->
    <el-dialog v-model="roomVisible" title="修改教室名" width="400px" :close-on-click-modal="false">
      <div class="room-device">
        设备：<b>{{ roomForm.deviceName || roomForm.deviceUuid }}</b>
      </div>
      <el-form label-width="80px">
        <el-form-item label="教室名">
          <el-input
            v-model="roomForm.roomName"
            placeholder="如：高一（2）班"
            maxlength="128"
            clearable
          />
        </el-form-item>
      </el-form>
      <template #footer>
        <el-button @click="roomVisible = false">取消</el-button>
        <el-button type="primary" :loading="roomSubmitting" @click="submitRoom">确定</el-button>
      </template>
    </el-dialog>
  </div>
</template>

<script setup>
import { ref, reactive, computed, onMounted, onBeforeUnmount, watch } from 'vue'
import { ElMessage } from 'element-plus'
import { getDevices, updateDeviceRoom } from '../api'

const REFRESH_INTERVAL = 30 * 1000

const list = ref([])
const loading = ref(false)
const autoRefresh = ref(true)
let timer = null

const roomVisible = ref(false)
const roomSubmitting = ref(false)
const roomForm = reactive({
  id: null,
  deviceUuid: '',
  deviceName: '',
  roomName: ''
})

const onlineCount = computed(() => list.value.filter((d) => d.online).length)
const sortedList = computed(() => {
  const arr = [...list.value]
  arr.sort((a, b) => {
    if (a.online !== b.online) return a.online ? -1 : 1
    return 0
  })
  return arr
})

async function loadList() {
  loading.value = true
  try {
    const { data } = await getDevices()
    list.value = data.items || []
  } catch (err) {
    ElMessage.error(err.response?.data?.error || '设备列表加载失败')
  } finally {
    loading.value = false
  }
}

function startTimer() {
  if (timer) clearInterval(timer)
  timer = setInterval(() => {
    loadList()
  }, REFRESH_INTERVAL)
}

function stopTimer() {
  if (timer) {
    clearInterval(timer)
    timer = null
  }
}

watch(autoRefresh, (val) => {
  if (val) startTimer()
  else stopTimer()
})

function openEditRoom(row) {
  roomForm.id = row.id
  roomForm.deviceUuid = row.device_uuid
  roomForm.deviceName = row.device_name
  roomForm.roomName = row.room_name || ''
  roomVisible.value = true
}

async function submitRoom() {
  roomSubmitting.value = true
  try {
    await updateDeviceRoom(roomForm.id, roomForm.roomName.trim())
    ElMessage.success('教室名已更新')
    roomVisible.value = false
    await loadList()
  } catch (err) {
    ElMessage.error(err.response?.data?.error || '教室名修改失败')
  } finally {
    roomSubmitting.value = false
  }
}

onMounted(() => {
  loadList()
  if (autoRefresh.value) startTimer()
})

onBeforeUnmount(() => {
  stopTimer()
})
</script>

<style scoped>
.toolbar {
  display: flex;
  align-items: center;
  justify-content: space-between;
  margin-bottom: 14px;
}

.toolbar-left {
  display: flex;
  align-items: center;
  gap: 10px;
}

.toolbar-title {
  font-size: 14px;
  font-weight: 600;
  color: #1f2329;
}

.toolbar-right {
  display: flex;
  align-items: center;
  gap: 10px;
}

.auto-label {
  font-size: 13px;
  color: #606266;
}

.room-device {
  margin-bottom: 14px;
  color: #606266;
  font-size: 13px;
  overflow: hidden;
  text-overflow: ellipsis;
  white-space: nowrap;
}

.muted {
  color: #c0c4cc;
}
</style>