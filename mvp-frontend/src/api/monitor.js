import service from './index'

// 获取最新监控数据（所有主机）
export function getLatestMonitor() {
  return service.get('/monitor/latest')
}

// 获取指定主机的监控历史
export function getMonitorHistory(hostId, params) {
  return service.get(`/monitor/history/${hostId}`, { params })
}

// 获取每日监控报告
export function getDailyReport() {
  return service.get('/monitor/daily-report')
}
