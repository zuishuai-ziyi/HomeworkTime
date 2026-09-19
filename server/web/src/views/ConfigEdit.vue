<template>
  <div class="page-card config-page">
    <!-- 顶部版本信息 -->
    <div class="config-head">
      <div class="config-meta">
        <el-tag type="primary" effect="dark" size="large">当前版本 v{{ version }}</el-tag>
        <span>更新时间：{{ updatedAt || '—' }}</span>
        <span>更新人：{{ updatedByName }}</span>
      </div>
      <el-button type="primary" size="large" :loading="saving" @click="handleSave">
        保存配置
      </el-button>
    </div>

    <el-form label-width="160px" label-position="left" class="config-form">
      <!-- 基本设置 -->
      <el-divider content-position="left">基本设置</el-divider>
      <el-form-item label="晚自习开始时间">
        <el-time-select
          v-model="form.evening_start"
          start="00:00"
          end="23:59"
          step="00:05"
          placeholder="选择开始时间"
        />
        <span class="tip">每天同一套时间段；end ≤ start 视为跨天（次日结束）</span>
      </el-form-item>
      <el-form-item label="晚自习结束时间">
        <el-time-select
          v-model="form.evening_end"
          start="00:00"
          end="23:59"
          step="00:05"
          placeholder="选择结束时间"
        />
      </el-form-item>

      <!-- 科目时间段 -->
      <el-divider content-position="left">科目时间段（最多 10 个）</el-divider>
      <el-form-item label=" " label-width="0">
        <div class="subject-block">
          <el-table :data="form.subjects" border stripe size="default">
            <el-table-column type="index" label="#" width="56" align="center" />
            <el-table-column label="科目名称" min-width="180">
              <template #default="{ row }">
                <el-input v-model="row.name" placeholder="如：语文" maxlength="32" />
              </template>
            </el-table-column>
            <el-table-column label="开始时间" width="190">
              <template #default="{ row }">
                <el-time-select
                  v-model="row.start"
                  start="00:00"
                  end="23:59"
                  step="00:05"
                  placeholder="开始"
                />
              </template>
            </el-table-column>
            <el-table-column label="结束时间" width="190">
              <template #default="{ row }">
                <el-time-select
                  v-model="row.end"
                  start="00:00"
                  end="23:59"
                  step="00:05"
                  placeholder="结束"
                />
              </template>
            </el-table-column>
            <el-table-column label="操作" width="100" align="center">
              <template #default="{ $index }">
                <el-button type="danger" link @click="removeSubject($index)">删除</el-button>
              </template>
            </el-table-column>
          </el-table>
          <div class="add-row">
            <el-button :disabled="form.subjects.length >= 10" @click="addSubject">
              添加科目
            </el-button>
            <span v-if="form.subjects.length >= 10" class="limit-tip">
              已达上限（10 个），可先删除再添加
            </span>
          </div>
        </div>
      </el-form-item>

      <!-- 外观 -->
      <el-divider content-position="left">外观（透明度）</el-divider>
      <el-form-item label="主窗口透明度">
        <div class="slider-wrap">
          <el-slider v-model="opacityPercent.main" :min="20" :max="100" :step="1" />
          <span class="slider-val">{{ opacityPercent.main }}%</span>
        </div>
      </el-form-item>
      <el-form-item label="悬浮球透明度">
        <div class="slider-wrap">
          <el-slider v-model="opacityPercent.ball" :min="20" :max="100" :step="1" />
          <span class="slider-val">{{ opacityPercent.ball }}%</span>
        </div>
      </el-form-item>
      <el-form-item label="配置窗口透明度">
        <div class="slider-wrap">
          <el-slider v-model="opacityPercent.config" :min="20" :max="100" :step="1" />
          <span class="slider-val">{{ opacityPercent.config }}%</span>
        </div>
      </el-form-item>

      <!-- 行为 -->
      <el-divider content-position="left">行为</el-divider>
      <el-form-item label="允许本地修改配置">
        <el-switch v-model="form.allow_local_edit" @change="onAllowLocalChange" />
        <span class="tip">关闭后客户端将隐藏本地配置入口，改为通过本后台修改</span>
      </el-form-item>
      <el-form-item label="空档期显示文本">
        <el-input
          v-model="form.idle_text"
          maxlength="64"
          placeholder="如：课间休息"
          style="width: 320px"
        />
        <span class="tip">落在晚自习区间但不属于任何科目段时显示的文字</span>
      </el-form-item>

      <!-- 提示音 -->
      <el-divider content-position="left">提示音（全局一套）</el-divider>
      <el-form-item label="提示音总开关">
        <el-switch v-model="form.sound.enabled" />
        <span class="tip">关闭后临近/结束提示音均不播放</span>
      </el-form-item>
      <el-form-item label="临近提示音阈值">
        <el-input-number v-model="form.sound.near_seconds" :min="1" :max="3600" step="1" :precision="0" />
        <span class="tip">秒，科目段结束前 N 秒开始每秒播放一次临近提示音</span>
      </el-form-item>
      <el-form-item label="临近提示音">
        <el-switch v-model="form.sound.near_enabled" style="margin-right: 12px" />
        <el-select v-model="form.sound.near_audio" placeholder="选择音频" style="width: 240px">
          <el-option v-for="f in audioOptions" :key="f" :label="f" :value="f" />
        </el-select>
        <span class="tip">仅 .wav，需先在音频管理页上传</span>
      </el-form-item>
      <el-form-item label="结束提示音">
        <el-switch v-model="form.sound.end_enabled" style="margin-right: 12px" />
        <el-select v-model="form.sound.end_audio" placeholder="选择音频" style="width: 240px">
          <el-option v-for="f in audioOptions" :key="f" :label="f" :value="f" />
        </el-select>
        <span class="tip">仅 .wav，需先在音频管理页上传</span>
      </el-form-item>
    </el-form>
  </div>
</template>

<script setup>
import { reactive, ref, computed, onMounted } from 'vue'
import { ElMessage, ElMessageBox } from 'element-plus'
import { getConfig, updateConfig, getUsers, getAudioList } from '../api'

const HHMM_RE = /^([01]\d|2[0-3]):[0-5]\d$/

const DEFAULT_SOUND = {
  enabled: true,
  near_seconds: 60,
  near_audio: 'near.wav',
  near_enabled: true,
  end_audio: 'end.wav',
  end_enabled: true
}

const saving = ref(false)
const version = ref(1)
const updatedAt = ref('')
const updatedBy = ref(null)
const userMap = new Map()
const audioOptions = ref([])

const form = reactive({
  evening_start: '18:30',
  evening_end: '22:00',
  subjects: [],
  allow_local_edit: true,
  idle_text: '',
  sound: { ...DEFAULT_SOUND }
})

// 透明度滑条用 20~100 的百分比展示，保存时换算回 0.2~1.0
const opacityPercent = reactive({ main: 85, ball: 70, config: 100 })

const updatedByName = computed(() => {
  if (!updatedBy.value) return '系统初始化'
  return userMap.get(updatedBy.value) || `用户 #${updatedBy.value}`
})

function applyConfig(data) {
  const c = data.config || {}
  form.evening_start = c.evening_start || ''
  form.evening_end = c.evening_end || ''
  form.subjects = JSON.parse(JSON.stringify(c.subjects || []))
  form.allow_local_edit = !!c.allow_local_edit
  form.idle_text = c.idle_text || ''
  form.sound = { ...DEFAULT_SOUND, ...(c.sound || {}) }
  const op = c.opacity || {}
  opacityPercent.main = Math.round((op.main ?? 0.85) * 100)
  opacityPercent.ball = Math.round((op.ball ?? 0.7) * 100)
  opacityPercent.config = Math.round((op.config ?? 1) * 100)
}

function syncMeta(data) {
  version.value = data.version
  updatedAt.value = data.updated_at || ''
  updatedBy.value = data.updated_by ?? null
}

async function loadConfig() {
  const { data } = await getConfig()
  syncMeta(data)
  applyConfig(data)
}

async function loadUsers() {
  try {
    const { data } = await getUsers()
    userMap.clear()
    ;(data.items || []).forEach((u) => userMap.set(u.id, u.username))
  } catch (e) {
    /* 用户名映射失败不影响页面使用 */
  }
}

async function loadAudioOptions() {
  try {
    const { data } = await getAudioList()
    audioOptions.value = (data.items || []).map((i) => i.filename)
  } catch (e) {
    /* 音频列表拉取失败时下拉留空 */
  }
}

function addSubject() {
  if (form.subjects.length >= 10) {
    ElMessage.warning('科目数量已达上限（10 个）')
    return
  }
  form.subjects.push({ name: '', start: '', end: '' })
}

function removeSubject(index) {
  form.subjects.splice(index, 1)
}

function onAllowLocalChange(val) {
  if (val) return
  ElMessageBox.confirm(
    '关闭后将禁止客户端本地修改配置，确定要关闭吗？',
    '二次确认',
    { confirmButtonText: '确定关闭', cancelButtonText: '取消', type: 'warning' }
  )
    .then(() => {
      ElMessage.info('已关闭本地修改配置权限')
    })
    .catch(() => {
      form.allow_local_edit = true
    })
}

function validate() {
  const errors = []
  if (!HHMM_RE.test(form.evening_start || '')) {
    errors.push('晚自习开始时间必须为 HH:MM 格式（如 18:30）')
  }
  if (!HHMM_RE.test(form.evening_end || '')) {
    errors.push('晚自习结束时间必须为 HH:MM 格式（如 22:00）')
  }
  if (form.subjects.length > 10) {
    errors.push('科目数量不能超过 10 个')
  }
  form.subjects.forEach((s, i) => {
    const pos = `第 ${i + 1} 行`
    if (!s.name || !s.name.trim()) {
      errors.push(`${pos}：科目名称不能为空`)
    } else if (s.name.trim().length > 32) {
      errors.push(`${pos}：科目名称不能超过 32 个字符`)
    }
    if (!HHMM_RE.test(s.start || '')) {
      errors.push(`${pos}：开始时间格式不正确（HH:MM）`)
    }
    if (!HHMM_RE.test(s.end || '')) {
      errors.push(`${pos}：结束时间格式不正确（HH:MM）`)
    }
    if (s.start && s.end && s.start === s.end) {
      errors.push(`${pos}：开始时间不能等于结束时间`)
    }
  })
  return errors
}

function buildPayload() {
  return {
    evening_start: form.evening_start || '',
    evening_end: form.evening_end || '',
    subjects: form.subjects.map((s) => ({
      name: (s.name || '').trim(),
      start: s.start || '',
      end: s.end || ''
    })),
    opacity: {
      main: opacityPercent.main / 100,
      ball: opacityPercent.ball / 100,
      config: opacityPercent.config / 100
    },
    allow_local_edit: !!form.allow_local_edit,
    idle_text: (form.idle_text || '').trim(),
    sound: { ...form.sound }
  }
}

function showBackendErrors(err) {
  const resp = err.response?.data
  const list = []
  if (Array.isArray(resp?.errors)) {
    list.push(...resp.errors.map((e) => `· ${e}`))
  }
  if (resp?.error && !Array.isArray(resp?.errors)) {
    list.push(`· ${resp.error}`)
  }
  if (!list.length) list.push('· 保存失败，请稍后重试')
  // 纯文本展示，禁用 HTML 渲染（防 XSS）；配合 .ht-config-error-alert 的
  // white-space: pre-line 保留换行
  ElMessageBox.alert(list.join('\n'), '配置保存失败', {
    confirmButtonText: '知道了',
    customClass: 'ht-config-error-alert'
  })
}

async function handleSave() {
  const errors = validate()
  if (errors.length) {
    ElMessage.error(errors.join('；'))
    return
  }
  saving.value = true
  try {
    const { data } = await updateConfig(buildPayload())
    syncMeta(data)
    applyConfig(data)
    ElMessage.success(`配置已保存，当前版本 v${data.version}`)
  } catch (err) {
    showBackendErrors(err)
  } finally {
    saving.value = false
  }
}

onMounted(() => {
  loadConfig().catch((e) => {
    ElMessage.error(e.response?.data?.error || '配置加载失败')
  })
  loadUsers()
  loadAudioOptions()
})
</script>

<style scoped>
.config-head {
  display: flex;
  align-items: center;
  justify-content: space-between;
  padding-bottom: 14px;
  border-bottom: 1px solid #ADE8F4;
  margin-bottom: 4px;
}

.config-meta {
  display: flex;
  align-items: center;
  gap: 12px;
  font-size: 13px;
  color: #606266;
}

.config-form {
  margin-top: 8px;
}

.tip {
  margin-left: 12px;
  font-size: 12px;
  color: #909399;
}

.subject-block {
  width: 100%;
}

.add-row {
  margin-top: 12px;
  display: flex;
  align-items: center;
  gap: 12px;
}

.limit-tip {
  font-size: 12px;
  color: #e6a23c;
}

.slider-wrap {
  display: flex;
  align-items: center;
  gap: 12px;
  width: 100%;
  max-width: 480px;
}

.slider-val {
  width: 48px;
  text-align: right;
  font-size: 14px;
  color: #1f2329;
  flex-shrink: 0;
}

.el-form-item {
  margin-bottom: 18px;
}
</style>

<!-- 全局（非 scoped）：配置保存失败弹窗的纯文本换行展示（不使用 HTML 渲染） -->
<style>
.ht-config-error-alert .el-message-box__message {
  white-space: pre-line;
}
</style>