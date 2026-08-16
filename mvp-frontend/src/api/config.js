import service from './index'

// 获取所有系统配置
export function getConfigs() {
  return service.get('/configs')
}

// 更新指定配置项
export function updateConfig(key, data) {
  return service.put(`/configs/${encodeURIComponent(key)}`, data)
}

// 测试钉钉推送（可传入自定义测试消息）
export function testDingtalk(message) {
  const data = message ? { message } : {}
  return service.post('/configs/test-dingtalk', data)
}

// 测试 AI 接口连通性（可传入自定义测试消息）
export function testAI(message) {
  const data = message ? { message } : {}
  return service.post('/configs/test-ai', data)
}
