<script setup>
import { computed } from 'vue'
import { WarningFilled, Document, Aim } from '@element-plus/icons-vue'

const props = defineProps({
  visible: { type: Boolean, default: false },
  title: { type: String, default: '操作确认' },
  command: { type: String, default: '' },
  impact: { type: String, default: '' }
})

const emit = defineEmits(['confirm', 'cancel', 'update:visible'])

// 危险命令正则检测
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

const isDangerous = computed(() => {
  const cmd = props.command || ''
  return DANGEROUS_PATTERNS.some((p) => p.test(cmd))
})

// el-dialog 的 before-close 仅在用户点击 X / ESC / 遮罩时触发
// 不会在 model-value 外部变更时触发，避免与 confirm/cancel 按钮重复 emit
const handleConfirm = () => {
  emit('confirm')
  emit('update:visible', false)
}

const handleCancel = () => {
  emit('cancel')
  emit('update:visible', false)
}

const handleBeforeClose = (done) => {
  handleCancel()
  done()
}
</script>

<template>
  <el-dialog
    :model-value="visible"
    :title="title"
    width="580px"
    :close-on-click-modal="false"
    :close-on-press-escape="!isDangerous"
    :before-close="handleBeforeClose"
  >
    <div class="confirm-body">
      <!-- 危险标识 -->
      <div class="confirm-header" :class="{ 'is-danger': isDangerous }">
        <el-icon class="header-icon" :size="22">
          <WarningFilled />
        </el-icon>
        <span class="header-text">
          {{ isDangerous ? '检测到危险操作，请谨慎确认' : '即将执行以下操作' }}
        </span>
      </div>

      <!-- 将执行的命令 -->
      <div class="confirm-section">
        <div class="section-label">
          <el-icon><Document /></el-icon>
          <span>将执行的命令</span>
        </div>
        <pre class="command-block" :class="{ 'is-danger': isDangerous }">{{ command || '(无命令)' }}</pre>
      </div>

      <!-- 影响范围 -->
      <div class="confirm-section" v-if="impact">
        <div class="section-label">
          <el-icon><Aim /></el-icon>
          <span>影响范围</span>
        </div>
        <div class="impact-text" :class="{ 'is-danger': isDangerous }">{{ impact }}</div>
      </div>
    </div>

    <template #footer>
      <el-button @click="handleCancel">取消</el-button>
      <el-button
        :type="isDangerous ? 'danger' : 'primary'"
        @click="handleConfirm"
      >
        {{ isDangerous ? '确认执行危险操作' : '确认执行' }}
      </el-button>
    </template>
  </el-dialog>
</template>

<style scoped>
.confirm-body {
  padding: 0 4px;
}

.confirm-header {
  display: flex;
  align-items: center;
  gap: 10px;
  padding: 12px 16px;
  border-radius: 6px;
  background-color: #f4f4f5;
  color: #909399;
  margin-bottom: 20px;
}

.confirm-header.is-danger {
  background-color: #fef0f0;
  color: #f56c6c;
}

.header-icon {
  flex-shrink: 0;
}

.header-text {
  font-size: 14px;
  font-weight: 600;
}

.confirm-section {
  margin-bottom: 18px;
}

.section-label {
  display: flex;
  align-items: center;
  gap: 6px;
  font-size: 13px;
  color: #606266;
  margin-bottom: 8px;
  font-weight: 600;
}

.command-block {
  background-color: #1e1e1e;
  color: #d4d4d4;
  padding: 12px 16px;
  border-radius: 6px;
  font-family: 'Consolas', 'Monaco', monospace;
  font-size: 13px;
  line-height: 1.6;
  overflow-x: auto;
  white-space: pre-wrap;
  word-break: break-all;
  margin: 0;
}

.command-block.is-danger {
  background-color: #2d1b1b;
  color: #f56c6c;
  border: 1px solid #f56c6c;
}

.impact-text {
  padding: 10px 16px;
  background-color: #f4f4f5;
  border-radius: 6px;
  font-size: 13px;
  color: #606266;
  line-height: 1.6;
}

.impact-text.is-danger {
  background-color: #fef0f0;
  color: #f56c6c;
}
</style>
