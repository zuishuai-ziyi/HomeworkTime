<template>
  <div class="page-card">
    <div class="toolbar">
      <span class="toolbar-title">客户端远程更新（全量推送）</span>
    </div>

    <el-alert
      class="tip"
      type="info"
      :closable="false"
      show-icon
      title="更新机制说明"
      description="上传的 zip 为最新版本应用程序整包（build.py 自动产出）。上传并发布后：离线设备会在下次联网心跳时自动下载（支持延迟更新）；到生效时间后自动替换并重启，若该时刻正处于晚自习时段则顺延至晚自习结束后执行。发布新包会替换现有包（不保留历史版本，回滚需重新上传旧包）。"
    />

    <!-- 当前已发布版本 -->
    <el-descriptions
      v-if="current"
      class="block"
      title="当前已发布版本"
      :column="2"
      border
    >
      <el-descriptions-item label="版本号">
        <el-tag type="success">{{ current.version }}</el-tag>
      </el-descriptions-item>
      <el-descriptions-item label="大小">{{ formatSize(current.size) }}</el-descriptions-item>
      <el-descriptions-item label="生效时间">
        <span>{{ current.effective_time }}</span>
        <el-button link type="primary" size="small" @click="openEditTime">
          修改
        </el-button>
      </el-descriptions-item>
      <el-descriptions-item label="发布时间">{{ current.published_at }}</el-descriptions-item>
      <el-descriptions-item label="更新说明" :span="2">
        {{ current.notes || '—' }}
      </el-descriptions-item>
      <el-descriptions-item label="SHA256" :span="2">
        <span class="sha" :title="current.sha256">{{ current.sha256 }}</span>
      </el-descriptions-item>
      <el-descriptions-item label="上传人">
        {{ current.uploaded_by || '—' }}
      </el-descriptions-item>
    </el-descriptions>
    <el-alert
      v-else
      class="block"
      type="info"
      :closable="false"
      show-icon
      title="尚未发布过更新包，客户端将保持当前版本运行"
    />

    <!-- 发布新版本 -->
    <div class="section-title">发布新版本</div>
    <el-form class="upload-form" label-width="90px">
      <el-form-item label="更新包">
        <el-upload
          ref="uploadRef"
          :auto-upload="false"
          :limit="1"
          :on-change="onFileChange"
          :on-remove="onFileRemove"
          :on-exceed="onExceed"
          accept=".zip"
          drag
          class="upload-area"
        >
          <el-icon class="el-icon--upload"><UploadFilled /></el-icon>
          <div class="el-upload__text">
            拖拽 zip 到此处，或<em>点击选择</em>
          </div>
          <template #tip>
            <div class="el-upload__tip">
              HomeworkTime_版本号.zip（由 client/build.py 自动产出，上限 500MB）
            </div>
          </template>
        </el-upload>
      </el-form-item>
      <el-form-item label="版本号">
        <el-input
          v-model="form.version"
          placeholder="如 1.1.0（选择文件后自动带出，需与包内一致）"
          maxlength="32"
          style="max-width: 320px"
        />
      </el-form-item>
      <el-form-item label="更新说明">
        <el-input
          v-model="form.notes"
          type="textarea"
          :rows="3"
          placeholder="本次更新内容（可选，最长 500 字）"
          maxlength="500"
          show-word-limit
          style="max-width: 520px"
        />
      </el-form-item>
      <el-form-item label="生效时间">
        <el-switch v-model="form.immediate" active-text="立即生效" />
        <el-date-picker
          v-if="!form.immediate"
          v-model="form.effectiveTime"
          type="datetime"
          placeholder="选择客户端执行更新的时间"
          value-format="YYYY-MM-DD HH:mm:ss"
          :disabled-date="(d) => d.getTime() < Date.now() - 86400000"
          style="margin-left: 12px"
        />
        <div class="form-tip">
          建议选择非晚自习时段（如上午 8:00）；到点时设备若正处于晚自习，会顺延至晚自习结束后执行。
        </div>
      </el-form-item>
      <el-form-item>
        <el-button type="primary" :loading="uploading" :disabled="!canSubmit" @click="submitUpload">
          <el-icon style="margin-right: 4px"><Upload /></el-icon>
          上传并发布
        </el-button>
      </el-form-item>
    </el-form>

    <!-- 修改生效时间 -->
    <el-dialog v-model="timeVisible" title="修改生效时间" width="420px" :close-on-click-modal="false">
      <el-date-picker
        v-model="timeForm.effectiveTime"
        type="datetime"
        placeholder="选择新的生效时间"
        value-format="YYYY-MM-DD HH:mm:ss"
        style="width: 100%"
      />
      <div class="form-tip" style="margin-top: 8px">
        修改后所有设备按新时间执行更新；已过期的时间会被视为立即生效。
      </div>
      <template #footer>
        <el-button @click="timeVisible = false">取消</el-button>
        <el-button type="primary" :loading="timeSubmitting" @click="submitTime">确定</el-button>
      </template>
    </el-dialog>
  </div>
</template>

<script setup>
import { ref, reactive, computed, onMounted } from 'vue'
import { ElMessage, ElMessageBox } from 'element-plus'
import { getUpdateInfo, uploadUpdate, updateEffectiveTime } from '../api'

const current = ref(null)
const loading = ref(false)
const uploading = ref(false)
const uploadRef = ref(null)

const form = reactive({
  file: null,
  version: '',
  notes: '',
  immediate: true,
  effectiveTime: ''
})

const timeVisible = ref(false)
const timeSubmitting = ref(false)
const timeForm = reactive({ effectiveTime: '' })

const canSubmit = computed(
  () => !!form.file && /^[0-9A-Za-z][0-9A-Za-z.+-]{0,31}$/.test(form.version) &&
    (form.immediate || !!form.effectiveTime)
)

async function loadInfo() {
  loading.value = true
  try {
    const { data } = await getUpdateInfo()
    current.value = data.item || null
  } catch (err) {
    ElMessage.error(err.response?.data?.error || '更新信息加载失败')
  } finally {
    loading.value = false
  }
}

function onFileChange(file) {
  if (!file) return
  if (file.status !== 'ready') return
  if (!/\.zip$/i.test(file.name)) {
    ElMessage.error('仅允许上传 .zip 更新包')
    // 从上传列表移除，允许用户重新选择
    uploadRef.value?.clearFiles()
    form.file = null
    return
  }
  form.file = file.raw
  // 从文件名自动带出版本号（未手动填写时）
  if (!form.version) {
    const m = /_([0-9]+\.[0-9]+\.[0-9]+(?:[-+][0-9A-Za-z.+-]+)?)\.zip$/i.exec(file.name)
    if (m) form.version = m[1]
  }
}

function onFileRemove() {
  form.file = null
}

/** limit=1 时再次选择文件：用新文件替换旧文件 */
function onExceed(files) {
  uploadRef.value?.clearFiles()
  const file = files?.[0]
  if (file) uploadRef.value?.handleStart(file)
}

function submitUpload() {
  const eff = form.immediate ? '' : form.effectiveTime
  const whenText = form.immediate ? '立即生效' : `于 ${form.effectiveTime} 生效`
  ElMessageBox.confirm(
    `确定发布版本 ${form.version} 吗？${whenText}，全部设备将自动更新到此版本（替换当前已发布的包）。`,
    '发布更新',
    { confirmButtonText: '发布', cancelButtonText: '取消', type: 'warning' }
  )
    .then(async () => {
      uploading.value = true
      try {
        await uploadUpdate(form.file, form.version.trim(), form.notes.trim(), eff)
        ElMessage.success(`版本 ${form.version} 已发布`)
        uploadRef.value?.clearFiles()
        form.file = null
        form.version = ''
        form.notes = ''
        form.immediate = true
        form.effectiveTime = ''
        await loadInfo()
      } catch (err) {
        ElMessage.error(err.response?.data?.error || '上传发布失败')
      } finally {
        uploading.value = false
      }
    })
    .catch(() => {})
}

function openEditTime() {
  timeForm.effectiveTime = current.value?.effective_time || ''
  timeVisible.value = true
}

function submitTime() {
  if (!timeForm.effectiveTime) {
    ElMessage.error('请选择生效时间')
    return
  }
  timeSubmitting.value = true
  updateEffectiveTime(timeForm.effectiveTime)
    .then(() => {
      ElMessage.success('生效时间已更新')
      timeVisible.value = false
      loadInfo()
    })
    .catch((err) => {
      ElMessage.error(err.response?.data?.error || '生效时间修改失败')
    })
    .finally(() => {
      timeSubmitting.value = false
    })
}

function formatSize(bytes) {
  if (bytes === null || bytes === undefined) return '—'
  const n = Number(bytes)
  if (n < 1024) return `${n} B`
  if (n < 1024 * 1024) return `${(n / 1024).toFixed(1)} KB`
  return `${(n / 1024 / 1024).toFixed(2)} MB`
}

onMounted(loadInfo)
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

.tip {
  margin-bottom: 16px;
}

.block {
  margin-bottom: 22px;
}

.section-title {
  font-size: 14px;
  font-weight: 600;
  color: #1f2329;
  margin-bottom: 14px;
  padding-top: 6px;
  border-top: 1px solid #e4e7ed;
}

.upload-area {
  width: 100%;
  max-width: 560px;
}

.upload-form :deep(.el-upload-dragger) {
  padding: 20px 0;
}

.sha {
  font-family: Consolas, Menlo, monospace;
  font-size: 12px;
  color: #606266;
  word-break: break-all;
}

.form-tip {
  font-size: 12px;
  color: #909399;
  line-height: 1.6;
  margin-top: 4px;
}
</style>
