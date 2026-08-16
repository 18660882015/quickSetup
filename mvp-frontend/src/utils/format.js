/**
 * 时间格式化
 * @param {string|number|Date} time 时间值
 * @param {string} fmt 格式模板，默认 YYYY-MM-DD HH:mm:ss
 * @returns {string}
 */
export function formatTime(time, fmt = 'YYYY-MM-DD HH:mm:ss') {
  if (!time) return '-'
  const d = new Date(time)
  if (isNaN(d.getTime())) return '-'
  const pad = (n) => String(n).padStart(2, '0')
  const map = {
    YYYY: d.getFullYear(),
    MM: pad(d.getMonth() + 1),
    DD: pad(d.getDate()),
    HH: pad(d.getHours()),
    mm: pad(d.getMinutes()),
    ss: pad(d.getSeconds())
  }
  return fmt.replace(/YYYY|MM|DD|HH|mm|ss/g, (m) => map[m])
}

/**
 * 文件大小格式化
 * @param {number} bytes 字节数
 * @returns {string}
 */
export function formatFileSize(bytes) {
  if (bytes == null || isNaN(bytes)) return '-'
  if (bytes === 0) return '0 B'
  const units = ['B', 'KB', 'MB', 'GB', 'TB']
  const i = Math.min(
    Math.floor(Math.log(bytes) / Math.log(1024)),
    units.length - 1
  )
  const size = (bytes / Math.pow(1024, i)).toFixed(2)
  return `${size} ${units[i]}`
}

/**
 * 部署/主机状态 -> Element Plus 标签颜色类型
 * @param {string} status 状态值
 * @returns {string} success|warning|danger|info|primary
 */
export function statusColor(status) {
  const map = {
    // 主机状态
    online: 'success',
    offline: 'danger',
    unknown: 'info',
    // 部署状态
    pending: 'info',
    running: 'warning',
    success: 'success',
    failed: 'danger',
    rolled_back: 'info',
    cancelled: 'info'
  }
  return map[status] || 'info'
}

/**
 * 状态值 -> 中文文本
 * @param {string} status 状态值
 * @returns {string}
 */
export function statusText(status) {
  const map = {
    online: '在线',
    offline: '离线',
    unknown: '未知',
    pending: '等待中',
    running: '执行中',
    success: '成功',
    failed: '失败',
    rolled_back: '已回滚',
    cancelled: '已取消'
  }
  return map[status] || status || '-'
}

/**
 * 日志级别 -> 颜色
 * @param {string} level info|warn|error|success
 * @returns {string}
 */
export function logLevelColor(level) {
  const map = {
    info: '#409eff',
    warn: '#e6a23c',
    error: '#f56c6c',
    success: '#67c23a'
  }
  return map[level] || '#909399'
}

/**
 * 持续时长格式化（秒 -> xh xm xs）
 * @param {number} seconds 秒
 * @returns {string}
 */
export function formatDuration(seconds) {
  if (seconds == null || isNaN(seconds)) return '-'
  if (seconds < 1) return `${Math.round(seconds * 1000)} ms`
  const h = Math.floor(seconds / 3600)
  const m = Math.floor((seconds % 3600) / 60)
  const s = Math.floor(seconds % 60)
  const parts = []
  if (h) parts.push(`${h}h`)
  if (m) parts.push(`${m}m`)
  parts.push(`${s}s`)
  return parts.join(' ')
}
