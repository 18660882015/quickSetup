import service from './index'

// 登录
export function login(data) {
  return service.post('/auth/login', data)
}

// 获取当前用户信息
export function getMe() {
  return service.get('/auth/me')
}
