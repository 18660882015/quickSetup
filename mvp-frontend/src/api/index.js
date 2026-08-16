import axios from 'axios'
import { ElMessage } from 'element-plus'
import router from '@/router'

const service = axios.create({
  baseURL: '/api/v1',
  timeout: 30000,
  headers: {
    'Content-Type': 'application/json'
  }
})

// 请求拦截器：自动添加 Bearer Token
service.interceptors.request.use(
  (config) => {
    const token = localStorage.getItem('token')
    if (token) {
      config.headers['Authorization'] = `Bearer ${token}`
    }
    return config
  },
  (error) => Promise.reject(error)
)

// 响应拦截器：统一处理 {code, msg, data} 格式
service.interceptors.response.use(
  (response) => {
    const res = response.data
    // 非 0 视为业务错误
    if (res.code !== 0) {
      ElMessage.error(res.msg || '请求失败')
      // 401 未授权，跳转登录
      if (res.code === 401) {
        handleUnauthorized()
      }
      return Promise.reject(new Error(res.msg || 'Error'))
    }
    return res
  },
  (error) => {
    const status = error.response?.status
    const msg = error.response?.data?.msg || error.message || '网络错误'
    if (status === 401) {
      handleUnauthorized()
    }
    ElMessage.error(msg)
    return Promise.reject(error)
  }
)

function handleUnauthorized() {
  localStorage.removeItem('token')
  localStorage.removeItem('user')
  const current = router.currentRoute.value?.fullPath
  if (current && current !== '/login') {
    router.replace({
      path: '/login',
      query: { redirect: current }
    })
  }
}

export default service
