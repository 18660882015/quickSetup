<script setup>
import { ref, reactive, onMounted } from 'vue'
import { ElMessage, ElMessageBox } from 'element-plus'
import {
  Plus,
  Edit,
  Delete,
  Connection,
  View,
  Refresh,
  Cpu,
  Coin,
  FolderOpened
} from '@element-plus/icons-vue'
import { getHosts, createHost, updateHost, deleteHost, testHost, inspectHost } from '@/api/host'
import { statusColor, statusText } from '@/utils/format'

// 主机列表
const hosts = ref([])
const loading = ref(false)
const searchKeyword = ref('')

// 过滤后的主机列表
const filteredHosts = ref([])

function filterHosts() {
  const kw = searchKeyword.value.trim().toLowerCase()
  if (!kw) {
    filteredHosts.value = hosts.value
    return
  }
  filteredHosts.value = hosts.value.filter(
    (h) =>
      h.name?.toLowerCase().includes(kw) ||
      h.ip?.toLowerCase().includes(kw) ||
      h.username?.toLowerCase().includes(kw)
  )
}

// 拉取主机列表
async function fetchHosts() {
  loading.value = true
  try {
    const res = await getHosts()
    hosts.value = res.data || []
    filterHosts()
  } catch (e) {
    // 错误由拦截器处理
  } finally {
    loading.value = false
  }
}

// ---- 添加/编辑弹窗 ----
const dialogVisible = ref(false)
const dialogTitle = ref('添加主机')
const isEdit = ref(false)
const submitting = ref(false)
const formRef = ref(null)

const defaultForm = () => ({
  name: '',
  ip: '',
  port: 22,
  username: 'root',
  password: '',
  auth_type: 'password',
  private_key: '',
  jdk_version: '17',
  deploy_dir: '/opt/app',
  backup_dir: '/opt/app/backup',
  is_local: false
})

const form = reactive(defaultForm())

const rules = {
  name: [{ required: true, message: '请输入主机名称', trigger: 'blur' }],
  ip: [{ required: true, message: '请输入主机 IP', trigger: 'blur' }],
  port: [{ required: true, message: '请输入端口', trigger: 'blur' }],
  username: [{ required: true, message: '请输入用户名', trigger: 'blur' }],
  jdk_version: [{ required: true, message: '请选择 JDK 版本', trigger: 'change' }],
  deploy_dir: [{ required: true, message: '请输入部署目录', trigger: 'blur' }]
}

function openAddDialog() {
  isEdit.value = false
  dialogTitle.value = '添加主机'
  Object.assign(form, defaultForm())
  dialogVisible.value = true
}

function openEditDialog(row) {
  isEdit.value = true
  dialogTitle.value = '编辑主机'
  Object.assign(form, defaultForm())
  Object.assign(form, {
    name: row.name,
    ip: row.ip,
    port: row.port,
    username: row.username,
    auth_type: row.auth_type || 'password',
    private_key: '',
    jdk_version: row.jdk_version || '17',
    deploy_dir: row.deploy_dir || '/opt/app',
    backup_dir: row.backup_dir || '/opt/app/backup',
    is_local: row.is_local || false
  })
  // 编辑时 id 单独存
  editingId.value = row.id
  dialogVisible.value = true
}

const editingId = ref(null)

// 本地主机切换
function handleLocalChange(val) {
  if (val) {
    form.port = form.port || 22
    form.username = form.username || 'root'
    form.deploy_dir = form.deploy_dir || 'C:\\app'
  }
}

// 提交表单
async function handleSubmit() {
  if (!formRef.value) return
  await formRef.value.validate(async (valid) => {
    if (!valid) return
    submitting.value = true
    try {
      const payload = { ...form }
      // 密钥认证时清空密码，密码认证时清空密钥
      if (payload.auth_type === 'key') {
        delete payload.password
      } else {
        delete payload.private_key
      }
      // 编辑时若密码为空则不传
      if (isEdit.value && !payload.password) {
        delete payload.password
      }

      if (isEdit.value) {
        await updateHost(editingId.value, payload)
        ElMessage.success('主机更新成功')
      } else {
        await createHost(payload)
        ElMessage.success('主机添加成功')
      }
      dialogVisible.value = false
      await fetchHosts()
    } catch (e) {
      // 错误由拦截器处理
    } finally {
      submitting.value = false
    }
  })
}

// ---- 测试连接 ----
const testingId = ref(null)

async function handleTestConnection(row) {
  testingId.value = row.id
  try {
    const res = await testHost(row.id)
    const data = res.data || {}
    if (data.success !== false) {
      ElMessage.success(`连接成功：${data.os_info || data.message || 'SSH 连接正常'}`)
    } else {
      ElMessage.error(`连接失败：${data.message || '未知错误'}`)
    }
    // 测试后刷新状态
    await fetchHosts()
  } catch (e) {
    // 错误由拦截器处理
  } finally {
    testingId.value = null
  }
}

// ---- 查看主机参数 ----
const inspectVisible = ref(false)
const inspectLoading = ref(false)
const inspectData = ref(null)
const inspectHostInfo = ref(null)

async function handleInspect(row) {
  inspectHostInfo.value = row
  inspectVisible.value = true
  inspectLoading.value = true
  inspectData.value = null
  try {
    const res = await inspectHost(row.id)
    inspectData.value = res.data || {}
  } catch (e) {
    // 错误由拦截器处理
  } finally {
    inspectLoading.value = false
  }
}

// ---- 删除主机 ----
async function handleDelete(row) {
  try {
    await ElMessageBox.confirm(
      `确定要删除主机「${row.name}」(${row.ip}) 吗？此操作不可恢复。`,
      '删除确认',
      {
        confirmButtonText: '确定删除',
        cancelButtonText: '取消',
        type: 'warning'
      }
    )
    await deleteHost(row.id)
    ElMessage.success('主机已删除')
    await fetchHosts()
  } catch (e) {
    // 用户取消或错误
  }
}

// JDK 版本选项
const jdkOptions = [
  { label: 'JDK 8', value: '8' },
  { label: 'JDK 17', value: '17' }
]

// 格式化主机类型
function hostTypeText(isLocal) {
  return isLocal ? '本地' : '远程'
}

function hostTypeTag(isLocal) {
  return isLocal ? 'success' : 'primary'
}

onMounted(fetchHosts)
</script>

<template>
  <div class="host-manage">
    <!-- 操作栏 -->
    <el-card shadow="never" class="toolbar-card">
      <div class="toolbar">
        <div class="toolbar-left">
          <el-input
            v-model="searchKeyword"
            placeholder="搜索主机名称/IP/用户名"
            clearable
            style="width: 260px"
            :prefix-icon="'Search'"
            @input="filterHosts"
          />
        </div>
        <div class="toolbar-right">
          <el-button :icon="Refresh" @click="fetchHosts" :loading="loading">刷新</el-button>
          <el-button type="primary" :icon="Plus" @click="openAddDialog">添加主机</el-button>
        </div>
      </div>
    </el-card>

    <!-- 主机表格 -->
    <el-card shadow="never" class="table-card">
      <el-table
        :data="filteredHosts"
        v-loading="loading"
        stripe
        style="width: 100%"
        empty-text="暂无主机，请点击「添加主机」"
      >
        <el-table-column prop="name" label="名称" min-width="140" show-overflow-tooltip />
        <el-table-column label="类型" width="80">
          <template #default="{ row }">
            <el-tag :type="hostTypeTag(row.is_local)" size="small">
              {{ hostTypeText(row.is_local) }}
            </el-tag>
          </template>
        </el-table-column>
        <el-table-column prop="ip" label="IP 地址" min-width="130" show-overflow-tooltip />
        <el-table-column prop="port" label="端口" width="80" />
        <el-table-column prop="jdk_version" label="JDK" width="80">
          <template #default="{ row }">
            <el-tag size="small" effect="plain">JDK {{ row.jdk_version || '-' }}</el-tag>
          </template>
        </el-table-column>
        <el-table-column label="状态" width="90">
          <template #default="{ row }">
            <el-tag :type="statusColor(row.status)" size="small">
              {{ statusText(row.status) }}
            </el-tag>
          </template>
        </el-table-column>
        <el-table-column label="操作" width="280" fixed="right">
          <template #default="{ row }">
            <el-button
              size="small"
              :icon="Connection"
              :loading="testingId === row.id"
              @click="handleTestConnection(row)"
            >
              测试连接
            </el-button>
            <el-button size="small" :icon="View" @click="handleInspect(row)">查看参数</el-button>
            <el-button size="small" :icon="Edit" @click="openEditDialog(row)">编辑</el-button>
            <el-button size="small" type="danger" :icon="Delete" @click="handleDelete(row)">
              删除
            </el-button>
          </template>
        </el-table-column>
      </el-table>
    </el-card>

    <!-- 添加/编辑弹窗 -->
    <el-dialog
      v-model="dialogVisible"
      :title="dialogTitle"
      width="640px"
      :close-on-click-modal="false"
      destroy-on-close
    >
      <el-form
        ref="formRef"
        :model="form"
        :rules="rules"
        label-width="100px"
        label-position="right"
      >
        <el-form-item label="是否本地" prop="is_local">
          <el-switch v-model="form.is_local" @change="handleLocalChange" />
          <span class="form-tip">本地主机为 Windows 部署，远程主机为 Linux SSH 部署</span>
        </el-form-item>

        <el-form-item label="主机名称" prop="name">
          <el-input v-model="form.name" placeholder="如：生产服务器-01" />
        </el-form-item>

        <el-form-item label="IP 地址" prop="ip">
          <el-input v-model="form.ip" placeholder="如：192.168.1.100 或 127.0.0.1" />
        </el-form-item>

        <el-form-item label="端口" prop="port">
          <el-input-number v-model="form.port" :min="1" :max="65535" controls-position="right" style="width: 100%" />
        </el-form-item>

        <el-form-item label="用户名" prop="username">
          <el-input v-model="form.username" placeholder="如：root" />
        </el-form-item>

        <el-form-item label="认证方式" prop="auth_type">
          <el-radio-group v-model="form.auth_type">
            <el-radio value="password">密码认证</el-radio>
            <el-radio value="key">密钥认证</el-radio>
          </el-radio-group>
        </el-form-item>

        <el-form-item v-if="form.auth_type === 'password'" label="密码" prop="password">
          <el-input
            v-model="form.password"
            type="password"
            show-password
            :placeholder="isEdit ? '留空则不修改密码' : '请输入密码'"
          />
        </el-form-item>

        <el-form-item v-if="form.auth_type === 'key'" label="私钥" prop="private_key">
          <el-input
            v-model="form.private_key"
            type="textarea"
            :rows="4"
            :placeholder="isEdit ? '留空则不修改密钥' : '粘贴 SSH 私钥内容'"
          />
        </el-form-item>

        <el-form-item label="JDK 版本" prop="jdk_version">
          <el-select v-model="form.jdk_version" style="width: 100%">
            <el-option
              v-for="opt in jdkOptions"
              :key="opt.value"
              :label="opt.label"
              :value="opt.value"
            />
          </el-select>
        </el-form-item>

        <el-form-item label="部署目录" prop="deploy_dir">
          <el-input v-model="form.deploy_dir" :placeholder="form.is_local ? 'C:\\app' : '/opt/app'" />
        </el-form-item>

        <el-form-item label="备份目录" prop="backup_dir">
          <el-input v-model="form.backup_dir" :placeholder="form.is_local ? 'C:\\app\\backup' : '/opt/app/backup'" />
        </el-form-item>
      </el-form>

      <template #footer>
        <el-button @click="dialogVisible = false">取消</el-button>
        <el-button type="primary" :loading="submitting" @click="handleSubmit">
          {{ isEdit ? '保存修改' : '添加主机' }}
        </el-button>
      </template>
    </el-dialog>

    <!-- 查看主机参数弹窗 -->
    <el-dialog
      v-model="inspectVisible"
      title="主机参数信息"
      width="680px"
      destroy-on-close
    >
      <div v-loading="inspectLoading">
        <template v-if="inspectData">
          <el-descriptions :column="2" border>
            <el-descriptions-item label="主机名称">{{ inspectHostInfo?.name }}</el-descriptions-item>
            <el-descriptions-item label="IP 地址">{{ inspectHostInfo?.ip }}:{{ inspectHostInfo?.port }}</el-descriptions-item>
            <el-descriptions-item label="操作系统" :span="2">
              {{ inspectData.os_info || inspectData.os || '-' }}
            </el-descriptions-item>
            <el-descriptions-item label="CPU">
              <div class="inspect-line">
                <el-icon><Cpu /></el-icon>
                <span>{{ inspectData.cpu_info || inspectData.cpu_model || '-' }}</span>
              </div>
              <div class="inspect-line" v-if="inspectData.cpu_usage != null">
                使用率：{{ inspectData.cpu_usage }}%
              </div>
            </el-descriptions-item>
            <el-descriptions-item label="内存">
              <div class="inspect-line">
                <el-icon><Coin /></el-icon>
                <span v-if="inspectData.memory_total">
                  总量 {{ inspectData.memory_total }} / 已用 {{ inspectData.memory_used || '-' }}
                </span>
                <span v-else>{{ inspectData.memory_info || '-' }}</span>
              </div>
              <div class="inspect-line" v-if="inspectData.memory_usage != null">
                使用率：{{ inspectData.memory_usage }}%
              </div>
            </el-descriptions-item>
            <el-descriptions-item label="磁盘" :span="2">
              <div class="inspect-line">
                <el-icon><FolderOpened /></el-icon>
                <span v-if="inspectData.disk_total">
                  总量 {{ inspectData.disk_total }} / 已用 {{ inspectData.disk_used || '-' }}
                </span>
                <span v-else>{{ inspectData.disk_info || '-' }}</span>
              </div>
              <div class="inspect-line" v-if="inspectData.disk_usage != null">
                使用率：{{ inspectData.disk_usage }}%
              </div>
            </el-descriptions-item>
          </el-descriptions>

          <!-- 服务状态 -->
          <div class="service-section" v-if="inspectData.services">
            <div class="section-title">服务状态</div>
            <div class="service-grid">
              <div
                v-for="(status, name) in inspectData.services"
                :key="name"
                class="service-item"
                :class="{ running: status === 'running' || status === true, stopped: status === 'stopped' || status === false }"
              >
                <el-icon :size="18">
                  <component :is="status === 'running' || status === true ? 'CircleCheck' : 'CircleClose'" />
                </el-icon>
                <span class="service-name">{{ name }}</span>
                <el-tag
                  :type="status === 'running' || status === true ? 'success' : 'danger'"
                  size="small"
                >
                  {{ status === 'running' || status === true ? '运行中' : '已停止' }}
                </el-tag>
              </div>
            </div>
          </div>
        </template>
        <el-empty v-else-if="!inspectLoading" description="暂无参数数据" />
      </div>

      <template #footer>
        <el-button @click="inspectVisible = false">关闭</el-button>
        <el-button type="primary" :loading="inspectLoading" @click="handleInspect(inspectHostInfo)">
          刷新参数
        </el-button>
      </template>
    </el-dialog>
  </div>
</template>

<style scoped>
.host-manage {
  display: flex;
  flex-direction: column;
  gap: 16px;
}

.toolbar-card {
  border-radius: 8px;
}

.toolbar {
  display: flex;
  align-items: center;
  justify-content: space-between;
  flex-wrap: wrap;
  gap: 12px;
}

.toolbar-left,
.toolbar-right {
  display: flex;
  align-items: center;
  gap: 8px;
}

.table-card {
  border-radius: 8px;
}

.form-tip {
  margin-left: 12px;
  font-size: 12px;
  color: #909399;
}

/* 主机参数弹窗 */
.inspect-line {
  display: flex;
  align-items: center;
  gap: 6px;
  font-size: 13px;
  line-height: 1.8;
}

.service-section {
  margin-top: 20px;
}

.section-title {
  font-size: 14px;
  font-weight: 600;
  color: #303133;
  margin-bottom: 12px;
}

.service-grid {
  display: grid;
  grid-template-columns: repeat(auto-fill, minmax(200px, 1fr));
  gap: 10px;
}

.service-item {
  display: flex;
  align-items: center;
  gap: 8px;
  padding: 10px 14px;
  border-radius: 6px;
  border: 1px solid #ebeef5;
}

.service-item.running {
  background-color: #f0f9eb;
  color: #67c23a;
}

.service-item.stopped {
  background-color: #fef0f0;
  color: #f56c6c;
}

.service-name {
  font-weight: 600;
  flex: 1;
}
</style>
