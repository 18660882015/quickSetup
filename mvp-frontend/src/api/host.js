import service from './index'

// 获取主机列表
export function getHosts() {
  return service.get('/hosts')
}

// 新增主机
export function createHost(data) {
  return service.post('/hosts', data)
}

// 更新主机
export function updateHost(id, data) {
  return service.put(`/hosts/${id}`, data)
}

// 删除主机
export function deleteHost(id) {
  return service.delete(`/hosts/${id}`)
}

// 测试主机连接
export function testHost(id) {
  return service.post(`/hosts/${id}/test`)
}

// 采集主机参数信息
export function inspectHost(id) {
  return service.get(`/hosts/${id}/inspect`)
}
