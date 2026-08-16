<script setup>
import { ref, reactive, computed, nextTick } from 'vue'
import { ElMessage, ElMessageBox } from 'element-plus'
import {
  Monitor,
  Folder,
  Setting,
  Document,
  VideoPlay,
  ArrowLeft,
  ArrowRight,
  RefreshLeft,
  Back,
  Check,
  Close,
  WarningFilled,
  Link,
  Loading,
  Connection
} from '@element-plus/icons-vue'
import { getPlan, executeDeploy, rollbackDeploy } from '@/api/deploy'
import HostSelector from '@/components/HostSelector.vue'
import FileSelector from '@/components/FileSelector.vue'
import LogStream from '@/components/LogStream.vue'
import ConfirmDialog from '@/components/ConfirmDialog.vue'

// ---- 步骤定义 ----
const stepTitles = ['选择模式', '选择项目', '配置参数', '部署预览', '执行与日志']

// ---- 向导状态 ----
const wizard = reactive({
  activeStep: 0,
  // 步骤一
  deployMode: 'local', // local | remote
  hostId: null,
  hostInfo: null,
  // 步骤二
  projectName: '',
  project: null,
  // 步骤三
  config: {
    env_type: 'dev',
    jdk_version: '17',
    db_name: '',
    execute_mode: 'auto',
    nginx_port: 80,
    tomcat_port: 8080,
    showAdvanced: false
  },
  // 步骤四
  plan: null,
  planLoading: false,
  // 步骤五
  deployId: '',
  recordId: null,
  executing: false,
  deployResult: null // { status, accessUrl, validationResults, error }
})

// ---- 选项 ----
const envOptions = [
  { label: '开发环境 (dev)', value: 'dev' },
  { label: '生产环境 (prod)', value: 'prod' }
]

const jdkOptions = [
  { label: 'JDK 8', value: '8' },
  { label: 'JDK 17', value: '17' }
]

const executeModeOptions = [
  { label: '自动执行（仅危险操作确认）', value: 'auto' },
  { label: '逐步确认执行', value: 'step_by_step' }
]

// ---- 默认部署计划（AI 不可用时的降级方案） ----
const DEFAULT_PLAN = {
  steps: [
    {
      name: '环境预检',
      command: '检查端口占用、磁盘空间、JDK 版本',
      impact: '只读检查，无副作用',
      dangerous: false
    },
    {
      name: '备份当前版本',
      command: 'cp -r /opt/app /opt/app_backup_$(date +%Y%m%d%H%M%S)',
      impact: '创建备份目录，占用磁盘空间',
      dangerous: false
    },
    {
      name: '传输部署包',
      command: 'scp deploy.tar.gz user@host:/tmp/deploy/',
      impact: '上传文件到远程主机临时目录',
      dangerous: false
    },
    {
      name: '安装部署包',
      command: 'tar -xzf deploy.tar.gz -C /opt/app',
      impact: '解压覆盖部署目录',
      dangerous: false
    },
    {
      name: '配置服务',
      command: '更新 nginx.conf / server.xml 配置文件',
      impact: '修改 Nginx 和 Tomcat 配置文件',
      dangerous: false
    },
    {
      name: '启动服务',
      command: 'systemctl restart nginx tomcat',
      impact: '重启相关服务，服务短暂不可用',
      dangerous: true
    },
    {
      name: '验证部署',
      command: 'curl -I http://localhost && netstat -tlnp | grep :80',
      impact: '只读检查，无副作用',
      dangerous: false
    },
    {
      name: '清理临时文件',
      command: 'rm -rf /tmp/deploy_*',
      impact: '删除临时部署文件',
      dangerous: true
    }
  ]
}

// ---- 危险命令检测 ----
const DANGEROUS_PATTERNS = [
  /rm\s+-rf/i,
  /del\s+\/[fs]/i,
  /shutdown/i,
  /format\s+/i,
  /mkfs/i,
  /dd\s+if/i,
  />\s*\/dev\/sd/i,
  /chmod\s+777/i,
  /kill\s+-9/i,
  /systemctl\s+(stop|restart)/i
]

function isDangerous(command) {
  return DANGEROUS_PATTERNS.some((p) => p.test(command || ''))
}

// ---- 规范化计划步骤 ----
const planSteps = computed(() => {
  if (!wizard.plan) return []
  const rawSteps = wizard.plan.steps || wizard.plan.plan || []
  if (!Array.isArray(rawSteps)) return []
  return rawSteps.map((s, i) => {
    const name = s.name || s.step || s.title || `步骤 ${i + 1}`
    const command = s.command || s.cmd || s.action || ''
    const impact = s.impact || s.description || s.risk || ''
    const dangerous = s.dangerous != null ? !!s.dangerous : isDangerous(command)
    return { index: i + 1, name, command, impact, dangerous }
  })
})

// 危险步骤数量
const dangerousStepCount = computed(() => planSteps.value.filter((s) => s.dangerous).length)

// ---- 步骤导航 ----
const canNext = computed(() => {
  switch (wizard.activeStep) {
    case 0:
      return wizard.deployMode === 'local' || (wizard.deployMode === 'remote' && wizard.hostId)
    case 1:
      return !!wizard.projectName
    case 2:
      return !!wizard.config.env_type && !!wizard.config.jdk_version
    case 3:
      return !!wizard.plan
    default:
      return false
  }
})

async function handleNext() {
  if (!canNext.value) return
  // 步骤二 -> 步骤三：生成部署计划
  if (wizard.activeStep === 2) {
    await generatePlan()
    if (!wizard.plan) return
  }
  if (wizard.activeStep < 4) {
    wizard.activeStep++
  }
}

function handlePrev() {
  if (wizard.activeStep > 0 && wizard.activeStep < 4) {
    wizard.activeStep--
  }
}

// ---- HostSelector / FileSelector 事件 ----
function handleHostChange(host) {
  wizard.hostInfo = host
}

function handleProjectChange(project) {
  wizard.project = project
  // 自动填充数据库名
  if (project?.name && !wizard.config.db_name) {
    wizard.config.db_name = project.name.replace(/[-\s]/g, '_').toLowerCase()
  }
}

// ---- 生成部署计划 ----
async function generatePlan() {
  wizard.planLoading = true
  try {
    const payload = {
      host_id: wizard.deployMode === 'remote' ? wizard.hostId : null,
      project_name: wizard.projectName,
      env_type: wizard.config.env_type,
      jdk_version: wizard.config.jdk_version,
      db_name: wizard.config.db_name,
      is_local: wizard.deployMode === 'local',
      execute_mode: wizard.config.execute_mode,
      nginx_port: wizard.config.nginx_port,
      tomcat_port: wizard.config.tomcat_port
    }
    const res = await getPlan(payload)
    const data = res.data
    if (data && (data.steps || data.plan)) {
      wizard.plan = data
    } else {
      // AI 返回为空，使用默认计划
      wizard.plan = DEFAULT_PLAN
      ElMessage.info('AI 未返回有效计划，已使用默认部署计划')
    }
  } catch (e) {
    // AI 不可用，降级为默认计划
    wizard.plan = DEFAULT_PLAN
    ElMessage.info('AI 服务不可用，已降级为默认部署计划')
  } finally {
    wizard.planLoading = false
  }
}

// ---- 确认弹窗 ----
const confirmDialog = reactive({
  visible: false,
  title: '',
  command: '',
  impact: ''
})

// ---- 开始执行部署 ----
function handleStartDeploy() {
  const dangerousSteps = planSteps.value.filter((s) => s.dangerous)
  if (dangerousSteps.length > 0) {
    // 显示危险操作确认
    const step = dangerousSteps[0]
    confirmDialog.title = `危险操作确认：${step.name}`
    confirmDialog.command = step.command
    confirmDialog.impact = step.impact || '此操作具有风险，请确认后执行'
    confirmDialog.visible = true
  } else if (wizard.config.execute_mode === 'step_by_step') {
    // 逐步模式但没有危险步骤，仍需确认
    confirmDialog.title = '逐步确认执行'
    confirmDialog.command = '即将开始逐步执行部署流程'
    confirmDialog.impact = '每个步骤执行前将需要您确认'
    confirmDialog.visible = true
  } else {
    doStartDeploy()
  }
}

function handleConfirm() {
  doStartDeploy()
}

function handleConfirmCancel() {
  // 用户取消，留在当前步骤
}

async function doStartDeploy() {
  wizard.activeStep = 4
  wizard.executing = true
  wizard.deployResult = null
  wizard.deployId = '' // 先清空，确保 LogStream 重置

  await nextTick()

  try {
    const payload = {
      host_id: wizard.deployMode === 'remote' ? wizard.hostId : null,
      project_name: wizard.projectName,
      env_type: wizard.config.env_type,
      jdk_version: wizard.config.jdk_version,
      db_name: wizard.config.db_name,
      execute_mode: wizard.config.execute_mode,
      is_local: wizard.deployMode === 'local',
      nginx_port: wizard.config.nginx_port,
      tomcat_port: wizard.config.tomcat_port
    }
    const res = await executeDeploy(payload)
    const data = res.data || {}
    wizard.deployId = String(data.task_id || data.id || data.record_id || '')
    wizard.recordId = data.record_id || data.id || wizard.deployId
    if (!wizard.deployId) {
      throw new Error('未获取到部署任务 ID')
    }
  } catch (e) {
    wizard.executing = false
    wizard.deployResult = {
      status: 'failed',
      error: e.message || '部署启动失败，请检查后端服务'
    }
  }
}

// ---- LogStream 事件 ----
function handleLogComplete(result) {
  wizard.deployResult = {
    status: 'success',
    accessUrl: result.accessUrl || '',
    validationResults: result.validationResults || null
  }
  wizard.executing = false
}

function handleLogError(result) {
  wizard.deployResult = {
    status: result.status || 'failed',
    error: result.error || '部署执行失败'
  }
  wizard.executing = false
}

function handleLogStatusChange(status) {
  // 可扩展：根据状态更新 UI
}

// ---- 回滚 ----
const rollingBack = ref(false)

async function handleRollback() {
  try {
    await ElMessageBox.confirm(
      '确定要回滚到上一版本吗？回滚将恢复备份文件并重启服务。',
      '回滚确认',
      {
        confirmButtonText: '确定回滚',
        cancelButtonText: '取消',
        type: 'warning'
      }
    )
    rollingBack.value = true
    await rollbackDeploy(wizard.recordId)
    ElMessage.success('回滚成功，已恢复到上一版本')
    wizard.deployResult = {
      status: 'rolled_back',
      error: '部署已回滚到上一版本'
    }
  } catch (e) {
    // 用户取消或错误
  } finally {
    rollingBack.value = false
  }
}

// ---- 重试 ----
async function handleRetry() {
  wizard.deployId = ''
  wizard.deployResult = null
  await nextTick()
  doStartDeploy()
}

// ---- 重新开始 ----
function handleRestart() {
  wizard.activeStep = 0
  wizard.deployId = ''
  wizard.deployResult = null
  wizard.plan = null
  wizard.projectName = ''
  wizard.project = null
  wizard.deployMode = 'local'
  wizard.hostId = null
  wizard.hostInfo = null
  wizard.config = {
    env_type: 'dev',
    jdk_version: '17',
    db_name: '',
    execute_mode: 'auto',
    nginx_port: 80,
    tomcat_port: 8080,
    showAdvanced: false
  }
}

// ---- 访问地址 ----
const accessUrl = computed(() => {
  if (wizard.deployResult?.accessUrl) return wizard.deployResult.accessUrl
  const port = wizard.config.nginx_port || 80
  const host = wizard.deployMode === 'local' ? 'localhost' : wizard.hostInfo?.ip || 'localhost'
  return `http://${host}:${port}`
})

// 是否显示部署结果
const showResult = computed(() => wizard.deployResult && !wizard.executing)
const isSuccess = computed(() => wizard.deployResult?.status === 'success')
const isFailed = computed(() => wizard.deployResult?.status === 'failed')
const isRolledBack = computed(() => wizard.deployResult?.status === 'rolled_back')
</script>

<template>
  <div class="deploy-wizard">
    <!-- 步骤条 -->
    <el-card shadow="never" class="steps-card">
      <el-steps :active="wizard.activeStep" finish-status="success" align-center>
        <el-step v-for="(title, idx) in stepTitles" :key="idx" :title="title" />
      </el-steps>
    </el-card>

    <!-- 步骤内容 -->
    <el-card shadow="never" class="content-card">
      <!-- 步骤一：选择部署模式 -->
      <div v-show="wizard.activeStep === 0" class="step-content">
        <div class="step-header">
          <el-icon :size="24" color="#409EFF"><Monitor /></el-icon>
          <h3>选择部署模式</h3>
        </div>
        <el-radio-group v-model="wizard.deployMode" class="mode-group">
          <el-radio value="local" border>
            <div class="mode-card">
              <el-icon :size="32" color="#67C23A"><Monitor /></el-icon>
              <div class="mode-info">
                <div class="mode-title">本地部署</div>
                <div class="mode-desc">在当前 Windows 机器上部署，适用于本地开发环境</div>
              </div>
            </div>
          </el-radio>
          <el-radio value="remote" border>
            <div class="mode-card">
              <el-icon :size="32" color="#409EFF"><Connection /></el-icon>
              <div class="mode-info">
                <div class="mode-title">远程部署</div>
                <div class="mode-desc">通过 SSH 连接远程 Linux 主机进行部署</div>
              </div>
            </div>
          </el-radio>
        </el-radio-group>

        <!-- 远程模式：选择主机 -->
        <div v-if="wizard.deployMode === 'remote'" class="host-select-section">
          <div class="section-label">选择目标主机</div>
          <HostSelector
            v-model="wizard.hostId"
            filter-type="remote"
            @change="handleHostChange"
          />
          <div v-if="wizard.hostInfo" class="host-info-bar">
            <el-tag size="small" :type="wizard.hostInfo.status === 'online' ? 'success' : 'danger'">
              {{ wizard.hostInfo.status === 'online' ? '在线' : '离线' }}
            </el-tag>
            <span class="host-ip">{{ wizard.hostInfo.ip }}:{{ wizard.hostInfo.port }}</span>
            <span class="host-jdk">JDK {{ wizard.hostInfo.jdk_version || '-' }}</span>
          </div>
        </div>
      </div>

      <!-- 步骤二：选择项目 -->
      <div v-show="wizard.activeStep === 1" class="step-content">
        <div class="step-header">
          <el-icon :size="24" color="#409EFF"><Folder /></el-icon>
          <h3>选择部署项目</h3>
        </div>
        <FileSelector
          v-model="wizard.projectName"
          @change="handleProjectChange"
        />
      </div>

      <!-- 步骤三：配置部署参数 -->
      <div v-show="wizard.activeStep === 2" class="step-content">
        <div class="step-header">
          <el-icon :size="24" color="#409EFF"><Setting /></el-icon>
          <h3>配置部署参数</h3>
        </div>
        <el-form :model="wizard.config" label-width="120px" label-position="right" class="config-form">
          <el-row :gutter="20">
            <el-col :span="12">
              <el-form-item label="环境类型">
                <el-select v-model="wizard.config.env_type" style="width: 100%">
                  <el-option
                    v-for="opt in envOptions"
                    :key="opt.value"
                    :label="opt.label"
                    :value="opt.value"
                  />
                </el-select>
              </el-form-item>
            </el-col>
            <el-col :span="12">
              <el-form-item label="JDK 版本">
                <el-select v-model="wizard.config.jdk_version" style="width: 100%">
                  <el-option
                    v-for="opt in jdkOptions"
                    :key="opt.value"
                    :label="opt.label"
                    :value="opt.value"
                  />
                </el-select>
              </el-form-item>
            </el-col>
          </el-row>
          <el-row :gutter="20">
            <el-col :span="12">
              <el-form-item label="数据库名">
                <el-input
                  v-model="wizard.config.db_name"
                  placeholder="如：myapp_db"
                />
              </el-form-item>
            </el-col>
            <el-col :span="12">
              <el-form-item label="执行模式">
                <el-select v-model="wizard.config.execute_mode" style="width: 100%">
                  <el-option
                    v-for="opt in executeModeOptions"
                    :key="opt.value"
                    :label="opt.label"
                    :value="opt.value"
                  />
                </el-select>
              </el-form-item>
            </el-col>
          </el-row>

          <!-- 高级选项 -->
          <el-divider>
            <el-link :underline="false" @click="wizard.config.showAdvanced = !wizard.config.showAdvanced">
              {{ wizard.config.showAdvanced ? '收起高级选项' : '展开高级选项' }}
            </el-link>
          </el-divider>

          <div v-show="wizard.config.showAdvanced">
            <el-row :gutter="20">
              <el-col :span="12">
                <el-form-item label="Nginx 端口">
                  <el-input-number
                    v-model="wizard.config.nginx_port"
                    :min="1"
                    :max="65535"
                    controls-position="right"
                    style="width: 100%"
                  />
                </el-form-item>
              </el-col>
              <el-col :span="12">
                <el-form-item label="Tomcat 端口">
                  <el-input-number
                    v-model="wizard.config.tomcat_port"
                    :min="1"
                    :max="65535"
                    controls-position="right"
                    style="width: 100%"
                  />
                </el-form-item>
              </el-col>
            </el-row>
          </div>
        </el-form>
      </div>

      <!-- 步骤四：AI 部署预览 -->
      <div v-show="wizard.activeStep === 3" class="step-content">
        <div class="step-header">
          <el-icon :size="24" color="#409EFF"><Document /></el-icon>
          <h3>AI 部署预览</h3>
          <el-tag v-if="dangerousStepCount > 0" type="danger" size="small" class="danger-tag">
            {{ dangerousStepCount }} 个危险操作
          </el-tag>
        </div>

        <div v-loading="wizard.planLoading" class="plan-container">
          <div v-if="planSteps.length > 0" class="plan-steps">
            <div
              v-for="step in planSteps"
              :key="step.index"
              class="plan-step"
              :class="{ 'is-dangerous': step.dangerous }"
            >
              <div class="step-index-circle" :class="{ 'is-dangerous': step.dangerous }">
                {{ step.index }}
              </div>
              <div class="step-detail">
                <div class="step-detail-header">
                  <span class="step-name">{{ step.name }}</span>
                  <el-tag
                    v-if="step.dangerous"
                    type="danger"
                    size="small"
                    effect="dark"
                  >
                    <el-icon><WarningFilled /></el-icon>
                    危险
                  </el-tag>
                </div>
                <div class="step-command" v-if="step.command">
                  <span class="command-label">命令：</span>
                  <code class="command-code" :class="{ 'is-dangerous': step.dangerous }">{{ step.command }}</code>
                </div>
                <div class="step-impact" v-if="step.impact">
                  <span class="impact-label">影响：</span>
                  <span class="impact-text">{{ step.impact }}</span>
                </div>
              </div>
            </div>
          </div>
          <el-empty v-else-if="!wizard.planLoading" description="暂无部署计划" />
        </div>
      </div>

      <!-- 步骤五：执行与日志 -->
      <div v-show="wizard.activeStep === 4" class="step-content">
        <div class="step-header">
          <el-icon :size="24" color="#409EFF"><VideoPlay /></el-icon>
          <h3>执行与日志</h3>
        </div>

        <!-- 执行中 / 日志流 -->
        <LogStream
          v-if="wizard.deployId"
          :deploy-id="wizard.deployId"
          @complete="handleLogComplete"
          @error="handleLogError"
          @status-change="handleLogStatusChange"
        />

        <!-- 执行等待 -->
        <div v-else-if="wizard.executing" class="executing-placeholder">
          <el-icon class="loading-icon" :size="40"><Loading /></el-icon>
          <p>正在创建部署任务...</p>
        </div>

        <!-- 部署结果 -->
        <div v-if="showResult" class="deploy-result" :class="{ success: isSuccess, failed: isFailed, rollback: isRolledBack }">
          <!-- 成功 -->
          <template v-if="isSuccess">
            <div class="result-header success-header">
              <el-icon :size="28" color="#67C23A"><Check /></el-icon>
              <span class="result-title">部署成功</span>
            </div>
            <div class="result-body">
              <div class="access-url-section">
                <span class="label">访问地址：</span>
                <el-link type="primary" :href="accessUrl" target="_blank" :underline="false">
                  <el-icon><Link /></el-icon>
                  {{ accessUrl }}
                </el-link>
              </div>
              <div v-if="wizard.deployResult.validationResults" class="validation-summary">
                <span class="label">验证结果：</span>
                <el-tag type="success" size="small">全部通过</el-tag>
              </div>
            </div>
            <div class="result-actions">
              <el-button type="danger" :icon="Back" :loading="rollingBack" @click="handleRollback">
                回滚部署
              </el-button>
              <el-button :icon="RefreshLeft" @click="handleRestart">重新部署</el-button>
            </div>
          </template>

          <!-- 失败 -->
          <template v-else-if="isFailed">
            <div class="result-header failed-header">
              <el-icon :size="28" color="#F56C6C"><Close /></el-icon>
              <span class="result-title">部署失败</span>
            </div>
            <div class="result-body">
              <div class="error-message">
                <span class="label">错误信息：</span>
                <span class="error-text">{{ wizard.deployResult.error }}</span>
              </div>
            </div>
            <div class="result-actions">
              <el-button type="primary" :icon="RefreshLeft" @click="handleRetry">重试部署</el-button>
              <el-button :icon="Back" :loading="rollingBack" @click="handleRollback">
                回滚到上一版本
              </el-button>
              <el-button @click="handleRestart">重新开始</el-button>
            </div>
          </template>

          <!-- 已回滚 -->
          <template v-else-if="isRolledBack">
            <div class="result-header rollback-header">
              <el-icon :size="28" color="#909399"><Back /></el-icon>
              <span class="result-title">已回滚</span>
            </div>
            <div class="result-body">
              <div class="error-message">
                <span class="label">说明：</span>
                <span>{{ wizard.deployResult.error }}</span>
              </div>
            </div>
            <div class="result-actions">
              <el-button :icon="RefreshLeft" @click="handleRestart">重新部署</el-button>
            </div>
          </template>
        </div>
      </div>

      <!-- 步骤导航按钮 -->
      <div class="step-nav" v-if="wizard.activeStep < 4">
        <el-button
          v-if="wizard.activeStep > 0"
          :icon="ArrowLeft"
          @click="handlePrev"
        >
          上一步
        </el-button>
        <el-button
          v-if="wizard.activeStep === 3"
          type="primary"
          :icon="VideoPlay"
          :loading="wizard.executing"
          @click="handleStartDeploy"
        >
          开始执行
        </el-button>
        <el-button
          v-else
          type="primary"
          :disabled="!canNext"
          :loading="wizard.planLoading"
          @click="handleNext"
        >
          下一步
          <el-icon class="el-icon--right"><ArrowRight /></el-icon>
        </el-button>
      </div>
    </el-card>

    <!-- 确认弹窗 -->
    <ConfirmDialog
      v-model:visible="confirmDialog.visible"
      :title="confirmDialog.title"
      :command="confirmDialog.command"
      :impact="confirmDialog.impact"
      @confirm="handleConfirm"
      @cancel="handleConfirmCancel"
    />
  </div>
</template>

<style scoped>
.deploy-wizard {
  display: flex;
  flex-direction: column;
  gap: 16px;
}

.steps-card {
  border-radius: 8px;
}

.content-card {
  border-radius: 8px;
  min-height: 400px;
}

.step-content {
  padding: 8px 4px;
}

.step-header {
  display: flex;
  align-items: center;
  gap: 10px;
  margin-bottom: 24px;
}

.step-header h3 {
  margin: 0;
  font-size: 18px;
  color: #303133;
}

.danger-tag {
  margin-left: 8px;
}

/* 步骤一：模式选择 */
.mode-group {
  display: flex;
  flex-direction: column;
  gap: 16px;
  width: 100%;
}

.mode-group :deep(.el-radio) {
  width: 100%;
  margin-right: 0;
  height: auto;
  padding: 16px;
}

.mode-card {
  display: flex;
  align-items: center;
  gap: 16px;
}

.mode-info {
  flex: 1;
}

.mode-title {
  font-size: 16px;
  font-weight: 600;
  color: #303133;
}

.mode-desc {
  font-size: 13px;
  color: #909399;
  margin-top: 4px;
}

.host-select-section {
  margin-top: 24px;
}

.section-label {
  font-size: 14px;
  font-weight: 600;
  color: #303133;
  margin-bottom: 10px;
}

.host-info-bar {
  display: flex;
  align-items: center;
  gap: 12px;
  margin-top: 12px;
  padding: 10px 16px;
  background-color: #f5f7fa;
  border-radius: 6px;
  font-size: 13px;
  color: #606266;
}

/* 步骤三：配置表单 */
.config-form {
  max-width: 800px;
}

/* 步骤四：部署计划 */
.plan-container {
  min-height: 200px;
}

.plan-steps {
  display: flex;
  flex-direction: column;
  gap: 12px;
}

.plan-step {
  display: flex;
  gap: 16px;
  padding: 16px;
  border: 1px solid #ebeef5;
  border-radius: 8px;
  background-color: #fff;
  transition: all 0.2s;
}

.plan-step.is-dangerous {
  border-color: #f56c6c;
  background-color: #fef0f0;
}

.step-index-circle {
  display: flex;
  align-items: center;
  justify-content: center;
  width: 32px;
  height: 32px;
  border-radius: 50%;
  background-color: #409eff;
  color: #fff;
  font-size: 14px;
  font-weight: 700;
  flex-shrink: 0;
}

.step-index-circle.is-dangerous {
  background-color: #f56c6c;
}

.step-detail {
  flex: 1;
  min-width: 0;
}

.step-detail-header {
  display: flex;
  align-items: center;
  gap: 8px;
  margin-bottom: 8px;
}

.step-name {
  font-size: 15px;
  font-weight: 600;
  color: #303133;
}

.step-command {
  margin-bottom: 6px;
  font-size: 13px;
}

.command-label {
  color: #909399;
}

.command-code {
  font-family: 'Consolas', 'Monaco', monospace;
  background-color: #1e1e1e;
  color: #d4d4d4;
  padding: 2px 8px;
  border-radius: 4px;
  font-size: 12px;
}

.command-code.is-dangerous {
  background-color: #2d1b1b;
  color: #f56c6c;
}

.step-impact {
  font-size: 13px;
  color: #606266;
}

.impact-label {
  color: #909399;
}

/* 步骤五：执行 */
.executing-placeholder {
  display: flex;
  flex-direction: column;
  align-items: center;
  justify-content: center;
  padding: 60px 20px;
  color: #909399;
}

.loading-icon {
  animation: rotating 1.5s linear infinite;
}

@keyframes rotating {
  from {
    transform: rotate(0deg);
  }
  to {
    transform: rotate(360deg);
  }
}

.executing-placeholder p {
  margin-top: 16px;
  font-size: 14px;
}

/* 部署结果 */
.deploy-result {
  margin-top: 20px;
  padding: 24px;
  border-radius: 8px;
  border: 1px solid;
}

.deploy-result.success {
  border-color: #67c23a;
  background-color: #f0f9eb;
}

.deploy-result.failed {
  border-color: #f56c6c;
  background-color: #fef0f0;
}

.deploy-result.rollback {
  border-color: #909399;
  background-color: #f4f4f5;
}

.result-header {
  display: flex;
  align-items: center;
  gap: 10px;
  margin-bottom: 16px;
}

.result-title {
  font-size: 18px;
  font-weight: 700;
}

.success-header .result-title {
  color: #67c23a;
}

.failed-header .result-title {
  color: #f56c6c;
}

.rollback-header .result-title {
  color: #909399;
}

.result-body {
  padding: 12px 0;
  font-size: 14px;
  color: #606266;
}

.access-url-section,
.validation-summary,
.error-message {
  display: flex;
  align-items: center;
  gap: 8px;
  margin-bottom: 10px;
  flex-wrap: wrap;
}

.access-url-section .label,
.validation-summary .label,
.error-message .label {
  color: #909399;
  font-weight: 600;
  flex-shrink: 0;
}

.error-text {
  color: #f56c6c;
  word-break: break-all;
}

.result-actions {
  display: flex;
  gap: 12px;
  margin-top: 16px;
  flex-wrap: wrap;
}

/* 步骤导航 */
.step-nav {
  display: flex;
  justify-content: flex-end;
  gap: 12px;
  margin-top: 24px;
  padding-top: 16px;
  border-top: 1px solid #ebeef5;
}
</style>
