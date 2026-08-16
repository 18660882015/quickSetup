<script setup>
import { ref, reactive, computed, onMounted } from 'vue'
import { useRouter } from 'vue-router'
import { Monitor, Upload, Clock, Check, Cpu, Warning } from '@element-plus/icons-vue'
import { getHistory } from '@/api/deploy'
import { getHosts } from '@/api/host'
import { getConfigs } from '@/api/config'
import { getLatestMonitor } from '@/api/monitor'
import { formatTime, statusColor, statusText } from '@/utils/format'

const router = useRouter()

const stats = reactive({
  hostTotal: 0,
  hostOnline: 0,
  todayDeploys: 0,
  successRate: 0
})

const hosts = ref([])
const recentDeploys = ref([])
const monitorList = ref([])
const loading = ref(false)

// 监控告警阈值（从系统配置读取，带默认值）
const thresholds = reactive({
  cpu: 80,
  memory: 80,
  disk: 90
})

const statCards = [
  { key: 'hostTotal', title: '主机总数', icon: Monitor, color: '#409eff' },
  { key: 'hostOnline', title: '在线主机', icon: Check, color: '#67c23a' },
  { key: 'todayDeploys', title: '今日部署', icon: Upload, color: '#e6a23c' },
  { key: 'successRate', title: '成功率', icon: Clock, color: '#909399', suffix: '%' }
]

// 主机ID -> 最新监控数据 的映射
const monitorMap = computed(() => {
  const map = {}
  monitorList.value.forEach((m) => {
    const id = m.host_id ?? m.hostId
    if (id != null) map[id] = m
  })
  return map
})

// 在线主机列表（用于监控展示）
const onlineHosts = computed(() =>
  hosts.value.filter((h) => h.status === 'online')
)

// 告警主机数量
const alertHostCount = computed(() => {
  return onlineHosts.value.filter((h) => {
    const m = monitorMap.value[h.id]
    if (!m) return false
    return isAlert(m, 'cpu') || isAlert(m, 'memory') || isAlert(m, 'disk')
  }).length
})

// 使用率数值容错处理
function usageValue(val) {
  const n = Number(val)
  return isNaN(n) ? 0 : n
}

// 是否超过阈值（告警）
function isAlert(monitor, type) {
  if (!monitor) return false
  const val = usageValue(monitor[`${type}_usage`])
  return val >= thresholds[type]
}

// 进度条颜色：超阈值红色，接近阈值(差10)橙色，否则绿色
function usageColor(monitor, type) {
  if (!monitor) return '#909399'
  const val = usageValue(monitor[`${type}_usage`])
  const threshold = thresholds[type]
  if (val >= threshold) return '#f56c6c'
  if (val >= threshold - 10) return '#e6a23c'
  return '#67c23a'
}

function hostDisplayName(host) {
  return host.name || host.ip || `主机#${host.id}`
}

const fetchDashboard = async () => {
  loading.value = true
  try {
    const [hostRes, historyRes, monitorRes, configRes] = await Promise.allSettled([
      getHosts(),
      getHistory({ page: 1, page_size: 5 }),
      getLatestMonitor(),
      getConfigs()
    ])

    if (hostRes.status === 'fulfilled') {
      const list = hostRes.value.data || []
      hosts.value = list
      stats.hostTotal = list.length
      stats.hostOnline = list.filter((h) => h.status === 'online').length
    }

    if (historyRes.status === 'fulfilled') {
      const payload = historyRes.value.data
      const list = Array.isArray(payload)
        ? payload
        : payload?.list || payload?.records || []
      recentDeploys.value = list.slice(0, 5)

      const todayStr = new Date().toDateString()
      const todayList = recentDeploys.value.filter(
        (d) => d.created_at && new Date(d.created_at).toDateString() === todayStr
      )
      stats.todayDeploys = todayList.length

      const total = recentDeploys.value.length
      const successCount = recentDeploys.value.filter(
        (d) => d.execute_status === 'success'
      ).length
      stats.successRate = total ? Math.round((successCount / total) * 100) : 0
    }

    if (monitorRes.status === 'fulfilled') {
      const payload = monitorRes.value.data
      monitorList.value = Array.isArray(payload)
        ? payload
        : payload?.list || payload?.records || []
    }

    if (configRes.status === 'fulfilled') {
      const list = configRes.value.data || []
      const byKey = {}
      list.forEach((c) => {
        byKey[c.config_key] = c.config_value
      })
      thresholds.cpu = Number(byKey.cpu_threshold) || 80
      thresholds.memory = Number(byKey.memory_threshold) || 80
      thresholds.disk = Number(byKey.disk_threshold) || 90
    }
  } finally {
    loading.value = false
  }
}

const goDeploy = () => router.push('/deploy')
const goHosts = () => router.push('/hosts')
const goHistory = () => router.push('/history')
const goConfig = () => router.push('/config')

onMounted(fetchDashboard)
</script>

<template>
  <div class="dashboard" v-loading="loading">
    <!-- 统计卡片 -->
    <el-row :gutter="20" class="stat-row">
      <el-col
        v-for="card in statCards"
        :key="card.key"
        :xs="12"
        :sm="12"
        :md="6"
      >
        <el-card shadow="hover" class="stat-card">
          <div class="stat-body">
            <div class="stat-icon" :style="{ backgroundColor: card.color }">
              <el-icon :size="26"><component :is="card.icon" /></el-icon>
            </div>
            <div class="stat-info">
              <div class="stat-value">
                {{ stats[card.key] }}{{ card.suffix || '' }}
              </div>
              <div class="stat-title">{{ card.title }}</div>
            </div>
          </div>
        </el-card>
      </el-col>
    </el-row>

    <!-- 快速入口 -->
    <el-card shadow="never" class="section-card">
      <template #header>
        <div class="section-header">
          <span>快速入口</span>
        </div>
      </template>
      <div class="quick-entry">
        <el-button type="primary" :icon="Upload" @click="goDeploy">发起部署</el-button>
        <el-button :icon="Monitor" @click="goHosts">主机管理</el-button>
        <el-button :icon="Clock" @click="goHistory">部署历史</el-button>
        <el-button :icon="Cpu" @click="goConfig">系统配置</el-button>
      </div>
    </el-card>

    <!-- 监控状态 -->
    <el-card shadow="never" class="section-card">
      <template #header>
        <div class="section-header">
          <span>
            <el-icon class="header-icon"><Cpu /></el-icon>
            监控状态
          </span>
          <div class="monitor-summary">
            <el-tag v-if="alertHostCount > 0" type="danger" size="small">
              <el-icon><Warning /></el-icon>
              {{ alertHostCount }} 台告警
            </el-tag>
            <el-tag v-else type="success" size="small">无告警</el-tag>
            <span class="threshold-info">
              阈值：CPU {{ thresholds.cpu }}% / 内存 {{ thresholds.memory }}% / 磁盘 {{ thresholds.disk }}%
            </span>
          </div>
        </div>
      </template>

      <div v-if="onlineHosts.length === 0" class="monitor-empty">
        暂无在线主机
      </div>

      <div v-else class="monitor-grid">
        <div v-for="host in onlineHosts" :key="host.id" class="monitor-item">
          <div class="monitor-host-header">
            <span class="monitor-host-name">{{ hostDisplayName(host) }}</span>
            <span class="monitor-host-ip">{{ host.ip }}</span>
          </div>

          <template v-if="monitorMap[host.id]">
            <div class="metric-row">
              <div class="metric-label">
                CPU
                <span class="metric-value" :class="{ alert: isAlert(monitorMap[host.id], 'cpu') }">
                  {{ usageValue(monitorMap[host.id].cpu_usage).toFixed(1) }}%
                </span>
              </div>
              <el-progress
                :percentage="Math.min(usageValue(monitorMap[host.id].cpu_usage), 100)"
                :color="usageColor(monitorMap[host.id], 'cpu')"
                :stroke-width="14"
                :show-text="false"
              />
            </div>

            <div class="metric-row">
              <div class="metric-label">
                内存
                <span class="metric-value" :class="{ alert: isAlert(monitorMap[host.id], 'memory') }">
                  {{ usageValue(monitorMap[host.id].memory_usage).toFixed(1) }}%
                </span>
              </div>
              <el-progress
                :percentage="Math.min(usageValue(monitorMap[host.id].memory_usage), 100)"
                :color="usageColor(monitorMap[host.id], 'memory')"
                :stroke-width="14"
                :show-text="false"
              />
            </div>

            <div class="metric-row">
              <div class="metric-label">
                磁盘
                <span class="metric-value" :class="{ alert: isAlert(monitorMap[host.id], 'disk') }">
                  {{ usageValue(monitorMap[host.id].disk_usage).toFixed(1) }}%
                </span>
              </div>
              <el-progress
                :percentage="Math.min(usageValue(monitorMap[host.id].disk_usage), 100)"
                :color="usageColor(monitorMap[host.id], 'disk')"
                :stroke-width="14"
                :show-text="false"
              />
            </div>

            <div v-if="monitorMap[host.id].created_at" class="monitor-time">
              采集时间：{{ formatTime(monitorMap[host.id].created_at) }}
            </div>
          </template>

          <div v-else class="monitor-no-data">
            暂无监控数据
          </div>
        </div>
      </div>
    </el-card>

    <!-- 最近部署记录 -->
    <el-card shadow="never" class="section-card">
      <template #header>
        <div class="section-header">
          <span>最近部署记录</span>
          <el-button type="primary" link @click="goHistory">查看全部</el-button>
        </div>
      </template>
      <el-table :data="recentDeploys" stripe style="width: 100%" empty-text="暂无部署记录">
        <el-table-column prop="project_name" label="项目" min-width="140" show-overflow-tooltip />
        <el-table-column label="状态" width="110">
          <template #default="{ row }">
            <el-tag :type="statusColor(row.execute_status)" size="small">
              {{ statusText(row.execute_status) }}
            </el-tag>
          </template>
        </el-table-column>
        <el-table-column prop="env_type" label="环境" width="90" />
        <el-table-column prop="operator" label="操作人" width="110" />
        <el-table-column label="部署时间" width="180">
          <template #default="{ row }">
            {{ formatTime(row.created_at) }}
          </template>
        </el-table-column>
      </el-table>
    </el-card>
  </div>
</template>

<style scoped>
.dashboard {
  display: flex;
  flex-direction: column;
  gap: 20px;
}

.stat-row {
  margin-bottom: 0;
}

.stat-card {
  border-radius: 8px;
}

.stat-body {
  display: flex;
  align-items: center;
  gap: 16px;
}

.stat-icon {
  width: 56px;
  height: 56px;
  border-radius: 10px;
  display: flex;
  align-items: center;
  justify-content: center;
  color: #fff;
  flex-shrink: 0;
}

.stat-value {
  font-size: 26px;
  font-weight: 600;
  color: #303133;
  line-height: 1.2;
}

.stat-title {
  font-size: 13px;
  color: #909399;
  margin-top: 4px;
}

.section-card {
  border-radius: 8px;
}

.section-header {
  display: flex;
  align-items: center;
  justify-content: space-between;
  font-weight: 600;
}

.header-icon {
  vertical-align: middle;
  margin-right: 4px;
}

.quick-entry {
  display: flex;
  flex-wrap: wrap;
  gap: 12px;
}

/* 监控状态 */
.monitor-summary {
  display: flex;
  align-items: center;
  gap: 12px;
}

.threshold-info {
  font-size: 12px;
  color: #909399;
  font-weight: 400;
}

.monitor-empty {
  text-align: center;
  color: #909399;
  padding: 32px 0;
}

.monitor-grid {
  display: grid;
  grid-template-columns: repeat(auto-fill, minmax(320px, 1fr));
  gap: 16px;
}

.monitor-item {
  border: 1px solid #ebeef5;
  border-radius: 8px;
  padding: 14px 16px;
  background-color: #fafafa;
}

.monitor-host-header {
  display: flex;
  align-items: center;
  justify-content: space-between;
  margin-bottom: 12px;
  padding-bottom: 8px;
  border-bottom: 1px dashed #ebeef5;
}

.monitor-host-name {
  font-weight: 600;
  color: #303133;
}

.monitor-host-ip {
  font-size: 12px;
  color: #909399;
}

.metric-row {
  margin-bottom: 10px;
}

.metric-label {
  display: flex;
  align-items: center;
  justify-content: space-between;
  font-size: 13px;
  color: #606266;
  margin-bottom: 4px;
}

.metric-value {
  font-weight: 600;
  color: #303133;
}

.metric-value.alert {
  color: #f56c6c;
}

.monitor-time {
  margin-top: 8px;
  font-size: 12px;
  color: #909399;
}

.monitor-no-data {
  text-align: center;
  color: #c0c4cc;
  font-size: 13px;
  padding: 16px 0;
}
</style>
