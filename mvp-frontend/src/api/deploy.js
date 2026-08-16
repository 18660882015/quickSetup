import service from './index'

// 生成 AI 部署计划（预览模式）
export function getPlan(data) {
  return service.post('/deploy/plan', data)
}

// 执行部署
export function executeDeploy(data) {
  return service.post('/deploy/execute', data)
}

// 快速部署（智能识别 + 自动配置）
export function quickDeploy(data) {
  return service.post('/deploy/quick', data)
}

// 批量部署（按顺序执行）
export function batchDeploy(data) {
  return service.post('/deploy/batch', data)
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

// 环境模板列表
export function getEnvTemplates() {
  return service.get('/env-templates')
}

// 保存自定义环境模板
export function saveEnvTemplate(data) {
  return service.post('/env-templates', data)
}

// 删除自定义环境模板
export function deleteEnvTemplate(name) {
  return service.delete(`/env-templates/${encodeURIComponent(name)}`)
}
