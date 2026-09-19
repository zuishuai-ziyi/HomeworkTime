<template>
  <div class="page-card">
    <div class="toolbar">
      <div class="toolbar-title">后台用户（{{ list.length }} 个）</div>
      <el-button type="primary" @click="openAdd">
        <el-icon style="margin-right: 4px"><Plus /></el-icon>
        新增用户
      </el-button>
    </div>

    <el-table :data="list" border stripe v-loading="loading">
      <el-table-column prop="id" label="ID" width="70" align="center" />
      <el-table-column prop="username" label="用户名" min-width="180" />
      <el-table-column prop="created_at" label="创建时间" width="200" />
      <el-table-column label="操作" width="180" align="center">
        <template #default="{ row }">
          <el-button type="primary" link @click="openChangePwd(row)">修改密码</el-button>
          <el-button type="danger" link @click="handleDelete(row)">删除</el-button>
        </template>
      </el-table-column>
    </el-table>

    <!-- 新增用户 -->
    <el-dialog v-model="addVisible" title="新增用户" width="420px" :close-on-click-modal="false">
      <el-form ref="addFormRef" :model="addForm" :rules="addRules" label-width="80px">
        <el-form-item label="用户名" prop="username">
          <el-input v-model="addForm.username" placeholder="登录用户名" maxlength="64" />
        </el-form-item>
        <el-form-item label="密码" prop="password">
          <el-input
            v-model="addForm.password"
            type="password"
            placeholder="至少 6 位"
            show-password
          />
        </el-form-item>
      </el-form>
      <template #footer>
        <el-button @click="addVisible = false">取消</el-button>
        <el-button type="primary" :loading="submitting" @click="submitAdd">确定</el-button>
      </template>
    </el-dialog>

    <!-- 修改密码 -->
    <el-dialog v-model="pwdVisible" title="修改密码" width="420px" :close-on-click-modal="false">
      <div class="pwd-user">用户：<b>{{ pwdForm.username }}</b></div>
      <el-form ref="pwdFormRef" :model="pwdForm" :rules="pwdRules" label-width="80px">
        <el-form-item label="新密码" prop="password">
          <el-input
            v-model="pwdForm.password"
            type="password"
            placeholder="至少 6 位"
            show-password
          />
        </el-form-item>
      </el-form>
      <template #footer>
        <el-button @click="pwdVisible = false">取消</el-button>
        <el-button type="primary" :loading="submitting" @click="submitPwd">确定</el-button>
      </template>
    </el-dialog>
  </div>
</template>

<script setup>
import { ref, reactive, onMounted } from 'vue'
import { ElMessage, ElMessageBox } from 'element-plus'
import { getUsers, createUser, updateUser, deleteUser } from '../api'

const list = ref([])
const loading = ref(false)
const submitting = ref(false)

const addVisible = ref(false)
const addFormRef = ref(null)
const addForm = reactive({ username: '', password: '' })
const addRules = {
  username: [
    { required: true, message: '请输入用户名', trigger: 'blur' },
    { min: 1, max: 64, message: '用户名长度为 1~64 字符', trigger: 'blur' }
  ],
  password: [
    { required: true, message: '请输入密码', trigger: 'blur' },
    { min: 6, message: '密码长度至少 6 位', trigger: 'blur' }
  ]
}

const pwdVisible = ref(false)
const pwdFormRef = ref(null)
const pwdForm = reactive({ id: null, username: '', password: '' })
const pwdRules = {
  password: [
    { required: true, message: '请输入新密码', trigger: 'blur' },
    { min: 6, message: '密码长度至少 6 位', trigger: 'blur' }
  ]
}

function showError(err, fallback) {
  ElMessage.error(err.response?.data?.error || fallback)
}

async function loadList() {
  loading.value = true
  try {
    const { data } = await getUsers()
    list.value = data.items || []
  } catch (err) {
    showError(err, '用户列表加载失败')
  } finally {
    loading.value = false
  }
}

function openAdd() {
  addForm.username = ''
  addForm.password = ''
  addVisible.value = true
}

async function submitAdd() {
  const valid = await addFormRef.value.validate().catch(() => false)
  if (!valid) return
  submitting.value = true
  try {
    await createUser({
      username: addForm.username.trim(),
      password: addForm.password
    })
    ElMessage.success('新增用户成功')
    addVisible.value = false
    await loadList()
  } catch (err) {
    showError(err, '新增用户失败')
  } finally {
    submitting.value = false
  }
}

function openChangePwd(row) {
  pwdForm.id = row.id
  pwdForm.username = row.username
  pwdForm.password = ''
  pwdVisible.value = true
}

async function submitPwd() {
  const valid = await pwdFormRef.value.validate().catch(() => false)
  if (!valid) return
  submitting.value = true
  try {
    await updateUser(pwdForm.id, { password: pwdForm.password })
    ElMessage.success('密码修改成功')
    pwdVisible.value = false
  } catch (err) {
    showError(err, '密码修改失败')
  } finally {
    submitting.value = false
  }
}

function handleDelete(row) {
  ElMessageBox.confirm(
    `确定删除用户「${row.username}」吗？删除后该账号将无法登录。`,
    '删除用户',
    {
      confirmButtonText: '删除',
      cancelButtonText: '取消',
      type: 'warning'
    }
  )
    .then(async () => {
      try {
        await deleteUser(row.id)
        ElMessage.success('删除成功')
        await loadList()
      } catch (err) {
        showError(err, '删除失败')
      }
    })
    .catch(() => {})
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

.pwd-user {
  margin-bottom: 14px;
  color: #606266;
}
</style>