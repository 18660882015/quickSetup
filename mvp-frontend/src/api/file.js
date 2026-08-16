import service from './index'

// 扫描可用项目列表
export function scanProjects() {
  return service.get('/files/scan')
}

// 列出指定项目下的文件
export function listFiles(project) {
  return service.get('/files/list', { params: { project } })
}

// 上传文件（multipart/form-data）
export function uploadFile(formData) {
  return service.post('/files/upload', formData, {
    headers: { 'Content-Type': 'multipart/form-data' },
    timeout: 0
  })
}

// 删除文件
export function deleteFile(path) {
  return service.delete(`/files/${encodeURIComponent(path)}`)
}
