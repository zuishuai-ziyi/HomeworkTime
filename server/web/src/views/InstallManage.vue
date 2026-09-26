<template>
  <div class="page-card">
    <div class="toolbar">
      <span class="toolbar-title">一键安装（PowerShell 命令分发）</span>
      <el-button link type="primary" @click="openSinkSettings">
        <el-icon style="margin-right: 4px"><Setting /></el-icon>
        短链服务设置
      </el-button>
    </div>

    <el-alert
      class="tip"
      type="info"
      :closable="false"
      show-icon
      title="一键安装机制"
      description="上传客户端整包 zip（build.py 产物可直接复用）后，服务端为该包生成一条 PowerShell 一键安装命令，在目标机 PowerShell 中执行即自动完成「结束旧进程 → 下载 → 解压 → 写入连接配置 → 启动」。脚本与安装包通过随机 slug 地址下载（slug 即凭据，请勿外传）；「写入连接配置」开启时按「客户端 Token」页当前值内嵌 Token，Token 重置后新执行的安装自动使用新 Token。"
    />

    <!-- 上传新安装包 -->
    <div class="section-title">上传新安装包</div>
    <el-form class="upload-form" label-width="120px">
      <el-form-item label="安装包">
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
              HomeworkTime_版本号.zip（client/build.py 产物，上限 500MB）
            </div>
          </template>
        </el-upload>
      </el-form-item>
      <el-form-item label="版本号">
        <el-input
          v-model="form.version"
          placeholder="可空（选择文件后自动带出）"
          maxlength="32"
          style="max-width: 320px"
        />
      </el-form-item>
      <el-form-item label="备注">
        <el-input
          v-model="form.notes"
          type="textarea"
          :rows="2"
          placeholder="可选，最长 500 字"
          maxlength="500"
          show-word-limit
          style="max-width: 520px"
        />
      </el-form-item>
      <el-form-item label="安装目录">
        <el-input
          v-model="form.installDir"
          placeholder="C:\HomeworkTime"
          maxlength="240"
          style="max-width: 320px"
        />
        <div class="form-tip">
          目标机上的绝对路径，需可写；若提示拒绝访问，请在目标机以管理员身份运行 PowerShell。
        </div>
      </el-form-item>
      <el-form-item label="客户端服务器地址">
        <el-input
          v-model="form.clientBaseUrl"
          placeholder="http://homeworktime.example.com:81"
          maxlength="240"
          style="max-width: 420px"
        />
        <div class="form-tip">
          目标机（教室一体机）需能访问该地址；安装脚本下载与 local_config.json 均使用它。
        </div>
      </el-form-item>
      <el-form-item label="写入连接配置">
        <el-switch v-model="form.embedConfig" />
        <div class="form-tip">
          开启：脚本写入 local_config.json（服务器地址 + 当前 Token + 开机自启），客户端首启免引导；
          关闭：首次启动弹出引导窗口，需现场填写。
        </div>
      </el-form-item>
      <el-form-item>
        <el-button type="primary" :loading="uploading" :disabled="!canSubmit" @click="submitUpload">
          <el-icon style="margin-right: 4px"><Upload /></el-icon>
          上传并生成安装命令
        </el-button>
      </el-form-item>
    </el-form>

    <!-- 安装包列表 -->
    <div class="section-title">安装包列表</div>
    <el-table :data="items" v-loading="loading" border stripe>
      <el-table-column label="版本" width="90">
        <template #default="{ row }">
          <el-tag v-if="row.version" type="success">{{ row.version }}</el-tag>
          <span v-else>—</span>
        </template>
      </el-table-column>
      <el-table-column prop="filename" label="文件名" min-width="200" show-overflow-tooltip />
      <el-table-column label="大小" width="90">
        <template #default="{ row }">{{ formatSize(row.size) }}</template>
      </el-table-column>
      <el-table-column prop="install_dir" label="安装目录" min-width="140" show-overflow-tooltip />
      <el-table-column prop="client_base_url" label="客户端服务器地址" min-width="180" show-overflow-tooltip />
      <el-table-column label="连接配置" width="90">
        <template #default="{ row }">
          <el-tag :type="row.embed_config ? 'primary' : 'info'">
            {{ row.embed_config ? '内嵌' : '引导' }}
          </el-tag>
        </template>
      </el-table-column>
      <el-table-column label="状态" width="80">
        <template #default="{ row }">
          <el-switch
            :model-value="row.enabled"
            :loading="row._statusSaving"
            @change="(val) => onToggleEnabled(row, val)"
          />
        </template>
      </el-table-column>
      <el-table-column prop="download_count" label="下载次数" width="90" />
      <el-table-column label="创建" width="170">
        <template #default="{ row }">
          <div>{{ row.created_by || '—' }}</div>
          <div class="cell-sub">{{ row.created_at }}</div>
        </template>
      </el-table-column>
      <el-table-column label="操作" width="180" fixed="right">
        <template #default="{ row }">
          <el-button link type="primary" @click="openCommand(row)">安装命令</el-button>
          <el-button link type="primary" :disabled="!row.enabled" @click="openShortlink(row)">
            短链
          </el-button>
          <el-button link type="danger" @click="confirmDelete(row)">删除</el-button>
        </template>
      </el-table-column>
    </el-table>

    <!-- 安装命令对话框 -->
    <el-dialog v-model="commandVisible" title="PowerShell 一键安装命令" width="720px" :close-on-click-modal="false">
      <template v-if="commandRow">
        <el-descriptions :column="1" border size="small" class="block">
          <el-descriptions-item label="版本">{{ commandRow.version || '—' }}</el-descriptions-item>
          <el-descriptions-item label="脚本地址">
            <span class="mono">{{ commandRow.script_url }}</span>
          </el-descriptions-item>
        </el-descriptions>
        <template v-if="commandRow.short_url">
          <el-alert
            class="block"
            type="success"
            :closable="false"
            show-icon
            title="该安装包已生成短链，目标机安装推荐使用以下短链命令（更短，便于口头转达 / 手工敲入）。"
          />
          <el-form label-width="110px" class="block">
            <el-form-item label="短链">
              <el-input :model-value="commandRow.short_url" readonly class="mono">
                <template #append>
                  <el-button @click="copyText(commandRow.short_url)">
                    <el-icon><CopyDocument /></el-icon>
                  </el-button>
                </template>
              </el-input>
            </el-form-item>
            <el-form-item label="短链安装命令">
              <el-input
                :model-value="commandRow.short_command"
                readonly
                :rows="3"
                type="textarea"
                class="mono"
              />
            </el-form-item>
          </el-form>
          <div style="margin-bottom: 10px; text-align: right">
            <el-button type="primary" @click="copyText(commandRow.short_command)">
              <el-icon style="margin-right: 4px"><CopyDocument /></el-icon>
              复制短链命令
            </el-button>
          </div>
        </template>
        <el-alert
          v-else
          class="block"
          type="info"
          :closable="false"
          show-icon
          title="尚未生成短链；可直接使用下面的完整命令，或通过列表「生成短链」获得更短的命令。"
        />
        <el-alert
          class="block"
          type="warning"
          :closable="false"
          show-icon
          title="在目标机的 PowerShell 中执行以下命令（建议管理员身份）。脚本地址含随机 slug 即下载凭据，请勿泄露到不可信渠道。"
        />
        <el-input :model-value="commandRow.command" readonly :rows="3" type="textarea" class="mono" />
        <div style="margin-top: 10px; text-align: right">
          <el-button type="primary" @click="copyText(commandRow.command)">
            <el-icon style="margin-right: 4px"><CopyDocument /></el-icon>
            复制命令
          </el-button>
        </div>
      </template>
    </el-dialog>

    <!-- 生成短链对话框 -->
    <el-dialog v-model="shortlinkVisible" title="生成短链（Sink 短链服务）" width="640px" :close-on-click-modal="false">
      <template v-if="shortlinkRow">
        <el-alert
          class="block"
          type="info"
          :closable="false"
          show-icon
          title="通过自托管 Sink 短链服务把脚本地址缩短为短链，方便口头转达或手工敲入。可勾选「保存到服务器」记住服务地址与 API Key，下次免输入（Key 仅脱敏回显，不会展示明文）。"
        />
        <el-form label-width="110px">
          <el-form-item label="Sink 服务地址">
            <el-input
              v-model="sinkForm.url"
              placeholder="https://s.example.com"
              maxlength="240"
            />
          </el-form-item>
          <el-form-item label="API Key">
            <el-input
              v-model="sinkForm.apiKey"
              type="password"
              show-password
              :placeholder="apiKeyPlaceholder"
            />
          </el-form-item>
          <el-form-item label="自定义 slug">
            <el-input
              v-model="sinkForm.slug"
              placeholder="可空 = 自动生成，如 ht-install"
              maxlength="64"
            />
          </el-form-item>
          <el-form-item label="">
            <el-checkbox v-model="sinkForm.save">保存到服务器（所有管理员共享，下次免输入）</el-checkbox>
          </el-form-item>
        </el-form>
        <div style="text-align: right">
          <el-button type="primary" :loading="shortlinkSubmitting" @click="submitShortlink">
            <el-icon style="margin-right: 4px"><Link /></el-icon>
            生成短链
          </el-button>
        </div>
        <template v-if="shortlinkResult">
          <el-divider />
          <el-alert
            v-if="shortlinkResult.existing"
            class="block"
            type="success"
            :closable="false"
            show-icon
            title="以下为该安装包已生成的短链，可直接复制使用；如需更换可重新生成。"
          />
          <el-form label-width="110px">
            <el-form-item label="短链">
              <el-input :model-value="shortlinkResult.short_url" readonly class="mono">
                <template #append>
                  <el-button @click="copyText(shortlinkResult.short_url)">
                    <el-icon><CopyDocument /></el-icon>
                  </el-button>
                </template>
              </el-input>
            </el-form-item>
            <el-form-item label="短链安装命令">
              <el-input
                :model-value="shortlinkResult.command"
                readonly
                :rows="3"
                type="textarea"
                class="mono"
              />
            </el-form-item>
          </el-form>
          <div style="text-align: right">
            <el-button type="primary" @click="copyText(shortlinkResult.command)">
              <el-icon style="margin-right: 4px"><CopyDocument /></el-icon>
              复制短链命令
            </el-button>
          </div>
        </template>
      </template>
    </el-dialog>

    <!-- Sink 短链服务设置对话框 -->
    <el-dialog v-model="sinkSettingsVisible" title="Sink 短链服务设置" width="560px" :close-on-click-modal="false">
      <el-alert
        class="block"
        type="info"
        :closable="false"
        show-icon
        title="保存后生成短链时自动使用该配置，所有管理端浏览器共享；API Key 加密保存于服务器数据库，页面仅脱敏回显。"
      />
      <el-descriptions :column="1" border size="small" class="block">
        <el-descriptions-item label="已保存 Key">
          <span v-if="sinkSaved.hasKey" class="mono">{{ sinkSaved.masked }}</span>
          <el-tag v-else type="info">未保存</el-tag>
        </el-descriptions-item>
        <el-descriptions-item label="更新时间">{{ sinkSaved.updatedAt || '—' }}</el-descriptions-item>
      </el-descriptions>
      <el-form label-width="110px">
        <el-form-item label="Sink 服务地址">
          <el-input
            v-model="sinkSettingsForm.url"
            placeholder="https://s.example.com"
            maxlength="240"
          />
        </el-form-item>
        <el-form-item label="API Key">
          <el-input
            v-model="sinkSettingsForm.apiKey"
            type="password"
            show-password
            :placeholder="sinkSaved.hasKey ? '留空保持已保存 Key 不变' : 'Sink 后台令牌（NUXT_SITE_TOKEN 或 sk_ 开头的 API Key）'"
          />
        </el-form-item>
      </el-form>
      <div style="text-align: right">
        <el-button type="primary" :loading="sinkSettingsSaving" @click="submitSinkSettings">
          <el-icon style="margin-right: 4px"><Check /></el-icon>
          保存配置
        </el-button>
      </div>
    </el-dialog>
  </div>
</template>

<script setup>
import { ref, reactive, computed, onMounted } from 'vue'
import { ElMessage, ElMessageBox } from 'element-plus'
import {
  getInstalls,
  createInstall,
  updateInstall,
  deleteInstall,
  createInstallShortlink,
  getSinkSettings,
  saveSinkSettings
} from '../api'

const items = ref([])
const loading = ref(false)
const uploading = ref(false)
const uploadRef = ref(null)

const form = reactive({
  file: null,
  version: '',
  notes: '',
  installDir: 'C:\\HomeworkTime',
  clientBaseUrl: window.location.origin,
  embedConfig: true
})

const commandVisible = ref(false)
const commandRow = ref(null)

const shortlinkVisible = ref(false)
const shortlinkRow = ref(null)
const shortlinkSubmitting = ref(false)
const shortlinkResult = ref(null)
const sinkForm = reactive({ url: '', apiKey: '', slug: '', save: true })

/** 服务端已保存的 Sink 配置（Key 仅脱敏回显） */
const sinkSaved = reactive({ url: '', hasKey: false, masked: '', updatedAt: '' })

/** 未保存 Key 时必填，已保存时可留空沿用 */
const apiKeyPlaceholder = computed(() =>
  sinkSaved.hasKey
    ? `留空使用已保存的 Key（${sinkSaved.masked}）`
    : 'Sink 后台令牌（NUXT_SITE_TOKEN 或 sk_ 开头的 API Key）'
)

const sinkSettingsVisible = ref(false)
const sinkSettingsSaving = ref(false)
const sinkSettingsForm = reactive({ url: '', apiKey: '' })

const canSubmit = computed(() => {
  return !!form.file &&
    /^[A-Za-z]:\\[^'"]{1,240}$/.test(form.installDir.trim()) &&
    /^https?:\/\/[^\s'"]+$/.test(form.clientBaseUrl.trim())
})

async function loadSinkSettings() {
  try {
    const { data } = await getSinkSettings()
    sinkSaved.url = data.sink_url || ''
    sinkSaved.hasKey = !!data.api_key_set
    sinkSaved.masked = data.api_key_masked || ''
    sinkSaved.updatedAt = data.updated_at || ''
  } catch (err) {
    // 配置读取失败不阻塞短链功能（仍可每次手工输入）
  }
}

async function loadList() {
  loading.value = true
  try {
    const { data } = await getInstalls()
    items.value = (data.items || []).map((it) => ({ ...it, _statusSaving: false }))
  } catch (err) {
    ElMessage.error(err.response?.data?.error || '安装包列表加载失败')
  } finally {
    loading.value = false
  }
}

function onFileChange(file) {
  if (!file) return
  if (file.status !== 'ready') return
  if (!/\.zip$/i.test(file.name)) {
    ElMessage.error('仅允许上传 .zip 安装包')
    uploadRef.value?.clearFiles()
    form.file = null
    return
  }
  form.file = file.raw
  // 从文件名自动带出版本号（未手动填写时），与更新管理一致
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

async function submitUpload() {
  uploading.value = true
  try {
    const { data } = await createInstall(form.file, {
      version: form.version.trim(),
      notes: form.notes.trim(),
      install_dir: form.installDir.trim(),
      client_base_url: form.clientBaseUrl.trim(),
      embed_config: form.embedConfig ? '1' : '0'
    })
    ElMessage.success('安装包已上传，安装入口已创建')
    uploadRef.value?.clearFiles()
    form.file = null
    form.version = ''
    form.notes = ''
    await loadList()
    // 上传完成后直接弹出该条目的安装命令
    const created = data.item
    const row = items.value.find((it) => it.id === created?.id)
    if (row) openCommand(row)
  } catch (err) {
    ElMessage.error(err.response?.data?.error || '上传失败')
  } finally {
    uploading.value = false
  }
}

function openCommand(row) {
  commandRow.value = row
  commandVisible.value = true
}

/** 打开 Sink 短链服务设置对话框（回填已保存的服务地址） */
function openSinkSettings() {
  sinkSettingsForm.url = sinkSaved.url
  sinkSettingsForm.apiKey = ''
  sinkSettingsVisible.value = true
}

/** 保存 Sink 配置到服务器（Key 留空 = 保持已保存 Key 不变） */
async function submitSinkSettings() {
  if (!sinkSettingsForm.url.trim()) {
    ElMessage.error('请填写 Sink 服务地址')
    return
  }
  if (!sinkSaved.hasKey && !sinkSettingsForm.apiKey.trim()) {
    ElMessage.error('首次保存请填写 API Key')
    return
  }
  sinkSettingsSaving.value = true
  try {
    const { data } = await saveSinkSettings({
      sink_url: sinkSettingsForm.url.trim(),
      api_key: sinkSettingsForm.apiKey.trim()
    })
    sinkSaved.url = data.sink_url || ''
    sinkSaved.hasKey = !!data.api_key_set
    sinkSaved.masked = data.api_key_masked || ''
    sinkSaved.updatedAt = data.updated_at || ''
    ElMessage.success('短链服务配置已保存')
    sinkSettingsVisible.value = false
  } catch (err) {
    ElMessage.error(err.response?.data?.error || '保存失败')
  } finally {
    sinkSettingsSaving.value = false
  }
}

function openShortlink(row) {
  shortlinkRow.value = row
  // 已生成过短链 → 直接展示，免重新生成
  shortlinkResult.value = row.short_url
    ? { short_url: row.short_url, command: row.short_command, existing: true }
    : null
  sinkForm.slug = ''
  sinkForm.apiKey = ''
  // 预填服务端已保存的服务地址（没有则留空待填）
  sinkForm.url = sinkSaved.url
  shortlinkVisible.value = true
}

async function submitShortlink() {
  const url = sinkForm.url.trim()
  const apiKey = sinkForm.apiKey.trim()
  if (!url) {
    ElMessage.error('请填写 Sink 服务地址')
    return
  }
  if (!apiKey && !sinkSaved.hasKey) {
    ElMessage.error('请填写 API Key（首次使用必填，或先在「短链服务设置」中保存）')
    return
  }
  shortlinkSubmitting.value = true
  try {
    if (sinkForm.save) {
      // 先落库（Key 留空 = 保持已保存 Key），失败则中止本次生成
      const { data: saved } = await saveSinkSettings({ sink_url: url, api_key: apiKey })
      sinkSaved.url = saved.sink_url || ''
      sinkSaved.hasKey = !!saved.api_key_set
      sinkSaved.masked = saved.api_key_masked || ''
      sinkSaved.updatedAt = saved.updated_at || ''
    }
    const { data } = await createInstallShortlink(shortlinkRow.value.id, {
      sink_url: url,
      sink_api_key: apiKey,
      slug: sinkForm.slug.trim()
    })
    shortlinkResult.value = data
    // 同步列表行（安装命令对话框与短链对话框共用同一行对象）
    const row = items.value.find((it) => it.id === shortlinkRow.value.id)
    if (row) {
      row.short_url = data.short_url
      row.short_command = data.command
    }
    ElMessage.success(data.status === 'existing' ? '短链已存在，直接复用' : '短链创建成功')
  } catch (err) {
    ElMessage.error(err.response?.data?.error || '短链生成失败')
  } finally {
    shortlinkSubmitting.value = false
  }
}

async function onToggleEnabled(row, val) {
  row._statusSaving = true
  try {
    await updateInstall(row.id, { enabled: !!val })
    row.enabled = !!val
    ElMessage.success(val ? '已启用' : '已停用（脚本与安装包下载立即 404）')
  } catch (err) {
    ElMessage.error(err.response?.data?.error || '状态修改失败')
  } finally {
    row._statusSaving = false
  }
}

function confirmDelete(row) {
  ElMessageBox.confirm(
    `确定删除该安装包吗？删除后对应安装命令立即失效（脚本与安装包下载返回 404）。`,
    '删除安装包',
    { confirmButtonText: '删除', cancelButtonText: '取消', type: 'warning' }
  )
    .then(async () => {
      try {
        await deleteInstall(row.id)
        ElMessage.success('已删除')
        await loadList()
      } catch (err) {
        ElMessage.error(err.response?.data?.error || '删除失败')
      }
    })
    .catch(() => {})
}

async function copyText(text) {
  try {
    await navigator.clipboard.writeText(text)
    ElMessage.success('已复制到剪贴板')
  } catch (e) {
    // 非安全上下文（http）降级：临时 textarea + execCommand
    const ta = document.createElement('textarea')
    ta.value = text
    ta.style.position = 'fixed'
    ta.style.opacity = '0'
    document.body.appendChild(ta)
    ta.select()
    try {
      document.execCommand('copy')
      ElMessage.success('已复制到剪贴板')
    } catch (err) {
      ElMessage.error('复制失败，请手动选择复制')
    }
    document.body.removeChild(ta)
  }
}

function formatSize(bytes) {
  if (bytes === null || bytes === undefined) return '—'
  const n = Number(bytes)
  if (n < 1024) return `${n} B`
  if (n < 1024 * 1024) return `${(n / 1024).toFixed(1)} KB`
  return `${(n / 1024 / 1024).toFixed(2)} MB`
}

onMounted(() => {
  loadList()
  loadSinkSettings()
})
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
  margin-bottom: 16px;
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

.form-tip {
  font-size: 12px;
  color: #909399;
  line-height: 1.6;
  margin-top: 4px;
  width: 100%;
}

.cell-sub {
  font-size: 12px;
  color: #909399;
}

.mono {
  font-family: Consolas, Menlo, monospace;
  font-size: 12px;
}
</style>
