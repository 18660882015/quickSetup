import service from './index'

// 生成 AI 部署计划（预览模式）
export function getPlan(data) {
  return service.post('/deploy/plan', data)
}

// 执行部署
export function executeDeploy(data) {
  return service.post('/deploy/execute', data)
}

// 查询部署任务状态
export function getTaskStatus(id) {
  return service.get(`/deploy/task/${id}`)
}

// 回滚部署
export function rollbackDeploy(id) {
  return service.post(`/deploy/rollback/${id}`)
}

// 获取部署历史列表
export function getHistory(params) {
  return service.get('/deploy/history', { params })
}
