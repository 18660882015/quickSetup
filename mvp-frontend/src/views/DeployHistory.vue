<script setup>
import { ref, computed, onMounted } from 'vue'
import { ElMessage, ElMessageBox } from 'element-plus'
import {
  Refresh,
  View,
  Back,
  Search,
  Document,
  Clock,
  CircleCheck,
  CircleClose
} from '@element-plus/icons-vue'
import { getHistory, rollbackDeploy, getTaskStatus } from '@/api/deploy'
import { statusColor, statusText, formatTime, formatDuration, logLevelColor } from '@/utils/format'

// ---- 列表状态 ----
const records = ref([])
const loading = ref(false)
const statusFilter = ref('') // '' | success | failed | rolled_back | running | pending
const searchKeyword = ref('')
const currentPage = ref(1)
const pageSize = ref(10)
const total = ref(0)

// 状态筛选选项
const statusOptions = [
  { label: '全部', value: '' },
  { label: '成功', value: 'success' },
  { label: '失败', value: 'failed' },
  { label: '已回滚', value: 'rolled_back' },
  { label: '执行中', value: 'running' },
  { label: '等待中', value: 'pending' }
]

// 拉取历史列表
async function fetchHistory() {
  loading.value = true
  try {
    const params = {
      page: currentPage.value,
      page_size: pageSize.value
    }
    if (statusFilter.value) {
      params.status = statusFilter.value
    }
    const res = await getHistory(params)
    const data = res.data
    // 兼容数组和分页对象两种格式
    if (Array.isArray(data)) {
      records.value = data
      total.value = data.length
    } else if (data) {
      records.value = data.list || data.records || data.items || []
      total.value = data.total || data.count || records.value.length
    } else {
      records.value = []
      total.value = 0
    }
  } catch (e) {
    // 错误由拦截器处理
  } finally {
    loading.value = false
  }
}

// 过滤后的记录（前端搜索）
const filteredRecords = computed(() => {
  const kw = searchKeyword.value.trim().toLowerCase()
  if (!kw) return records.value
  return records.value.filter(
    (r) =>
      r.project_name?.toLowerCase().includes(kw) ||
      r.host_name?.toLowerCase().includes(kw) ||
      r.operator?.toLowerCase().includes(kw)
  )
})

// ---- 详情弹窗 ----
const detailVisible = ref(false)
const detailLoading = ref(false)
const currentRecord = ref(null)

async function handleViewDetail(row) {
  currentRecord.value = row
  detailVisible.value = true
  detailLoading.value = true

  // 尝试拉取完整的任务详情（含完整日志）
  try {
    const taskId = row.id || row.task_id || row.record_id
    if (taskId) {
      const res = await getTaskStatus(taskId)
      const data = res.data
      if (data) {
        // 合并完整数据
        currentRecord.value = { ...row, ...data }
      }
    }
  } catch (e) {
    // 如果拉取失败，使用列表中的数据
  } finally {
    detailLoading.value = false
  }
}

// 解析步骤明细
function parseStepsDetail(stepsDetail) {
  if (!stepsDetail) return []
  if (Array.isArray(stepsDetail)) return stepsDetail
  try {
    const parsed = JSON.parse(stepsDetail)
    return Array.isArray(parsed) ? parsed : []
  } catch (e) {
    return []
  }
}

// 解析日志为带颜色的行
function parseLogs(logText) {
  if (!logText) return []
  const lines = String(logText).split('\n').filter((l) => l.trim())
  return lines.map((line) => {
    // 尝试匹配 [LEVEL] 格式
    const levelMatch = line.match(/\[(INFO|WARN|WARNING|ERROR|SUCCESS)\]/i)
    let level = 'info'
    if (levelMatch) {
      const matched = levelMatch[1].toLowerCase()
      level = matched === 'warning' ? 'warn' : matched
    } else if (/error|exception|failed/i.test(line)) {
      level = 'error'
    } else if (/success|complete|done/i.test(line)) {
      level = 'success'
    } else if (/warn/i.test(line)) {
      level = 'warn'
    }
    return { level, text: line }
  })
}

const parsedLogs = computed(() => {
  if (!currentRecord.value) return []
  return parseLogs(currentRecord.value.logs)
})

const parsedSteps = computed(() => {
  if (!currentRecord.value) return []
  return parseStepsDetail(currentRecord.value.steps_detail)
})

// AI 建议区块：失败时展示为「AI 错误分析」，其余展示为「AI 部署建议」
const aiSectionMeta = computed(() => {
  if (!currentRecord.value) {
    return { title: 'AI 部署建议', icon: CircleCheck, color: '#67C23A' }
  }
  if (currentRecord.value.execute_status === 'failed') {
    return { title: 'AI 错误分析', icon: CircleClose, color: '#E6A23C' }
  }
  return { title: 'AI 部署建议', icon: CircleCheck, color: '#67C23A' }
})

// 是否为失败部署（用于错误分析展示）
const isFailedDeploy = computed(
  () => currentRecord.value?.execute_status === 'failed'
)

// 日志颜色
function getLogColor(level) {
  return logLevelColor(level)
}

// ---- 回滚 ----
const rollingBackId = ref(null)

async function handleRollback(row) {
  try {
    await ElMessageBox.confirm(
      `确定要回滚部署「${row.project_name}」到上一版本吗？此操作将恢复备份文件并重启服务。`,
      '回滚确认',
      {
        confirmButtonText: '确定回滚',
        cancelButtonText: '取消',
        type: 'warning'
      }
    )
    rollingBackId.value = row.id
    await rollbackDeploy(row.id)
    ElMessage.success('回滚成功，已恢复到上一版本')
    await fetchHistory()
  } catch (e) {
    // 用户取消或错误
  } finally {
    rollingBackId.value = null
  }
}

// ---- 分页 ----
function handlePageChange(page) {
  currentPage.value = page
  fetchHistory()
}

function handleSizeChange(size) {
  pageSize.value = size
  currentPage.value = 1
  fetchHistory()
}

// ---- 筛选 ----
function handleStatusChange() {
  currentPage.value = 1
  fetchHistory()
}

// 步骤状态颜色
function stepStatusColor(status) {
  const map = {
    success: '#67C23A',
    failed: '#F56C6C',
    running: '#409EFF',
    pending: '#909399',
    skipped: '#909399'
  }
  return map[status] || '#909399'
}

function stepStatusText(status) {
  const map = {
    success: '成功',
    failed: '失败',
    running: '执行中',
    pending: '等待中',
    skipped: '跳过'
  }
  return map[status] || status || '-'
}

onMounted(fetchHistory)
</script>

<template>
  <div class="deploy-history">
    <!-- 操作栏 -->
    <el-card shadow="never" class="toolbar-card">
      <div class="toolbar">
        <div class="toolbar-left">
          <el-select
            v-model="statusFilter"
            placeholder="按状态筛选"
            clearable
            style="width: 160px"
            @change="handleStatusChange"
          >
            <el-option
              v-for="opt in statusOptions"
              :key="opt.value"
              :label="opt.label"
              :value="opt.value"
            />
          </el-select>
          <el-input
            v-model="searchKeyword"
            placeholder="搜索项目名/主机/操作人"
            clearable
            style="width: 240px"
            :prefix-icon="Search"
          />
        </div>
        <div class="toolbar-right">
          <el-button :icon="Refresh" @click="fetchHistory" :loading="loading">刷新</el-button>
        </div>
      </div>
    </el-card>

    <!-- 历史表格 -->
    <el-card shadow="never" class="table-card">
      <el-table
        :data="filteredRecords"
        v-loading="loading"
        stripe
        style="width: 100%"
        empty-text="暂无部署记录"
      >
        <el-table-column prop="project_name" label="项目名" min-width="140" show-overflow-tooltip />
        <el-table-column label="主机" min-width="120" show-overflow-tooltip>
          <template #default="{ row }">
            {{ row.host_name || row.host_ip || row.host_id || '-' }}
          </template>
        </el-table-column>
        <el-table-column label="状态" width="100">
          <template #default="{ row }">
            <el-tag :type="statusColor(row.execute_status)" size="small">
              {{ statusText(row.execute_status) }}
            </el-tag>
          </template>
        </el-table-column>
        <el-table-column prop="env_type" label="环境" width="80">
          <template #default="{ row }">
            <el-tag size="small" effect="plain">{{ row.env_type || '-' }}</el-tag>
          </template>
        </el-table-column>
        <el-table-column label="部署时间" width="180">
          <template #default="{ row }">
            {{ formatTime(row.started_at || row.created_at) }}
          </template>
        </el-table-column>
        <el-table-column label="耗时" width="100">
          <template #default="{ row }">
            {{ formatDuration(row.duration) }}
          </template>
        </el-table-column>
        <el-table-column prop="operator" label="操作人" width="100" show-overflow-tooltip />
        <el-table-column label="操作" width="200" fixed="right">
          <template #default="{ row }">
            <el-button size="small" :icon="View" @click="handleViewDetail(row)">
              查看详情
            </el-button>
            <el-button
              v-if="row.can_rollback"
              size="small"
              type="warning"
              :icon="Back"
              :loading="rollingBackId === row.id"
              @click="handleRollback(row)"
            >
              回滚
            </el-button>
          </template>
        </el-table-column>
      </el-table>

      <!-- 分页 -->
      <div class="pagination" v-if="total > 0">
        <el-pagination
          v-model:current-page="currentPage"
          v-model:page-size="pageSize"
          :total="total"
          :page-sizes="[10, 20, 50]"
          layout="total, sizes, prev, pager, next"
          @current-change="handlePageChange"
          @size-change="handleSizeChange"
        />
      </div>
    </el-card>

    <!-- 详情弹窗 -->
    <el-dialog
      v-model="detailVisible"
      title="部署详情"
      width="900px"
      destroy-on-close
    >
      <div v-loading="detailLoading">
        <template v-if="currentRecord">
          <!-- 基本信息 -->
          <el-descriptions :column="3" border>
            <el-descriptions-item label="项目名">{{ currentRecord.project_name || '-' }}</el-descriptions-item>
            <el-descriptions-item label="主机">{{ currentRecord.host_name || currentRecord.host_ip || '-' }}</el-descriptions-item>
            <el-descriptions-item label="状态">
              <el-tag :type="statusColor(currentRecord.execute_status)" size="small">
                {{ statusText(currentRecord.execute_status) }}
              </el-tag>
            </el-descriptions-item>
            <el-descriptions-item label="环境">{{ currentRecord.env_type || '-' }}</el-descriptions-item>
            <el-descriptions-item label="JDK 版本">{{ currentRecord.jdk_version || '-' }}</el-descriptions-item>
            <el-descriptions-item label="执行模式">{{ currentRecord.execute_mode === 'step_by_step' ? '逐步确认' : '自动执行' }}</el-descriptions-item>
            <el-descriptions-item label="开始时间">{{ formatTime(currentRecord.started_at || currentRecord.created_at) }}</el-descriptions-item>
            <el-descriptions-item label="结束时间">{{ formatTime(currentRecord.finished_at) }}</el-descriptions-item>
            <el-descriptions-item label="耗时">{{ formatDuration(currentRecord.duration) }}</el-descriptions-item>
            <el-descriptions-item label="操作人">{{ currentRecord.operator || '-' }}</el-descriptions-item>
            <el-descriptions-item label="数据库名">{{ currentRecord.db_name || '-' }}</el-descriptions-item>
            <el-descriptions-item label="版本">{{ currentRecord.version || '-' }}</el-descriptions-item>
          </el-descriptions>

          <!-- 错误信息 -->
          <div v-if="currentRecord.error_message" class="error-section">
            <div class="section-title">
              <el-icon color="#F56C6C"><CircleClose /></el-icon>
              错误信息
            </div>
            <div class="error-box">{{ currentRecord.error_message }}</div>
          </div>

          <!-- 步骤时间线 -->
          <div v-if="parsedSteps.length > 0" class="steps-section">
            <div class="section-title">
              <el-icon color="#409EFF"><Clock /></el-icon>
              步骤时间线
            </div>
            <el-timeline>
              <el-timeline-item
                v-for="(step, idx) in parsedSteps"
                :key="idx"
                :timestamp="formatTime(step.started_at || step.timestamp)"
                placement="top"
                :color="stepStatusColor(step.status)"
              >
                <div class="step-timeline-item">
                  <span class="step-timeline-name">{{ step.name || step.step || `步骤 ${idx + 1}` }}</span>
                  <el-tag :color="stepStatusColor(step.status)" effect="dark" size="small" style="color: #fff; border: none;">
                    {{ stepStatusText(step.status) }}
                  </el-tag>
                  <span v-if="step.duration != null" class="step-timeline-duration">
                    耗时：{{ formatDuration(step.duration) }}
                  </span>
                </div>
                <div v-if="step.command" class="step-timeline-command">{{ step.command }}</div>
                <div v-if="step.message || step.error" class="step-timeline-message">
                  {{ step.message || step.error }}
                </div>
              </el-timeline-item>
            </el-timeline>
          </div>

          <!-- AI 建议 / 错误分析 -->
          <div v-if="currentRecord.ai_suggestion" class="ai-section">
            <div class="section-title">
              <el-icon :color="aiSectionMeta.color"><component :is="aiSectionMeta.icon" /></el-icon>
              {{ aiSectionMeta.title }}
            </div>
            <div
              class="ai-box"
              :class="{ 'ai-box-error': isFailedDeploy }"
            >
              {{ currentRecord.ai_suggestion }}
            </div>
          </div>

          <!-- 完整日志 -->
          <div class="logs-section">
            <div class="section-title">
              <el-icon color="#409EFF"><Document /></el-icon>
              完整日志
              <span class="log-count">（{{ parsedLogs.length }} 条）</span>
            </div>
            <div class="logs-container">
              <div v-if="parsedLogs.length === 0" class="logs-empty">
                暂无日志
              </div>
              <div
                v-for="(log, idx) in parsedLogs"
                :key="idx"
                class="log-line"
                :style="{ color: getLogColor(log.level) }"
              >
                {{ log.text }}
              </div>
            </div>
          </div>

          <!-- 回滚信息 -->
          <div v-if="currentRecord.rollback_info" class="rollback-section">
            <div class="section-title">
              <el-icon color="#909399"><Back /></el-icon>
              回滚信息
            </div>
            <div class="rollback-box">{{ currentRecord.rollback_info }}</div>
          </div>
        </template>
      </div>

      <template #footer>
        <el-button @click="detailVisible = false">关闭</el-button>
        <el-button
          v-if="currentRecord?.can_rollback"
          type="warning"
          :icon="Back"
          :loading="rollingBackId === currentRecord?.id"
          @click="handleRollback(currentRecord)"
        >
          回滚部署
        </el-button>
      </template>
    </el-dialog>
  </div>
</template>

<style scoped>
.deploy-history {
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

.toolbar-left {
  display: flex;
  align-items: center;
  gap: 8px;
  flex-wrap: wrap;
}

.toolbar-right {
  display: flex;
  align-items: center;
  gap: 8px;
}

.table-card {
  border-radius: 8px;
}

.pagination {
  display: flex;
  justify-content: flex-end;
  margin-top: 16px;
}

/* 详情弹窗 */
.section-title {
  display: flex;
  align-items: center;
  gap: 6px;
  font-size: 14px;
  font-weight: 600;
  color: #303133;
  margin: 20px 0 12px;
}

.log-count {
  font-size: 12px;
  color: #909399;
  font-weight: 400;
}

/* 错误信息 */
.error-section {
  margin-top: 20px;
}

.error-box {
  padding: 12px 16px;
  background-color: #fef0f0;
  border: 1px solid #f56c6c;
  border-radius: 6px;
  font-size: 13px;
  color: #f56c6c;
  line-height: 1.6;
  word-break: break-all;
}

/* 步骤时间线 */
.steps-section {
  margin-top: 20px;
}

.step-timeline-item {
  display: flex;
  align-items: center;
  gap: 8px;
}

.step-timeline-name {
  font-weight: 600;
  color: #303133;
}

.step-timeline-duration {
  font-size: 12px;
  color: #909399;
}

.step-timeline-command {
  margin-top: 4px;
  font-family: 'Consolas', 'Monaco', monospace;
  font-size: 12px;
  color: #606266;
  background-color: #f5f7fa;
  padding: 4px 8px;
  border-radius: 4px;
}

.step-timeline-message {
  margin-top: 4px;
  font-size: 13px;
  color: #606266;
}

/* AI 建议 */
.ai-section {
  margin-top: 20px;
}

.ai-box {
  padding: 12px 16px;
  background-color: #f0f9eb;
  border: 1px solid #67c23a;
  border-radius: 6px;
  font-size: 13px;
  color: #606266;
  line-height: 1.6;
  white-space: pre-wrap;
}

/* 失败时的错误分析样式（橙色基调） */
.ai-box-error {
  background-color: #fdf6ec;
  border-color: #e6a23c;
  color: #b88230;
}

/* 日志容器 */
.logs-section {
  margin-top: 20px;
}

.logs-container {
  max-height: 400px;
  overflow-y: auto;
  background-color: #1e1e1e;
  border-radius: 6px;
  padding: 12px 16px;
  font-family: 'Consolas', 'Monaco', 'Courier New', monospace;
  font-size: 13px;
  line-height: 1.7;
}

.logs-empty {
  color: #606266;
  text-align: center;
  padding: 40px 0;
}

.log-line {
  white-space: pre-wrap;
  word-break: break-all;
}

/* 回滚信息 */
.rollback-section {
  margin-top: 20px;
}

.rollback-box {
  padding: 12px 16px;
  background-color: #f4f4f5;
  border: 1px solid #909399;
  border-radius: 6px;
  font-size: 13px;
  color: #606266;
  line-height: 1.6;
  white-space: pre-wrap;
  word-break: break-all;
}

/* 滚动条 */
.logs-container::-webkit-scrollbar {
  width: 8px;
}

.logs-container::-webkit-scrollbar-track {
  background-color: #2d2d2d;
}

.logs-container::-webkit-scrollbar-thumb {
  background-color: #555;
  border-radius: 4px;
}

.logs-container::-webkit-scrollbar-thumb:hover {
  background-color: #777;
}
</style>
