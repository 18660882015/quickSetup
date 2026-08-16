<script setup>
import { ref, computed, watch, nextTick, onUnmounted } from 'vue'
import { ElMessage } from 'element-plus'
import {
  VideoPause,
  VideoPlay,
  DocumentCopy,
  Download,
  RefreshRight,
  Connection
} from '@element-plus/icons-vue'
import { useWebSocket } from '@/composables/useWebSocket'

const props = defineProps({
  deployId: { type: [String, Number], default: '' },
  // 部署步骤列表（可选，用于进度条展示）
  stepList: { type: Array, default: () => [] }
})

const emit = defineEmits(['status-change', 'complete', 'error'])

// 日志级别颜色（与约束一致）
const LEVEL_COLORS = {
  info: '#409EFF',
  warn: '#E6A23C',
  error: '#F56C6C',
  success: '#67C23A',
  warning: '#E6A23C'
}

// 标准化日志级别
function normalizeLevel(level) {
  const l = (level || 'info').toLowerCase()
  return l === 'warning' ? 'warn' : l
}

// 部署步骤状态
const DEPLOY_STEPS_DEFAULT = [
  { name: '预检', key: 'precheck' },
  { name: '备份', key: 'backup' },
  { name: '传输', key: 'transfer' },
  { name: '安装', key: 'install' },
  { name: '配置', key: 'configure' },
  { name: '启动', key: 'start' },
  { name: '验证', key: 'validate' },
  { name: '清理', key: 'cleanup' }
]

// ---- 响应式状态 ----
const logs = ref([])
const paused = ref(false)
const currentStep = ref('')
const progress = ref(0)
const deployStatus = ref('idle') // idle | running | success | failed | rolled_back
const stepStates = ref([]) // {name, status: pending|running|success|failed}
const validationResults = ref(null)
const accessUrl = ref('')
const errorMessage = ref('')
const logBodyRef = ref(null)

// 步骤列表
const steps = computed(() => {
  if (props.stepList && props.stepList.length > 0) {
    return props.stepList.map((s, i) => ({
      name: typeof s === 'string' ? s : s.name || s.step || `步骤${i + 1}`,
      key: typeof s === 'string' ? s : s.key || s.step || `step_${i}`,
      status: stepStates.value.find((st) => st.key === (s.key || s.step || s.name))?.status || 'pending'
    }))
  }
  return DEPLOY_STEPS_DEFAULT.map((s) => ({
    ...s,
    status: stepStates.value.find((st) => st.key === s.key)?.status || 'pending'
  }))
})

// WebSocket 连接
const { status: wsStatus, close: wsClose, connect: wsConnect } = useWebSocket('', {
  autoConnect: false,
  onMessage: handleMessage
})

// 构建 WebSocket URL
function buildWsUrl(id) {
  if (!id) return ''
  const protocol = window.location.protocol === 'https:' ? 'wss:' : 'ws:'
  return `${protocol}//${window.location.host}/ws/logs/${id}`
}

// 重置状态
function resetState() {
  logs.value = []
  currentStep.value = ''
  progress.value = 0
  deployStatus.value = 'idle'
  stepStates.value = []
  validationResults.value = null
  accessUrl.value = ''
  errorMessage.value = ''
}

// 更新步骤状态
function updateStepState(stepName, stepStatus) {
  if (!stepName) return
  const existing = stepStates.value.find((s) => s.name === stepName || s.key === stepName)
  if (existing) {
    existing.status = stepStatus
  } else {
    stepStates.value.push({ name: stepName, key: stepName, status: stepStatus })
  }
}

// 处理 WebSocket 消息
function handleMessage(payload) {
  const { type, level, message, step, timestamp, progress: msgProgress, status: msgStatus, current_step, total_steps, validation, access_url, error } = payload

  // 日志消息
  if (type === 'log' || type === 'raw' || !type) {
    logs.value.push({
      level: normalizeLevel(level),
      message: message || '',
      step: step || '',
      timestamp: timestamp || new Date().toISOString()
    })
  }

  // 状态更新
  if (type === 'status') {
    if (msgStatus) {
      deployStatus.value = msgStatus
      emit('status-change', msgStatus)
      if (msgStatus === 'success') {
        emit('complete', { status: 'success', accessUrl: accessUrl.value, validationResults: validationResults.value })
      } else if (msgStatus === 'failed' || msgStatus === 'rolled_back') {
        errorMessage.value = error || message || '部署失败'
        emit('error', { status: msgStatus, error: errorMessage.value })
      }
    }
    // 步骤状态
    if (step) {
      const stepStatus = level === 'error' ? 'failed' : level === 'success' ? 'success' : 'running'
      updateStepState(step, stepStatus)
    }
  }

  // 进度更新
  if (type === 'progress') {
    if (typeof msgProgress === 'number') {
      progress.value = msgProgress
    }
    if (current_step) {
      currentStep.value = current_step
      updateStepState(current_step, 'running')
    }
    // 根据步骤进度计算
    if (total_steps && current_step) {
      const stepIdx = steps.value.findIndex(
        (s) => s.name === current_step || s.key === current_step
      )
      if (stepIdx >= 0) {
        progress.value = Math.round(((stepIdx + 1) / total_steps) * 100)
      }
    }
  }

  // 验证结果
  if (type === 'validation' || validation) {
    validationResults.value = validation || payload
  }

  // 完成结果
  if (type === 'result' || type === 'complete') {
    if (access_url) accessUrl.value = access_url
    if (validation) validationResults.value = validation
    if (status || msgStatus) {
      deployStatus.value = msgStatus || status || 'success'
    }
    if (error) errorMessage.value = error
    if (deployStatus.value === 'success') {
      progress.value = 100
      emit('complete', {
        status: 'success',
        accessUrl: accessUrl.value,
        validationResults: validationResults.value
      })
    } else if (deployStatus.value === 'failed') {
      emit('error', { status: 'failed', error: errorMessage.value })
    }
  }

  // 自动滚动
  if (!paused.value) {
    nextTick(scrollToBottom)
  }
}

// 滚动到底部
function scrollToBottom() {
  const el = logBodyRef.value
  if (el) {
    el.scrollTop = el.scrollHeight
  }
}

// 暂停/继续滚动
function togglePause() {
  paused.value = !paused.value
  if (!paused.value) {
    nextTick(scrollToBottom)
  }
}

// 复制日志
async function copyLogs() {
  if (logs.value.length === 0) {
    ElMessage.warning('暂无日志可复制')
    return
  }
  const text = logs.value
    .map((l) => `[${l.timestamp}] [${l.level.toUpperCase()}]${l.step ? ` [${l.step}]` : ''} ${l.message}`)
    .join('\n')
  try {
    await navigator.clipboard.writeText(text)
    ElMessage.success('日志已复制到剪贴板')
  } catch (e) {
    // 降级方案
    const textarea = document.createElement('textarea')
    textarea.value = text
    document.body.appendChild(textarea)
    textarea.select()
    try {
      document.execCommand('copy')
      ElMessage.success('日志已复制到剪贴板')
    } catch (err) {
      ElMessage.error('复制失败，请手动选择日志复制')
    }
    document.body.removeChild(textarea)
  }
}

// 下载日志
function downloadLogs() {
  if (logs.value.length === 0) {
    ElMessage.warning('暂无日志可下载')
    return
  }
  const text = logs.value
    .map((l) => `[${l.timestamp}] [${l.level.toUpperCase()}]${l.step ? ` [${l.step}]` : ''} ${l.message}`)
    .join('\n')
  const blob = new Blob([text], { type: 'text/plain;charset=utf-8' })
  const url = URL.createObjectURL(blob)
  const a = document.createElement('a')
  a.href = url
  a.download = `deploy-${props.deployId}-${Date.now()}.log`
  document.body.appendChild(a)
  a.click()
  document.body.removeChild(a)
  URL.revokeObjectURL(url)
}

// 清空日志
function clearLogs() {
  logs.value = []
}

// 监听 deployId 变化，建立/重建 WebSocket
watch(
  () => props.deployId,
  (newId) => {
    wsClose()
    resetState()
    if (newId) {
      const url = buildWsUrl(newId)
      if (url) {
        wsConnect(url)
      }
    }
  },
  { immediate: true }
)

onUnmounted(() => {
  wsClose()
})

// 暴露给父组件的方法
defineExpose({
  clearLogs,
  scrollToBottom,
  pause: () => {
    paused.value = true
  },
  resume: () => {
    paused.value = false
    nextTick(scrollToBottom)
  }
})

// 计算属性：日志总数
const logCount = computed(() => logs.value.length)

// 计算属性：WebSocket 状态文本
const wsStatusText = computed(() => {
  const map = {
    idle: '未连接',
    connecting: '连接中...',
    connected: '已连接',
    reconnecting: '重连中...',
    closed: '已关闭',
    error: '连接错误'
  }
  return map[wsStatus.value] || wsStatus.value
})

// 计算属性：步骤进度条颜色
const progressColor = computed(() => {
  if (deployStatus.value === 'failed') return '#F56C6C'
  if (deployStatus.value === 'success') return '#67C23A'
  if (deployStatus.value === 'rolled_back') return '#909399'
  return '#409EFF'
})

// 格式化时间显示
function formatTimestamp(ts) {
  if (!ts) return ''
  try {
    const d = new Date(ts)
    if (isNaN(d.getTime())) return ts
    const pad = (n) => String(n).padStart(2, '0')
    return `${pad(d.getHours())}:${pad(d.getMinutes())}:${pad(d.getSeconds())}`
  } catch (e) {
    return ts
  }
}
</script>

<template>
  <div class="log-stream">
    <!-- 进度条区域 -->
    <div class="progress-section">
      <div class="progress-header">
        <span class="step-label">
          {{ currentStep ? `当前步骤：${currentStep}` : '等待部署开始...' }}
        </span>
        <el-tag size="small" :type="wsStatus === 'connected' ? 'success' : 'info'">
          <el-icon class="ws-icon"><Connection /></el-icon>
          {{ wsStatusText }}
        </el-tag>
      </div>
      <el-progress
        :percentage="progress"
        :color="progressColor"
        :stroke-width="10"
        :text-inside="true"
        :format="(p) => `${p}%`"
      />
      <!-- 步骤指示器 -->
      <div class="steps-indicator" v-if="steps.length > 0">
        <div
          v-for="(step, idx) in steps"
          :key="step.key || idx"
          class="step-item"
          :class="`step-${step.status || 'pending'}`"
        >
          <span class="step-index">{{ idx + 1 }}</span>
          <span class="step-name">{{ step.name }}</span>
        </div>
      </div>
    </div>

    <!-- 工具栏 -->
    <div class="toolbar">
      <div class="toolbar-left">
        <el-button
          size="small"
          :type="paused ? 'primary' : 'default'"
          :icon="paused ? VideoPlay : VideoPause"
          @click="togglePause"
        >
          {{ paused ? '继续滚动' : '暂停滚动' }}
        </el-button>
        <el-button size="small" :icon="DocumentCopy" @click="copyLogs">复制</el-button>
        <el-button size="small" :icon="Download" @click="downloadLogs">下载</el-button>
        <el-button size="small" :icon="RefreshRight" @click="clearLogs">清空</el-button>
      </div>
      <div class="toolbar-right">
        <span class="log-count">共 {{ logCount }} 条日志</span>
      </div>
    </div>

    <!-- 日志正文 -->
    <div ref="logBodyRef" class="log-body">
      <div v-if="logs.length === 0" class="log-empty">
        <el-icon :size="32" color="#909399"><Connection /></el-icon>
        <p>{{ deployId ? '等待日志输出...' : '尚未开始部署，无日志' }}</p>
      </div>
      <div
        v-for="(log, idx) in logs"
        :key="idx"
        class="log-line"
        :style="{ color: LEVEL_COLORS[log.level] || '#909399' }"
      >
        <span class="log-time">[{{ formatTimestamp(log.timestamp) }}]</span>
        <span class="log-level">[{{ log.level.toUpperCase() }}]</span>
        <span class="log-step" v-if="log.step">[{{ log.step }}]</span>
        <span class="log-message">{{ log.message }}</span>
      </div>
    </div>

    <!-- 验证结果 -->
    <div class="validation-section" v-if="validationResults">
      <div class="section-title">验证结果</div>
      <div class="validation-grid">
        <div
          v-for="(val, key) in validationResults"
          :key="key"
          class="validation-item"
          :class="{ passed: val.passed, failed: !val.passed }"
        >
          <el-icon :size="16">
            <component :is="val.passed ? 'CircleCheck' : 'CircleClose'" />
          </el-icon>
          <span class="validation-name">{{ key }}</span>
          <span class="validation-detail">{{ val.detail || (val.passed ? '通过' : '未通过') }}</span>
        </div>
      </div>
    </div>
  </div>
</template>

<style scoped>
.log-stream {
  display: flex;
  flex-direction: column;
  height: 100%;
  min-height: 400px;
}

/* 进度区域 */
.progress-section {
  padding: 12px 16px;
  background-color: #fff;
  border-radius: 6px 6px 0 0;
  border: 1px solid #ebeef5;
  border-bottom: none;
}

.progress-header {
  display: flex;
  align-items: center;
  justify-content: space-between;
  margin-bottom: 10px;
}

.step-label {
  font-size: 13px;
  color: #606266;
  font-weight: 600;
}

.ws-icon {
  margin-right: 4px;
  vertical-align: middle;
}

.steps-indicator {
  display: flex;
  flex-wrap: wrap;
  gap: 6px;
  margin-top: 12px;
}

.step-item {
  display: flex;
  align-items: center;
  gap: 4px;
  padding: 2px 8px;
  border-radius: 4px;
  font-size: 12px;
  background-color: #f4f4f5;
  color: #909399;
}

.step-item.step-running {
  background-color: #ecf5ff;
  color: #409eff;
  font-weight: 600;
}

.step-item.step-success {
  background-color: #f0f9eb;
  color: #67c23a;
}

.step-item.step-failed {
  background-color: #fef0f0;
  color: #f56c6c;
}

.step-index {
  display: inline-flex;
  align-items: center;
  justify-content: center;
  width: 16px;
  height: 16px;
  border-radius: 50%;
  background-color: currentColor;
  color: #fff;
  font-size: 10px;
}

/* 工具栏 */
.toolbar {
  display: flex;
  align-items: center;
  justify-content: space-between;
  padding: 8px 16px;
  background-color: #f5f7fa;
  border: 1px solid #ebeef5;
  border-bottom: none;
}

.toolbar-left {
  display: flex;
  gap: 8px;
}

.toolbar-right {
  font-size: 12px;
  color: #909399;
}

.log-count {
  font-size: 12px;
}

/* 日志正文 */
.log-body {
  flex: 1;
  overflow-y: auto;
  background-color: #1e1e1e;
  padding: 12px 16px;
  border: 1px solid #ebeef5;
  border-radius: 0 0 6px 6px;
  font-family: 'Consolas', 'Monaco', 'Courier New', monospace;
  font-size: 13px;
  line-height: 1.7;
  min-height: 300px;
  max-height: 500px;
}

.log-empty {
  display: flex;
  flex-direction: column;
  align-items: center;
  justify-content: center;
  height: 100%;
  min-height: 200px;
  color: #606266;
}

.log-empty p {
  margin-top: 12px;
  font-size: 13px;
}

.log-line {
  white-space: pre-wrap;
  word-break: break-all;
}

.log-time {
  opacity: 0.6;
  margin-right: 6px;
}

.log-level {
  font-weight: 700;
  margin-right: 6px;
  min-width: 70px;
  display: inline-block;
}

.log-step {
  opacity: 0.8;
  margin-right: 6px;
  font-style: italic;
}

.log-message {
  flex: 1;
}

/* 验证结果 */
.validation-section {
  margin-top: 16px;
  padding: 12px 16px;
  background-color: #fff;
  border-radius: 6px;
  border: 1px solid #ebeef5;
}

.section-title {
  font-size: 14px;
  font-weight: 600;
  color: #303133;
  margin-bottom: 12px;
}

.validation-grid {
  display: grid;
  grid-template-columns: repeat(auto-fill, minmax(280px, 1fr));
  gap: 10px;
}

.validation-item {
  display: flex;
  align-items: center;
  gap: 8px;
  padding: 8px 12px;
  border-radius: 4px;
  font-size: 13px;
}

.validation-item.passed {
  background-color: #f0f9eb;
  color: #67c23a;
}

.validation-item.failed {
  background-color: #fef0f0;
  color: #f56c6c;
}

.validation-name {
  font-weight: 600;
}

.validation-detail {
  margin-left: auto;
  font-size: 12px;
  opacity: 0.8;
}

/* 滚动条样式 */
.log-body::-webkit-scrollbar {
  width: 8px;
}

.log-body::-webkit-scrollbar-track {
  background-color: #2d2d2d;
}

.log-body::-webkit-scrollbar-thumb {
  background-color: #555;
  border-radius: 4px;
}

.log-body::-webkit-scrollbar-thumb:hover {
  background-color: #777;
}
</style>
